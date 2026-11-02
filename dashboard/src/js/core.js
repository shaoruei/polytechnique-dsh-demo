// core.js: data, formatting, the guarded chart() wrapper, shared dedicated assumptions and the page router.
// Each page lives in its own file and registers PAGES.<id> = { html, init(), draw() }.
/* global Chart */
const D = window.DEMO_DATA;
const SWE = D.swe; // 9 SWE-bench runs, DeepSeek-V4-Flash on Token Factory Public (exported JSON)
const BENCH = D.bench; // API load test of the same model, public endpoint (exported JSON)
const PR = SWE.pricing; // verified public list price, $ per 1M tokens
const LIMITS = PR.rate_limits; // verified account limits
const $ = (id) => document.getElementById(id);

// ------------------------------------------------------------------ formatting
const usd = (x, digits) => {
  if (x === null || x === undefined || !Number.isFinite(x)) return '–';
  const d = digits ?? (Math.abs(x) >= 1000 ? 0 : Math.abs(x) >= 10 ? 1 : Math.abs(x) >= 0.1 ? 2 : Math.abs(x) >= 0.001 ? 4 : 6);
  return '$' + x.toLocaleString('en-US', { minimumFractionDigits: d, maximumFractionDigits: d });
};
const num = (x, d = 0) => (x === null || x === undefined || !Number.isFinite(x) ? '–' : x.toLocaleString('en-US', { maximumFractionDigits: d, minimumFractionDigits: d }));
const big = (x) => {
  if (!Number.isFinite(x)) return '–';
  const a = Math.abs(x);
  if (a >= 1e9) return num(x / 1e9, 1) + 'B';
  if (a >= 1e6) return num(x / 1e6, a >= 1e7 ? 0 : 1) + 'M';
  if (a >= 1e4) return num(x / 1e3, 0) + 'k';
  if (a >= 1e3) return num(x / 1e3, 1) + 'k';
  return num(x, 0);
};
const pct = (x, d = 0) => (Number.isFinite(x) ? num(x * 100, d) + '%' : '–');
const secs = (s) => (!Number.isFinite(s) ? '–' : s < 60 ? num(s, s < 10 ? 1 : 0) + ' s' : s < 3600 ? num(s / 60, 1) + ' min' : num(s / 3600, 1) + ' h');
const esc = (s) => String(s ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const ev = (kind, label) => `<span class="ev ev-${kind}">${label ?? kind[0].toUpperCase() + kind.slice(1)}</span>`;
const mean = (a) => (a.length ? a.reduce((s, x) => s + x, 0) / a.length : NaN);
const median = (a) => {
  if (!a.length) return NaN;
  const s = [...a].sort((x, y) => x - y);
  const m = Math.floor(s.length / 2);
  return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2;
};
const sum = (a) => a.reduce((x, y) => x + y, 0);
const pctl = (arr, q) => {
  const a = arr.filter(Number.isFinite).sort((x, y) => x - y);
  const i = (a.length - 1) * q;
  return a[Math.floor(i)] + (a[Math.ceil(i)] - a[Math.floor(i)]) * (i - Math.floor(i));
};
const tile = (label, value, detail, evKind) =>
  `<div class="tile"><span class="label">${label}${evKind ? ' ' + ev(evKind) : ''}</span><span class="value">${value}</span><span class="detail">${detail}</span></div>`;

// ------------------------------------------------------------------ SWE-bench helpers
const SWE_RUN = (id) => SWE.runs.find((x) => x.run_id === id);
const reqsOf = (r) => SWE.requests.filter((q) => q.run === r.run_id);
const shortIssue = (iid) => iid.replace('django__django-', '');
const hhmm = (iso) => iso.slice(11, 16);
let currentRun = SWE.runs.find((r) => r.label === 'A1');
function selectRun(id) {
  currentRun = SWE_RUN(id);
  dirty.add('measure');
}
function runOptions() {
  return Object.keys(SWE.instances).map((iid) => `<optgroup label="Issue ${SWE.instances[iid].alias.slice(-1).toUpperCase()} · django-${shortIssue(iid)}">${
    SWE.runs.filter((r) => r.instance_id === iid).sort((a, b) => a.trial - b.trial)
      .map((r) => `<option value="${r.run_id}">${r.label} · ${r.official.resolved ? 'resolved' : 'not resolved'} · ${secs(r.wall_time_s)}</option>`).join('')}</optgroup>`).join('');
}
const tokensPerTask = mean(SWE.runs.map((r) => r.metrics.prompt_tokens + r.metrics.output_tokens)); // all count towards tokens/min
const costPerTask = mean(SWE.runs.map((r) => r.metrics.cost_usd));
const publicTasksPerHour = () => Math.min(LIMITS.tokens_per_minute / tokensPerTask, LIMITS.requests_per_minute / mean(SWE.runs.map((r) => r.metrics.llm_requests))) * 60;

// ------------------------------------------------------------------ dedicated: assumptions only (never measured)
// The DeepSeek dedicated endpoint never became ready, so every dedicated number is a labelled, adjustable assumption.
// The dedicated configuration from the Token Factory console. The price is the console's estimate, not an invoice.
const DEDICATED = { hardware: '2× NVIDIA B200, 1 replica', region: 'us-central1', quantization: 'FP8', gpuHour: 8.7, replicaHour: 17.4 };
// Performance scenarios for that same replica (same hardware, same price). Inputs, not measurements.
// Public reference (measured, agent-sized request ~10k in / 512 out, alone): ~200 tok/s, TTFT ~1.2 s.
const SCENARIOS = {
  conservative: { label: 'Conservative', reqSpeed: 120, ttft: 1.5, reqPerReplica: 10 },
  baseline: { label: 'Baseline', reqSpeed: 200, ttft: 1.0, reqPerReplica: 20 },
  optimistic: { label: 'Optimistic', reqSpeed: 300, ttft: 0.6, reqPerReplica: 40 },
};
const ASSUME = { scenario: 'baseline', ...SCENARIOS.baseline };
// dedicated agent-step latency (s) for a request of `out` output tokens with c requests running at once
const dedicatedSpeed = (c) => ASSUME.reqSpeed * Math.min(1, ASSUME.reqPerReplica / c);
const dedicatedLatency = (c, out = 512) => ASSUME.ttft + out / dedicatedSpeed(c);
// capacity of the single replica in SWE-bench tasks per hour: an agent spends this share of its time in an LLM request
const llmShare = mean(SWE.runs.map((r) => r.metrics.llm_time_s / r.wall_time_s));
const meanTaskSeconds = mean(SWE.runs.map((r) => r.wall_time_s));
const dedicatedAgents = () => ASSUME.reqPerReplica / llmShare; // agents working at once that keep it at its rated load
const dedicatedTasksPerHour = () => (dedicatedAgents() * 3600) / meanTaskSeconds;
const scenarioName = () => SCENARIOS[ASSUME.scenario].label;
const replicaHour = () => DEDICATED.replicaHour;
/** Scenario selector with the scenario's values read-only, and the fixed configuration. Ids are prefixed per page. */
function scenarioControl(page) {
  return `<div class="panel controls assume" id="a-${page}"><h3>Dedicated scenario ${ev('assumption')}</h3>
    <select id="a-${page}-scenario" data-assume="scenario" aria-label="Dedicated performance scenario">${Object.entries(SCENARIOS).map(([k, v]) => `<option value="${k}">${v.label}</option>`).join('')}</select>
    <dl class="kv" data-assume-values></dl>
    <p class="hint">${DEDICATED.hardware} · ${DEDICATED.quantization} · ${DEDICATED.region}<br>${usd(DEDICATED.replicaHour, 2)} per replica-hour (${usd(DEDICATED.gpuHour, 2)}/GPU-h), console estimate, same for every scenario.</p></div>`;
}
/** Show the shared scenario in every scenario control. */
function syncAssumptions() {
  for (const el of document.querySelectorAll('[data-assume]')) el.value = ASSUME.scenario;
  for (const el of document.querySelectorAll('[data-assume-values]')) {
    el.innerHTML = `<dt>Speed per request</dt><dd>${ASSUME.reqSpeed} tok/s</dd><dt>Time to first token</dt><dd>${num(ASSUME.ttft, 1)} s</dd>
      <dt>Requests at that speed</dt><dd>${ASSUME.reqPerReplica}</dd><dt>Capacity</dt><dd>≈ ${num(dedicatedTasksPerHour())} tasks/h</dd>`;
  }
}
function bindAssumptions(page, redraw) {
  $(`a-${page}-scenario`).addEventListener('change', (e) => {
    Object.assign(ASSUME, SCENARIOS[e.target.value], { scenario: e.target.value });
    syncAssumptions();
    for (const p of Object.keys(PAGES)) dirty.add(p);
    redraw();
  });
  syncAssumptions();
}

// ------------------------------------------------------------------ theme-aware charts
const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
const charts = {};
function themeDefaults() {
  Chart.defaults.color = css('--muted');
  Chart.defaults.borderColor = css('--line');
  Chart.defaults.font.family = css('--font-body');
  Chart.defaults.font.size = 14; // projector
  Chart.defaults.plugins.legend.labels.boxWidth = 12;
  Chart.defaults.datasets.line.pointStyle = 'circle';
  Chart.defaults.maintainAspectRatio = false;
  // No animations. Assigning a partial object here (formerly { duration: 250 }) replaced Chart.js's
  // animation defaults: Animations.configure() copies only the keys of defaults.animation, so colour
  // properties lost their 'color' interpolator. The first animated colour change (hovering a bar,
  // whose hover colour differs) threw "this._fn is not a function" inside Chart.js's shared animation
  // loop, which stopped it, and every chart drawn afterwards stayed blank. Static charts also suit a
  // projector. Set globally here and again per chart in chart().
  Chart.defaults.animation = false;
}
// ------------------------------------------------------------------ diagnostics
// A chart that fails must say so on screen. A blank canvas cannot be diagnosed from a projector.
function diagText(err) {
  return `${err && err.message ? err.message : String(err)}\n${navigator.userAgent}`;
}
function reportProblem(where, err) {
  console.error(`[dashboard] ${where}:`, err);
  const box = $('diag');
  if (!box) return;
  box.hidden = false;
  const line = document.createElement('pre');
  line.textContent = `${where}: ${diagText(err)}`;
  box.append(line);
}
function chartNotice(canvas, text) {
  const host = canvas.parentElement;
  let el = host.querySelector('.chart-error');
  if (!text) {
    if (el) el.remove();
    return;
  }
  if (!el) {
    el = document.createElement('pre');
    el.className = 'chart-error';
    host.append(el);
  }
  el.textContent = text;
}
// Chart.js registers an instance on its canvas before the first update, so a constructor that
// throws can leave a partial chart behind that we never got a reference to. Destroy whatever is
// registered, otherwise every later redraw fails with "Canvas is already in use".
function releaseCanvas(id, canvas) {
  for (const inst of new Set([charts[id], Chart.getChart(canvas)])) {
    if (!inst) continue;
    try {
      inst.destroy();
    } catch (err) {
      reportProblem(`chart ${id} destroy`, err);
    }
  }
  delete charts[id];
}
function chart(id, config) {
  const canvas = $(id);
  if (config.type === 'line') {
    const lg = (((config.options ??= {}).plugins ??= {}).legend ??= {});
    lg.labels = { usePointStyle: true, pointStyle: 'line', pointStyleWidth: 28, ...(lg.labels || {}) };
  }
  releaseCanvas(id, canvas);
  chartNotice(canvas, null);
  config.options = { ...(config.options || {}), animation: false };
  try {
    charts[id] = new Chart(canvas, config);
  } catch (err) {
    releaseCanvas(id, canvas);
    chartNotice(canvas, `This chart could not be drawn.\n${diagText(err)}`);
    reportProblem(`chart ${id}`, err);
    return null;
  }
  const instance = charts[id];
  // after the first frame: a chart with no plot area or a zero-size canvas is broken; try one resize, then say so
  setTimeout(() => {
    if (charts[id] !== instance || canvas.closest('.view')?.hidden) return;
    const area = instance.chartArea;
    const ok = () => canvas.width > 0 && canvas.height > 0 && area && area.right - area.left > 0 && area.bottom - area.top > 0;
    if (ok()) return;
    try {
      instance.resize();
      instance.update('none');
    } catch (err) {
      reportProblem(`chart ${id} resize`, err);
    }
    if (!(canvas.width > 0 && canvas.height > 0 && instance.chartArea && instance.chartArea.right > instance.chartArea.left)) {
      chartNotice(canvas, `This chart has no drawing area (canvas ${canvas.width}x${canvas.height}).\n${navigator.userAgent}`);
    }
  }, 600);
  return instance;
}
function alpha(color, a) {
  const m = /^#([0-9a-f]{3}|[0-9a-f]{6})$/i.exec(String(color).trim());
  if (!m) return color;
  let h = m[1];
  if (h.length === 3) h = h.split('').map((c) => c + c).join('');
  const n = parseInt(h, 16);
  return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${a})`;
}


// ------------------------------------------------------------------ router
const PAGES = {};
const ORDER = ['run', 'measure', 'endpoints', 'economics', 'classroom'];
const inited = new Set();
const dirty = new Set();
const currentView = () => (ORDER.includes(location.hash.slice(1)) ? location.hash.slice(1) : 'run');
function show(view) {
  for (const v of ORDER) $(`view-${v}`).hidden = v !== view;
  for (const a of document.querySelectorAll('.tabs a')) {
    if (a.dataset.view === view) a.setAttribute('aria-current', 'page');
    else a.removeAttribute('aria-current');
  }
  const page = PAGES[view];
  syncAssumptions(); // keep every assumption control in step with the shared values
  try {
    if (!inited.has(view)) {
      inited.add(view);
      $(`view-${view}`).innerHTML = page.html();
      page.init?.();
      page.draw();
    } else if (dirty.has(view)) page.draw();
    dirty.delete(view);
  } catch (err) {
    reportProblem(`view ${view}`, err);
  }
}
window.addEventListener('hashchange', () => show(currentView()));

async function selfCheck() {
  const btn = $('self-check');
  const box = $('self-check-out');
  btn.disabled = true;
  const back = currentView();
  const rows = [];
  for (const v of ['measure', 'endpoints', 'economics', 'classroom']) {
    location.hash = v;
    await new Promise((r) => setTimeout(r, v === 'classroom' ? 2500 : 1200));
    for (const c of document.querySelectorAll(`#view-${v} canvas`)) {
      const inst = Chart.getChart(c);
      let painted = 'n/a';
      try {
        if (c.width && c.height) {
          const d = c.getContext('2d').getImageData(0, 0, c.width, c.height).data;
          let n = 0;
          for (let i = 3; i < d.length; i += 4) if (d[i] > 0) n++;
          painted = `${((100 * n) / (d.length / 4)).toFixed(1)}%`;
        }
      } catch (err) {
        painted = `unreadable (${err.name})`;
      }
      const area = inst && inst.chartArea ? `${Math.round(inst.chartArea.right - inst.chartArea.left)}x${Math.round(inst.chartArea.bottom - inst.chartArea.top)}` : '-';
      const note = c.parentElement.querySelector('.chart-error');
      rows.push([v, c.id, inst ? 'yes' : (c.dataset.onDemand !== undefined ? 'on demand' : 'NO'), `${c.width}x${c.height}`, area, painted, note ? note.textContent.split('\n')[0] : '']);
    }
  }
  location.hash = back;
  box.hidden = false;
  box.innerHTML = `<p class="note">${esc(navigator.userAgent)}</p><div class="table-wrap"><table><thead><tr><th>view</th><th>chart</th><th>created</th><th>canvas</th><th>plot area</th><th>painted</th><th>error</th></tr></thead><tbody>${
    rows.map((r) => `<tr>${r.map((x) => `<td>${esc(x)}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`;
  btn.disabled = false;
}


