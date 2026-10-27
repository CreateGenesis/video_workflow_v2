/**
 * v3 console structure. The router mounts only the pages the platform already implements.
 */
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";
import { CONSOLE_ROUTES, REQUIRED_SECTIONS, UNMOUNTED } from "../src/lib/routes.js";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const read = (path) => readFileSync(join(root, path), "utf8");

test("v3 router mounts products, settings, and comic missing only", () => {
  const sections = new Set(CONSOLE_ROUTES.map((route) => route.section));
  for (const section of REQUIRED_SECTIONS) {
    assert.ok(sections.has(section), `missing section ${section}`);
  }
  const paths = CONSOLE_ROUTES.map((route) => route.path);
  assert.deepEqual(paths.sort(), ["/", "/comic", "/products", "/settings"]);
  for (const route of CONSOLE_ROUTES) {
    assert.match(read(`src/${route.module}`), /export default function/);
  }
  const main = read("src/main.jsx");
  assert.match(main, /CONSOLE_ROUTES\.map/);
  assert.doesNotMatch(main, /pages\/login/);
  assert.doesNotMatch(main, /pages\/explore/);
  assert.doesNotMatch(main, /pages\/workflows/);
  assert.doesNotMatch(main, /pages\/queue/);
  const layout = read("src/components/layout.jsx");
  for (const path of UNMOUNTED) {
    assert.equal(layout.includes(`to: "${path}"`), false, path);
  }
  assert.match(layout, /to: "\/products"/);
  assert.match(layout, /to: "\/comic"/);
  assert.match(layout, /to: "\/settings"/);
  assert.doesNotMatch(layout, /\/api\/tasks/);
});
