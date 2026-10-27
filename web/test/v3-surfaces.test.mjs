import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { assertRunnableInputs, blockInspirationRun, MCP_EXAMPLE, verifyAccount, verifyMcpCard } from "../src/lib/v3-actions.js";

const read = (path) => readFileSync(new URL(path, import.meta.url), "utf8");

test("verify button posts the filled token and the example to the platform", async () => {
  const seen = [];
  const result = await verifyAccount("secret-value", async (path, body) => {
    seen.push({ path, body });
    return { status: "可用", error: "", next: "" };
  });
  assert.equal(seen[0].path, "/api/accounts/verify");
  assert.equal(seen[0].body.fields.token, "secret-value");
  assert.match(seen[0].body.example, /ghp_/);
  assert.equal(result.status, "可用");
  const source = readFileSync(new URL("../src/pages/settings.jsx", import.meta.url), "utf8");
  assert.match(source, /data-testid="verify-button"/);
  assert.match(source, /onClick=\{onVerify\}/);
  assert.match(source, /verifyAccount\(token, post\)/);
});

test("mcp card posts the filled address and example, then the platform stores it", async () => {
  const seen = [];
  const result = await verifyMcpCard({ name: "资料检索", address: "http://127.0.0.1:3333/mcp" }, async (path, body) => {
    seen.push({ path, body });
    return { status: "可用", card: { status: "可用", address: body.address } };
  });
  assert.equal(seen[0].path, "/api/mcp/verify");
  assert.equal(seen[0].body.address, "http://127.0.0.1:3333/mcp");
  assert.equal(seen[0].body.example, MCP_EXAMPLE);
  assert.equal(result.card.status, "可用");
  const source = read("../src/pages/settings.jsx");
  assert.match(source, /data-testid="mcp-verify-button"/);
  assert.match(source, /verifyMcpCard\(\{ name, address, tools: \["search"\] \}, post\)/);
  assert.match(source, /示例：\{MCP_EXAMPLE\}/);
});

test("products and comic pages request only the platform routes", () => {
  assert.equal(blockInspirationRun({ inspiration: "一句灵感" }).blocked, true);
  assert.throws(() => assertRunnableInputs([{ inspiration: "一句灵感" }]), /不能新开一条灵感出片运行/);
  const products = read("../src/pages/products.jsx");
  assert.match(products, /\/api\/products/);
  assert.doesNotMatch(products, /\/api\/works/);
  const comic = read("../src/pages/comic.jsx");
  assert.match(comic, /\/api\/comic\/missing/);
  const settings = read("../src/pages/settings.jsx");
  assert.match(settings, /verifyAccount\(token, post\)/);
  assert.match(settings, /verifyMcpCard/);
  assert.doesNotMatch(settings, /pages\/settings\/providers/);
  const main = read("../src/main.jsx");
  assert.match(main, /products: \(\) => import\("@\/pages\/products"\)/);
  assert.doesNotMatch(main, /path="\/login"/);
});
