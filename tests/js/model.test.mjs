// Tests for the capacity, cost and classroom-simulation model.   Run: node --test tests/js
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

import * as cap from '../../model/capacity.js';
import * as cost from '../../model/cost.js';
import { simulate, autoSize } from '../../model/sim.js';
import { trajectoriesFrom, perTaskProfile } from '../../model/data.js';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const load = (f) => JSON.parse(readFileSync(path.join(ROOT, f), 'utf8'));
const pricing = load('data/pricing.json');
const profiles = load('data/dedicated_profiles.json');
const runs = load('data/runs.json');
const H100 = profiles.gpus.h100;
const PRICES = pricing.public;

// Synthetic trajectory: 3 requests of known size and latency.
const synth = (over = {}) => ({
  runId: 'synthetic', task: 'tx', effort: 'medium', success: true, lead_s: 1,
  steps: [
    { u: 1000, c: 4000, o: 100, lat: 1.0, gap: 0.5 },
    { u: 500, c: 5000, o: 200, lat: 1.0, gap: 0.5 },
    { u: 300, c: 5500, o: 50, lat: 0.5, gap: 0 },
  ],
  ...over,
});
const baseScenario = {
  students: 20, tasksPerStudent: 3, pattern: 'class', windowHours: 1, syncMinutes: 2, releaseSpan: 0.8,
  reviewMinutes: 1, retryFailed: false, seed: 42, effort: 'medium',
};

// ---------------------------------------------------------------- data sanity / provenance
test('benchmark points imply a consistent ~4-GPU serving instance for H100 (interpretation check)', () => {
  // InferenceX reported concurrency at 90/143/197 tok/s/user: ~32, ~13, ~6
  const reported = { 90: 32, 143: 13, 197: 6 };
  for (const p of H100.points) {
    const gpus = (reported[p.interactivity] * p.interactivity) / (p.tps_per_gpu / 9);
    assert.ok(Math.abs(gpus - 4) < 0.25, `implied GPUs ${gpus}`);
  }
});

test('measured runs carry exact provider usage and an independently recomputed cost', () => {
  const usable = runs.runs.filter((r) => r.usable);
  assert.ok(usable.length >= 9, 'enough measured runs');
  for (const r of usable) {
    assert.ok(Math.abs(r.metrics.cost_usd - r.metrics.cost_usd_recomputed) < 1e-6, r.run_id);
    const t = r.trajectory.steps.reduce((a, s) => ({ u: a.u + s.u, c: a.c + s.c, o: a.o + s.o }), { u: 0, c: 0, o: 0 });
    assert.equal(t.u, r.metrics.uncached_input_tokens);
    assert.equal(t.c, r.metrics.cached_input_tokens);
    assert.equal(t.o, r.metrics.output_tokens);
    assert.ok(Math.abs(cost.publicCost({ uncached: t.u, cached: t.c, output: t.o }, PRICES) - r.metrics.cost_usd) < 1e-6);
  }
});

// ---------------------------------------------------------------- capacity
test('interpolation reproduces the benchmark points and is monotone', () => {
  for (const p of cap.curvePoints(H100)) {
    assert.ok(Math.abs(cap.interactivityAt(H100, p.concurrency) - p.interactivity) < 1e-6);
  }
  let prevSpeed = Infinity;
  let prevThroughput = 0;
  for (let c = 0.5; c <= 64; c += 0.5) {
    const s = cap.interactivityAt(H100, c);
    const thr = cap.outputThroughputAt(H100, c);
    assert.ok(s <= prevSpeed + 1e-9, 'per-user speed never increases with load');
    assert.ok(thr >= prevThroughput - 1e-9, 'aggregate throughput never decreases with load');
    prevSpeed = s;
    prevThroughput = thr;
  }
  // saturation: at most +15% over the last benchmark point
  const last = cap.curvePoints(H100).at(-1);
  assert.ok(cap.outputThroughputAt(H100, 1000) <= last.outputTpsPerGpu * 1.15 + 1e-6);
});

test('concurrencyForInteractivity inverts interactivityAt and respects the cap', () => {
  for (const target of [100, 120, 150, 180]) {
    const c = cap.concurrencyForInteractivity(H100, target);
    assert.ok(Math.abs(cap.interactivityAt(H100, c) - target) < 0.01, `target ${target}`);
  }
  assert.equal(cap.concurrencyForInteractivity(H100, 10), H100.max_concurrency_per_gpu);
  assert.equal(cap.concurrencyForInteractivity(H100, 500), 0, 'faster than one stream is impossible');
  assert.ok(cap.capacityPerGpu(profiles.gpus.b200, 90) > cap.capacityPerGpu(H100, 90) * 4);
});

