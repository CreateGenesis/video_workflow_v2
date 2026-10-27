/**
 * Shipped console routes. main.jsx renders this table; the structural test imports it.
 * Paths are relative to the authenticated layout except the public ones.
 */

/** v3 console. Only pages the platform already implements. */
export const CONSOLE_ROUTES = [
  { path: "/", index: true, page: "products", module: "pages/products.jsx", section: "产物" },
  { path: "/products", page: "products", module: "pages/products.jsx", section: "产物" },
  { path: "/settings", page: "settings", module: "pages/settings.jsx", section: "设置" },
  { path: "/comic", page: "comic", module: "pages/comic.jsx", section: "漫剧缺项" },
];

export const REQUIRED_SECTIONS = ["产物", "设置", "漫剧缺项"];
export const UNMOUNTED = ["/login", "/explore", "/workflows", "/runs", "/queue"];
