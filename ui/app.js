// Jobissimo local UI — hash router and shell.
import { h, session, get, post, AuthError, toast, onOffline } from "./lib.js";
import { icon } from "./icons.js";
import { closePanel } from "./components.js";
import { initDock, resumeActive, agentPicker, onRunFinished } from "./agent.js";
import * as overview from "./views/overview.js";
import * as applications from "./views/applications.js";
import * as knowledge from "./views/knowledge.js";
import * as pipeline from "./views/pipeline.js";
import * as analytics from "./views/analytics.js";
import * as settings from "./views/settings.js";
import * as welcome from "./views/welcome.js";

let onboarded = true;   // from /api/session; "Get started" shows until setup is complete

const ROUTES = [
  { id: "welcome", label: "Get started", view: welcome, hidden: () => onboarded },
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
  nav.replaceChildren(...ROUTES.filter((r) => !(r.hidden && r.hidden()) || r.id === active).map((r) => h("a", {
    href: `#/${r.id}`, "aria-current": r.id === active ? "page" : null, class: r.foot ? "nav-foot" : null,
  }, icon(r.id === "welcome" ? "spark" : r.id), h("span", { class: "label" }, r.label),
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

export function setOnboarded(v) { onboarded = v; drawNav(parseRoute().id); }

// ---------------------------------------------------------------- lifetime: heartbeat, quit, offline

let stopped = false;

function heartbeat() {
  // an open page keeps an app-started UI alive (it stops after 30 idle minutes)
  const beat = () => { if (document.visibilityState === "visible" && !stopped) get("/api/ping").catch(() => {}); };
  setInterval(beat, 60000);
  document.addEventListener("visibilitychange", beat);
}

function showStopped(byQuit) {
  if (stopped) return;
  stopped = true;
  document.getElementById("agent-dock")?.setAttribute("hidden", "");
  document.getElementById("view").replaceChildren(
    h("div", { class: "page-head" }, h("div", {},
      h("h1", {}, byQuit ? "Jobissimo has stopped" : "Jobissimo isn't running"),
      h("p", {}, "Open it again from the Jobissimo app — or run python3 scripts/launcher.py open. Everything is saved."))));
  document.title = "Stopped · Jobissimo";
}

async function quit(force = false) {
  const btn = document.getElementById("quit-button");
  try {
    await post("/api/quit", { force });
    showStopped(true);
  } catch (e) {
    if (/still running/.test(e.message) && !force) {
      toast(`${e.message} Click Quit again within 5 seconds to stop them and quit.`, "error");
      btn.textContent = "Stop runs and quit";
      btn.onclick = () => quit(true);
      setTimeout(() => { btn.textContent = "Quit"; btn.onclick = () => quit(false); }, 5000);
    } else if (!stopped) {
      toast(e.message, "error");
    }
  }
}

function signedOut() {
  document.getElementById("view").replaceChildren(
    h("div", { class: "page-head" }, h("div", {},
      h("h1", {}, "Open Jobissimo from the app"),
      h("p", {}, "This page signs in through a one-time link. Open Jobissimo from its app (or run python3 scripts/launcher.py open) for a fresh one."))));
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
    onboarded = s.onboarding_complete !== false;
    if (!onboarded && !location.hash.replace(/^#\/?/, "")) location.replace("#/welcome");
  } catch (e) {
    drawNav("overview");
    if (e instanceof AuthError) return signedOut();
    toast(e.message, "error");
  }
  window.addEventListener("hashchange", () => { closePanel(); render(); document.getElementById("main").focus({ preventScroll: true }); });
  onOffline(() => showStopped(false));
  document.getElementById("quit-button").onclick = () => quit(false);
  heartbeat();
  initDock();
  await resumeActive();   // agents first, so views can show Run buttons
  document.getElementById("agent-picker-slot").replaceChildren(agentPicker());
  onRunFinished(() => { render(); refreshCounts(); });  // a run changes state: redraw
  await render();
  refreshCounts();
}

start();
