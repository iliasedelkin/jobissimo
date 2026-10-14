// Applications — every posting, its state, and a detail panel per job.
import { h, get, post, fmt, statusEl, toast, OUTCOME } from "../lib.js";
import { icon } from "../icons.js";
import { pageHead, segmented, table, panel, closePanel, commandChip, empty, replacePanelBody } from "../components.js";
import { setParams, render as rerender, refreshCounts } from "../app.js";
import { runButton } from "../agent.js";

const GROUPS = [
  { id: "active", label: "Active", statuses: ["shortlisted", "generated", "ready", "applied", "responded", "offered"] },
  { id: "prepare", label: "To prepare", statuses: ["shortlisted"] },
  { id: "ready", label: "Ready to send", statuses: ["generated", "ready"] },
  { id: "applied", label: "Applied", statuses: ["applied"] },
  { id: "process", label: "In process", statuses: ["responded", "offered"] },
  { id: "closed", label: "Closed", statuses: ["closed"] },
  { id: "archive", label: "Archive", statuses: ["found", "scored", "on_hold", "missed", "skipped", "discarded"] },
];
const STATUS_TO_GROUP = { shortlisted: "prepare", ready: "ready", applied: "applied", responded: "process", closed: "closed" };

let state = { group: "active", q: "", source: "" };

export async function render(route) {
  const p = route.params;
  if (p.status) state.group = STATUS_TO_GROUP[p.status] || state.group;
  if (p.group) state.group = p.group;
  const data = await get("/api/jobs");
  const page = h("div", {}, pageHead("Applications", "Every posting Jobissimo has found, and where each one stands."));
  if (!data.items.length) {
    page.append(empty("No postings yet", "Run /hunt to find and score postings against your targets.", commandChip("/hunt")));
    return page;
  }
  const counts = Object.fromEntries(GROUPS.map((g) => [g.id, g.statuses.reduce((n, s) => n + (data.counts[s] || 0), 0)]));
  const listBox = h("div");
  const draw = () => {
    const g = GROUPS.find((x) => x.id === state.group);
    const q = state.q.trim().toLowerCase();
    const rows = data.items.filter((j) => g.statuses.includes(j.status)
      && (!state.source || j.source === state.source)
      && (!q || `${j.company} ${j.title} ${j.job_id}`.toLowerCase().includes(q)));
    listBox.replaceChildren(rows.length ? jobsTable(rows, g.id) :
      h("p", { class: "muted" }, q ? `No postings match “${state.q}”.` : "Nothing here."));
    toolbar.querySelector(".segmented").replaceWith(seg());
  };
  const seg = () => segmented(GROUPS.map((g) => ({ id: g.id, label: g.label, count: counts[g.id] })), state.group,
    (id) => { state.group = id; draw(); }, "Filter by stage");
  const search = h("input", { class: "input", type: "search", placeholder: "Search company or title", value: state.q,
    "aria-label": "Search postings", oninput: (e) => { state.q = e.target.value; draw(); } });
  const source = h("select", { class: "select", "aria-label": "Source", style: { width: "auto" },
    onchange: (e) => { state.source = e.target.value; draw(); } },
  h("option", { value: "" }, "All sources"), data.sources.map((s) => h("option", { value: s, selected: s === state.source }, s)));
  const toolbar = h("div", { class: "toolbar" }, seg(), h("div", { class: "grow" }),
    h("div", { class: "search" }, icon("search"), search), source);
  page.append(toolbar, listBox);
  draw();
  if (p.job) openJob(p.job);
  return page;
}

function jobsTable(rows, group) {
  const showApplied = ["applied", "process", "closed"].includes(group);
  return table({
    caption: "Postings",
    rows,
    sortKey: showApplied ? "applied" : null,
    sortDir: "desc",
    onRow: (j) => openJob(j.job_id),
    columns: [
      { key: "role", label: "Role", sort: (j) => j.company.toLowerCase(),
        render: (j) => h("div", {}, h("div", { class: "cell-title" }, j.company), h("div", { class: "cell-sub" }, j.title)) },
      { key: "status", label: "Status", render: (j) => statusEl(j.status, j.outcome), sort: (j) => j.status },
      { key: "fit", label: "Fit", num: true, sort: (j) => j.fit, render: (j) => (j.fit ? j.fit.toFixed(1) : "–") },
      { key: "ats", label: "ATS", num: true, sort: (j) => j.ats, render: (j) => (j.ats ?? "–") },
      showApplied
        ? { key: "applied", label: "Applied", sort: (j) => j.date_applied, render: (j) => fmt.date(j.date_applied) }
        : { key: "age", label: "Found", num: true, sort: (j) => j.age_days, render: (j) => (j.age_days === null ? "–" : `${j.age_days}d ago`) },
      { key: "next", label: "Next", render: (j) => (j.next ? h("span", { class: "subtle" }, j.next) : h("span", { class: "muted" }, "–")) },
    ],
  });
}

