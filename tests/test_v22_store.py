"""tests/test_v22_store.py —— V22-01 酒馆数据层 · 纯函数断言（零 Qt / 无墙钟 / tmp_path 隔离）。

覆盖 ``docs/design-v22.md`` §4.4 的原子写与**坏档恢复矩阵 L0–L6**、§5.4-2/3/4/6/7 的
「数据不乱」机制，以及 §4.5 的「与既有业务数据隔离」：

    * L0 缺文件 → 类默认且不崩、**不写盘**；
    * L1 缺键 → 补默认；L2 类型错 / 顶层非 object → 回落且不崩；
    * L3 旧版本 → 迁移归位；L4 新版本 → 只读加载、**不写回**；
    * L5 截断 JSON → 走快照；L6 截断 + 快照也坏 → 空档 + 隔离坏档；
    * 原子写：写后可解析、内容正确；**写失败时原档不被破坏**；
    * 快照轮转：连写 N 次后快照数量符合 :data:`MAX_BACKUPS` 策略；
    * 只读写 ``tavern.json``（记录被写入的路径集合断言）；
    * 局 / journal 最小内存态 API；零 Qt 证据（子进程 + 屏蔽 finder）。

所有用例只用 ``tmp_path`` 隔离，绝不写真实 ``~/.maid_coder``；不建 ``QApplication``。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

import gui.tavern.store as store_mod
from gui.tavern import (
    SCHEMA_VERSION,
    SETTING_DEFAULTS,
    TOP_LEVEL_KEYS,
    TavernDataError,
    TavernStoreError,
    default_tavern,
    new_play,
)
from gui.tavern.store import (
    MAX_BACKUPS,
    TavernStore,
)

_TS = "2026-09-15T20:00:00+08:00"
_JOURNAL_DEFAULT = {"seen_endings": [], "unlocked_entries": [], "first_seen": {}}


# ---------------------------------------------------------------------------
# 辅助
# ---------------------------------------------------------------------------

def _make_store(tmp_path: Path) -> TavernStore:
    return TavernStore(base_dir=tmp_path / "tavern")


def _write_main(store: TavernStore, obj) -> None:
    store.path.parent.mkdir(parents=True, exist_ok=True)
    store.path.write_text(
        obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False),
        encoding="utf-8",
    )


def _good_tavern() -> dict:
    d = default_tavern(now=_TS)
    d["plays"] = [new_play("lantern", "灯笼还亮着", 1731845, play_id="p1", now=_TS)]
    d["active_play_id"] = "p1"
    return d


# ===========================================================================
# L0 / L1 / L2 —— 缺文件 / 缺键 / 类型错
# ===========================================================================

def test_load_missing_file_returns_default_and_no_write(tmp_path):
    """L0：文件不存在 → 类默认；且 **load 不写盘**（单写点纪律）。"""
    store = _make_store(tmp_path)
    data = store.load()
    assert set(data) == set(TOP_LEVEL_KEYS)
    assert data["schema_version"] == SCHEMA_VERSION
    assert data["plays"] == []
    assert store.read_only is False
    # 加载绝不在磁盘上留痕
    assert not store.path.exists()


def test_load_missing_keys_fill_defaults(tmp_path):
    """L1：缺键 → 读时迁移补默认（零迁移前提）。"""
    store = _make_store(tmp_path)
    _write_main(store, {"schema_version": 1, "plays": []})
    data = store.load()
    assert set(data) == set(TOP_LEVEL_KEYS)
    assert data["settings"] == SETTING_DEFAULTS
    assert data["library"] == {"books": [], "bound_book_ids": [], "cast": []}
    assert data["journal"] == _JOURNAL_DEFAULT
    assert data["active_play_id"] == ""


def test_load_type_error_fields_fall_back(tmp_path):
    """L2：字段类型错（plays 非 list / library 非 dict / active_play_id 非 str）→ 回落默认。"""
    store = _make_store(tmp_path)
    _write_main(store, {
        "schema_version": 1,
        "plays": "oops",
        "library": [],
        "active_play_id": 123,
        "journal": 42,
    })
    data = store.load()
    assert data["plays"] == []
    assert data["library"] == {"books": [], "bound_book_ids": [], "cast": []}
    assert data["active_play_id"] == ""
    assert data["journal"] == _JOURNAL_DEFAULT


def test_load_non_object_top_level(tmp_path):
    """L2：顶层非 object（list / str / null）→ 回落类默认且不崩。"""
    store = _make_store(tmp_path)
    for payload in ("[1, 2, 3]", "\"oops\"", "null", "42"):
        _write_main(store, payload)
        data = store.load()
        assert set(data) == set(TOP_LEVEL_KEYS), payload
        assert data["schema_version"] == SCHEMA_VERSION


# ===========================================================================
# L3 / L4 —— 旧版本迁移 / 新版本只读不写回
# ===========================================================================

def test_load_old_version_migrates(tmp_path):
    """L3：旧 ``schema_version`` → ``migrate`` 归位到当前版本（不丢既有数据）。"""
    store = _make_store(tmp_path)
    _write_main(store, {"schema_version": 0, "plays": [{"play_id": "p1", "turn": 3}]})
    data = store.load()
    assert data["schema_version"] == SCHEMA_VERSION
    assert data["plays"][0]["play_id"] == "p1"
    assert data["plays"][0]["turn"] == 3
    assert store.read_only is False


def test_load_missing_schema_version_normalized(tmp_path):
    """L1/L3：缺 ``schema_version`` 亦归位当前版本。"""
    store = _make_store(tmp_path)
    _write_main(store, {"plays": []})
    data = store.load()
    assert data["schema_version"] == SCHEMA_VERSION


def test_load_new_version_read_only_no_writeback(tmp_path, monkeypatch):
    """L4：``schema_version`` 高于当前 → 只读加载，**断言加载后未发生任何写操作**。"""
    store = _make_store(tmp_path)
    future = SCHEMA_VERSION + 5
    _write_main(store, {"schema_version": future, "plays": []})
    before = store.path.read_text(encoding="utf-8")

    writes: list[str] = []
    monkeypatch.setattr(store_mod, "_atomic_write_json",
                        lambda path, data: writes.append(str(path)))

    data = store.load()
    assert data["schema_version"] == future          # 不降级
    assert store.read_only is True                   # 打了只读标
    assert writes == []                              # 未发生写操作
    assert store.path.read_text(encoding="utf-8") == before   # 主档未被改写


def test_save_rejected_when_read_only(tmp_path):
    """L4：只读档 ``save`` 被拒（本期不写回更高版本），原档不动。"""
    store = _make_store(tmp_path)
    _write_main(store, {"schema_version": SCHEMA_VERSION + 1, "plays": []})
    before = store.path.read_text(encoding="utf-8")
    data = store.load()
    with pytest.raises(TavernStoreError) as ei:
        store.save(data)
    assert ei.value.reason == "read_only"
    assert store.path.read_text(encoding="utf-8") == before


# ===========================================================================
# L5 / L6 —— 截断走快照 / 截断 + 快照也坏 → 空档
# ===========================================================================

def test_load_truncated_uses_latest_backup(tmp_path):
    """L5：主档 JSON 截断 → 从 ``tavern.json.bak.1`` 恢复。"""
    store = _make_store(tmp_path)
    store.path.parent.mkdir(parents=True, exist_ok=True)
    store.path.write_text('{"schema_version": 1, "plays": [', encoding="utf-8")   # 截断
    store._backup_path(1).write_text(
        json.dumps(_good_tavern(), ensure_ascii=False), encoding="utf-8")

    data = store.load()
    assert data["plays"][0]["play_id"] == "p1"
    assert data["active_play_id"] == "p1"


def test_load_truncated_falls_to_second_backup(tmp_path):
    """L5 纵深：``.bak.1`` 也坏 → 继续尝试 ``.bak.2``。"""
    store = _make_store(tmp_path)
    store.path.parent.mkdir(parents=True, exist_ok=True)
    store.path.write_text('{broken', encoding="utf-8")
    store._backup_path(1).write_text('{also broken', encoding="utf-8")
    store._backup_path(2).write_text(
        json.dumps(_good_tavern(), ensure_ascii=False), encoding="utf-8")

    data = store.load()
    assert data["plays"][0]["play_id"] == "p1"


def test_load_truncated_and_backup_broken_quarantines(tmp_path):
    """L6：截断 + 快照也坏 → 空档；损坏主档改名保留（``*.corrupt``）。"""
    store = _make_store(tmp_path)
    store.path.parent.mkdir(parents=True, exist_ok=True)
    store.path.write_text('{broken', encoding="utf-8")
    store._backup_path(1).write_text('{also broken', encoding="utf-8")

    data = store.load()
    assert set(data) == set(TOP_LEVEL_KEYS)
    assert data["plays"] == []
    assert data["schema_version"] == SCHEMA_VERSION
    # 主档被隔离（不静默删除）
    assert not store.path.exists()
    assert (store.path.parent / "tavern.json.corrupt").exists()


# ===========================================================================
# 原子写 —— 成功 / 建父目录 / 失败不破坏原档
# ===========================================================================

def test_save_roundtrip_parseable_and_no_tmp(tmp_path):
    """原子写：写后可解析、内容正确、无 ``.tmp`` 残留。"""
    store = _make_store(tmp_path)
    store.save(_good_tavern())

    assert store.path.exists()
    raw = json.loads(store.path.read_text(encoding="utf-8"))
    assert raw["plays"][0]["play_id"] == "p1"
    assert raw["active_play_id"] == "p1"
    assert isinstance(raw["meta"]["updated_at"], str) and raw["meta"]["updated_at"]
    # 原子写完成即无 .tmp 残留
    assert not store.path.with_name(store.path.name + ".tmp").exists()


def test_save_creates_missing_parent_dirs(tmp_path):
    """``_atomic_write_json`` 不建父目录 → save 必须先 ``mkdir(parents=True)``。"""
    store = TavernStore(base_dir=tmp_path / "deep" / "nested" / "tavern")
    assert not store.path.parent.exists()
    store.save(default_tavern(now=_TS))
    assert store.path.exists()


def test_save_serialization_failure_preserves_original(tmp_path):
    """预校验不可序列化 → 抛错且**原档不动、不轮转**。"""
    store = _make_store(tmp_path)
    store.save(_good_tavern())
    before = store.path.read_text(encoding="utf-8")

    bad = _good_tavern()
    bad["none_serializable"] = object()   # json.dumps 会失败
    with pytest.raises(TavernStoreError) as ei:
        store.save(bad)
    assert ei.value.reason == "not_serializable"
    assert store.path.read_text(encoding="utf-8") == before
    assert not store._backup_path(1).exists()   # 未轮转


def test_save_write_failure_preserves_original(tmp_path, monkeypatch):
    """注入写异常（``_atomic_write_json`` 抛 OSError）→ 抛 ``TavernStoreError`` 且原档完好。"""
    store = _make_store(tmp_path)
    store.save(_good_tavern())
    before = store.path.read_text(encoding="utf-8")

    def _boom(path, data):
        raise OSError("disk full")

    monkeypatch.setattr(store_mod, "_atomic_write_json", _boom)

    new = _good_tavern()
    new["plays"][0]["title"] = "换了个标题"
    with pytest.raises(TavernStoreError) as ei:
        store.save(new)
    assert ei.value.reason == "write_failed"
    # 原档字节级不变
    assert store.path.read_text(encoding="utf-8") == before
    # 轮转已发生（快照=写前内容），但主档未被破坏
    assert json.loads(store._backup_path(1).read_text(encoding="utf-8"))["plays"][0]["play_id"] == "p1"


def test_save_bad_payload_type(tmp_path):
    """入参非 dict → 抛 ``TavernStoreError``（不落盘）。"""
    store = _make_store(tmp_path)
    with pytest.raises(TavernStoreError) as ei:
        store.save(["not", "a", "dict"])  # type: ignore[arg-type]
    assert ei.value.reason == "bad_payload"
    assert not store.path.exists()


# ===========================================================================
# 快照轮转 —— 数量符合策略 / .bak.1 = 上一版
# ===========================================================================

def test_backup_rotation_keeps_max_and_bak1_is_previous(tmp_path):
    """连写 N 次后快照数量 == ``MAX_BACKUPS``；``.bak.1`` 恒为上上一版内容。"""
    store = _make_store(tmp_path)
    total = MAX_BACKUPS + 3
    for i in range(total):
        data = default_tavern(now=_TS)
        data["plays"] = [new_play("lantern", f"t{i}", i, play_id=f"p{i}", now=_TS)]
        store.save(data)

    baks = sorted(p for p in store.path.parent.iterdir() if ".bak." in p.name)
    assert len(baks) == MAX_BACKUPS
    # .bak.1 = 倒数第二次写入的内容
    assert json.loads(store._backup_path(1).read_text(encoding="utf-8"))["plays"][0]["play_id"] \
        == f"p{total - 2}"
    # .bak.MAX = 最旧保留的一份
    assert json.loads(store._backup_path(MAX_BACKUPS).read_text(encoding="utf-8"))["plays"][0]["play_id"] \
        == f"p{total - 1 - MAX_BACKUPS}"


# ===========================================================================
# 隔离 —— 只读写 tavern.json，绝不碰别的业务数据
# ===========================================================================

def test_store_touches_only_tavern_json(tmp_path, monkeypatch):
    """记录被写入的路径集合：仅 ``tavern.json``；兄弟业务档零触碰。"""
    home = tmp_path
    siblings = {
        "companion.json": '{"schema_version": 1}',
        "user_memory.json": "{}",
        "intimacy.json": "{}",
    }
    for name, content in siblings.items():
        (home / name).write_text(content, encoding="utf-8")
    (home / "sessions").mkdir(exist_ok=True)
    (home / "sessions" / "s1.json").write_text("{}", encoding="utf-8")

    touched: list[str] = []
    real = store_mod._atomic_write_json

    def _spy(path, data):
        touched.append(os.path.basename(str(path)))
        return real(path, data)

    monkeypatch.setattr(store_mod, "_atomic_write_json", _spy)

    store = TavernStore(base_dir=home / "tavern")
    store.save(_good_tavern())
    store.load()

    assert touched == ["tavern.json"]
    # 别人的业务档内容不变
    for name, content in siblings.items():
        assert (home / name).read_text(encoding="utf-8") == content
    assert (home / "sessions" / "s1.json").read_text(encoding="utf-8") == "{}"
    # 只落在 tavern 子目录
    assert store.path == home / "tavern" / "tavern.json"


# ===========================================================================
# 局 / journal 最小 API（内存态；落盘只经 save）
# ===========================================================================

def test_play_upsert_get_delete(tmp_path):
    store = _make_store(tmp_path)
    data = default_tavern(now=_TS)

    play = new_play("lantern", "t", 1, play_id="p1", now=_TS)
    store.upsert_play(data, play)
    assert store.get_play(data, "p1") is play
    assert store.get_play(data, "missing") is None

    # 同 id 覆盖（不新增第二条）
    play2 = new_play("lantern", "t2", 2, play_id="p1", now=_TS)
    store.upsert_play(data, play2)
    assert len(data["plays"]) == 1
    assert store.get_play(data, "p1")["title"] == "t2"

    # 删除当前局 → 清空 active_play_id（防悬空引用）
    data["active_play_id"] = "p1"
    assert store.delete_play(data, "p1") is True
    assert data["active_play_id"] == ""
    assert data["plays"] == []
    assert store.delete_play(data, "p1") is False   # 幂等


def test_play_upsert_rejects_bad_payload(tmp_path):
    store = _make_store(tmp_path)
    data = default_tavern(now=_TS)
    with pytest.raises(TavernDataError):
        store.upsert_play(data, {"title": "无 id"})   # type: ignore[arg-type]
    with pytest.raises(TavernDataError):
        store.upsert_play(data, "not-a-dict")          # type: ignore[arg-type]


def test_append_journal(tmp_path):
    store = _make_store(tmp_path)
    data = default_tavern(now=_TS)

    assert store.append_journal(data, "seen_endings", "e1") is True
    assert store.append_journal(data, "seen_endings", "e1") is False   # 去重
    assert store.append_journal(data, "unlocked_entries", 12) is True
    assert store.append_journal(data, "first_seen", {"lantern": _TS}) is True
    # 首次语义：已存在不覆盖
    assert store.append_journal(data, "first_seen", {"lantern": "later"}) is False
    assert data["journal"]["first_seen"]["lantern"] == _TS

    with pytest.raises(TavernDataError):
        store.append_journal(data, "not_a_key", 1)
    with pytest.raises(TavernDataError):
        store.append_journal(data, "first_seen", ["lantern", _TS])  # 需 dict


# ===========================================================================
# 零 Qt 证据
# ===========================================================================

def test_no_qt_import_even_with_blocker(tmp_path):
    """主动屏蔽 ``PySide6`` 后，子进程内 ``import gui.tavern.store`` 仍成功。"""
    root = str(Path(__file__).resolve().parent.parent)
    code = textwrap.dedent(
        """
        import sys
        class _Block:
            def find_spec(self, name, path=None, target=None):
                if name == "PySide6" or name.startswith("PySide6."):
                    raise ImportError("blocked: " + name)
                return None
        sys.meta_path.insert(0, _Block())
        import gui.tavern.store as s
        assert "PySide6" not in sys.modules, "store 链拉入了 PySide6"
        assert hasattr(s, "TavernStore")
        print("ZERO_QT_OK")
        """
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        cwd=root, capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stderr
    assert "ZERO_QT_OK" in proc.stdout