// ---------------------------------------------------------------- cost
test('public cost matches a hand calculation', () => {
  // 1M uncached x $0.15 + 2M cached x $0.10 + 0.5M output x $0.60 = 0.15 + 0.20 + 0.30
  assert.ok(Math.abs(cost.publicCost({ uncached: 1e6, cached: 2e6, output: 5e5 }, PRICES) - 0.65) < 1e-12);
});

test('billed hours per schedule', () => {
  assert.equal(cost.billedHoursPerMonth({ kind: 'always-on' }), 730);
  assert.equal(cost.billedHoursPerMonth({ kind: 'business-hours', hoursPerDay: 10, daysPerMonth: 22 }), 220);
  assert.equal(cost.billedHoursPerMonth({ kind: 'class-only', sessionsPerMonth: 8, sessionHours: 2, warmupHours: 0.25 }), 18);
});

test('analytic break-even agrees with a brute-force sweep (including the sawtooth)', () => {
  const tr = trajectoriesFrom(runs).filter((t) => t.effort === 'medium');
  const perTask = perTaskProfile(tr);
  for (const [gpuKey, schedule, target] of [
    ['h100', { kind: 'always-on' }, 90],
    ['h100', { kind: 'business-hours', hoursPerDay: 10, daysPerMonth: 22 }, 143],
    ['b200', { kind: 'class-only', sessionsPerMonth: 8, sessionHours: 2, warmupHours: 0.25 }, 90],
  ]) {
    const gpu = { profile: profiles.gpus[gpuKey], pricePerGpuHour: pricing.dedicated.gpus[gpuKey].price_per_gpu_hour };
    const opts = { perTask, prices: PRICES, schedule, gpu, targetInteractivity: target, targetUtilization: 0.7, peakFactor: 3 };
    const be = cost.breakEvenTasks(opts);
    const dedAt = (v) => cost.dedicatedSizing({ tasksPerMonth: v, outputPerTask: perTask.tokens.output, schedule, gpu,
      targetInteractivity: target, targetUtilization: 0.7, peakFactor: 3 }).monthlyCost;
    const pubAt = (v) => v * cost.publicCost(perTask.tokens, PRICES);
    // brute force first crossing on a fine grid around the analytic answer
    const top = (be.tasks ?? be.publicTasksPerGpuMonthCost) * 4;
    const step = top / 20000;
    let first = null;
    let lastPublicCheaper = 0;
    for (let v = step; v <= top; v += step) {
      const dedCheaper = dedAt(v) <= pubAt(v);
      if (dedCheaper && first === null) first = v;
      if (!dedCheaper) lastPublicCheaper = v;
    }
    if (be.tasks === null) {
      assert.equal(first, null, `${gpuKey}: no crossing expected (${be.reason})`);
    } else {
      assert.ok(Math.abs(first - be.tasks) <= 2 * step, `${gpuKey} first crossing ${first} vs ${be.tasks}`);
      if (be.permanentFromTasks !== null && be.permanentFromTasks < top) {
        assert.ok(lastPublicCheaper <= be.permanentFromTasks + 2 * step,
          `${gpuKey} public never cheaper after ${be.permanentFromTasks} (last ${lastPublicCheaper})`);
      }
    }
  }
});

test('capacity-aware dedicated cost steps up with volume while naive cost stays flat', () => {
  const gpu = { profile: H100, pricePerGpuHour: 4.5 };
  const schedule = { kind: 'class-only', sessionsPerMonth: 8, sessionHours: 2, warmupHours: 0.25 };
  const small = cost.dedicatedSizing({ tasksPerMonth: 1000, outputPerTask: 1500, schedule, gpu, targetInteractivity: 90, peakFactor: 3 });
  const big = cost.dedicatedSizing({ tasksPerMonth: 500000, outputPerTask: 1500, schedule, gpu, targetInteractivity: 90, peakFactor: 3 });
  assert.equal(small.gpus, 1);
  assert.ok(big.gpus > 10);
  assert.ok(big.monthlyCost > cost.naiveDedicatedCost({ schedule, gpu }) * 10);
  assert.ok(big.utilization <= 0.7 + 1e-9, 'sized to the target utilisation');
});

// ---------------------------------------------------------------- simulation
test('simulation is deterministic for a seed and varies across seeds', () => {
  const tr = trajectoriesFrom(runs);
  const b = { kind: 'public', rpm: 600, tpm: 500000 };
  const a1 = simulate(tr, baseScenario, b, PRICES).summary;
  const a2 = simulate(tr, baseScenario, b, PRICES).summary;
  const a3 = simulate(tr, { ...baseScenario, seed: 43 }, b, PRICES).summary;
  assert.deepEqual(a1, a2);
  assert.notDeepEqual(a1.tokens, a3.tokens);
});

