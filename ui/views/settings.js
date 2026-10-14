// Settings — what agent runs need on this machine, checked live: the agent
// CLIs and their sign-in, what a run may do without asking, the browser and
// mail connectors, run preferences, and the local tools the pipeline uses.
// Every change goes through scripts/agent_setup.py; permission rules live in
// Claude Code's own .claude/settings.local.json, so they apply in the chat too.
import { h, get, post, toast } from "../lib.js";
import { icon } from "../icons.js";
import { pageHead, sectionHead, segmented } from "../components.js";
import { render as rerender } from "../app.js";
import { chosenAgent, setChosenAgent, startInstall, loadAgents, onRunFinished } from "../agent.js";
import { launcherCall } from "./welcome.js";

let refreshNext = false;
let hooked = false;

export async function render() {
  if (!hooked) {  // an install finishing changes the tool list
    hooked = true;
    onRunFinished((m) => { if (m.agent === "task") refreshNext = true; });
  }
  const s = await get(`/api/settings${refreshNext ? "?refresh=1" : ""}`);
  refreshNext = false;
  const again = h("button", { type: "button", class: "btn btn-sm", onclick: async (e) => {
    e.currentTarget.disabled = true;
    e.currentTarget.replaceChildren(h("span", { class: "spinner sm" }), "Checking…");
    refreshNext = true;
    await loadAgents();
    rerender();
  } }, icon("refresh"), "Check again");
  const page = h("div", {}, pageHead("Settings",
    "What agent runs can use on this machine — checked live. Changes apply to the next run.", again));

  if (s.recommendations.length) {
    page.append(h("div", { class: "section recs" }, s.recommendations.map(recEl)));
  }

  page.append(h("div", { class: "section" }, sectionHead("Agents", "the CLIs that run your commands, with your own login and plan"),
    h("div", { class: "agent-cards" }, agentCard("claude", s.agents.claude, s), agentCard("codex", s.agents.codex, s))));

  page.append(permissionsSection(s));
  page.append(prefsSection(s));
  page.append(toolsSection(s));
  page.append(computerSection(s.launcher));

  page.append(h("div", { class: "section" }, sectionHead("Workspace"),
    h("div", { class: "rows" },
      kv("Workspace", h("span", { class: "mono" }, s.workspace.path)),
      kv("Config", h("span", { class: "mono" }, s.workspace.config)),
      kv("Synced", s.workspace.git ? "Yes — a private git repo (/sync)" : h("span", { class: "muted" }, "Not a git repo — /sync init sets it up")),
      kv("Browse adapter", s.adapters.browse || h("span", { class: "muted" }, "not set"), "From capabilities.yaml — /doctor --capabilities re-detects it."),
      kv("Mail adapter", s.adapters.mail || h("span", { class: "muted" }, "not set")),
      kv("Permission rules", h("span", { class: "mono" }, s.workspace.settings_file), "Claude Code's own per-machine file (git-ignored)."),
      kv("Run preferences", h("span", { class: "mono" }, s.workspace.prefs_file), "Machine-specific, never synced."))));
  return page;
}

// ---------------------------------------------------------------- pieces

function kv(label, value, help) {
  return h("div", { class: "row setting" },
    h("div", {}, h("div", { class: "s-label" }, label), help ? h("div", { class: "s-help" }, help) : null),
    h("div", { class: "s-value" }, value));
}

function dot(state) {
  return h("span", { class: `sdot ${state}`, "aria-hidden": "true" });
}

function recEl(r) {
  const fix = r.fix ? fixButton(r.fix) : null;
  return h("div", { class: `notice ${r.level === "info" ? "" : "warn"} rec` },
    icon(r.level === "info" ? "info" : "alert"),
    h("div", { class: "grow" }, r.text),
    fix);
}

function fixButton(fix) {
  if (fix.kind === "permission") {
    return h("button", { type: "button", class: "btn btn-sm", onclick: () => setPermission(fix.capability, fix.mode) }, "Allow");
  }
  if (fix.kind === "pref") {
    return h("button", { type: "button", class: "btn btn-sm", onclick: () => setPref(fix.key, fix.value) },
      typeof fix.value === "boolean" ? "Turn on" : `Use ${fix.value}`);
  }
  if (fix.kind === "codex_trust") {
    return h("button", { type: "button", class: "btn btn-sm", onclick: trustCodex }, "Trust this repo");
  }
  if (fix.kind === "install") {
    return h("button", { type: "button", class: "btn btn-sm", onclick: () => startInstall(fix.tool) }, "Install");
  }
  return null;
}

async function call(path, body, msg) {
  try {
    const res = await post(path, body);
    toast(msg || res.message || "Saved");
    refreshNext = path.includes("codex-trust");
    await loadAgents();
    rerender();
  } catch (e) {
    toast(e.message, "error");
  }
}

