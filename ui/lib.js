// Small DOM + API helpers. No framework: views are functions that build nodes.

export function h(tag, attrs, ...children) {
  // attrs is optional: a node, text or list in its place is the first child
  if (attrs === null || attrs === undefined || attrs instanceof Node || typeof attrs !== "object" || Array.isArray(attrs)) {
    if (attrs !== null && attrs !== undefined) children.unshift(attrs);
    attrs = {};
  }
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") el.className = v;
    else if (k === "style" && typeof v === "object") Object.assign(el.style, v);
    else if (k.startsWith("on") && typeof v === "function") el.addEventListener(k.slice(2), v);
    else if (k === "html") el.innerHTML = v; // only ever used with our own static SVG strings
    else if (v === true) el.setAttribute(k, "");
    else el.setAttribute(k, v);
  }
  append(el, children);
  return el;
}

export function append(el, children) {
  for (const c of children.flat(Infinity)) {
    if (c === null || c === undefined || c === false) continue;
    el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return el;
}

const SVGNS = "http://www.w3.org/2000/svg";
export function s(tag, attrs, ...children) {
  const el = document.createElementNS(SVGNS, tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined) continue;
    el.setAttribute(k, v);
  }
  for (const c of children.flat()) {
    if (c === null || c === undefined) continue;
    el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return el;
}

// ---------------------------------------------------------------- API

let csrf = null;

export async function session() {
  const res = await fetch("/api/session", { credentials: "same-origin" });
  if (res.status === 401) throw new AuthError();
  const data = await res.json();
  csrf = data.csrf;
  return data;
}

export class AuthError extends Error {}

export async function get(path) {
  const res = await fetch(path, { credentials: "same-origin" });
  if (res.status === 401) throw new AuthError();
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || `Request failed (${res.status})`);
  return data;
}

export async function post(path, body) {
  const res = await fetch(path, {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf || "" },
    body: JSON.stringify(body || {}),
  });
  if (res.status === 401) throw new AuthError();
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || `Request failed (${res.status})`);
  return data;
}

// ---------------------------------------------------------------- format

export const fmt = {
  pct(x, digits = 0) {
    if (x === null || x === undefined || Number.isNaN(x)) return "–";
    return `${(100 * x).toFixed(digits)}%`;
  },
  num(x) {
    if (x === null || x === undefined) return "–";
    return new Intl.NumberFormat().format(x);
  },
  date(s) {
    if (!s) return "–";
    const d = new Date(s.length <= 10 ? `${s}T00:00:00` : s);
    if (Number.isNaN(d.getTime())) return s;
    const sameYear = d.getFullYear() === new Date().getFullYear();
    return d.toLocaleDateString(undefined, { day: "numeric", month: "short", ...(sameYear ? {} : { year: "numeric" }) });
  },
  relative(s) {
    if (!s) return "never";
    const d = new Date(s.length <= 10 ? `${s}T00:00:00` : s);
    const days = Math.floor((Date.now() - d.getTime()) / 86400000);
    if (days <= 0) return "today";
    if (days === 1) return "yesterday";
    if (days < 14) return `${days} days ago`;
    if (days < 60) return `${Math.round(days / 7)} weeks ago`;
    return fmt.date(s);
  },
  plural(n, one, many) {
    return `${fmt.num(n)} ${n === 1 ? one : (many || `${one}s`)}`;
  },
  today() {
    const d = new Date();
    const m = String(d.getMonth() + 1).padStart(2, "0");
    return `${d.getFullYear()}-${m}-${String(d.getDate()).padStart(2, "0")}`;
  },
};

export const STATUS = {
  found: ["Found", "s-quiet"], scored: ["Scored", "s-quiet"], shortlisted: ["Shortlisted", "s-active"],
  generated: ["Preparing", "s-active"], ready: ["Ready to send", "s-warn"], applied: ["Applied", "s-active"],
  responded: ["In process", "s-good"], offered: ["Offer", "s-good"], closed: ["Closed", "s-quiet"],
  on_hold: ["On hold", "s-quiet"], missed: ["Missed", "s-quiet"], skipped: ["Skipped", "s-quiet"],
  discarded: ["Discarded", "s-quiet"],
};

export const OUTCOME = {
  no_response: "No response", rejected: "Rejected", interview: "Interviewed",
  offer_accepted: "Offer accepted", offer_declined: "Offer declined",
  offer_withdrawn: "Offer withdrawn", withdrawn: "Withdrew",
};

