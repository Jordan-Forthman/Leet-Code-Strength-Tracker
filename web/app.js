"use strict";

/* =====================================================================
   LeetCode Strength Tracker - front end (vanilla JS, no build step)
   ===================================================================== */

// ---------- DOM helpers (text always goes in as text nodes) ----------
function h(tag, attrs, ...kids) {
  const el = document.createElement(tag);
  applyAttrs(el, attrs);
  appendKids(el, kids);
  return el;
}
const SVGNS = "http://www.w3.org/2000/svg";
function s(tag, attrs, ...kids) {
  const el = document.createElementNS(SVGNS, tag);
  applyAttrs(el, attrs);
  appendKids(el, kids);
  return el;
}
function applyAttrs(el, attrs) {
  if (!attrs) return;
  for (const [k, v] of Object.entries(attrs)) {
    if (v === null || v === undefined || v === false) continue;
    if (k.startsWith("on") && typeof v === "function") el.addEventListener(k.slice(2), v);
    else if (k === "style" && typeof v === "object") Object.assign(el.style, v);
    else if (k === "class") el.setAttribute("class", v);
    else if (k === "value" && "value" in el) el.value = v;
    else if (k === "checked" || k === "selected" || k === "disabled") el[k] = !!v;
    else el.setAttribute(k, v === true ? "" : String(v));
  }
}
function appendKids(el, kids) {
  for (const k of kids.flat(Infinity)) {
    if (k === null || k === undefined || k === false) continue;
    el.appendChild(k instanceof Node ? k : document.createTextNode(String(k)));
  }
}
const $ = (sel, root = document) => root.querySelector(sel);

// ---------- formatting ----------
const fmt = {
  r: (x) => Math.round(x).toLocaleString(),
  pct: (x) => (x === null || x === undefined ? "–" : `${Math.round(x * 100)}%`),
  signed: (x, d = 0) => `${x > 0 ? "+" : x < 0 ? "−" : "±"}${Math.abs(x).toFixed(d)}`,
  date: (ts) => new Date(ts).toLocaleDateString(undefined, { month: "short", day: "numeric" }),
  dateTime: (ts) => new Date(ts).toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }),
  mins: (m) => (m === null || m === undefined ? "–" : `${(+m).toFixed(m < 10 ? 1 : 0)}m`),
  clock: (ms) => {
    const t = Math.max(0, Math.floor(ms / 1000));
    const hh = Math.floor(t / 3600), mm = Math.floor((t % 3600) / 60), ss = t % 60;
    const p = (n) => String(n).padStart(2, "0");
    return hh ? `${hh}:${p(mm)}:${p(ss)}` : `${p(mm)}:${p(ss)}`;
  },
};
function deltaSpan(x, d = 0) {
  return h("span", { class: x > 0.05 ? "delta-up" : x < -0.05 ? "delta-down" : "muted" }, fmt.signed(x, d));
}
function severity(p) {
  if (p >= 0.7) return { color: "var(--good)", label: "Ready" };
  if (p >= 0.5) return { color: "var(--warning)", label: "Close" };
  if (p >= 0.3) return { color: "var(--serious)", label: "Building" };
  return { color: "var(--critical)", label: "Low" };
}
function localInputNow() {
  const d = new Date();
  d.setMinutes(d.getMinutes() - d.getTimezoneOffset());
  return d.toISOString().slice(0, 16);
}
function localInputFrom(ts) {
  const d = new Date(ts);
  d.setMinutes(d.getMinutes() - d.getTimezoneOffset());
  return d.toISOString().slice(0, 16);
}

// ---------- storage (per-browser conveniences only) ----------
const LS = {
  get(k, dflt) { try { const v = localStorage.getItem(k); return v === null ? dflt : JSON.parse(v); } catch { return dflt; } },
  set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* ignore */ } },
  del(k) { try { localStorage.removeItem(k); } catch { /* ignore */ } },
};

// ---------- API ----------
async function api(path, opts = {}) {
  const init = { method: opts.method || "GET", headers: {} };
  if (opts.body !== undefined) {
    init.headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(opts.body);
  }
  const res = await fetch(path, init);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
  return data;
}
const cache = { problems: null, byId: null, groups: null, typical: null };
async function loadProblems(force = false) {
  if (cache.problems && !force) return cache;
  const d = await api("/api/problems");
  cache.problems = d.problems;
  cache.byId = new Map(d.problems.map((p) => [p.id, p]));
  cache.groups = d.groups;
  cache.typical = d.typical;
  return cache;
}
function invalidate() { cache.problems = null; }

function toast(msg) {
  const t = $("#toast");
  t.textContent = msg;
  t.hidden = false;
  clearTimeout(toast._t);
  toast._t = setTimeout(() => { t.hidden = true; }, 2600);
}

// ---------- tooltip ----------
const tip = {
  show(evt, build) {
    const el = $("#tooltip");
    el.replaceChildren(...build());
    el.hidden = false;
    this.move(evt);
  },
  move(evt) {
    const el = $("#tooltip");
    let x, y;
    if (evt && "clientX" in evt && evt.clientX) { x = evt.clientX; y = evt.clientY; }
    else if (evt && evt.target && evt.target.getBoundingClientRect) {
      const r = evt.target.getBoundingClientRect(); x = r.left + r.width / 2; y = r.top;
    } else return;
    const w = el.offsetWidth, hgt = el.offsetHeight;
    let left = x + 14, top = y - hgt - 10;
    if (left + w > window.innerWidth - 8) left = x - w - 14;
    if (top < 8) top = y + 16;
    el.style.left = `${Math.max(8, left)}px`;
    el.style.top = `${top}px`;
  },
  hide() { $("#tooltip").hidden = true; },
};

// =====================================================================
// Practice session + timer (persisted so a refresh doesn't lose it)
// =====================================================================
const session = {
  get() { return LS.get("lct.session", null); },
  set(v) { LS.set("lct.session", v); updateTimerChip(); },
  clear() { LS.del("lct.session"); updateTimerChip(); },
  elapsed(sess = this.get()) {
    if (!sess) return 0;
    return (sess.accMs || 0) + (sess.running ? Date.now() - sess.startedAt : 0);
  },
  start(problemId, source = "self", blind = false) {
    const cur = this.get();
    if (cur && cur.problemId === problemId) return;
    this.set({ problemId, source, blind, accMs: 0, running: false, startedAt: null });
  },
  run() {
    const c = this.get(); if (!c || c.running) return;
    this.set({ ...c, running: true, startedAt: Date.now() });
  },
  pause() {
    const c = this.get(); if (!c || !c.running) return;
    this.set({ ...c, running: false, accMs: this.elapsed(c), startedAt: null });
  },
  reset() {
    const c = this.get(); if (!c) return;
    this.set({ ...c, running: false, accMs: 0, startedAt: null });
  },
};

function updateTimerChip() {
  const chip = $("#timer-chip");
  const sess = session.get();
  const onPractice = location.hash.startsWith("#/practice");
  if (!sess || onPractice || (!sess.running && !sess.accMs)) { chip.hidden = true; return; }
  const p = cache.byId && cache.byId.get(sess.problemId);
  const limitMs = (p ? p.timeLimit : 35) * 60000;
  const ms = session.elapsed(sess);
  chip.hidden = false;
  chip.classList.toggle("over", ms > limitMs);
  chip.textContent = `${sess.running ? "⏱" : "⏸"} ${fmt.clock(ms)}${p ? " · #" + p.id : ""}`;
}
$("#timer-chip").addEventListener("click", () => { location.hash = "#/practice"; });
setInterval(() => {
  updateTimerChip();
  const disp = $("#timer-display");
  if (disp && disp.isConnected) disp.dispatchEvent(new Event("tick"));
}, 250);

