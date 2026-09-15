"""gui/tavern/store.py —— 酒馆功能域 · 数据层（V22-01，纯逻辑零 Qt）。

设计依据：``docs/design-v22.md``
    - §4.1  ``~/.maid_coder/tavern/tavern.json``（单文件，顶层 ``schema_version``）
    - §4.3  ``TavernStore`` 接口签名（``path`` / ``load`` / ``save`` / ``_rotate_backup``）
    - §4.4  原子写 + 坏档恢复矩阵 **L0–L6**（``load`` **绝不抛**）
    - §2    D-V22-07：落盘跟随既有业务数据 ``~/.maid_coder``（**不碰 %APPDATA%**）+
            原子写 + 读时迁移 + 写前快照轮转
    - §4.5  与既有业务数据隔离（只读写 ``tavern.json``）
    - §5.4-2/3/4/6/7：「数据不乱」机制（原子写 / 单写点 / 读时迁移 / 快照轮转 / 单局-跨局分离）

硬约束（本模块）：
    * **零 Qt**：仅依赖标准库 + 项目内既有工具（``from utils import _atomic_write_json``，
      ``memory.py:12`` / ``intimacy.py:11`` 为既有先例）。**不 import 任何 ``gui.*`` UI 模块**。
      ``import gui.tavern.store`` 必须在「主动屏蔽 PySide6」的环境下成功。
    * **单写点**：全模块**只有** :meth:`TavernStore.save` 触碰落盘（``_rotate_backup`` 只做
      备份复制/平移，``load`` **不写盘**）。play / journal 的便捷方法只做**内存态**变更，
      由调用方决定何时 ``save``。
    * **归属边界**：``default_tavern`` / ``merge_defaults`` / ``migrate`` / ``merge_play``
      四个不变量函数**已冻结在** :mod:`gui.tavern.model`，本模块**直接调用、不重复实现**。
    * 异常一律走 :mod:`gui.tavern.errors` 既有层级；日志以 ``logger.debug(..., exc_info=True)``
      收口，**无裸 ``except: pass``**。
"""
from __future__ import annotations

import json
import logging
import os
import shutil
from pathlib import Path
from typing import Any, Optional, Tuple, Union

from utils import _atomic_write_json

from .errors import TavernDataError, TavernStoreError
from .model import (
    SCHEMA_VERSION,
    TAVERN_DIR_NAME,
    TAVERN_FILE_NAME,
    default_tavern,
    iso_now,
    migrate,
)

_LOG = logging.getLogger("maling.tavern.store")

__all__ = [
    "MAX_BACKUPS",
    "CORRUPT_SUFFIX",
    "JOURNAL_LIST_KEYS",
    "JOURNAL_MAP_KEYS",
    "JOURNAL_KEYS",
    "default_base_dir",
    "TavernStore",
]

#: 快照保留份数（``tavern.json.bak.1`` = 最新一份；§4.4）。
MAX_BACKUPS: int = 3

#: 损坏档隔离后缀（L6 改名保留，绝不再当主档读）。
CORRUPT_SUFFIX: str = ".corrupt"

#: ``journal`` 的 list 型子集合（追加 + 去重）。
JOURNAL_LIST_KEYS: Tuple[str, ...] = ("seen_endings", "unlocked_entries")

#: ``journal`` 的 dict 型子集合（仅首次写入）。
JOURNAL_MAP_KEYS: Tuple[str, ...] = ("first_seen",)

#: ``journal`` 子集合全集（``append_journal`` 的合法键）。
JOURNAL_KEYS: Tuple[str, ...] = JOURNAL_LIST_KEYS + JOURNAL_MAP_KEYS


def _safe_int(value: Any, default: int) -> int:
    """``int`` 守卫：``bool`` 不算 int；非法回默认（对齐 model 既有写法）。"""
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def default_base_dir() -> Path:
    """默认业务数据目录：``~/.maid_coder/tavern``（跟随既有业务数据，D-V22-07）。

    **不碰** ``%APPDATA%\\maid_coder``（那是 GUI 配置 ``gui_config.json`` 的地盘）。
    """
    return Path(os.path.expanduser("~/.maid_coder")) / TAVERN_DIR_NAME


