"""探针：验证设置页各分区是否都已挂上投影（v2.1 UI-P2 铺开验证）。

**为什么必须有这个探针**
``elevation.apply_card_shadow()`` 在「主题无 shadow / 解析失败 / 无 theme_engine」时
是**静默跳过**（R-Q 静默降级）—— 代码看起来改对了，但界面上可能一个阴影都没有。
而测试里的 ``app_ctx`` 是 ``SimpleNamespace(config=..., cfg=None)``，**不含
theme_engine**，那种构造下投影必然不挂载，测试全绿也证明不了效果。
故本探针用**真实 ThemeEngine** 构造设置页，实测挂载数。

用法（工程根执行）：
    QT_QPA_PLATFORM=offscreen <py> tools/_probe_settings_elevation.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from types import SimpleNamespace  # noqa: E402

from PySide6.QtWidgets import QApplication, QFrame  # noqa: E402

app = QApplication.instance() or QApplication([])  # noqa: F841

from gui.config import GuiConfig  # noqa: E402
from gui.qt_compat import QGraphicsDropShadowEffect  # noqa: E402
from gui.theme_engine import ThemeEngine  # noqa: E402
from gui import elevation  # noqa: E402
from gui.pages.page_settings import PageSettings  # noqa: E402


def main() -> int:
    engine = ThemeEngine()

    # ① 真实主题的 shadow 能否解析 —— 解析失败则整条链路静默 no-op
    parsed = elevation.current_shadow(engine)
    print("① current_shadow(真实主题) =", parsed)
    if parsed is None:
        print("   ❌ 主题 shadow 解析失败 → 投影不会挂载，改动无任何视觉效果！")
        return 1
    print("   ✅ 可解析（offset=%s,%s css_blur=%s）" % (parsed[0], parsed[1], parsed[2]))

    # ② 真实构造设置页（带 theme_engine —— 测试里的 app_ctx 没有它）
    page = PageSettings(
        SimpleNamespace(config=GuiConfig(), cfg=None, theme_engine=engine))

    # ③ 统计分区与投影
    sections = [w for w in page.findChildren(QFrame)
                if w.objectName() == "settingsSection"]
    shadowed = [w for w in sections
                if isinstance(w.graphicsEffect(), QGraphicsDropShadowEffect)]

    print("② 设置页分区总数（objectName=settingsSection） =", len(sections))
    print("③ 已挂投影的分区数                            =", len(shadowed))
    print("④ elevation.mounted_count() 全局登记数        =", elevation.mounted_count())

    ok = len(sections) > 0 and len(shadowed) == len(sections)
    print()
    if ok:
        print("✅ 全部 %d 个分区均已挂载投影（铺开成功）" % len(sections))
    else:
        print("❌ 挂载不全：%d/%d" % (len(shadowed), len(sections)))

    # ⑤ 换肤后是否仍全部保持（验证 refresh_all 覆盖新挂载点）
    try:
        refreshed = elevation.refresh_all()
        after = [w for w in sections
                 if isinstance(w.graphicsEffect(), QGraphicsDropShadowEffect)]
        print("⑤ refresh_all() 返回 =", refreshed, "；换肤后仍挂 =", len(after))
        if len(after) != len(sections):
            print("   ⚠ 换肤后投影数发生变化，需检查 refresh_all 覆盖")
    except Exception as exc:  # pragma: no cover
        print("⑤ refresh_all 异常：", exc)

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
