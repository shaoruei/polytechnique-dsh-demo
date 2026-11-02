// Turn the raw data bundle (data/*.json) into model inputs. Pure: no file or network access.

/**
 * Replayable trajectories from usable measured runs. By default only the original public cohort
 * (2026-10-30), so the original classroom scenarios stay unchanged; pass {cohorts} to choose.
 */
export function trajectoriesFrom(runsDoc, { cohorts = ['public-historical'] } = {}) {
  return runsDoc.runs
    .filter((r) => r.usable && r.trajectory && r.trajectory.steps.length)
    .filter((r) => !cohorts || cohorts.includes(r.cohort ?? 'public-historical'))
    .map((r) => ({ runId: r.run_id, task: r.task, effort: r.effort, success: r.success, endpoint: r.endpoint ?? 'public',
      cohort: r.cohort ?? 'public-historical', ...r.trajectory }));
}

/** Mean per-task token mix, request count and GPU work over a set of trajectories. */
export function perTaskProfile(trajectories, { cachedWorkWeight = 0 } = {}) {
  const n = trajectories.length;
  if (!n) return null;
  const sum = { uncached: 0, cached: 0, output: 0, requests: 0, success: 0, duration: 0 };
  for (const t of trajectories) {
    for (const s of t.steps) {
      sum.uncached += s.u;
      sum.cached += s.c;
      sum.output += s.o;
    }
    sum.requests += t.steps.length;
    sum.success += t.success ? 1 : 0;
    sum.duration += t.lead_s + t.steps.reduce((a, s) => a + s.lat + s.gap, 0);
  }
  const tokens = { uncached: sum.uncached / n, cached: sum.cached / n, output: sum.output / n };
  tokens.prompt_plus_output = tokens.uncached + tokens.cached + tokens.output;
  return {
    n,
    tokens,
    requests: sum.requests / n,
    work: tokens.uncached + tokens.output + cachedWorkWeight * tokens.cached,
    successRate: sum.success / n,
    soloDurationS: sum.duration / n,
  };
}
