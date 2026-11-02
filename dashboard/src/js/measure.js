// Page 2 · Measure it: task overview, tokens & caching, and the nine-run decode-speed chart.
// "this run" = the run selected (shared with page 1); "all 9" = across the nine runs.
const TOK = () => ({ cached: css('--tok-cached'), uncached: css('--tok-uncached'), output: css('--tok-output') });
const scope = (sel) => `<span class="scope ${sel ? 'sel' : 'agg'}">${sel ? 'this run' : 'all 9'}</span>`;
const statTile = (label, value, agg, key = false) =>
  `<div class="tile${key ? ' key' : ''}"><span class="label">${scope(true)}${label}</span><span class="value">${value}</span><span class="agg">${scope(false)}${agg}</span></div>`;
PAGES.measure = {
  html: () => `
    <div class="section-head row">
      <h2>2 · Measure it</h2>
      <div class="filters"><label for="m-run">Selected run</label><select id="m-run">${runOptions()}</select></div>
    </div>
    <h3 class="msec"><b>A</b> Task overview</h3>
    <div class="tiles tiles-3" id="m-tiles-task"></div>
    <h3 class="msec"><b>B</b> Token usage &amp; caching</h3>
    <div class="grid msec-grid">
      <div class="tiles tiles-stack" id="m-tiles-tokens"></div>
      <figure class="panel"><figcaption>Cost per run by token type ${ev('measured')}</figcaption><div class="chart"><canvas id="c-costsplit"></canvas></div></figure>
    </div>
    <h3 class="msec"><b>C</b> Latency &amp; generation speed</h3>
    <figure class="panel headline"><figcaption>Public decode speed over time · median of each run ${ev('measured')}</figcaption><div class="chart xl"><canvas id="c-decode-time"></canvas></div>
      <ul class="takeaways" id="m-takeaways"></ul>
      <p class="note" id="m-decode-note"></p>
    </figure>`,
  init() {
    $('m-run').addEventListener('change', (e) => { selectRun(e.target.value); dirty.add('run'); this.draw(); });
  },
  draw: () => drawMeasure(),
};

function drawMeasure() {
  $('m-run').value = currentRun.run_id;
  const r = currentRun;
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
