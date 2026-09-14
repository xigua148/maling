"""v2.1 bug 修复验证：onboarding 主题选择能正确更新 ``_selected_theme``。

**Bug 根因**
``theme_preview.theme_selected`` 信号（onboarding.py:278 声明、:337 发射）此前**全文件无任何
``connect()``** —— 用户在「主题选择」步骤点「选择此风格」后信号发出去没人收，
``_selected_theme`` 停留在默认值 ``ui_minimal``（onboarding.py:358），
「完成」时（onboarding.py:490-507）应用的仍是默认主题，用户感知「选了不生效」。

**本探针**
直接构造 ``OnboardingDialog`` → 发射 ``theme_preview.theme_selected("ui_cream")`` → 验证
``_selected_theme`` 被更新为 ``ui_cream``（修复前会停在 ``ui_minimal``）。
绕开 ``_select_theme`` 内的 ``QMessageBox.information``（模态弹窗会阻塞自动化）。

用法（工程根）：
    QT_QPA_PLATFORM=offscreen <py> tools/_probe_onboarding_theme.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from types import SimpleNamespace  # noqa: E402

from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication([])  # noqa: F841

from gui.config import GuiConfig  # noqa: E402
from gui.theme_engine import ThemeEngine  # noqa: E402
from gui.pages.onboarding import OnboardingDialog  # noqa: E402


def main() -> int:
    engine = ThemeEngine()
    app_ctx = SimpleNamespace(config=GuiConfig(), theme_engine=engine)
    dlg = OnboardingDialog(app_ctx)

    print("① 初始 _selected_theme =", dlg._selected_theme)
    assert dlg._selected_theme == "ui_minimal", "默认值应是 ui_minimal"

    # 直接发射选择信号（绕开 QMessageBox 弹窗）
    dlg.theme_preview.theme_selected.emit("ui_cream")
    print("② 发射 theme_selected('ui_cream') 后 _selected_theme =",
          dlg._selected_theme)

    # 再换一次，确认不是「一次性」覆盖
    dlg.theme_preview.theme_selected.emit("ui_night")
    print("③ 再发射 theme_selected('ui_night') 后 _selected_theme =",
          dlg._selected_theme)

    if dlg._selected_theme == "ui_night":
        print("✅ 修复生效：信号被 _on_theme_selected 接住并实时更新 _selected_theme")
        return 0
    print("❌ 修复未生效：_selected_theme 未被更新（bug 仍在）")
    return 1


if __name__ == "__main__":
    sys.exit(main())