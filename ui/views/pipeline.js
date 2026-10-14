// Pipeline — how Jobissimo runs for you: the stages, the runs, the settings
// it runs on, and the changes the optimiser proposes. Every setting change
// needs a reason and is recorded.
import { h, get, post, fmt, toast } from "../lib.js";
import { icon } from "../icons.js";
import { pageHead, sectionHead, panel, closePanel, commandChip, notice } from "../components.js";
import { render as rerender, refreshCounts } from "../app.js";
import { runButton, canRun } from "../agent.js";

const RUN_ORDER = ["cycle", "hunt", "prepare", "refresh", "enrich", "optimise", "doctor"];

export async function render() {
  const p = await get("/api/pipeline");
  const page = h("div", {}, pageHead("Pipeline", "How Jobissimo runs for you, and the settings it runs on."));

  // stages, left to right, with the command that moves each one on
  page.append(h("div", { class: "stages", role: "list", "aria-label": "Pipeline stages" }, p.stages.map((st) =>
    h("div", { class: "stage", role: "listitem" },
      h("div", { class: "label" }, st.label),
      h("div", { class: "value" }, fmt.num(st.count)),
      st.command ? h("div", { class: "cmd" }, st.command) : h("div", { class: "cmd" }, " ")))));
  const parked = Object.entries(p.parked).filter(([, n]) => n);
  if (parked.length) {
    page.append(h("p", { class: "muted", style: { margin: "12px 2px 0" } },
      `Set aside: ${parked.map(([k, n]) => `${n} ${k.replace("_", " ")}`).join(" · ")}. Discarded postings are kept so they are never re-processed.`));
  }

  // run a command in the user's own agent
  if (RUN_ORDER.some(canRun)) {
    page.append(h("div", { class: "section" }, sectionHead("Run a command", "in your own Claude Code or Codex, on this machine"),
      h("div", { class: "rows run-list" }, RUN_ORDER.filter(canRun).map((c) => h("div", { class: "row" },
        h("span", { class: "row-icon" }, icon("play")),
        h("div", { class: "grow" }, h("div", { class: "row-title mono" }, `/${c}`), h("div", { class: "row-sub" }, runHelp(c))),
        runButton(c, null, { label: "Run" })))),
      h("p", { class: "muted" }, "Runs use your agent's own login and plan, and several can go at once (never two that touch the same thing). When a run needs a decision or a permission it asks you in the run panel; a finished run takes a reply. /apply, /setup and /sync stay in the chat. What runs may do without asking: ", h("a", { href: "#/settings" }, "Settings"), ".")));
  }

  // suggestions first: they are the decisions waiting on you
  const sugg = p.suggestions.items.filter((s) => ["pending", "approved", "deferred"].includes(s.status));
  page.append(h("div", { class: "section" }, sectionHead("Suggested changes",
    p.suggestions.latest_report ? `latest report: ${p.suggestions.latest_report}` : null),
  sugg.length ? h("div", { class: "rows" }, sugg.map(suggestionRow))
    : h("div", {}, notice(h("span", {}, "No suggestions waiting. ", h("span", {}, "Run "), commandChip("/optimise"),
      h("span", {}, " to analyse outcomes and propose changes — each one needs your approval.")))),
  p.suggestions.queued_from_runs ? h("p", { class: "muted" }, `${p.suggestions.queued_from_runs} problem reports from runs are queued for the next /optimise.`) : null));

  // runs
  const runs = p.runs.latest;
  page.append(h("div", { class: "section" }, sectionHead("Recent runs", p.runs.orphans ? h("span", { class: "meta tag-warn" }, `${p.runs.orphans} without an end`) : null),
    runs.length ? h("div", { class: "rows" }, runs.map((r) => h("div", { class: "row" },
      h("span", { class: "row-icon" }, icon("play")),
      h("div", { class: "grow" }, h("div", { class: "row-title" }, `/${r.command}`), h("div", { class: "row-sub mono" }, r.run_id)),
      h("span", { class: `status ${r.orphan ? "s-warn" : r.status === "complete" ? "s-good" : "s-warn"}` }, r.orphan ? "no end logged" : r.status),
      h("span", { class: "row-meta" }, fmt.relative(r.start || r.end))))) : notice("No runs logged yet."),
    p.runs.orphans ? h("p", { class: "muted" }, "A run without an end is one that stopped mid-way (a closed session, a stall). It is invisible to /optimise's run statistics; /doctor lists them.") : null,
    h("div", { class: "toolbar", style: { marginTop: "14px" } }, h("span", { class: "subtle" }, "Run the whole loop:"), commandChip("/cycle"),
      h("span", { class: "muted" }, `default ${p.cycle.default_intensity || "daily"}`))));

  // settings
  const settings = h("div", { class: "section" }, sectionHead("Settings", h("span", { class: "meta mono", title: "Config revision" }, `rev ${p.config_rev}`)));
  for (const g of p.settings) {
    settings.append(h("div", { class: "settings-group" }, h("h3", {}, g.title),
      h("div", { class: "rows" }, g.items.map((it) => settingRow(it)))));
  }
  settings.append(h("div", { class: "settings-group" }, h("h3", {}, "Targets"),
    h("div", { class: "rows" }, (p.targets.length ? p.targets : [{}]).map((t) => h("div", { class: "row" },
      t.cluster ? [h("span", { class: "chip mono" }, `#${t.rank ?? "–"}`),
        h("div", { class: "grow" }, h("div", { class: "row-title" }, t.cluster),
          h("div", { class: "row-sub" }, [t.seniority_band, t.hunt_share !== undefined ? `${Math.round(t.hunt_share * 100)}% of the hunt` : null, t.experiment ? "experiment" : null].filter(Boolean).join(" · ")))]
        : h("div", { class: "grow muted" }, "No targets configured."),
      h("span", { class: "row-meta" }, "via /setup or /optimise")))),
    h("p", { class: "muted" }, `Pack: ${p.pack}${p.salary_expectation ? ` · salary expectation ${fmt.num(p.salary_expectation.amount)} ${p.salary_expectation.currency} (applicant profile)` : ""}`)));
  page.append(settings);

  // sources
  page.append(h("div", { class: "section" }, sectionHead("Sources", `${p.boards.length} boards in the catalogue`),
    h("div", { class: "table-wrap" }, h("table", {},
      h("caption", { class: "sr-only" }, "Sources by results"),
      h("thead", {}, h("tr", {}, ["Source", "Found", "Applied", "Replies", "Reply rate"].map((x, i) => h("th", { scope: "col", class: i ? "num" : "" }, x)))),
      h("tbody", {}, p.sources.slice(0, 12).map((s) => h("tr", {},
        h("td", { class: "cell-title" }, s.slug),
        h("td", { class: "num" }, fmt.num(s.found)), h("td", { class: "num" }, fmt.num(s.applied)),
        h("td", { class: "num" }, fmt.num(s.responded)),
        h("td", { class: "num" }, s.applied >= 8 ? fmt.pct(s.responded / s.applied) : h("span", { class: "muted" }, s.applied ? "few" : "–")))))))));

  // history + guarantees
  page.append(h("div", { class: "section split" },
    h("div", {}, sectionHead("Change history"),
      p.history.length ? h("ul", { class: "timeline" }, p.history.map((c) => h("li", { class: "key" },
        h("div", {}, h("span", { class: "mono" }, c.key), ` ${JSON.stringify(c.from)} → ${JSON.stringify(c.to)}`),
        h("div", { class: "subtle" }, c.reason), h("div", { class: "when" }, `${fmt.date(c.ts)}${c.suggestion ? ` · ${c.suggestion}` : ""}`))))
        : h("p", { class: "muted" }, "Changes made here or by approved suggestions appear with their reason.")),
    h("div", {}, sectionHead("Always true"),
      h("div", { class: "rows" }, p.invariants.map((x) => h("div", { class: "row", style: { alignItems: "flex-start" } },
        h("span", { class: "row-icon" }, icon("shield")),
        h("div", { class: "grow" }, h("div", { class: "row-title" }, x.title), h("div", { class: "row-sub", style: { whiteSpace: "normal" } }, x.text))))),
      h("p", { class: "muted" }, "These are part of the engine, not settings: nothing here can turn them off."))));
  return page;
}

