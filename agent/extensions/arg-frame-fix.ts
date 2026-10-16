/**
 * Pi Agent 扩展：工具参数“帧”强制规范化 + 不可恢复畸形调用机械阻断（机制级硬约束）。
 *
 * 背景（BAPI-02 会话多轮踩坑）：模型偶尔把工具参数错误地包裹成：
 *   - 一个多余的 "arguments" 帧（字符串或对象）：bash:{arguments:'{"command":...}'}
 *   - 值再被包一层：write:{path:{path:...}} 或 edit:{edits:"[{...}]"/单个对象}
 *   - 最严重：整个 input 是空对象 {} 或缺少必需字段（如 write 只有 content 没有 path）
 * 这使得内置工具报 “path/command must have required properties” 并反复重试。
 *
 * 本扩展分两层处理：
 *   1) 可恢复帧（frame/deep/字符串化）→ 就地改写 event.input 顶层字段，组件层规范化。
 *   2) 不可恢复缺必需字段（空 {}、缺 path 等，无从推断值）→ 直接 return {block:true}
 *      阻断该调用，并输出具体缺哪个字段的诊断；坏调用根本不执行，杜绝"空转一轮校验失败"。
 *
 * 部署：放到 ~/.pi/agent/extensions/arg-frame-fix.ts，重启 pi 即生效。
 * 无第三方依赖，纯就地 JSON 字段重排 + 事件级机械阻断。
 */
import type {
	ExtensionAPI,
	ToolCallEvent,
	ToolCallEventResult,
} from "@earendil-works/pi-coding-agent";

/** 需要强制存在必需字段的工具（read/grep/find/ls 无严格必需字段，不阻断）。 */
const REQUIRED: Record<string, string[]> = {
	bash: ["command"],
	powershell: ["command"],
	write: ["path", "content"],
	edit: ["path", "edits"],
};

/** 每个工具可读字段的非空约束：path/command/content 不得为空串/纯空白。 */
const NON_EMPTY: Record<string, string[]> = {
	bash: ["command"],
	powershell: ["command"],
	write: ["path", "content"],
	edit: ["path"],
};

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
 * 深度修复“值再被包一层”的形态：
 *   - path 本身是对象（{ path: { path: '...' } }）→ 取字符串子字段；
 *   - edits 是 JSON 字符串 → 解析成数组；edits 是单个对象 → 包装成数组；
 *   - content 是 JSON 对象/数组串 → 解析（普通 markdown 文本不会被误解析）。
 * 仅在没有顶层正确字段时才修正；正常参数保持不变。
 */
function deepFixFrames(_tool: string, input: Record<string, unknown>): void {
	if (input.path !== undefined && isPlainObject(input.path)) {
		for (const k of ["path", "file", "f"]) {
			const v = input.path[k];
			if (typeof v === "string") {
				input.path = v;
				break;
			}
		}
	}
	if (typeof input.edits === "string") {
		const v = parseJsonLike(input.edits);
		if (Array.isArray(v)) input.edits = v;
	}
	if (isPlainObject(input.edits) && typeof (input.edits as Record<string, unknown>).oldText === "string") {
		input.edits = [input.edits];
	}
	if (typeof input.content === "string") {
		const v = parseJsonLike(input.content);
		if (v && !Array.isArray(v)) input.content = v;
	}
}

/** 把命名帧里的缺失必需字段提升到顶层（顶层已有键优先，不覆盖）。返回是否修复。 */
function liftFromFrames(input: Record<string, unknown>, required: string[]): boolean {
	const candidates: Record<string, unknown>[] = [];
	for (const f of ["arguments", "args", "payload", "input"]) {
		if (!(f in input)) continue;
		const raw = input[f];
		if (isPlainObject(raw)) candidates.push(raw);
		else if (typeof raw === "string") {
			const o = parseJsonLike(raw);
			if (o && isPlainObject(o)) candidates.push(o);
		}
	}
	let fixed = false;
	for (const c of candidates) {
		for (const k of required) {
			if (input[k] === undefined && c[k] !== undefined) {
				input[k] = c[k];
				fixed = true;
			}
		}
	}
	if (fixed) {
		delete input.arguments;
		if ("args" in input && (input.args === undefined || JSON.stringify(input.args) === JSON.stringify({}))) {
			delete input.args;
		}
	}
	return fixed;
}

function dump(o: unknown): string {
	try {
		return JSON.stringify(o);
	} catch {
		return String(o);
	}
}

export default function (pi: ExtensionAPI): void {
	pi.on(
		"tool_call",
		(event: ToolCallEvent & { input?: Record<string, unknown> }, _ctx): ToolCallEventResult | undefined => {
			const input = event.input;
			if (!isPlainObject(input)) return undefined;

			const required = REQUIRED[event.toolName];
			if (required) {
				// 1) 值再包一层 / 字符串化 edits / path 对象化：无条件深度修复
				deepFixFrames(event.toolName, input);
				// 2) 帧解包：若顶层缺必需字段，从 arguments/args/payload/input 帧提升
				liftFromFrames(input, required);
			}

			// 非严格必需的工具：不阻断
			if (!required) return undefined;

			// 3) 硬约束：缺必需字段或必填为空 → 阻断，杜绝空转校验失败
			const missing: string[] = required.filter(
				(k) => input[k] === undefined || (NON_EMPTY[event.toolName]?.includes(k) && typeof input[k] === "string" && !input[k].toString().trim())
			);
			if (missing.length > 0) {
				const reason =
					`[arg-frame-fix] ${event.toolName} 调用被硬约束阻断：缺少必需字段 ${missing.join(",")}。` +
					`请补齐为 ${event.toolName === "write" ? "{ path, content }" : event.toolName === "edit" ? "{ path, edits:[{oldText,newText}] }" : "{ command }"} 的顶层字段。` +
					`原始 input=${dump(input)}`;
				console.error(reason);
				return { block: true, reason };
			}
			return undefined;
		}
	);
}
