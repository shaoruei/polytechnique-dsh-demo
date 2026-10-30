// Dashboard application. Model functions (simulate, costCurves, ...) are bundled above this file.
/* global Chart */
const D = window.DEMO_DATA;
const PRICES = D.pricing.public;
const GPUS = D.profiles.gpus;
const TRAJ = trajectoriesFrom({ runs: D.runs });
const $ = (id) => document.getElementById(id);
const TASK_SHORT = { 't1-grade-average': 'T1 grade average', 't2-duration-parser': 'T2 duration parser', 't3-schedule-conflicts': 'T3 timetable clashes' };

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
const tile = (label, value, detail = '', key = false) =>
  `<div class="tile${key ? ' key' : ''}"><span class="label">${label}</span><span class="value">${value}</span><span class="detail">${detail}</span></div>`;

// ------------------------------------------------------------------ theme-aware charts
const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
const charts = {};
function themeDefaults() {
  Chart.defaults.color = css('--muted');
  Chart.defaults.borderColor = css('--line');
  Chart.defaults.font.family = css('--font-body');
  Chart.defaults.font.size = 12;
  Chart.defaults.plugins.legend.labels.boxWidth = 12;
  Chart.defaults.maintainAspectRatio = false;
  Chart.defaults.animation = window.matchMedia('(prefers-reduced-motion: reduce)').matches ? false : { duration: 250 };
}
function chart(id, config) {
  if (charts[id]) charts[id].destroy();
  charts[id] = new Chart($(id), config);
  return charts[id];
}
const TASK_COLORS = () => ({ 't1-grade-average': css('--accent'), 't2-duration-parser': css('--bad'), 't3-schedule-conflicts': css('--dedicated') });
const alpha = (color, a) => `color-mix(in srgb, ${color} ${Math.round(a * 100)}%, transparent)`;

// ------------------------------------------------------------------ router
const VIEWS = ['run', 'measure', 'economics', 'classroom', 'method'];
const inited = {}; // view -> controls wired and drawn once
const stale = {}; // view -> charts need redrawing (theme change)
const INIT = { run: () => renderRun(), measure: () => renderMeasure(), economics: () => renderEconomics(), classroom: () => renderClassroom(), method: () => renderMethod() };
const DRAW = { run: () => loadRun($('run-select').value), measure: () => drawMeasure(), economics: () => drawEconomics(), classroom: () => drawSim(), method: () => {} };
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
  if (!inited[view]) {
    inited[view] = true;
    stale[view] = false;
    INIT[view]();
  } else if (stale[view]) {
    stale[view] = false;
    DRAW[view]();
  }
}
window.addEventListener('hashchange', () => show(location.hash.slice(1)));

// ==================================================================== 1. RUN
let replayTimer = null;
function renderRun() {
  const sel = $('run-select');
  const order = ['t3-schedule-conflicts', 't1-grade-average', 't2-duration-parser'];
  const runs = [...D.runs].filter((r) => D.replays[r.run_id]?.length).sort((a, b) =>
    order.indexOf(a.task) - order.indexOf(b.task) || ['medium', 'low', 'high'].indexOf(a.effort) - ['medium', 'low', 'high'].indexOf(b.effort) || a.run_id.localeCompare(b.run_id));
  let group = null;
  let optgroup = null;
  for (const r of runs) {
    if (r.task !== group) {
      group = r.task;
      optgroup = document.createElement('optgroup');
      optgroup.label = D.tasks[r.task]?.title ?? r.task;
      sel.append(optgroup);
    }
    const o = document.createElement('option');
    o.value = r.run_id;
    o.textContent = `${r.success ? 'pass' : 'FAIL'} · ${r.effort} · ${secs(r.wall_time_s)} · ${r.metrics.llm_requests} req · ${r.run_id.slice(9, 15)}${r.label === 'live' ? ' · live' : ''}`;
    optgroup.append(o);
  }
  const live = runs.filter((r) => r.label === 'live').at(-1);
  sel.value = (live ?? runs.find((r) => r.task === 't3-schedule-conflicts' && r.effort === 'medium' && r.success) ?? runs[0]).run_id;
  sel.addEventListener('change', () => loadRun(sel.value));
  $('replay-play').addEventListener('click', () => playReplay());
  $('replay-all').addEventListener('click', () => drawEvents(Infinity));
  $('copy-cmd').addEventListener('click', async () => {
    const text = $('live-cmd').textContent;
    try {
      await navigator.clipboard.writeText(text);
      $('copy-cmd').textContent = 'Copied';
    } catch {
      const range = document.createRange();
      range.selectNodeContents($('live-cmd'));
      getSelection().removeAllRanges();
      getSelection().addRange(range);
      $('copy-cmd').textContent = 'Selected';
    }
    setTimeout(() => ($('copy-cmd').textContent = 'Copy'), 1500);
  });
  loadRun(sel.value);
}

let currentRun = null;
function loadRun(runId) {
  clearInterval(replayTimer);
  const r = D.runs.find((x) => x.run_id === runId);
  currentRun = r;
  const m = r.metrics;
  $('run-meta').innerHTML = [
    r.effort + ' effort', `${m.llm_requests} LLM requests`, `${m.tool_calls} tool calls`, secs(r.wall_time_s),
    usd(m.cost_usd), `cache hit ${pct(m.cache_hit_rate)}`, r.started_at.slice(0, 16).replace('T', ' ') + ' UTC',
  ].map((x) => `<span>${esc(x)}</span>`).join('');
  $('run-prompt').textContent = D.tasks[r.task]?.prompt ?? '';
  $('live-cmd').textContent = `python3 harness/run_task.py ${r.task.split('-')[0]} --live`;
  drawLane(r);
  drawEvents(Infinity);
  drawVerdict(r);
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
  const events = D.replays[r.run_id];
  const segs = laneSegments(events);
  const total = Math.max(...segs.map((s) => s.to), 0.001);
  $('lane').innerHTML = segs.map((s) =>
    `<span class="${s.kind}${s.from > upTo ? ' dim' : ''}" style="width:${((s.to - s.from) / total) * 100}%" title="${s.kind} ${num(s.to - s.from, 2)} s"></span>`).join('');
}

function eventRow(e) {
  const t = `<span class="t">${num(e.t, 1)}s</span>`;
  switch (e.k) {
    case 'step': return `<li class="step">${t}<span class="kind">request</span><span class="body">LLM request #${e.step}</span></li>`;
    case 'think': return `<li class="think">${t}<span class="kind">thinking</span><span class="body">${esc(e.text)}</span></li>`;
    case 'say': return `<li>${t}<span class="kind say">answer</span><span class="body">${esc(e.text)}</span></li>`;
    case 'call': return `<li>${t}<span class="kind call">${esc(e.name)}</span><span class="body"><code>${esc(e.text)}</code></span></li>`;
    case 'result': return `<li>${t}<span class="kind result${e.err ? ' err' : ''}">${e.err ? 'error' : 'result'}</span><span class="body"><code>${esc(e.text)}</code></span></li>`;
    case 'usage': return `<li>${t}<span class="kind">tokens</span><span class="body mono">in ${num(e.u + e.c)} (cached ${num(e.c)}) · out ${num(e.o)}</span></li>`;
    case 'end': return `<li class="step">${t}<span class="kind">done</span><span class="body">turn ended: ${esc(e.text)}</span></li>`;
    default: return '';
  }
}

