// Overview — what Jobissimo is doing, and what needs you.
import { h, get, fmt, statusEl } from "../lib.js";
import { icon } from "../icons.js";
import { pageHead, sectionHead, commandChip, empty, notice } from "../components.js";
import { go } from "../app.js";
import { openJob } from "./applications.js";
import { canRun, startRun, runButton } from "../agent.js";

const ACT_ICON = { offer: "offer", follow_up: "send", ready: "send", shortlisted: "applications",
  inbox: "inbox", suggestions: "spark" };

export async function render() {
  const o = await get("/api/overview");
  const today = new Date(`${o.today}T00:00:00`).toLocaleDateString(undefined, { weekday: "long", day: "numeric", month: "long" });
  const page = h("div", {}, pageHead("Overview", `${today} · ${fmt.plural(o.totals.jobs, "job")} tracked`));

  if (!o.has_data) {
    page.append(empty("Nothing tracked yet",
      "Run /setup to build your profile from your own documents, then /hunt to find your first postings.",
      commandChip("/setup")));
    return page;
  }

  page.append(statusLine(o));

  // what needs you
  page.append(h("div", { class: "section" }, sectionHead("Needs you", o.act_now.length ? null : "Nothing waiting on you"),
    trackBox(),
    o.act_now.length ? h("div", { class: "rows" }, o.act_now.map(actRow)) :
      notice("You are up to date. The next /cycle will reconcile mail, hunt, and prepare the freshest postings.")));

  // three numbers, not a wall of cards
  const r8 = o.rates.response_8w;
  const ps = o.rates.past_screen;
  const kpis = h("div", { class: "kpis" },
    kpi("Sent this week", fmt.num(o.momentum.this_week), `${o.momentum.last_week} last week · ${o.momentum.this_month} this month`),
    kpi("Reply rate, last 8 weeks", fmt.pct(r8.rate), r8.n ? `${r8.k} of ${fmt.plural(r8.n, "application")}` : "No applications in 8 weeks"),
    kpi("Past the CV screen", fmt.pct(ps.rate), `${ps.k} of ${fmt.plural(ps.n, "application")}, all time`));
  page.append(h("div", { class: "section" }, sectionHead("This week", h("a", { href: "#/analytics", class: "meta" }, "Analytics →")), kpis));

  // in process + insights
  const left = h("div", {}, sectionHead("In process", o.in_process.length ? `${o.in_process.length} active` : null),
    o.in_process.length ? h("div", { class: "rows" }, o.in_process.map(processRow))
      : notice("No live interview processes. Replies you record with /track appear here."));
  const right = h("div", {}, sectionHead("Worth acting on"), insightsBox());
  page.append(h("div", { class: "section split" }, left, right));

  if (o.recent.length) {
    page.append(h("div", { class: "section" }, sectionHead("Recent outcomes"),
      h("div", { class: "rows" }, o.recent.map((e) => h("button", { type: "button", class: "row", onclick: () => openJob(e.job_id) },
        h("div", { class: "grow" }, h("div", { class: "row-title" }, e.company), h("div", { class: "row-sub" }, e.title)),
        statusEl(e.to, e.outcome),
        h("span", { class: "row-meta" }, fmt.relative(e.ts)))))));
  }
  return page;
}

function statusLine(o) {
  const bits = [];
  const last = o.runs.latest[0];
  if (last) bits.push(`Last run: /${last.command}, ${fmt.relative(last.start || last.end)}`);
  const errs = o.health.errors.length, warns = o.health.warnings.length;
  bits.push(errs ? `${fmt.plural(errs, "config error")}` : warns ? `${fmt.plural(warns, "config warning")}` : "Config healthy");
  const line = h("div", { class: "toolbar" }, bits.map((b) => h("span", { class: "chip" }, b)));
  if (o.runs.orphans) {
    line.append(h("a", { class: "chip", href: "#/pipeline", title: "Runs that started but never logged an end" },
      icon("alert"), `${o.runs.orphans} runs without an end`));
  }
  return line;
}

