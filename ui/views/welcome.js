// Get started — from a fresh install to a first audited application, without
// a terminal: the agent and its sign-in, the tools, your documents (uploaded
// here, ingested by intake.py), then /setup in the run panel, then a first
// /hunt. Each step says what is done and what is next.
import { h, get, post, upload, toast, fmt } from "../lib.js";
import { icon } from "../icons.js";
import { pageHead, notice } from "../components.js";
import { render as rerender, setOnboarded, go } from "../app.js";
import { runButton, startInstall, chosenAgent, getAgents, copyChip, loadAgents } from "../agent.js";

const ACCEPT = ".pdf,.docx,.doc,.odt,.rtf,.md,.txt,.html,.htm,.csv,.json,.yaml,.yml,.zip";

export async function render() {
  const o = await get("/api/onboarding");
  if (o.complete) setOnboarded(true);
  const page = h("div", { class: "welcome" }, pageHead(o.complete ? "You're set up" : "Get started",
    o.complete ? "Your profile is built. From here the Overview is home; this page stays for re-runs."
      : "From here to your first audited application in about 30 minutes. Everything stays on this machine."));

  if (!o.workspace.separate) {
    page.append(notice(h("span", {}, "Your data would be written inside the engine folder (",
      h("code", {}, o.workspace.path), "). Setup will first offer to move it into its own private folder."), "warn", "alert"));
  }

  const agentSlot = h("div", {}, h("p", { class: "loading" }, "Checking your agent…"));
  const toolSlot = h("div", {}, h("p", { class: "loading" }, "Checking tools…"));
  const docs = o.documents;
  const steps = h("ol", { class: "steps" },
    step(1, "Your agent", "Jobissimo's work is done by your own Claude Code or Codex, signed in with your plan.", agentSlot, "pending", "agent"),
    step(2, "Tools", "Pandoc turns your CV into a Word file; the rest are optional.", toolSlot, "pending", "tools"),
    step(3, "Your documents", "CVs (several versions are better than one), your LinkedIn export, old cover letters, reviews. Any format, any language.",
      docsBlock(docs), docs.length ? "done" : "next"),
    step(4, "Build your profile", "/setup reads your documents into a knowledge base, asks what it couldn't find, sets your targets, and prepares one real application to check its work.",
      setupBlock(o), o.setup.complete ? "done" : docs.length ? "next" : "later"),
    step(5, "First results", "Find and score postings on your boards; the best ones get prepared.",
      firstBlock(o), o.jobs ? "done" : o.setup.complete ? "next" : "later"));
  page.append(steps);
  page.append(appBlock(o.launcher));

  get("/api/settings").then((s) => {
    fillAgent(agentSlot, s);
    fillTools(toolSlot, s);
  }).catch((e) => {
    agentSlot.replaceChildren(notice(e.message, "warn", "alert"));
    toolSlot.replaceChildren();
  });
  return page;
}

function step(n, title, text, body, state, key) {
  return h("li", { class: `step-card st-${state}`, "data-step": key || String(n) },
    h("div", { class: "step-num", "aria-hidden": "true" }, state === "done" ? icon("check") : String(n)),
    h("div", { class: "step-main" },
      h("div", { class: "step-title" }, h("h2", {}, title), stateChip(state)),
      h("p", { class: "step-text" }, text),
      body));
}

function stateChip(state) {
  const label = { done: "Done", next: "Next", later: "After the steps above", pending: "Checking", warn: "Needs you" }[state];
  return h("span", { class: `chip step-state ${state}` }, label);
}

function setStepState(el, state) {
  const card = el.closest(".step-card");
  if (!card) return;
  card.className = `step-card st-${state}`;
  card.querySelector(".step-state").replaceWith(stateChip(state));
  const num = card.querySelector(".step-num");
  num.replaceChildren(state === "done" ? icon("check") : card.dataset.step === "agent" ? "1" : "2");
}

// ---------------------------------------------------------------- 1 · agent

