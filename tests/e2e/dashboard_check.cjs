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
    for (const view of ['run', 'measure', 'workloads', 'dedicated', 'economics', 'classroom', 'method']) {
      await page.evaluate((v) => { location.hash = v; }, view);
      await page.waitForTimeout(view === 'classroom' ? 2500 : 700);
      if (view === 'economics') {
        await page.selectOption('#e-effort', 'wl-heavy');
        await page.waitForTimeout(500);
        const t = await page.locator('#e-tiles').innerText();
        if (!/public cost per task/i.test(t) || /NaN|undefined/.test(t)) problems.push(`[${scheme}] economics: heavy workload broke tiles`);
        await page.selectOption('#e-effort', 'medium');
        await page.waitForTimeout(300);
      }
      if (view === 'run') {
        await page.click('#replay-all');
        const n = await page.locator('#events li').count();
        if (n < 10) problems.push(`[${scheme}] run: only ${n} trajectory events`);
        // SWE-bench trials: 9 runs, the task, edit diffs, official verdict and the patch are shown
        const r = await page.evaluate(() => ({
          options: document.querySelectorAll('#run-select option').length,
          prompt: document.getElementById('run-prompt').textContent,
          edits: document.querySelectorAll('#events .edit .diff').length,
          verdict: document.getElementById('verdict').innerText,
          patch: document.getElementById('run-patch').textContent,
        }));
        if (r.options !== 9) problems.push(`[${scheme}] run: ${r.options} runs in the selector, expected the 9 SWE-bench trials`);
        if (!/<issue>/.test(r.prompt)) problems.push(`[${scheme}] run: task prompt missing`);
        if (!r.edits) problems.push(`[${scheme}] run: no source-change (edit) diffs in the trajectory`);
        if (!/RESOLVED|UNRESOLVED/.test(r.verdict) || !/fail-to-pass/.test(r.verdict)) problems.push(`[${scheme}] run: official verdict missing`);
        if (!/^diff --git/.test(r.patch)) problems.push(`[${scheme}] run: resulting patch missing`);
        await page.selectOption('#run-select', { index: 6 }); // the unresolved trial; must carry over to section 2
      }
      if (view === 'measure') {
        const m = await page.evaluate(() => ({
          sel: document.getElementById('m-run').value, run: document.getElementById('run-select').value,
          sections: [...document.querySelectorAll('#view-measure h3.msec')].map((h) => h.textContent),
          tiles: document.getElementById('view-measure').innerText,
        }));
        if (m.sel !== m.run) problems.push(`[${scheme}] measure: selected run ${m.sel} differs from section 1 (${m.run})`);
        if (m.sections.length !== 3) problems.push(`[${scheme}] measure: ${m.sections.length} sections, expected 3`);
        if (/NaN|undefined/.test(m.tiles)) problems.push(`[${scheme}] measure: NaN/undefined in the page`);
      }
      if (view === 'classroom') {
        await page.click('#s-sweep');
        await page.waitForFunction(() => !document.getElementById('s-sweep').disabled, null, { timeout: 120000 });
        const txt = await page.locator('#s-compare').innerText();
        if (!/Cost for this session/.test(txt)) problems.push(`[${scheme}] classroom: no comparison output`);
        // workload selector: heavy traces must simulate without errors and say so
        await page.selectOption('#s-effort', 'wl-heavy');
        await page.waitForTimeout(2500);
        const note = await page.locator('#s-active-note').innerText();
        if (!/Heavy H1/.test(note)) problems.push(`[${scheme}] classroom: heavy workload not applied`);
        await page.selectOption('#s-effort', 'medium');
        await page.waitForTimeout(1500);
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
    for (const view of ['run', 'measure', 'workloads', 'dedicated', 'classroom']) {
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