class TavernStore:
    """酒馆存档 IO 门面（**唯一写点** + 坏档恢复矩阵，纯逻辑零 Qt）。

    典型用法::

        store = TavernStore()                 # 默认 ~/.maid_coder/tavern
        data = store.load()                   # 坏档逐级恢复，绝不抛
        store.upsert_play(data, play)         # 内存态变更
        store.save(data)                      # 原子写（唯一落盘点）

    Attributes:
        read_only: 最近一次 :meth:`load` 是否命中「更高版本只读」档（L4）；
            为真时 :meth:`save` 会被拒绝（本期不写回更高版本）。
    """

    def __init__(self, base_dir: Optional[Union[str, "os.PathLike[str]"]] = None) -> None:
        """构造数据层门面。

        Args:
            base_dir: 存档目录；``None`` 时取 :func:`default_base_dir`
                （``~/.maid_coder/tavern``）。**不创建目录**（首次 ``save`` 才建）。
        """
        self._base_dir: Path = Path(base_dir) if base_dir is not None else default_base_dir()
        self._read_only: bool = False

    # ------------------------------------------------------------------
    # 路径
    # ------------------------------------------------------------------

    @property
    def base_dir(self) -> Path:
        """存档目录（只读）。"""
        return self._base_dir

    @property
    def path(self) -> Path:
        """主档路径：``<base_dir>/tavern.json``（§4.3）。"""
        return self._base_dir / TAVERN_FILE_NAME

    @property
    def read_only(self) -> bool:
        """最近一次加载是否只读（L4：``schema_version`` 高于当前，不写回）。"""
        return self._read_only

    def _backup_path(self, index: int) -> Path:
        """第 ``index`` 份快照路径（``tavern.json.bak.<index>``，1 = 最新）。"""
        p = self.path
        return p.with_name(f"{p.name}.bak.{index}")

    # ------------------------------------------------------------------
    # 读：坏档恢复矩阵 L0–L6（绝不抛）
    # ------------------------------------------------------------------

    def load(self) -> dict:
        """读取并「读时迁移」酒馆存档；坏档逐级恢复，**绝不抛**（§4.4 L0–L6）。

        Returns:
            完整的 ``tavern`` 结构（顶层键集 == :data:`gui.tavern.model.TOP_LEVEL_KEYS`）。
            各级行为：

            * **L0** 文件不存在 → 类默认（新档）；**不写盘**（单写点纪律）；
            * **L1** 字段缺失 → :func:`model.merge_defaults` 补默认；
            * **L2** 字段类型错 / 顶层非 object → 该字段回落默认；
            * **L3** ``schema_version`` 旧 → :func:`model.migrate` 升级；
            * **L4** ``schema_version`` 高于当前 → 只读加载（``read_only`` 置真，**不写回**）；
            * **L5** JSON 截断 / 解析失败 → 尝试最新快照 ``tavern.json.bak.1``；
            * **L6** 截断 + 快照也坏 → 空档 + 损坏档改名保留（``*.corrupt``），不弹框。
        """
        self._read_only = False
        path = self.path

        # L0：首次运行（不建文件）
        if not path.exists():
            _LOG.debug("L0 酒馆存档不存在，返回类默认（不写盘）: %s", path)
            return default_tavern()

        # L5/L6 入口：解析主档（json.JSONDecodeError ⊂ ValueError）
        try:
            with open(path, "r", encoding="utf-8") as f:
                raw = json.load(f)
        except (OSError, ValueError) as exc:
            _LOG.debug("L5 酒馆主档解析失败，尝试快照恢复: %s", path, exc_info=True)
            recovered = self._load_latest_backup()
            if recovered is not None:
                return recovered
            _LOG.debug("L6 主档与快照均不可用，回落空档并隔离坏档: %s", path, exc_info=True)
            self._quarantine_corrupt(path)
            return default_tavern()

        # L1/L2/L3/L4：读时迁移 + 只读判定
        return self._finalize(raw)

    def _finalize(self, raw: Any) -> dict:
        """L1/L2/L3/L4：以 :func:`model.migrate` 为底读时迁移，并按版本打只读标。

        Args:
            raw: 已解析的 JSON 对象（可为任意类型）。

        Returns:
            迁移后的完整结构；若 ``schema_version`` 高于当前，置 :attr:`read_only`。
        """
        if not isinstance(raw, dict):
            # L2：顶层非 object（``null`` / list / str / int）→ 回落类默认
            _LOG.debug("L2 酒馆顶层非 object（%s），回落类默认", type(raw).__name__)
            return migrate(raw)
        data = migrate(raw)
        if _safe_int(data.get("schema_version"), SCHEMA_VERSION) > SCHEMA_VERSION:
            # L4：更高版本只读加载，不降级、不写回（model.migrate 已保证不降级）
            self._read_only = True
            _LOG.debug(
                "L4 酒馆 schema_version=%s 高于当前 %s，只读加载（不写回）",
                data.get("schema_version"), SCHEMA_VERSION,
            )
        return data

    def _load_latest_backup(self) -> Optional[dict]:
        """L5：按 ``.bak.1``（最新）→ ``.bak.<MAX_BACKUPS>`` 取第一份可解析快照。

        Returns:
            恢复后的完整结构；无可用快照返回 ``None``（交由调用方走 L6 空档）。
        """
        for index in range(1, MAX_BACKUPS + 1):
            bak = self._backup_path(index)
            if not bak.exists():
                continue
            try:
                with open(bak, "r", encoding="utf-8") as f:
                    raw = json.load(f)
            except (OSError, ValueError):
                _LOG.debug("L6 快照亦损坏，跳过: %s", bak, exc_info=True)
                continue
            _LOG.debug("L5 已从快照恢复: %s", bak)
            return self._finalize(raw)
        return None

    def _quarantine_corrupt(self, path: Path) -> None:
        """L6：把损坏主档改名保留（``tavern.json.corrupt[.n]``），**绝不静默删除**。

        命名不加时间戳（保证确定性单测不受墙钟影响）；同名占用时追加 ``.1`` / ``.2`` …。
        """
        target = path.with_name(path.name + CORRUPT_SUFFIX)
        n = 1
        while target.exists():
            target = path.with_name(f"{path.name}{CORRUPT_SUFFIX}.{n}")
            n += 1
        try:
            os.replace(str(path), str(target))
        except OSError:
            # 隔离失败也要能返回空档（不阻断 load 的「绝不抛」承诺）
            _LOG.debug("L6 隔离坏档失败（忽略，仍返回空档）: %s", path, exc_info=True)

    # ------------------------------------------------------------------
    # 写：唯一写点（mkdir → updated_at → 预校验 → 快照轮转 → 原子写）
    # ------------------------------------------------------------------

    def save(self, data: dict) -> None:
        """**唯一写点**：把酒馆存档原子写盘（§4.4）。

        流程（逐条对齐 §4.4）：
            1. ``mkdir(parents=True, exist_ok=True)``（``_atomic_write_json`` **不建父目录**）；
            2. 更新 ``data["meta"]["updated_at"] = iso_now()``；
            3. ``json.dumps`` 预校验可序列化（失败即终止，**不写坏**）；
            4. 若主档已存在 → :meth:`_rotate_backup`（写前快照轮转）；
            5. ``_atomic_write_json(path, data)``（``tmp`` + ``os.replace``）。

        Args:
            data: 完整酒馆结构（就地更新 ``meta.updated_at``）。

        Raises:
            TavernStoreError: 入参非 dict / 只读档（L4）/ 无法建目录 / 不可序列化 / 写盘失败。
                任一步失败都**不破坏现有存档**（快照轮转采用复制而非移动）。
        """
        if not isinstance(data, dict):
            raise TavernStoreError("酒馆存档必须是对象（dict）。", reason="bad_payload")
        if self._read_only:
            raise TavernStoreError(
                "这份存档来自更高的版本，本期只读，不写回。", reason="read_only")

        path = self.path
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise TavernStoreError("无法创建酒馆存档目录。", reason="mkdir_failed") from exc

        # 2) 时间戳（结构字段由 store 统一维护）
        meta = data.get("meta")
        if not isinstance(meta, dict):
            meta = {}
            data["meta"] = meta
        meta["updated_at"] = iso_now()

        # 3) 预校验可序列化（不通过则原档不动）
        try:
            json.dumps(data, ensure_ascii=False)
        except (TypeError, ValueError) as exc:
            raise TavernStoreError(
                "酒馆存档无法序列化，已放弃本次写入（原档未改）。",
                reason="not_serializable") from exc

        # 4) 写前快照轮转（复制当前档到 .bak.1，不动 path 本身）
        if path.exists():
            self._rotate_backup()

        # 5) 原子写
        try:
            _atomic_write_json(str(path), data)
        except (OSError, ValueError) as exc:
            raise TavernStoreError(
                "写入酒馆存档失败（原档未改）。", reason="write_failed") from exc

    def _rotate_backup(self) -> None:
        """写前快照轮转：保留最近 :data:`MAX_BACKUPS` 份 ``.bak.N``（``.bak.1`` 最新）。

        采用**复制**（``shutil.copy2``）而非移动当前档：移动会让「写失败」时原档消失，
        违背「写失败原档不被破坏」。轮转本身失败**不阻断**写入（best-effort，仅记日志）。
        """
        path = self.path
        try:
            # 先腾出最旧一格（.bak.MAX 删除，实现滚动）
            oldest = self._backup_path(MAX_BACKUPS)
            if oldest.exists():
                os.remove(str(oldest))
            # 由旧到新平移：.bak.i -> .bak.(i+1)
            for index in range(MAX_BACKUPS - 1, 0, -1):
                src = self._backup_path(index)
                if src.exists():
                    os.replace(str(src), str(self._backup_path(index + 1)))
            # 当前档 -> .bak.1（复制，保留 path 原文件）
            shutil.copy2(str(path), str(self._backup_path(1)))
        except OSError:
            _LOG.debug("快照轮转失败（忽略，不阻断写入）: %s", path, exc_info=True)

    # ------------------------------------------------------------------
    # 局与 journal 的最小操作（**内存态**；落盘只经 save()）
    # ------------------------------------------------------------------

    @staticmethod
    def get_play(data: dict, play_id: str) -> Optional[dict]:
        """按 ``play_id`` 取局对象（返回 ``data`` 内的**实时引用**；无则 ``None``）。"""
        plays = data.get("plays")
        if not isinstance(plays, list):
            return None
        for play in plays:
            if isinstance(play, dict) and play.get("play_id") == play_id:
                return play
        return None

    @staticmethod
    def upsert_play(data: dict, play: dict) -> dict:
        """按 ``play_id`` 新增或替换一局（内存态，**不落盘**）；返回入库对象。

        Args:
            data: 酒馆结构（就地修改 ``data["plays"]``）。
            play: 局对象（须为 dict 且含非空 ``play_id``）。

        Returns:
            入库的局对象（与入参同一引用）。

        Raises:
            TavernDataError: ``play`` 非 dict 或缺 ``play_id``。
        """
        if not isinstance(play, dict):
            raise TavernDataError("局数据必须是对象（dict）。", reason="bad_play")
        play_id = play.get("play_id")
        if not isinstance(play_id, str) or not play_id:
            raise TavernDataError("局数据缺少 play_id。", reason="missing_play_id")
        plays = data.get("plays")
        if not isinstance(plays, list):
            plays = []
            data["plays"] = plays
        for index, existing in enumerate(plays):
            if isinstance(existing, dict) and existing.get("play_id") == play_id:
                plays[index] = play
                return play
        plays.append(play)
        return play

    @staticmethod
    def delete_play(data: dict, play_id: str) -> bool:
        """按 ``play_id`` 删除一局（内存态，**不落盘**）；返回是否确有删除。

        若删除的正是 ``active_play_id``，一并清空，避免悬空引用。
        """
        plays = data.get("plays")
        if not isinstance(plays, list):
            return False
        kept = [p for p in plays
                if not (isinstance(p, dict) and p.get("play_id") == play_id)]
        if len(kept) == len(plays):
            return False
        data["plays"] = kept
        if data.get("active_play_id") == play_id:
            data["active_play_id"] = ""
        return True

    @staticmethod
    def append_journal(data: dict, key: str, value: Any) -> bool:
        """向 ``journal`` 追加一条跨局记录（内存态，**不落盘**）；返回是否新增。

        Args:
            data: 酒馆结构（就地修改 ``data["journal"]``）。
            key: ``journal`` 子集合名，须 ∈ :data:`JOURNAL_KEYS`。
            value: ``seen_endings`` / ``unlocked_entries``（list）→ 标量（去重追加）；
                ``first_seen``（dict）→ ``{书id: 时间戳}`` 映射（仅首次写入）。

        Returns:
            ``True`` 表示确有新增；``False`` 表示已存在（幂等）。

        Raises:
            TavernDataError: 未知 ``key`` 或 ``first_seen`` 取值非 dict。
        """
        if key not in JOURNAL_KEYS:
            raise TavernDataError(f"未知 journal 键: {key!r}", reason="unknown_journal_key")

        journal = data.get("journal")
        if not isinstance(journal, dict):
            journal = {"seen_endings": [], "unlocked_entries": [], "first_seen": {}}
            data["journal"] = journal

        if key in JOURNAL_LIST_KEYS:
            bucket = journal.get(key)
            if not isinstance(bucket, list):
                bucket = []
                journal[key] = bucket
            if value in bucket:
                return False
            bucket.append(value)
            return True

        # first_seen：dict，仅首次写入（setdefault 语义）
        if not isinstance(value, dict):
            raise TavernDataError(
                "first_seen 需要 {书id: 时间戳} 映射。", reason="bad_journal_value")
        bucket = journal.get(key)
        if not isinstance(bucket, dict):
            bucket = {}
            journal[key] = bucket
        added = False
        for topic, stamp in value.items():
            if topic not in bucket:
                bucket[topic] = stamp
                added = True
        return added