// =====================================================================
// Router
// =====================================================================
const routes = {
  "": renderDashboard,
  practice: renderPractice,
  topics: renderTopics,
  bank: renderBank,
  history: renderHistory,
  settings: renderSettings,
  method: renderMethod,
};
function parseHash() {
  const raw = location.hash.replace(/^#\/?/, "");
  const [path, query] = raw.split("?");
  return { name: path || "", params: new URLSearchParams(query || "") };
}
async function router() {
  const { name, params } = parseHash();
  const fn = routes[name] || renderDashboard;
  document.querySelectorAll("#nav a").forEach((a) => {
    const target = a.getAttribute("href").replace(/^#\/?/, "");
    a.classList.toggle("active", target === name);
  });
  tip.hide();
  updateTimerChip();
  const view = $("#view");
  try {
    const node = await fn(params);
    view.replaceChildren(node);
  } catch (e) {
    console.error(e);
    view.replaceChildren(h("div", { class: "card" }, h("h2", null, "Something went wrong"),
      h("p", { class: "muted" }, String(e.message || e)),
      h("p", { class: "muted small" }, "Is the server running? Start it with: python3 lct.py")));
  }
  window.scrollTo(0, 0);
}
window.addEventListener("hashchange", router);

// theme toggle
(function initTheme() {
  const saved = LS.get("lct.theme", null);
  if (saved) document.documentElement.dataset.theme = saved;
  $("#theme-toggle").addEventListener("click", () => {
    const cur = document.documentElement.dataset.theme ||
      (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
    const next = cur === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    LS.set("lct.theme", next);
  });
})();

// re-render charts on resize (debounced)
let resizeT;
window.addEventListener("resize", () => {
  clearTimeout(resizeT);
  resizeT = setTimeout(() => document.querySelectorAll("[data-chart]").forEach((c) => c.dispatchEvent(new Event("redraw"))), 150);
});

function practiceLink(problem, source = "self", blind = false) {
  return () => {
    session.start(problem.id, source, blind);
    location.hash = "#/practice";
  };
}
function lcLink(p, label = "LeetCode ↗") {
  return h("a", { class: "btn sm", href: p.url, target: "_blank", rel: "noopener" }, label);
}

// =====================================================================
// Dashboard
// =====================================================================
let shuffleN = 0;
async function renderDashboard() {
  const [d] = await Promise.all([api(`/api/dashboard?shuffle=${shuffleN}`), loadProblems().catch(() => null)]);
  const o = d.overall;
  const hasData = d.totals.attempts > 0;
  const root = h("div", { class: "stack" });

  // ---- hero ----
  const toTarget = Math.max(0, Math.min(1, (o.r - o.start) / Math.max(1, o.target - o.start)));
  const hero = h("section", { class: "card" },
    h("div", { class: "card-head" }, h("h2", null, "Overall strength"),
      h("span", { class: "sub" }, hasData ? `updated ${fmt.dateTime(d.now)}` : "provisional, no attempts yet")),
    h("div", { class: "hero" },
      h("div", null,
        h("span", { class: "hero-num num" }, fmt.r(o.r)),
        h("span", { class: "hero-pm num" }, `±${Math.round(o.rd)}`)),
      h("div", { class: "stack", style: { gap: "6px" } },
        h("span", { class: "tier" }, o.tier),
        hasData ? h("span", { class: "small ink2" }, "7-day ", deltaSpan(o.weekChange)) : null)),
    h("div", { style: { marginTop: "16px" } },
      h("div", { class: "row small ink2", style: { marginBottom: "6px" } },
        h("span", null, `Start ${fmt.r(o.start)}`), h("span", { class: "spacer" }),
        h("span", null, o.r >= o.target ? "Target reached" : `${fmt.r(o.target - o.r)} to assessment-ready (${fmt.r(o.target)})`)),
      h("div", { class: "progress", title: "Progress from your starting rating to the assessment-ready target" },
        h("span", { style: { width: `${toTarget * 100}%` } }))),
    h("h3", { style: { margin: "18px 0 8px" } }, "Readiness: expected score on a typical interview problem, within your time limit"),
    h("div", { class: "meters" }, ["Easy", "Medium", "Hard"].map((diff) => {
      const p = o.readiness[diff];
      const sev = severity(p);
      return h("div", { class: "meter-row" },
        h("span", { class: `diff ${diff}` }, diff),
        h("div", { class: "meter", title: `${fmt.pct(p)}; 70% marks assessment-ready` },
          h("span", { style: { width: `${p * 100}%`, background: sev.color } }),
          h("span", { class: "mark", style: { left: "70%" } })),
        h("span", { class: "status num" }, h("i", { style: { background: sev.color } }), `${fmt.pct(p)} · ${sev.label}`));
    })),
    h("p", { class: "small muted", style: { margin: "10px 0 0" } },
      `Typical ratings: Easy ${d.bankInfo.typical.Easy}, Medium ${d.bankInfo.typical.Medium}, Hard ${d.bankInfo.typical.Hard} `,
      `(NeetCode 150 medians). Limits: ${d.settings.timeLimits.Easy}/${d.settings.timeLimits.Medium}/${d.settings.timeLimits.Hard} min.`));

  // ---- today's plan ----
  const sg = d.suggestions;
  const items = [...sg.review.slice(0, 2), ...sg.focus, ...(sg.mock ? [sg.mock] : [])];
  const plan = h("section", { class: "card" },
    h("div", { class: "card-head" },
      h("h2", null, "Today's plan"),
      h("div", { class: "row" },
        h("span", { class: "sub num" }, `${d.totals.today}/${d.settings.dailyGoal} done today`),
        h("button", { class: "sm", type: "button", title: "Different picks for the same priorities",
          onclick: () => { shuffleN++; router(); } }, "↻ Shuffle"))),
    items.length ? items.map((it) => suggestionRow(it)) : h("div", { class: "empty" }, "Nothing to suggest. Try enabling premium problems in Settings."),
    sg.review.length > 2 ? h("p", { class: "small muted", style: { margin: "8px 0 0" } },
      `+${sg.review.length - 2} more due for review. `, h("a", { href: "#/bank?status=review" }, "See review queue")) : null);

  // ---- tiles ----
  const t = d.totals;
  const tile = (label, value, note) => h("div", { class: "tile" },
    h("div", { class: "label" }, label), h("div", { class: "value num" }, value), note ? h("div", { class: "note" }, note) : null);
  const tiles = (h("div", { class: "tiles" },
    tile("Attempts logged", t.attempts, `${t.unique} distinct problems`),
    tile("Clean timed solves", t.clean, t.attempts ? `${fmt.pct(t.clean / t.attempts)} of attempts` : "solved alone, within limit"),
    tile("Day streak", t.streak, t.streak ? "keep it going" : "log one today"),
    tile("Today", `${t.today}/${d.settings.dailyGoal}`, "daily goal"),
    tile("Review queue", t.reviewPending, "problems to re-solve"),
    tile("7-day change", fmt.signed(o.weekChange), "overall rating")));
  root.append(h("div", { class: "grid g-hero" }, h("div", { class: "stack" }, hero, tiles), plan));

  // ---- charts ----
  const histCard = h("section", { class: "card" },
    h("div", { class: "card-head" }, h("h2", null, "Rating over time"), h("span", { class: "sub" }, "overall, after each attempt")));
  histCard.append(hasData ? historyChart(d.history, o.target, o.start) : h("div", { class: "empty" }, "Your rating curve appears after your first logged attempt."));
  const topicCard = h("section", { class: "card" },
    h("div", { class: "card-head" }, h("h2", null, "Topic strengths"),
      h("a", { class: "sub", href: "#/topics" }, "details →")),
    topicChart(d.groups, o.target));
  root.append(h("div", { class: "grid g-2" }, histCard, topicCard));

  // ---- difficulty + calendar ----
  const diffCard = h("section", { class: "card" },
    h("div", { class: "card-head" }, h("h2", null, "By difficulty")),
    h("div", { class: "table-wrap" }, h("table", null,
      h("thead", null, h("tr", null, h("th", null, "Difficulty"), h("th", { class: "r" }, "Attempts"),
        h("th", { class: "r" }, "Clean"), h("th", { class: "r" }, "Avg solve"), h("th", { class: "r" }, "Limit"),
        h("th", { class: "r" }, "Readiness"))),
      h("tbody", null, ["Easy", "Medium", "Hard"].map((diff) => {
        const x = d.byDifficulty[diff];
        return h("tr", null, h("td", null, h("span", { class: `diff ${diff}` }, diff)),
          h("td", { class: "r" }, x.attempts),
          h("td", { class: "r" }, x.attempts ? `${x.clean} (${fmt.pct(x.cleanRate)})` : "–"),
          h("td", { class: "r" }, fmt.mins(x.avgMinutes)),
          h("td", { class: "r" }, `${x.limit}m`),
          h("td", { class: "r" }, fmt.pct(o.readiness[diff])));
      })))),
    d.weakest.length ? h("p", { class: "small ink2", style: { margin: "12px 0 0" } },
      h("b", null, "Weakest: "), d.weakest.join(", "), h("br"),
      h("b", null, "Strongest: "), d.strongest.join(", ")) : null);
  const calCard = h("section", { class: "card" },
    h("div", { class: "card-head" }, h("h2", null, "Activity"), h("span", { class: "sub" }, "last 18 weeks")),
    heatmap(d.calendar, d.now));
  root.append(h("div", { class: "grid g-2" }, diffCard, calCard));

  // ---- recent ----
  if (hasData) {
    root.append(h("section", { class: "card" },
      h("div", { class: "card-head" }, h("h2", null, "Recent attempts"), h("a", { class: "sub", href: "#/history" }, "full history →")),
      attemptsTable(d.recent.slice(0, 8), { compact: true })));
  }
  return root;
}

function suggestionRow(it) {
  const p = it.problem;
  const blind = !!it.blind;
  return h("div", { class: "sugg" },
    h("div", null,
      h("div", { class: "row", style: { marginBottom: "4px" } },
        h("span", { class: `kind ${it.kind}` }, it.kind),
        h("span", { class: `diff ${p.difficulty}` }, p.difficulty),
        h("span", { class: "chip num", title: p.ratingSource === "contest" ? "Contest-derived rating" : "Estimated rating" },
          `${p.ratingSource === "contest" ? "" : "~"}${p.rating}`),
        h("span", { class: "chip num" }, `${it.timeLimit} min`),
        h("span", { class: "chip num", title: "Model's expected score for you" }, `exp ${fmt.pct(it.expected)}`)),
      h("div", { class: "title" }, `${p.id}. ${p.title}`),
      h("div", { class: "reason" }, it.reason),
      !blind && p.groups.length ? h("div", { class: "row", style: { marginTop: "4px" } }, p.groups.slice(0, 3).map((g) => h("span", { class: "chip" }, g))) : null),
    h("div", { class: "actions" },
      h("button", { class: "primary sm", type: "button", onclick: practiceLink(p, it.kind === "focus" ? "suggested" : it.kind, blind) }, "Start ▸"),
      lcLink(p)));
}

// ---------- chart: rating history ----------
function historyChart(history, target, start) {
  const wrap = h("div", { class: "chart", "data-chart": "history" });
  const draw = () => {
    const W = Math.max(320, wrap.clientWidth || 560), H = 260;
    const m = { l: 44, r: 14, t: 16, b: 26 };
    const pts = [{ r: start, rd: null, i: 0 }, ...history.map((x, i) => ({ ...x, i: i + 1 }))];
    const n = pts.length - 1;
    let lo = Math.min(target, ...pts.map((p) => p.r - (p.rd || 0)));
    let hi = Math.max(target, ...pts.map((p) => p.r + (p.rd || 0)));
    lo = Math.floor((lo - 20) / 100) * 100; hi = Math.ceil((hi + 20) / 100) * 100;
    const x = (i) => m.l + (n ? (i / n) : 0.5) * (W - m.l - m.r);
    const y = (v) => m.t + (1 - (v - lo) / (hi - lo)) * (H - m.t - m.b);
    const step = (hi - lo) > 800 ? 200 : 100;
    const svg = s("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": "Overall rating history" });
    for (let v = lo; v <= hi; v += step) {
      svg.append(s("line", { class: "gridline", x1: m.l, x2: W - m.r, y1: y(v), y2: y(v) }),
        s("text", { x: m.l - 6, y: y(v) + 4, "text-anchor": "end" }, String(v)));
    }
    // uncertainty band (only for points after attempts)
    const bp = pts.filter((p) => p.rd !== null);
    if (bp.length) {
      const up = bp.map((p) => `${x(p.i)},${y(p.r + p.rd)}`);
      const dn = bp.slice().reverse().map((p) => `${x(p.i)},${y(p.r - p.rd)}`);
      svg.append(s("polygon", { class: "bandarea", points: [...up, ...dn].join(" ") }));
    }
    svg.append(s("line", { class: "target", x1: m.l, x2: W - m.r, y1: y(target), y2: y(target) }),
      s("text", { class: "target-lbl", x: W - m.r, y: y(target) - 6, "text-anchor": "end" }, `Target ${Math.round(target)}`));
    svg.append(s("path", { class: "line", d: pts.map((p, k) => `${k ? "L" : "M"}${x(p.i)},${y(p.r)}`).join("") }));
    const last = pts[pts.length - 1];
    svg.append(s("circle", { class: "dot", cx: x(last.i), cy: y(last.r), r: 4.5 }),
      s("text", { class: "val", x: x(last.i) - 8, y: y(last.r) - 10, "text-anchor": "end" }, String(Math.round(last.r))));
    // x labels: first & last dates
    if (history.length) {
      svg.append(s("text", { x: x(1), y: H - 6, "text-anchor": "start" }, fmt.date(history[0].ts)),
        s("text", { x: W - m.r, y: H - 6, "text-anchor": "end" }, `${fmt.date(history[history.length - 1].ts)} · ${n} attempts`));
    }
    // hover layer: crosshair snaps to nearest attempt
    const cross = s("line", { class: "crosshair", y1: m.t, y2: H - m.b, visibility: "hidden" });
    const hl = s("circle", { class: "dot", r: 5, visibility: "hidden" });
    const overlay = s("rect", { class: "hit", x: m.l, y: 0, width: W - m.l - m.r, height: H, tabindex: 0,
      "aria-label": "Rating history; use arrow keys to step through attempts" });
    let cur = n;
    const showAt = (i, evt) => {
      cur = Math.max(1, Math.min(n, i));
      const p = pts[cur];
      cross.setAttribute("x1", x(cur)); cross.setAttribute("x2", x(cur)); cross.setAttribute("visibility", "visible");
      hl.setAttribute("cx", x(cur)); hl.setAttribute("cy", y(p.r)); hl.setAttribute("visibility", "visible");
      tip.show(evt, () => [
        h("div", { class: "tv num" }, `${Math.round(p.r)} ±${Math.round(p.rd)}`),
        h("div", { class: "tl" }, `#${cur} · ${fmt.dateTime(p.ts)}`),
        h("div", null, `${p.title} (${p.difficulty})`),
        h("div", { class: "tl" }, `${p.outcome} · score ${p.score.toFixed(2)}`),
      ]);
    };
    overlay.addEventListener("pointermove", (e) => {
      if (!n) return;
      const box = svg.getBoundingClientRect();
      const px = (e.clientX - box.left) * (W / box.width);
      showAt(Math.round(((px - m.l) / (W - m.l - m.r)) * n), e);
    });
    overlay.addEventListener("pointerleave", () => { cross.setAttribute("visibility", "hidden"); hl.setAttribute("visibility", "hidden"); tip.hide(); });
    overlay.addEventListener("keydown", (e) => {
      if (e.key === "ArrowLeft") { showAt(cur - 1, { target: hl }); e.preventDefault(); }
      if (e.key === "ArrowRight") { showAt(cur + 1, { target: hl }); e.preventDefault(); }
    });
    overlay.addEventListener("blur", () => tip.hide());
    svg.append(cross, hl, overlay);
    wrap.replaceChildren(svg, h("div", { class: "legend" },
      h("span", { class: "key" }, h("span", { class: "ln", style: { background: "var(--accent)" } }), "Rating"),
      h("span", { class: "key" }, h("span", { class: "sw", style: { background: "var(--band)" } }), "±1 RD (uncertainty)"),
      h("span", { class: "key" }, h("span", { class: "ln", style: { background: "var(--good)" } }), "Assessment-ready target")));
  };
  wrap.addEventListener("redraw", draw);
  requestAnimationFrame(draw);
  return wrap;
}

// ---------- chart: topic strengths (dot + uncertainty interval) ----------
function topicChart(groups, target) {
  const wrap = h("div", { class: "chart", "data-chart": "topics" });
  const rows = groups.filter((g) => g.importance >= 0.5 || g.rated).slice()
    .sort((a, b) => (b.rated - a.rated) || (a.rated ? a.r - b.r : b.importance - a.importance));
  const draw = () => {
    const W = Math.max(320, wrap.clientWidth || 560);
    const narrow = W < 460;
    const rowH = 24, m = { l: narrow ? 118 : 168, r: 82, t: 22, b: 8 };
    const H = m.t + rows.length * rowH + m.b;
    let lo = Math.min(target - 100, ...rows.map((g) => g.r - g.rd));
    let hi = Math.max(target + 100, ...rows.map((g) => g.r + g.rd));
    lo = Math.floor(lo / 100) * 100; hi = Math.ceil(hi / 100) * 100;
    const x = (v) => m.l + ((v - lo) / (hi - lo)) * (W - m.l - m.r);
    const svg = s("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": "Topic ratings with uncertainty" });
    const step = (hi - lo) > 1000 ? 400 : 200;
    for (let v = Math.ceil(lo / step) * step; v <= hi; v += step) {
      svg.append(s("line", { class: "gridline", x1: x(v), x2: x(v), y1: m.t - 4, y2: H - m.b }));
      if (Math.abs(x(v) - x(target)) > 44) svg.append(s("text", { x: x(v), y: 12, "text-anchor": "middle" }, String(v)));
    }
    svg.append(s("line", { class: "target", x1: x(target), x2: x(target), y1: m.t - 4, y2: H - m.b }));
    rows.forEach((g, i) => {
      const cy = m.t + i * rowH + rowH / 2;
      const label = narrow && g.group.length > 16 ? g.group.slice(0, 15) + "…" : g.group;
      const grp = s("g", { class: "rowg", tabindex: 0, role: "link", "aria-label": `${g.group}: ${Math.round(g.r)} plus or minus ${Math.round(g.rd)}` },
        s("rect", { class: "row-hover", x: 0, y: cy - rowH / 2, width: W, height: rowH, rx: 4 }),
        s("text", { class: "lbl", x: m.l - 10, y: cy + 4, "text-anchor": "end" }, label),
        s("line", { class: `interval${g.rated ? "" : " unrated"}`, x1: x(g.r - g.rd), x2: x(g.r + g.rd), y1: cy, y2: cy }),
        s("circle", { class: `dot${g.rated ? "" : " unrated"}`, cx: x(g.r), cy, r: 4.5 }),
        s("text", { class: g.rated ? "val" : "", x: W - 4, y: cy + 4, "text-anchor": "end" },
          g.rated ? `${Math.round(g.r)} ±${Math.round(g.rd)}` : "not yet"),
        s("rect", { class: "hit", x: 0, y: cy - rowH / 2, width: W, height: rowH }));
      const show = (e) => tip.show(e, () => [
        h("div", { class: "tv num" }, g.rated ? `${Math.round(g.r)} ±${Math.round(g.rd)}` : "Not practised yet"),
        h("div", null, g.group),
        h("div", { class: "tl" }, g.rated ? `${g.attempts} attempts · Medium readiness ${fmt.pct(g.readiness.Medium)}` : "Assumed equal to your overall rating until you log one"),
        h("div", { class: "tl" }, `Assessment frequency: ${g.importance >= 0.9 ? "core" : g.importance >= 0.7 ? "common" : "occasional"}`),
      ]);
      grp.addEventListener("pointermove", show);
      grp.addEventListener("focus", show);
      grp.addEventListener("pointerleave", () => tip.hide());
      grp.addEventListener("blur", () => tip.hide());
      const go = () => { location.hash = `#/topics?focus=${encodeURIComponent(g.group)}`; };
      grp.addEventListener("click", go);
      grp.addEventListener("keydown", (e) => { if (e.key === "Enter") go(); });
      svg.append(grp);
    });
    svg.append(s("text", { class: "target-lbl", x: x(target), y: 12, "text-anchor": "middle" }, `target ${Math.round(target)}`));
    wrap.replaceChildren(svg, h("div", { class: "legend" },
      h("span", { class: "key muted" }, "Weakest first ·"),
      h("span", { class: "key" }, h("span", { class: "sw", style: { background: "var(--accent)", width: "10px", borderRadius: "50%" } }), "Rating"),
      h("span", { class: "key" }, h("span", { class: "sw", style: { background: "var(--band)", width: "22px" } }), "±1 RD"),
      h("span", { class: "key" }, h("span", { class: "sw", style: { border: "1.5px solid var(--muted)", width: "10px", borderRadius: "50%" } }), "Not practised"),
      h("span", { class: "key" }, h("span", { class: "ln", style: { background: "var(--good)", width: "2px", height: "12px" } }), "Target")));
  };
  wrap.addEventListener("redraw", draw);
  requestAnimationFrame(draw);
  return wrap;
}

// ---------- chart: activity heatmap ----------
function heatmap(calendar, nowIso) {
  const weeks = 18, cell = 14, gap = 3;
  const now = new Date(nowIso);
  const end = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const dow = (end.getDay() + 6) % 7; // Monday = 0
  const startDay = new Date(end); startDay.setDate(end.getDate() - dow - (weeks - 1) * 7);
  const W = 28 + weeks * (cell + gap), H = 7 * (cell + gap) + 18;
  const svg = s("svg", { viewBox: `0 0 ${W} ${H}`, width: W, height: H, class: "heat", role: "img", "aria-label": "Daily attempts heatmap", style: "max-width:100%;height:auto" });
  ["Mon", "", "Wed", "", "Fri", "", ""].forEach((lbl, r) => lbl && svg.append(s("text", { x: 0, y: 18 + r * (cell + gap) + cell - 3 }, lbl)));
  const level = (c) => (c <= 0 ? 0 : c === 1 ? 1 : c === 2 ? 2 : c <= 4 ? 3 : 4);
  let lastMonth = -1, lastLabelW = -9;
  for (let w = 0; w < weeks; w++) {
    for (let r = 0; r < 7; r++) {
      const d = new Date(startDay); d.setDate(startDay.getDate() + w * 7 + r);
      if (d > end) continue;
      const key = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
      const c = calendar[key] || 0;
      if (r === 0 && d.getMonth() !== lastMonth && w - lastLabelW >= 3) {
        lastMonth = d.getMonth(); lastLabelW = w;
        svg.append(s("text", { x: 28 + w * (cell + gap), y: 10 }, d.toLocaleDateString(undefined, { month: "short" })));
      }
      const rect = s("rect", { x: 28 + w * (cell + gap), y: 18 + r * (cell + gap), width: cell, height: cell, rx: 3,
        style: `fill: var(--heat-${level(c)})`, tabindex: -1 });
      const show = (e) => tip.show(e, () => [h("div", { class: "tv num" }, `${c} attempt${c === 1 ? "" : "s"}`),
        h("div", { class: "tl" }, d.toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" }))]);
      rect.addEventListener("pointermove", show);
      rect.addEventListener("pointerleave", () => tip.hide());
      svg.append(rect);
    }
  }
  return h("div", { class: "chart" }, svg, h("div", { class: "legend" }, "Less",
    [0, 1, 2, 3, 4].map((l) => h("span", { class: "sw", style: { background: `var(--heat-${l})` } })), "More"));
}

// ---------- shared: attempts table ----------
function attemptsTable(rows, { compact = false, onEdit, onDelete } = {}) {
  if (!rows.length) return h("div", { class: "empty" }, "No attempts logged yet.");
  return h("div", { class: "table-wrap" }, h("table", null,
    h("thead", null, h("tr", null,
      h("th", null, "When"), h("th", null, "Problem"), h("th", null, "Outcome"),
      h("th", { class: "r" }, "Time"), compact ? null : h("th", { class: "r" }, "Wrong"),
      h("th", { class: "r", title: "Performance score vs the model's expectation" }, "Score / exp"),
      h("th", { class: "r" }, "Overall Δ"), compact ? null : h("th", null, "Topic Δ"),
      onEdit ? h("th", null, "") : null)),
    h("tbody", null, rows.map((r) => {
      const top = Object.entries(r.groupDeltas).sort((a, b) => Math.abs(b[1]) - Math.abs(a[1])).slice(0, 3);
      return h("tr", null,
        h("td", { class: "small ink2", style: { whiteSpace: "nowrap" } }, fmt.dateTime(r.ts)),
        h("td", { class: "title-cell" },
          h("a", { href: r.problem.url, target: "_blank", rel: "noopener" }, `${r.problem.id}. ${r.problem.title}`), " ",
          h("span", { class: `diff ${r.problem.difficulty}` }), r.repeat ? h("span", { class: "chip", title: "Repeat attempts count at 60% weight" }, "repeat") : null,
          r.notes ? h("div", { class: "small muted" }, r.notes) : null),
        h("td", { class: "small" }, r.outcomeLabel),
        h("td", { class: "r num" }, `${fmt.mins(r.minutes)} / ${Math.round(r.limit || 0) || "–"}`),
        compact ? null : h("td", { class: "r num" }, r.wrong || 0),
        h("td", { class: "r num" }, `${r.score.toFixed(2)} / ${r.expected.toFixed(2)}`),
        h("td", { class: "r num" }, deltaSpan(r.overallDelta, 1)),
        compact ? null : h("td", { class: "small" }, top.map(([g, v]) => h("div", null, `${g} `, deltaSpan(v, 1)))),
        onEdit ? h("td", { style: { whiteSpace: "nowrap" } },
          h("button", { class: "sm ghost", type: "button", onclick: () => onEdit(r) }, "Edit"),
          h("button", { class: "sm ghost danger", type: "button", onclick: () => onDelete(r) }, "Delete")) : null);
    }))));
}

// =====================================================================
// Practice: pick a problem, run the timer, log the result
// =====================================================================
async function renderPractice(params) {
  await loadProblems();
  if (params.get("id")) session.start(+params.get("id"), params.get("source") || "self", params.get("blind") === "1");
  const root = h("div", { class: "stack" });
  const sess = session.get();
  const p = sess && cache.byId.get(sess.problemId);

  // ---- picker ----
  const list = h("div", { class: "picker-list", hidden: true });
  const input = h("input", { type: "search", placeholder: "Search by number or title, e.g. 200 or islands", style: { width: "100%" },
    "aria-label": "Search problems" });
  input.addEventListener("input", () => {
    const q = input.value.trim().toLowerCase();
    if (!q) { list.hidden = true; return; }
    const isNum = /^\d+$/.test(q);
    const hits = [];
    for (const pr of cache.problems) {
      if (isNum ? String(pr.id).startsWith(q) : pr.title.toLowerCase().includes(q)) hits.push(pr);
      if (hits.length >= 40) break;
    }
    hits.sort((a, b) => (isNum ? (String(a.id) === q ? -1 : String(b.id) === q ? 1 : a.id - b.id)
      : ((b.lists.length - a.lists.length) || ((b.likes || 0) - (a.likes || 0)))));
    list.replaceChildren(...hits.slice(0, 12).map((pr) => h("button", { type: "button", onclick: () => {
      session.set({ problemId: pr.id, source: "self", blind: false, accMs: 0, running: false, startedAt: null });
      router();
    } }, h("span", null, `${pr.id}. ${pr.title}`, pr.paid ? " 🔒" : ""), h("span", { class: `diff ${pr.difficulty}` }, pr.difficulty))));
    if (!hits.length) list.replaceChildren(h("div", { class: "empty" }, "No match"));
    list.hidden = false;
  });
  input.addEventListener("keydown", (e) => { if (e.key === "Escape") list.hidden = true; });

  root.append(h("section", { class: "card" },
    h("div", { class: "card-head" }, h("h2", null, "Practice"),
      h("span", { class: "sub" }, "Pick a suggestion from the dashboard, or choose your own")),
    h("div", { class: "picker" }, input, list)));

  root.addEventListener("click", (e) => { if (!list.contains(e.target) && e.target !== input) list.hidden = true; });

  if (!p) {
    root.append(h("section", { class: "card" }, h("div", { class: "empty" },
      "No problem selected. Search above, or ", h("a", { href: "#/" }, "take one of today's suggestions"), ".")));
    return root;
  }

  // ---- problem card ----
  const detail = await api(`/api/problems/${p.id}`);
  const dp = detail.problem;
  let revealed = !sess.blind;
  const tagsBox = h("div", { class: "row" });
  const drawTags = () => tagsBox.replaceChildren(...(revealed
    ? [...dp.groups.map((g) => h("span", { class: "chip" }, g)),
      ...dp.tags.filter((t) => !dp.groups.includes(t)).map((t) => h("span", { class: "chip muted" }, t))]
    : [h("span", { class: "small muted" }, "Topics hidden (mock mode): identify the pattern yourself. "),
      h("button", { class: "sm", type: "button", onclick: () => { revealed = true; drawTags(); } }, "Reveal")]));
  drawTags();
  const probCard = h("section", { class: "card" },
    h("div", { class: "row", style: { marginBottom: "6px" } },
      sess.source && sess.source !== "self" ? h("span", { class: `kind ${sess.source === "suggested" ? "focus" : sess.source}` }, sess.source === "suggested" ? "focus" : sess.source) : null,
      h("span", { class: `diff ${dp.difficulty}` }, dp.difficulty),
      h("span", { class: "chip num" }, `${dp.ratingSource === "contest" ? "" : "~"}${dp.rating} rating`),
      dp.paid ? h("span", { class: "chip" }, "🔒 premium") : null,
      dp.lists.map((l) => h("span", { class: "chip" }, l === "neetcode150" ? "NeetCode 150" : l === "blind75" ? "Blind 75" : l))),
    h("h1", null, `${dp.id}. ${dp.title}`),
    h("div", { class: "row", style: { margin: "10px 0" } },
      h("a", { class: "btn primary", href: dp.url, target: "_blank", rel: "noopener", onclick: () => session.run() }, "Open on LeetCode & start timer ↗"),
      h("button", { type: "button", onclick: () => { session.clear(); router(); } }, "Clear")),
    tagsBox,
    h("p", { class: "small ink2", style: { margin: "10px 0 0" } },
      `Model expects a score of ${fmt.pct(dp.expected)} for you here. `,
      `Time limit ${dp.timeLimit} min (${dp.difficulty}).`,
      detail.attempts.length ? ` You've attempted this ${detail.attempts.length}× before; repeats count at 60% weight.` : ""));

  // ---- timer ----
  const limitMs = dp.timeLimit * 60000;
  const disp = h("div", { id: "timer-display", class: "timer num" }, "00:00");
  const bar = h("div", { class: "timer-bar" }, h("span"));
  const runBtn = h("button", { class: "primary", type: "button" });
  const resetBtn = h("button", { type: "button", onclick: () => { if (confirm("Reset the timer?")) { session.reset(); tick(); } } }, "Reset");
  const status = h("div", { class: "small muted", style: { textAlign: "center", marginTop: "8px" } });
  const tick = () => {
    const sNow = session.get();
    const ms = session.elapsed(sNow);
    disp.textContent = fmt.clock(ms);
    const over = ms > limitMs;
    disp.classList.toggle("over", over);
    bar.classList.toggle("over", over);
    bar.firstChild.style.width = `${Math.min(100, (ms / limitMs) * 100)}%`;
    runBtn.textContent = sNow && sNow.running ? "Pause" : ms ? "Resume" : "Start";
    status.textContent = over ? `Over the ${dp.timeLimit}-minute limit by ${fmt.clock(ms - limitMs)}. Keep going or log it.`
      : `${fmt.clock(limitMs - ms)} left of ${dp.timeLimit} min`;
  };
  runBtn.addEventListener("click", () => { const c = session.get(); if (c && c.running) session.pause(); else session.run(); tick(); });
  disp.addEventListener("tick", tick);
  const timerCard = h("section", { class: "card" },
    h("div", { class: "card-head" }, h("h2", null, "Timer"), h("span", { class: "sub" }, "keeps running if you leave this page")),
    disp, bar, h("div", { class: "row", style: { justifyContent: "center" } }, runBtn, resetBtn), status);
  tick();

  // ---- log form ----
  const outcomes = [
    ["solved", "Solved on my own", "Accepted, no hints or solutions"],
    ["hint", "Solved with a hint", "Peeked at a hint / topic / discussion"],
    ["solution", "Needed the solution", "Read the editorial, then implemented it"],
    ["failed", "Could not solve", "Ran out of time or gave up"],
  ];
  const seg = h("div", { class: "seg", role: "radiogroup", "aria-label": "Outcome" }, outcomes.map(([v, label, sub], i) =>
    h("label", null, h("input", { type: "radio", name: "outcome", value: v, checked: i === 0 }), h("b", null, label), h("small", null, sub))));
  const minutes = h("input", { type: "number", min: 0, step: 0.5, required: true, style: { width: "110px" }, "aria-label": "Minutes" });
  const useTimer = () => { const ms = session.elapsed(); if (ms) minutes.value = (Math.round(ms / 6000) / 10).toFixed(1); };
  useTimer();
  const wrong = h("input", { type: "number", min: 0, max: 100, step: 1, value: 0, style: { width: "80px" } });
  const when = h("input", { type: "datetime-local", value: localInputNow() });
  const notes = h("textarea", { placeholder: "What tripped you up? Which pattern was it? (optional)" });
  const feedback = h("div");
  const form = h("form", { class: "stack", style: { gap: "12px" } },
    seg,
    h("div", { class: "row", style: { gap: "16px", alignItems: "flex-end" } },
      h("label", { class: "field" }, "Minutes taken", h("div", { class: "row" }, minutes,
        h("button", { class: "sm", type: "button", onclick: useTimer, title: "Fill from the timer" }, "⏱ from timer"))),
      h("label", { class: "field" }, "Wrong submissions", wrong),
      h("label", { class: "field" }, "When", when)),
    h("label", { class: "field" }, "Notes", notes),
    h("div", { class: "row" }, h("button", { class: "primary", type: "submit" }, "Log attempt"),
      h("span", { class: "small muted" }, "Be honest. The model only works if the log is truthful.")),
    feedback);
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    if (minutes.value === "") { minutes.focus(); toast("Enter the minutes taken"); return; }
    const outcome = form.querySelector("input[name=outcome]:checked").value;
    try {
      const res = await api("/api/attempts", { method: "POST", body: {
        problemId: dp.id, outcome, minutes: +minutes.value, wrong: +wrong.value || 0, notes: notes.value,
        ts: when.value || undefined, source: sess.source || "self", limit: dp.timeLimit,
      } });
      session.clear();
      invalidate();
      form.querySelector("button[type=submit]").disabled = true;
      feedback.replaceChildren(feedbackPanel(res.feedback));
      toast("Attempt logged");
    } catch (err) { toast(`Could not log: ${err.message}`); }
  });
  const logCard = h("section", { class: "card" }, h("div", { class: "card-head" }, h("h2", null, "Log the result")), form);

  root.append(h("div", { class: "grid g-2" }, h("div", { class: "stack" }, probCard, timerCard), logCard));
  if (detail.attempts.length) {
    root.append(h("section", { class: "card" }, h("div", { class: "card-head" }, h("h2", null, "Your previous attempts on this problem")),
      attemptsTable(detail.attempts, { compact: true })));
  }
  return root;
}

function feedbackPanel(fb) {
  if (!fb) return h("div");
  const deltas = Object.entries(fb.groupDeltas).sort((a, b) => Math.abs(b[1]) - Math.abs(a[1]));
  const better = fb.score >= fb.expected;
  return h("div", { class: "feedback stack", style: { gap: "6px" } },
    h("div", null, h("b", null, `Score ${fb.score.toFixed(2)}`), ` vs expected ${fb.expected.toFixed(2)}: `,
      better ? "better than the model predicted, so ratings go up." : "below what the model predicted, so ratings go down."),
    h("div", null, "Overall ", deltaSpan(fb.overallDelta, 1), ` → ${Math.round(fb.overallAfter)} ±${Math.round(fb.overallRdAfter)}`),
    deltas.length ? h("div", { class: "small" }, deltas.map(([g, v]) => h("span", { class: "chip", style: { marginRight: "4px" } }, `${g} `, deltaSpan(v, 1)))) : null,
    h("div", { class: "row", style: { marginTop: "6px" } },
      h("a", { class: "btn primary sm", href: "#/" }, "Back to today's plan"),
      h("a", { class: "btn sm", href: "#/practice", onclick: () => setTimeout(router, 0) }, "Log another")));
}

// =====================================================================
// Topics
// =====================================================================
async function renderTopics(params) {
  const d = await api("/api/dashboard");
  const focus = params.get("focus");
  const root = h("div", { class: "stack" },
    h("div", { class: "card" }, h("h1", null, "Topics"),
      h("p", { class: "ink2", style: { margin: "6px 0 0" } },
        "Ratings per interview topic, built from LeetCode's tags. Each logged attempt updates every topic the problem belongs to, ",
        "weighted by how specific the tag is (\"Topological Sort\" says more about a problem than \"Array\"). ",
        "± is the rating deviation: big means the model hasn't seen enough of that topic yet.")));
  const groups = d.groups.slice().sort((a, b) => (b.importance - a.importance) || (a.r - b.r));
  const grid = h("div", { class: "grid g-3" });
  for (const g of groups) {
    const med = g.readiness.Medium, sev = severity(med);
    const card = h("section", { class: "card topic-card", id: `t-${g.group}` },
      h("div", { class: "card-head" }, h("h2", null, g.group),
        h("span", { class: "chip" }, g.importance >= 0.9 ? "core" : g.importance >= 0.7 ? "common" : g.importance >= 0.5 ? "occasional" : "rare")),
      h("div", { class: "row", style: { alignItems: "baseline" } },
        h("span", { class: "num", style: { fontSize: "28px", fontWeight: 650 } }, g.rated ? fmt.r(g.r) : "–"),
        h("span", { class: "muted num" }, g.rated ? `±${Math.round(g.rd)}` : "not practised"),
        h("span", { class: "spacer" }),
        h("span", { class: "small muted" }, `${g.attempts} attempt${g.attempts === 1 ? "" : "s"}`)),
      h("div", { class: "meter-row", style: { gridTemplateColumns: "52px 1fr 116px", margin: "8px 0" } },
        h("span", { class: "small ink2" }, "Medium"),
        h("div", { class: "meter" }, h("span", { style: { width: `${med * 100}%`, background: sev.color } }), h("span", { class: "mark", style: { left: "70%" } })),
        h("span", { class: "status num" }, h("i", { style: { background: sev.color } }), `${fmt.pct(med)} · ${sev.label}`)),
      g.tags.length ? h("div", null, g.tags.slice(0, 8).map((t) => h("div", { class: "tagrow" },
        h("span", { class: "ink2" }, t.tag), h("span", { class: "num r" }, `${Math.round(t.r)}`), h("span", { class: "num muted" }, `±${Math.round(t.rd)}`)))) : null,
      h("div", { class: "row", style: { marginTop: "10px" } },
        h("a", { class: "btn sm", href: `#/bank?group=${encodeURIComponent(g.group)}&sort=fit&status=unseen` }, "Best-fit problems →")));
    if (focus === g.group) card.style.boxShadow = "0 0 0 2px var(--accent)";
    grid.append(card);
  }
  root.append(grid);
  if (focus) requestAnimationFrame(() => { const el = document.getElementById(`t-${focus}`); if (el) el.scrollIntoView({ block: "center" }); });
  return root;
}

// =====================================================================
// Problem bank
// =====================================================================
async function renderBank(params) {
  await loadProblems();
  const st = {
    q: params.get("q") || "", diff: params.get("diff") || "", group: params.get("group") || "",
    list: params.get("list") || "", status: params.get("status") || "", premium: params.get("premium") === "1",
    sort: params.get("sort") || "id", page: +(params.get("page") || 1),
  };
  const root = h("div", { class: "stack" });
  const sel = (key, opts, label) => {
    const el = h("select", { "aria-label": label }, opts.map(([v, t]) => h("option", { value: v, selected: st[key] === v }, t)));
    el.addEventListener("change", () => { st[key] = el.value; st.page = 1; draw(); });
    return el;
  };
  const search = h("input", { type: "search", placeholder: "Search number or title", value: st.q });
  let qt;
  search.addEventListener("input", () => { clearTimeout(qt); qt = setTimeout(() => { st.q = search.value; st.page = 1; draw(); }, 150); });
  const prem = h("input", { type: "checkbox", checked: st.premium });
  prem.addEventListener("change", () => { st.premium = prem.checked; st.page = 1; draw(); });
  const filters = h("div", { class: "filters" }, search,
    sel("diff", [["", "All difficulties"], ["Easy", "Easy"], ["Medium", "Medium"], ["Hard", "Hard"]], "Difficulty"),
    sel("group", [["", "All topics"], ...cache.groups.map((g) => [g, g])], "Topic"),
    sel("list", [["", "All problems"], ["neetcode150", "NeetCode 150"], ["blind75", "Blind 75"]], "List"),
    sel("status", [["", "Any status"], ["unseen", "Not attempted"], ["attempted", "Attempted"], ["review", "In review queue"], ["clean", "Solved clean"]], "Status"),
    sel("sort", [["id", "Sort: number"], ["fit", "Sort: best fit for me"], ["rating", "Sort: easiest first"], ["-rating", "Sort: hardest first"], ["likes", "Sort: most popular"]], "Sort"),
    h("label", { class: "row small ink2", style: { gap: "4px" } }, prem, "Include premium"));
  const tableBox = h("div");
  const card = h("section", { class: "card" },
    h("div", { class: "card-head" }, h("h1", null, "Problem bank"),
      h("span", { class: "sub" }, `${cache.problems.length.toLocaleString()} algorithm problems`)),
    filters, tableBox);
  root.append(card);

  function draw() {
    const q = st.q.trim().toLowerCase();
    let rows = cache.problems.filter((p) => {
      if (!st.premium && p.paid) return false;
      if (st.diff && p.difficulty !== st.diff) return false;
      if (st.group && !p.groups.includes(st.group)) return false;
      if (st.list && !p.lists.includes(st.list)) return false;
      if (st.status === "unseen" && p.status) return false;
      if (st.status === "attempted" && !p.status) return false;
      if (st.status === "review" && !(p.status && p.status.reviewDue)) return false;
      if (st.status === "clean" && !(p.status && p.status.best >= 0.78)) return false;
      if (q && !(/^\d+$/.test(q) ? String(p.id).startsWith(q) : p.title.toLowerCase().includes(q))) return false;
      return true;
    });
    const sorters = {
      id: (a, b) => a.id - b.id,
      rating: (a, b) => a.rating - b.rating,
      "-rating": (a, b) => b.rating - a.rating,
      likes: (a, b) => (b.likes || 0) - (a.likes || 0),
      fit: (a, b) => (Math.abs(a.expected - 0.6) - Math.abs(b.expected - 0.6)) || (b.lists.length - a.lists.length) || ((b.likes || 0) - (a.likes || 0)),
    };
    if (st.status === "review") rows.sort((a, b) => a.status.reviewDue.localeCompare(b.status.reviewDue));
    else rows.sort(sorters[st.sort] || sorters.id);
    const per = 50, pages = Math.max(1, Math.ceil(rows.length / per));
    st.page = Math.min(st.page, pages);
    const slice = rows.slice((st.page - 1) * per, st.page * per);
    const qs = new URLSearchParams(Object.entries(st).filter(([, v]) => v && v !== "id" && !(v === 1)).map(([k, v]) => [k, v === true ? "1" : String(v)]));
    history.replaceState(null, "", `#/bank${qs.toString() ? "?" + qs : ""}`);
    tableBox.replaceChildren(
      h("div", { class: "small muted", style: { marginBottom: "6px" } }, `${rows.length.toLocaleString()} matching`),
      h("div", { class: "table-wrap" }, h("table", null,
        h("thead", null, h("tr", null, h("th", { class: "r" }, "#"), h("th", null, "Title"), h("th", null, "Difficulty"),
          h("th", { class: "r", title: "~ = estimated from acceptance rate; otherwise contest-derived" }, "Rating"),
          h("th", null, "Topics"), h("th", { class: "r" }, "Accept"), h("th", { class: "r", title: "Model's expected score for you" }, "Exp"),
          h("th", { class: "r" }, "Your best"), h("th", null, ""))),
        h("tbody", null, slice.map((p) => h("tr", null,
          h("td", { class: "r num muted" }, p.id),
          h("td", { class: "title-cell" }, h("a", { href: p.url, target: "_blank", rel: "noopener" }, p.title), p.paid ? " 🔒" : "",
            p.lists.includes("neetcode150") ? h("span", { class: "chip", style: { marginLeft: "6px" } }, "NC150") : null),
          h("td", null, h("span", { class: `diff ${p.difficulty}` }, p.difficulty)),
          h("td", { class: "r num" }, `${p.ratingSource === "contest" ? "" : "~"}${p.rating}`),
          h("td", null, p.groups.slice(0, 2).map((g) => h("span", { class: "chip", style: { marginRight: "4px" } }, g))),
          h("td", { class: "r num" }, p.acRate ? `${Math.round(p.acRate)}%` : "–"),
          h("td", { class: "r num" }, fmt.pct(p.expected)),
          h("td", { class: "r num" }, p.status ? h("span", { title: `${p.status.n} attempt(s)${p.status.reviewDue ? " · review due " + fmt.date(p.status.reviewDue) : ""}` },
            p.status.best.toFixed(2), p.status.reviewDue ? " ↻" : "") : "–"),
          h("td", null, h("button", { class: "sm", type: "button", onclick: practiceLink(p) }, "Practice"))))))),
      h("div", { class: "pager" },
        h("button", { class: "sm", type: "button", disabled: st.page <= 1, onclick: () => { st.page--; draw(); } }, "← Prev"),
        h("span", { class: "small muted num" }, `Page ${st.page} / ${pages}`),
        h("button", { class: "sm", type: "button", disabled: st.page >= pages, onclick: () => { st.page++; draw(); } }, "Next →")));
  }
  draw();
  return root;
}

// =====================================================================
// History
// =====================================================================
async function renderHistory() {
  const d = await api("/api/attempts");
  const root = h("div", { class: "stack" });
  const editor = h("div");
  const onDelete = async (r) => {
    if (!confirm(`Delete this attempt on "${r.problem.title}"? Ratings are recomputed from the remaining log.`)) return;
    await api(`/api/attempts/${r.id}`, { method: "DELETE" });
    invalidate(); toast("Deleted"); router();
  };
  const onEdit = (r) => {
    const outcome = h("select", null, Object.entries(d.outcomes).map(([k, v]) => h("option", { value: k, selected: r.outcome === k }, v)));
    const minutes = h("input", { type: "number", min: 0, step: 0.5, value: r.minutes, style: { width: "100px" } });
    const limit = h("input", { type: "number", min: 1, step: 1, value: r.limit || "", style: { width: "90px" } });
    const wrong = h("input", { type: "number", min: 0, step: 1, value: r.wrong || 0, style: { width: "80px" } });
    const when = h("input", { type: "datetime-local", value: localInputFrom(r.ts) });
    const notes = h("textarea", null);
    notes.value = r.notes || "";
    editor.replaceChildren(h("section", { class: "card" },
      h("div", { class: "card-head" }, h("h2", null, `Edit: ${r.problem.id}. ${r.problem.title}`)),
      h("div", { class: "row", style: { gap: "12px", alignItems: "flex-end" } },
        h("label", { class: "field" }, "Outcome", outcome), h("label", { class: "field" }, "Minutes", minutes),
        h("label", { class: "field" }, "Limit", limit), h("label", { class: "field" }, "Wrong", wrong),
        h("label", { class: "field" }, "When", when)),
      h("label", { class: "field", style: { marginTop: "10px" } }, "Notes", notes),
      h("div", { class: "row", style: { marginTop: "10px" } },
        h("button", { class: "primary", type: "button", onclick: async () => {
          try {
            await api(`/api/attempts/${r.id}`, { method: "PUT", body: { outcome: outcome.value, minutes: +minutes.value,
              limit: limit.value ? +limit.value : null, wrong: +wrong.value || 0, notes: notes.value, ts: when.value } });
            invalidate(); toast("Saved"); router();
          } catch (e) { toast(e.message); }
        } }, "Save"),
        h("button", { type: "button", onclick: () => editor.replaceChildren() }, "Cancel"))));
    window.scrollTo({ top: 0, behavior: "smooth" });
  };
  root.append(editor, h("section", { class: "card" },
    h("div", { class: "card-head" }, h("h1", null, "History"), h("span", { class: "sub" }, `${d.attempts.length} attempts`)),
    attemptsTable(d.attempts, { onEdit, onDelete })));
  return root;
}

// =====================================================================
// Settings
// =====================================================================
async function renderSettings() {
  const [st, dash] = await Promise.all([api("/api/settings"), api("/api/dashboard")]);
  const lim = {};
  const limInputs = ["Easy", "Medium", "Hard"].map((dname) => {
    lim[dname] = h("input", { type: "number", min: 1, max: 240, value: st.timeLimits[dname], style: { width: "90px" } });
    return h("label", { class: "field" }, `${dname} limit (min)`, lim[dname]);
  });
  const premium = h("input", { type: "checkbox", checked: st.includePremium });
  const start = h("input", { type: "number", min: 800, max: 3000, step: 50, value: st.startRating, style: { width: "100px" } });
  const goal = h("input", { type: "number", min: 1, max: 20, value: st.dailyGoal, style: { width: "80px" } });
  const save = async () => {
    await api("/api/settings", { method: "PUT", body: {
      timeLimits: Object.fromEntries(Object.entries(lim).map(([k, el]) => [k, +el.value])),
      includePremium: premium.checked, startRating: +start.value, dailyGoal: +goal.value } });
    invalidate(); toast("Settings saved");
  };
  const fileIn = h("input", { type: "file", accept: "application/json", hidden: true });
  fileIn.addEventListener("change", async () => {
    const f = fileIn.files[0]; if (!f) return;
    try {
      const data = JSON.parse(await f.text());
      if (!confirm(`Replace your log with ${(data.attempts || []).length} attempts from ${f.name}?`)) return;
      const r = await api("/api/import", { method: "POST", body: data });
      invalidate(); toast(`Imported ${r.imported} attempts`);
    } catch (e) { toast(`Import failed: ${e.message}`); }
  });
  const exportJson = async () => {
    const data = await api("/api/export");
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
    const a = h("a", { href: URL.createObjectURL(blob), download: `leetcode-strength-${new Date().toISOString().slice(0, 10)}.json` });
    document.body.append(a); a.click(); a.remove();
  };
  const b = dash.bankInfo;
  return h("div", { class: "stack" },
    h("section", { class: "card" }, h("div", { class: "card-head" }, h("h1", null, "Settings")),
      h("h3", { style: { marginBottom: "8px" } }, "Time limits"),
      h("p", { class: "small muted", style: { marginTop: 0 } }, "A solve counts as on-time only within these. Limits are saved with each attempt, so changing them only affects future logs."),
      h("div", { class: "row", style: { gap: "16px" } }, limInputs),
      h("h3", { style: { margin: "18px 0 8px" } }, "Recommendations"),
      h("label", { class: "row" }, premium, "Include LeetCode Premium problems in suggestions"),
      h("div", { class: "row", style: { gap: "16px", marginTop: "12px" } },
        h("label", { class: "field" }, "Daily goal (problems)", goal),
        h("label", { class: "field" }, "Starting rating (prior)", start)),
      h("p", { class: "small muted" }, "The starting rating is only a prior; it washes out after a handful of attempts. Changing it re-scores your whole history."),
      h("button", { class: "primary", type: "button", onclick: save }, "Save settings")),
    h("section", { class: "card" }, h("div", { class: "card-head" }, h("h2", null, "Your data")),
      h("p", { class: "small ink2", style: { marginTop: 0 } }, "Your log lives in data/user/attempts.json next to the app. It's plain JSON, so you can commit it to git as a backup."),
      h("div", { class: "row" }, h("button", { type: "button", onclick: exportJson }, "Export JSON"),
        h("button", { type: "button", onclick: () => fileIn.click() }, "Import JSON…"), fileIn)),
    h("section", { class: "card" }, h("div", { class: "card-head" }, h("h2", null, "Problem bank")),
      h("p", { class: "small ink2", style: { margin: 0 } },
        `${b.count.toLocaleString()} algorithm problems · source: ${b.source || "?"} · generated ${b.generated ? fmt.dateTime(b.generated) : "?"}.`),
      h("p", { class: "small muted" }, "Refresh it (new problems, updated acceptance rates and contest ratings) with: ", h("code", null, "python3 lct.py sync"))));
}

// =====================================================================
// How it works
// =====================================================================
function renderMethod() {
  const row = (...cells) => h("tr", null, cells.map((c) => h("td", null, c)));
  return h("div", { class: "card prose" },
    h("h1", null, "How the strength model works"),
    h("p", null, "Every attempt you log is treated like a match between you and the problem, scored with a Glicko-style rating system (Elo plus uncertainty). You and every problem live on the same rating scale."),
    h("h2", null, "1. Problem difficulty"),
    h("p", null, "About 2,600 contest problems carry ratings computed from real contest results (zerotrac's dataset): a problem rated 1650 is one a 1650-rated contestant solves about half the time. The rest get a rating estimated from difficulty label and acceptance rate, using a regression fitted on the contest-rated problems, and are marked ~ in the UI. Estimated ratings carry more uncertainty, so they move your rating a bit less."),
    h("h2", null, "2. Your performance score"),
    h("table", null, h("thead", null, h("tr", null, h("th", null, "Outcome"), h("th", null, "Score"))), h("tbody", null,
      row("Solved alone, ≤ 50% of the limit", "1.00"),
      row("Solved alone, at the limit", "0.80 (linear in between)"),
      row("Solved alone, over the limit", "0.60 → 0.30 at 2× the limit"),
      row("Solved with a hint", "0.45 within limit, 0.30 over"),
      row("Needed the solution", "0.10"),
      row("Could not solve", "0.00"),
      row("Each wrong submission", "−0.04 (max 5) on solved/hint"))),
    h("p", null, "The drop from 0.80 to 0.60 at the limit is deliberate: a timed assessment gives nothing for a correct answer that lands after time is up."),
    h("h2", null, "3. Expected vs actual"),
    h("p", null, "Before scoring, the model predicts your expected score from the rating gap: E = 1 / (1 + 10^(−g·(you − problem)/400)). Each rating then moves by K·(actual − expected), where K grows with that rating's uncertainty (RD). Beat a problem rated far above you and you jump; fail one far below you and you drop; perform as expected and little changes."),
    h("h2", null, "4. Topics"),
    h("p", null, "Ratings exist at three levels: overall, ~20 interview topic groups, and every raw LeetCode tag. A problem updates each of its topics, weighted by how specific the tag is (inverse document frequency): \"Topological Sort\" gets full credit, \"Array\" (on 60% of problems) gets a small share. A topic you haven't touched starts at your overall rating with wide uncertainty."),
    h("h2", null, "5. Uncertainty and rust"),
    h("p", null, "RD (the ± number) shrinks as evidence accumulates and grows again while a topic sits idle. That way a topic you haven't practised in a month gets re-tested sooner and moves faster when you do. There's a floor so your rating keeps responding while you improve. Re-attempting a problem you've seen counts at 60% weight, since memory helps."),
    h("h2", null, "6. Readiness and target"),
    h("p", null, "Readiness is your expected score on a typical interview problem (the median NeetCode 150 rating per difficulty) under your time limit. The assessment-ready target is the rating where that expectation reaches 70% for a typical Medium. Tiers: Foundations (< 30%), Developing (30-50%), Competitive (50-70%), Assessment-ready (≥ 70%), Strong (≥ 50% on a typical Hard)."),
    h("h2", null, "7. What to practise next"),
    h("ul", null,
      h("li", null, h("b", null, "Review: "), "anything not solved cleanly comes back after 2 days (failed / needed solution) or 4 days (hint / slow). Each clean re-solve pushes it out ×2.5; it graduates after a ~3-week interval."),
      h("li", null, h("b", null, "Focus: "), "topics are ranked by need = assessment frequency × (gap below target + uncertainty), discounted if you hit them in the last 3 days. For each, the pick is an unseen problem where your expected score is about 60%, a stretch you can still finish. Curated, popular problems are preferred."),
      h("li", null, h("b", null, "Mock: "), "one typical-difficulty Medium with topic tags hidden, so you practise identifying the pattern under the clock like on test day.")),
    h("p", null, "The full log is replayed from scratch on every page load, so editing or deleting an attempt, or changing a setting, always gives consistent results."));
}

// boot
loadProblems().catch(() => null).finally(updateTimerChip);
router();
