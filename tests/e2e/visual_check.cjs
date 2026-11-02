// Visual check of the built offline dashboard: are the charts actually drawn?
//   node tests/e2e/visual_check.cjs [outDir]
//
// Opens dashboard/dist/index.html over file:// with every network request blocked, visits every
// tab in light and dark mode at two viewport sizes, and for every visible <canvas> checks the
// rendered pixels, not just the Chart.js datasets:
//   * the canvas has a non-zero backing size and CSS size,
//   * at least MIN_PAINTED of its pixels are painted,
//   * every visible dataset's colour is present in the pixels (translucent colours are blended
//     over the panel background), so axes and grid lines alone do not pass,
// and that no chart error notice or diagnostics banner is shown. Exit code 1 on any failure.
const { chromium } = require('playwright');
const path = require('path');
const fs = require('fs');

const MIN_PAINTED = 0.01; // 1% of canvas pixels
const MIN_COLOR_PIXELS = 25; // pixels that must match a dataset colour
const VIEWS = ['run', 'measure', 'workloads', 'dedicated', 'economics', 'classroom', 'method'];

function inspectCanvases(MIN_COLOR_PIXELS) {
  // runs in the page (constants are passed in as arguments)
  const toRgba = (color) => {
    const c = document.createElement('canvas');
    c.width = c.height = 1;
    const x = c.getContext('2d');
    x.clearRect(0, 0, 1, 1);
    x.fillStyle = '#000';
    x.fillStyle = color;
    x.fillRect(0, 0, 1, 1);
    return [...x.getImageData(0, 0, 1, 1).data];
  };
  // getImageData returns un-premultiplied RGBA and the canvas background is transparent, so a
  // translucent fill shows up as its own RGB with reduced alpha (or blended where it overlaps lines).
  const out = [];
  for (const canvas of document.querySelectorAll('.view:not([hidden]) canvas')) {
    const r = canvas.getBoundingClientRect();
    const res = { id: canvas.id, w: canvas.width, h: canvas.height, cssW: Math.round(r.width), cssH: Math.round(r.height), painted: 0, missing: [] };
    const chart = window.Chart.getChart(canvas);
    if (!chart) {
      if (canvas.dataset.onDemand === undefined) res.missing.push('no Chart instance');
      else res.onDemand = true;
      out.push(res);
      continue;
    }
    if (!canvas.width || !canvas.height) {
      out.push(res);
      continue;
    }
    const data = canvas.getContext('2d').getImageData(0, 0, canvas.width, canvas.height).data;
    let painted = 0;
    for (let i = 3; i < data.length; i += 4) if (data[i] > 0) painted++;
    res.painted = painted / (data.length / 4);
    chart.data.datasets.forEach((ds, i) => {
      if (!chart.isDatasetVisible(i) || !ds.data || !ds.data.some((v) => v !== null && v !== undefined)) return;
      const candidates = [ds.borderColor, ds.backgroundColor].flat().filter((c) => typeof c === 'string' && c !== 'transparent');
      const targets = candidates.map(toRgba).filter((t) => t[3] > 0);
      let hits = 0;
      for (let p = 0; p < data.length && hits < MIN_COLOR_PIXELS; p += 4) {
        for (const t of targets) {
          if (Math.abs(data[p + 3] - t[3]) <= 20 && Math.abs(data[p] - t[0]) <= 14 && Math.abs(data[p + 1] - t[1]) <= 14
            && Math.abs(data[p + 2] - t[2]) <= 14) {
            hits++;
            break;
          }
        }
      }
      if (hits < MIN_COLOR_PIXELS) res.missing.push(`dataset "${ds.label || i}" (${hits} px of its colour)`);
    });
    out.push(res);
  }
  return {
    canvases: out,
    notices: [...document.querySelectorAll('.view:not([hidden]) .chart-error')].map((e) => e.textContent.slice(0, 200)),
    diag: document.getElementById('diag') && !document.getElementById('diag').hidden ? document.getElementById('diag').innerText.slice(0, 400) : null,
  };
}

// Negative control: suppress every canvas drawing call inside the Cost Curves view (the reported
// symptom: blank charts, but controls and text present) and require the check to catch it.
const BLANK_ECONOMICS = () => {
  const P = CanvasRenderingContext2D.prototype;
  for (const m of ['fill', 'stroke', 'fillRect', 'strokeRect', 'fillText', 'strokeText', 'drawImage']) {
    const orig = P[m];
    P[m] = function patched(...args) {
      if (this.canvas && this.canvas.closest && this.canvas.closest('#view-economics')) return undefined;
      return orig.apply(this, args);
    };
  }
};

async function negativeControl(browser, root) {
  const ctx = await browser.newContext({ viewport: { width: 1400, height: 1000 } });
  const page = await ctx.newPage();
  await page.route('**/*', (r) => (r.request().url().startsWith('file://') ? r.continue() : r.abort()));
  await page.addInitScript(BLANK_ECONOMICS);
  await page.goto('file://' + path.join(root, 'dashboard/dist/index.html') + '#economics');
  await page.waitForTimeout(1200);
  const res = await page.evaluate(inspectCanvases, MIN_COLOR_PIXELS);
  await ctx.close();
  const detected = res.canvases.filter((c) => c.painted < MIN_PAINTED || c.missing.length).map((c) => c.id);
  return { detected, total: res.canvases.length };
}

