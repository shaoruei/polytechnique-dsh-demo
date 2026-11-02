// Dashboard application (presentation build). Model functions (simulate, publicCost, ...) are bundled above.
// Data: the 9 SWE-bench runs of deepseek-ai/DeepSeek-V4-Flash-0731 on Token Factory Public (D.swe) and the
// separate API load test of the same model (D.bench). No other workload is shown.
/* global Chart */
const D = window.DEMO_DATA;
const SWE = D.swe;
const BENCH = D.bench;
const PR = SWE.pricing; // verified public list price, $/1M tokens
const LIMITS = BENCH.limits;
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
const VIEWS = ['run', 'measure', 'endpoints', 'economics', 'classroom', 'method'];
const inited = {}; // view -> controls wired and drawn once
const stale = {}; // view -> charts need redrawing (theme change)
const INIT = { run: () => renderRun(), measure: () => renderMeasure(), endpoints: () => drawEndpoints(), economics: () => renderEconomics(), classroom: () => renderClassroom(), method: () => renderMethod() };
const DRAW = { run: () => loadRun($('run-select').value), measure: () => drawMeasure(), endpoints: () => drawEndpoints(), economics: () => drawEconomics(), classroom: () => drawSim(), method: () => {} };
function currentView() {
  const v = location.hash.slice(1);
  return VIEWS.includes(v) ? v : 'run';
}
function show(view) {
  if (!VIEWS.includes(view)) view = 'run';
  for (const v of VIEWS) $(`view-${v}`).hidden = v !== view;
  for (const a of document.querySelectorAll('.tabs a')) {
    if (a.dataset.view === view) a.setAttribute('aria-current', 'page');
    else a.removeAttribute('aria-current');
  }
  try {
    if (!inited[view]) {
      inited[view] = true;
      stale[view] = false;
      INIT[view]();
    } else if (stale[view]) {
      stale[view] = false;
      DRAW[view]();
    }
  } catch (err) {
    reportProblem(`view ${view}`, err);
  }
}
window.addEventListener('hashchange', () => show(location.hash.slice(1)));


// ------------------------------------------------------------------ shared data helpers
const SWE_RUN = (id) => SWE.runs.find((x) => x.run_id === id);
const replayOf = (r) => SWE.replays[r.run_id];
const reqsOf = (r) => SWE.requests.filter((q) => q.run === r.run_id);
const shortIssue = (iid) => iid.replace('django__django-', '');
const hhmm = (iso) => iso.slice(11, 16);
const sum = (a) => a.reduce((x, y) => x + y, 0);
const pctl = (arr, q) => {
  const a = arr.filter(Number.isFinite).sort((x, y) => x - y);
  const i = (a.length - 1) * q;
  return a[Math.floor(i)] + (a[Math.ceil(i)] - a[Math.floor(i)]) * (i - Math.floor(i));
};
const scope = (sel) => `<span class="scope ${sel ? 'sel' : 'agg'}">${sel ? 'this run' : 'all 9'}</span>`;
const statTile = (label, value, agg, key = false) =>
  `<div class="tile${key ? ' key' : ''}"><span class="label">${scope(true)}${label}</span><span class="value">${value}</span><span class="agg">${scope(false)}${agg}</span></div>`;
const plainTile = (label, value, detail, evKind) =>
  `<div class="tile"><span class="label">${label}${evKind ? ' ' + ev(evKind) : ''}</span><span class="value">${value}</span><span class="detail">${detail}</span></div>`;
// SWE-bench runs in the simulator's trajectory shape (verified to replay exactly by the experiment)
const SWE_TRAJ = SWE.runs.map((r) => ({ task: r.instance_id, effort: r.effort, success: r.success, lead_s: r.trajectory.lead_s, steps: r.trajectory.steps }));
const tokensPerTask = mean(SWE.runs.map((r) => r.metrics.prompt_tokens + r.metrics.output_tokens)); // counted by the TPM limiter (cached included)
const publicTasksPerHourCap = (mult = 1) => Math.min((LIMITS.tokens_per_minute * mult) / tokensPerTask, (LIMITS.requests_per_minute * mult) / mean(SWE.runs.map((r) => r.metrics.llm_requests))) * 60;

