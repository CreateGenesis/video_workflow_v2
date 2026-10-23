// Thin fetch wrapper: same-origin cookies, CSRF header on writes, JSON errors with the server `detail`.

export class ApiError extends Error {
  constructor(message, status, body) {
    super(message);
    this.status = status;
    this.body = body;
  }
}

export const uiFlags = { confirmActive: false };

let unauthorizedHandler = null;
export function onUnauthorized(handler) {
  unauthorizedHandler = handler;
}

function detailOf(body, status) {
  if (!body) return `请求失败（${status}）`;
  const detail = body.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((item) => {
        const where = (item.loc || []).filter((part) => part !== "body").join(".");
        return where ? `${where}：${item.msg}` : item.msg;
      })
      .join("；");
  }
  return `请求失败（${status}）`;
}

export async function request(method, path, { body, form, signal, quiet401 = false } = {}) {
  const headers = { Accept: "application/json" };
  if (method !== "GET") headers["X-CVGEN-CSRF"] = "1";
  let payload;
  if (form) {
    payload = form;
  } else if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    payload = JSON.stringify(body);
  }
  let response;
  try {
    response = await fetch(path, { method, headers, body: payload, credentials: "same-origin", signal });
  } catch (error) {
    if (error.name === "AbortError") throw error;
    throw new ApiError("连不上服务器，请检查网络后重试", 0, null);
  }
  const text = await response.text();
  let data = null;
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = { detail: text.slice(0, 300) };
    }
  }
  if (!response.ok) {
    if (response.status === 401 && !quiet401 && unauthorizedHandler) unauthorizedHandler();
    throw new ApiError(detailOf(data, response.status), response.status, data);
  }
  return data;
}

export const api = {
  get: (path, options) => request("GET", path, options),
  post: (path, body, options) => request("POST", path, { ...options, body: body ?? {} }),
  put: (path, body, options) => request("PUT", path, { ...options, body }),
  patch: (path, body, options) => request("PATCH", path, { ...options, body }),
  del: (path, options) => request("DELETE", path, options),
  upload: (file, workspaceId, label) => {
    const form = new FormData();
    form.append("file", file);
    form.append("workspace_id", workspaceId);
    form.append("label", label || file.name);
    return request("POST", "/api/uploads", { form });
  },
};

export function qs(params) {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params || {})) {
    if (value === undefined || value === null || value === "") continue;
    search.set(key, String(value));
  }
  const text = search.toString();
  return text ? `?${text}` : "";
}

export function downloadUrl(url) {
  if (!url) return url;
  return url + (url.includes("?") ? "&" : "?") + "download=1";
}
