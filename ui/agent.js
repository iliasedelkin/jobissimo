// Running commands in the user's own Claude Code or Codex, and the
// Cursor-style activity dock that shows what the agents are doing.
//
// The dock stays out of the way: a small status pill while runs are going,
// expandable into the run's step list — thinking, messages, every command and
// file the agent touched (outputs folded away), its questions and permission
// requests, and a reply box once a turn ends. Several runs can go at once;
// tabs switch between them. Whether it opens expanded is remembered.
import { h, get, post, fmt, toast, mdLite, linkify, copyText } from "./lib.js";
import { icon } from "./icons.js";

let agents = null;          // /api/agents payload
const runs = new Map();     // id -> { meta, events: [], seen: Set(ask ids) }
let selected = null;        // run id shown in the dock
let pollTimer = null;
let tickTimer = null;
const listeners = new Set();
const BUSY = new Set(["starting", "running", "needs_input"]);
const isBusy = (m) => BUSY.has(m.status);

const store = {
  get(k, d) { try { return localStorage.getItem(k) ?? d; } catch { return d; } },
  set(k, v) { try { localStorage.setItem(k, v); } catch { /* private mode */ } },
};

export function onRunFinished(fn) { listeners.add(fn); }
export const getAgents = () => agents;

export async function loadAgents() {
  try {
    agents = await get("/api/agents");
  } catch {
    agents = { agents: {}, commands: {}, runs: [], max_parallel: 1 };
  }
  return agents;
}

export function chosenAgent() {
  const avail = Object.entries(agents?.agents || {}).filter(([, a]) => a.available).map(([k]) => k);
  const pref = store.get("jobissimo-agent", "claude");
  return avail.includes(pref) ? pref : avail[0] || null;
}

export function setChosenAgent(agent) {
  store.set("jobissimo-agent", agent);
  const sel = document.getElementById("agent-select");
  if (sel) sel.value = agent;
}

export function canRun(command) {
  return Boolean(agents && agents.commands[command] && chosenAgent());
}

/** The "Run with" picker for the sidebar. */
export function agentPicker() {
  const wrap = h("div", { class: "agent-picker" });
  const entries = Object.entries(agents?.agents || {});
  if (!entries.some(([, a]) => a.available)) {
    wrap.append(h("a", { class: "muted", href: "#/settings" }, "No agent CLI found — see Settings."));
    return wrap;
  }
  const sel = h("select", { class: "select select-sm", id: "agent-select", "aria-label": "Run commands with",
    onchange: (e) => store.set("jobissimo-agent", e.target.value) },
  entries.map(([k, a]) => h("option", { value: k, disabled: !a.available, selected: k === chosenAgent() },
    a.available ? a.label : `${a.label} (not found)`)));
  wrap.append(h("label", { for: "agent-select", class: "agent-picker-label" }, "Run with"), sel);
  return wrap;
}

/** A Run button for one command. Null if no agent can run it. */
export function runButton(command, arg = null, { label, primary = false, small = true } = {}) {
  if (!canRun(command)) return null;
  const spec = agents.commands[command];
  return h("button", {
    type: "button", class: `btn ${primary ? "btn-accent" : ""} ${small ? "btn-sm" : ""}`,
    title: `${spec.help} Runs in your ${agents.agents[chosenAgent()].label}.`,
    onclick: (e) => { e.stopPropagation(); startRun(command, arg); },
  }, icon("play"), label || spec.label);
}

/** "/prepare abc123" as a button that runs it — or a copy chip for the
 *  commands that stay in the chat (/apply, /setup, /sync). */
export function commandButton(cmd) {
  const m = /^\/([a-z]+)(?:\s+(.+))?$/.exec(cmd.trim());
  if (!m || !canRun(m[1])) return null;
  const spec = agents.commands[m[1]];
  return h("button", {
    type: "button", class: "chip chip-run mono",
    title: `Run ${cmd} — ${spec.help} (in your ${agents.agents[chosenAgent()].label})`,
    onclick: (e) => { e.stopPropagation(); startRun(m[1], m[2] || null); },
  }, icon("play"), cmd);
}