// ==================================================================== 1. RUN AN AGENT
let replayTimer = null;
let currentRun = null;
function renderRun() {
  const sel = $('run-select');
  for (const iid of Object.keys(SWE.instances)) {
    const og = document.createElement('optgroup');
    og.label = `Issue ${SWE.instances[iid].alias.slice(-1).toUpperCase()} · django-${shortIssue(iid)}`;
    for (const r of SWE.runs.filter((x) => x.instance_id === iid).sort((a, b) => a.trial - b.trial)) {
      const o = document.createElement('option');
      o.value = r.run_id;
      o.textContent = `${r.label} · ${r.official.resolved ? 'resolved' : 'not resolved'} · ${secs(r.wall_time_s)}`;
      og.append(o);
    }
    sel.append(og);
  }
  sel.value = SWE.runs.find((r) => r.label === 'A1').run_id;
  sel.addEventListener('change', () => loadRun(sel.value));
  $('replay-play').addEventListener('click', () => playReplay());
  $('replay-all').addEventListener('click', () => drawEvents(Infinity));
  loadRun(sel.value);
}
function loadRun(runId) {
  clearInterval(replayTimer);
  const r = SWE_RUN(runId);
  currentRun = r;
  const inst = SWE.instances[r.instance_id];
  $('issue-id').textContent = `${inst.instance_id} · Django ${inst.version}`;
  $('issue-title').textContent = inst.title;
  $('issue-summary').textContent = inst.summary;
  $('run-prompt').textContent = inst.issue;
  $('run-metrics').innerHTML = [['Time', secs(r.wall_time_s)], ['LLM requests', num(r.metrics.llm_requests)], ['Cost', usd(r.metrics.cost_usd, 4)]]
    .map(([k, v]) => `<div><span>${k}</span><b>${v}</b></div>`).join('');
  $('run-result').innerHTML = r.official.resolved
    ? '<span class="pill ok">RESOLVED</span> official SWE-bench tests pass'
    : '<span class="pill bad">NOT RESOLVED</span> one hidden test still fails';
  drawEvents(Infinity);
  if (inited.measure && currentView() !== 'measure') stale.measure = true;
}
// show a bash command as the command itself rather than its JSON arguments
function callText(e) {
  try {
    const a = JSON.parse(e.text);
    if (e.name === 'bash' && a.command) return '$ ' + a.command;
    if (a.file_path || a.path || a.pattern) return [a.file_path ?? a.path, a.pattern].filter(Boolean).join('  ');
  } catch { /* truncated or not JSON: show as recorded */ }
  return e.text;
}
function eventRow(e) {
  const t = `<span class="t">${num(e.t, 1)}s</span>`;
  switch (e.k) {
    case 'step': return `<li class="step">${t}<span class="kind">request</span><span class="body">LLM request #${e.step}</span></li>`;
    case 'think': return `<li class="think">${t}<span class="kind">thinking</span><span class="body">${esc(e.text)}</span></li>`;
    case 'say': return `<li>${t}<span class="kind say">answer</span><span class="body">${esc(e.text)}</span></li>`;
    case 'call':
      if (e.edit) {
        const lines = (txt, sign) => (txt ? txt.split('\n').map((l) => sign + l).join('\n') : '');
        return `<li>${t}<span class="kind call">edit</span><span class="body edit"><code>${esc(e.edit.file)}</code><pre class="diff">${diffHtml([lines(e.edit.old, '-'), lines(e.edit.new, '+')].filter(Boolean).join('\n'))}</pre></span></li>`;
      }
      return `<li>${t}<span class="kind call">${esc(e.name)}</span><span class="body"><code>${esc(callText(e))}</code></span></li>`;
    case 'result': return `<li>${t}<span class="kind result${e.err ? ' err' : ''}">${e.err ? 'error' : 'result'}</span><span class="body"><code>${esc(e.text)}</code></span></li>`;
    case 'usage': return `<li>${t}<span class="kind">tokens</span><span class="body mono">in ${num(e.u + e.c)} (cached ${num(e.c)}) · out ${num(e.o)}</span></li>`;
    case 'end': return `<li class="step">${t}<span class="kind">done</span><span class="body">turn ended: ${esc(e.text)}</span></li>`;
    default: return '';
  }
}
function diffHtml(text) {
  return text.split('\n').map((l) => {
    const cls = l.startsWith('diff --git') || l.startsWith('+++') || l.startsWith('---') ? 'file' : l.startsWith('@@') ? 'hunk' : l.startsWith('+') ? 'add' : l.startsWith('-') ? 'del' : '';
    return cls ? `<span class="${cls}">${esc(l)}</span>` : esc(l);
  }).join('\n');
}
function laneSegments(events) {
  // step start -> assistant message (LLM) -> tool result(s) (tool) -> next step start (harness)
  const segs = [];
  let stepStart = null;
  let llmEnd = null;
  let toolEnd = null;
  const flush = (next) => {
    if (stepStart === null) return;
    const end = llmEnd ?? next;
    segs.push({ kind: 'llm', from: stepStart, to: end });
    if (toolEnd !== null) segs.push({ kind: 'tool', from: end, to: toolEnd });
    const last = toolEnd ?? end;
    if (next !== null && next > last) segs.push({ kind: 'gap', from: last, to: next });
  };
  for (const e of events) {
    if (e.k === 'step') {
      flush(e.t);
      stepStart = e.t;
      llmEnd = null;
      toolEnd = null;
    } else if (e.k === 'usage') llmEnd = e.t;
    else if (e.k === 'result') toolEnd = e.t;
    else if (e.k === 'end') {
      flush(null);
      stepStart = null;
    }
  }
  return segs;
}

