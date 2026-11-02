// Build the dashboard into self-contained HTML files (no server, no network needed).
//
//   node dashboard/build.mjs
//
// dist/index.html     offline: data, model, app and Chart.js all inlined (open via file://)
// dist/artifact.html  same page for publishing as a claude.ai Artifact: Chart.js from jsDelivr
//                     (exact npm version) and no document skeleton (the host adds it)
import { readFileSync, writeFileSync, mkdirSync, readdirSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const rd = (p) => readFileSync(path.join(ROOT, p), 'utf8');
const json = (p) => JSON.parse(rd(p));
const CHART_VERSION = '4.4.9';

// Model modules, concatenated in dependency order. Imports are dropped and exports become plain
// declarations; the module names do not collide.
const MODEL_ORDER = ['prng.js', 'capacity.js', 'cost.js', 'sim.js'];
const bundleModel = () =>
  MODEL_ORDER.map((f) => `// ---- model/${f}\n` + rd(`model/${f}`)
    .replace(/^import .*?;\s*$/gms, '')
    .replace(/^export (?=(async )?function|const|let|class)/gm, '')
    .replace(/^\s*\/\/.*\n/gm, '')) // drop full-line comments (development notes, not presentation content)
    .join('\n');

// Presentation data: DeepSeek-V4-Flash SWE-bench runs and the API load test only.
const data = {
  builtAt: new Date().toISOString(),
  swe: json('data/swebench.json'),
  bench: json('data/endpoint_bench.json'),
};
delete data.swe.groups; // not shown

const body = rd('dashboard/src/page.html');
const css = rd('dashboard/src/style.css');
const app = rd('dashboard/src/app.js');
const dataScript = `<script>window.DEMO_DATA = ${JSON.stringify(data).replace(/</g, '\\u003c')};</script>`;
const appScript = `<script type="module">\n${bundleModel()}\n// ---- app\n${app}\n</script>`;

function page({ chartTag, skeleton }) {
  const inner = body
    .replace('/*__CSS__*/', () => css) // function form: no $-pattern expansion
    .replace('<!--__SCRIPTS__-->', () => `${chartTag}\n${dataScript}\n${appScript}`);
  if (!skeleton) return inner;
  return `<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n` +
    `<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n</head>\n<body>\n${inner}\n</body>\n</html>\n`;
}

mkdirSync(path.join(ROOT, 'dashboard/dist'), { recursive: true });
const chartInline = `<script>\n${rd('dashboard/vendor/chart.umd.js')}\n</script>`;
const chartCdn = `<script src="https://cdn.jsdelivr.net/npm/chart.js@${CHART_VERSION}/dist/chart.umd.js"></script>`;
writeFileSync(path.join(ROOT, 'dashboard/dist/index.html'), page({ chartTag: chartInline, skeleton: true }));
writeFileSync(path.join(ROOT, 'dashboard/dist/artifact.html'), page({ chartTag: chartCdn, skeleton: false }));
const size = (f) => (readFileSync(path.join(ROOT, 'dashboard/dist', f)).length / 1024).toFixed(0) + ' KB';
console.log(`built dashboard/dist/index.html (${size('index.html')}, offline) and artifact.html (${size('artifact.html')}); ` +
  `${data.swe.runs.length} SWE-bench runs, ${data.bench.totals.public_requests} API test requests`);