export function copyChip(cmd, why) {
  return h("button", { type: "button", class: "chip mono", title: why || "Copy the command to run it in Claude Code or Codex",
    onclick: (e) => { e.stopPropagation(); copyText(cmd); } }, cmd, icon("copy"));
}

export async function startRun(command, arg = null) {
  const agent = chosenAgent();
  if (!agent) { toast("No agent CLI found on this machine — see Settings.", "error"); return null; }
  try {
    const res = await post("/api/runs", { agent, command, arg });
    track(res.run);
    selected = res.run.id;
    toast(`Started ${res.run.label} in ${agents.agents[agent].label}`);
    showDock();
    poll();
    return res.run;
  } catch (e) {
    toast(e.message, "error");
    return null;
  }
}

/** Install a tool through the same dock (Settings → Tools). */
export async function startInstall(tool) {
  try {
    const res = await post("/api/settings/install", { tool });
    track(res.run);
    selected = res.run.id;
    showDock();
    poll();
  } catch (e) { toast(e.message, "error"); }
}

function track(meta) {
  if (!runs.has(meta.id)) runs.set(meta.id, { meta, events: [], seen: new Set() });
  else runs.get(meta.id).meta = meta;
  return runs.get(meta.id);
}

async function act(path, body, okMsg) {
  try {
    const res = await post(path, body);
    const r = track(res.run);
    r.meta = res.run;
    if (okMsg) toast(okMsg);
    drawDock();
    poll();
    return true;
  } catch (e) {
    toast(e.message, "error");
    return false;
  }
}

const stopRun = (id) => act(`/api/runs/${id}/stop`, {});

// ---------------------------------------------------------------- polling

async function poll() {
  clearTimeout(pollTimer);
  const live = [...runs.values()].filter((r) => isBusy(r.meta) || r.refresh);
  await Promise.all(live.map(pollOne));
  if ([...runs.values()].some((r) => isBusy(r.meta))) pollTimer = setTimeout(poll, 800);
}

async function pollOne(r) {
  r.refresh = false;
  try {
    const res = await get(`/api/runs/${r.meta.id}?after=${r.events.length}`);
    const was = r.meta;
    r.meta = res.run;
    if (res.events.length) {
      r.events.push(...res.events);
      if (selected === r.meta.id && expanded()) appendSteps(res.events);
    }
    const fresh = (r.meta.asks || []).filter((a) => !r.seen.has(a.id));
    if (fresh.length) {
      fresh.forEach((a) => r.seen.add(a.id));
      // a question waits on the user: bring it into view
      selected = r.meta.id;
      store.set("jobissimo-dock", "expanded");
      toast(`${r.meta.label} needs you: ${fresh[0].kind === "question" ? "a question" : fresh[0].title}`);
      drawDock();
    } else {
      drawChrome();
    }
    if (isBusy(was) && !isBusy(r.meta)) finished(r.meta);
  } catch {
    r.refresh = true; // try again on the next tick
  }
}

function finished(m) {
  if (m.status === "succeeded") toast(`${m.label} finished in ${duration(m.elapsed_s)}`);
  else if (m.status === "stopped") toast(`${m.label} stopped`);
  else toast(`${m.label} ${m.status}: ${m.error || "see the activity panel"}`, "error");
  drawDock();
  for (const fn of listeners) fn(m);
}

/** On page load: reattach to the runs of this server session. */
export async function resumeActive() {
  await loadAgents();
  for (const m of agents.runs || []) {
    const r = track(m);
    (m.asks || []).forEach((a) => r.seen.add(a.id));
  }
  const busy = (agents.runs || []).filter(isBusy);
  if (busy.length) {
    selected = (busy.find((m) => m.status === "needs_input") || busy[0]).id;
    for (const r of runs.values()) r.refresh = true;
    showDock();
    poll();
  }
}

