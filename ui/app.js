// Jobissimo local UI — hash router and shell.
import { h, session, get, AuthError, toast } from "./lib.js";
import { icon } from "./icons.js";
import { closePanel } from "./components.js";
import { initDock, resumeActive, agentPicker, onRunFinished } from "./agent.js";
import * as overview from "./views/overview.js";
import * as applications from "./views/applications.js";
import * as knowledge from "./views/knowledge.js";
import * as pipeline from "./views/pipeline.js";
import * as analytics from "./views/analytics.js";
import * as settings from "./views/settings.js";

const ROUTES = [
  { id: "overview", label: "Overview", view: overview },
  { id: "applications", label: "Applications", view: applications },
  { id: "knowledge", label: "Knowledge", view: knowledge },
  { id: "pipeline", label: "Pipeline", view: pipeline },
  { id: "analytics", label: "Analytics", view: analytics },
  { id: "settings", label: "Settings", view: settings, foot: true },
];

export function parseRoute() {
  const raw = location.hash.replace(/^#\/?/, "") || "overview";
  const [path, query] = raw.split("?");
  const [id, ...rest] = path.split("/");
  const params = Object.fromEntries(new URLSearchParams(query || ""));
  return { id: ROUTES.some((r) => r.id === id) ? id : "overview", sub: rest.join("/") || null, params };
}

export function go(id, params = {}, sub = null) {
  const q = new URLSearchParams(Object.entries(params).filter(([, v]) => v !== null && v !== undefined && v !== "")).toString();
  const target = `#/${id}${sub ? `/${sub}` : ""}${q ? `?${q}` : ""}`;
  if (location.hash === target) render();
  else location.hash = target;
}

/** Update the URL without re-rendering (e.g. when a panel opens). */
export function setParams(params) {
  const { id, sub } = parseRoute();
  const q = new URLSearchParams(Object.entries(params).filter(([, v]) => v !== null && v !== undefined && v !== "")).toString();
  history.replaceState(null, "", `#/${id}${sub ? `/${sub}` : ""}${q ? `?${q}` : ""}`);
}

let navCounts = {};

function drawNav(active) {
  const nav = document.getElementById("nav");
  nav.replaceChildren(...ROUTES.map((r) => h("a", {
    href: `#/${r.id}`, "aria-current": r.id === active ? "page" : null, class: r.foot ? "nav-foot" : null,
  }, icon(r.id), h("span", { class: "label" }, r.label),
  navCounts[r.id] ? h("span", { class: "count", "aria-label": `${navCounts[r.id]} to review` }, navCounts[r.id]) : null)));
}

export async function refreshCounts() {
  try {
    const o = await get("/api/overview");
    const inbox = o.act_now.find((a) => a.kind === "inbox");
    const sugg = o.act_now.find((a) => a.kind === "suggestions");
    navCounts = {
      knowledge: inbox ? parseInt(inbox.title, 10) : 0,
      pipeline: sugg ? parseInt(sugg.title, 10) : 0,
    };
    drawNav(parseRoute().id);
  } catch { /* counts are decoration */ }
}

let rendering = 0;
export async function render() {
  const token = ++rendering;
  const route = parseRoute();
  drawNav(route.id);
  const r = ROUTES.find((x) => x.id === route.id);
  document.title = `${r.label} · Jobissimo`;
  const container = document.getElementById("view");
  try {
    const node = await r.view.render(route);
    if (token !== rendering) return; // a newer navigation won
    container.replaceChildren(node);
  } catch (e) {
    if (e instanceof AuthError) return signedOut();
    container.replaceChildren(h("div", { class: "error-box", role: "alert" }, `Could not load this page: ${e.message}`));
  }
}

function signedOut() {
  document.getElementById("view").replaceChildren(
    h("div", { class: "page-head" }, h("div", {},
      h("h1", {}, "Open Jobissimo from your terminal"),
      h("p", {}, "This page needs the one-time link printed by python3 scripts/ui.py. Restart it if the link has expired."))));
}

function initTheme() {
  const stored = (() => { try { return localStorage.getItem("jobissimo-theme"); } catch { return null; } })();
  if (stored) document.documentElement.dataset.theme = stored;
  document.getElementById("theme-toggle").addEventListener("click", () => {
    const dark = document.documentElement.dataset.theme
      ? document.documentElement.dataset.theme === "dark"
      : matchMedia("(prefers-color-scheme: dark)").matches;
    const next = dark ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    try { localStorage.setItem("jobissimo-theme", next); } catch { /* private mode */ }
  });
}

async function start() {
  initTheme();
  try {
    const s = await session();
    document.getElementById("workspace-name").textContent = s.workspace;
  } catch (e) {
    drawNav("overview");
    if (e instanceof AuthError) return signedOut();
    toast(e.message, "error");
  }
  window.addEventListener("hashchange", () => { closePanel(); render(); document.getElementById("main").focus({ preventScroll: true }); });
  initDock();
  await resumeActive();   // agents first, so views can show Run buttons
  document.getElementById("agent-picker-slot").replaceChildren(agentPicker());
  onRunFinished(() => { render(); refreshCounts(); });  // a run changes state: redraw
  await render();
  refreshCounts();
}

start();
