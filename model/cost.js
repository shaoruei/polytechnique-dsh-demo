// Public (pay-per-token) vs Dedicated (pay-per-GPU-hour) cost model.
import { capacityPerGpu } from './capacity.js';

export const HOURS_PER_MONTH = 730;

/** Public endpoint price of a token mix (USD). */
export function publicCost(tokens, prices) {
  return (
    (tokens.uncached * prices.input_per_mtok +
      tokens.cached * prices.cached_input_per_mtok +
      tokens.output * prices.output_per_mtok) /
    1e6
  );
}

/** Operating schedules: hours per month the dedicated endpoint is billed. */
export function billedHoursPerMonth(schedule) {
  switch (schedule.kind) {
    case 'always-on':
      return HOURS_PER_MONTH;
    case 'business-hours':
      return schedule.hoursPerDay * schedule.daysPerMonth;
    case 'class-only':
      // spin up shortly before each session, scale to zero after (per-minute billing)
      return schedule.sessionsPerMonth * (schedule.sessionHours + schedule.warmupHours);
    default:
      throw new Error(`unknown schedule ${schedule.kind}`);
  }
}

/** Hours per month during which the demand actually arrives (it must fit in the billed hours). */
export function activeHoursPerMonth(schedule) {
  switch (schedule.kind) {
    case 'always-on':
      return schedule.activeHoursPerMonth ?? HOURS_PER_MONTH;
    case 'business-hours':
      return schedule.hoursPerDay * schedule.daysPerMonth;
    case 'class-only':
      return schedule.sessionsPerMonth * schedule.sessionHours;
    default:
      throw new Error(`unknown schedule ${schedule.kind}`);
  }
}

/**
 * Analytic capacity-aware dedicated sizing for a monthly task volume.
 * Demand is measured in output tokens (decode slots are the binding resource, see capacity.js):
 * average rate = tasks x output/task / active seconds; peak = average x peakFactor.
 * GPUs = max(minGpus, ceil(peak / (capacity per GPU at target interactivity x target utilisation))).
 */
export function dedicatedSizing({ tasksPerMonth, outputPerTask, schedule, gpu, targetInteractivity,
  targetUtilization = 0.7, peakFactor = 1, efficiency = 1, minGpus = 1 }) {
  const activeSeconds = activeHoursPerMonth(schedule) * 3600;
  const avgWorkRate = (tasksPerMonth * outputPerTask) / activeSeconds;
  const peakWorkRate = avgWorkRate * peakFactor;
  const perGpu = capacityPerGpu(gpu.profile, targetInteractivity, efficiency);
  const replicaGpus = gpu.profile.gpus_per_replica || 1;
  let gpus = perGpu > 0 ? Math.ceil(peakWorkRate / (perGpu * targetUtilization) - 1e-9) : Infinity;
  gpus = Math.max(minGpus, gpus);
  gpus = Math.ceil(gpus / replicaGpus) * replicaGpus;
  const hours = billedHoursPerMonth(schedule);
  return {
    gpus,
    perGpuCapacity: perGpu,
    avgWorkRate,
    peakWorkRate,
    utilization: gpus > 0 && perGpu > 0 ? peakWorkRate / (gpus * perGpu) : null,
    billedHours: hours,
    monthlyCost: gpus * gpu.pricePerGpuHour * hours,
  };
}

/** Naive dedicated cost that ignores capacity (one replica regardless of volume). */
export function naiveDedicatedCost({ schedule, gpu }) {
  return (gpu.profile.gpus_per_replica || 1) * gpu.pricePerGpuHour * billedHoursPerMonth(schedule);
}

/** Public monthly cost and rate-limit feasibility for a task volume. */
export function publicMonthly({ tasksPerMonth, perTask, prices, schedule, peakFactor = 1, rateLimits }) {
  const cost = tasksPerMonth * publicCost(perTask.tokens, prices);
  const activeMinutes = activeHoursPerMonth(schedule) * 60;
  const avgRpm = (tasksPerMonth * perTask.requests) / activeMinutes;
  const avgTpm = (tasksPerMonth * perTask.tokens.prompt_plus_output) / activeMinutes;
  const peakRpm = avgRpm * peakFactor;
  const peakTpm = avgTpm * peakFactor;
  const mult = rateLimits.multiplier ?? 1;
  return {
    monthlyCost: cost,
    avgRpm,
    avgTpm,
    peakRpm,
    peakTpm,
    withinRateLimits: peakRpm <= rateLimits.rpm * mult && peakTpm <= rateLimits.tpm * mult,
    rpmUtilization: peakRpm / (rateLimits.rpm * mult),
    tpmUtilization: peakTpm / (rateLimits.tpm * mult),
  };
}