// ---------------------------------------------------------------- dock

const dock = () => document.getElementById("agent-dock");
const expanded = () => store.get("jobissimo-dock", "collapsed") === "expanded";
const visibleRuns = () => [...runs.values()].filter((r) => !r.dismissed).sort((a, b) => (a.meta.started_at < b.meta.started_at ? -1 : 1));

function duration(s) {
  if (s === null || s === undefined) return "";
  s = Math.round(s);
  return s < 60 ? `${s}s` : `${Math.floor(s / 60)}m ${String(s % 60).padStart(2, "0")}s`;
}

function showDock() {
  dock().hidden = false;
  drawDock();
  clearInterval(tickTimer);
  tickTimer = setInterval(() => {
    for (const r of runs.values()) if (r.meta.status === "running" || r.meta.status === "needs_input") r.meta.elapsed_s += 1;
    const r = runs.get(selected);
    const el = dock().querySelector(".dock-elapsed");
    if (r && el) el.textContent = duration(r.meta.elapsed_s);
  }, 1000);
}

function statusIcon(status) {
  if (status === "needs_input") return h("span", { class: "dock-status ask", "aria-hidden": "true" }, "?");
  if (status === "running" || status === "starting") return h("span", { class: "spinner", "aria-hidden": "true" });
  if (status === "succeeded") return h("span", { class: "dock-status ok", "aria-hidden": "true" }, icon("check"));
  if (status === "stopped") return h("span", { class: "dock-status quiet", "aria-hidden": "true" }, icon("close"));
  return h("span", { class: "dock-status bad", "aria-hidden": "true" }, icon("alert"));
}

function statusWord(m) {
  if (m.stopping && isBusy(m)) return "Stopping";
  return { starting: "Starting", running: "Working", needs_input: "Needs you", succeeded: "Done",
    failed: "Failed", stopped: "Stopped" }[m.status] || m.status;
}

const agentLabel = (m) => (m.agent === "task" ? "Homebrew" : agents?.agents?.[m.agent]?.label || m.agent);

/** Which run the collapsed pill is about: whoever needs you, else working, else newest. */
function focusRun() {
  const list = visibleRuns();
  return list.find((r) => r.meta.status === "needs_input") || runs.get(selected) || list.find((r) => isBusy(r.meta)) || list[list.length - 1];
}

function drawDock() {
  const root = dock();
  const list = visibleRuns();
  if (!list.length) { root.hidden = true; attention(); return; }
  root.hidden = false;
  if (!runs.get(selected) || runs.get(selected).dismissed) selected = focusRun().meta.id;
  const open = expanded();
  root.className = `agent-dock ${open ? "open" : ""}`;
  root.replaceChildren(...[head(open), open ? body() : null].filter(Boolean));
  if (open) {
    appendSteps(runs.get(selected).events, true);
    scrollToEnd(true);
  }
  attention();
}

/** Redraw the parts that change on every poll, without touching what the user types. */
function drawChrome() {
  const root = dock();
  if (root.hidden) return;
  const old = root.querySelector(".dock-head");
  if (old) old.replaceWith(head(expanded()));
  const r = runs.get(selected);
  if (expanded() && r) {
    const sub = root.querySelector(".run-head");
    if (sub) sub.replaceWith(runHead(r.meta));
    const tray = root.querySelector(".dock-tray");
    const sig = traySig(r.meta);
    if (tray && tray.dataset.sig !== sig) tray.replaceWith(trayEl(r.meta));
    const live = root.querySelector(".dock-live");
    if (live) live.textContent = `${r.meta.label}: ${statusWord(r.meta)}`;
  }
  attention();
}

function attention() {
  const waiting = [...runs.values()].filter((r) => !r.dismissed && r.meta.status === "needs_input").length;
  document.title = document.title.replace(/^\(\d+\) /, "");
  if (waiting) document.title = `(${waiting}) ${document.title}`;
}

