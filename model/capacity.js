// Dedicated-endpoint capacity model: historical benchmark curve plus explicit assumptions.
// See data/dedicated_profiles.json for sources and the derivation of per-GPU concurrency.
//
// Model:
//  * I(c) is the per-user output speed (tok/s) with c concurrent requests per GPU. It comes from
//    the benchmark's (interactivity, throughput) points, converted to per-GPU concurrency.
//  * A request takes  baseLatency + uncachedInput / prefillTps + output / (I(c) x efficiency).
//  * GPU capacity at a target interactivity I* is limited by decode slots: c*(I*) x I* output
//    tokens/s. The benchmark mixes 8k-token prefills into every request. The measured agent
//    requests prefill far fewer uncached tokens per output token, so this capacity is
//    conservative. The `efficiency` multiplier covers serving optimisations such as speculative
//    decoding or a lighter prefill mix.

const BENCH_RATIO = 8; // benchmark input:output tokens (8k/1k)
const SATURATION_GAIN = 0.15; // aggregate output may grow at most 15% beyond the last benchmark point

/** Benchmark points converted to per-GPU concurrency, ascending concurrency. */
export function curvePoints(profile) {
  return profile.points
    .map((p) => ({
      interactivity: p.interactivity,
      tpsPerGpu: p.tps_per_gpu,
      outputTpsPerGpu: p.tps_per_gpu / (1 + BENCH_RATIO),
      concurrency: p.tps_per_gpu / (1 + BENCH_RATIO) / p.interactivity,
    }))
    .sort((a, b) => a.concurrency - b.concurrency);
}

/**
 * Per-user output speed (tok/s) at c concurrent requests per GPU. Log-log interpolation between
 * points; flat below the first point; above the last point, aggregate output saturates at
 * (1 + SATURATION_GAIN) x the last point.
 */
export function interactivityAt(profile, c) {
  const pts = curvePoints(profile);
  if (c <= pts[0].concurrency) return pts[0].interactivity;
  for (let i = 1; i < pts.length; i++) {
    const a = pts[i - 1];
    const b = pts[i];
    if (c <= b.concurrency) {
      const t = (Math.log(c) - Math.log(a.concurrency)) / (Math.log(b.concurrency) - Math.log(a.concurrency));
      return Math.exp(Math.log(a.interactivity) + t * (Math.log(b.interactivity) - Math.log(a.interactivity)));
    }
  }
  const last = pts[pts.length - 1];
  const aggOut = last.outputTpsPerGpu * (1 + SATURATION_GAIN * (1 - last.concurrency / c));
  return aggOut / c;
}

/** Aggregate output tok/s of one GPU at c concurrent requests. */
export function outputThroughputAt(profile, c, efficiency = 1) {
  return c * interactivityAt(profile, c) * efficiency;
}

/** Highest per-GPU concurrency (<= cap) that still delivers >= targetInteractivity tok/s/user. */
export function concurrencyForInteractivity(profile, targetInteractivity, efficiency = 1) {
  const cap = profile.max_concurrency_per_gpu;
  const speed = (c) => interactivityAt(profile, c) * efficiency;
  if (speed(1e-9) < targetInteractivity) return 0;
  if (speed(cap) >= targetInteractivity) return cap;
  let lo = 1e-9;
  let hi = cap;
  for (let i = 0; i < 80; i++) {
    const mid = (lo + hi) / 2;
    if (speed(mid) >= targetInteractivity) lo = mid;
    else hi = mid;
  }
  return lo;
}

/** Sustainable output tok/s per GPU while every user gets >= targetInteractivity. */
export function capacityPerGpu(profile, targetInteractivity, efficiency = 1) {
  const c = concurrencyForInteractivity(profile, targetInteractivity, efficiency);
  return c > 0 ? outputThroughputAt(profile, c, efficiency) : 0;
}

/** Fixed (non-decode) part of a request on a dedicated replica, seconds. */
export function prefillSeconds(profile, step, { baseLatency = 0.15, cachedWorkWeight = 0 } = {}) {
  return baseLatency + (step.u + cachedWorkWeight * step.c) / profile.prefill_tps;
}

/** Request latency on an otherwise idle replica (seconds). */
export function soloRequestSeconds(profile, step, opts = {}) {
  return prefillSeconds(profile, step, opts) + step.o / (interactivityAt(profile, 1) * (opts.efficiency ?? 1));
}

export const constants = { BENCH_RATIO, SATURATION_GAIN };