// Diagnostics control: make the logarithmic scale throw (as an incompatible engine might) and require
// the page to show the error in the chart box and in the diagnostics banner, not a silent blank.
async function diagnosticsControl(browser, root) {
  const ctx = await browser.newContext({ viewport: { width: 1400, height: 1000 } });
  const page = await ctx.newPage();
  await page.route('**/*', (r) => (r.request().url().startsWith('file://') ? r.continue() : r.abort()));
  await page.goto('file://' + path.join(root, 'dashboard/dist/index.html') + '#run');
  await page.waitForTimeout(500);
  await page.evaluate(() => {
    const Log = window.Chart.registry.getScale('logarithmic');
    Log.prototype.buildTicks = () => { throw new Error('simulated log-scale failure'); };
    location.hash = 'economics';
  });
  await page.waitForTimeout(1200);
  const r = await page.evaluate(() => ({
    notices: [...document.querySelectorAll('#view-economics .chart-error')].map((e) => e.textContent),
    banner: !document.getElementById('diag').hidden,
    note: document.getElementById('e-curve-note').textContent.length,
  }));
  await ctx.close();
  return r;
}

(async () => {
  const root = path.resolve(__dirname, '../..');
  const out = process.argv[2] || path.join(root, '.cache', 'visual');
  fs.mkdirSync(out, { recursive: true });
  const browser = await chromium.launch();
  const problems = [];
  const control = await negativeControl(browser, root);
  if (control.total < 2 || control.detected.length !== control.total) {
    problems.push(`negative control: blanked Cost Curves charts were not all detected (${control.detected.join(',')} of ${control.total})`);
  } else {
    console.log(`negative control OK: blanked charts detected (${control.detected.join(', ')})`);
  }
  const dc = await diagnosticsControl(browser, root);
  if (dc.notices.length !== 2 || !dc.notices.every((t) => /simulated log-scale failure/.test(t)) || !dc.banner || !dc.note) {
    problems.push(`diagnostics control: failure not surfaced (${JSON.stringify(dc).slice(0, 300)})`);
  } else {
    console.log('diagnostics control OK: a throwing chart shows its error in place and in the banner; the rest of the view still renders');
  }
  let checked = 0;
  for (const viewport of [{ width: 1400, height: 1000 }, { width: 1024, height: 720 }]) {
    for (const scheme of ['light', 'dark']) {
      const ctx = await browser.newContext({ viewport, colorScheme: scheme });
      const page = await ctx.newPage();
      const tag = `${scheme} ${viewport.width}px`;
      page.on('pageerror', (e) => problems.push(`[${tag}] pageerror: ${e.message}`));
      page.on('console', (m) => { if (m.type() === 'error' && !/ERR_FAILED|fonts\.g/.test(m.text())) problems.push(`[${tag}] console: ${m.text()}`); });
      await page.route('**/*', (r) => (r.request().url().startsWith('file://') ? r.continue() : r.abort()));
      // open each tab directly by URL (a fresh load), then also by in-page navigation
      for (const mode of ['direct', 'navigate']) {
        if (mode === 'navigate') await page.goto('file://' + path.join(root, 'dashboard/dist/index.html'));
        for (const view of VIEWS) {
          if (mode === 'direct') await page.goto('file://' + path.join(root, 'dashboard/dist/index.html') + '#' + view);
          else await page.evaluate((v) => { location.hash = v; }, view);
          await page.waitForTimeout(view === 'classroom' ? 2500 : 900);
          if (view === 'classroom' && mode === 'direct') {
            await page.click('#s-sweep');
            await page.waitForFunction(() => !document.getElementById('s-sweep').disabled, null, { timeout: 120000 });
            await page.waitForTimeout(800);
          }
          const res = await page.evaluate(inspectCanvases, MIN_COLOR_PIXELS);
          for (const c of res.canvases) {
            if (c.onDemand) continue; // drawn only when the user runs it (classroom sweep); checked after the click
            checked++;
            const where = `[${tag} ${mode}] #${view} ${c.id}`;
            if (!c.w || !c.h || !c.cssW || !c.cssH) problems.push(`${where}: zero size (canvas ${c.w}x${c.h}, css ${c.cssW}x${c.cssH})`);
            else if (c.painted < MIN_PAINTED) problems.push(`${where}: blank (${(100 * c.painted).toFixed(2)}% painted)`);
            for (const m of c.missing) problems.push(`${where}: not drawn: ${m}`);
          }
          for (const n of res.notices) problems.push(`[${tag} ${mode}] #${view}: chart error notice: ${n}`);
          if (res.diag) problems.push(`[${tag} ${mode}] #${view}: diagnostics banner: ${res.diag}`);
          if (mode === 'direct' && viewport.width === 1400) await page.screenshot({ path: path.join(out, `${scheme}-${view}.png`), fullPage: true });
        }
      }
      await ctx.close();
    }
  }
  await browser.close();
  if (problems.length) {
    console.log(`VISUAL CHECK FAILED (${problems.length} problems, ${checked} canvas checks):\n` + problems.join('\n'));
    process.exit(1);
  }
  console.log(`visual check OK: ${checked} canvas checks, every chart drawn with all visible datasets; screenshots in ${out}`);
})();