function head(open) {
  const list = visibleRuns();
  const f = runs.get(selected) && open ? runs.get(selected) : focusRun();
  const m = f.meta;
  const toggle = () => { store.set("jobissimo-dock", open ? "collapsed" : "expanded"); drawDock(); };
  const busy = list.filter((r) => isBusy(r.meta)).length;
  const waiting = list.filter((r) => r.meta.status === "needs_input").length;
  const sub = list.length > 1
    ? `${busy ? `${busy} working` : "all done"}${waiting ? ` · ${waiting} need${waiting > 1 ? "" : "s"} you` : ""} · ${list.length} runs`
    : [statusWord(m), agentLabel(m)].join(" · ");
  return h("div", { class: "dock-head" },
    h("button", { type: "button", class: "dock-toggle", "aria-expanded": String(open), "aria-controls": "dock-steps",
      onclick: toggle, title: open ? "Hide agent activity" : "Show agent activity" },
    statusIcon(m.status),
    h("span", { class: "dock-title" },
      h("span", { class: "mono" }, list.length > 1 && !open ? `${m.label} +${list.length - 1}` : open ? "Agent runs" : m.label),
      h("span", { class: "dock-sub" }, sub)),
    h("span", { class: "dock-chevron", "aria-hidden": "true" }, open ? "⌄" : "⌃")),
    !open && isBusy(m) && m.status !== "needs_input" ? h("button", { type: "button", class: "btn btn-sm", onclick: () => stopRun(m.id) }, "Stop") : null);
}

function tabs() {
  const list = visibleRuns();
  if (list.length < 2) return null;
  return h("div", { class: "dock-tabs", role: "tablist", "aria-label": "Runs" }, list.map((r) => {
    const on = r.meta.id === selected;
    return h("button", { type: "button", role: "tab", "aria-selected": String(on), class: `dock-tab ${on ? "on" : ""} st-${r.meta.status}`,
      title: `${r.meta.label} — ${statusWord(r.meta)}`, onclick: () => { selected = r.meta.id; drawDock(); } },
    h("span", { class: "dot", "aria-hidden": "true" }), h("span", { class: "mono" }, r.meta.label));
  }));
}

function runHead(m) {
  const busy = isBusy(m);
  const bits = [statusWord(m), agentLabel(m), h("span", { class: "dock-elapsed" }, duration(m.elapsed_s))];
  if (m.turn > 1) bits.push(`${m.turn} turns`);
  if (m.cost_usd) bits.push(`$${m.cost_usd.toFixed(2)}`);
  else if (m.tokens && m.tokens.output_tokens) bits.push(`${fmt.num(m.tokens.input_tokens + m.tokens.output_tokens)} tokens`);
  return h("div", { class: "run-head" },
    statusIcon(m.status),
    h("div", { class: "grow" }, h("div", { class: "mono run-title" }, m.label),
      h("div", { class: "dock-sub" }, bits.flatMap((b, i) => (i ? [" · ", b] : [b])))),
    busy ? h("button", { type: "button", class: "btn btn-sm", onclick: () => stopRun(m.id) }, m.stopping ? "Stopping…" : "Stop")
      : h("button", { type: "button", class: "btn btn-ghost btn-icon btn-sm", "aria-label": "Remove from the panel",
        title: "Remove from the panel", onclick: () => { runs.get(m.id).dismissed = true; selected = null; drawDock(); } }, icon("close")));
}

function body() {
  const r = runs.get(selected);
  return h("div", { class: "dock-body" },
    tabs(),
    runHead(r.meta),
    h("div", { class: "sr-only dock-live", "aria-live": "polite" }),
    h("ol", { class: "dock-steps", id: "dock-steps", "aria-label": "Agent activity",
      onscroll: (e) => { e.target.dataset.pinned = String(e.target.scrollTop + e.target.clientHeight >= e.target.scrollHeight - 24); } }),
    trayEl(r.meta));
}