function fillAgent(slot, s) {
  const id = chosenAgent() || (s.agents.claude.available ? "claude" : s.agents.codex.available ? "codex" : null);
  const a = id ? s.agents[id] : null;
  const ok = a && a.available && a.signed_in !== false;
  const lines = [];
  if (!s.agents.claude.available && !s.agents.codex.available) {
    lines.push(h("p", {}, "Install one, sign in once in a terminal, then check again here. Claude Code (recommended — it can ask you questions while it works):"),
      h("div", { class: "toolbar" }, copyChip("curl -fsSL https://claude.ai/install.sh | bash"), h("span", { class: "muted" }, "then"), copyChip("claude")),
      h("p", { class: "muted" }, "Or Codex: ", h("code", {}, "brew install --cask codex"), " then ", h("code", {}, "codex login"), "."));
  } else if (a && a.signed_in === false) {
    lines.push(h("p", {}, `${a.label} is installed but not signed in. Sign in once in a terminal:`),
      h("div", { class: "toolbar" }, copyChip(id === "claude" ? "claude" : "codex login")));
  } else if (a) {
    const acct = a.account || {};
    lines.push(h("p", { class: "ok-line" }, icon("check"), `${a.label} ${a.version ? `(${a.version.split(" ")[0]})` : ""} — signed in`,
      acct.subscriptionType ? h("span", { class: "muted" }, ` · ${acct.subscriptionType}`) : null,
      h("a", { href: "#/settings", class: "muted" }, " · Settings")));
    const conns = a.connectors || {};
    if (id === "claude") {
      lines.push(h("p", { class: "muted" }, "Optional: ",
        conns["claude-in-chrome"] === "connected" ? "Chrome is connected" : "the Claude in Chrome extension lets it browse logged-in job boards",
        " · ", conns["claude.ai Gmail"] === "connected" ? "Gmail is connected (read-only)" : "connecting Gmail lets it read job alerts", "."));
    }
  }
  lines.push(h("button", { type: "button", class: "btn btn-sm", onclick: async () => { await loadAgents(); await get("/api/settings?refresh=1"); rerender(); } }, icon("refresh"), "Check again"));
  slot.replaceChildren(...lines);
  setStepState(slot, ok ? "done" : "warn");
}

// ---------------------------------------------------------------- 2 · tools

function fillTools(slot, s) {
  const rows = s.tools.filter((t) => t.id !== "python3" && t.id !== "git").map((t) => h("div", { class: "tool-row" },
    h("span", { class: `sdot ${t.found ? "ok" : t.required ? "bad" : "quiet"}`, "aria-hidden": "true" }),
    h("span", { class: "grow" }, h("strong", {}, t.label), h("span", { class: "muted" }, ` — ${t.purpose}${t.required ? "" : " (optional)"}`)),
    t.found ? h("span", { class: "muted" }, "Installed")
      : t.install && s.brew ? h("button", { type: "button", class: "btn btn-sm", onclick: () => startInstall(t.id) }, `Install`)
        : h("code", {}, linuxHint(t.id))));
  slot.replaceChildren(...[...rows,
    !s.brew && s.tools.some((t) => !t.found) ? h("p", { class: "muted" }, "Install the missing ones with your package manager, then check again.") : null].filter(Boolean));
  const pandoc = s.tools.find((t) => t.id === "pandoc");
  setStepState(slot, pandoc && pandoc.found ? "done" : "warn");
}

function linuxHint(id) {
  return { pandoc: "sudo apt install pandoc", pdf_engine: "sudo apt install texlive-xetex", poppler: "sudo apt install poppler-utils",
    tesseract: "sudo apt install tesseract-ocr" }[id] || "";
}

// ---------------------------------------------------------------- 3 · documents

function docsBlock(docs) {
  const list = h("ul", { class: "doc-list" });
  const draw = (items) => {
    list.replaceChildren(...items.map((d) => h("li", {},
      icon("file"),
      h("span", { class: "grow" }, d.name),
      h("span", { class: "muted" }, d.needs_text ? "couldn't read the text — setup will ask for a text version"
        : `${d.language && d.language !== "und" ? `${d.language} · ` : ""}${fmt.num(Number(d.words) || 0)} words`))));
  };
  draw(docs);
  const input = h("input", { type: "file", multiple: true, accept: ACCEPT, class: "sr-only", id: "doc-input" });
  const status = h("p", { class: "muted", "aria-live": "polite" });
  const send = async (files) => {
    for (const f of files) {
      status.textContent = `Reading ${f.name}…`;
      try {
        const res = await upload("/api/intake", f);
        draw(res.documents);
        toast(res.message);
      } catch (e) {
        toast(`${f.name}: ${e.message}`, "error");
      }
    }
    status.textContent = "";
    rerender();
  };
  input.addEventListener("change", () => send([...input.files]));
  const zone = h("label", { class: "dropzone", for: "doc-input" },
    icon("plus"), h("span", {}, h("strong", {}, "Drop files here"), " or click to choose"),
    h("span", { class: "muted" }, "PDF, Word, text, Markdown, HTML, or the LinkedIn export .zip — up to 25 MB each"));
  zone.addEventListener("dragover", (e) => { e.preventDefault(); zone.classList.add("over"); });
  zone.addEventListener("dragleave", () => zone.classList.remove("over"));
  zone.addEventListener("drop", (e) => { e.preventDefault(); zone.classList.remove("over"); send([...e.dataTransfer.files]); });
  return h("div", {}, zone, input, status, list,
    h("p", { class: "muted" }, "Each document is converted to text in your workspace (", h("code", {}, "_intake/"),
      ") with an id, so every fact in your CV can point back to where it came from. Nothing is uploaded anywhere."));
}

