// Charts as inline SVG. Each chart carries a text alternative for screen readers.
import { h, s, fmt } from "./lib.js";

const MIN_N = 8;

/** Dub-style funnel: numbers across the top, one band narrowing below.
 *  Band heights use a square-root scale so late stages stay visible; the
 *  numbers above are exact. */
export function funnel(steps, { selected, onSelect } = {}) {
  const n = steps.length;
  const first = Math.max(1, steps[0]?.n || 1);
  const H = 200, colW = 100, pad = 14, minH = 3;
  const heights = steps.map((st) => (st.n > 0 ? Math.max(minH, (H - 2 * pad) * Math.sqrt(st.n / first)) : 0));
  const wrap = h("div", { class: "funnel" });
  wrap.style.setProperty("--steps", n);
  wrap.style.setProperty("--steps-sm", Math.min(n, 4));

  const head = h("div", { class: "funnel-head" });
  steps.forEach((st, i) => {
    const prev = i > 0 ? steps[i - 1].n : null;
    const conv = prev ? st.n / prev : null;
    head.append(h("button", {
      type: "button", class: "funnel-step", "aria-pressed": String(selected === st.key),
      onclick: onSelect ? () => onSelect(st.key) : null,
    },
    h("div", { class: "label" }, h("span", { class: "dot", "aria-hidden": "true" }), st.label),
    h("div", { class: "value" }, fmt.num(st.n)),
    h("div", { class: "conv" }, i === 0 ? " " : `${fmt.pct(conv)} of ${steps[i - 1].label.toLowerCase()}`)));
  });
  wrap.append(head);

  const W = n * colW;
  const svg = s("svg", { viewBox: `0 0 ${W} ${H}`, preserveAspectRatio: "none", "aria-hidden": "true" });
  const selIdx = steps.findIndex((x) => x.key === selected);
  if (selIdx >= 0) svg.append(s("rect", { class: "col-hi", x: selIdx * colW, y: 0, width: colW, height: H }));
  for (let i = 1; i < n; i++) svg.append(s("line", { class: "col-line", x1: i * colW, x2: i * colW, y1: 0, y2: H, "vector-effect": "non-scaling-stroke" }));
  const mid = H / 2;
  // The band is symmetric about the middle: trace the top edge left to
  // right, then the same curve mirrored, right to left.
  const path = (extra) => {
    const hs = heights.map((x) => (x ? x + extra : 0));
    const seg = steps.map((_, i) => {
      const x0 = i * colW, flat = x0 + colW * 0.42, x1 = (i + 1) * colW;
      return { x0, flat, x1, a: hs[i] / 2, b: (i + 1 < n ? hs[i + 1] : hs[i]) / 2 };
    });
    const c = colW * 0.3;
    let d = `M 0 ${mid - seg[0].a} `;
    for (const g of seg) d += `L ${g.flat} ${mid - g.a} C ${g.flat + c} ${mid - g.a}, ${g.x1 - c} ${mid - g.b}, ${g.x1} ${mid - g.b} `;
    d += `L ${W} ${mid + seg[n - 1].b} `;
    for (const g of [...seg].reverse()) d += `C ${g.x1 - c} ${mid + g.b}, ${g.flat + c} ${mid + g.a}, ${g.flat} ${mid + g.a} L ${g.x0} ${mid + g.a} `;
    return `${d}Z`;
  };
  svg.append(s("path", { class: "band-soft", d: path(14) }));
  svg.append(s("path", { class: "band", d: path(0) }));
  wrap.append(h("div", { class: "funnel-chart" }, svg));
  wrap.append(srTable(["Stage", "Count", "Of previous"], steps.map((st, i) =>
    [st.label, st.n, i ? fmt.pct(steps[i - 1].n ? st.n / steps[i - 1].n : null) : "–"]), "Funnel"));
  return wrap;
}