const setPermission = (capability, mode) => call("/api/settings/permission", { capability, mode }, "Saved to .claude/settings.local.json");
const setPref = (key, value) => call("/api/settings/pref", { key, value }, "Saved");
const trustCodex = () => call("/api/settings/codex-trust", {}, "Codex now trusts this repo");

function agentCard(id, a, s) {
  const using = chosenAgent() === id;
  const lines = [];
  if (!a.available) {
    lines.push(h("div", { class: "ac-line" }, dot("bad"), "Not installed",
      h("a", { href: id === "claude" ? "https://docs.claude.com/en/docs/claude-code/setup" : "https://github.com/openai/codex",
        target: "_blank", rel: "noopener noreferrer" }, "How to install")));
  } else {
    lines.push(h("div", { class: "ac-line" }, dot("ok"), a.version || "Installed"));
    if (a.signed_in === true) {
      const acct = a.account || {};
      lines.push(h("div", { class: "ac-line" }, dot("ok"), "Signed in",
        acct.subscriptionType || a.login ? h("span", { class: "muted" }, ` · ${acct.subscriptionType || a.login}`) : null,
        acct.email ? h("span", { class: "muted" }, ` · ${acct.email}`) : null));
    } else if (a.signed_in === false) {
      lines.push(h("div", { class: "ac-line" }, dot("bad"), "Not signed in — run ", h("code", {}, id === "claude" ? "claude" : "codex login"), " in a terminal"));
    } else if (s.quick || a.error) {
      lines.push(h("div", { class: "ac-line" }, dot("quiet"), a.error || "Sign-in not checked"));
    }
    if (id === "claude" && a.connectors) {
      const want = [["claude-in-chrome", "Chrome"], ["claude.ai Gmail", "Gmail"]];
      lines.push(h("div", { class: "ac-line" }, "Connectors:",
        want.map(([k, label]) => h("span", { class: "conn" }, dot(a.connectors[k] === "connected" ? "ok" : a.connectors[k] ? "warn" : "quiet"),
          label, h("span", { class: "muted" }, a.connectors[k] ? ` ${a.connectors[k]}` : " not set up")))));
      lines.push(h("div", { class: "ac-line muted" }, "Asks you live: questions and permission requests appear in the run panel."));
    }
    if (id === "codex") {
      lines.push(h("div", { class: "ac-line" }, dot(a.trusted ? "ok" : "warn"),
        a.trusted ? "Trusts this repo" : "Doesn't trust this repo — its command rules don't load",
        a.trusted ? null : h("button", { type: "button", class: "btn btn-sm", onclick: trustCodex }, "Trust")));
      if (a.model || a.reasoning_effort) {
        lines.push(h("div", { class: "ac-line muted" }, `Model ${a.model || "default"} · reasoning ${a.reasoning_effort || "default"} (~/.codex/config.toml)`));
      }
      lines.push(h("div", { class: "ac-line muted" }, "Can't ask mid-run: it ends with its questions and you reply."));
    }
  }
  return h("div", { class: `card agent-card ${using ? "using" : ""}` },
    h("div", { class: "ac-head" },
      h("div", { class: "ac-name" }, a.label || id),
      a.available ? (using ? h("span", { class: "chip" }, icon("check"), "Runs commands")
        : h("button", { type: "button", class: "btn btn-sm", onclick: () => { setChosenAgent(id); rerender(); } }, "Use for runs")) : null),
    lines);
}

function permissionsSection(s) {
  const c = s.agents.claude;
  const rows = Object.entries(s.permissions).map(([cap, p]) => {
    const extra = cap === "web_pages" && p.saved && p.saved.length
      ? h("details", { class: "s-help saved" }, h("summary", {}, `+ ${p.saved.length} site${p.saved.length > 1 ? "s" : ""} you allowed during runs`),
        h("div", { class: "mono" }, p.saved.join(", ")))
      : null;
    return h("div", { class: "row setting perm" },
      h("div", {}, h("div", { class: "s-label" }, p.label), h("div", { class: "s-help" }, p.help), extra),
      segmented(p.modes, p.mode, (mode) => { if (mode !== p.mode) setPermission(cap, mode); }, p.label));
  });
  const fixed = [
    ["Change files", "Inside the workspace without asking; anywhere else asks you."],
    ["Run commands", "The Jobissimo scripts without asking (the project allowlist); anything else asks you. sync.py status only."],
    ["Never", "Start another agent, change these settings, submit an application, or bypass an audit — refused without asking."],
  ];
  return h("div", { class: "section" },
    sectionHead("What runs may do without asking", c.available ? "Claude Code — anything else, it asks you in the run panel" : "Claude Code"),
    h("div", { class: "rows" }, rows, fixed.map(([l, t]) => kv(l, h("span", { class: "muted" }, t)))),
    h("p", { class: "muted" }, "Saved in Claude Code's own ", h("code", {}, ".claude/settings.local.json"),
      ", so they also apply when you use Claude Code in the chat. Codex runs follow the sandbox below."));
}