function drawLane(r, upTo = Infinity) {
  const events = replayOf(r);
  const segs = laneSegments(events);
  const total = Math.max(...segs.map((s) => s.to), 0.001);
  $('lane').innerHTML = segs.map((s) =>
    `<span class="${s.kind}${s.from > upTo ? ' dim' : ''}" style="width:${((s.to - s.from) / total) * 100}%" title="${s.kind} ${num(s.to - s.from, 2)} s"></span>`).join('');
}

function drawEvents(upTo, animateFrom = Infinity) {
  const events = replayOf(currentRun);
  const shown = events.filter((e) => e.t <= upTo);
  const list = $('events');
  list.innerHTML = shown.map(eventRow).join('');
  if (Number.isFinite(animateFrom)) {
    const items = list.children;
    for (let i = animateFrom; i < items.length; i++) items[i].classList.add('enter');
    list.scrollTop = list.scrollHeight;
  }
  drawLane(currentRun, upTo);
}

function playReplay() {
  clearInterval(replayTimer);
  const events = replayOf(currentRun);
  const end = events.at(-1).t;
  const speed = Number($('replay-speed').value);
  const start = performance.now();
  let lastCount = 0;
  drawEvents(-1);
  replayTimer = setInterval(() => {
    const t = ((performance.now() - start) / 1000) * speed;
    const count = events.filter((e) => e.t <= t).length;
    if (count !== lastCount) {
      drawEvents(t, lastCount);
      lastCount = count;
    }
    if (t > end) clearInterval(replayTimer);
  }, 100);
}


