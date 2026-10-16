/**
 * Pi Agent 扩展：工具参数“帧”归一化（Schema 校验前执行）。
 *
 * 背景（BAPI-02 会话多轮踩坑）：模型偶尔把工具参数错误地包裹成：
 *   - bash: {arguments:'{"command":...}'}  （字符串帧）
 *   - bash: {arguments:{command:...}}       （对象帧）
 *   - write/edit 同理：{arguments:{path,content}} 等
 * 这类畸形调用在 Pi 内置工具的 Schema 校验阶段即失败（InputValidationError），
 * 模型随后反复重试，浪费大量 token。
 *
 * 本扩展通过 `pi.registerTool` 以同名覆盖内置 read/write/edit/bash 工具：
 *   - 复用内置工厂（createReadToolDefinition / createWriteToolDefinition /
 *     createEditToolDefinition / createBashToolDefinition）构造的完整实现，
 *     保留原 Schema、执行逻辑、渲染、constrainedSampling 与 Shell 选项；
 *   - 仅额外挂一个 `prepareArguments`，在 Schema 校验【之前】做有限归一化：
 *       1) {arguments:"{...}"}（字符串帧）→ 解包为对象；
 *       2) {arguments:{...}}（对象帧）→ 解包为对象；
 *       3) {commands:{command:...}} 类多余帧（值再包一层）→ 顶层字段提升。
 *   prepareArguments 返回新对象才会生效（agent-loop.js prepareToolCallArguments
 *   用引用比较判定是否替换）；不命中任何帧时原样返回，不产生任何副作用。
 *
 * 归一化原则（相对旧版的关键收敛）：
 *   - 只解包“多余的 arguments/commands 帧”，不做 path/edits/content 的深度改写；
 *   - 不再在 tool_call（校验后）事件里改 input —— 那在 Pi 1.2.0 中已无法救回
 *     校验失败，且文档明确 “No re-validation is performed after mutation”；
 *   - 不再机械阻断缺字段调用（阻断会打断模型修复节奏，交由 Schema 校验自然报错）。
 *
 * 部署：放到 ~/.pi/agent/extensions/arg-frame-fix.ts，重启 pi 即生效。
 * 无第三方依赖。
 */
import type {
	ExtensionAPI,
	ToolDefinition,
} from "@earendil-works/pi-coding-agent";
import {
	createBashToolDefinition,
	createEditToolDefinition,
	createReadToolDefinition,
	createWriteToolDefinition,
} from "@earendil-works/pi-coding-agent";

function isPlainObject(v: unknown): v is Record<string, unknown> {
	return typeof v === "object" && v !== null && !Array.isArray(v);
}

function parseJsonLike(s: string): unknown {
	const t = s.trim();
	if (!t) return null;
	if (!t.startsWith("{") && !t.startsWith("[")) return null; // 仅解析对象/数组串，避免误解析普通文本
	try {
		return JSON.parse(t);
	} catch {
		return null;
	}
}

/**
 * 解包“多余的帧”。命中时返回新对象，未命中返回原引用（prepareArguments
 * 依赖引用比较决定是否替换，见 agent-loop.js prepareToolCallArguments）。
 *
 * 处理的帧形态：
 *   - 顶层只有 {arguments: "{...}"}（字符串帧）→ 解包为解析出的对象；
 *   - 顶层只有 {arguments: {...}}（对象帧）→ 解包为内层对象；
 *   - 顶层 arguments 为对象/字符串，且缺少必需字段时，把帧内字段提升到顶层
 *     （顶层已有同名字段则保留顶层，不覆盖）；
 *   - bash 特有 {commands: {...}} 值再包一层 → 把内层 command 提升到顶层。
 */
function unwrapFrames(input: unknown, required: readonly string[]): unknown {
	if (!isPlainObject(input)) return input;
	const args = input;

	// 1) 字符串帧：{arguments: "{...}"} 或 {commands: "{...}"}
	for (const key of ["arguments", "args", "commands"] as const) {
		if (typeof args[key] === "string" && Object.keys(args).length === 1) {
			const parsed = parseJsonLike(args[key]);
			if (parsed !== null && isPlainObject(parsed)) return parsed;
		}
	}

	// 2) 对象帧：{arguments: {...}} 或 {args: {...}}（顶层仅此一帧时直接解包）
	for (const key of ["arguments", "args"] as const) {
		if (isPlainObject(args[key]) && Object.keys(args).length === 1) {
			return args[key];
		}
	}

	// 3) 值再包一层：顶层同时存在多余帧与(部分)顶层字段。
	//    仅当顶层缺必需字段时，从 arguments/args/payload/input 帧提升字段到顶层。
	let fixed = false;
	const out: Record<string, unknown> = { ...args };
	for (const key of ["arguments", "args", "payload", "input", "commands"] as const) {
		const raw = out[key];
		let inner: Record<string, unknown> | null = null;
		if (isPlainObject(raw)) inner = raw;
		else if (typeof raw === "string") {
			const parsed = parseJsonLike(raw);
			if (isPlainObject(parsed)) inner = parsed;
		}
		if (!inner) continue;
		for (const k of required) {
			if (out[k] === undefined && inner[k] !== undefined) {
				out[k] = inner[k];
				fixed = true;
			}
		}
	}
	if (!fixed) return input;
	// 提升成功后移除已被吸收的空帧，避免残留多余字段干扰 Schema 校验。
	for (const key of ["arguments", "args", "payload", "input", "commands"] as const) {
		if (isPlainObject(out[key]) && Object.keys(out[key] as Record<string, unknown>).length === 0) {
			delete out[key];
		}
	}
	return out;
}

/** 每个被归一化工具的“必需字段”，用于帧提升判断（不用于阻断）。 */
const REQUIRED: Record<string, readonly string[]> = {
	bash: ["command"],
	powershell: ["command"],
	write: ["path", "content"],
	edit: ["path", "edits"],
	read: ["path"],
};

/** 给工具定义挂上 prepareArguments（未命中帧时原样返回，无副作用）。 */
function withFrameFix<T extends ToolDefinition<any, any, any>>(def: T, required: readonly string[]): T {
	const original = def.prepareArguments;
	const prepared = (args: unknown) => {
		const unwrapped = unwrapFrames(args, required);
		if (unwrapped !== args) return unwrapped;
		return original ? (original(args) as unknown) : args;
	};
	return { ...def, prepareArguments: prepared };
}

export default function (pi: ExtensionAPI): void {
	const cwd = pi.cwd;

	// 注意：不能在扩展加载阶段调用 pi.getSettings() —— Pi 1.2.0 在加载期
	// 以 throwing stub 拒绝所有 action 方法（loader.js createExtensionRuntime，
	// 报 "Extension runtime not initialized"）。本机无自定义 shellPath/
	// shellCommandPrefix，createBashToolDefinition 默认 bash 即已生效选项；
	// 若需自定义 shell，可后续改用事件回调（如 session_start）里读取 settings
	// 再动态注册，或经 registerFlag 传入。
	// 复用内置工厂构造完整工具定义，仅补 prepareArguments 帧归一化。
	pi.registerTool(withFrameFix(createReadToolDefinition(cwd), REQUIRED.read));
	pi.registerTool(withFrameFix(createWriteToolDefinition(cwd), REQUIRED.write));
	pi.registerTool(withFrameFix(createEditToolDefinition(cwd), REQUIRED.edit));
	pi.registerTool(
		withFrameFix(
			createBashToolDefinition(cwd, { exposeSessionEnvironment: true }),
			REQUIRED.bash
		)
	);
}