// ---------------------------------------------------------------- tray: asks + reply

const traySig = (m) => `${m.status}|${(m.asks || []).map((a) => a.id).join(",")}|${m.can_reply}`;

function trayEl(m) {
  const tray = h("div", { class: "dock-tray", "data-sig": traySig(m) });
  const asks = m.asks || [];
  if (asks.length) {
    tray.append(...asks.map((a) => (a.kind === "question" ? questionCard(m, a) : permissionCard(m, a))));
    return tray;
  }
  if (m.status === "failed" && m.error) tray.append(h("div", { class: "tray-error" }, icon("alert"), h("span", {}, m.error)));
  if (m.can_reply) {
    tray.append(replyBox(m));
  } else if (isBusy(m) && m.agent !== "task") {
    tray.append(h("p", { class: "tray-hint" }, m.agent === "claude"
      ? "If Claude needs a decision or a permission, it asks you here."
      : "Codex can't ask mid-run — it ends with its questions, and you reply here."));
  }
  return tray;
}

function replyBox(m) {
  const who = agentLabel(m).split(" ")[0];
  const ta = h("textarea", { class: "input reply-input", rows: "2", maxlength: "4000", "aria-label": `Reply to ${who}`,
    placeholder: m.conversation ? `Answer ${who}…` : `Reply to ${who} — answer its questions or ask for a change` });
  const send = async () => {
    const text = ta.value.trim();
    if (!text) return;
    ta.disabled = true;
    const ok = await act(`/api/runs/${m.id}/reply`, { text });
    if (!ok) { ta.disabled = false; ta.focus(); }
  };
  ta.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) { e.preventDefault(); send(); }
  });
  ta.addEventListener("input", () => { ta.style.height = "auto"; ta.style.height = `${Math.min(ta.scrollHeight, 160)}px`; });
  return h("div", { class: "reply" }, ta,
    h("div", { class: "reply-foot" },
      h("span", { class: "muted" }, "⌘↵ to send · continues the same session"),
      h("button", { type: "button", class: "btn btn-accent btn-sm", onclick: send }, icon("send"), "Send")));
}

function permissionCard(m, a) {
  const note = h("input", { class: "input input-sm", maxlength: "500", placeholder: "Tell the agent why, or what to do instead (optional)", "aria-label": "Note for the agent" });
  const noteRow = h("div", { class: "ask-note", hidden: true }, note,
    h("button", { type: "button", class: "btn btn-sm", onclick: () => answer(m, a, { decision: "deny", message: note.value }) }, "Deny"));
  const detail = a.url
    ? h("a", { class: "ask-detail mono", href: a.url, target: "_blank", rel: "noopener noreferrer" }, a.detail)
    : h("div", { class: `ask-detail ${a.mono ? "mono" : ""}` }, a.detail);
  return h("div", { class: "ask-card", role: "group", "aria-label": `Permission request: ${a.title}` },
    h("div", { class: "ask-head" }, icon("shield"), h("span", {}, `${agentLabel(m).split(" ")[0]} wants to `, h("strong", {}, a.title.charAt(0).toLowerCase() + a.title.slice(1)))),
    detail,
    a.why ? h("div", { class: "ask-why" }, a.why) : null,
    h("div", { class: "ask-actions" },
      h("button", { type: "button", class: "btn btn-accent btn-sm", onclick: () => answer(m, a, { decision: "allow" }) }, "Allow once"),
      a.rules && a.rules.length ? h("button", { type: "button", class: "btn btn-sm", title: `Saves ${a.rules.join(", ")} to .claude/settings.local.json`,
        onclick: () => answer(m, a, { decision: "always" }) }, "Always allow") : null,
      h("button", { type: "button", class: "btn btn-sm", onclick: () => { noteRow.hidden = false; note.focus(); } }, "Deny…")),
    a.rules && a.rules.length ? h("div", { class: "ask-rules" }, "Always allow saves ", h("code", {}, a.rules.join(", ")), " — change it any time in Settings.") : null,
    noteRow);
}