const RUN_HELP = {
  cycle: "Reconcile mail, hunt, prepare the freshest postings, and report.",
  hunt: "Find, score and record new postings on your boards.",
  prepare: "Prepare the most perishable shortlisted job (or pick one in Applications).",
  refresh: "Check that open postings are still live; mark closed ones missed.",
  enrich: "Answer the profile questions that matter most — about five minutes, in the run panel.",
  optimise: "Analyse outcomes and propose changes — they appear here for you to decide.",
  doctor: "Config health, provenance and drift.",
};
function runHelp(c) { return RUN_HELP[c] || ""; }

function show(v) {
  if (v === null || v === undefined) return h("span", { class: "muted" }, "not set");
  if (Array.isArray(v)) return v.length ? v.join(", ") : h("span", { class: "muted" }, "none");
  if (typeof v === "boolean") return v ? "Yes" : "No";
  return String(v);
}

function settingRow(it) {
  return h("div", { class: "row setting" },
    h("div", {}, h("div", { class: "s-label" }, it.label), it.help ? h("div", { class: "s-help" }, it.help) : null),
    h("div", { class: "s-value" }, show(it.value)),
    it.editable ? h("button", { type: "button", class: "btn btn-sm", onclick: () => editSetting(it), "aria-label": `Change ${it.label}` }, "Change")
      : h("span", { class: "muted", title: "Not in your config yet — set it via /setup" }, "–"));
}

