// Headless check of the built offline dashboard with ALL network blocked.
//   node tests/e2e/dashboard_check.cjs [outDir]
// Fails on any console error, page error, empty chart, or missing simulation output.
const { launch } = require('./browser.cjs');
const path = require('path');
const fs = require('fs');

(async () => {
  const root = path.resolve(__dirname, '../..');
  const out = process.argv[2] || path.join(root, '.cache', 'screens');
  fs.mkdirSync(out, { recursive: true });
  const browser = await launch();
  const problems = [];
  for (const scheme of ['light', 'dark']) {
    const ctx = await browser.newContext({ viewport: { width: 1400, height: 1000 }, colorScheme: scheme });
    const page = await ctx.newPage();
    let blocked = 0;
    await page.route('**/*', (route) => {
      if (route.request().url().startsWith('file://')) return route.continue();
      blocked++;
      return route.abort();
    });
    page.on('console', (m) => { if (m.type() === 'error' && !/fonts\.googleapis|ERR_FAILED/.test(m.text())) problems.push(`[${scheme}] console: ${m.text()}`); });
    page.on('pageerror', (e) => problems.push(`[${scheme}] pageerror: ${e.message}`));
    await page.goto('file://' + path.join(root, 'dashboard/dist/index.html'));
    for (const view of ['run', 'measure', 'endpoints']) {
      await page.evaluate((v) => { location.hash = v; }, view);
      await page.waitForTimeout(view === 'classroom' ? 2500 : 700);
      // presentation content: only the DeepSeek / SWE-bench story, no legacy workloads or model
      const visible = await page.evaluate(() => document.querySelector('header').innerText + '\n' + document.querySelector('.view:not([hidden])').innerText + '\n' + document.querySelector('footer').innerText);
      for (const bad of [/Bigger tasks/i, /\bM1\b/, /\bH1\b/, /gpt-oss/i, /\bT[123]\b/]) {
        if (bad.test(visible)) problems.push(`[${scheme}] ${view}: visible legacy content ${bad}`);
      }
      if (/NaN|undefined/.test(visible)) problems.push(`[${scheme}] ${view}: NaN/undefined in the page`);
      const dupIds = await page.evaluate(() => { const ids = [...document.querySelectorAll('[id]')].map((e) => e.id); return ids.filter((x, i) => ids.indexOf(x) !== i); });
      if (dupIds.length) problems.push(`[${scheme}] ${view}: duplicate element ids ${[...new Set(dupIds)].join(',')}`);
      if (view === 'run') {
        // every one of the 9 real runs can be selected and replayed
        const ids = await page.evaluate(() => [...document.querySelectorAll('#run-select option')].map((o) => o.value));
        if (ids.length !== 9) problems.push(`[${scheme}] run: ${ids.length} runs in the selector, expected 9`);
        for (const id of ids) {
          await page.selectOption('#run-select', id);
          await page.click('#replay-all');
          const n = await page.evaluate(() => ({ steps: document.querySelectorAll('#events li.step').length, lane: document.querySelectorAll('#lane span').length }));
          if (n.steps < 10 || !n.lane) problems.push(`[${scheme}] run ${id}: trajectory not shown (${JSON.stringify(n)})`);
        }
        const r = await page.evaluate(() => ({
          patchPanel: !!document.getElementById('run-patch') || /Resulting patch/i.test(document.getElementById('view-run').innerText),
          report: /What the agent reported|fail-to-pass|pass-to-pass/i.test(document.getElementById('view-run').innerText),
          edits: document.querySelectorAll('#events .edit .diff').length,
          metrics: document.querySelectorAll('#run-metrics > div').length,
          result: document.getElementById('run-result').innerText,
        }));
        if (r.patchPanel || r.report) problems.push(`[${scheme}] run: patch panel or verbose judge report still shown`);
        if (!r.edits) problems.push(`[${scheme}] run: no code-edit diffs in the trajectory`);
        if (r.metrics !== 3 || !/RESOLVED/.test(r.result)) problems.push(`[${scheme}] run: expected 3 metrics and a result indicator`);
        await page.click('#replay-play');
        await page.waitForTimeout(1200);
        const during = await page.locator('#events li').count();
        if (!during) problems.push(`[${scheme}] run: replay shows nothing after 1.2 s`);
        await page.selectOption('#run-select', { index: 6 }); // must carry over to section 2
      }
      if (view === 'measure') {
        const m = await page.evaluate(() => {
          const ch = window.Chart.getChart(document.getElementById('c-decode-time'));
          const cost = window.Chart.getChart(document.getElementById('c-costsplit'));
          const rgb = (c) => { const x = document.createElement('canvas').getContext('2d'); x.fillStyle = c; const h = x.fillStyle; return [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16)); };
          const [cached, uncached, output] = cost.data.datasets.map((d) => rgb(Array.isArray(d.backgroundColor) ? d.backgroundColor[0] : d.backgroundColor));
          const dist = (a, b) => Math.hypot(a[0] - b[0], a[1] - b[1], a[2] - b[2]);
          return {
            sel: document.getElementById('m-run').value, run: document.getElementById('run-select').value,
            sections: document.querySelectorAll('#view-measure h3.msec').length,
            labels: ch.data.labels, values: ch.data.datasets[0].data, type: ch.config.type, datasets: ch.data.datasets.length,
            colorGap: Math.min(dist(cached, uncached), dist(cached, output), dist(uncached, output)),
          };
        });
        if (m.sel !== m.run) problems.push(`[${scheme}] measure: selected run differs from section 1`);
        if (m.sections !== 3) problems.push(`[${scheme}] measure: ${m.sections} sections, expected 3`);
        if (m.type !== 'line' || m.datasets !== 1 || m.labels.join(',') !== 'A1,B1,C1,A2,B2,C2,A3,B3,C3') problems.push(`[${scheme}] measure: decode chart is not the 9-point chronological line (${m.labels})`);
        if (Math.round(Math.min(...m.values)) !== 23 || Math.round(Math.max(...m.values)) !== 404) problems.push(`[${scheme}] measure: decode range ${Math.min(...m.values)}–${Math.max(...m.values)}, expected 23–404`);
        if (m.colorGap < 120) problems.push(`[${scheme}] measure: token colours too similar (min RGB distance ${m.colorGap.toFixed(0)})`);
      }
      if (view === 'endpoints') {
        const t = await page.locator('#view-endpoints').innerText();
        if (!/MEASURED/i.test(t) || !/SCENARIO/i.test(t)) problems.push(`[${scheme}] endpoints: measured/scenario labels missing`);
        const series = () => page.evaluate(() => window.Chart.getChart(document.getElementById('c-ep-speed')).data.datasets.map((d) => d.data));
        const params = { conservative: [400, 1.0, 10], baseline: [500, 0.8, 20], optimistic: [600, 0.6, 40] };
        const conc = [1, 2, 5, 10, 20, 30];
        let prev = null;
        for (const [name, [speed, ttft, perReplica]] of Object.entries(params)) {
          await page.selectOption('#a-endpoints-scenario', name);
          await page.waitForTimeout(150);
          const [pub, ded] = await series();
          conc.forEach((c, i) => {
            const expect = ttft + 512 / (speed * Math.min(1, perReplica / c));
            if (Math.abs(ded[i] - expect) > 1e-9) problems.push(`[${scheme}] endpoints ${name}: c=${c} latency ${ded[i]} ≠ ${expect}`);
            if (ded[i] > pub[i]) problems.push(`[${scheme}] endpoints ${name}: dedicated slower than measured public at c=${c}`);
          });
          if (prev && ded.some((x, i) => x > prev[i])) problems.push(`[${scheme}] endpoints: ${name} slower than the previous scenario`);
          prev = ded;
        }
        await page.selectOption('#a-endpoints-scenario', 'baseline');
        const controls = await page.locator('#view-endpoints input, #view-endpoints select').count();
        if (controls !== 1) problems.push(`[${scheme}] endpoints: ${controls} controls, expected only the scenario selector`);
        const lim = await page.locator('#ep-limits .tile').count();
        if (lim !== 3) problems.push(`[${scheme}] endpoints: rate-limit tiles missing`);
      }
      // every visible canvas must have a Chart instance with data
      const empty = await page.evaluate(() => [...document.querySelectorAll('.view:not([hidden]) canvas')]
        .filter((c) => { const ch = window.Chart.getChart(c); return !ch || !ch.data.datasets.length || !ch.data.datasets.some((d) => d.data.length); })
        .map((c) => c.id));
      if (empty.length) problems.push(`[${scheme}] ${view}: empty charts ${empty.join(',')}`);
      await page.screenshot({ path: path.join(out, `${scheme}-${view}.png`), fullPage: true });
    }
    // phone width: no horizontal page scroll
    await page.setViewportSize({ width: 400, height: 900 });
    for (const view of ['run', 'measure', 'endpoints']) {
      await page.evaluate((v) => { location.hash = v; }, view);
      await page.waitForTimeout(600);
      const over = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
      if (over > 1) problems.push(`[${scheme}] ${view}: horizontal overflow ${over}px at 400px`);
    }
    await page.screenshot({ path: path.join(out, `${scheme}-phone-classroom.png`), fullPage: false });
    console.log(`${scheme}: blocked ${blocked} network requests (fonts) - page still rendered`);
    await ctx.close();
  }
  await browser.close();
  if (problems.length) {
    console.log('PROBLEMS:\n' + problems.join('\n'));
    process.exit(1);
  }
  console.log('dashboard check OK; screenshots in ' + out);
})();