// ==================================================================== 2. MEASURE IT
// "this run" = the run selected here (shared with page 1); "all 9" = across the nine runs.
const TOK = () => ({ cached: css('--tok-cached'), uncached: css('--tok-uncached'), output: css('--tok-output') });
function renderMeasure() {
  if (!inited.run) { // opened directly at #measure: the run list lives in section 1
    inited.run = true;
    renderRun();
  }
  const sel = $('m-run');
  sel.innerHTML = $('run-select').innerHTML;
  sel.value = currentRun.run_id;
  sel.addEventListener('change', () => {
    $('run-select').value = sel.value;
    loadRun(sel.value);
    drawMeasure();
  });
  drawMeasure();
}
function drawMeasure() {
  if (currentRun && $('m-run').value !== currentRun.run_id) $('m-run').value = currentRun.run_id;
  const r = SWE_RUN($('m-run').value);
  const runs = SWE.runs;
  const m = r.metrics;
  const M = (k) => runs.map((x) => x.metrics[k]);
  const tok = TOK();
  const dot = (c) => `<i class="dot" style="background:${c}"></i>`;

  // A. Task overview
  $('m-tiles-task').innerHTML = [
    statTile('Wall time', secs(r.wall_time_s), `mean ${secs(mean(runs.map((x) => x.wall_time_s)))}`),
    statTile('LLM requests', num(m.llm_requests), `mean ${num(mean(M('llm_requests')), 1)}`),
    statTile('Public cost (est.)', usd(m.cost_usd, 4), `mean ${usd(mean(M('cost_usd')), 4)} · ${usd(sum(M('cost_usd')), 3)} total`, true),
  ].join('');

  // B. Token usage & caching
  const allCost = sum(M('cost_usd'));
  const noCache = sum(M('cost_usd_without_cache_discount'));
  $('m-tiles-tokens').innerHTML = [
    statTile('Cache hit rate', pct(m.cache_hit_rate, 1) + `<small>${dot(tok.cached)}${big(m.cached_input_tokens)} cached · ${dot(tok.uncached)}${big(m.uncached_input_tokens)} uncached · ${dot(tok.output)}${big(m.output_tokens)} output</small>`,
      pct(sum(M('cached_input_tokens')) / sum(M('prompt_tokens')), 1)),
    `<div class="tile key"><span class="label">${scope(false)}Caching saved</span><span class="value">${pct(1 - allCost / noCache)}</span><span class="detail">${usd(allCost, 3)} instead of ${usd(noCache, 3)} for all 9 runs</span></div>`,
  ].join('');
  const dollars = runs.map((x) => ({
    c: (x.metrics.cached_input_tokens * PR.cached_input_per_mtok) / 1e6,
    u: (x.metrics.uncached_input_tokens * PR.input_per_mtok) / 1e6,
    o: (x.metrics.output_tokens * PR.output_per_mtok) / 1e6,
  }));
  const isSel = (x) => x.run_id === r.run_id;
  const edge = runs.map((x) => (isSel(x) ? 2.5 : 0));
  chart('c-costsplit', {
    type: 'bar',
    data: {
      labels: runs.map((x) => (isSel(x) ? '▶ ' : '') + x.label),
      datasets: [
        { label: `Cached input ($${PR.cached_input_per_mtok}/M)`, data: dollars.map((d) => d.c), backgroundColor: tok.cached, borderColor: css('--fg'), borderWidth: edge, tokens: M('cached_input_tokens') },
        { label: `Uncached input ($${PR.input_per_mtok}/M)`, data: dollars.map((d) => d.u), backgroundColor: tok.uncached, borderColor: css('--fg'), borderWidth: edge, tokens: M('uncached_input_tokens') },
        { label: `Output ($${PR.output_per_mtok}/M)`, data: dollars.map((d) => d.o), backgroundColor: tok.output, borderColor: css('--fg'), borderWidth: edge, tokens: M('output_tokens') },
      ],
    },
    options: {
      scales: { x: { stacked: true }, y: { stacked: true, title: { display: true, text: 'USD per run' }, ticks: { callback: (v) => '$' + v.toFixed(3) } } },
      plugins: { tooltip: { callbacks: { label: (c) => `${c.dataset.label}: ${usd(c.raw, 4)} · ${big(c.dataset.tokens[c.dataIndex])} tokens` } } },
    },
  });

  // C. Latency & generation speed: one line through the nine per-run medians, in run order
  const series = css('--series');
  const highLoad = runs.map((x) => x.load_peak_rpm >= LIMITS.requests_per_minute);
  const band = highLoad.reduce((acc, on, i) => (on ? [acc[0] ?? i, i] : acc), []);
  chart('c-decode-time', {
    type: 'line',
    data: {
      labels: runs.map((x) => x.label),
      datasets: [{
        label: 'median decode speed of the run',
        data: M('decode_tps_p50'),
        borderColor: series, backgroundColor: series, borderWidth: 4, tension: 0,
        pointRadius: runs.map((x) => (isSel(x) ? 9 : 6)), pointBorderWidth: runs.map((x) => (isSel(x) ? 3 : 0)), pointBorderColor: css('--fg'),
        pointHoverRadius: 10,
      }],
    },
    options: {
      layout: { padding: { top: 28 } },
      scales: {
        y: { min: 0, suggestedMax: 450, title: { display: true, text: 'tokens / second' }, ticks: { font: { size: 15 } } },
        x: { offset: true, title: { display: true, text: 'runs in the order they ran (A, B, C = the three issues)' }, ticks: { font: { size: 16, weight: '600' } } },
      },
      plugins: {
        legend: { display: false },
        tooltip: { callbacks: {
          title: (c) => { const x = runs[c[0].dataIndex]; return `${x.label} · django-${shortIssue(x.instance_id)} · started ${hhmm(x.metrics.turn_started_at_utc)} UTC`; },
          label: (c) => { const x = runs[c.dataIndex].metrics; return [`decode median ${num(x.decode_tps_p50, 1)} tok/s`, `TTFT median ${num(x.ttft_s_p50, 2)} s`, `stalls ${num(x.stream_stall_s, 1)} s`]; },
        } },
      },
    },
    plugins: [
      { id: 'pointValues', afterDatasetsDraw(ch) {
        const { ctx } = ch;
        ctx.save();
        ctx.fillStyle = css('--fg');
        ctx.font = `600 15px ${css('--font-body')}`;
        ctx.textAlign = 'center';
        ch.getDatasetMeta(0).data.forEach((p, i) => ctx.fillText(num(ch.data.datasets[0].data[i]), p.x, p.y - 14));
        ctx.restore();
      } },
      { id: 'loadBand', beforeDatasetsDraw(ch) {
        if (band.length !== 2) return;
        const { ctx, chartArea, scales } = ch;
        const step = scales.x.getPixelForValue(1) - scales.x.getPixelForValue(0);
        const x0 = scales.x.getPixelForValue(band[0]) - step / 2;
        const x1 = scales.x.getPixelForValue(band[1]) + step / 2;
        ctx.save();
        ctx.fillStyle = alpha(css('--muted'), 0.12);
        ctx.fillRect(x0, chartArea.top, x1 - x0, chartArea.bottom - chartArea.top);
        ctx.fillStyle = css('--muted');
        ctx.font = `13px ${css('--font-body')}`;
        ctx.textAlign = 'center';
        ctx.fillText('separate load test ≥ 1,000 req/min', (x0 + x1) / 2, chartArea.top + 16);
        ctx.restore();
      } },
    ],
  });
  const d = M('decode_tps_p50');
  const t = M('ttft_s_p50');
  $('m-takeaways').innerHTML =
    `<li><b>${num(Math.min(...d))}–${num(Math.max(...d))} tok/s</b><span>observed decode speed (median per run)</span></li>` +
    `<li><b>${num(Math.min(...t), 1)}–${num(Math.max(...t), 1)} s</b><span>time to first token stayed stable (median per run)</span></li>` +
    `<li class="minor"><b>${num(pctl(SWE.requests.map((q) => q.lat), 0.5), 1)} s</b><span>request latency, median of all ${SWE.requests.length} requests</span></li>`;
  $('m-decode-note').textContent = 'The slowdown overlapped with a separate load test we ran on the same public model (shaded); the timing matches, but correlation does not establish causation.';
}

