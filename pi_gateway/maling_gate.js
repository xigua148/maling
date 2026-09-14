/**
 * maling_gate.js —— 码铃授权门禁扩展（Pi 编程引擎试点，v1.7.2 T2）
 *
 * 目标：把码铃 AgentTools 的授权语义移植到 Pi 侧，保证两条引擎安全基线一致：
 *   1. 工作区白名单：workspace（环境变量 MALING_GATE_WORKSPACE 指定）内的
 *      文件写改自动放行；越界路径 → 弹 confirm（RPC 下即 extension_ui_request，
 *      由码铃授权弹窗裁决），拒绝/无 UI 一律 block（fail-safe）。
 *   2. 命令白名单：bash/powershell 首词 ∈ {python, python3, pytest, node} 且
 *      不含 shell 元字符 → 自动放行；其余 → confirm 裁决（对齐码铃 run_command
 *      白名单 + 授权弹窗语义，见 command_runner.py）。
 *   3. 只读工具（read/grep/find/ls）零拦截。
 *
 * 版本锁定：Pi 0.85.1（extension UI 子协议随版本可能变化，升级须回归
 * tests/test_pi_backend.py 的门禁端到端用例）。
 * 加载方式：码铃 PiBackend 启动参数固定携带 `-e <本文件路径>`（部署脚本
 * deploy_gate.py 仅提供持久化安装的可选路径，引擎内以 -e 为准，防漏载）。
 */
import { isAbsolute, join, normalize, relative } from "node:path";

const CMD_ALLOW = new Set(["python", "python3", "pytest", "node"]);
// run_command 同款元字符拒绝：无 shell/管道/重定向（对齐 command_runner.py）
const META = /[;|&><`$]/;

function pathInWorkspace(p, workspace) {
	if (!workspace) return false;
	const abs = isAbsolute(p) ? p : join(workspace, p);
	const rel = relative(normalize(workspace), normalize(abs));
	if (rel.startsWith("..") || isAbsolute(rel)) return false;
	// 不要求目标存在（写新文件场景），仅做路径包含判定
	return true;
}

function firstToken(cmd) {
	return (cmd || "").trim().split(/\s+/)[0] || "";
}

function isWhitelistedCommand(cmd) {
	const t = firstToken(cmd).toLowerCase();
	return CMD_ALLOW.has(t) && !META.test(cmd);
}

export default function (pi) {
	const WORKSPACE = (process.env.MALING_GATE_WORKSPACE || "").trim();

	pi.on("tool_call", async (event, ctx) => {
		const name = event.toolName;

		// 1) 只读工具零拦截
		if (["read", "grep", "find", "ls"].includes(name)) return;

		// 2) 文件写改类：workspace 内自动放行，越界走 confirm
		if (["write", "edit"].includes(name)) {
			const target = String((event.input && (event.input.path || event.input.filepath)) || "");
			if (target && pathInWorkspace(target, WORKSPACE)) return; // 白名单内自动放行
			if (!ctx.hasUI) {
				return { block: true, reason: `目标不在工作区白名单且无确认渠道: ${target}` };
			}
			const ok = await ctx.ui.confirm(
				"码铃授权确认",
				`工具 [${name}] 请求访问工作区外的路径：\n${target}\n是否允许？`,
			);
			if (!ok) {
				ctx.ui.notify("已按用户授权拒绝该操作", "warning");
				return { block: true, reason: "用户在授权弹窗中拒绝" };
			}
			return;
		}

		// 3) 命令执行类：白名单命令自动放行，其余走 confirm
		if (["bash", "powershell"].includes(name)) {
			const cmd = String((event.input && (event.input.command || "")) || "");
			if (cmd && isWhitelistedCommand(cmd)) return; // python/pytest/node 直行
			if (!ctx.hasUI) {
				return { block: true, reason: `命令不在白名单且无确认渠道: ${cmd.slice(0, 80)}` };
			}
			const ok = await ctx.ui.confirm(
				"码铃授权确认",
				`工具 [${name}] 请求执行非白名单命令：\n${cmd.slice(0, 200)}\n是否允许？`,
			);
			if (!ok) {
				ctx.ui.notify("已按用户授权拒绝该操作", "warning");
				return { block: true, reason: "用户在授权弹窗中拒绝" };
			}
			return;
		}

		// 4) 其余扩展/内置工具：保守放行（试点范围仅覆盖上述三类）
	});
}
