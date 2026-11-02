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
const MODEL_ORDER = ['prng.js', 'capacity.js', 'cost.js', 'data.js', 'sim.js'];
const bundleModel = () =>
  MODEL_ORDER.map((f) => `// ---- model/${f}\n` + rd(`model/${f}`)
    .replace(/^import .*?;\s*$/gms, '')
    .replace(/^export (?=(async )?function|const|let|class)/gm, ''))
    .join('\n');

const provenance = json('data/provenance/tofa_models_verbose_2026-10-30.json');
const data = {
  builtAt: new Date().toISOString(),
  runs: json('data/runs.json').runs,
  workload: json('data/workload.json'),
  pricing: json('data/pricing.json'),
  profiles: json('data/dedicated_profiles.json'),
  ledger: json('data/experiment_ledger.json'),
  replays: json('data/replays.json').runs,
  tasks: json('data/tasks.json').tasks,
  rateLimitInference: json('data/rate_limit_inference.json'),
  dedicatedBenchmark: json('data/dedicated_benchmark.json'),
  workloadComparison: (() => { const w = json('data/workload_comparison.json'); delete w.groups.pilot?.context_growth; return w; })(),
  apiSnapshot: { retrieved_at: provenance.retrieved_at, pricing: provenance.entry.pricing, limits: provenance.entry.per_request_limits },
};
// keep the bundle small: per-request detail is only needed for the context-growth chart
for (const r of data.runs) {
  r.metrics.requests = (r.metrics.requests || []).map((q) => ({
    p: q.prompt_tokens, c: q.cached_tokens, o: q.completion_tokens, ttft: q.ttft_s, lat: q.latency_s, tps: q.decode_tps,
  }));
}

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
  `${data.runs.length} runs, ${readdirSync(path.join(ROOT, 'runs')).length} run folders`);
