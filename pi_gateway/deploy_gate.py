# -*- coding: utf-8 -*-
"""pi_gateway/deploy_gate.py —— 门禁扩展部署脚本（可选路径）。

码铃 PiBackend 启动时以 `-e <pi_gateway/maling_gate.js>` 固定加载门禁扩展
（防漏载，主机制）。本脚本提供「持久化安装」到 Pi 全局扩展目录的可选方式：
    python pi_gateway/deploy_gate.py            # 复制到 ~/.pi/agent/extensions/
    python pi_gateway/deploy_gate.py --remove   # 卸载

注意：
- 持久化安装后所有 pi 会话（含终端手动启动的）都会加载本门禁；
  卸载请用 --remove，不要手工删除 ~/.pi 目录。
- 版本锁定 Pi 0.85.1；Pi 升级后须回归 tests/test_pi_backend.py。
"""
import shutil
import sys
from pathlib import Path

GATE_SRC = Path(__file__).resolve().parent / "maling_gate.js"


def pi_extensions_dir() -> Path:
    """Pi 配置目录（尊重 PI_CODING_AGENT_DIR 覆盖，默认 ~/.pi/agent）。"""
    import os

    base = os.environ.get("PI_CODING_AGENT_DIR") or str(
        Path.home() / ".pi" / "agent")
    return Path(base) / "extensions"


def main() -> int:
    if "--remove" in sys.argv:
        dst = pi_extensions_dir() / "maling_gate.js"
        if dst.exists():
            dst.unlink()
            print(f"已卸载门禁扩展: {dst}")
        else:
            print(f"未找到已安装的门禁扩展: {dst}")
        return 0
    if not GATE_SRC.exists():
        print(f"错误: 找不到门禁扩展源文件 {GATE_SRC}")
        return 1
    dst_dir = pi_extensions_dir()
    dst_dir.mkdir(parents=True, exist_ok=True)
    dst = dst_dir / "maling_gate.js"
    shutil.copy2(GATE_SRC, dst)
    print(f"门禁扩展已部署: {dst}")
    print("说明: 码铃 PiBackend 启动时仍以 -e 参数固定加载源文件，")
    print("      本持久化安装仅为覆盖手动 pi 会话的可选措施。")
    print("版本锁定: Pi 0.85.1（pi --version 检查；不符请")
    print("  npm install -g --ignore-scripts @earendil-works/pi-coding-agent@0.85.1）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