// ---------------------------------------------------------------- detail panel

let currentJob = null;

export async function openJob(jobId) {
  currentJob = jobId;
  let j;
  try {
    j = await get(`/api/jobs/${encodeURIComponent(jobId)}`);
  } catch (e) {
    toast(e.message, "error");
    return;
  }
  const link = j.url ? h("a", { class: "btn btn-sm", href: j.url, target: "_blank", rel: "noopener noreferrer" }, icon("external"), "Posting") : null;
  panel({
    title: j.company, subtitle: j.title, actions: link, label: `${j.company} details`,
    body: jobBody(j),
    onClose: () => { currentJob = null; if (location.hash.startsWith("#/applications")) setParams({}); },
  });
  // after panel(): opening it closes the previous one, whose onClose clears the URL
  currentJob = jobId;
  if (location.hash.startsWith("#/applications")) setParams({ job: jobId });
}

function jobBody(j) {
  const body = h("div");
  const formSlot = h("div");
  body.append(actionsFor(j, formSlot), formSlot);
  if (j.next) body.append(h("p", { class: "subtle", style: { marginTop: "-8px" } }, `Next: ${j.next}`));

  const prop = (k, v) => (v === null || v === undefined || v === "" ? null : [h("dt", {}, k), h("dd", {}, v)]);
  const cv = j.assets.find((a) => a.kind === "cv");
  body.append(h("dl", { class: "props" },
    prop("Status", statusEl(j.status, j.outcome)),
    prop("Fit", j.fit ? `${j.fit.toFixed(1)} / 5${j.priority ? ` · ${j.priority} priority` : ""}` : null),
    prop("Source", j.source),
    prop("Location", [j.location, j.remote].filter(Boolean).join(" · ")),
    prop("Language", j.language),
    prop("Target", j.role_cluster),
    prop("Found", fmt.date(j.date_found)),
    prop("Applied", j.date_applied ? fmt.date(j.date_applied) : null),
    prop("Replied", j.response_date ? fmt.date(j.response_date) : null),
    prop("ATS score", j.ats !== null && j.ats !== undefined ? `${j.ats} / 100${cv && cv.scorer_version ? ` · scorer ${cv.scorer_version}` : ""}` : null),
    prop("CV variant", cv && cv.variant_id ? h("span", { class: "mono" }, cv.variant_id) : null),
    prop("Why not", j.fields.rejection_reason)));

  if (j.stages.length) {
    body.append(h("h3", {}, "Rounds"), h("ul", { class: "list-plain" }, j.stages.map((g) => h("li", {},
      h("div", { style: { display: "flex", justifyContent: "space-between", gap: "12px" } },
        h("span", {}, `${g.seq}. ${g.kind}${g.label ? ` · ${g.label}` : ""}`),
        h("span", { class: g.result === "failed" || g.result === "declined" ? "tag-bad" : g.result === "passed" || g.result === "accepted" ? "tag-good" : "muted" },
          `${g.result} · ${fmt.date(g.date)}`))))));
  }
  if (j.fields.interview_stage) {
    body.append(h("details", {}, h("summary", { class: "subtle" }, "Process notes"), h("p", { class: "quote" }, j.fields.interview_stage)));
  }

  const f = j.folder;
  if (f) {
    const ev = f.evidence;
    body.append(h("h3", {}, "Requirements"),
      h("p", { class: "subtle", style: { margin: "0 0 8px" } },
        `${ev.explicit_match} matched directly · ${ev.implicit_match} matched indirectly · ${ev.no_evidence} without evidence`),
      f.requirements.length ? h("details", {}, h("summary", { class: "muted" }, "Show requirements"),
        h("ul", { class: "list-plain" }, f.requirements.map((r) => h("li", {},
          h("span", { class: r.status === "no_evidence" ? "tag-warn" : "" }, r.jd_wording),
          h("span", { class: "muted" }, ` · ${r.priority} · ${r.status.replace("_", " ")}`))))) : null);
    if (f.bullets.length) {
      body.append(h("h3", {}, "Evidence used in the CV"), h("ul", { class: "list-plain" }, f.bullets.map((b) => h("li", {},
        b.kind === "achievement" ? h("a", { href: `#/knowledge/experience?bullet=${encodeURIComponent(b.id)}`, class: "mono", onclick: () => closePanel() }, b.id)
          : h("span", { class: "mono" }, b.id),
        b.status === "deprecated" ? h("span", { class: "tag-warn" }, " · deprecated since") : null,
        h("div", { class: "subtle" }, b.text)))));
    }
    body.append(h("h3", {}, "Files"), h("p", { class: "subtle", style: { margin: 0 } }, h("span", { class: "mono" }, `applications/${f.name}/`)),
      h("p", { class: "muted", style: { margin: "6px 0 0" } }, f.files.filter((x) => !x.startsWith(".")).join(" · ")),
      f.audit ? h("p", { class: f.audit === "PASS" ? "tag-good" : "tag-bad" }, `Truth audit: ${f.audit}`) : null);
  }

  if (j.timeline.length) {
    body.append(h("h3", {}, "Timeline"), h("ul", { class: "timeline" }, [...j.timeline].reverse().slice(0, 30).map((e) => {
      const d = e.detail || {};
      const text = e.action === "status_change" ? `${d.from} → ${d.to}${d.outcome ? ` (${OUTCOME[d.outcome] || d.outcome})` : ""}`
        : e.action === "stage_added" ? `Round recorded: ${d.kind}`
          : e.action === "stage_resolved" ? `Round ${d.seq}: ${d.to}`
            : e.action.replaceAll("_", " ");
      return h("li", { class: e.action === "status_change" ? "key" : "" }, h("div", {}, text), h("div", { class: "when" }, `${fmt.date(e.ts)} · ${e.command || "–"}`));
    })));
  }
  return body;
}