/** "Fever rejected me today" → /track, in the user's own agent. */
function trackBox() {
  if (!canRun("track")) return null;
  const input = h("input", { class: "input", name: "update", maxlength: "600", autocomplete: "off",
    placeholder: "Record an update — e.g. “Acme invited me to a second interview on Friday”", "aria-label": "Record an update" });
  const f = h("form", { class: "track-box", style: { marginBottom: "14px" } }, input,
    h("button", { type: "submit", class: "btn" }, "Record"));
  f.addEventListener("submit", (e) => {
    e.preventDefault();
    if (!input.value.trim()) return;
    startRun("track", input.value.trim());
    input.value = "";
  });
  return f;
}

function actRow(a) {
  const apply = a.kind === "ready" && a.job_ids && a.job_ids.length
    ? runButton("apply", a.job_ids.join(" "), { label: a.job_ids.length > 1 ? `Apply to ${a.job_ids.length}` : "Apply" }) : null;
  const right = apply ? h("div", { class: "toolbar", style: { margin: 0, flexWrap: "nowrap" }, onclick: (e) => e.stopPropagation() }, apply)
    : a.command
    ? h("div", { class: "toolbar", style: { margin: 0, flexWrap: "nowrap" } }, commandChip(a.command))
    : h("span", { class: "row-meta" }, "Open →");
  const open = () => {
    if (a.job_id) return openJob(a.job_id);
    if (a.view) {
      const [id, q] = a.view.split("?");
      go(id, Object.fromEntries(new URLSearchParams(q || "")));
    }
  };
  return h("button", { type: "button", class: "row", onclick: open },
    h("span", { class: `row-icon ${a.kind === "offer" || a.kind === "ready" ? "accent" : ""}` }, icon(ACT_ICON[a.kind] || "info")),
    h("div", { class: "grow" }, h("div", { class: "row-title" }, a.title), a.detail ? h("div", { class: "row-sub" }, a.detail) : null),
    right);
}

function kpi(label, value, foot) {
  return h("div", { class: "kpi" }, h("div", { class: "label" }, label), h("div", { class: "value" }, value), h("div", { class: "foot" }, foot));
}

function processRow(j) {
  const last = j.stages[j.stages.length - 1];
  const when = last && last.result === "pending" ? `pending since ${fmt.date(last.date)}` : last ? `${last.result} · ${fmt.date(last.date)}` : "";
  const sub = last ? `${last.kind}${last.label ? ` · ${last.label}` : ""} · ${when}` : (j.next || "");
  return h("button", { type: "button", class: "row", onclick: () => openJob(j.job_id) },
    h("div", { class: "grow" }, h("div", { class: "row-title" }, `${j.company} — ${j.title}`), h("div", { class: "row-sub" }, sub)),
    statusEl(j.status, j.outcome));
}

function insightsBox() {
  const box = h("div", { class: "card" }, h("p", { class: "loading", style: { padding: "18px 20px", margin: 0 } }, "Reading the numbers…"));
  get("/api/insights").then((items) => {
    if (!items.length) {
      box.replaceChildren(h("div", { class: "insight" }, h("div", {},
        h("h4", {}, "Nothing stands out yet"),
        h("p", {}, "Insights appear once groups are large enough to compare honestly (8+ applications)."))));
      return;
    }
    box.replaceChildren(...items.slice(0, 3).map(insightEl));
  }).catch(() => box.replaceChildren(h("p", { class: "muted", style: { padding: "18px 20px" } }, "Insights unavailable.")));
  return h("div", {}, box,
    h("div", { style: { marginTop: "16px" } }, notice("Anonymous benchmarks are off. Nothing leaves this machine.", "", "lock")));
}

export function insightEl(i) {
  const lever = i.lever || {};
  return h("div", { class: "insight" },
    h("span", { class: `sev ${i.severity}`, "aria-label": `${i.severity} priority` }),
    h("div", {},
      h("h4", {}, i.title),
      h("p", {}, i.detail),
      h("div", { class: "lever" }, "Lever:",
        lever.command ? commandChip(lever.command)
          : lever.setting ? h("a", { href: "#/pipeline", class: "chip" }, lever.label)
            : lever.view ? h("a", { href: `#/${lever.view}`, class: "chip" }, lever.label)
              : h("span", {}, lever.label))));
}