// ==================================================================== 3. PUBLIC VS DEDICATED
function drawEndpoints() {
  const S = BENCH.scaling;
  const conc = S.A.map((x) => x.c);
  const R = BENCH.ramps.R;
  const firstR = R.find((x) => x.rate_429 > 0);
  $('ep-public-status').textContent = `${num(BENCH.totals.public_requests)} requests on ${BENCH.model}, ${BENCH.window_utc} UTC. No errors up to 30 concurrent requests or 1,000 requests/min.`;
  $('ep-dedicated-status').textContent = `${BENCH.dedicated.endpoint} (${BENCH.dedicated.hardware}) stayed in “starting” from 14:35 to 16:23 UTC and never served a request. No dedicated numbers are shown.`;
  const lines = (k) => [
    { label: 'agent step (~10k in / 512 out)', data: S.B.map((x) => x[k]), borderColor: css('--series'), backgroundColor: css('--series'), borderWidth: 3, pointRadius: 5 },
    { label: 'chat (~3k in / 256 out)', data: S.A.map((x) => x[k]), borderColor: css('--muted'), backgroundColor: css('--muted'), borderWidth: 2, pointRadius: 4, borderDash: [6, 4] },
  ];
  const x = { title: { display: true, text: 'concurrent requests' } };
  chart('c-ep-throughput', { type: 'line', data: { labels: conc, datasets: lines('agg_out_tps') },
    options: { scales: { x, y: { min: 0, title: { display: true, text: 'output tokens / second (all requests)' } } } } });
  chart('c-ep-latency', { type: 'line', data: { labels: conc, datasets: lines('lat_p95') },
    options: { scales: { x, y: { min: 0, title: { display: true, text: 'p95 latency per request (s)' } } } } });
  $('ep-limits').innerHTML = [
    plainTile('Requests', '1,000 / min', `first 429 after ${num(firstR.first_429_s / 60, 0)} min at ${num(firstR.offered_rpm)} req/min`, 'verified'),
    plainTile('Tokens', '2M / min', `cached tokens count in full: ≈ ${num(publicTasksPerHourCap(), 0)} SWE-bench tasks per hour`, 'measured'),
    plainTile('Over the limit', `≈ ${num(firstR.lat429_p50, 1)} s wait`, 'then HTTP 429, without a Retry-After header', 'measured'),
  ].join('');
}