function drawEvents(upTo, animateFrom = Infinity) {
  const events = D.replays[currentRun.run_id];
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
  const events = D.replays[currentRun.run_id];
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

function drawVerdict(r) {
  const a = r.acceptance;
  const fails = a.failing_cases?.length ? `<p>Failing: <code>${a.failing_cases.map(esc).join(', ')}</code></p>` : '';
  $('verdict').innerHTML = `
    <div><h3>What the agent reported</h3><div class="claim">${esc(r.agent_final_answer || '(no final answer)')}</div>
      <p class="note">Its own test run: ${r.agent_suite_ok ? 'passing' : 'failing'}. Changed ${r.diff_stats.files_changed} file(s), +${r.diff_stats.lines_added}/−${r.diff_stats.lines_removed} lines${r.modified_test_files.length ? `, edited tests: ${r.modified_test_files.join(', ')}` : ''}.</p></div>
    <div><h3>Independent judge ${ev('measured')}</h3>
      <p><span class="pill ${a.ok ? 'ok' : 'bad'}">${a.ok ? 'PASS' : 'FAIL'}</span> ${a.tests_run} tests (visible + hidden), ${a.failures} failures, ${a.errors} errors.</p>${fails}
      <p class="note">The harness copies the agent's code into a clean directory, restores the original visible tests, adds the hidden acceptance tests and runs <code>python3 -m unittest</code>. Only this decides success.</p></div>
    <div><h3>Measured for this run</h3><dl class="kv">
      <dt>End-to-end time</dt><dd>${secs(r.wall_time_s)}</dd>
      <dt>LLM time / tool time</dt><dd>${secs(r.metrics.llm_time_s)} / ${secs(r.metrics.tool_time_s)}</dd>
      <dt>TTFT p50</dt><dd>${num(r.metrics.ttft_s_p50, 2)} s</dd>
      <dt>Decode p50</dt><dd>${num(r.metrics.decode_tps_p50)} tok/s</dd>
      <dt>Input (cached) / output</dt><dd>${big(r.metrics.prompt_tokens)} (${big(r.metrics.cached_input_tokens)}) / ${big(r.metrics.output_tokens)}</dd>
      <dt>Cost</dt><dd>${usd(r.metrics.cost_usd)}</dd></dl></div>`;
}

// ==================================================================== 2. MEASURE
function measureRuns() {
  const e = $('m-effort').value;
  return D.runs.filter((r) => r.usable && (e === 'all' || r.effort === e));
}
function renderMeasure() {
  $('m-nruns').textContent = D.runs.filter((r) => r.usable).length;
  $('m-effort').addEventListener('change', drawMeasure);
  drawMeasure();
}
function drawMeasure() {
  const runs = measureRuns();
  const M = (k) => runs.map((r) => r.metrics[k]).filter(Number.isFinite);
  const reqs = runs.flatMap((r) => r.metrics.requests);
  const succ = runs.filter((r) => r.success).length;
  const byTask = (t) => runs.filter((r) => r.task === t);
  const succTxt = Object.keys(TASK_SHORT).map((t) => `${t.slice(0, 2).toUpperCase()} ${byTask(t).filter((r) => r.success).length}/${byTask(t).length}`).join(' · ');
  $('m-tiles').innerHTML = [
    tile('Runs', num(runs.length), `${big(D.ledger.llm_requests)} requests in all; total spend ${usd(D.ledger.total_cost_usd, 2)}`),
    tile('Success (hidden tests)', pct(succ / runs.length), succTxt, true),
    tile('Task time, median', secs(median(runs.map((r) => r.wall_time_s))), 'DSH start to final answer'),
    tile('LLM requests / task', num(mean(M('llm_requests')), 1), `${num(mean(M('tool_calls')), 1)} tool calls`),
    tile('Input tokens / task', big(mean(M('prompt_tokens'))), `output ${big(mean(M('output_tokens')))}`),
    tile('Cache hit rate', pct(M('cached_input_tokens').reduce((a, b) => a + b, 0) / M('prompt_tokens').reduce((a, b) => a + b, 0)), 'cached ÷ prompt tokens'),
    tile('Cost / task', usd(mean(M('cost_usd')), 4), `${usd(1000 * mean(M('cost_usd')), 2)} per 1,000 tasks`, true),
    tile('TTFT p50', num(median(reqs.map((q) => q.ttft).filter(Number.isFinite)), 2) + ' s', 'per request, public endpoint'),
    tile('Decode p50', num(median(reqs.map((q) => q.tps).filter(Number.isFinite))) + ' tok/s', 'per request stream'),
  ].join('');

  const colors = TASK_COLORS();
  // scatter
  chart('c-scatter', {
    type: 'scatter',
    data: {
      datasets: Object.keys(TASK_SHORT).map((t) => ({
        label: TASK_SHORT[t],
        data: byTask(t).map((r) => ({ x: r.wall_time_s, y: r.metrics.cost_usd, r })),
        backgroundColor: byTask(t).map((r) => (r.success ? colors[t] : 'transparent')),
        borderColor: colors[t],
        pointStyle: byTask(t).map((r) => (r.success ? 'circle' : 'crossRot')),
        pointRadius: byTask(t).map((r) => (r.effort === 'high' ? 8 : r.effort === 'low' ? 4 : 6)),
        borderWidth: 2,
      })),
    },
    options: {
      scales: { x: { title: { display: true, text: 'completion time (s)' }, min: 0 }, y: { title: { display: true, text: 'cost per task (USD)' }, min: 0, ticks: { callback: (v) => '$' + v.toFixed(3) } } },
      plugins: { tooltip: { callbacks: { label: (c) => `${c.raw.r.success ? 'pass' : 'FAIL'} · ${c.raw.r.effort} · ${secs(c.raw.x)} · ${usd(c.raw.y)} · ${c.raw.r.metrics.llm_requests} req` } } },
    },
  });

  // cost split per task
  const tasks = Object.keys(TASK_SHORT);
  const avg = (t, k) => mean(byTask(t).map((r) => r.metrics[k]));
  const parts = tasks.map((t) => ({
    unc: (avg(t, 'uncached_input_tokens') * PRICES.input_per_mtok) / 1e6,
    cac: (avg(t, 'cached_input_tokens') * PRICES.cached_input_per_mtok) / 1e6,
    out: (avg(t, 'output_tokens') * PRICES.output_per_mtok) / 1e6,
    tUnc: avg(t, 'uncached_input_tokens'), tCac: avg(t, 'cached_input_tokens'), tOut: avg(t, 'output_tokens'),
  }));
  chart('c-costsplit', {
    type: 'bar',
    data: {
      labels: tasks.map((t) => TASK_SHORT[t]),
      datasets: [
        { label: `cached input ($${PRICES.cached_input_per_mtok}/M)`, data: parts.map((p) => p.cac), backgroundColor: alpha(css('--accent'), 0.45) },
        { label: `uncached input ($${PRICES.input_per_mtok}/M)`, data: parts.map((p) => p.unc), backgroundColor: css('--accent') },
        { label: `output incl. reasoning ($${PRICES.output_per_mtok}/M)`, data: parts.map((p) => p.out), backgroundColor: css('--public') },
      ],
    },
    options: {
      scales: { x: { stacked: true }, y: { stacked: true, title: { display: true, text: 'mean cost per task (USD)' }, ticks: { callback: (v) => '$' + v.toFixed(3) } } },
      plugins: { tooltip: { callbacks: { label: (c) => `${c.dataset.label}: ${usd(c.raw)} (${big([parts[c.dataIndex].tCac, parts[c.dataIndex].tUnc, parts[c.dataIndex].tOut][c.datasetIndex])} tokens)` } } },
    },
  });
  const tot = parts.reduce((s, p) => ({ unc: s.unc + p.unc, cac: s.cac + p.cac, out: s.out + p.out }), { unc: 0, cac: 0, out: 0 });
  const all = tot.unc + tot.cac + tot.out;
  $('cost-split-note').textContent = `Cached input is ${pct(tot.cac / all)} of the cost even at the discounted $${PRICES.cached_input_per_mtok}/M (one third off the $${PRICES.input_per_mtok}/M input price). Without the cache discount these tasks would cost ${pct(mean(M('cost_usd_without_cache_discount')) / mean(M('cost_usd')) - 1)} more.`;

  // context growth
  const sample = tasks.map((t) => byTask(t).find((r) => r.metrics.requests.length > 3)).filter(Boolean);
  chart('c-context', {
    type: 'line',
    data: {
      datasets: sample.flatMap((r) => [
        { label: `${TASK_SHORT[r.task]}: prompt`, data: r.metrics.requests.map((q, i) => ({ x: i + 1, y: q.p })), borderColor: colors[r.task], backgroundColor: colors[r.task], tension: 0.2, pointRadius: 2 },
        { label: `${TASK_SHORT[r.task]}: cached`, data: r.metrics.requests.map((q, i) => ({ x: i + 1, y: q.c })), borderColor: colors[r.task], borderDash: [4, 4], pointRadius: 0, borderWidth: 1.5 },
      ]),
    },
    options: { parsing: false, scales: { x: { type: 'linear', title: { display: true, text: 'LLM request # within the task' }, ticks: { stepSize: 1 } }, y: { title: { display: true, text: 'tokens' }, min: 0 } } },
  });

  // time breakdown
  const tb = tasks.map((t) => {
    const rs = byTask(t);
    const llm = mean(rs.map((r) => r.metrics.llm_time_s));
    const tool = mean(rs.map((r) => r.metrics.tool_time_s));
    return { llm, tool, other: Math.max(mean(rs.map((r) => r.wall_time_s)) - llm - tool, 0) };
  });
  chart('c-time', {
    type: 'bar',
    data: {
      labels: tasks.map((t) => TASK_SHORT[t]),
      datasets: [
        { label: 'LLM requests', data: tb.map((x) => x.llm), backgroundColor: css('--accent') },
        { label: 'tool execution', data: tb.map((x) => x.tool), backgroundColor: css('--public') },
        { label: 'DSH start-up + harness', data: tb.map((x) => x.other), backgroundColor: css('--line') },
      ],
    },
    options: { indexAxis: 'y', scales: { x: { stacked: true, title: { display: true, text: 'mean seconds per task' } }, y: { stacked: true } } },
  });

  // ttft / decode distribution
  const ttft = reqs.map((q) => q.ttft).filter(Number.isFinite);
  const bins = [0.3, 0.35, 0.4, 0.45, 0.5, 0.6, 0.8, 1.0, 1.5, 2.0, 3.0];
  const hist = bins.slice(0, -1).map((b, i) => ttft.filter((x) => x >= b && x < bins[i + 1]).length);
  const tps = reqs.map((q) => q.tps).filter(Number.isFinite);
  chart('c-ttft', {
    type: 'bar',
    data: {
      labels: bins.slice(0, -1).map((b, i) => `${b}–${bins[i + 1]}`),
      datasets: [{ label: `TTFT (n=${ttft.length}), p50 ${num(median(ttft), 2)} s, p90 ${num([...ttft].sort((a, b) => a - b)[Math.floor(ttft.length * 0.9)], 2)} s`, data: hist, backgroundColor: css('--accent') }],
    },
    options: {
      scales: { x: { title: { display: true, text: `seconds to first token · decode p50 ${num(median(tps))} tok/s (range ${num(Math.min(...tps))}–${num(Math.max(...tps))})` } }, y: { title: { display: true, text: 'requests' } } },
    },
  });

  // effort comparison (always across all efforts)
  const efforts = ['low', 'medium', 'high'];
  const cell = (t, e) => D.runs.filter((r) => r.usable && r.task === t && r.effort === e);
  chart('c-effort', {
    type: 'bar',
    data: {
      labels: efforts,
      datasets: tasks.map((t) => ({
        label: TASK_SHORT[t],
        data: efforts.map((e) => mean(cell(t, e).map((r) => r.metrics.cost_usd))),
        backgroundColor: colors[t],
        succ: efforts.map((e) => `${cell(t, e).filter((r) => r.success).length}/${cell(t, e).length}`),
      })),
    },
    options: {
      scales: { x: { title: { display: true, text: 'gpt-oss reasoning effort' } }, y: { title: { display: true, text: 'mean cost per task (USD)' }, ticks: { callback: (v) => '$' + v.toFixed(3) } } },
      plugins: { tooltip: { callbacks: { label: (c) => `${c.dataset.label}: ${usd(c.raw)} · success ${c.dataset.succ[c.dataIndex]}` } } },
    },
  });

  // table
  const rows = [...D.runs].sort((a, b) => a.run_id.localeCompare(b.run_id));
  $('runs-table').innerHTML = `<thead><tr><th>run</th><th>task</th><th>effort</th><th>result</th><th>time</th><th>req</th><th>tools (err)</th><th>input</th><th>cached</th><th>output</th><th>hit</th><th>TTFT p50</th><th>decode p50</th><th>cost</th></tr></thead><tbody>` +
    rows.map((r) => {
      const m = r.metrics;
      return `<tr><td class="mono">${r.run_id}</td><td>${TASK_SHORT[r.task] ?? r.task}</td><td>${r.effort}</td><td><span class="pill ${r.success ? 'ok' : 'bad'}">${r.success ? 'pass' : 'fail'}</span></td><td>${num(r.wall_time_s, 1)} s</td><td>${m.llm_requests}</td><td>${m.tool_calls} (${m.tool_calls_failed})</td><td>${num(m.prompt_tokens)}</td><td>${num(m.cached_input_tokens)}</td><td>${num(m.output_tokens)}</td><td>${pct(m.cache_hit_rate)}</td><td>${num(m.ttft_s_p50, 2)}</td><td>${num(m.decode_tps_p50)}</td><td>${usd(m.cost_usd, 5)}</td></tr>`;
    }).join('') + '</tbody>';
}

// ==================================================================== 3. ECONOMICS
function fillGpuSelect(sel, priceInput) {
  for (const [k, g] of Object.entries(GPUS)) {
    const o = document.createElement('option');
    o.value = k;
    o.textContent = `${g.label}`;
    sel.append(o);
  }
  sel.value = 'h100';
  const setPrice = () => (priceInput.value = D.pricing.dedicated.gpus[sel.value].price_per_gpu_hour.toFixed(2));
  setPrice();
  sel.addEventListener('change', setPrice);
}

function econInputs() {
  const s = $('e-sched').value;
  const schedule = s === 'class-only'
    ? { kind: s, sessionsPerMonth: +$('e-sessions').value, sessionHours: +$('e-shours').value, warmupHours: +$('e-warm').value }
    : s === 'business-hours' ? { kind: s, hoursPerDay: +$('e-bh').value, daysPerMonth: +$('e-bd').value } : { kind: s };
  const tr = TRAJ.filter((t) => t.effort === $('e-effort').value);
  return {
    perTask: perTaskProfile(tr),
    schedule,
    gpu: { key: $('e-gpu').value, profile: GPUS[$('e-gpu').value], pricePerGpuHour: +$('e-price').value },
    targetInteractivity: +$('e-speed').value,
    targetUtilization: +$('e-util').value,
    peakFactor: +$('e-peak').value,
    efficiency: +$('e-eff').value,
    rateLimits: { rpm: PRICES.rate_limits.requests_per_minute, tpm: PRICES.rate_limits.tokens_per_minute, multiplier: 1 },
  };
}

function renderEconomics() {
  fillGpuSelect($('e-gpu'), $('e-price'));
  const form = $('econ-form');
  form.addEventListener('input', drawEconomics);
  form.addEventListener('change', drawEconomics);
  $('e-sched').addEventListener('change', () => {
    for (const d of document.querySelectorAll('#econ-form .sched')) d.hidden = d.dataset.s !== $('e-sched').value;
  });
  drawEconomics();
}

function drawEconomics() {
  const inp = econInputs();
  $('e-util-o').textContent = pct(inp.targetUtilization);
  $('e-peak-o').textContent = num(inp.peakFactor, 1) + '×';
  $('e-eff-o').textContent = num(inp.efficiency, 1) + '×';
  const g = D.pricing.dedicated.gpus[inp.gpu.key];
  $('e-price-hint').innerHTML = `Default = Nebius AI Cloud on-demand list price (${usd(g.price_per_gpu_hour, 2)}); docs GPU line item ${usd(g.alt_prices.ai_cloud_docs_gpu_line_item, 2)}. No published Token Factory dedicated rate.`;

  const p = inp.perTask;
  const costPerTask = publicCost(p.tokens, PRICES);
  const hours = billedHoursPerMonth(inp.schedule);
  const activeH = activeHoursPerMonth(inp.schedule);
  const perGpuOut = capacityPerGpu(inp.gpu.profile, inp.targetInteractivity, inp.efficiency);
  const tasksPerGpuHour = (perGpuOut * inp.targetUtilization * 3600) / (p.tokens.output * inp.peakFactor);
  const be = breakEvenTasks({ ...inp, prices: PRICES });
  const naiveBE = naiveDedicatedCost(inp) / costPerTask;
  const perSession = inp.schedule.kind === 'class-only' ? inp.schedule.sessionsPerMonth : null;

  const volumes = [];
  for (let e = 2; e <= 7.0001; e += 0.02) volumes.push(Math.round(10 ** e));
  const curves = costCurves({ volumes, ...inp, prices: PRICES });
  const studentsAt = (tasks) => (perSession ? ` ≈ ${num(tasks / perSession / 6)} students × 6 tasks per session` : '');

  $('e-tiles').innerHTML = [
    tile('Public cost per task', usd(costPerTask, 4), `${ev('measured')} tokens × ${ev('verified')} prices`, true),
    tile('Dedicated GPU, per month', usd(inp.gpu.pricePerGpuHour * hours, 0), `${num(hours)} billed h × ${usd(inp.gpu.pricePerGpuHour, 2)} ${ev('assumption')}`),
    tile('Tasks one GPU can serve', `${big(tasksPerGpuHour)}/h`, `at ≥${inp.targetInteractivity} tok/s per user, ${pct(inp.targetUtilization)} peak utilisation ${ev('benchmark')}`),
    tile('Break-even volume', be.tasks ? `${big(be.tasks)} tasks/mo` : 'none', be.tasks ? `${studentsAt(be.tasks)} ${ev('estimate')}` : esc(be.reason), true),
    tile('Naive break-even', `${big(naiveBE)} tasks/mo`, 'if one GPU had unlimited capacity'),
  ].join('');

  const rows = curves.rows;
  const over = rows.filter((r) => !r.publicWithinLimits);
  chart('c-curve', {
    type: 'line',
    data: {
      datasets: [
        { label: 'Public (pay per token)', data: rows.map((r) => ({ x: r.tasksPerMonth, y: r.publicCost })), borderColor: css('--public'), backgroundColor: css('--public'), pointRadius: 0, borderWidth: 2.5,
          segment: { borderDash: (c) => (rows[c.p1DataIndex] && !rows[c.p1DataIndex].publicWithinLimits ? [6, 4] : undefined) } },
        { label: `Dedicated ${inp.gpu.profile.label}, sized for capacity`, data: rows.map((r) => ({ x: r.tasksPerMonth, y: r.dedicatedCost, gpus: r.dedicatedGpus })), borderColor: css('--dedicated'), backgroundColor: css('--dedicated'), stepped: 'before', pointRadius: 0, borderWidth: 2.5 },
        { label: 'Dedicated, naive (one replica, ignores capacity)', data: rows.map((r) => ({ x: r.tasksPerMonth, y: r.naiveDedicatedCost })), borderColor: css('--muted'), borderDash: [3, 4], pointRadius: 0, borderWidth: 1.5 },
      ],
    },
    options: {
      parsing: false,
      interaction: { mode: 'nearest', axis: 'x', intersect: false },
      scales: {
        x: { type: 'logarithmic', title: { display: true, text: 'agent tasks per month (log scale)' }, ticks: { callback: (v) => ([1e2, 1e3, 1e4, 1e5, 1e6, 1e7].includes(v) ? big(v) : '') } },
        y: { type: 'logarithmic', title: { display: true, text: 'USD per month (log scale)' }, ticks: { callback: (v) => ([1, 10, 100, 1e3, 1e4, 1e5, 1e6].includes(v) ? usd(v, 0) : '') } },
      },
      plugins: { tooltip: { callbacks: { title: (c) => `${big(c[0].raw.x)} tasks/month`, label: (c) => `${c.dataset.label}: ${usd(c.raw.y, 0)}${c.raw.gpus ? ` (${c.raw.gpus} GPU)` : ''}` } } },
    },
  });
  const firstOver = over[0];
  $('e-curve-note').innerHTML = `${be.tasks ? `Dedicated becomes cheaper at <b>${big(be.tasks)} tasks/month</b>${be.permanentFromTasks ? `, and stays cheaper above ${big(be.permanentFromTasks)}` : ''}.` : 'With these inputs dedicated never becomes cheaper.'}
    The dedicated line steps up each time another GPU is needed to hold ${inp.targetInteractivity} tok/s per user at peak.
    ${firstOver ? `The public line turns dashed above ${big(firstOver.tasksPerMonth)} tasks/month: peak demand then exceeds the account's default ${big(PRICES.rate_limits.tokens_per_minute)} tokens/min, so that volume needs higher (auto-scaled or Enterprise) rate limits.` : ''}`;

  // cost per task vs utilisation
  const utils = [];
  for (let u = 0.02; u <= 1.0001; u += 0.02) utils.push(u);
  const perTaskAt = (u) => (inp.gpu.pricePerGpuHour / (perGpuOut * u * 3600)) * p.tokens.output;
  chart('c-util', {
    type: 'line',
    data: {
      datasets: [
        { label: 'Dedicated cost per task', data: utils.map((u) => ({ x: u * 100, y: perTaskAt(u) })), borderColor: css('--dedicated'), pointRadius: 0, borderWidth: 2.5 },
        { label: 'Public cost per task', data: utils.map((u) => ({ x: u * 100, y: costPerTask })), borderColor: css('--public'), pointRadius: 0, borderWidth: 2.5 },
      ],
    },
    options: {
      parsing: false,
      scales: { x: { type: 'linear', min: 0, max: 100, title: { display: true, text: 'average GPU utilisation over billed hours (%)' } }, y: { type: 'logarithmic', title: { display: true, text: 'USD per task (log)' }, ticks: { callback: (v) => ([0.0001, 0.001, 0.01, 0.1, 1].includes(v) ? '$' + v : '') } } },
    },
  });
  const crossU = (inp.gpu.pricePerGpuHour * p.tokens.output) / (perGpuOut * 3600 * costPerTask);

  // speed and feasibility
  const pubReq = D.runs.filter((r) => r.usable).flatMap((r) => r.metrics.requests);
  const pubTps = median(pubReq.map((q) => q.tps).filter(Number.isFinite));
  const tr = TRAJ.filter((t) => t.effort === $('e-effort').value);
  const solo = median(tr.map((t) => t.lead_s + t.steps.reduce((s, x) => s + soloRequestSeconds(inp.gpu.profile, x, { efficiency: inp.efficiency }) + x.gap, 0)));
  const measured = median(tr.map((t) => t.lead_s + t.steps.reduce((s, x) => s + x.lat + x.gap, 0)));
  const maxC = concurrencyForInteractivity(inp.gpu.profile, inp.targetInteractivity, inp.efficiency);
  $('e-feasibility').innerHTML = `<h3>Break-even is not the same as feasibility</h3><ul>
    <li>A dedicated GPU pays off only above about <b>${pct(crossU)}</b> average utilisation of its billed hours. ${ev('estimate')}</li>
    <li>At ${inp.targetInteractivity} tok/s per user one ${inp.gpu.profile.label} holds about <b>${num(maxC, 1)}</b> requests in flight. Each running agent has about one request in flight most of the time. ${ev('benchmark')}</li>
    <li>Single-stream speed: public endpoint measured <b>${num(pubTps)} tok/s</b> median ${ev('measured')}; ${inp.gpu.profile.label} benchmark best case ${num(interactivityAt(inp.gpu.profile, 1) * inp.efficiency)} tok/s ${ev('benchmark')}.</li>
    <li>Median task on an idle dedicated replica: <b>${secs(solo)}</b> (estimate) vs ${secs(measured)} measured on public.</li>
    <li>Public endpoint default limits: ${num(PRICES.rate_limits.requests_per_minute)} requests/min and ${big(PRICES.rate_limits.tokens_per_minute)} tokens/min ${ev('verified')}. One task sends about ${big(p.tokens.prompt_plus_output)} tokens, so the default limit covers about <b>${num(PRICES.rate_limits.tokens_per_minute / p.tokens.prompt_plus_output, 0)} task starts per minute</b>.</li></ul>`;
}

// ==================================================================== 4. CLASSROOM
let simTimer = null;
let lastSim = null;
function renderClassroom() {
  fillGpuSelect($('s-gpu'), $('s-price'));
  for (const n of [1, 2, 3, 4, 6, 8, 12, 16, 24, 32]) {
    const o = document.createElement('option');
    o.value = String(n);
    o.textContent = `${n} replica${n > 1 ? 's' : ''} (fixed)`;
    $('s-replicas').append(o);
  }
  const form = $('sim-form');
  const schedule = () => {
    clearTimeout(simTimer);
    simTimer = setTimeout(runSim, 180);
  };
  form.addEventListener('input', schedule);
  form.addEventListener('change', schedule);
  for (const b of document.querySelectorAll('.presets button')) {
    b.addEventListener('click', () => {
      $('s-students').value = b.dataset.n;
      schedule();
    });
  }
  $('s-pattern').addEventListener('change', () => {
    const day = $('s-pattern').value === 'day';
    $('s-hours').value = day ? 10 : 2;
    $('s-sync').disabled = day;
  });
  $('s-sweep').addEventListener('click', runSweep);
  runSim();
}

function simInputs() {
  const students = +$('s-students').value;
  const scenario = {
    students, tasksPerStudent: +$('s-tasks').value, pattern: $('s-pattern').value, windowHours: +$('s-hours').value,
    syncMinutes: +$('s-sync').value, releaseSpan: 0.8, reviewMinutes: +$('s-review').value, retryFailed: $('s-retry').checked,
    seed: +$('s-seed').value || 1, effort: $('s-effort').value,
  };
  const publicB = {
    kind: 'public', rpm: PRICES.rate_limits.requests_per_minute, tpm: PRICES.rate_limits.tokens_per_minute,
    rateLimitMultiplier: +$('s-mult').value, dynamicLimits: $('s-dyn').checked, tpmCountsCached: $('s-cachedtpm').checked,
  };
  const gpuKey = $('s-gpu').value;
  const dedicatedB = { kind: 'dedicated', profile: GPUS[gpuKey], targetInteractivity: 90 };
  return { scenario, publicB, dedicatedB, gpuKey, replicas: $('s-replicas').value, price: +$('s-price').value,
    sessions: +$('s-sessions').value, warm: +$('s-warm').value };
}

function feasibility(sum) {
  if (sum.tasksCompleted < sum.tasksAttempted || sum.overranWindow) return ['bad', 'overloaded'];
  if (sum.slowdownP95 > 3) return ['bad', 'severely slowed'];
  if (sum.slowdownP95 > 1.5) return ['warn', 'slowed'];
  return ['ok', 'keeps up'];
}

function simulatePair(inp) {
  const pub = simulate(TRAJ, inp.scenario, inp.publicB, PRICES);
  let ded;
  let replicas;
  if (inp.replicas === 'auto') {
    const r = autoSize(TRAJ, inp.scenario, inp.dedicatedB, PRICES, { sloSlowdown: 1.5, maxReplicas: 64 });
    replicas = r.replicas ?? 64;
    ded = r.result;
  } else {
    replicas = +inp.replicas;
    ded = simulate(TRAJ, inp.scenario, { ...inp.dedicatedB, replicas }, PRICES);
  }
  const gpr = inp.dedicatedB.profile.gpus_per_replica || 1;
  const windowH = Math.max(inp.scenario.windowHours, ded.summary.makespanS / 3600);
  const billedH = inp.scenario.pattern === 'class' ? windowH + inp.warm : windowH;
  const dedSession = replicas * gpr * inp.price * billedH;
  return { pub, ded, replicas, gpus: replicas * gpr, dedSession, billedH };
}

function runSim() {
  const inp = simInputs();
  $('s-students-o').textContent = inp.scenario.students;
  $('s-tasks-o').textContent = inp.scenario.tasksPerStudent;
  $('s-hours-o').textContent = num(inp.scenario.windowHours, 1) + ' h';
  $('s-sync-o').textContent = num(inp.scenario.syncMinutes, 2);
  $('s-review-o').textContent = num(inp.scenario.reviewMinutes, 1);
  $('s-mult-o').textContent = inp.publicB.rateLimitMultiplier + '×';
  for (const b of document.querySelectorAll('.presets button')) b.setAttribute('aria-pressed', String(+b.dataset.n === inp.scenario.students));
  const t0 = performance.now();
  const res = simulatePair(inp);
  lastSim = { inp, res, ms: performance.now() - t0 };
  drawSim();
}

function sideCard(kind, sum, extra) {
  const [cls, label] = feasibility(sum);
  const title = kind === 'public' ? 'Public endpoint' : `Dedicated · ${extra.gpus} × ${extra.gpuLabel}`;
  return `<div class="panel side ${kind}"><h3>${title} <span class="pill ${cls}">${label}</span></h3><dl class="kv">
    <dt>Cost for this session</dt><dd class="big">${usd(extra.sessionCost, 2)}</dd>
    <dt>Cost per month (${extra.sessions} sessions)</dt><dd>${usd(extra.sessionCost * extra.sessions, 0)}</dd>
    <dt>Cost basis</dt><dd>${extra.basis}</dd>
    <dt>Task time p50 / p95</dt><dd>${secs(sum.taskDurationP50)} / ${secs(sum.taskDurationP95)}</dd>
    <dt>p95 slowdown vs ${kind === 'public' ? 'measured' : 'idle replica'}</dt><dd>${num(sum.slowdownP95, 2)}×</dd>
    ${kind === 'dedicated' ? `<dt>p95 task time vs measured public</dt><dd>${num(sum.vsMeasuredPublicP95, 2)}×</dd>` : ''}
    <dt>Mean wait per task</dt><dd>${secs(sum.meanWaitPerTask)}</dd>
    <dt>Peak agents working</dt><dd>${num(sum.peakActiveAgents, 0)}</dd>
    <dt>Peak requests / min</dt><dd>${num(sum.peakRpm)}</dd>
    <dt>Peak tokens / min</dt><dd>${big(sum.peakTpm)}</dd>
    ${kind === 'public' ? `<dt>Rate-limit factor reached</dt><dd>${sum.rateLimitHistory?.length ? num(Math.max(...sum.rateLimitHistory.map((h) => h.factor)), 2) + '×' : '1×'}</dd>`
      : `<dt>Decode-slot utilisation</dt><dd>${pct(sum.slotUtilization, 1)}</dd>`}
    <dt>Tasks finished (successful)</dt><dd>${sum.tasksCompleted} (${sum.successfulTasks})</dd></dl></div>`;
}

function drawSim() {
  const { inp, res, ms } = lastSim;
  const ps = res.pub.summary;
  const ds = res.ded.summary;
  const gpuLabel = inp.dedicatedB.profile.label.replace(/^1x /, '');
  $('s-compare').innerHTML =
    sideCard('public', ps, { sessionCost: ps.publicCostUsd, sessions: inp.sessions, basis: `${big(ps.tokens.uncached + ps.tokens.cached + ps.tokens.output)} tokens` }) +
    sideCard('dedicated', ds, { sessionCost: res.dedSession, sessions: inp.sessions, gpus: res.gpus, gpuLabel,
      basis: `${res.gpus} GPU × ${num(res.billedH, 2)} h × ${usd(inp.price, 2)}` });

  const labels = (tl) => tl.map((m) => m.minute);
  const n = Math.max(res.pub.timeline.length, res.ded.timeline.length);
  const xs = Array.from({ length: n }, (_, i) => i);
  const val = (tl, k) => xs.map((i) => tl[i]?.[k] ?? 0);
  chart('c-active', {
    type: 'line',
    data: {
      labels: xs,
      datasets: [
        { label: 'Public: agents in progress', data: val(res.pub.timeline, 'activeAgents'), borderColor: css('--public'), backgroundColor: alpha(css('--public'), 0.15), fill: true, pointRadius: 0, borderWidth: 2 },
        { label: 'Dedicated: agents in progress', data: val(res.ded.timeline, 'activeAgents'), borderColor: css('--dedicated'), backgroundColor: alpha(css('--dedicated'), 0.15), fill: true, pointRadius: 0, borderWidth: 2 },
      ],
    },
    options: { scales: { x: { title: { display: true, text: 'minute of the session' }, ticks: { maxTicksLimit: 12 } }, y: { title: { display: true, text: 'agents (minute average)' }, min: 0 } } },
  });
  const total = ps.tasksAttempted;
  $('s-active-note').innerHTML = `${num(inp.scenario.students)} students × ${inp.scenario.tasksPerStudent} tasks = ${num(total)} agent runs including retries, about ${big(ps.requests)} LLM requests (${num(ps.requests / Math.max(total, 1), 1)} per task). When the public endpoint throttles, agents pile up: they wait instead of finishing. Simulated in ${num(ms)} ms, seed ${inp.scenario.seed}.`;

  const mult = inp.publicB.rateLimitMultiplier;
  const limitLine = xs.map((i) => {
    const h = ps.rateLimitHistory || [];
    let f = 1;
    for (const e of h) if (e.minute <= i) f = e.factor;
    return PRICES.rate_limits.tokens_per_minute * mult * (inp.publicB.dynamicLimits ? f : 1);
  });
  chart('c-tpm', {
    type: 'line',
    data: {
      labels: xs,
      datasets: [
        { label: 'tokens/min sent', data: xs.map((i) => (res.pub.timeline[i] ? res.pub.timeline[i].tokensIn + res.pub.timeline[i].tokensOut : 0)), borderColor: css('--public'), pointRadius: 0, borderWidth: 2 },
        { label: 'tokens/min limit', data: limitLine, borderColor: css('--bad'), borderDash: [5, 4], pointRadius: 0, borderWidth: 1.5, stepped: true },
      ],
    },
    options: { scales: { x: { title: { display: true, text: 'minute' }, ticks: { maxTicksLimit: 10 } }, y: { min: 0, ticks: { callback: (v) => big(v) } } } },
  });
  chart('c-queue', {
    type: 'line',
    data: {
      labels: xs,
      datasets: [
        { label: 'requests in flight', data: val(res.ded.timeline, 'inflight'), borderColor: css('--dedicated'), pointRadius: 0, borderWidth: 2 },
        { label: 'requests waiting for a slot', data: val(res.ded.timeline, 'queued'), borderColor: css('--bad'), pointRadius: 0, borderWidth: 2 },
        { label: `slot capacity at 90 tok/s/user (${res.replicas} replica${res.replicas > 1 ? 's' : ''})`, data: xs.map(() => res.gpus * concurrencyForInteractivity(inp.dedicatedB.profile, 90)), borderColor: css('--muted'), borderDash: [4, 4], pointRadius: 0, borderWidth: 1.5 },
      ],
    },
    options: { scales: { x: { title: { display: true, text: 'minute' }, ticks: { maxTicksLimit: 10 } }, y: { min: 0, title: { display: true, text: 'requests (minute average)' } } } },
  });
}

async function runSweep() {
  const btn = $('s-sweep');
  btn.disabled = true;
  const base = simInputs();
  const sizes = [20, 50, 100, 200, 350, 500];
  const out = [];
  for (const n of sizes) {
    btn.textContent = `Simulating ${n} students…`;
    await new Promise((r) => setTimeout(r, 20));
    const inp = { ...base, scenario: { ...base.scenario, students: n }, replicas: 'auto' };
    const res = simulatePair(inp);
    out.push({ n, pubMonth: res.pub.summary.publicCostUsd * base.sessions, dedMonth: res.dedSession * base.sessions, gpus: res.gpus,
      pubSlow: res.pub.summary.slowdownP95, pubFeas: feasibility(res.pub.summary)[1] });
  }
  btn.textContent = 'Run sweep';
  btn.disabled = false;
  chart('c-sweep', {
    data: {
      labels: sizes,
      datasets: [
        { type: 'line', label: 'Public: cost per month', data: out.map((o) => o.pubMonth), borderColor: css('--public'), backgroundColor: css('--public'), yAxisID: 'y', borderWidth: 2.5,
          pointStyle: out.map((o) => (o.pubSlow > 1.5 ? 'triangle' : 'circle')), pointRadius: out.map((o) => (o.pubSlow > 1.5 ? 7 : 4)) },
        { type: 'line', label: 'Dedicated (auto-sized): cost per month', data: out.map((o) => o.dedMonth), borderColor: css('--dedicated'), backgroundColor: css('--dedicated'), yAxisID: 'y', borderWidth: 2.5, stepped: false },
        { type: 'bar', label: 'GPUs needed', data: out.map((o) => o.gpus), backgroundColor: alpha(css('--dedicated'), 0.2), yAxisID: 'y2' },
      ],
    },
    options: {
      scales: {
        x: { title: { display: true, text: 'students in the class' } },
        y: { position: 'left', min: 0, title: { display: true, text: 'USD per month' }, ticks: { callback: (v) => usd(v, 0) } },
        y2: { position: 'right', min: 0, grid: { drawOnChartArea: false }, title: { display: true, text: 'GPUs' }, ticks: { stepSize: 1 } },
      },
      plugins: { tooltip: { callbacks: { afterBody: (c) => `public p95 slowdown ${num(out[c[0].dataIndex].pubSlow, 1)}× (${out[c[0].dataIndex].pubFeas})` } } },
    },
  });
  const cross = out.find((o) => o.dedMonth <= o.pubMonth);
  const slow = out.filter((o) => o.pubSlow > 1.5).map((o) => o.n);
  $('s-sweep-note').innerHTML = `${cross ? `With these settings dedicated is cheaper from about <b>${cross.n} students</b>.` : 'With these settings dedicated stays more expensive across all class sizes.'}
    ${slow.length ? `Triangles mark class sizes where the public endpoint, at the chosen rate limits, slows the p95 task by more than 1.5× (${slow.join(', ')} students). The cheaper option there is not a working option without higher limits.` : 'At the chosen rate limits the public endpoint keeps up at every class size.'}
    Dedicated cost is per-minute billing for ${$('s-sessions').value} sessions/month plus warm-up; GPUs are auto-sized to keep p95 slowdown ≤ 1.5×.`;
}

// ==================================================================== METHOD
function renderMethod() {
  const pr = D.pricing;
  const pf = D.profiles;
  const li = (s) => `<li>${s}</li>`;
  const src = (arr) => arr.map((s) => li(`${esc(s.label)}: ${s.ref.startsWith('http') ? `<a href="${esc(s.ref)}" target="_blank" rel="noopener">${esc(s.ref)}</a>` : `<code>${esc(s.ref)}</code>`}`)).join('');
  const gpuRows = Object.entries(pf.gpus).map(([k, g]) => {
    const pts = curvePoints(g).map((p) => `${p.interactivity} tok/s/user → ${num(p.tpsPerGpu)} tok/s/GPU (≈${num(p.concurrency, 1)} req/GPU)`).join('; ');
    return li(`<b>${esc(g.label)}</b> ${usd(pr.dedicated.gpus[k].price_per_gpu_hour, 2)}/GPU-h ${ev('assumption')}. Benchmark: ${pts} ${ev('benchmark')}. Max ${g.max_concurrency_per_gpu} concurrent: ${esc(g.max_concurrency_note)} Prefill ${num(g.prefill_tps)} tok/s ${ev('assumption')}.`);
  }).join('');
  const w = D.workload.pooled;
  $('method').innerHTML = `
  <div class="panel"><h3>Public endpoint pricing ${ev('verified')}</h3><ul>
    ${li(`Input $${pr.public.input_per_mtok}/M, cached input $${pr.public.cached_input_per_mtok}/M, output $${pr.public.output_per_mtok}/M tokens (reasoning tokens bill as output). Read from the API's own <code>pricing</code> block on ${esc(D.apiSnapshot.retrieved_at)}: prompt ${esc(D.apiSnapshot.pricing.prompt)}, input_cache_read ${esc(D.apiSnapshot.pricing.input_cache_read)}, completion ${esc(D.apiSnapshot.pricing.completion)} USD/token.`)}
    ${li(`Rate limits for this account: ${num(pr.public.rate_limits.requests_per_minute)} requests/min, ${num(pr.public.rate_limits.tokens_per_minute)} tokens/min (API <code>per_request_limits</code> and matching <code>x-ratelimit-limit-*</code> headers). ${esc(pr.public.rate_limits.notes)}`)}
    ${li(esc(pr.public.billing_notes))}
    ${li(`Do cached tokens count towards tokens/min? Fitting the measured <code>x-ratelimit-remaining-tokens</code> drops across ${D.rateLimitInference.n_pairs} request pairs: cached-token coefficient ${D.rateLimitInference.model_with_cached.coef_cached}, R² ${D.rateLimitInference.model_with_cached.r2} vs ${D.rateLimitInference.model_without_cached.r2} without cached tokens. Conclusion: ${esc(D.rateLimitInference.conclusion)} ${ev('estimate')}. This is why agent traffic, which resends a mostly cached context on every request, reaches the token limit long before the request limit.`)}
    ${li(`Batch inference: ${pct(pr.batch.discount)} off, 24 h turnaround, so not usable for interactive agents (${esc(pr.batch.ref)}).`)}
    ${src(pr.public.sources)}</ul></div>
  <div class="panel"><h3>Dedicated endpoint ${ev('assumption')} ${ev('benchmark')}</h3><ul>
    ${li(esc(pr.dedicated.billing_model))}
    ${li(esc(pr.dedicated.price_note))}
    ${gpuRows}
    ${li(`Benchmark: ${esc(pf.benchmark.name)}. ${esc(pf.benchmark.interpretation)}`)}
    ${Object.values(pf.model_assumptions).filter((x) => typeof x === 'string').map((x) => li(esc(x))).join('')}
    ${pf.gpu_requirements.facts.map((x) => li(esc(x) + ' ' + ev('verified'))).join('')}
    ${src(pr.dedicated.sources)}</ul></div>
  <div class="panel"><h3>What was measured ${ev('measured')}</h3><ul>
    ${li(`${D.ledger.runs} DSH runs (${esc(D.runs[0]?.started_at?.slice(0, 10))}), ${num(D.ledger.llm_requests)} LLM requests, ${big(D.ledger.prompt_tokens)} prompt and ${big(D.ledger.output_tokens)} output tokens. Total experiment spend <b>${usd(D.ledger.total_cost_usd, 4)}</b>. Every run is sequential; there was no load testing.`)}
    ${li('Three tasks with hidden acceptance tests and reference solutions: T1 bug-fix (1 file), T2 feature from a written spec with its own tests, T3 multi-file debugging. Efforts: low/medium/high.')}
    ${li('Token usage: the provider <code>usage</code> block of every streamed response (prompt_tokens incl. cached_tokens, completion_tokens incl. reasoning).')}
    ${li('TTFT: relay receives the request → first streamed delta of any kind. Decode: completion tokens ÷ (last byte − first token). Latency: request → last byte. These are client-side observations from this cloud container (Finland endpoint), and they include proxy hops.')}
    ${li('Tool time: DSH session log <code>tool/call</code> → <code>tool/result</code>. Task time: harness wall clock from launching <code>dsh</code> to process exit (includes ~1.5–2 s DSH start-up).')}
    ${li(`Success: the harness's own unittest run (pristine visible tests + hidden tests) against the agent's code. The agent's claim is shown but never used.`)}
    ${li(`Pooled: success ${pct(w.success_rate)}, per-request TTFT p50 ${num(w.per_request.ttft_s.p50, 2)} s, decode p50 ${num(w.per_request.decode_tps.p50)} tok/s, uncached input : output = ${num(w.per_request.uncached_to_output_ratio, 1)} : 1.`)}</ul></div>
  <div class="panel"><h3>Integration notes and limitations</h3><ul>
    ${li('<b>Token Factory streaming bug.</b> For gpt-oss-120b the last argument fragment of a streamed tool call arrives with <code>index: 1</code> and no id. A spec-following client (pi-ai inside DSH) then opens a second, nameless tool call and the agent loop aborts. A loopback relay (<code>harness/tofa_relay.py</code>) remaps such fragments to the open call. It forwards to the same host through the same egress proxy and never sees the credential.')}
    ${li('DSH compat settings needed for Token Factory: no <code>developer</code> role, no <code>store</code>, <code>max_tokens</code> (see <code>dsh/tofa.patch.yml</code>). DSH telemetry is disabled.')}
    ${li('Small sample: 2–6 runs per task × effort. Treat success rates as indicative. T2 fails every time on the same spec clause.')}
    ${li('Public latency in the simulation is the measured latency. It assumes the shared endpoint does not slow down under our own traffic.')}
    ${li('Dedicated latency, throughput and queueing are <b>simulated</b> from third-party benchmark data, not measured. The benchmark mix is 8k input / 1k output tokens, while agent requests carry fewer uncached tokens per output token, so capacity is likely conservative. The efficiency slider covers serving optimisations.')}
    ${li('Not modelled: cold starts and capacity availability of dedicated endpoints, failed or retried HTTP requests (none occurred in the measured runs), network differences between campus and this container, and the student-side review time distribution.')}
    ${li('Simulation: time step 0.1 s (0.5 s for day-long windows), deterministic for a seed; every backend sees identical demand (common random numbers).')}</ul></div>`;
}

// ------------------------------------------------------------------ boot
function boot() {
  themeDefaults();
  $('dsh-version').textContent = D.runs[0]?.dsh_version ?? '';
  $('foot').textContent = `Built ${D.builtAt.slice(0, 16).replace('T', ' ')} UTC from ${D.runs.length} recorded runs. Model: openai/gpt-oss-120b via https://api.tokenfactory.nebius.com/v1. Offline-capable: all data and code are inside this file.`;
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
