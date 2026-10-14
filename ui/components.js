// Accessible primitives: side panel (dialog), menu, tabs, segmented control,
// sortable table, empty state, command chip.
import { h } from "./lib.js";
import { commandButton, copyChip } from "./agent.js";
import { icon } from "./icons.js";

// ---------------------------------------------------------------- panel

let openPanel = null;

export function closePanel() {
  if (!openPanel) return;
  const { root, restore, onClose } = openPanel;
  root.replaceChildren();
  document.removeEventListener("keydown", openPanel.onKey);
  openPanel = null;
  if (onClose) onClose();
  if (restore && document.contains(restore)) restore.focus();
}

/** A right-hand detail panel with dialog semantics, focus trap and Esc. */
export function panel({ title, subtitle, actions, body, onClose, label }) {
  closePanel();
  const root = document.getElementById("panel-root");
  const titleId = `panel-title-${Math.random().toString(36).slice(2, 8)}`;
  const closeBtn = h("button", { class: "btn btn-ghost btn-icon", type: "button", "aria-label": "Close panel", onclick: closePanel }, icon("close"));
  const dialog = h("div", { class: "panel", role: "dialog", "aria-modal": "true", "aria-labelledby": titleId, "aria-label": label },
    h("div", { class: "panel-head" },
      h("div", { style: { flex: "1", minWidth: "0" } },
        h("h2", { id: titleId }, title),
        subtitle ? h("div", { class: "sub" }, subtitle) : null),
      actions || null,
      closeBtn),
    h("div", { class: "panel-body" }, body));
  const overlay = h("div", { class: "panel-overlay", onclick: closePanel });
  root.replaceChildren(overlay, dialog);
  const onKey = (e) => {
    if (e.key === "Escape") { e.preventDefault(); closePanel(); return; }
    if (e.key !== "Tab") return;
    const f = [...dialog.querySelectorAll("a[href],button:not([disabled]),input,select,textarea,[tabindex]:not([tabindex='-1'])")]
      .filter((el) => el.offsetParent !== null);
    if (!f.length) return;
    const first = f[0], last = f[f.length - 1];
    if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
  };
  document.addEventListener("keydown", onKey);
  openPanel = { root, restore: document.activeElement, onClose, onKey };
  closeBtn.focus();
  return dialog;
}

export function replacePanelBody(body) {
  const el = document.querySelector("#panel-root .panel-body");
  if (el) el.replaceChildren(body);
}

// ---------------------------------------------------------------- menu

/** A "⋯" button opening an action menu. items: [{label, onSelect, danger}|"-"|{heading}] */
export function menu(items, { label = "More actions", buttonClass = "btn btn-ghost btn-icon btn-sm" } = {}) {
  const wrap = h("div", { class: "menu-wrap" });
  const btn = h("button", { class: buttonClass, type: "button", "aria-haspopup": "menu", "aria-expanded": "false", "aria-label": label }, icon("more"));
  let list = null;
  const close = () => {
    if (!list) return;
    list.remove(); list = null;
    btn.setAttribute("aria-expanded", "false");
    document.removeEventListener("click", outside, true);
  };
  const outside = (e) => { if (!wrap.contains(e.target)) close(); };
  btn.addEventListener("click", (e) => {
    e.stopPropagation();
    if (list) { close(); return; }
    list = h("div", { class: "menu", role: "menu" });
    for (const it of items) {
      if (it === "-") { list.append(h("hr")); continue; }
      if (it.heading) { list.append(h("div", { class: "menu-label" }, it.heading)); continue; }
      list.append(h("button", {
        type: "button", role: "menuitem", class: it.danger ? "danger" : "",
        onclick: (ev) => { ev.stopPropagation(); close(); it.onSelect(); },
      }, it.label));
    }
    list.addEventListener("keydown", (ev) => {
      const opts = [...list.querySelectorAll("button")];
      const i = opts.indexOf(document.activeElement);
      if (ev.key === "ArrowDown") { ev.preventDefault(); opts[(i + 1) % opts.length].focus(); }
      if (ev.key === "ArrowUp") { ev.preventDefault(); opts[(i - 1 + opts.length) % opts.length].focus(); }
      if (ev.key === "Escape") { ev.stopPropagation(); close(); btn.focus(); }
    });
    wrap.append(list);
    btn.setAttribute("aria-expanded", "true");
    document.addEventListener("click", outside, true);
    list.querySelector("button")?.focus();
  });
  wrap.append(btn);
  return wrap;
}

// ---------------------------------------------------------------- tabs