// ---------------------------------------------------------------- 4 · setup

function setupBlock(o) {
  const st = o.setup;
  const list = h("ol", { class: "stage-list" }, st.stages.map((s) => h("li", { class: `stage-${s.status}` },
    h("span", { class: "sdot-wrap" }, s.status === "done" || s.status === "deferred" ? icon("check") : h("span", { class: "sdot quiet" })),
    s.label, s.status === "deferred" ? h("span", { class: "muted" }, " (deferred)") : null)));
  const arg = st.started && !st.complete ? "--resume" : null;
  const btn = runButton("setup", arg, { label: st.complete ? "Run setup again" : st.started ? "Continue setup" : "Start setup", primary: !st.complete, small: false });
  const agents = getAgents();
  return h("div", {},
    st.started ? list : null,
    h("div", { class: "toolbar", style: { marginTop: "12px" } },
      btn || h("span", { class: "muted" }, "Set up your agent first (step 1)."),
      st.started ? h("span", { class: "muted" }, `${st.done} of ${st.total} done`) : null),
    btn ? h("p", { class: "muted" }, "About 25 minutes. It asks you things in the run panel at the bottom right — choose an option or type an answer. Stop any time; ",
      "Continue picks up where you left off.",
      agents?.agents?.codex?.available && chosenAgent() === "codex" ? " With Codex, questions come at the end of each turn and you reply." : "") : null);
}

// ---------------------------------------------------------------- 5 · first results

function firstBlock(o) {
  if (!o.setup.complete) return h("p", { class: "muted" }, "Available once your profile is built.");
  return h("div", { class: "toolbar" },
    runButton("hunt", null, { label: "Find postings", primary: !o.jobs, small: false }),
    h("button", { type: "button", class: "btn", onclick: () => go("overview") }, "Go to the Overview"),
    o.jobs ? h("span", { class: "muted" }, `${fmt.num(o.jobs)} postings so far`) : null);
}

// ---------------------------------------------------------------- open without a terminal

function appBlock(l) {
  if (!l || !l.app.supported) return null;
  const isMac = l.os === "mac";
  const where = isMac ? "your Applications folder (drag it to the Dock)" : "your app menu";
  return h("div", { class: "card app-card" },
    h("div", { class: "app-card-head" }, icon("spark"), h("h2", {}, "Open Jobissimo without a terminal")),
    l.app.installed
      ? h("p", {}, icon("check"), ` The Jobissimo app is in ${where}. It opens this page, starting it if needed; after 30 minutes with no page open and no run going, it stops by itself.`)
      : h("p", {}, `Add a Jobissimo app to ${where}. It opens this page, starting it if needed, and stops by itself after 30 idle minutes.`),
    h("div", { class: "toolbar" },
      h("button", { type: "button", class: "btn btn-sm", onclick: () => launcherCall("app", { action: "install" }) },
        l.app.installed ? "Reinstall the app" : "Add the app"),
      h("label", { class: "switch" },
        h("input", { type: "checkbox", checked: l.login.on, onchange: (e) => launcherCall("login", { on: e.target.checked }) }),
        h("span", {}, "Start in the background when I log in"))));
}

export async function launcherCall(what, body) {
  try {
    const res = await post(`/api/launcher/${what}`, body);
    toast(res.message);
    rerender();
  } catch (e) {
    toast(e.message, "error");
  }
}