test('single unloaded task on public reproduces the measured trajectory exactly', () => {
  const t = synth();
  const sc = { ...baseScenario, students: 1, tasksPerStudent: 1, syncMinutes: 0, dt: 0.05 };
  const r = simulate([t], sc, { kind: 'public', rpm: 1e9, tpm: 1e12 }, PRICES).summary;
  assert.deepEqual(r.tokens, { uncached: 1800, cached: 14500, output: 350 });
  assert.equal(r.requests, 3);
  const measured = 1 + 1.0 + 0.5 + 1.0 + 0.5 + 0.5;
  assert.ok(Math.abs(r.taskDurationP50 - measured) <= 3 * 0.05 + 1e-9, `${r.taskDurationP50} vs ${measured}`);
  assert.ok(Math.abs(r.publicCostUsd - cost.publicCost({ uncached: 1800, cached: 14500, output: 350 }, PRICES)) < 1e-12);
});

test('token totals are conserved: public and dedicated see identical demand', () => {
  const tr = trajectoriesFrom(runs);
  const sc = { ...baseScenario, retryFailed: true };
  const pub = simulate(tr, sc, { kind: 'public', rpm: 1e9, tpm: 1e12 }, PRICES).summary;
  const ded = simulate(tr, sc, { kind: 'dedicated', profile: H100, replicas: 8 }, PRICES).summary;
  // common random numbers: same trajectories picked; generous capacity -> same retries
  assert.deepEqual(pub.tokens, ded.tokens);
  assert.equal(pub.requests, ded.requests);
  assert.ok(Math.abs(ded.outputTokensGenerated - ded.tokens.output) < 1e-3);
});

test('public rate limits are never exceeded in any fixed minute', () => {
  const tr = trajectoriesFrom(runs);
  const sc = { ...baseScenario, students: 60 };
  const r = simulate(tr, sc, { kind: 'public', rpm: 30, tpm: 150000 }, PRICES);
  for (const m of r.timeline) {
    assert.ok(m.requestsStarted <= 30, `minute ${m.minute}: ${m.requestsStarted} requests`);
    assert.ok(m.tokensIn + m.tokensOut <= 150000, `minute ${m.minute}: ${m.tokensIn + m.tokensOut} tokens`);
  }
  assert.ok(r.summary.meanWaitPerTask > 0, 'throttling causes waiting');
});

test('dynamic rate-limit scaling raises limits under sustained load, capped at 20x', () => {
  const tr = trajectoriesFrom(runs);
  const sc = { ...baseScenario, students: 200, tasksPerStudent: 6, windowHours: 2 };
  const r = simulate(tr, sc, { kind: 'public', rpm: 600, tpm: 500000, dynamicLimits: true }, PRICES).summary;
  const factors = r.rateLimitHistory.map((h) => h.factor);
  assert.ok(factors.length > 3);
  assert.ok(Math.max(...factors) > 1.2, `limits grew: ${factors}`);
  assert.ok(Math.max(...factors) <= 20);
});

test('dedicated concurrency cap is enforced and extra load queues', () => {
  const tr = trajectoriesFrom(runs);
  const sc = { ...baseScenario, students: 80, syncMinutes: 0.2 };
  const r = simulate(tr, sc, { kind: 'dedicated', profile: H100, replicas: 1, maxConcurrencyPerGpu: 4 }, PRICES).summary;
  assert.ok(r.maxPerReplicaInstant <= 4);
  assert.ok(r.maxInflightInstant <= 4);
  assert.ok(r.peakQueued > 0 && r.requestWaitP95 > 0);
});

test('more replicas never make the classroom slower (common random numbers)', () => {
  const tr = trajectoriesFrom(runs);
  const sc = { ...baseScenario, students: 150, syncMinutes: 1 };
  let prev = Infinity;
  for (const replicas of [1, 2, 4, 8]) {
    const r = simulate(tr, sc, { kind: 'dedicated', profile: H100, replicas }, PRICES).summary;
    assert.ok(r.slowdownP95 <= prev * 1.02, `replicas ${replicas}: ${r.slowdownP95} vs ${prev}`);
    prev = r.slowdownP95;
  }
});

test('auto-sizing needs more GPUs for bigger classes, which raises dedicated cost', () => {
  const tr = trajectoriesFrom(runs);
  const sizes = [20, 200, 500].map((students) => autoSize(tr, { ...baseScenario, students, tasksPerStudent: 4, syncMinutes: 1 },
    { kind: 'dedicated', profile: H100 }, PRICES, { sloSlowdown: 1.5 }).replicas);
  assert.ok(sizes[0] <= sizes[1] && sizes[1] <= sizes[2], `${sizes}`);
  assert.ok(sizes[2] > sizes[0], `${sizes}`);
});

test('a 500-student scenario completes quickly enough for live interaction', () => {
  const tr = trajectoriesFrom(runs);
  const t0 = Date.now();
  simulate(tr, { ...baseScenario, students: 500, tasksPerStudent: 6, windowHours: 2 }, { kind: 'dedicated', profile: H100, replicas: 4 }, PRICES);
  assert.ok(Date.now() - t0 < 5000, `${Date.now() - t0} ms`);
});