/** Tabs with roving focus. tabs: [{id, label, count}]. */
export function tabs(list, active, onChange, label = "Sections") {
  const bar = h("div", { class: "tabs", role: "tablist", "aria-label": label });
  for (const t of list) {
    const b = h("button", {
      type: "button", role: "tab", id: `tab-${t.id}`, "aria-selected": String(t.id === active),
      tabindex: t.id === active ? "0" : "-1", onclick: () => onChange(t.id),
    }, t.label, t.count !== undefined && t.count !== null ? h("span", { class: "n" }, t.count) : null);
    bar.append(b);
  }
  bar.addEventListener("keydown", (e) => {
    const btns = [...bar.querySelectorAll("button")];
    const i = btns.indexOf(document.activeElement);
    if (e.key === "ArrowRight" || e.key === "ArrowLeft") {
      e.preventDefault();
      const j = (i + (e.key === "ArrowRight" ? 1 : -1) + btns.length) % btns.length;
      btns[j].focus(); btns[j].click();
    }
  });
  return bar;
}

export function segmented(options, active, onChange, label) {
  const g = h("div", { class: "segmented", role: "group", "aria-label": label });
  for (const o of options) {
    g.append(h("button", { type: "button", "aria-pressed": String(o.id === active), onclick: () => onChange(o.id) },
      o.label, o.count !== undefined ? h("span", { class: "n" }, o.count) : null));
  }
  return g;
}

// ---------------------------------------------------------------- table

/** Sortable table. columns: [{key, label, render(row), sort(row), num, width}] */
export function table({ columns, rows, onRow, sortKey, sortDir = "asc", caption, selected }) {
  let key = sortKey, dir = sortDir;
  const wrap = h("div", { class: "table-wrap" });
  const draw = () => {
    const col = columns.find((c) => c.key === key);
    const sorted = col && col.sort ? [...rows].sort((a, b) => {
      const x = col.sort(a), y = col.sort(b);
      if (x === y) return 0;
      if (x === null || x === undefined) return 1;
      if (y === null || y === undefined) return -1;
      return (x < y ? -1 : 1) * (dir === "asc" ? 1 : -1);
    }) : rows;
    const thead = h("thead", {}, h("tr", {}, columns.map((c) => {
      const th = h("th", { scope: "col", class: c.num ? "num" : "", style: c.width ? { width: c.width } : null });
      if (c.sort) {
        if (c.key === key) th.setAttribute("aria-sort", dir === "asc" ? "ascending" : "descending");
        th.append(h("button", { type: "button", onclick: () => {
          if (key === c.key) dir = dir === "asc" ? "desc" : "asc"; else { key = c.key; dir = c.num ? "desc" : "asc"; }
          draw();
        } }, c.label, c.key === key ? (dir === "asc" ? " ↑" : " ↓") : ""));
      } else th.append(c.label);
      return th;
    })));
    const tbody = h("tbody");
    for (const r of sorted) {
      const tr = h("tr", { class: `${onRow ? "clickable" : ""} ${selected && selected(r) ? "selected" : ""}` });
      columns.forEach((c, i) => {
        const td = h("td", { class: c.num ? "num" : "" }, c.render ? c.render(r) : r[c.key]);
        if (i === 0 && onRow) {
          // the first cell carries a real button so the row is keyboard-reachable
          const content = [...td.childNodes];
          const b = h("button", { type: "button", class: "row-link", onclick: (e) => { e.stopPropagation(); onRow(r); } });
          b.append(...content);
          td.replaceChildren(b);
        }
        tr.append(td);
      });
      if (onRow) tr.addEventListener("click", () => onRow(r));
      tbody.append(tr);
    }
    wrap.replaceChildren(h("table", {}, caption ? h("caption", { class: "sr-only" }, caption) : null, thead, tbody));
  };
  draw();
  return wrap;
}

// ---------------------------------------------------------------- bits

export function empty(title, text, action) {
  return h("div", { class: "empty" }, h("h3", {}, title), h("p", {}, text), action ? h("div", { style: { marginTop: "16px" } }, action) : null);
}

const CHAT_ONLY = {
  apply: "Runs in the chat: it fills the form in your browser and stops for you before submitting. Click to copy.",
  setup: "Runs in the chat for now. Click to copy.",
  sync: "Runs in the chat: it pushes to your private repo. Click to copy.",
};

/** A command chip: runs it in your own Claude Code / Codex when it can be
 *  started from here, otherwise copies it for the chat. */
export function commandChip(cmd) {
  const name = (/^\/([a-z]+)/.exec(cmd) || [])[1];
  return commandButton(cmd) || copyChip(cmd, CHAT_ONLY[name]);
}

export function sectionHead(title, meta) {
  return h("div", { class: "section-head" }, h("h2", {}, title), meta ? (typeof meta === "string" ? h("p", {}, meta) : meta) : null);
}

export function pageHead(title, subtitle, actions) {
  return h("div", { class: "page-head" },
    h("div", {}, h("h1", {}, title), subtitle ? h("p", {}, subtitle) : null),
    actions || null);
}

export function notice(text, kind = "", iconName = "info") {
  return h("div", { class: `notice ${kind}` }, icon(iconName), h("div", {}, text));
}