/** Sweep task volume and return both curves plus break-even points. */
export function costCurves({ volumes, perTask, prices, schedule, gpu, targetInteractivity,
  targetUtilization, peakFactor, efficiency, rateLimits }) {
  const rows = volumes.map((v) => {
    const pub = publicMonthly({ tasksPerMonth: v, perTask, prices, schedule, peakFactor, rateLimits });
    const ded = dedicatedSizing({ tasksPerMonth: v, outputPerTask: perTask.tokens.output, schedule, gpu,
      targetInteractivity, targetUtilization, peakFactor, efficiency });
    return {
      tasksPerMonth: v,
      publicCost: pub.monthlyCost,
      publicWithinLimits: pub.withinRateLimits,
      publicPeakTpm: pub.peakTpm,
      dedicatedCost: ded.monthlyCost,
      dedicatedGpus: ded.gpus,
      naiveDedicatedCost: naiveDedicatedCost({ schedule, gpu }),
    };
  });
  return {
    rows,
    breakEven: breakEvenTasks({ perTask, prices, schedule, gpu, targetInteractivity, targetUtilization,
      peakFactor, efficiency }),
    naiveBreakEven: naiveDedicatedCost({ schedule, gpu }) / publicCost(perTask.tokens, prices),
  };
}

/**
 * Smallest monthly task volume at which capacity-aware dedicated is no more expensive than public.
 * The dedicated curve is a step function, so after each step the public line may cross again;
 * returns the first crossing and whether dedicated stays cheaper for all larger volumes.
 */
export function breakEvenTasks({ perTask, prices, schedule, gpu, targetInteractivity, targetUtilization = 0.7,
  peakFactor = 1, efficiency = 1, maxTasks = 1e9 }) {
  const costPerTask = publicCost(perTask.tokens, prices);
  const hours = billedHoursPerMonth(schedule);
  const perGpu = capacityPerGpu(gpu.profile, targetInteractivity, efficiency);
  if (perGpu <= 0) return { tasks: null, reason: 'target interactivity not reachable on this GPU' };
  // Tasks one GPU can absorb per month at the target utilisation.
  const activeSeconds = activeHoursPerMonth(schedule) * 3600;
  const tasksPerGpu = (perGpu * targetUtilization * activeSeconds) / (perTask.tokens.output * peakFactor);
  const gpuMonthCost = gpu.pricePerGpuHour * hours;
  // Within the k-th GPU step, dedicated cost = k x gpuMonthCost while volume in ((k-1)T, kT].
  // Public cost reaches k x gpuMonthCost at V = k x gpuMonthCost / costPerTask.
  const vPerGpuBreakEven = gpuMonthCost / costPerTask; // volume where public pays for one GPU-month
  if (vPerGpuBreakEven > tasksPerGpu) {
    return {
      tasks: null,
      reason: 'never: one GPU saturates before its cost is covered by public pricing',
      tasksPerGpu,
      publicTasksPerGpuMonthCost: vPerGpuBreakEven,
      costPerTask,
      gpuMonthCost,
    };
  }
  // Sawtooth: right after adding GPU k (volume just above (k-1)T) dedicated costs k*G while public
  // costs (k-1)*T*p, which can be cheaper again. Dedicated is cheaper in step k on
  // [max((k-1)T, kG/p), kT]; it is cheaper for every larger volume from step k0, the first k with
  // (k-1)T >= kG/p, i.e. k0 = ceil(T / (T - G/p)).
  const T = tasksPerGpu;
  const g = vPerGpuBreakEven;
  const k0 = T - g > 0 ? Math.max(1, Math.ceil(T / (T - g) - 1e-9)) : Infinity;
  const permanent = k0 === 1 ? g : (k0 - 1) * T;
  return {
    tasks: Math.min(g, maxTasks),
    permanentFromTasks: Number.isFinite(permanent) ? permanent : null,
    gpusAtPermanent: Number.isFinite(k0) ? k0 : null,
    tasksPerGpu,
    publicTasksPerGpuMonthCost: vPerGpuBreakEven,
    costPerTask,
    gpuMonthCost,
  };
}

/** Dedicated cost per 1M output tokens at a given utilisation. */
export function dedicatedCostPerMOutputTok({ gpu, targetInteractivity, utilization, efficiency = 1 }) {
  const perGpu = capacityPerGpu(gpu.profile, targetInteractivity, efficiency);
  return (gpu.pricePerGpuHour / (perGpu * utilization * 3600)) * 1e6;
}
