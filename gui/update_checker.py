"""UpdateChecker —— 启动后异步检查更新（v1.0.0 新增）。

行为边界（执行文档 3.4，已定案）：
- 启动后异步检查，不阻塞主窗口显示；
- 超时 5 秒静默放弃；失败 / 离线 / JSON 解析错误一律静默跳过，
  仅记 info 级以下日志，绝不弹窗、绝不影响启动；
- 发现新版 → GUI 非阻断提示「发现新版本 vX.Y.Z：{要点}」，
  操作两个：「复制下载链接」（主链失败降级备用链）+「忽略此版本」；
- 不做自动下载、不做自动安装。

「忽略此版本」的存储（执行文档 3.3）：
- 独立文件 get_user_data_dir()/update_state.json，不进 config.yaml——
  更新行为状态不是用户产品配置，且 config.yaml 读写是正在修复的缺陷域，互不拖累；
- 用户忽略某版本后记录版本号，仅当 version.json 出现比被忽略版本更新的版本时
  才恢复提示；同一版本不因重启反复弹。

版本比较一律走 core.parse_version 数值元组（执行文档 2.3），
本地版本低于 min_compatible 时提示「建议重新下载安装」而非普通更新。

---- v2.0 增量（design-v20，R-D 只增量不重构）----
本模块是 v2.0「检查更新」层的契约冻结区（域1）：
- 频道化：stable / beta 双 URL（D-V20-07），owner 单一常量；
- 状态原子写：新增 save_update_state(dict) 单一写入口（D-V20-10）；
- 新增纯函数：resolve_channel_url / should_check_now / should_prompt /
  asset_for_form / has_valid_sha256 / is_allowed_url(R-M) / detect_install_form；
- **既有契约零变更**：evaluate_update / format_update_text / pick_download_link /
  UpdateChecker.update_available / load_update_state / save_ignored_version /
  _valid_remote 语义与签名保留（D-V20-15 论证表）。
"""
from __future__ import annotations

import json
import logging
import os
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable, Optional
from urllib.parse import urlparse

from gui.qt_compat import QObject, Signal
from gui.qt_exit_guard import ExitSafeQThread

from core import __version__, parse_version, is_newer_version

logger = logging.getLogger("maid_coder.gui")

# ---------------------------------------------------------------------------
# v2.0(D-V20-07): 频道与 URL 表 —— owner 单一常量，一处可改
# ---------------------------------------------------------------------------
# R-O③ 发版硬闸：真实 GitHub 用户名（占位已消解）。
GITHUB_OWNER = "xigua148"
GITHUB_REPO = "maling"
CHANNEL_STABLE = "stable"
CHANNEL_BETA = "beta"

# 频道 → version.json URL（beta 走同仓库 main/beta/version.json，Q-U8）
CHANNEL_URLS = {
    "stable": f"https://raw.githubusercontent.com/{GITHUB_OWNER}/{GITHUB_REPO}/main/version.json",
    "beta": f"https://raw.githubusercontent.com/{GITHUB_OWNER}/{GITHUB_REPO}/main/beta/version.json",
}
# design-v20 §D-V20-07 命名别名（契约冻结：两个名字指向同一张表）
VERSION_JSON_URLS = CHANNEL_URLS
# 向后兼容别名（R-D：常量名保留，取值升级为 stable 频道）
VERSION_JSON_URL = CHANNEL_URLS[CHANNEL_STABLE]

# 检查超时（秒）：超时静默放弃，绝不阻塞启动。
CHECK_TIMEOUT_SECONDS = 5

# 手动检查三态（L1-2 验收①）
CHECK_UPDATE = "update"    # 有新版本
CHECK_LATEST = "latest"    # 已是最新
CHECK_FAILED = "failed"    # 检查失败，请稍后重试

# ---------------------------------------------------------------------------
# v2.0(R-M / D-V20-11): URL 安全白名单（单一收口）
# ---------------------------------------------------------------------------
# 默认允许的下载 / 检查域名（GitHub 系）；用户自配镜像 host 由 extra_hosts 追加。
ALLOWED_URL_HOSTS = (
    "github.com",
    "objects.githubusercontent.com",
    "raw.githubusercontent.com",
    "codeload.github.com",
)
_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")


def resolve_channel(channel: Any) -> str:
    """归一频道名；非法 / 空 → "stable"（D-V20-07）。"""
    key = str(channel or "").strip().lower()
    return key if key in CHANNEL_URLS else CHANNEL_STABLE