function prefsSection(s) {
  const specs = s.pref_specs;
  const row = (key) => {
    const spec = specs[key];
    const v = s.prefs[key];
    let control;
    if (spec.type === "bool") {
      control = h("label", { class: "switch" },
        h("input", { type: "checkbox", checked: Boolean(v), onchange: (e) => setPref(key, e.target.checked) }),
        h("span", {}, v ? "On" : "Off"));
    } else if (spec.type === "int") {
      const input = h("input", { class: "input input-sm num", type: "number", min: String(spec.min), max: String(spec.max), value: String(v),
        "aria-label": spec.label });
      input.addEventListener("change", () => setPref(key, input.value));
      control = input;
    } else {
      control = h("select", { class: "select select-sm", "aria-label": spec.label, onchange: (e) => setPref(key, e.target.value) },
        spec.choices.map((c) => h("option", { value: c, selected: c === v }, c || "Default")));
    }
    return h("div", { class: "row setting" },
      h("div", {}, h("div", { class: "s-label" }, spec.label), h("div", { class: "s-help" }, spec.help)),
      h("div", { class: "s-value" }, control));
  };
  const group = (title, keys) => [h("div", { class: "row group-head" }, title), keys.map(row)];
  return h("div", { class: "section" }, sectionHead("Run preferences", "for runs started here; the chat keeps its own"),
    h("div", { class: "rows" },
      group("Claude Code", ["claude.model", "claude.effort", "claude.chrome"]),
      group("Codex", ["codex.reasoning_effort", "codex.network", "codex.web_search"]),
      group("Runs", ["runs.max_parallel", "runs.ask_timeout_min"])));
}

function computerSection(l) {
  if (!l) return null;
  const isMac = l.os === "mac";
  const rows = [];
  if (l.app.supported) {
    rows.push(kv(isMac ? "Jobissimo app" : "App-menu entry",
      h("div", { class: "toolbar", style: { margin: 0 } },
        l.app.installed ? h("span", { class: "mono muted" }, l.app.path) : h("span", { class: "muted" }, "Not added"),
        h("button", { type: "button", class: "btn btn-sm", onclick: () => launcherCall("app", { action: "install" }) }, l.app.installed ? "Reinstall" : "Add"),
        l.app.installed ? h("button", { type: "button", class: "btn btn-ghost btn-sm", onclick: () => launcherCall("app", { action: "uninstall" }) }, "Remove") : null),
      "Opens this page without a terminal, starting it if needed; it stops by itself after 30 minutes with no page open and no run. Reinstall after moving the workspace."));
    rows.push(kv("Start at login",
      h("label", { class: "switch" }, h("input", { type: "checkbox", checked: l.login.on, onchange: (e) => launcherCall("login", { on: e.target.checked }) }),
        h("span", {}, l.login.on ? "On — runs in the background, opens instantly" : "Off")),
      "Keeps it running in the background from login, so the app opens instantly."));
  }
  rows.push(kv("Quit", h("button", { type: "button", class: "btn btn-sm", onclick: () => document.getElementById("quit-button").click() }, "Quit Jobissimo"),
    `Stops this page's server${l.pid ? ` (pid ${l.pid})` : ""} and any runs. Log: ${l.log}`));
  return h("div", { class: "section" }, sectionHead("This computer"), h("div", { class: "rows" }, rows));
}

function toolsSection(s) {
  return h("div", { class: "section" }, sectionHead("Tools", s.brew ? "missing ones install with Homebrew, shown in the run panel" : "install missing ones with your package manager"),
    h("div", { class: "rows" }, s.tools.map((t) => h("div", { class: "row setting" },
      h("div", {}, h("div", { class: "s-label" }, dot(t.found ? "ok" : t.required ? "bad" : "quiet"), t.label,
        t.required ? null : h("span", { class: "muted" }, " · optional")),
      h("div", { class: "s-help" }, t.purpose)),
      h("div", { class: "s-value" }, t.found
        ? h("span", { class: "mono muted" }, Object.values(t.paths)[0] || "found")
        : t.install && s.brew ? h("button", { type: "button", class: "btn btn-sm", onclick: () => startInstall(t.id) }, `Install ${t.install}`)
          : h("span", { class: "muted" }, "Not found"))))));
}

