export const ACCOUNT_EXAMPLE = "ghp_ 加说明，不放真实值。从令牌页面复制。";
export const MCP_EXAMPLE = "http://127.0.0.1:3333/mcp";

export async function verifyAccount(token, post) {
  return post("/api/accounts/verify", { fields: { token }, example: ACCOUNT_EXAMPLE });
}

export async function verifyMcpCard(card, post) {
  return post("/api/mcp/verify", {
    name: card.name,
    address: card.address,
    example: MCP_EXAMPLE,
    enabled: true,
    tools: card.tools || ["search"],
  });
}

export function blockInspirationRun(values) {
  const script = String(values?.script || values?.剧本 || "").trim();
  if (!script) {
    return { blocked: true, message: "不能新开一条灵感出片运行" };
  }
  return { blocked: false, script };
}

export function assertRunnableInputs(rows) {
  const blocked = rows.find((values) => blockInspirationRun(values).blocked);
  if (blocked) {
    const error = new Error("不能新开一条灵感出片运行");
    error.code = "inspiration";
    throw error;
  }
}
