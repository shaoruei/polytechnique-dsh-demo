// The classroom page replays the 9 SWE-bench runs: unloaded, each must reproduce its measured cost and requests.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { simulate } from '../../model/sim.js';

const swe = JSON.parse(readFileSync(new URL('../../data/swebench.json', import.meta.url)));

test('each SWE-bench run replays alone with its measured public cost and request count', () => {
  for (const r of swe.runs) {
    const traj = [{ task: r.instance_id, effort: r.effort, success: r.success, lead_s: r.trajectory.lead_s, steps: r.trajectory.steps }];
    const res = simulate(traj, { students: 1, tasksPerStudent: 1, pattern: 'class', windowHours: 1, syncMinutes: 0.01, releaseSpan: 0, reviewMinutes: 0, seed: 1 },
      { kind: 'public', rpm: 1000, tpm: 2_000_000, tpmCountsCached: true }, swe.pricing);
    assert.equal(res.summary.requests, r.metrics.llm_requests, r.run_id);
    assert.ok(Math.abs(res.summary.publicCostUsd - r.metrics.cost_usd) < 2e-6, `${r.run_id}: ${res.summary.publicCostUsd} vs ${r.metrics.cost_usd}`);
  }
});

test('decode-speed chart values are the recorded per-run medians in run order', () => {
  const labels = swe.runs.map((r) => r.label).join(',');
  assert.equal(labels, 'A1,B1,C1,A2,B2,C2,A3,B3,C3');
  const v = swe.runs.map((r) => Math.round(r.metrics.decode_tps_p50));
  assert.deepEqual(v, [404, 309, 220, 64, 23, 242, 263, 273, 335]);
});
