import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { assertRunnableInputs, blockInspirationRun, verifyAccount } from "../src/lib/v3-actions.js";

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

test("a new run without a script stops before the old run endpoint", () => {
  assert.equal(blockInspirationRun({ inspiration: "一句灵感" }).blocked, true);
  assert.equal(blockInspirationRun({ inspiration: "一句灵感" }).message, "不能新开一条灵感出片运行");
  assert.equal(blockInspirationRun({ script: "第一场" }).blocked, false);
  const source = read("../src/pages/run-new.jsx");
  const start = source.indexOf("const start = async");
  const submitAt = source.indexOf("submit.mutateAsync", start);
  const gateAt = source.indexOf("blockInspirationRun", start);
  assert.ok(start >= 0);
  assert.ok(gateAt > start);
  assert.ok(submitAt > gateAt);
  const body = source.slice(start, submitAt);
  assert.match(body, /if \(gate\.blocked\)/);
  assert.match(body, /return;/);
  const submitFn = source.indexOf("const submit = useMutation");
  const mutation = source.slice(submitFn, source.indexOf("onSuccess:", submitFn));
  assert.match(mutation, /assertRunnableInputs\(selected\)/);
  assert.ok(mutation.indexOf("assertRunnableInputs") < mutation.indexOf('api.post("/api/runs"'));
  assert.throws(() => assertRunnableInputs([{ inspiration: "一句灵感" }]), /不能新开一条灵感出片运行/);
  assert.doesNotThrow(() => assertRunnableInputs([{ script: "第一场 室内" }]));
  const routes = read("../src/lib/routes.js");
  assert.match(routes, /path: "\/products"/);
  const products = read("../src/pages/products.jsx");
  assert.match(products, /\/api\/products/);
  assert.match(products, /搜索提示词/);
  const layout = read("../src/components/layout.jsx");
  assert.match(layout, /to: "\/products", label: "产物"/);
  const main = read("../src/main.jsx");
  assert.match(main, /products: \(\) => import\("@\/pages\/products"\)/);
});
