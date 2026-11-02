// Build the presentation into one self-contained offline file: dashboard/dist/index.html.
//   node dashboard/build.mjs
// Inputs are existing exports, read as they are:
//   data/swebench.json                              9 SWE-bench runs (analysis/build_swebench.py, run once per new run)
//   data/deepseek_v4_endpoint_load/summary.json     API load test summary
import { readFileSync, writeFileSync, mkdirSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const rd = (p) => readFileSync(path.join(ROOT, p), 'utf8');
const json = (p) => JSON.parse(rd(p));

const swe = json('data/swebench.json');
delete swe.groups;
const load = json('data/deepseek_v4_endpoint_load/summary.json');
const ramp = Object.values(load.ratelimit.public.R).find((x) => x.rate_429 > 0);
const data = {
  builtAt: new Date().toISOString(),
  swe,
  bench: {
    totalRequests: load.totals.public_requests,
    // agent-step profile (B): ~10k tokens in, 512 out
    scaling: Object.entries(load.scaling.public.B).map(([k, v]) => ({ c: +k.split('=')[1], decode_p50: v.decode_tps_per_request.p50, lat_p50: v.latency_s.p50, ttft_p50: v.ttft_s.p50 })),
    firstRateLimited: { offered_rpm: ramp.offered_rpm, first_429_s: ramp.first_429_at_s, wait_429_s: ramp.latency_429_s.p50 },
  },
};

// page modules, concatenated in dependency order
const PAGES = ['core', 'run', 'measure', 'endpoints', 'main'].map((f) => `// ---- ${f}.js\n` + rd(`dashboard/src/js/${f}.js`)).join('\n');

const html = `<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n<meta name="viewport" content="width=device-width, initial-scale=1">\n</head>\n<body>\n` +
  rd('dashboard/src/index.html')
    .replace('/*__CSS__*/', () => rd('dashboard/src/style.css'))
    .replace('<!--__SCRIPTS__-->', () => [
      `<script>\n${rd('dashboard/vendor/chart.umd.js')}\n</script>`,
      `<script>window.DEMO_DATA = ${JSON.stringify(data).replace(/</g, '\\u003c')};</script>`,
      `<script>\n${PAGES}\n</script>`,
    ].join('\n')) +
  '\n</body>\n</html>\n';
mkdirSync(path.join(ROOT, 'dashboard/dist'), { recursive: true });
writeFileSync(path.join(ROOT, 'dashboard/dist/index.html'), html);
console.log(`built dashboard/dist/index.html (${(html.length / 1024).toFixed(0)} KB, offline)`);