function questionCard(m, a) {
  const form = h("form", { class: "ask-card", "aria-label": "Question from the agent" });
  const getters = [];
  a.questions.forEach((q, qi) => {
    const name = `q${a.id}_${qi}`;
    const other = h("input", { class: "input input-sm", maxlength: "2000", placeholder: "Or type your own answer", "aria-label": `Your own answer to: ${q.question}` });
    const opts = q.options.map((o) => h("label", { class: "ask-opt" },
      h("input", { type: q.multiSelect ? "checkbox" : "radio", name, value: o.label }),
      h("span", {}, h("span", { class: "ask-opt-label" }, o.label), o.description ? h("span", { class: "ask-opt-desc" }, linkify(o.description)) : null)));
    other.addEventListener("input", () => { if (other.value && !q.multiSelect) form.querySelectorAll(`input[name="${name}"]`).forEach((x) => { x.checked = false; }); });
    form.append(h("fieldset", { class: "ask-q" },
      h("legend", {}, q.header ? h("span", { class: "chip" }, q.header) : null, h("span", { class: "ask-q-text" }, linkify(q.question))),
      opts, other));
    getters.push(() => {
      const picked = [...form.querySelectorAll(`input[name="${name}"]:checked`)].map((x) => x.value);
      const typed = other.value.trim();
      const all = typed ? [...picked, typed] : picked;
      return [q.question, q.multiSelect ? all : (typed || picked[0] || "")];
    });
  });
  form.append(h("div", { class: "ask-actions" },
    h("button", { type: "submit", class: "btn btn-accent btn-sm" }, icon("send"), "Answer"),
    h("button", { type: "button", class: "btn btn-ghost btn-sm", onclick: () => answer(m, a, { decline: true }) }, "Skip — take the safe default")));
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    const answers = Object.fromEntries(getters.map((g) => g()));
    const missing = Object.entries(answers).find(([, v]) => (Array.isArray(v) ? !v.length : !v));
    if (missing) { toast(`Answer: ${missing[0]}`, "error"); return; }
    answer(m, a, { answers });
  });
  return form;
}

async function answer(m, a, body) {
  dock().querySelectorAll(".ask-card button").forEach((b) => { b.disabled = true; });
  const ok = await act(`/api/runs/${m.id}/asks/${a.id}`, body);
  if (!ok) dock().querySelectorAll(".ask-card button").forEach((b) => { b.disabled = false; });
}

// ---------------------------------------------------------------- steps

const VERB_ICON = { Ran: "terminal", Read: "file", Wrote: "file", Edited: "edit", Searched: "search",
  "Searched the web": "globe", Fetched: "globe", Browser: "globe", Gmail: "inbox", Loaded: "spark", Planned: "list" };

function appendSteps(events, rebuild = false) {
  const list = dock().querySelector(".dock-steps");
  if (!list) return;
  if (rebuild) list.replaceChildren();
  const settle = (ev) => {
    if (ev.kind === "tool_result") {
      const row = list.querySelector(`[data-tool="${CSS.escape(ev.id || "")}"]`);
      if (row) fillResult(row, ev);
      return true;
    }
    if (ev.kind === "ask_done") {
      const row = list.querySelector(`[data-ask="${CSS.escape(ev.id)}"]`);
      if (row) {
        row.classList.add(`ask-${ev.outcome}`);
        const out = row.querySelector(".ask-outcome");
        if (out) out.textContent = `→ ${ev.answer}`;
      }
      return true;
    }
    return false;
  };
  for (const ev of events) {
    if (settle(ev)) continue;
    const el = stepEl(ev);
    if (el) list.append(el);
  }
  // results can arrive before their row on a rebuild — settle them
  if (rebuild) for (const ev of events) settle(ev);
  scrollToEnd();
}

