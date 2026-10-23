/**
 * Structural check of the shipped console: §9.3 routes, ComfyUI dark tokens,
 * and the Chinese status words the API values are shown as.
 * Imports the real route table, palette module, and label map — not copies.
 */
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";
import { COMFY_DARK, SLOT_COLORS } from "../src/lib/comfy.js";
import { poolEtaLabel, taskEtaLabel } from "../src/lib/eta-label.js";
import { CONSOLE_ROUTES, REQUIRED_SECTIONS } from "../src/lib/routes.js";
import { RUN_STATUS, TASK_STATUS, VERSION_STATUS } from "../src/lib/labels.js";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const read = (path) => readFileSync(join(root, path), "utf8");

test("every §9.3 module has a distinct shipped route and page module", () => {
  const sections = new Set(CONSOLE_ROUTES.map((route) => route.section));
  for (const section of REQUIRED_SECTIONS) {
    assert.ok(sections.has(section), `missing section ${section}`);
  }
  const paths = CONSOLE_ROUTES.map((route) => route.path);
  assert.equal(new Set(paths).size, paths.length, "route paths must be unique");
  for (const route of CONSOLE_ROUTES) {
    const source = read(`src/${route.module}`);
    assert.match(source, /export default function/);
  }
  const main = read("src/main.jsx");
  assert.match(main, /CONSOLE_ROUTES\.map/);
  assert.match(main, /BrowserRouter/);
  assert.match(main, /QueryClientProvider/);
  assert.match(main, /dashboard: \(\) => import\("@\/pages\/dashboard"\)/);
  assert.match(main, /function warmPages/);
  const layout = read("src/components/layout.jsx");
  assert.match(layout, /useLiveUpdates/);
  const session = read("src/lib/session.jsx");
  assert.match(session, /new EventSource\("\/api\/events\/stream"\)/);
  const media = read("src/components/media.jsx");
  assert.match(media, /artifact\.url/);
  assert.doesNotMatch(media, /Authorization/);
});

test("shipped theme tokens are the ComfyUI official dark palette", () => {
  assert.equal(COMFY_DARK.canvas, "#202020");
  assert.equal(COMFY_DARK.page, "#171718");
  assert.equal(COMFY_DARK.panel, "#353535");
  assert.equal(COMFY_DARK.panelAlt, "#262729");
  assert.equal(COMFY_DARK.border, "#4e4e4e");
  assert.equal(COMFY_DARK.primary, "#0b8ce9");
  assert.equal(SLOT_COLORS.IMAGE, "#64B5F6");
  assert.equal(SLOT_COLORS.MODEL, "#B39DDB");
  assert.equal(SLOT_COLORS.LATENT, "#FF9CF9");
  assert.equal(SLOT_COLORS.VAE, "#FF6E6E");
  assert.equal(SLOT_COLORS.CONDITIONING, "#FFA931");
  assert.equal(SLOT_COLORS.MASK, "#81C784");
  const css = read("src/styles.css");
  for (const hex of ["#202020", "#171718", "#353535", "#262729", "#4e4e4e", "#0b8ce9", "#64b5f6", "#b39ddb", "#ff9cf9", "#ff6e6e", "#ffa931", "#81c784"]) {
    assert.ok(css.toLowerCase().includes(hex), `styles.css missing ${hex}`);
  }
  assert.match(css, /color-scheme:\s*dark/);
  assert.doesNotMatch(css, /--background:\s*#f5f6f8/);
  const graph = read("src/components/step-graph.jsx");
  assert.match(graph, /slotColor/);
  assert.match(graph, /data-testid="step-graph"/);
});

test("queue and run pages print historical eta, and the pool editor stays inside 0–64", () => {
  const queue = read("src/pages/queue.jsx");
  const run = read("src/pages/run.jsx");
  const eta = read("../server/engine/eta.py");
  assert.match(queue, /poolEtaLabel/);
  assert.match(queue, /taskEtaLabel/);
  assert.match(read("src/lib/eta-label.js"), /暂无历史/);
  assert.match(queue, /Number\(concurrency\) > 64/);
  assert.match(queue, /if \(bad\) return/);
  assert.match(queue, /await update\.mutateAsync/);
  assert.match(queue, /disabled=\{bad\}/);
  assert.match(run, /progress\.eta_seconds/);
  assert.match(run, /detail\.data\.eta_seconds/);
  assert.match(run, /还没有同类历史耗时/);
  assert.doesNotMatch(run, /timeout_seconds/);
  assert.match(eta, /waves \* average/);
  assert.doesNotMatch(eta, /timeout_seconds/);
  assert.equal(poolEtaLabel({ ready: 0, eta_seconds: null }), "—");
  assert.equal(poolEtaLabel({ ready: 1, eta_seconds: null }), "暂无历史");
  assert.equal(poolEtaLabel({ ready: 1, eta_seconds: 15 }), "15 秒");
  assert.equal(poolEtaLabel({ ready: 1, eta_seconds: 1800 }), "30 分 0 秒");
  assert.equal(taskEtaLabel({ eta_seconds: null, timeout_seconds: 1800 }), "暂无历史");
  assert.equal(taskEtaLabel({ eta_seconds: 30, timeout_seconds: 1800 }), "预计 30 秒");
  assert.equal(taskEtaLabel({ queue_position: 1, eta_seconds: 15 }), "预计 15 秒");
});

test("status labels are the Chinese words, not raw English API values", () => {
  const expected = {
    queued: undefined,
    ready: "排队中",
    running: "执行中",
    waiting: "待审批",
    needs_attention: "需要处理",
    succeeded: "已完成",
    failed: "失败",
    canceled: "已取消",
  };
  for (const [key, label] of Object.entries(expected)) {
    if (!label) continue;
    assert.equal(TASK_STATUS[key]?.label, label, key);
    assert.match(TASK_STATUS[key].label, /[\u4e00-\u9fff]/);
  }
  assert.equal(RUN_STATUS.paused.label, "已暂停");
  assert.equal(VERSION_STATUS.published.label, "已发布");
  assert.equal(VERSION_STATUS.retired.label, "已下线");
  const common = read("src/components/common.jsx");
  assert.match(common, /statusOf\(TASK_STATUS/);
});
