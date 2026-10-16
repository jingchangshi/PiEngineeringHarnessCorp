/**
 * Pi Agent 1.2.0 扩展：在状态栏/Footer 显示当前账户 Credit left（Quota 剩余）。
 *
 * 数据来源：与 codeagentcli 右下角 "Credit left" 同一 API（已验证可达）：
 *   GET https://{host}/api/v1/quota/usage
 *   header: x-auth-token（= decrypt-token.py xAuthToken 解密结果，与 snapengine-proxy 同 token）
 *           plugin-version
 *   响应:   { quotas:[{type, used_quota, total_quota, usage_ratio,
 *                      reset_at, message_en, message_cn}], show_link, message_en, message_cn }
 *
 *   真实（prod-szv-y）返回示例：
 *     CPM        used 964.57 / 20000   (月，reset 2026-11-01)   usage_ratio 0.0482 -> 5%
 *     CPD_Peak   used 7.69  / 2500     (日，reset 2026-10-16)   usage_ratio 0.0030
 *     CPD_Valley used 6.71  / 2500     (日，reset 2026-10-16)   usage_ratio 0.0026
 *
 * 说明：内网网关使用私有 CA，Node 内置 fetch 会因 TLS 证书校验失败，
 *       因此必须用 https.request + rejectUnauthorized:false（与 curl -k 等价）。
 *
 * 展示策略：优先选月度配额(CPM)作为 "Credit left"，回落时取 usage_ratio 最高项，
 * 剩余 = total_quota - used_quota，百分比 = usage_ratio * 100。
 *
 * 部署：
 *   1. 复制/软链本文件到 ~/.pi/agent/extensions/credit-status.ts
 *      （或任意 personal/project extensions 目录，见 docs/extensions.md）
 *   2. 重启 pi（加载扩展需在进程启动时）。状态栏出现 "Credit left: ..." 并周期刷新。
 *
 * 依赖：node 内置 https + spawn decrypt-token.py 取 token，无第三方依赖。
 * 只读用户自身凭证与只读 API，不做任何写操作。
 */
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

// 已验证可达的 prod yellow zone 网关（与 codeagent-proxy 一致）
const QUOTA_HOST = "snapengine.cida.cce.prod-szv-y.dragon.tools.huawei.com";
const DECRYPT = "/home/shijingchang/workspace/codeagent-proxy/decrypt-token.py";
const REFRESH_MS = 60_000; // 刷新间隔（配额按分钟/小时/天/月重置，60s 足够）

// 用 node 内置 https + 忽略 TLS 证书校验（内网私有 CA，等价 curl -k）
const https = require("node:https");

function getToken(): string | null {
	try {
		const { execFileSync } = require("node:child_process");
		const out = execFileSync("python3", [DECRYPT, "xAuthToken"], {
			encoding: "utf8",
			timeout: 20_000,
		});
		const t = out.trim();
		return t || null;
	} catch {
		return null;
	}
}

function fetchQuota(token: string, timeoutMs = 15000): Promise<any> {
	return new Promise((resolve, reject) => {
		const req = https.request(
			{
				hostname: QUOTA_HOST,
				path: "/api/v1/quota/usage",
				method: "GET",
				rejectUnauthorized: false, // 内网私有 CA
				headers: {
					"Content-Type": "application/json",
					"x-auth-token": token,
					"plugin-version": "pi-1.2.0",
				},
			},
			(res) => {
				let body = "";
				res.on("data", (c) => (body += c));
				res.on("end", () => {
					if (res.statusCode !== 200) {
						reject(new Error(`http ${res.statusCode}`));
						return;
					}
					try {
						resolve(JSON.parse(body));
					} catch (e) {
						reject(e);
					}
				});
			}
		);
		req.setTimeout(timeoutMs, () => {
			req.destroy(new Error("timeout"));
		});
		req.on("error", reject);
		req.end();
	});
}

interface QuotaItem {
	type?: string;
	used_quota?: number;
	total_quota?: number;
	usage_ratio?: number;
	remaining_quota?: number;
	reset_at?: string;
}

interface QuotaResp {
	quotas?: QuotaItem[];
	message_cn?: string;
	message_en?: string;
}

// 选一个用于展示的配额项：优先月度 CPM，否则取 usage_ratio(已用比例)最高的项。
function pickCredit(q: QuotaResp): QuotaItem | null {
	if (!q || !Array.isArray(q.quotas) || q.quotas.length === 0) return null;
	const items = q.quotas.filter((x) => x && x.total_quota != null && x.type);
	const monthly = items.find((x) => /^CPM$/i.test((x.type || "").trim()));
	if (monthly) return monthly;
	let best: QuotaItem | null = null;
	for (const it of items) {
		const r = it.usage_ratio ?? 0;
		const br = best ? best.usage_ratio ?? 0 : -1;
		if (!best || r > br) best = it;
	}
	return best;
}

function fmt(v: number): string {
	if (v >= 1e8) return `${(v / 1e8).toFixed(2)}亿`;
	if (v >= 1e4) return `${(v / 1e4).toFixed(2)}万`;
	if (v >= 1000) return `${(v / 1000).toFixed(1)}k`;
	return String(Math.round(v));
}

export default function (pi: ExtensionAPI) {
	let timer: ReturnType<typeof setInterval> | null = null;

	pi.on("session_shutdown", async (_event, ctx) => {
		if (timer) {
			clearInterval(timer);
			timer = null;
		}
		ctx.ui.setStatus("credit", undefined); // 幂等清理
	});

	pi.on("session_start", async (_event, ctx) => {
		if (ctx.mode !== "tui") return; // setStatus 仅 TUI 生效

		const refresh = async () => {
			const token = getToken();
			if (!token) {
				ctx.ui.setStatus("credit", "Credit: <no token>");
				return;
			}
			try {
				const data = (await fetchQuota(token)) as QuotaResp;
				const it = pickCredit(data);
				if (!it) {
					ctx.ui.setStatus("credit", data.message_cn || data.message_en || "Credit: n/a");
					return;
				}
				const total = it.total_quota ?? 0;
				const used = it.used_quota ?? 0;
				const left = Math.max(0, total - used);
				const pct = Math.round((it.usage_ratio ?? 0) * 100);
				const label = /^CPM$/i.test((it.type || "").trim()) ? "月" : (it.type || "").toUpperCase();
				ctx.ui.setStatus("credit", `Credit left: ${fmt(left)}/${fmt(total)} (${pct}%) ${label}`);
			} catch (e) {
				ctx.ui.setStatus("credit", "Credit: fetch fail");
			}
		};

		await refresh();
		if (!timer) timer = setInterval(refresh, REFRESH_MS);
	});
}