function scrollToEnd(force = false) {
  const list = dock().querySelector(".dock-steps");
  if (list && (force || list.dataset.pinned !== "false")) list.scrollTop = list.scrollHeight;
}

function stepEl(ev) {
  if (ev.kind === "init") {
    return h("li", { class: "step step-meta" }, `${ev.turn > 1 ? "Continued" : "Started"}${ev.model ? ` · ${ev.model}` : ""}`);
  }
  if (ev.kind === "thinking") {
    const words = ev.text.split(/\s+/).length;
    return h("li", { class: "step step-thinking" },
      h("details", {}, h("summary", {}, `Thought · ${words} words`), h("div", { class: "step-text" }, ev.text)));
  }
  if (ev.kind === "text") return h("li", { class: "step step-text-msg" }, mdLite(ev.text));
  if (ev.kind === "user") return h("li", { class: "step step-user" }, h("div", { class: "bubble" }, ev.text));
  if (ev.kind === "result") {
    if (!ev.text) return null;
    return h("li", { class: `step step-result ${ev.ok ? "" : "bad"}` },
      h("div", { class: "step-result-head" }, ev.ok ? "Summary" : "Ended with an error",
        h("span", { class: "muted" }, [ev.cost_usd ? `$${ev.cost_usd.toFixed(2)}` : null, ev.duration_ms ? duration(ev.duration_ms / 1000) : null].filter(Boolean).join(" · "))),
      mdLite(ev.text));
  }
  if (ev.kind === "ask") {
    const a = ev.ask;
    const what = a.kind === "question" ? (a.questions[0]?.question || "A question") : `${a.title}: ${a.detail}`;
    return h("li", { class: "step step-ask", "data-ask": a.id },
      h("span", { class: "tool-icon" }, icon(a.kind === "question" ? "info" : "shield")),
      h("span", { class: "ask-what" }, a.kind === "question" ? "Asked: " : "Permission: ", what),
      h("span", { class: "ask-outcome" }, a.answer ? `→ ${a.answer}` : ""));
  }
  if (ev.kind === "error") return h("li", { class: "step step-error" }, icon("alert"), h("span", {}, ev.text));
  if (ev.kind === "log") return h("li", { class: "step step-log mono" }, linkify(ev.text));
  if (ev.kind === "tool") {
    const isUrl = /^https?:\/\//.test(ev.target || "");
    const d = h("details", { class: "tool" },
      h("summary", {},
        h("span", { class: "tool-icon" }, icon(VERB_ICON[ev.verb] || "terminal")),
        h("span", { class: "tool-verb" }, ev.verb),
        h("span", { class: "tool-target mono", title: ev.target }, ev.target),
        isUrl ? h("a", { class: "tool-link", href: ev.target, target: "_blank", rel: "noopener noreferrer", title: "Open the page",
          onclick: (e) => e.stopPropagation() }, icon("external")) : null,
        h("span", { class: `tool-state ${ev.status}`, "aria-label": ev.status }, ev.status === "running" ? h("span", { class: "spinner sm" }) : null)),
      h("pre", { class: "tool-output" }, ev.status === "running" ? "Running…" : ""));
    return h("li", { class: "step step-tool", "data-tool": ev.id || "" }, d);
  }
  return null;
}

function fillResult(row, ev) {
  const state = row.querySelector(".tool-state");
  state.className = `tool-state ${ev.status}`;
  state.replaceChildren(ev.status === "error" ? icon("alert") : icon("check"));
  state.setAttribute("aria-label", ev.status === "error" ? "failed" : "done");
  row.querySelector(".tool-output").textContent = ev.output || "(no output)";
  if (ev.status === "error") row.classList.add("failed");
}

export function initDock() {
  if (!document.getElementById("agent-dock")) {
    document.body.append(h("section", { id: "agent-dock", class: "agent-dock", hidden: true, "aria-label": "Agent runs" }));
  }
}
