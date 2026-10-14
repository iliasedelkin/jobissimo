// Knowledge — what Jobissimo knows about you, where each claim comes from,
// how it is used, and what is missing. Every change goes through
// scripts/knowledge.py; agent proposals wait in the inbox for you.
import { h, get, post, fmt, toast } from "../lib.js";
import { icon } from "../icons.js";
import { pageHead, tabs, panel, closePanel, menu, commandChip, empty, notice, sectionHead, replacePanelBody } from "../components.js";
import { go, render as rerender, refreshCounts } from "../app.js";

const OP_LABEL = { add_bullet: "New achievement", add_fact: "Add a fact", add_phrasing: "New phrasing",
  deprecate: "Retire an achievement", mark_duplicate: "Mark as duplicate", restore: "Restore an achievement" };
const MIN_N = 8;

export async function render(route) {
  const tab = route.sub || "experience";
  const [k, gaps] = await Promise.all([get("/api/knowledge"), tab === "gaps" ? get("/api/gaps") : null]);
  const page = h("div", {}, pageHead("Knowledge", "What Jobissimo knows about you, where every claim comes from, and what is missing."));
  page.append(tabs([
    { id: "inbox", label: "Inbox", count: k.inbox.length || null },
    { id: "experience", label: "Experience", count: k.stats.bullets },
    { id: "skills", label: "Skills", count: k.skills.length },
    { id: "gaps", label: "Gaps" },
  ], tab, (id) => go("knowledge", {}, id), "Knowledge sections"));
  const body = { inbox: inboxTab, experience: experienceTab, skills: skillsTab, gaps: gapsTab }[tab] || experienceTab;
  page.append(body(k, gaps));
  if (route.params.bullet) {
    const b = findBullet(k, route.params.bullet);
    if (b) setTimeout(() => openBullet(k, b), 0);
  }
  return page;
}

function findBullet(k, id) {
  for (const r of k.roles) for (const b of r.bullets) if (b.id === id) return b;
  return null;
}

function bulletText(b) {
  return b.phrasings[0] || b.facts[0] || b.id;
}

// ---------------------------------------------------------------- experience

function experienceTab(k) {
  const st = k.stats;
  const wrap = h("div");
  if (!k.roles.length) {
    wrap.append(empty("No experience yet", "Run /setup with your CV and LinkedIn export; Jobissimo extracts every role and achievement with its source.", commandChip("/setup")));
    return wrap;
  }
  wrap.append(h("div", { class: "toolbar" },
    h("span", { class: "chip" }, `${st.bullets} achievements · ${st.roles} roles`),
    h("span", { class: "chip" }, `${st.with_metric} with a number`),
    h("span", { class: "chip" }, `${st.used} used in applications`),
    st.deprecated ? h("span", { class: "chip" }, `${st.deprecated} retired`) : null,
    st.contradictions ? h("span", { class: "chip tag-warn" }, `${st.contradictions} with a contradiction to resolve`) : null));
  wrap.append(h("div", { style: { marginBottom: "28px" } }, notice(
    "CVs may select and rephrase these achievements, never add to them. A requirement you have no evidence for goes to Gaps, not into a CV.", "", "shield")));
  for (const role of k.roles) {
    wrap.append(h("div", { class: "role-head" },
      h("div", {}, h("h3", {}, `${role.company || role.id}${role.title ? ` — ${role.title}` : ""}`),
        h("div", { class: "meta" }, [role.period, role.fields.Industry].filter(Boolean).join(" · "))),
      h("button", { type: "button", class: "btn btn-ghost btn-sm", onclick: () => openAddBullet(k, role) }, icon("plus"), "Add achievement")));
    wrap.append(role.bullets.length ? h("div", { class: "rows" }, role.bullets.map((b) => bulletRow(k, b)))
      : h("p", { class: "muted" }, "No achievements recorded for this role."));
  }
  return wrap;
}

