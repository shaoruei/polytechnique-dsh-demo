// Read-only check that export/ is directly usable by the existing capacity/cost model:
// each exported trajectory, replayed by model/sim.js simulate() as ONE unloaded public task,
// must reproduce its measured tokens, public cost and duration. Nothing is modified.
// Usage: node experiments/swebench_public_v4flash/scripts/check_sim_compat.mjs
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import assert from 'node:assert/strict';
import { simulate } from '../../../model/sim.js';
import * as cost from '../../../model/cost.js';

const EXP = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const trajectories = JSON.parse(readFileSync(path.join(EXP, 'export/trajectories.json'), 'utf8'));
const runs = JSON.parse(readFileSync(path.join(EXP, 'export/runs.json'), 'utf8'));
const PRICES = runs.pricing_public;
const sc = { students: 1, tasksPerStudent: 1, pattern: 'class', windowHours: 1, syncMinutes: 0, releaseSpan: 0.8,
  reviewMinutes: 0, retryFailed: false, seed: 1, effort: 'high', dt: 0.05 };
for (const t of trajectories) {
  const r = runs.runs.find((x) => x.run_id === t.run_id).metrics;
  const s = simulate([t], sc, { kind: 'public', rpm: 1e9, tpm: 1e12 }, PRICES).summary;
  assert.deepEqual(s.tokens, { uncached: r.uncached_input_tokens, cached: r.cached_input_tokens, output: r.output_tokens }, t.run_id);
  assert.equal(s.requests, r.llm_requests);
  const measured = t.lead_s + t.steps.reduce((a, x) => a + x.lat + x.gap, 0);
  assert.ok(Math.abs(s.taskDurationP50 - measured) <= 0.05 * (t.steps.length * 2 + 2), `${t.run_id}: ${s.taskDurationP50} vs ${measured}`);
  assert.ok(Math.abs(s.publicCostUsd - r.cost_usd) < 1e-6, `${t.run_id}: cost ${s.publicCostUsd} vs ${r.cost_usd}`);
  console.log(`ok ${t.run_id}: ${s.requests} req, ${s.taskDurationP50.toFixed(2)} s (measured ${measured.toFixed(2)}), $${s.publicCostUsd.toFixed(6)}`);
}
console.log(`all ${trajectories.length} trajectories reproduce their measured tokens, cost and duration in model/sim.js`);
