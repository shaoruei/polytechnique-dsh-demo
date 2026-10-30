// Compute the headline numbers quoted in docs/REPORT.md from the same model the dashboard uses.
//   node analysis/key_findings.mjs      -> data/findings.json (+ printed summary)
import { readFileSync, writeFileSync } from 'node:fs';
import { capacityPerGpu, interactivityAt } from '../model/capacity.js';
import { breakEvenTasks, publicCost, billedHoursPerMonth } from '../model/cost.js';
import { simulate, autoSize } from '../model/sim.js';
import { trajectoriesFrom, perTaskProfile } from '../model/data.js';

const j = (p) => JSON.parse(readFileSync(new URL('../' + p, import.meta.url)));
const pricing = j('data/pricing.json');
const prof = j('data/dedicated_profiles.json');
const tr = trajectoriesFrom(j('data/runs.json'));
const PR = pricing.public;
const per = perTaskProfile(tr.filter((t) => t.effort === 'medium'));
const out = { generatedAt: new Date().toISOString(), perTaskMedium: per, costPerTask: publicCost(per.tokens, PR), breakEven: [], classroom: [] };

const schedules = {
  'class-only (8 x 2h + 15 min warm-up)': { kind: 'class-only', sessionsPerMonth: 8, sessionHours: 2, warmupHours: 0.25 },
  'business hours (10h x 22d)': { kind: 'business-hours', hoursPerDay: 10, daysPerMonth: 22 },
  'always-on 24/7': { kind: 'always-on' },
};
for (const gk of ['h100', 'h200', 'b200']) {
  for (const speed of [90, 143]) {
    for (const eff of [1, 2]) {
      for (const [sname, sched] of Object.entries(schedules)) {
        const gpu = { profile: prof.gpus[gk], pricePerGpuHour: pricing.dedicated.gpus[gk].price_per_gpu_hour };
        const be = breakEvenTasks({ perTask: per, prices: PR, schedule: sched, gpu, targetInteractivity: speed, targetUtilization: 0.7, peakFactor: 3, efficiency: eff });
        const perGpu = capacityPerGpu(gpu.profile, speed, eff);
        // utilisation (of billed hours, at the target speed) needed to match public price
        const breakEvenUtil = (gpu.pricePerGpuHour * per.tokens.output) / (perGpu * 3600 * out.costPerTask);
        out.breakEven.push({ gpu: gk, speed, efficiency: eff, schedule: sname, billedHours: billedHoursPerMonth(sched),
          tasksPerMonth: be.tasks, permanentFrom: be.permanentFromTasks ?? null, reason: be.reason ?? null, breakEvenUtil });
      }
    }
  }
}

const sc = (students) => ({ students, tasksPerStudent: 6, pattern: 'class', windowHours: 2, syncMinutes: 3, releaseSpan: 0.8,
  reviewMinutes: 2, retryFailed: true, seed: 7, effort: 'medium' });
for (const students of [20, 100, 200, 500]) {
  const row = { students };
  for (const [label, b] of [
    ['public_default', { kind: 'public', rpm: 600, tpm: 500000, dynamicLimits: true }],
    ['public_20x', { kind: 'public', rpm: 600, tpm: 500000, rateLimitMultiplier: 20 }],
  ]) {
    const s = simulate(tr, sc(students), b, PR).summary;
    row[label] = { costSession: s.publicCostUsd, p50: s.taskDurationP50, p95: s.taskDurationP95, slowdownP95: s.slowdownP95, peakTpm: s.peakTpm, peakRpm: s.peakRpm, peakAgents: s.peakActiveAgents, tasks: s.tasksAttempted, requests: s.requests };
  }
  for (const gk of ['h100', 'b200']) {
    const a = autoSize(tr, sc(students), { kind: 'dedicated', profile: prof.gpus[gk], targetInteractivity: 90 }, PR, { sloSlowdown: 1.5 });
    const s = a.result.summary;
    const hours = Math.max(2, s.makespanS / 3600) + 0.25;
    row[`dedicated_${gk}`] = { replicas: a.replicas, costSession: a.replicas * pricing.dedicated.gpus[gk].price_per_gpu_hour * hours,
      p50: s.taskDurationP50, p95: s.taskDurationP95, slowdownP95: s.slowdownP95, vsPublicP95: s.vsMeasuredPublicP95, slotUtil: s.slotUtilization };
  }
  out.classroom.push(row);
}
writeFileSync(new URL('../data/findings.json', import.meta.url), JSON.stringify(out, null, 1) + '\n');

const f = (x, d = 2) => (x == null ? '-' : Number(x).toFixed(d));
console.log(`medium task: ${f(per.requests, 1)} req, ${Math.round(per.tokens.prompt_plus_output)} tokens, public $${f(out.costPerTask, 4)}/task, success ${f(per.successRate * 100, 0)}%`);
console.log('\nbreak-even (peak factor 3, 70% util):');
for (const r of out.breakEven) console.log(`  ${r.gpu} @${r.speed} eff${r.efficiency} ${r.schedule.padEnd(38)} ${r.tasksPerMonth ? Math.round(r.tasksPerMonth) + ' tasks/mo' : 'never'}  (needs ${f(r.breakEvenUtil * 100, 0)}% util)`);
console.log('\nclassroom (6 tasks/student, 2h, 3-min start spread), per session:');
for (const r of out.classroom) {
  console.log(`  ${String(r.students).padStart(3)} students: public default $${f(r.public_default.costSession)} p95 ${f(r.public_default.p95, 0)}s (x${f(r.public_default.slowdownP95, 1)}) | public 20x $${f(r.public_20x.costSession)} p95 ${f(r.public_20x.p95, 0)}s | ` +
    `H100 x${r.dedicated_h100.replicas} $${f(r.dedicated_h100.costSession)} p95 ${f(r.dedicated_h100.p95, 0)}s | B200 x${r.dedicated_b200.replicas} $${f(r.dedicated_b200.costSession)} p95 ${f(r.dedicated_b200.p95, 0)}s`);
}