function actionsFor(j, slot) {
  const bar = h("div", { class: "panel-actions" });
  const show = (form) => { slot.replaceChildren(form); form.querySelector("input,select,textarea,button")?.focus(); };
  const s = j.status;
  if (s === "shortlisted") {
    bar.append(runButton("prepare", j.job_id, { label: "Prepare application", primary: true }) || commandChip(`/prepare ${j.job_id}`));
  }
  if (s === "ready" || s === "generated") {
    bar.append(h("button", { class: "btn btn-accent btn-sm", type: "button", onclick: () => show(appliedForm(j)) }, "Mark as applied"),
      commandChip(`/apply ${j.job_id}`));
  }
  if (s === "applied") bar.append(h("button", { class: "btn btn-sm", type: "button", onclick: () => show(simpleStatus(j, "responded", "Record a reply", "The employer replied (any reply, including a screening call).")) }, "Record a reply"));
  if (["applied", "responded"].includes(s)) bar.append(h("button", { class: "btn btn-sm", type: "button", onclick: () => show(roundForm(j)) }, "Record a round"));
  if (j.stages.some((g) => g.result === "pending")) bar.append(h("button", { class: "btn btn-sm", type: "button", onclick: () => show(resolveForm(j)) }, "Settle a round"));
  if (["applied", "responded", "offered"].includes(s)) bar.append(h("button", { class: "btn btn-sm", type: "button", onclick: () => show(closeForm(j)) }, "Close…"));
  if (["shortlisted", "ready", "generated"].includes(s)) {
    bar.append(h("button", { class: "btn btn-ghost btn-sm", type: "button", onclick: () => show(simpleStatus(j, "missed", "Posting closed", "The posting is no longer open.")) }, "Posting closed"));
  }
  return bar;
}