function editSetting(it) {
  const id = "setting-input";
  let input;
  if (it.type === "bool") {
    input = h("select", { class: "select", id }, h("option", { value: "true", selected: it.value === true }, "Yes"), h("option", { value: "false", selected: it.value === false }, "No"));
  } else if (it.type === "enum") {
    input = h("select", { class: "select", id }, it.options.map((o) => h("option", { value: o, selected: o === it.value }, o)));
  } else if (it.type === "list" && it.options) {
    input = h("div", { class: "checks", id, role: "group", "aria-label": it.label }, it.options.map((o) =>
      h("label", {}, h("input", { type: "checkbox", value: o, checked: (it.value || []).includes(o) }), o)));
  } else if (it.type === "list") {
    input = h("input", { class: "input", id, value: (it.value || []).join(", ") });
  } else {
    input = h("input", { class: "input", id, type: it.type === "text" ? "text" : "number", step: it.type === "number" ? "0.1" : "1", value: it.value ?? "" });
  }
  const reason = h("textarea", { class: "textarea", id: "setting-reason", required: true, rows: "3", placeholder: "e.g. three postings with fit 3.8 got interviews" });
  const err = h("p", { class: "tag-bad", role: "alert" });
  const read = () => {
    if (it.type === "bool") return input.value === "true";
    if (it.type === "enum") return input.value;
    if (it.type === "list" && it.options) return [...input.querySelectorAll("input:checked")].map((c) => c.value);
    if (it.type === "list") return input.value.split(",").map((x) => x.trim()).filter(Boolean);
    if (it.type === "int") return parseInt(input.value, 10);
    if (it.type === "number") return parseFloat(input.value);
    return input.value.trim();
  };
  const f = h("form", {},
    h("p", { class: "subtle", style: { marginTop: 0 } }, it.help || ""),
    h("div", { class: "field" }, it.type === "list" && it.options ? h("div", { class: "label" }, "New value") : h("label", { for: id }, "New value"), input),
    h("div", { class: "field" }, h("label", { for: "setting-reason" }, "Why are you changing it?"), reason,
      h("p", { class: "hint" }, "Recorded with the change, so you and /optimise can see later what it was for.")),
    err,
    h("div", { style: { display: "flex", gap: "8px" } },
      h("button", { type: "submit", class: "btn btn-primary" }, "Save change"),
      h("button", { type: "button", class: "btn btn-ghost", onclick: closePanel }, "Cancel")));
  f.addEventListener("submit", async (e) => {
    e.preventDefault();
    const value = read();
    if (typeof value === "number" && Number.isNaN(value)) { err.textContent = "Enter a number."; return; }
    try {
      const res = await post("/api/config", { file: it.file, key: it.key, value, reason: reason.value });
      toast(res.message);
      closePanel();
      await rerender();
    } catch (ex) { err.textContent = ex.message; }
  });
  panel({ title: it.label, subtitle: h("span", { class: "mono" }, `config/${it.file}.yaml · ${it.key}`), body: f });
}

