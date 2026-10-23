export function yuan(value, { digits } = {}) {
  if (value === null || value === undefined || value === "") return "—";
  const number = Number(value);
  if (!Number.isFinite(number)) return "—";
  const places = digits ?? (number !== 0 && Math.abs(number) < 0.1 ? 4 : 2);
  return `¥${number.toFixed(places)}`;
}

const absoluteFormatter = new Intl.DateTimeFormat("zh-CN", {
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
  hour12: false,
});

export function toDate(value) {
  if (!value) return null;
  if (value instanceof Date) return value;
  if (typeof value === "number") return new Date(value < 1e12 ? value * 1000 : value);
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}

export function absoluteTime(value) {
  const date = toDate(value);
  return date ? absoluteFormatter.format(date) : "—";
}

export function relativeTime(value, now = Date.now()) {
  const date = toDate(value);
  if (!date) return "—";
  const diff = Math.round((now - date.getTime()) / 1000);
  const future = diff < 0;
  const seconds = Math.abs(diff);
  let text;
  if (seconds < 10) return future ? "马上" : "刚刚";
  if (seconds < 60) text = `${seconds} 秒`;
  else if (seconds < 3600) text = `${Math.floor(seconds / 60)} 分钟`;
  else if (seconds < 86400) text = `${Math.floor(seconds / 3600)} 小时`;
  else if (seconds < 86400 * 30) text = `${Math.floor(seconds / 86400)} 天`;
  else return absoluteTime(date).slice(0, 10);
  return future ? `${text}后` : `${text}前`;
}

export function duration(seconds) {
  if (seconds === null || seconds === undefined) return "—";
  const total = Math.max(0, Math.round(Number(seconds)));
  if (total < 60) return `${total} 秒`;
  const minutes = Math.floor(total / 60);
  if (minutes < 60) return `${minutes} 分 ${total % 60} 秒`;
  return `${Math.floor(minutes / 60)} 小时 ${minutes % 60} 分`;
}

export function elapsed(start, end) {
  const a = toDate(start);
  if (!a) return null;
  const b = toDate(end) || new Date();
  return (b.getTime() - a.getTime()) / 1000;
}

export function bytes(value) {
  if (!value && value !== 0) return "—";
  const units = ["B", "KB", "MB", "GB"];
  let number = Number(value);
  let index = 0;
  while (number >= 1024 && index < units.length - 1) {
    number /= 1024;
    index += 1;
  }
  return `${number.toFixed(index ? 1 : 0)} ${units[index]}`;
}

export function percent(value) {
  if (value === null || value === undefined) return "0%";
  return `${Math.round(Number(value) * 100)}%`;
}

export function shortId(id) {
  if (!id) return "";
  const parts = String(id).split("_");
  return parts.length > 1 ? `${parts[0]}_${parts.slice(1).join("_").slice(-6)}` : String(id).slice(-8);
}

export function pretty(value) {
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

/** A one-line description of a run's inputs: the first text value, else the first list joined. */
export function inputsSummary(inputs) {
  const values = Object.values(inputs || {});
  const text = values.find((value) => typeof value === "string" && value.trim() && !/^art_/.test(value));
  if (text) return text.replace(/\s+/g, " ").slice(0, 80);
  const list = values.find((value) => Array.isArray(value) && value.length && typeof value[0] === "string" && !/^art_/.test(value[0]));
  return list ? list.join("、").slice(0, 80) : "";
}

export function itemLabel(item, index) {
  if (item === "" || item === null || item === undefined) return "";
  if (typeof index === "number") return `第 ${index + 1} 条`;
  const number = Number(item);
  return Number.isFinite(number) ? `第 ${number + 1} 条` : String(item);
}