// ==================================================================== 4. COST CURVES
function renderEconomics() {
  const sel = $('e-task');
  const opt = (v, label) => { const o = document.createElement('option'); o.value = v; o.textContent = label; sel.append(o); };
  opt('all', `All 9 runs: ${usd(mean(SWE.runs.map((r) => r.metrics.cost_usd)), 4)} per task`);
  for (const [iid, inst] of Object.entries(SWE.instances)) {
    const c = mean(SWE.runs.filter((r) => r.instance_id === iid).map((r) => r.metrics.cost_usd));
    opt(iid, `Issue ${inst.alias.slice(-1).toUpperCase()} (django-${shortIssue(iid)}): ${usd(c, 4)}`);
  }
  $('econ-form').addEventListener('input', drawEconomics);
  drawEconomics();
}
function drawEconomics() {
  const price = +$('e-price').value;
  const v = $('e-task').value;
  const perTask = mean(SWE.runs.filter((r) => v === 'all' || r.instance_id === v).map((r) => r.metrics.cost_usd));
  const be = price / perTask;
  const cap = publicTasksPerHourCap();
  $('e-price-o').textContent = usd(price, 2);
  const xmax = Math.ceil((Math.max(be, cap) * 1.25) / 500) * 500;
  const ymax = Math.max(price, perTask * xmax) * 1.05;
  $('e-tiles').innerHTML = [
    plainTile('Public cost per task', usd(perTask, 4), 'DeepSeek list price × measured tokens', 'measured'),
    plainTile('Break-even', `${num(be, 0)} tasks/h`, `≈ ${num(be / 60, 0)} per minute, every billed hour`, 'estimate'),
    plainTile('Public default limit', `≈ ${num(cap, 0)} tasks/h`, `2M tokens/min ÷ ${big(tokensPerTask)} tokens per task`, 'estimate'),
  ].join('');
  chart('c-curve', {
    type: 'line',
    data: {
      datasets: [
        { label: 'Public: pay per token', data: [{ x: 0, y: 0 }, { x: xmax, y: perTask * xmax }], borderColor: css('--series'), backgroundColor: css('--series'), borderWidth: 4, pointRadius: 0 },
        { label: `Dedicated replica: ${usd(price, 2)} per hour (assumed)`, data: [{ x: 0, y: price }, { x: xmax, y: price }], borderColor: css('--tok-output'), backgroundColor: css('--tok-output'), borderWidth: 3, borderDash: [8, 5], pointRadius: 0 },
        { label: 'Public default limit', data: [{ x: cap, y: 0 }, { x: cap, y: ymax }], borderColor: css('--muted'), backgroundColor: css('--muted'), borderWidth: 1.5, borderDash: [3, 4], pointRadius: 0 },
        { type: 'scatter', label: 'break-even', data: [{ x: be, y: price }], backgroundColor: css('--fg'), borderColor: css('--fg'), pointRadius: 7 },
      ],
    },
    options: {
      scales: {
        x: { type: 'linear', min: 0, max: xmax, title: { display: true, text: 'SWE-bench tasks per hour' } },
        y: { min: 0, max: ymax, title: { display: true, text: 'USD per billed hour' }, ticks: { callback: (y) => usd(y, 0) } },
      },
      plugins: { tooltip: { callbacks: { label: (c) => `${c.dataset.label}: ${num(c.raw.x, 0)} tasks/h → ${usd(c.raw.y, 2)}` } } },
    },
  });
  $('e-note').textContent = `Dedicated only pays off above ${num(be, 0)} tasks per hour, ${num(be / cap, 1)}× what the default public limits allow, and only if the replica is that busy every billed hour. Dedicated capacity for this model is pending: the 2× B200 endpoint never became ready, so whether one replica could serve that load is unknown.`;
}