export function statusEl(status, outcome) {
  const [label, cls] = STATUS[status] || [status, "s-quiet"];
  let text = label;
  let c = cls;
  if (status === "closed" && outcome) {
    text = OUTCOME[outcome] || outcome;
    if (outcome === "offer_accepted") c = "s-good";
    if (outcome === "rejected") c = "s-bad";
  }
  return h("span", { class: `status ${c}` }, text);
}

// ---------------------------------------------------------------- toast

let toastTimer = null;
export function toast(message, kind = "info") {
  const root = document.getElementById("toast-root");
  root.replaceChildren(h("div", { class: `toast ${kind === "error" ? "error" : ""}`, role: kind === "error" ? "alert" : "status" }, message));
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => root.replaceChildren(), kind === "error" ? 7000 : 3500);
}

export async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
    toast(`Copied ${text}`);
  } catch {
    toast(text);
  }
}

// ---------------------------------------------------------------- links

const URL_RE = /https?:\/\/[^\s<>"'`)\]]+[^\s<>"'`)\].,;:!?]/g;

/** Text → text nodes with every http(s) URL as a link that opens a new tab. */
export function linkify(text) {
  const frag = document.createDocumentFragment();
  const s = String(text ?? "");
  let last = 0;
  for (const m of s.matchAll(URL_RE)) {
    if (m.index > last) frag.append(s.slice(last, m.index));
    frag.append(link(m[0]));
    last = m.index + m[0].length;
  }
  if (last < s.length) frag.append(s.slice(last));
  return frag;
}

function link(url, label) {
  const a = document.createElement("a");
  a.href = url;
  a.target = "_blank";
  a.rel = "noopener noreferrer";
  a.textContent = label || url;
  return a;
}

// ---------------------------------------------------------------- markdown-lite

/** Agent text → DOM: headings, bullets, fenced code, **bold**, `code`,
 *  [links](https://…) and bare URLs (open in a new tab). Built from text
 *  nodes only — agent output can never inject markup. */
export function mdLite(text) {
  const root = document.createElement("div");
  root.className = "md";
  const lines = String(text || "").split("\n");
  let list = null, fence = null;
  const inline = (s) => {
    const frag = document.createDocumentFragment();
    const re = /(\*\*[^*]+\*\*|`[^`]+`|\[[^\]]+\]\(https?:\/\/[^)\s]+\))/g;
    let last = 0, m;
    while ((m = re.exec(s))) {
      if (m.index > last) frag.append(linkify(s.slice(last, m.index)));
      const tok = m[0];
      if (tok.startsWith("[")) {
        const lm = /^\[([^\]]+)\]\((.+)\)$/.exec(tok);
        frag.append(link(lm[2], lm[1]));
      } else if (tok.startsWith("**")) {
        const el = document.createElement("strong");
        el.append(linkify(tok.slice(2, -2)));
        frag.append(el);
      } else {
        const el = document.createElement("code");
        const inner = tok.slice(1, -1);
        if (/^https?:\/\/\S+$/.test(inner)) el.append(link(inner));
        else el.textContent = inner;
        frag.append(el);
      }
      last = m.index + tok.length;
    }
    if (last < s.length) frag.append(linkify(s.slice(last)));
    return frag;
  };
  for (const line of lines) {
    if (line.trim().startsWith("```")) {
      if (fence) { root.append(fence); fence = null; } else { fence = document.createElement("pre"); }
      list = null;
      continue;
    }
    if (fence) { fence.append(linkify(`${line}\n`)); continue; }
    const hm = line.match(/^(#{1,4})\s+(.*)$/);
    const bm = line.match(/^(\s*)([-*]|\d{1,2}[.)])\s+(.*)$/);
    if (hm) {
      const el = document.createElement("div");
      el.className = "md-h";
      el.append(inline(hm[2]));
      root.append(el);
      list = null;
    } else if (bm) {
      const tag = /\d/.test(bm[2]) ? "ol" : "ul";
      if (!list || list.tagName.toLowerCase() !== tag) {
        list = document.createElement(tag);
        if (tag === "ol") list.start = parseInt(bm[2], 10) || 1;
        root.append(list);
      }
      const li = document.createElement("li");
      if (bm[1].length >= 2) li.className = "nested";
      li.append(inline(bm[3]));
      list.append(li);
    } else if (line.trim()) {
      const p = document.createElement("p");
      p.append(inline(line));
      root.append(p);
      list = null;
    } else {
      list = null;
    }
  }
  if (fence) root.append(fence);
  return root;
}