/** Applications per week, with the ones that got a reply in the accent. */
export function weeklyBars(weekly, { label = "Applications per week" } = {}) {
  const W = 1000, H = 190, padL = 30, padB = 26, padT = 10;
  const max = Math.max(4, ...weekly.map((w) => w.applied));
  const step = (W - padL) / weekly.length;
  const bw = Math.max(4, step * 0.62);
  const y = (v) => padT + (H - padT - padB) * (1 - v / max);
  const svg = s("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": label });
  for (const t of [0, Math.round(max / 2), max]) {
    svg.append(s("line", { class: "grid", x1: padL, x2: W, y1: y(t), y2: y(t) }));
    svg.append(s("text", { class: "axis", x: 0, y: y(t) + 4 }, String(t)));
  }
  weekly.forEach((w, i) => {
    const x = padL + i * step + (step - bw) / 2;
    if (w.applied) svg.append(s("rect", { class: "b-all", x, width: bw, y: y(w.applied), height: y(0) - y(w.applied), rx: 2 },
      s("title", {}, `Week of ${fmt.date(w.week)}: ${w.applied} applied, ${w.responded} replied`)));
    if (w.responded) svg.append(s("rect", { class: "b-reply", x, width: bw, y: y(w.responded), height: y(0) - y(w.responded), rx: 2 }));
    if (i % 4 === 0) svg.append(s("text", { class: "axis", x: x + bw / 2, y: H - 6, "text-anchor": "middle" }, fmt.date(w.week)));
  });
  return h("div", { class: "chart" },
    h("div", { class: "legend" }, h("span", {}, h("i", { class: "l-all" }), "Applied"), h("span", {}, h("i", { class: "l-reply" }), "Got a reply")),
    svg,
    srTable(["Week", "Applied", "Replied"], weekly.filter((w) => w.applied).map((w) => [w.week, w.applied, w.responded]), label));
}

/** Ranked list of reply rates with a faint 95% interval; small groups muted. */
export function rateList(rows, { pool = 3, valueLabel = "reply rate" } = {}) {
  const list = h("div", { class: "barlist", role: "list" });
  // groups of one or two say nothing on their own: pool them into "Other"
  const shown = rows.filter((r) => r.n >= pool || rows.length <= 3);
  const rest = rows.filter((r) => !shown.includes(r));
  if (rest.length) {
    const k = rest.reduce((a, r) => a + r.k, 0), n = rest.reduce((a, r) => a + r.n, 0);
    shown.push({ key: `Other (${rest.length} groups)`, k, n, rate: n ? k / n : null, low: null, high: null });
  }
  for (const r of shown) {
    const small = r.n < MIN_N;
    const track = h("div", { class: "bar-track" });
    const fill = h("div", { class: "bar-fill" });
    fill.style.width = `${Math.max(1.5, (r.rate || 0) * 100)}%`;
    track.append(fill);
    if (!small && r.low !== null && r.low !== undefined) {
      const ci = h("div", { class: "bar-ci", title: `95% interval ${fmt.pct(r.low)}–${fmt.pct(r.high)}` });
      ci.style.left = `${r.low * 100}%`;
      ci.style.width = `${Math.max(0.5, (r.high - r.low) * 100)}%`;
      track.append(ci);
    }
    track.append(h("span", { class: "bar-label" }, r.key));
    list.append(h("div", { class: `bar-row ${small ? "small" : ""}`, role: "listitem",
      "aria-label": `${r.key}: ${fmt.pct(r.rate)} ${valueLabel}, ${r.k} of ${r.n}${small ? " (small sample)" : ""}` },
      track,
      h("div", { class: "bar-value" }, fmt.pct(r.rate), h("span", { class: "muted" }, `${r.k}/${r.n}`))));
  }
  if (!shown.length) list.append(h("p", { class: "muted" }, "No applications in this group yet."));
  return list;
}

/** Plain horizontal bars for counts (e.g. time to reply). */
export function countList(rows) {
  const max = Math.max(1, ...rows.map((r) => r.n));
  const list = h("div", { class: "barlist", role: "list" });
  for (const r of rows) {
    const fill = h("div", { class: "bar-fill" });
    fill.style.width = `${Math.max(r.n ? 2 : 0, (r.n / max) * 100)}%`;
    list.append(h("div", { class: "bar-row", role: "listitem", "aria-label": `${r.label}: ${r.n}` },
      h("div", { class: "bar-track" }, fill, h("span", { class: "bar-label" }, r.label)),
      h("div", { class: "bar-value" }, fmt.num(r.n))));
  }
  return list;
}

function srTable(headers, rows, caption) {
  return h("table", { class: "sr-only" }, h("caption", {}, caption),
    h("thead", {}, h("tr", {}, headers.map((x) => h("th", { scope: "col" }, x)))),
    h("tbody", {}, rows.map((r) => h("tr", {}, r.map((c) => h("td", {}, c))))));
}
