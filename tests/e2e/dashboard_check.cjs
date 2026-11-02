// Headless check of the built offline dashboard with ALL network blocked.
//   node tests/e2e/dashboard_check.cjs [outDir]
// Fails on any console error, page error, empty chart, or missing simulation output.
const { chromium } = require('playwright');
const path = require('path');
const fs = require('fs');

(async () => {
  const root = path.resolve(__dirname, '../..');
  const out = process.argv[2] || path.join(root, '.cache', 'screens');
  fs.mkdirSync(out, { recursive: true });
  const browser = await chromium.launch();
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
    for (const view of ['run', 'measure', 'dedicated', 'economics', 'classroom', 'method']) {
      await page.evaluate((v) => { location.hash = v; }, view);
      await page.waitForTimeout(view === 'classroom' ? 2500 : 700);
      if (view === 'run') {
        await page.click('#replay-all');
        const n = await page.locator('#events li').count();
        if (n < 10) problems.push(`[${scheme}] run: only ${n} trajectory events`);
      }
      if (view === 'classroom') {
        await page.click('#s-sweep');
        await page.waitForFunction(() => !document.getElementById('s-sweep').disabled, null, { timeout: 120000 });
        const txt = await page.locator('#s-compare').innerText();
        if (!/Cost for this session/.test(txt)) problems.push(`[${scheme}] classroom: no comparison output`);
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
    for (const view of ['run', 'measure', 'dedicated', 'classroom']) {
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
