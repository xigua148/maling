# -*- coding: utf-8 -*-
"""v2.2.5 设置页新增分区单测：内置酒馆（预热开关）与诊断（导出诊断包）。

⚠️ 副作用纪律：预热开关会在 ``stateChanged`` 时**立即写配置并落盘**。所以凡是会
触发 change 的用例，都必须先把 ``GuiConfig._config_path`` 指到临时目录 ——
否则测试会改掉开发者本机的真实 ``config.yaml``。
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from gui.config import GuiConfig
from gui.pages.page_settings import PageSettings
from gui.qt_compat import QApplication


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


@pytest.fixture
def sandbox_config(tmp_path, monkeypatch):
    """把 GuiConfig 的读写落到临时目录（防止测试污染真实配置文件）。"""
    monkeypatch.setattr(GuiConfig, "_config_path",
                        staticmethod(lambda: tmp_path / "gui_config.json"))
    return GuiConfig()


def _page(cfg) -> PageSettings:
    return PageSettings(SimpleNamespace(config=cfg, cfg=None))


class TestTavernSection:
    def test_switch_exists_and_defaults_on(self, qapp, sandbox_config):
        page = _page(sandbox_config)
        assert hasattr(page, "tavern_warmup_check"), "设置页缺少预热开关"
        assert page.tavern_warmup_check.isChecked() is True, "默认应开启预热"
        page.deleteLater()

    def test_switch_reflects_config_on_load(self, qapp, sandbox_config):
        sandbox_config.tavern_warmup = False
        sandbox_config.save()
        page = _page(GuiConfig.load())
        assert page.tavern_warmup_check.isChecked() is False, "关闭态应正确回显"
        page.deleteLater()

    def test_toggling_writes_config_and_persists(self, qapp, sandbox_config):
        page = _page(sandbox_config)
        page.tavern_warmup_check.setChecked(False)
        qapp.processEvents()
        assert sandbox_config.tavern_warmup is False, "开关应写进 GuiConfig"
        assert GuiConfig.load().tavern_warmup is False, "应已落盘"
        page.deleteLater()


class TestDiagnosticsSection:
    def test_button_exists(self, qapp, sandbox_config):
        page = _page(sandbox_config)
        assert hasattr(page, "diag_btn"), "设置页缺少导出诊断包按钮"
        assert page.diag_btn.text() == "导出诊断包"
        assert hasattr(page, "diag_hint")
        page.deleteLater()

    def test_export_writes_zip_and_reports_path(self, qapp, sandbox_config, tmp_path, monkeypatch):
        """点导出 → 真的产出 zip，且提示里带上文件名（不弹系统对话框、不联网）。"""
        import gui.diagnostics as diag

        monkeypatch.setattr(diag, "default_bundle_dir", lambda: tmp_path / "diag")
        page = _page(sandbox_config)
        page._on_export_diagnostics()
        hint = page.diag_hint.text()
        assert hint.startswith("已导出"), f"未导出成功：{hint}"
        produced = list((tmp_path / "diag").glob("maling_diagnostics_*.zip"))
        assert len(produced) == 1 and produced[0].stat().st_size > 0
        assert produced[0].name in hint
        page.deleteLater()

    def test_export_failure_is_readable_not_crash(self, qapp, sandbox_config, monkeypatch):
        """导出失败只改提示文案，绝不让设置页崩。"""
        import gui.diagnostics as diag

        def boom(**_kw):
            raise RuntimeError("磁盘满了")

        monkeypatch.setattr(diag, "build_bundle", boom)
        page = _page(sandbox_config)
        page._on_export_diagnostics()
        assert "导出失败" in page.diag_hint.text()
        assert "磁盘满了" in page.diag_hint.text()
        page.deleteLater()
