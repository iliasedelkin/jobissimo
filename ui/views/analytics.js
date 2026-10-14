// Analytics — the funnel as a story, over time, and by what you send.
import { h, get, fmt } from "../lib.js";
import { icon } from "../icons.js";
import { pageHead, sectionHead, tabs, notice, empty, commandChip } from "../components.js";
import { funnel, weeklyBars, rateList, countList } from "../charts.js";
import { go } from "../app.js";
import { insightEl } from "./overview.js";

const RANGES = [["", "All time"], ["180", "Last 6 months"], ["90", "Last 90 days"], ["30", "Last 30 days"]];
const DIMS = [
  ["source", "Source"], ["fit_bucket", "Fit score"], ["ats_band", "ATS score"],
  ["positioning", "Positioning"], ["language", "Language"], ["seniority_level", "Seniority"],
];
let dim = "source";
let step = "applied";

function sinceDate(days) {
  if (!days) return "";
  const d = new Date(Date.now() - Number(days) * 86400000);
  return d.toISOString().slice(0, 10);
}

export async function render(route) {
  const range = route.params.range || "";
  const since = sinceDate(range);
  const a = await get(`/api/analytics${since ? `?since=${since}` : ""}`);
  const select = h("select", { class: "select", "aria-label": "Time range", style: { width: "auto" },
    onchange: (e) => go("analytics", { range: e.target.value }) },
  RANGES.map(([v, l]) => h("option", { value: v, selected: v === range }, l)));
  const page = h("div", {}, pageHead("Analytics", "How your search converts — over time, and by what you send.", select));

  if (!a.steps[0].n) {
    page.append(empty("No data in this range", "Postings appear here once /hunt has recorded them.", commandChip("/hunt")));
    return page;
  }

  if (a.insights && a.insights.length) {
    page.append(h("div", { class: "section", style: { marginTop: 0 } }, sectionHead("Worth acting on"),
      h("div", { class: "card" }, a.insights.map(insightEl))));
  }

  // funnel + the sentence that explains the selected step
  const story = h("p", { class: "subtle", style: { margin: "14px 2px 0", maxWidth: "820px" }, "aria-live": "polite" });
  const funnelBox = h("div");
  const drawFunnel = () => {
    funnelBox.replaceChildren(funnel(a.steps, { selected: step, onSelect: (k) => { step = k; drawFunnel(); } }));
    story.textContent = stepStory(a, step);
  };
  drawFunnel();
  page.append(h("div", { class: "section", style: a.insights && a.insights.length ? null : { marginTop: 0 } },
    sectionHead("Funnel", range ? `postings found in the ${RANGES.find((r) => r[0] === range)[1].toLowerCase()}` : "all postings"),
    funnelBox, story));

  page.append(h("div", { class: "section" }, sectionHead("Over time", "applications per week, by the week sent"), weeklyBars(a.weekly)));

  // what gets replies
  const listBox = h("div");
  const drawDim = () => {
    listBox.replaceChildren(
      tabs(DIMS.map(([id, l]) => ({ id, label: l })), dim, (id) => { dim = id; drawDim(); }, "Group replies by"),
      rateList(a.breakdowns[dim] || []));
  };
  drawDim();
  page.append(h("div", { class: "section" }, sectionHead("What gets replies",
    "faint line: 95% interval · muted: fewer than 8 applications"), listBox));

  // time to reply + rounds
  const rounds = a.rounds.length ? h("div", { class: "table-wrap" }, h("table", {},
    h("caption", { class: "sr-only" }, "Interview rounds"),
    h("thead", {}, h("tr", {}, ["Round", "Reached", "Passed", "Failed", "Pending"].map((x, i) => h("th", { scope: "col", class: i ? "num" : "" }, x)))),
    h("tbody", {}, a.rounds.map((r) => h("tr", {}, h("td", { class: "cell-title" }, r.kind),
      h("td", { class: "num" }, r.reached), h("td", { class: "num" }, r.passed),
      h("td", { class: "num" }, r.failed), h("td", { class: "num" }, r.pending))))))
    : notice("Rounds appear once you record them (Applications → a job → Record a round).");
  page.append(h("div", { class: "section grid-2" },
    h("div", {}, sectionHead("Time to first reply", a.median_days_to_response !== null ? `median ${a.median_days_to_response} days` : null), countList(a.time_to_response)),
    h("div", {}, sectionHead("Interview rounds"), rounds)));

  page.append(h("div", { class: "section" }, sectionHead("Compared with others"),
    h("div", { class: "notice" }, icon("lock"), h("div", {},
      h("div", { style: { color: "var(--text)", fontWeight: "560", marginBottom: "2px" } }, "Anonymous benchmarks are off"),
      "Percentiles against other Jobissimo users need an opt-in that shares only coarse counts — never your CV, the jobs, or the companies. Until then, nothing leaves this machine."))));
  return page;
}

function stepStory(a, key) {
  const s = Object.fromEntries(a.steps.map((x) => [x.key, x.n]));
  const pct = (x, y) => (y ? fmt.pct(x / y) : "–");
  switch (key) {
    case "found": return `${fmt.num(s.found)} postings found; ${fmt.num(a.scored)} were scored against your targets.`;
    case "recommended": return `${fmt.num(s.recommended)} of ${fmt.num(s.found)} found postings (${pct(s.recommended, s.found)}) were worth applying to. A low share points at sourcing: boards or queries, not your CV.`;
    case "prepared": {
      const lost = a.lost_before_sending;
      return `${fmt.num(s.prepared)} applications prepared from ${fmt.num(s.recommended)} shortlisted.` +
        (lost.n ? ` In the last 90 days, ${lost.k} of ${lost.n} recommended postings closed before they were sent (${fmt.pct(lost.rate)}).` : "");
    }
    case "applied": return `${fmt.num(s.applied)} sent of ${fmt.num(s.prepared)} prepared (${pct(s.applied, s.prepared)}). Prepared work that is never sent is the most common leak.`;
    case "responded": return `${fmt.num(s.responded)} of ${fmt.num(s.applied)} applications got a reply (${pct(s.responded, s.applied)}) — any reply, including rejections.`;
    case "past_screen": return `${fmt.num(s.past_screen)} of ${fmt.num(s.responded)} replies (${pct(s.past_screen, s.responded)}) led to a conversation. When most replies are rejections, the CV and targeting are the lever, not volume.`;
    case "interview": return `${fmt.num(s.interview)} reached an interview round.`;
    case "offer": return `${fmt.num(s.offer)} offer${s.offer === 1 ? "" : "s"} from ${fmt.num(s.applied)} applications (${pct(s.offer, s.applied)}).`;
    default: return "";
  }
}