// ==================================================================== 5. CLASSROOM SIMULATION
let simTimer = null;
let lastSim = null;
function renderClassroom() {
  const form = $('sim-form');
  const schedule = () => { clearTimeout(simTimer); simTimer = setTimeout(runSim, 150); };
  form.addEventListener('input', schedule);
  form.addEventListener('change', schedule);
  for (const b of document.querySelectorAll('.presets button')) b.addEventListener('click', () => { $('s-students').value = b.dataset.n; schedule(); });
  runSim();
}
function runSim() {
  const scenario = {
    students: +$('s-students').value, tasksPerStudent: +$('s-tasks').value, pattern: 'class', windowHours: +$('s-hours').value,
    syncMinutes: +$('s-sync').value, releaseSpan: 0.8, reviewMinutes: 2, retryFailed: false, seed: 7,
  };
  const mult = +$('s-mult').value;
  const backend = { kind: 'public', rpm: LIMITS.requests_per_minute, tpm: LIMITS.tokens_per_minute, rateLimitMultiplier: mult, dynamicLimits: false, tpmCountsCached: true };
  $('s-students-o').textContent = scenario.students;
  $('s-tasks-o').textContent = scenario.tasksPerStudent;
  $('s-hours-o').textContent = num(scenario.windowHours, 1) + ' h';
  $('s-sync-o').textContent = num(scenario.syncMinutes, 1);
  for (const b of document.querySelectorAll('.presets button')) b.setAttribute('aria-pressed', String(+b.dataset.n === scenario.students));
  lastSim = { scenario, mult, res: simulate(SWE_TRAJ, scenario, backend, PR) };
  drawSim();
}
function drawSim() {
  const { scenario, mult, res } = lastSim;
  const s = res.summary;
  const limit = LIMITS.tokens_per_minute * mult;
  const feasible = s.tasksCompleted >= s.tasksAttempted && !s.overranWindow;
  $('s-tiles').innerHTML = [
    plainTile('Session cost', usd(s.publicCostUsd, 2), `${usd(s.publicCostUsd / scenario.students, 3)} per student · list price`, 'estimate'),
    plainTile('Task time p95', secs(s.taskDurationP95), feasible ? `${num(s.slowdownP95, 1)}× the recorded run` : 'not all tasks finished in the session', 'estimate'),
    plainTile('Peak tokens / min', big(s.peakTpm), `${pct(s.peakTpm / limit)} of the ${big(limit)} limit`, 'estimate'),
  ].join('');
  const tl = res.timeline;
  const xs = tl.map((x) => x.minute);
  chart('c-tpm', {
    type: 'line',
    data: { labels: xs, datasets: [
      { label: 'tokens/min sent (cached included)', data: tl.map((x) => x.tokensIn + x.tokensOut), borderColor: css('--series'), backgroundColor: alpha(css('--series'), 0.15), fill: true, pointRadius: 0, borderWidth: 2.5 },
      { label: `limit ${big(limit)}/min`, data: xs.map(() => limit), borderColor: css('--bad'), borderDash: [6, 4], pointRadius: 0, borderWidth: 2 },
    ] },
    options: { scales: { x: { title: { display: true, text: 'minute of the session' }, ticks: { maxTicksLimit: 12 } }, y: { min: 0, ticks: { callback: (v) => big(v) } } } },
  });
  chart('c-active', {
    type: 'line',
    data: { labels: xs, datasets: [
      { label: 'agents in progress', data: tl.map((x) => x.activeAgents), borderColor: css('--tok-output'), backgroundColor: alpha(css('--tok-output'), 0.15), fill: true, pointRadius: 0, borderWidth: 2.5 },
    ] },
    options: { plugins: { legend: { display: false } }, scales: { x: { title: { display: true, text: 'minute of the session' }, ticks: { maxTicksLimit: 12 } }, y: { min: 0, title: { display: true, text: 'agents' } } } },
  });
  $('s-note').textContent = `${num(scenario.students)} students × ${scenario.tasksPerStudent} tasks, replaying the 9 recorded runs. Assumes each request keeps its recorded latency; the API test saw requests slow down from about 10 concurrent. Dedicated comparison pending.`;
}