function usageText(b) {
  const u = b.usage;
  if (!u.applications) return "Not used yet";
  return `Used in ${fmt.plural(u.applications, "application")}`;
}

function bulletRow(k, b) {
  const dep = b.meta.status === "deprecated";
  const r = b.usage.replies;
  // only when the 95% interval excludes your average — otherwise it is noise
  const base = k.baseline.rate;
  const lift = r.n >= MIN_N && base !== null && (r.low > base || r.high < base) ? r.rate - base : null;
  return h("button", { type: "button", class: `row ${dep ? "deprecated" : ""}`, onclick: () => openBullet(k, b) },
    h("div", { class: "grow" },
      h("div", { class: "row-title fact-text" }, bulletText(b)),
      h("div", { class: "row-sub" }, [b.id, b.tags.join(", ")].filter(Boolean).join(" · "))),
    dep ? h("span", { class: "status s-quiet" }, "Retired") : null,
    !dep && !b.has_metric ? h("span", { class: "chip", title: "No number in any fact" }, "no number") : null,
    lift !== null ? h("span", { class: `chip ${lift > 0 ? "tag-good" : ""}`, title: "Reply rate of applications citing it vs your average (correlation)" },
      `${lift > 0 ? "+" : "−"}${Math.round(Math.abs(lift) * 100)} pts replies`) : null,
    h("span", { class: "row-meta" }, usageText(b)));
}

function openBullet(k, b) {
  const dep = b.meta.status === "deprecated";
  const others = k.roles.flatMap((r) => r.bullets).filter((x) => x.id !== b.id && x.meta.status !== "deprecated");
  const slot = h("div");
  const show = (f) => { slot.replaceChildren(f); f.querySelector("input,textarea,select")?.focus(); };
  const actions = menu(dep ? [
    { label: "Restore — usable in CVs again", onSelect: () => show(confirmForm(b, "restore", "Restore this achievement?", "It becomes citable in new CVs again.", {})) },
  ] : [
    { heading: "Change" },
    { label: "Add a fact or number", onSelect: () => show(factForm(b)) },
    { label: "Add a phrasing", onSelect: () => show(phrasingForm(b)) },
    "-",
    { label: "Mark as duplicate of…", onSelect: () => show(duplicateForm(b, others)) },
    { label: "Retire (keep history, stop using)", danger: true, onSelect: () => show(retireForm(b)) },
  ], { label: "Change this achievement" });
  const u = b.usage;
  const r = u.replies;
  const body = h("div", {},
    dep ? h("div", { style: { marginBottom: "18px" } }, notice(`Retired ${b.meta.on || ""}${b.meta.reason ? ` — ${b.meta.reason}` : ""}. Past applications keep it; new CVs cannot cite it.`, "warn", "alert")) : null,
    h("div", { class: "panel-actions" },
      dep ? null : h("button", { type: "button", class: "btn btn-sm", onclick: () => show(factForm(b)) }, "Add a number"),
      dep ? null : h("button", { type: "button", class: "btn btn-sm", onclick: () => show(phrasingForm(b)) }, "Add a phrasing"),
      actions),
    slot,
    h("h3", {}, "Facts"), h("ul", { class: "list-plain" }, b.facts.map((f) => h("li", { class: "fact-text" }, f))),
    b.phrasings.length ? [h("h3", {}, "Approved phrasings"), h("ul", { class: "list-plain" }, b.phrasings.map((p) => h("li", { class: "fact-text" }, `“${p}”`)))] : null,
    h("h3", {}, "Where it comes from"),
    b.provenance.length ? h("ul", { class: "list-plain" }, b.provenance.map((p) => h("li", {}, provenanceLabel(p))))
      : h("p", { class: "subtle" }, "No source document is recorded — this achievement predates source tracking."),
    b.meta.by ? h("p", { class: "muted" }, `Verified by you on ${b.meta.on}${b.meta.inbox ? ` (${b.meta.inbox})` : ""}.`)
      : h("p", { class: "muted" }, "Counts as verified: you confirmed it when your profile was set up."),
    h("h3", {}, "How it is used"),
    h("dl", { class: "props" },
      h("dt", {}, "Applications"), h("dd", {}, fmt.num(u.applications)),
      h("dt", {}, "Sent"), h("dd", {}, fmt.num(u.sent)),
      h("dt", {}, "Last used"), h("dd", {}, u.last_used ? fmt.date(u.last_used) : "–"),
      h("dt", {}, "Replies"), h("dd", {}, r.n ? `${r.k} of ${r.n} (${fmt.pct(r.rate)})` : "–"),
      h("dt", {}, "Your average"), h("dd", {}, k.baseline.n ? `${fmt.pct(k.baseline.rate)} of ${k.baseline.n}` : "–")),
    r.n >= MIN_N ? h("p", { class: "muted" }, "This is a correlation: it depends on which jobs the achievement was used for, not only on the achievement.")
      : h("p", { class: "muted" }, `Reply comparisons appear after ${MIN_N} sent applications cite it.`));
  panel({ title: b.id, subtitle: bulletText(b), body, label: `Achievement ${b.id}` });
}

