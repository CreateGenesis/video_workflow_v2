/**
 * Shipped console routes. main.jsx renders this table; the structural test imports it.
 * Paths are relative to the authenticated layout except the public ones.
 */

export const PUBLIC_ROUTES = [
  { path: "/login", page: "login", module: "pages/login.jsx" },
  { path: "/approve", page: "approve", module: "pages/approve.jsx" },
  { path: "/approve/:code", page: "approve", module: "pages/approve.jsx" },
];

/** docs/design/v2.md §9.3 modules. Each page has its own address. */
export const CONSOLE_ROUTES = [
  { path: "/", index: true, page: "dashboard", module: "pages/dashboard.jsx", section: "工作台" },
  { path: "/explore", page: "explore", module: "pages/explore.jsx", section: "探索" },
  { path: "/explore/:workId", page: "work", module: "pages/work.jsx", section: "探索" },
  { path: "/workflows", page: "workflows", module: "pages/workflows.jsx", section: "工作流" },
  { path: "/workflows/:id", page: "workflow", module: "pages/workflow.jsx", section: "工作流" },
  { path: "/workflows/:id/v/:version", page: "workflow-version", module: "pages/workflow-version.jsx", section: "工作流" },
  { path: "/runs", page: "runs", module: "pages/runs.jsx", section: "运行" },
  { path: "/runs/new", page: "run-new", module: "pages/run-new.jsx", section: "运行" },
  { path: "/runs/:id", page: "run", module: "pages/run.jsx", section: "运行" },
  { path: "/queue", page: "queue", module: "pages/queue.jsx", section: "队列" },
  { path: "/library", page: "library", module: "pages/library.jsx", section: "素材库" },
  { path: "/products", page: "products", module: "pages/products.jsx", section: "产物" },
  { path: "/settings", page: "settings", module: "pages/settings.jsx", section: "设置" },
];

export const REQUIRED_SECTIONS = ["探索", "工作流", "运行", "队列", "素材库", "设置"];