// ==================================================================== 6. METHOD & SOURCES
function renderMethod() {
  const p = SWE.pooled;
  $('method').innerHTML = `
    <h3>Data</h3><ul>
      <li><b>Agent runs</b> ${ev('measured')}: 9 SWE-bench Verified runs (3 Django issues × 3), stock DSH Web UI, <code>${esc(SWE.model)}</code> on Token Factory Public, 2 November 14:54–15:28 UTC. Official SWE-bench harness: ${p.successes}/${p.runs} resolved. <code>docs/SWEBENCH_PUBLIC_V4FLASH.md</code></li>
      <li><b>API load test</b> ${ev('measured')}: ${num(BENCH.totals.public_requests)} requests to the same model, ${BENCH.window_utc} UTC, concurrency 1–30 and rate ramps to 1,500 req/min. <code>docs/DEEPSEEK_ENDPOINT_PERFORMANCE.md</code></li>
      <li><b>Prices and limits</b> ${ev('verified')}: $${PR.input_per_mtok} input, $${PR.cached_input_per_mtok} cached input, $${PR.output_per_mtok} output per 1M tokens; 1,000 requests and 2M tokens per minute (model catalogue and response headers).</li></ul>
    <h3>Definitions</h3><ul>
      <li>TTFT: request sent → first streamed token. Decode speed: output tokens ÷ time from first to last token. Latency: request sent → response complete.</li>
      <li>Cost = uncached input × $${PR.input_per_mtok} + cached input × $${PR.cached_input_per_mtok} + output × $${PR.output_per_mtok} per 1M tokens (list price, not an invoice).</li></ul>
    <h3>Limits of this demo</h3><ul>
      <li>Dedicated: not measured. The 2× B200 endpoint never became ready; its hourly price is an assumption.</li>
      <li>9 runs on 3 issues on one afternoon: a small sample. Public speed varied during the window.</li>
      <li>The classroom simulation replays recorded requests and assumes the shared pool does not slow down with class load.</li></ul>`;
}

// ------------------------------------------------------------------ boot
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


function boot() {
  themeDefaults();
  $('self-check').addEventListener('click', () => selfCheck().catch((err) => reportProblem('self-check', err)));
  $('dsh-version').textContent = (/\d+\.\d+\.\d+(-[\w.]+)?/.exec(SWE.harness) || [''])[0];
  $('foot').textContent = `Built ${D.builtAt.slice(0, 16).replace('T', ' ')} UTC from ${SWE.runs.length} recorded SWE-bench runs and ${num(BENCH.totals.public_requests)} API test requests. Model ${SWE.model} on Nebius Token Factory Public. Offline: all data and code are inside this file.`;
  show(currentView());
  const redraw = () => {
    themeDefaults();
    for (const v of VIEWS) if (inited[v]) stale[v] = true;
    show(currentView());
  };
  window.matchMedia('(prefers-color-scheme: dark)').addEventListener?.('change', redraw);
  new MutationObserver(redraw).observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });
}
boot();