function provenanceLabel(p) {
  if (/^user#/i.test(p)) return `Added by you (${p.slice(5)})`;
  const [src, loc] = p.split("#");
  return h("span", {}, h("span", { class: "mono" }, src), loc ? h("span", { class: "muted" }, ` · ${loc}`) : null);
}

// ---------------------------------------------------------------- forms

function kform(title, note, fields, submit, onSubmit) {
  const err = h("p", { class: "tag-bad", role: "alert" });
  const f = h("form", { class: "card card-pad", style: { margin: "0 0 20px" } },
    h("h3", { style: { marginTop: 0 } }, title), note ? h("p", { class: "subtle", style: { marginTop: 0 } }, note) : null,
    fields, err,
    h("div", { style: { display: "flex", gap: "8px" } },
      h("button", { type: "submit", class: "btn btn-primary btn-sm" }, submit),
      h("button", { type: "button", class: "btn btn-ghost btn-sm", onclick: () => f.remove() }, "Cancel")));
  f.addEventListener("submit", async (e) => {
    e.preventDefault();
    const btn = f.querySelector("[type=submit]");
    btn.disabled = true;
    err.textContent = "";
    try {
      const res = await onSubmit(new FormData(f));
      toast(res.message);
      closePanel();
      refreshCounts();
      await rerender();
    } catch (ex) {
      err.textContent = ex.message;
      btn.disabled = false;
    }
  });
  return f;
}

function fld(label, input, hint) {
  const id = `k-${Math.random().toString(36).slice(2, 8)}`;
  input.id = id;
  return h("div", { class: "field" }, h("label", { for: id }, label), input, hint ? h("p", { class: "hint" }, hint) : null);
}

const change = (op, target, payload, note) => post("/api/knowledge/propose", { op, target, payload, note, accept: true });

function factForm(b) {
  return kform("Add a fact or number", "Only what you could defend in an interview. Keep it to this achievement — never combine numbers from different ones.",
    [fld("Fact", h("input", { class: "input", name: "fact", required: true, placeholder: "Outcome: triage time down from 5 days to 2" }),
      "Start with Outcome:, Scope: or Mechanism: when it fits.")],
    "Add fact", (fd) => change("add_fact", b.id, { fact: fd.get("fact") }));
}

function phrasingForm(b) {
  return kform("Add a phrasing", "A wording CVs may use. It must say nothing the facts do not.",
    [fld("Phrasing", h("textarea", { class: "textarea", name: "phrasing", required: true }))],
    "Add phrasing", (fd) => change("add_phrasing", b.id, { phrasing: fd.get("phrasing") }));
}

function retireForm(b) {
  return kform("Retire this achievement", "It stays linked to the applications that used it, and new CVs stop citing it.",
    [fld("Why", h("input", { class: "input", name: "reason", required: true, placeholder: "e.g. outdated, superseded, can't verify" }))],
    "Retire", (fd) => change("deprecate", b.id, { reason: fd.get("reason") }, fd.get("reason")));
}

function duplicateForm(b, others) {
  return kform("Mark as duplicate", "Keeps the other achievement and retires this one. Texts and numbers are never merged.",
    [fld("Duplicate of", h("select", { class: "select", name: "of", required: true },
      others.map((o) => h("option", { value: o.id }, `${o.id} — ${bulletText(o).slice(0, 80)}`))))],
    "Mark duplicate", (fd) => change("mark_duplicate", b.id, { of: fd.get("of") }));
}

function confirmForm(b, op, title, note, payload) {
  return kform(title, note, [], "Confirm", () => change(op, b.id, payload));
}

function openAddBullet(k, role) {
  const body = h("div", {},
    notice("Write facts the way you would say them to an interviewer: what you did, the outcome with its number, and how. Each line is one fact.", "", "info"),
    h("div", { style: { height: "18px" } }),
    kform("New achievement", null, [
      fld("Facts (one per line)", h("textarea", { class: "textarea", name: "facts", required: true, rows: "5",
        placeholder: "Led the migration to usage-based billing\nOutcome: churn down 3 points in two quarters\nMechanism: cohort analysis + pricing experiments" })),
      fld("A phrasing CVs may use (optional)", h("textarea", { class: "textarea", name: "phrasing" })),
      fld("Tags (comma-separated)", h("input", { class: "input", name: "tags", placeholder: "PRODUCT, ANALYTICS" })),
    ], "Add achievement", (fd) => change("add_bullet", role.id, {
      role_id: role.id,
      facts: String(fd.get("facts")).split("\n").map((x) => x.trim()).filter(Boolean),
      phrasings: fd.get("phrasing") ? [String(fd.get("phrasing"))] : [],
      tags: String(fd.get("tags") || "").split(",").map((x) => x.trim().toUpperCase()).filter(Boolean),
    })));
  panel({ title: "Add achievement", subtitle: `${role.company} — ${role.title}`, body });
}

// ---------------------------------------------------------------- inbox

function inboxTab(k) {
  const wrap = h("div");
  if (!k.inbox.length) {
    wrap.append(empty("Nothing to review",
      "When /enrich or /optimise proposes a change to your knowledge, it waits here. Nothing changes until you accept it."));
  } else {
    wrap.append(h("p", { class: "subtle", style: { marginTop: 0 } },
      "Proposals from your agent runs. Accepting writes the change into your knowledge, marked as verified by you."));
    wrap.append(h("div", { class: "rows" }, k.inbox.map((item) => inboxItem(k, item))));
  }
  if (k.decided.length) {
    wrap.append(h("div", { class: "section" }, sectionHead("Recently decided"),
      h("div", { class: "rows" }, [...k.decided].reverse().map((i) => h("div", { class: "row" },
        h("div", { class: "grow" }, h("div", { class: "row-title" }, `${OP_LABEL[i.op] || i.op}${i.target_id ? ` · ${i.target_id}` : ""}`),
          h("div", { class: "row-sub" }, i.reason || (i.result_id ? `→ ${i.result_id}` : ""))),
        h("span", { class: `status ${i.status === "accepted" ? "s-good" : "s-quiet"}` }, i.status),
        h("span", { class: "row-meta" }, fmt.relative(i.decided_at)))))));
  }
  return wrap;
}

function payloadView(k, item) {
  const p = item.payload || {};
  const target = item.target_id ? findBullet(k, item.target_id) : null;
  const parts = [];
  if (target) parts.push(h("div", { class: "quote" }, bulletText(target)));
  if (item.op === "add_fact") parts.push(h("div", { class: "diff-add" }, `+ ${p.fact}`));
  if (item.op === "add_phrasing") parts.push(h("div", { class: "diff-add" }, `+ “${p.phrasing}”`));
  if (item.op === "add_bullet") parts.push(h("div", { class: "diff-add" }, (p.facts || []).map((f) => h("div", {}, `+ ${f}`))));
  if (item.op === "deprecate") parts.push(h("div", { class: "diff-del" }, `Retire: ${p.reason || item.note || ""}`));
  if (item.op === "mark_duplicate") parts.push(h("div", { class: "diff-del" }, `Duplicate of ${p.of}`));
  return parts;
}

function inboxItem(k, item) {
  const slot = h("div");
  const by = item.proposed_by === "user" ? "you" : item.proposed_by;
  const decide = async (decision, extra = {}) => {
    try {
      const res = await post(`/api/inbox/${item.id}/decision`, { decision, ...extra });
      toast(res.message);
      refreshCounts();
      await rerender();
    } catch (e) { toast(e.message, "error"); }
  };
  const rejectForm = () => {
    const input = h("input", { class: "input", name: "reason", required: true, placeholder: "Why — so it is not proposed again" });
    const f = h("form", { class: "toolbar", style: { marginTop: "12px" } }, input,
      h("button", { type: "submit", class: "btn btn-sm" }, "Reject"),
      h("button", { type: "button", class: "btn btn-ghost btn-sm", onclick: () => f.remove() }, "Cancel"));
    f.addEventListener("submit", (e) => { e.preventDefault(); decide("reject", { reason: input.value }); });
    slot.replaceChildren(f); input.focus();
  };
  const editForm = () => {
    const p = item.payload || {};
    const key = item.op === "add_fact" ? "fact" : item.op === "add_phrasing" ? "phrasing" : null;
    if (!key && item.op !== "add_bullet") return;
    const ta = h("textarea", { class: "textarea", "aria-label": "Edit before accepting" },
      key ? p[key] : (p.facts || []).join("\n"));
    const f = h("form", { style: { marginTop: "12px" } }, ta, h("div", { class: "toolbar", style: { marginTop: "8px" } },
      h("button", { type: "submit", class: "btn btn-primary btn-sm" }, "Accept edited"),
      h("button", { type: "button", class: "btn btn-ghost btn-sm", onclick: () => f.remove() }, "Cancel")));
    f.addEventListener("submit", (e) => {
      e.preventDefault();
      const payload = key ? { ...p, [key]: ta.value } : { ...p, facts: ta.value.split("\n").map((x) => x.trim()).filter(Boolean) };
      decide("accept", { payload });
    });
    slot.replaceChildren(f); ta.focus();
  };
  const editable = ["add_fact", "add_phrasing", "add_bullet"].includes(item.op);
  return h("div", { class: "row", style: { alignItems: "flex-start", flexDirection: "column", gap: "4px" } },
    h("div", { style: { display: "flex", width: "100%", gap: "12px", alignItems: "baseline" } },
      h("div", { class: "row-title grow" }, `${OP_LABEL[item.op] || item.op}${item.target_id ? ` · ${item.target_id}` : ""}`),
      h("span", { class: "row-meta" }, `from ${by} · ${fmt.relative(item.proposed_at)}`)),
    item.note ? h("p", { class: "subtle", style: { margin: "2px 0" } }, item.note) : null,
    h("div", { style: { width: "100%" } }, payloadView(k, item)),
    h("div", { class: "toolbar", style: { margin: "10px 0 0" } },
      h("button", { type: "button", class: "btn btn-primary btn-sm", onclick: () => decide("accept") }, icon("check"), "Accept"),
      editable ? h("button", { type: "button", class: "btn btn-sm", onclick: editForm }, "Edit, then accept") : null,
      h("button", { type: "button", class: "btn btn-ghost btn-sm", onclick: rejectForm }, "Reject")),
    h("div", { style: { width: "100%" } }, slot));
}

// ---------------------------------------------------------------- skills

function skillsTab(k) {
  const wrap = h("div");
  if (!k.skills.length) {
    wrap.append(empty("No skills inventory", "/setup builds it from your documents; every skill needs evidence from an achievement."));
    return wrap;
  }
  const rows = [...k.skills].sort((a, b) => (b.recency || 0) - (a.recency || 0) || a.name.localeCompare(b.name));
  wrap.append(h("div", { class: "table-wrap" }, h("table", {},
    h("caption", { class: "sr-only" }, "Skills"),
    h("thead", {}, h("tr", {}, ["Skill", "Level", "Last used", "Evidence"].map((x) => h("th", { scope: "col" }, x)))),
    h("tbody", {}, rows.map((s) => h("tr", {},
      h("td", { class: "cell-title" }, s.name),
      h("td", {}, s.proficiency || "–"),
      h("td", {}, s.recency || "–"),
      h("td", {}, s.evidence.length ? s.evidence.map((e, i) => [i ? ", " : "",
        /^[A-Z0-9]+(-[A-Z0-9]+)+$/.test(e) ? h("a", { href: `#/knowledge/experience?bullet=${encodeURIComponent(e)}`, class: "mono" }, e) : e])
        : h("span", { class: "tag-warn" }, "none"))))))));
  wrap.append(h("div", { class: "section" }, sectionHead("Claimed but not evidenced",
    k.unevidenced.length ? "Never used in a CV until you add evidence" : null),
  k.unevidenced.length ? h("div", { class: "rows" }, k.unevidenced.map((u) => h("div", { class: "row" },
    h("div", { class: "grow" }, h("div", { class: "row-title" }, u.name), h("div", { class: "row-sub" }, u.note)),
    commandChip("/enrich"))))
    : h("p", { class: "muted" }, "Every claimed skill has evidence.")));
  return wrap;
}

// ---------------------------------------------------------------- gaps

function gapsTab(k, gaps) {
  const wrap = h("div");
  wrap.append(h("p", { class: "subtle", style: { marginTop: 0, maxWidth: "720px" } },
    `Requirements jobs asked for that your knowledge has no evidence for, across ${fmt.plural(gaps.evidence_maps, "prepared application")}. `
    + "A gap is either evidence you have not written down yet — add it — or a real gap: skip those jobs, or build it."));
  const split = h("div", { class: "split" });
  const top = gaps.items.slice(0, 40);
  split.append(h("div", {}, sectionHead("Most requested", top.length ? `${gaps.items.length} terms` : null),
    top.length ? h("div", { class: "rows" }, top.map((t) => {
      const details = h("details", {}, h("summary", { class: "muted" }, `Asked by ${fmt.plural(t.count, "job")}${t.must ? ` · ${t.must} as must-have` : ""}`),
        h("p", { class: "subtle", style: { margin: "6px 0 0" } }, [...new Map(t.jobs.map((j) => [j.job_id, j])).values()].map((j, i) =>
          [i ? ", " : "", h("a", { href: `#/applications?job=${encodeURIComponent(j.job_id)}&group=archive` }, j.company)])));
      return h("div", { class: "row" },
        h("div", { class: "grow" }, h("div", { class: "row-title" }, t.term), details),
        h("span", { class: "row-meta" }, t.last_seen ? `last ${fmt.date(t.last_seen)}` : ""));
    })) : notice("No gaps recorded yet. They come from the evidence maps /prepare writes.")));
  split.append(h("div", {}, sectionHead("Questions that would close gaps"),
    k.queue.length ? h("div", { class: "rows" }, k.queue.slice(0, 8).map((q) => h("div", { class: "row", style: { alignItems: "flex-start" } },
      h("div", { class: "grow" }, h("div", { class: "fact-text" }, q.prompt),
        h("div", { class: "row-sub" }, `impact ${q.impact}/5 · about ${q.est_minutes} min`))))) : notice("No open questions."),
    k.queue.length ? h("div", { style: { marginTop: "14px" } }, h("span", { class: "subtle" }, "Answer them in five minutes: "), commandChip("/enrich")) : null));
  wrap.append(split);
  return wrap;
}