function form(title, fields, submitLabel, onSubmit, note) {
  const err = h("p", { class: "tag-bad", role: "alert" });
  const el = h("form", { class: "card card-pad", style: { marginBottom: "24px" } },
    h("h3", { style: { marginTop: 0 } }, title), note ? h("p", { class: "subtle", style: { marginTop: 0 } }, note) : null, fields, err,
    h("div", { style: { display: "flex", gap: "8px" } },
      h("button", { class: "btn btn-primary btn-sm", type: "submit" }, submitLabel),
      h("button", { class: "btn btn-ghost btn-sm", type: "button", onclick: () => el.remove() }, "Cancel")));
  el.addEventListener("submit", async (e) => {
    e.preventDefault();
    const btn = el.querySelector("button[type=submit]");
    btn.disabled = true;
    err.textContent = "";
    try {
      const res = await onSubmit(new FormData(el));
      toast(res.message.split("\n")[0]);
      afterChange();
    } catch (ex) {
      err.textContent = ex.message;
      btn.disabled = false;
    }
  });
  return el;
}

function field(label, input, hint) {
  const id = `f-${Math.random().toString(36).slice(2, 8)}`;
  input.id = id;
  return h("div", { class: "field" }, h("label", { for: id }, label), input, hint ? h("p", { class: "hint" }, hint) : null);
}

const dateInput = (name = "date") => h("input", { class: "input", type: "date", name, value: fmt.today(), required: true });

function appliedForm(j) {
  return form("Mark as applied", [
    field("Date applied", dateInput()),
    field("Applied via", h("select", { class: "select", name: "applied_via" },
      ["employer_site", "linkedin", "email", "referral", "portal_only"].map((v) => h("option", { value: v }, v.replace("_", " "))))),
  ], "Mark applied", (fd) => post(`/api/jobs/${j.job_id}/status`, { status: "applied", date: fd.get("date"), applied_via: fd.get("applied_via") }),
  "Only after you have submitted it yourself. Jobissimo never submits for you.");
}

function simpleStatus(j, status, title, note) {
  return form(title, [field("Date", dateInput())], "Save", (fd) => post(`/api/jobs/${j.job_id}/status`, { status, date: fd.get("date") }), note);
}

function roundForm(j) {
  return form("Record a round", [
    field("Kind", h("select", { class: "select", name: "kind" },
      [["screen", "Screening"], ["hr", "HR / recruiter"], ["hm", "Hiring manager"], ["test", "Take-home / test"], ["tech", "Technical"], ["panel", "Panel"], ["final", "Final"]]
        .map(([v, l]) => h("option", { value: v }, l)))),
    field("Held on", dateInput(), "A test counts from the day you submitted it."),
    field("Label (optional)", h("input", { class: "input", name: "label", placeholder: "e.g. case study, CTO round" })),
  ], "Record round", (fd) => post(`/api/jobs/${j.job_id}/stage`, { kind: fd.get("kind"), date: fd.get("date"), label: fd.get("label") }),
  "Recording a new round marks the previous one as passed.");
}

function resolveForm(j) {
  const pending = j.stages.filter((g) => g.result === "pending");
  const last = pending[pending.length - 1];
  const offer = last.kind === "offer";
  return form(`Settle round ${last.seq} (${last.kind})`, [
    field("Result", h("select", { class: "select", name: "result" },
      (offer ? ["accepted", "declined", "withdrawn", "countered"] : ["passed", "failed", "withdrawn"]).map((v) => h("option", { value: v }, v)))),
    field("Decided on", dateInput()),
  ], "Save", (fd) => post(`/api/jobs/${j.job_id}/stage/resolve`, { seq: last.seq, result: fd.get("result"), date: fd.get("date") }));
}

function closeForm(j) {
  const outcomes = j.status === "offered"
    ? ["offer_accepted", "offer_declined", "offer_withdrawn", "withdrawn"]
    : ["rejected", "no_response", "withdrawn", "interview"];
  return form("Close this application", [
    field("Outcome", h("select", { class: "select", name: "outcome" }, outcomes.map((v) => h("option", { value: v }, OUTCOME[v] || v)))),
    field("Date", dateInput()),
  ], "Close", (fd) => post(`/api/jobs/${j.job_id}/status`, { status: "closed", outcome: fd.get("outcome"), date: fd.get("date") }),
  "A rejection also fails the round that was pending.");
}

// After a change: refresh the page underneath, then the open panel. On the
// Applications page the re-render reopens the panel from the URL itself.
async function afterChange() {
  refreshCounts();
  const onApps = location.hash.startsWith("#/applications");
  await rerender();
  if (!onApps && currentJob) {
    const j = await get(`/api/jobs/${encodeURIComponent(currentJob)}`);
    replacePanelBody(jobBody(j));
  }
}
