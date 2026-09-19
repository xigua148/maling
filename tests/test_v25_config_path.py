"""tests/test_v25_config_path.py —— v2.5 配置路径锚定与原子写加固。

对应决策：
- D-V25-08 应用根解析（根治「工作目录决定 config.yaml 位置」）
- D-V25-02 原子写临时文件名唯一化（消除跨进程撞名导致的混合内容）

测试数据隔离：一律 tmp_path（共享知识 23）。
"""
import json
import os
import sys
import threading
from pathlib import Path

import pytest


class TestAppRootResolution:
    """D-V25-08：resolve_app_root / resolve_config_path。"""

    def test_source_mode_root_is_repo_root(self):
        """源码形态：应用根 = 项目根（含 core/ 的那一级）。"""
        from core.path_guard import resolve_app_root, resolve_config_path
        root = resolve_app_root()
        assert (root / "core" / "path_guard.py").exists()
        assert (root / "memory.py").exists()
        assert resolve_config_path() == root / "config.yaml"

    def test_frozen_mode_uses_exe_dir(self, monkeypatch):
        """打包形态：应用根 = 可执行文件所在目录（不是 _MEIPASS）。

        onedir/onefile 同为 exe 旁 —— 这正是既有安装包里 config.yaml 的位置，
        故对既有安装零迁移。
        """
        from core.path_guard import resolve_app_root, resolve_config_path
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.setattr(sys, "executable", str(Path("D:/fake/install/maling.exe")))
        assert resolve_app_root() == Path("D:/fake/install")
        assert resolve_config_path() == Path("D:/fake/install/config.yaml")

    def test_resolution_independent_of_cwd(self, tmp_path, monkeypatch):
        """核心保证：换工作目录不改变解析结果（原实现会跟着漂）。"""
        from core.path_guard import resolve_config_path
        before = resolve_config_path()
        monkeypatch.chdir(tmp_path)
        assert resolve_config_path() == before

    def test_no_bare_relative_config_path_left(self):
        """回归护栏：源码中不得再出现裸相对 `Path("config.yaml")` 解析。

        这是「一次修掉一整类坑」的防线——新增调用点若忘了用 resolve_config_path，
        本用例会红。
        """
        root = Path(__file__).resolve().parent.parent
        targets = []
        for sub in ("core", "gui", "*"):
            targets.extend(root.glob(f"{sub}/*.py") if sub != "*" else root.glob("*.py"))
        offenders = []
        for f in targets:
            if f.name in ("path_guard.py",):
                continue
            for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
                if 'Path("config.yaml")' in line and "resolve_config_path" not in line:
                    offenders.append(f"{f.relative_to(root)}:{i}")
                if 'open("config.yaml"' in line or 'exists("config.yaml")' in line:
                    offenders.append(f"{f.relative_to(root)}:{i}")
        assert offenders == [], f"仍有裸相对 config.yaml 解析：{offenders}"


class TestAtomicWriteHardening:
    """D-V25-02：_atomic_write_json 临时文件名唯一化 + 失败清理。"""

    def test_no_tmp_left_after_success(self, tmp_path):
        from utils import _atomic_write_json
        p = str(tmp_path / "x.json")
        _atomic_write_json(p, {"a": 1})
        assert os.path.exists(p)
        assert json.loads(Path(p).read_text(encoding="utf-8")) == {"a": 1}
        assert [f for f in os.listdir(tmp_path) if ".tmp" in f] == []

    def test_tmp_name_carries_pid_and_tid(self):
        """临时名带 pid+线程 id 后缀 —— 两个写者不再撞同一个文件。"""
        import utils
        src = Path(utils.__file__).read_text(encoding="utf-8")
        assert "threading.get_ident()" in src
        assert "%s.tmp.%d.%d" in src

    def test_failed_write_cleans_up_tmp(self, tmp_path):
        from utils import _atomic_write_json

        class _Bad:
            pass

        p = str(tmp_path / "y.json")
        with pytest.raises(TypeError):
            _atomic_write_json(p, {"bad": _Bad()})
        # 不留垃圾临时文件
        assert [f for f in os.listdir(tmp_path) if ".tmp" in f] == []

    def test_concurrent_writes_never_interleave(self, tmp_path):
        """多线程并发写：最终文件必须是**某一完整份**，不能是交错的混合内容。

        Windows 下并发 replace 同一目标可能撞共享冲突（WinError 5）——
        _atomic_write_json 内置有界重试吸收之；本用例同时验证重试有效
        （不产生未捕获异常）与内容完整性。
        """
        from utils import _atomic_write_json
        p = str(tmp_path / "c.json")
        errors: list = []

        def worker(n: int) -> None:
            try:
                for i in range(40):
                    _atomic_write_json(p, {"n": n, "i": i, "pad": "x" * 500})
            except Exception as exc:                 # pragma: no cover
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(k,)) for k in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == [], f"并发写出现未吸收异常：{errors[:2]}"
        data = json.loads(Path(p).read_text(encoding="utf-8"))   # 必须可解析
        assert data["n"] in (0, 1, 2, 3)
        assert data["pad"] == "x" * 500                          # 结构完整，无截断
        assert [f for f in os.listdir(tmp_path) if ".tmp" in f] == []
