"""tests/test_v24_memory_persistence.py —— v2.4 落盘安全网（D-V24-05 / P0-1）。

背景：`_load()` 原实现遇 `json.JSONDecodeError` 直接 pass、随即用默认结构**覆盖
写盘** —— 这是 memory.py 唯一会静默销毁用户记忆的路径（无备份、无日志）。GUI 改为
每轮对话都落盘后该风险被放大。

修复对齐 `gui/tavern/store.py` 的既有约定：
- L5 主档不可解析 -> 尝试最新快照 `.bak.1`；
- L6 快照亦坏 -> 损坏档**改名保留**为 `*.corrupt[.n]`，绝不静默删除；
- 写前快照轮转采用**复制**，保证「写失败原档不被破坏」。

测试数据隔离：一律 `filepath=tmp_path`（共享知识 23）。
"""
import glob
import json
import os

from memory import MemoryManager


def _files(dirpath, prefix):
    return sorted(os.path.basename(p) for p in glob.glob(os.path.join(dirpath, prefix + "*")))


def _corrupt(path, text="这是一段坏掉的 JSON {{"):
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


class TestWriteSnapshot:
    """写前快照轮转。"""

    def test_first_write_creates_no_snapshot(self, tmp_path):
        """首次写盘时还没有主档可快照 —— 不应凭空造出 .bak.1。"""
        fp = str(tmp_path / "m.json")
        MemoryManager(filepath=fp)
        assert _files(tmp_path, "m.json") == ["m.json"]

    def test_second_write_creates_snapshot(self, tmp_path):
        fp = str(tmp_path / "m.json")
        mm = MemoryManager(filepath=fp)
        mm.add_topic("学 Rust", source="manual")
        assert "m.json.bak.1" in _files(tmp_path, "m.json")

    def test_snapshot_is_one_save_behind(self, tmp_path):
        """快照语义：始终是**上一次**成功写盘的状态（写前拍摄，可回滚）。"""
        fp = str(tmp_path / "m.json")
        mm = MemoryManager(filepath=fp)
        mm.add_topic("第一个话题", source="manual")     # 写 #1（无快照）
        mm.add_topic("第二个话题", source="manual")     # 写 #2（快照 = 写 #1 状态）
        with open(fp + ".bak.1", encoding="utf-8") as f:
            snap = json.load(f)
        subs = [t["subject"] for t in snap["topics"]["active"]]
        assert subs == ["第一个话题"], "快照应落后主档一次保存"

    def test_snapshot_never_replaces_main_file(self, tmp_path):
        """轮转用复制而非移动 —— 主档必须原地保留。"""
        fp = str(tmp_path / "m.json")
        mm = MemoryManager(filepath=fp)
        mm.add_topic("学 Rust", source="manual")
        mm.add_topic("学 Go", source="manual")
        assert os.path.exists(fp)
        assert [t["subject"] for t in mm.get_active_topics()] == ["学 Rust", "学 Go"]


class TestCorruptRecovery:
    """L5/L6 加载阶梯。"""

    def test_corrupt_main_recovers_from_snapshot(self, tmp_path):
        """主档坏了 -> 从快照恢复，数据不丢（只丢最后一次保存）。"""
        fp = str(tmp_path / "m.json")
        mm = MemoryManager(filepath=fp)
        mm.add_topic("学 Rust", source="manual")
        mm.add_topic("学 Go", source="manual")     # 快照 = 只有「学 Rust」
        _corrupt(fp)
        recovered = MemoryManager(filepath=fp)
        assert [t["subject"] for t in recovered.get_active_topics()] == ["学 Rust"]

    def test_corrupt_main_and_snapshot_quarantines(self, tmp_path):
        """主档 + 快照都坏 -> 隔离坏档，回落默认结构。"""
        fp = str(tmp_path / "m.json")
        mm = MemoryManager(filepath=fp)
        mm.add_topic("装修计划", source="manual")
        mm.add_topic("备考", source="manual")
        _corrupt(fp)
        _corrupt(fp + ".bak.1", "快照也坏")
        fresh = MemoryManager(filepath=fp)
        assert fresh.get_active_topics() == []
        assert "m.json.corrupt" in _files(tmp_path, "m.json")

    def test_quarantine_preserves_content(self, tmp_path):
        """核心保证：坏档被**改名保留**，内容仍可读 —— 绝不静默删除。"""
        fp = str(tmp_path / "m.json")
        MemoryManager(filepath=fp)
        _corrupt(fp, "用户的记忆在这里边")
        MemoryManager(filepath=fp)
        with open(fp + ".corrupt", encoding="utf-8") as f:
            assert f.read() == "用户的记忆在这里边"

    def test_second_corruption_does_not_overwrite_first(self, tmp_path):
        """二次损坏追加序号，不覆盖既有 .corrupt（与 tavern store 同款）。"""
        fp = str(tmp_path / "m.json")
        MemoryManager(filepath=fp)
        _corrupt(fp, "第一次坏")
        MemoryManager(filepath=fp)
        _corrupt(fp, "第二次坏")
        MemoryManager(filepath=fp)
        names = _files(tmp_path, "m.json")
        assert "m.json.corrupt" in names
        assert "m.json.corrupt.1" in names
        with open(fp + ".corrupt", encoding="utf-8") as f:
            assert f.read() == "第一次坏"
        with open(fp + ".corrupt.1", encoding="utf-8") as f:
            assert f.read() == "第二次坏"

    def test_truncated_json_triggers_recovery(self, tmp_path):
        """截断（半截写入）也走恢复阶梯，而非当空档处理。"""
        fp = str(tmp_path / "m.json")
        mm = MemoryManager(filepath=fp)
        mm.add_topic("学 Rust", source="manual")
        mm.add_topic("学 Go", source="manual")
        with open(fp, encoding="utf-8") as f:
            good = f.read()
        with open(fp, "w", encoding="utf-8") as f:
            f.write(good[: len(good) // 2])          # 截断
        recovered = MemoryManager(filepath=fp)
        assert [t["subject"] for t in recovered.get_active_topics()] == ["学 Rust"]


class TestNoRegressionOnNormalPath:
    """安全网不得干扰正常读写路径。"""

    def test_roundtrip_intact(self, tmp_path):
        fp = str(tmp_path / "m.json")
        mm = MemoryManager(filepath=fp)
        mm.add_topic("学 Rust", source="manual")
        mm.set_preference("nickname", "小远")
        again = MemoryManager(filepath=fp)
        assert [t["subject"] for t in again.get_active_topics()] == ["学 Rust"]
        assert again.get_preference("nickname") == "小远"

    def test_extra_files_are_not_treated_as_main(self, tmp_path):
        """副作用文件（.bak.N / .corrupt）不应被误当主档读取。"""
        fp = str(tmp_path / "m.json")
        mm = MemoryManager(filepath=fp)
        mm.add_topic("学 Rust", source="manual")
        mm.add_topic("学 Go", source="manual")
        # 把快照写成一份「内容不同」的合法档，主档仍应胜出
        with open(fp + ".bak.1", "w", encoding="utf-8") as f:
            json.dump({"preferences": {"nickname": "不该出现"}}, f, ensure_ascii=False)
        again = MemoryManager(filepath=fp)
        assert again.get_active_topics()[0]["subject"] == "学 Rust"
        assert again.get_preference("nickname") is None