def resolve_channel_url(channel: str) -> str:
    """频道 → version.json URL；非法频道回落 stable（L1-3 验收②）。"""
    return CHANNEL_URLS[resolve_channel(channel)]


def resolve_effective_channel(cfg_channel: Any, state_channel: Any) -> str:
    """生效频道：GuiConfig(真值源) > update_state.channel > stable（D-V20-07）。"""
    if str(cfg_channel or "").strip():
        return resolve_channel(cfg_channel)
    return resolve_channel(state_channel)


def _update_state_path() -> Path:
    """update_state.json 存 get_user_data_dir() 下（依赖 gui.utils，延迟导入便于测试）。"""
    from gui.utils import get_user_data_dir
    return get_user_data_dir() / "update_state.json"


def load_update_state() -> dict:
    """读取忽略状态；文件不存在 / 损坏一律返回空状态（静默）。"""
    try:
        path = _update_state_path()
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
    except Exception as exc:  # 解析错误静默跳过（执行文档 3.4）
        logger.info("update_state.json 读取失败（忽略）: %s", exc)
    return {}


def _atomic_write_json(path: Path, data: dict) -> None:
    """原子写 JSON：同目录临时文件 + os.replace（D-V20-10）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".tmp{os.getpid()}")
    tmp.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    os.replace(tmp, path)


def save_update_state(patch: dict) -> None:
    """update_state.json 唯一写入口（读-合并-写，原子）。

    v2.0(D-V20-10): 所有状态写走本函数，禁止散落直接 write_text。
    任何失败静默（更新状态写失败不影响主流程，R-N）。
    """
    if not isinstance(patch, dict):
        return
    try:
        path = _update_state_path()
        state = load_update_state()
        state.update(patch)
        _atomic_write_json(path, state)
    except Exception as exc:  # 写失败不影响主流程
        logger.info("update_state.json 写入失败（忽略）: %s", exc)


def save_ignored_version(version: str) -> None:
    """记录被忽略的版本号（含 last_checked 日期）。

    v2.0: 内部改调 save_update_state（原子写），签名与语义不变（R-D）。
    """
    save_update_state({
        "ignored_version": version,
        "last_checked": date.today().isoformat(),
    })


def _valid_remote(data: Any) -> Optional[dict]:
    """校验 version.json 字段合法性（执行文档 3.2 必填项）。

    不合法返回 None —— 调用方静默跳过（JSON 解析错误同待遇）。
    """
    if not isinstance(data, dict):
        return None
    version = data.get("version")
    downloads = data.get("downloads")
    if not isinstance(version, str) or not version:
        return None
    try:
        parse_version(version)
    except (TypeError, ValueError):
        return None
    if not isinstance(downloads, dict):
        return None
    if not isinstance(downloads.get("github"), str) or not downloads.get("github"):
        return None
    return data


def evaluate_update(remote: Any, local_version: str, ignored_version: Optional[str]) -> Optional[dict]:
    """纯函数：给定远端 version.json 数据与本地状态，判断是否提示。

    返回 None 表示不提示（无更新 / 已忽略 / 数据不合法）；
    返回 dict: {kind: "update"|"reinstall", version, notes, primary, mirror,
    assets, min_updatable, release_url}。
    本函数不碰网络与文件，便于回归测试直接断言。

    v2.0(R-D 纯增量): 在既有五键**之后追加** assets / min_updatable / release_url
    （原样透传，不做二次校验；缺失一律 None）。旧消费方只读既有键，零破坏。
    """
    data = _valid_remote(remote)
    if data is None:
        return None
    version = data["version"]
    downloads = data["downloads"]
    notes = data.get("notes") if isinstance(data.get("notes"), list) else []
    notes = [str(n) for n in notes][:5]

    # v2.0 追加字段（原样透传；类型不符 / 缺失 → None）
    assets = data.get("assets")
    if not isinstance(assets, dict):
        assets = None
    min_updatable = data.get("min_updatable")
    if not isinstance(min_updatable, str) or not min_updatable:
        min_updatable = None
    release_url = data.get("release_url")
    if not isinstance(release_url, str) or not release_url:
        release_url = None

    def _payload(kind: str) -> dict:
        return {
            # ---- 既有键（签名与语义零变更，R-D）----
            "kind": kind,
            "version": version,
            "notes": notes,
            "primary": downloads.get("github", ""),
            "mirror": downloads.get("mirror", ""),
            # ---- v2.0 追加键（纯增量）----
            "assets": assets,
            "min_updatable": min_updatable,
            "release_url": release_url,
        }

    # 忽略规则：仅当出现比被忽略版本更新的版本时才恢复提示
    if ignored_version:
        try:
            if not is_newer_version(version, ignored_version):
                return None
        except (TypeError, ValueError):
            return None

    # 本地低于 min_compatible：提示建议重新下载安装（不走普通更新提示）
    min_compatible = data.get("min_compatible")
    if isinstance(min_compatible, str) and min_compatible:
        try:
            if parse_version(local_version) < parse_version(min_compatible):
                return _payload("reinstall")
        except (TypeError, ValueError):
            pass  # min_compatible 不合法则按普通逻辑走

    if is_newer_version(version, local_version):
        return _payload("update")
    return None


def _parse_state_time(value: Any) -> Optional[datetime]:
    """解析 update_state 中的时间字段（支持 YYYY-MM-DD 与 ISO datetime）。"""
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        try:
            return datetime.combine(date.fromisoformat(text), datetime.min.time())
        except ValueError:
            return None


def should_check_now(state: Any, now: Optional[datetime] = None,
                     force: bool = False) -> bool:
    """纯函数：启动时是否应发起自动检查（Q-U13 / D-V20-14）。

    - force=True（手动检查）恒 True，不受 24h 闸限制；
    - last_checked 缺失 / 非法 → True（首次检查）；
    - 否则 now - last_checked >= 24h → True，否则 False。
    注：cfg.auto_check 开关由调用方在调用前判定（关闭时不调用本函数）。
    """
    if force:
        return True
    if not isinstance(state, dict):
        state = {}
    last = _parse_state_time(state.get("last_checked"))
    if last is None:
        return True
    if now is None:
        now = datetime.now()
    elif isinstance(now, date) and not isinstance(now, datetime):
        now = datetime.combine(now, datetime.min.time())
    try:
        return (now - last) >= timedelta(hours=24)
    except TypeError:
        return True


def should_prompt(state: Any, version: str, today: Any) -> bool:
    """纯函数：同一天是否还该弹更新提示（L1-5 验收②③ / D-V20-14）。

    - ignored_version 为空 → True；
    - 出现比被忽略版本更新的版本 → True（恢复提示）；
    - 否则 last_prompt_date == today → False（同日不重弹）。
    """
    if not isinstance(state, dict):
        state = {}
    ignored = state.get("ignored_version")
    if not ignored:
        return True
    try:
        if is_newer_version(version, ignored):
            return True
    except (TypeError, ValueError):
        return True
    return str(state.get("last_prompt_date") or "") != str(today)


def last_install_hint(state: Any) -> str:
    """纯函数：由 update_state.last_install 生成一句中性提示（R-A / L3-6）。

    仅当上次换包结果为 failed / rolled_back 时返回一句可重试提示；
    success / 缺失 / 非法一律返回 ""（不显示；不催促、无数值化语义）。
    供设置页「更新」区做安静的只读提示行（重试入口复用既有「检查更新」按钮）。
    """
    if not isinstance(state, dict):
        return ""
    info = state.get("last_install")
    if not isinstance(info, dict):
        return ""
    if info.get("result") in ("failed", "rolled_back"):
        return "上次更新未完成，可重试"
    return ""


def asset_for_form(remote: Any, form: str = "onedir") -> Optional[dict]:
    """纯函数：按安装形态取 version.json 的对应资产 dict（L2-7）。

    form: detect_install_form() 的结果（"onedir"/"onefile"/"dev"）或资产键
          （"onedir"/"single"）；onefile/single → assets.single，其余 → assets.onedir。
    remote: 完整 version.json dict（含 "assets"）；也兼容直接传 assets 表。
    返回 None 表示无对应资产（缺 assets / 缺对应键）。
    """
    if not isinstance(remote, dict):
        return None
    assets = remote.get("assets")
    if not isinstance(assets, dict) and ("onedir" in remote or "single" in remote):
        assets = remote  # 兼容直接传入 assets 表
    if not isinstance(assets, dict):
        return None
    kind = "single" if str(form or "").strip().lower() in (
        "onefile", "single", "singlefile", "exe",
    ) else "onedir"
    asset = assets.get(kind)
    return asset if isinstance(asset, dict) else None


def has_valid_sha256(asset: Any) -> bool:
    """纯函数：sha256 是否为 64 位十六进制（Q-U5）。

    False（缺失 / 非法）→ 禁止自动替换，仅提示手动下载。
    """
    if not isinstance(asset, dict):
        return False
    value = asset.get("sha256")
    return isinstance(value, str) and bool(_SHA256_RE.match(value.strip()))


def is_allowed_url(url: str, extra_hosts: Optional[Iterable[str]] = None) -> bool:
    """纯函数：R-M URL 校验收口（D-V20-11）。

    仅允许 https；拒绝 http / file / UNC / 相对路径 / 含 .. 的路径注入；
    host 必须命中默认白名单或 extra_hosts（用户自配镜像 host）。
    本函数是更新链 URL 校验的**权威单一实现**（下载器不重复实现域名白名单）。
    """
    if not isinstance(url, str):
        return False
    raw = url.strip()
    if not raw:
        return False
    # 显式拒绝 UNC（\\server\share）与协议相对地址（//host/path）
    if raw.startswith("\\") or raw.startswith("//"):
        return False
    try:
        parsed = urlparse(raw)
    except Exception:
        return False
    if (parsed.scheme or "").lower() != "https":
        return False
    host = (parsed.hostname or "").lower()
    if not host:
        return False
    # 路径注入：任何 ".." 段一律拒绝
    path = (parsed.path or "").replace("\\", "/")
    if ".." in [seg for seg in path.split("/") if seg]:
        return False
    allowed = {h.lower() for h in ALLOWED_URL_HOSTS}
    if extra_hosts:
        for extra in extra_hosts:
            if isinstance(extra, str) and extra.strip():
                allowed.add(extra.strip().lower())
    for base in allowed:
        if host == base or host.endswith("." + base):
            return True
    return False


def extract_host(url: str) -> str:
    """从 URL 取 host（供设置页展示镜像 host / 白名单拼装），非法返回 ""。"""
    try:
        return (urlparse(str(url or "").strip()).hostname or "").lower()
    except Exception:
        return ""


def detect_install_form() -> str:
    """探测当前安装形态："onedir" | "onefile" | "dev"（D-V20-06 / L2-7）。

    - 非 Windows 或非 frozen（源码态）→ "dev"（禁用自动替换）；
    - frozen 且有 _internal 目录 → "onedir"；
    - frozen 且 _MEIPASS 与 exe 目录不同 → "onefile"；
    - 其它 frozen → "onefile"（保守）；
    - 探测异常 → "onedir"（默认）并留 info 日志。
    """
    try:
        if os.name != "nt":
            return "dev"
        if not getattr(sys, "frozen", False):
            return "dev"
        exe_dir = Path(sys.executable).resolve().parent
        if (exe_dir / "_internal").is_dir():
            return "onedir"
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass and Path(meipass) != exe_dir:
            return "onefile"
        return "onefile"
    except Exception as exc:
        logger.info("安装形态探测失败（按 onedir 处理）: %s", exc)
        return "onedir"


class _FetchWorker(ExitSafeQThread):
    """后台拉取 version.json；任何失败都只结束线程，不抛异常（静默边界）。

    退出自我收口（继承 :class:`gui.qt_exit_guard.ExitSafeQThread`）：无父控件，靠
    ``aboutToQuit`` → 幂等有界 ``stop()`` 收口；超时 detach + 强引用防 GC。
    """

    fetched = Signal(object)   # 成功：dict（原始 JSON）；失败不发信号
    failed = Signal()

    def __init__(self, url: str, timeout: int = CHECK_TIMEOUT_SECONDS, parent=None):
        super().__init__(parent)
        self._url = url
        self._timeout = timeout

    def run(self):  # pragma: no cover - 网络路径由集成测试覆盖
        try:
            import requests  # 延迟导入：更新检查失败不拖累启动
            resp = requests.get(self._url, timeout=self._timeout)
            if resp.status_code != 200:
                self.failed.emit()
                return
            data = json.loads(resp.text)
            if _valid_remote(data) is None:
                self.failed.emit()
                return
            self.fetched.emit(data)
        except Exception as exc:  # 离线 / 超时 / JSON 解析错误一律静默
            logger.info("更新检查失败（静默跳过）: %s", exc)
            self.failed.emit()


class UpdateChecker(QObject):
    """启动后异步检查更新。用法（gui/main.py）：

        checker = UpdateChecker(parent=window)                   # 默认 stable 频道
        checker = UpdateChecker(parent=window, channel=cfg.update_channel)
        checker.update_available.connect(show_update_prompt)    # 非阻断提示（R-D 保留）
        checker.check_finished.connect(on_check_finished)        # v2.0 三态结果
        checker.start()                # 自动检查（主窗口已显示后）
        checker.start(manual=True)     # 手动检查（不受忽略/24h 闸影响）

    信号 / 属性：
    - update_available(dict)：payload 即 evaluate_update() 的返回值。既有键
      （kind/version/notes/primary/mirror）契约零变更（R-D），v2.0 追加
      assets / min_updatable / release_url（纯增量，旧消费方只读既有键）。
    - check_finished(str)：v2.0 新增，三态 CHECK_UPDATE / CHECK_LATEST /
      CHECK_FAILED，供手动入口给出确定结果（L1-2 验收①）。
    - last_remote（只读属性）：最近一次成功拉取的**原始** version.json dict
      （含 assets/min_updatable/release_url），未成功过 → None。main.py 取
      assets/sha256/size 用此属性，勿再访问私有 `_worker`。
    """

    update_available = Signal(dict)
    check_finished = Signal(str)

    def __init__(self, parent=None, url: str = "", local_version: str = __version__,
                 channel: str = ""):
        super().__init__(parent)
        self._channel = resolve_channel(channel)
        # url 显式传入优先（测试 / 回归兼容）；空则按频道解析（D-V20-07）
        self._url = (url or "").strip() or resolve_channel_url(self._channel)
        self._local_version = local_version
        self._worker: Optional[_FetchWorker] = None
        self._manual = False
        # v2.0(修正1): 最近一次成功拉取的原始 version.json（含 assets/min_updatable/
        # release_url）；公开只读属性 last_remote 供 main.py 解耦取用，勿再摸私有 _worker。
        self._last_remote: Optional[dict] = None

    @property
    def last_remote(self) -> Optional[dict]:
        """最近一次成功拉取到的**原始** version.json dict；未成功过 → None。"""
        return self._last_remote

    @property
    def url(self) -> str:
        """当前生效的检查 URL（供测试 / 设置页展示）。"""
        return self._url

    @property
    def channel(self) -> str:
        """当前生效频道（供测试 / 设置页展示）。"""
        return self._channel

    def start(self, manual: bool = False):
        """启动异步检查（内部新建 QThread，不阻塞调用方）。

        manual=True 表示手动检查：结果不受「忽略此版本」与 24h 闸限制。
        """
        self._manual = bool(manual)
        # parent=self：worker 成为 checker 的 Qt 子对象 → checker 被销毁时由退出收口
        # 的父控件 destroyed 钩子先行停机（避免连坐析构运行中的 QThread）
        self._worker = _FetchWorker(self._url, parent=self)
        self._worker.fetched.connect(self._on_fetched)
        self._worker.failed.connect(self._on_failed)
        self._worker.start()

    def _on_fetched(self, remote: dict):
        # v2.0(修正1): 保存原始远端 dict（无论是否提示），供 last_remote 公开取用
        self._last_remote = remote
        try:
            state = load_update_state()
            ignored = state.get("ignored_version")
            result = evaluate_update(remote, self._local_version, ignored)
        except Exception as exc:  # 任何意外都不弹窗
            logger.info("更新检查评估失败（静默跳过）: %s", exc)
            self.check_finished.emit(CHECK_FAILED)
            return
        today = date.today().isoformat()
        # 成功检查：记录 last_checked + 生效频道镜像（D-V20-07 / §4.2）
        try:
            save_update_state({
                "last_checked": datetime.now().isoformat(timespec="seconds"),
                "channel": self._channel,
            })
        except Exception:
            pass
        if not result:
            self.check_finished.emit(CHECK_LATEST)
            return
        version = str(result.get("version") or "")
        if self._manual or should_prompt(state, version, today):
            try:
                save_update_state({"last_prompt_date": today})
            except Exception:
                pass
            self.update_available.emit(result)
            self.check_finished.emit(CHECK_UPDATE)
        else:
            self.check_finished.emit(CHECK_LATEST)

    def _on_failed(self):
        # 失败不更新 last_checked（下次启动可重试）；静默（R-A / L1-1 验收②）
        self.check_finished.emit(CHECK_FAILED)


def format_update_text(info: dict) -> str:
    """构造提示文案（GUI 非阻断提示用）。"""
    notes = info.get("notes") or []
    shown = "；".join(notes[:3]) if notes else "详见更新日志"
    if info.get("kind") == "reinstall":
        return (
            f"当前版本过旧（v{__version__}），建议重新下载安装最新版 "
            f"v{info['version']}：{shown}"
        )
    return f"发现新版本 v{info['version']}：{shown}"


def pick_download_link(info: dict) -> str:
    """「复制下载链接」的取链规则：主链失败/缺失降级备用链。"""
    primary = (info.get("primary") or "").strip()
    mirror = (info.get("mirror") or "").strip()
    if primary:
        return primary
    return mirror
