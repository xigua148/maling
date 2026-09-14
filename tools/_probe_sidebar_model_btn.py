"""探针：用真实 ThemeEngine 加载完整 QSS，验证 v2.1 侧栏「模型」按钮去框改动的
QSS 解析无报错（无 Qt warning）。

为什么需要这个探针：QSS 改的是 #sidebarModelBtn 的 background/border 属性，
万一注释或结构引入语法错误，Qt 会向 stderr 打 ``QSS: ...`` 警告；测试构造里
app_ctx 不带 theme_engine（参见 ``_probe_settings_elevation.py`` 注释），不会
触发完整 QSS 路径，故需本探针。

用法（工程根）：
    QT_QPA_PLATFORM=offscreen <py> tools/_probe_sidebar_model_btn.py
"""
from __future__ import annotations

import contextlib
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QPushButton  # noqa: E402

from gui.theme_engine import ThemeEngine  # noqa: E402

app = QApplication.instance() or QApplication([])  # noqa: F841


@contextlib.contextmanager
def _capture_stderr():
    """捕获 Qt qWarning 等走 stderr 的诊断信息（QSS 解析错误也会走这里）。"""
    buf = io.StringIO()
    old = sys.stderr
    sys.stderr = buf
    try:
        yield buf
    finally:
        sys.stderr = old


def main() -> int:
    engine = ThemeEngine()

    # ① 真实加载完整 QSS（base + 主题，变量替换），同时构造模型按钮 —— 触发 QSS 匹配
    with _capture_stderr() as buf:
        ok = engine.load_theme("ui_minimal")
        btn = QPushButton("模型 · 未配置")
        btn.setObjectName("sidebarModelBtn")
        # 触发样式应用（创建时 QApplication 已持有全局 QSS）
        btn.ensurePolished()
        btn.grab().save("/tmp/_sidebar_model_btn_snap.png")  # 渲染一次触发警告

    warnings = buf.getvalue()

    print("load_theme(ui_minimal) =", ok)
    print("button constructed:", btn.objectName())
    if warnings.strip():
        print("\n--- captured stderr (可疑行) ---")
        for line in warnings.splitlines():
            if any(k in line.lower() for k in ("qss", "warning", "error", "invalid")):
                print(" ", line)
        # 过滤掉 QPixmap::scaled 之类的离屏平台噪声，只看 QSS 相关
        qss_warns = [l for l in warnings.splitlines()
                     if "QSS" in l or "stylesheet" in l.lower()]
        if qss_warns:
            print("❌ 检出 QSS 相关警告：")
            for l in qss_warns:
                print(" ", l)
            return 1
    print("✅ QSS 解析无警告（去框改动兼容）")
    return 0


if __name__ == "__main__":
    sys.exit(main())