function suggestionRow(sg) {
  const decide = async (status, extra = {}) => {
    try {
      const res = await post(`/api/suggestions/${sg.id}/decision`, { status, ...extra });
      toast(res.message.split("\n").pop());
      refreshCounts();
      await rerender();
    } catch (e) { toast(e.message, "error"); }
  };
  const open = () => {
    const reason = h("input", { class: "input", placeholder: "Reason (required to reject)", "aria-label": "Reason" });
    const canApply = sg.ops.length > 0;
    panel({
      title: sg.title, subtitle: `${sg.id}${sg.lens ? ` · ${sg.lens}` : ""}${sg.target ? ` · ${sg.target}` : ""}`,
      body: h("div", {},
        h("h3", { style: { marginTop: 0 } }, "Evidence"),
        sg.evidence ? h("pre", { class: "card card-pad mono", style: { whiteSpace: "pre-wrap", fontSize: "13px", margin: 0 } }, JSON.stringify(sg.evidence, null, 2))
          : h("p", { class: "muted" }, "No evidence attached."),
        h("h3", {}, "Change"),
        canApply ? h("ul", { class: "list-plain" }, sg.ops.map((o) => h("li", {}, h("span", { class: "mono" }, `config/${o.file}.yaml · ${o.key}`), ` → ${JSON.stringify(o.to)}`)))
          : h("p", { class: "subtle" }, "A prose change: approving it lets the agent apply it on the next /optimise run."),
        h("div", { class: "field", style: { marginTop: "20px" } }, reason),
        h("div", { class: "toolbar" },
          sg.status !== "approved" ? h("button", { type: "button", class: "btn btn-primary", onclick: () => decide("approved", { apply: canApply }) }, canApply ? "Approve and apply" : "Approve") : null,
          sg.status === "approved" && canApply ? h("button", { type: "button", class: "btn btn-primary", onclick: () => decide("applied") }, "Mark applied") : null,
          h("button", { type: "button", class: "btn", onclick: () => decide("deferred") }, "Later"),
          h("button", { type: "button", class: "btn btn-ghost btn-danger", onclick: () => {
            if (!reason.value.trim()) { reason.focus(); toast("Add a reason to reject.", "error"); return; }
            decide("rejected", { reason: reason.value });
          } }, "Reject"))),
    });
  };
  return h("button", { type: "button", class: "row", onclick: open },
    h("span", { class: "row-icon accent" }, icon("spark")),
    h("div", { class: "grow" }, h("div", { class: "row-title" }, sg.title), h("div", { class: "row-sub" }, [sg.target, sg.lens].filter(Boolean).join(" · "))),
    h("span", { class: `status ${sg.status === "approved" ? "s-good" : sg.status === "deferred" ? "s-quiet" : "s-active"}` }, sg.status));
}
