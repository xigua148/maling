"""tests/conftest.py —— 共享 fixtures。

所有测试共用：临时 workspace、mock AppConfig、mock Logger。
"""
import json
import logging
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# 确保项目根目录在 sys.path
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture
def tmp_workspace(tmp_path):
    """临时 workspace 目录，含几个示例文件。"""
    (tmp_path / "hello.py").write_text("print('hello')\n", encoding="utf-8")
    (tmp_path / "data.json").write_text('{"key": "value"}\n', encoding="utf-8")
    sub = tmp_path / "subdir"
    sub.mkdir()
    (sub / "nested.txt").write_text("nested content\n", encoding="utf-8")
    return tmp_path


@pytest.fixture
def mock_cfg(tmp_workspace):
    """最小化 mock AppConfig，覆盖 Agent/安全/格式化需要的字段。"""
    cfg = MagicMock()
    cfg.workspace = str(tmp_workspace)
    cfg.api_url = "https://api.deepseek.com/chat/completions"
    cfg.api_model = "deepseek-chat"
    cfg.api_key = "sk-test-key"
    cfg.api_keys = ["sk-test-key"]
    cfg.api_provider = "deepseek"
    cfg.api_max_tokens = 2048
    cfg.api_temperature = 0.7
    cfg.api_retry_times = 1
    cfg.code_exec_timeout = 10
    cfg.web_search_max_results = 5
    cfg.agent_enabled = True
    cfg.agent_max_steps = 4
    cfg.agent_max_retries = 2
    cfg.stream_mode = True
    return cfg


@pytest.fixture
def logger():
    """测试用 Logger（DEBUG 级别，输出到 stdout）。"""
    log = logging.getLogger("test.maling")
    log.setLevel(logging.DEBUG)
    if not log.handlers:
        handler = logging.StreamHandler()
        handler.setLevel(logging.DEBUG)
        log.addHandler(handler)
    return log


# ---------------------------------------------------------------------------
# Qt 控件累积治理（v2.1 测试基建）
# ---------------------------------------------------------------------------
# 背景：GUI 用例每例都会新建大量控件 —— 单个 ``PageSettings`` 约 320 个，其中
# 11 个 ``QComboBox`` 的弹出层是「有父控件、但仍是顶层窗口」的 ``QFrame``。
# 这些控件因信号闭包形成的引用环而**不被回收**（实测 ``gc.collect()`` 也收不掉），
# 于是进程内控件数随用例线性增长（12 个用例后即达 5299 个 / 208 个顶层窗口）。
# 而 ``ThemeEngine.load_theme()`` 每次都要 ``app.setStyleSheet()`` 重新 polish
# **全部**存活控件 —— 越跑越慢（v21 尾部 164 例单跑约 75s，其中构造一次主窗约 60s），
# 全量套件因此超出单命令时限而被中断。
#
# 处置：每例收尾销毁「本用例新建、无父窗口」的顶层控件，并 flush 延迟删除。
# module/class 级 fixture 产出的控件天然豁免：其作用域高于本 function 级 fixture，
# 在下面 ``before`` 快照建立**之前**就已创建（pytest 先装配高作用域 fixture），
# 故其 id 恒在 ``before`` 中、必被跳过 —— 无需任何显式登记。
@pytest.fixture(autouse=True)
def _qt_widget_cleanup():
    """每例收尾销毁本用例新建的顶层控件，抑制跨用例累积（详见本节注释）。"""
    try:
        from gui.qt_compat import QApplication, QEvent
    except Exception:  # pragma: no cover - 无 PySide6 环境
        yield
        return

    app = QApplication.instance()
    if app is None:  # 纯逻辑用例：没有 QApplication，无需清理
        yield
        return

    before = {id(w) for w in app.topLevelWidgets()}
    try:
        yield
    finally:
        try:
            for w in list(app.topLevelWidgets()):
                if id(w) in before:
                    continue
                if w.parent() is not None:
                    # 弹出层等子窗口：随宿主控件一起销毁；单独删会留下悬空指针
                    continue
                try:
                    w.close()
                    w.deleteLater()
                except Exception:
                    pass
            # 立即 flush 延迟删除，否则要等下一次事件循环才真正释放
            QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        except Exception:
            pass


