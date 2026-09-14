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
