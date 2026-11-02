// Classroom traffic simulation: students run coding agents; every agent replays a REAL measured
// DSH trajectory (a sequence of LLM requests with measured tokens and latency, separated by the
// measured tool/harness gaps). Deterministic for a given seed.
//
// Backends:
//  public    - each request takes its measured public-endpoint latency (shared infrastructure;
//              our load is assumed not to slow it down) but admission is throttled by the
//              account's requests/min and tokens/min limits (sliding 60 s window), the way a
//              client that backs off on HTTP 429 would experience it.
//  dedicated - R replicas, each with a per-GPU concurrency cap; requests share GPU throughput
//              (processor sharing) according to the benchmark-derived capacity curve.
//              Requests beyond the cap wait in a FIFO queue.

import { mulberry32, exponential } from './prng.js';
import { interactivityAt, prefillSeconds, capacityPerGpu, soloRequestSeconds } from './capacity.js';
import { publicCost } from './cost.js';

/** Build the list of task start "release" times and per-student start delays. */
export function buildStudents(scenario, rng) {
  const { students, tasksPerStudent } = scenario;
  const horizon = scenario.windowHours * 3600;
  const out = [];
  for (let s = 0; s < students; s++) {
    const releases = [];
    if (scenario.pattern === 'class') {
      // exercises released at evenly spaced points of the session; each student starts after a
      // random delay (mean = syncMinutes; small = everybody starts at once)
      for (let k = 0; k < tasksPerStudent; k++) {
        const release = (k / tasksPerStudent) * horizon * scenario.releaseSpan;
        releases.push(release + exponential(rng, scenario.syncMinutes * 60));
      }
    } else {
      // spread over the whole window (e.g. a working day): uniform random, sorted
      for (let k = 0; k < tasksPerStudent; k++) releases.push(rng() * horizon * 0.95);
      releases.sort((a, b) => a - b);
    }
    // Pre-draw every random choice per student so all backends face identical demand
    // ("common random numbers"): trajectory for each attempt (task + optional retry) and the
    // review pause after each attempt.
    const picks = [];
    const reviews = [];
    for (let k = 0; k < 2 * tasksPerStudent; k++) {
      picks.push(rng());
      reviews.push(exponential(rng, (scenario.reviewMinutes ?? 2) * 60));
    }
    out.push({ releases, picks, reviews });
  }
  return out;
}

/**
 * Run the simulation.
 * @param trajectories [{task, effort, success, lead_s, steps:[{u,c,o,lat,gap}]}]
 * @param scenario {students, tasksPerStudent, pattern:'class'|'day', windowHours, syncMinutes,
 *                  releaseSpan, reviewMinutes, retryFailed, seed, effort, tasks}
 * @param backend  {kind:'public', rpm, tpm} | {kind:'dedicated', profile, replicas, efficiency,
 *                  maxConcurrencyPerGpu, baseLatency, cachedWorkWeight}
 */
export function simulate(trajectories, scenario, backend, prices) {
  const rng = mulberry32(scenario.seed ?? 1);
  const pool = trajectories.filter(
    (t) => (!scenario.effort || t.effort === scenario.effort) && (!scenario.tasks || scenario.tasks.includes(t.task)),
  );
  if (!pool.length) throw new Error('no trajectories match the scenario');
  const students = buildStudents(scenario, rng);
  const horizonS = scenario.windowHours * 3600;
  const dt = scenario.dt ?? (horizonS <= 4 * 3600 ? 0.1 : 0.5);

  // ---- agent (task) state -------------------------------------------------------------------
  const agents = []; // one entry per task attempt
  const live = []; // agents not yet done
  let unstarted = students.reduce((n, s) => n + s.releases.length, 0);
  let pendingRetries = 0;
  const studentState = students.map((s, i) => ({
    id: i, next: 0, attempt: 0, releases: s.releases, picks: s.picks, reviews: s.reviews, busy: false, readyAt: 0,
  }));

  function startTask(st, t, isRetry) {
    const traj = pool[Math.floor(st.picks[st.attempt] * pool.length)];
    const a = {
      student: st.id, traj, step: -1, phase: 'lead', until: t + traj.lead_s, start: t, end: null,
      retry: isRetry, waited: 0, requests: 0, success: traj.success,
    };
    agents.push(a);
    live.push(a);
    st.busy = true;
    return a;
  }

  // ---- backend state --------------------------------------------------------------------------
  const queue = []; // FIFO of agents with a ready request
  const inflight = []; // {agent, remaining (s or work tokens), fixed, replica, startT, readyT}
  const window = []; // public: admitted requests in last 60 s {t, tokens}
  let windowTokens = 0;
  const replicas = backend.kind === 'dedicated' ? Array.from({ length: backend.replicas }, () => 0) : [];
  const gpr = backend.kind === 'dedicated' ? backend.profile.gpus_per_replica || 1 : 1;
  const capPerReplica = backend.kind === 'dedicated'
    ? Math.max(1, Math.floor((backend.maxConcurrencyPerGpu ?? backend.profile.max_concurrency_per_gpu) * gpr))
    : Infinity;
  const mult = backend.rateLimitMultiplier ?? 1;
  const baseRpm = backend.kind === 'public' ? backend.rpm * mult : Infinity;
  const baseTpm = backend.kind === 'public' ? backend.tpm * mult : Infinity;
  let rpm = baseRpm;
  let tpm = baseTpm;
  // Documented dynamic scaling: per 15-min window, usage >= 80% of the limit -> +20% next window;
  // usage <= 50% -> /1.5 (never below base); hard ceiling 20x base.
  const dynamic = backend.kind === 'public' && backend.dynamicLimits;
  let winStart = 0;
  let winReq = 0;
  let winTok = 0;
  let limitFactor = 1;
  const limitHistory = [];

  // ---- metrics --------------------------------------------------------------------------------
  const maxT = horizonS * 3; // allow overrun when the system is overloaded
  const minutes = Math.ceil(maxT / 60) + 2;
  const tl = Array.from({ length: minutes }, (_, m) => ({
    minute: m, activeAgents: 0, inflight: 0, queued: 0, requestsStarted: 0, tokensIn: 0, tokensOut: 0, samples: 0,
  }));
  const tokens = { uncached: 0, cached: 0, output: 0 };
  const reqLatencies = [];
  const reqWaits = [];
  let outputDone = 0;
  let gpuBusySeconds = 0; // integral of occupied replicas over time
  let maxInflightInstant = 0;
  let maxPerReplicaInstant = 0;

  const countCached = backend.tpmCountsCached ?? true;
  const tokensOf = (step) => step.u + (countCached ? step.c : 0) + step.o;

  function canAdmitPublic(t, step) {
    while (window.length && window[0].t <= t - 60) windowTokens -= window.shift().tokens;
    return window.length < rpm && windowTokens + tokensOf(step) <= tpm;
  }

  function admit(t) {
    while (queue.length) {
      const a = queue[0];
      const step = a.traj.steps[a.step];
      if (backend.kind === 'public') {
        if (!canAdmitPublic(t, step)) break;
        window.push({ t, tokens: tokensOf(step) });
        windowTokens += tokensOf(step);
        winReq++;
        winTok += tokensOf(step);
        inflight.push({ agent: a, remaining: step.lat, fixed: 0, replica: -1, startT: t, readyT: a.readyT });
      } else {
        let best = -1;
        for (let r = 0; r < replicas.length; r++) {
          if (replicas[r] < capPerReplica && (best < 0 || replicas[r] < replicas[best])) best = r;
        }
        if (best < 0) break;
        replicas[best]++;
        inflight.push({
          agent: a,
          remaining: step.o,
          fixed: prefillSeconds(backend.profile, step, {
            baseLatency: backend.baseLatency, cachedWorkWeight: backend.cachedWorkWeight,
          }),
          replica: best, startT: t, readyT: a.readyT,
        });
      }
      queue.shift();
      a.phase = 'inflight';
      a.waited += t - a.readyT;
      reqWaits.push(t - a.readyT);
      const m = tl[Math.min(minutes - 1, Math.floor(t / 60))];
      m.requestsStarted++;
      m.tokensIn += step.u + step.c;
      m.tokensOut += step.o;
      tokens.uncached += step.u;
      tokens.cached += step.c;
      tokens.output += step.o;
    }
  }

  function advanceAgent(a, t) {
    // called when lead or gap phase ends: issue next request or finish
    a.step++;
    if (a.step < a.traj.steps.length) {
      a.phase = 'queued';
      a.readyT = t;
      a.requests++;
      queue.push(a);
    } else {
      a.phase = 'done';
      a.end = t;
      const st = studentState[a.student];
      st.busy = false;
      st.readyAt = t + st.reviews[st.attempt];
      st.attempt++;
      if (!a.success && scenario.retryFailed && !a.retry) {
        st.pendingRetry = true;
        pendingRetries++;
      }
    }
  }

  // ---- main loop ------------------------------------------------------------------------------
  let t = 0;
  let pendingWork = true;
  for (; t <= maxT && pendingWork; t += dt) {
    // 1. students start tasks
    for (const st of studentState) {
      if (st.busy || t < st.readyAt) continue;
      if (st.pendingRetry) {
        st.pendingRetry = false;
        pendingRetries--;
        startTask(st, t, true);
      } else if (st.next < st.releases.length && t >= st.releases[st.next]) {
        st.next++;
        unstarted--;
        startTask(st, t, false);
      }
    }
    // 2. lead/gap timers
    let removed = false;
    for (const a of live) {
      if ((a.phase === 'lead' || a.phase === 'gap') && t >= a.until) {
        advanceAgent(a, t);
        if (a.phase === 'done') removed = true;
      }
    }
    if (removed) {
      for (let i = live.length - 1; i >= 0; i--) if (live[i].phase === 'done') live.splice(i, 1);
    }
    // 3. admission (public: update dynamic limits at 15-minute window boundaries)
    if (dynamic && t - winStart >= 900) {
      const used = Math.max(winReq / (rpm * 15), winTok / (tpm * 15));
      if (used >= 0.8) limitFactor = Math.min(20, limitFactor * 1.2);
      else if (used <= 0.5) limitFactor = Math.max(1, limitFactor / 1.5);
      rpm = baseRpm * limitFactor;
      tpm = baseTpm * limitFactor;
      limitHistory.push({ minute: Math.round(t / 60), factor: limitFactor });
      winStart = t;
      winReq = 0;
      winTok = 0;
    }
    admit(t);
    // 4. progress in-flight requests
    if (backend.kind === 'dedicated') {
      const rates = replicas.map((n) => (n > 0 ? interactivityAt(backend.profile, n / gpr) * (backend.efficiency ?? 1) : 0));
      for (const f of inflight) {
        let budget = dt;
        if (f.fixed > 0) {
          const used = Math.min(f.fixed, budget);
          f.fixed -= used;
          budget -= used;
        }
        if (budget > 0 && f.remaining > 0) {
          const rate = rates[f.replica];
          const w = Math.min(f.remaining, rate * budget);
          f.remaining -= w;
          outputDone += w;
          budget -= rate > 0 ? w / rate : budget;
        }
        f.doneAt = t + (dt - budget); // exact completion time within this tick
      }
    } else {
      for (const f of inflight) {
        f.doneAt = t + Math.min(dt, Math.max(f.remaining, 0));
        f.remaining -= dt;
      }
    }
    if (backend.kind === 'dedicated') gpuBusySeconds += inflight.length * dt;
    if (inflight.length > maxInflightInstant) maxInflightInstant = inflight.length;
    if (backend.kind === 'dedicated') for (const n of replicas) if (n > maxPerReplicaInstant) maxPerReplicaInstant = n;
    for (let i = inflight.length - 1; i >= 0; i--) {
      const f = inflight[i];
      if (f.remaining <= 1e-9 && f.fixed <= 1e-9) {
        inflight.splice(i, 1);
        if (f.replica >= 0) replicas[f.replica]--;
        const a = f.agent;
        reqLatencies.push(f.doneAt - f.startT);
        a.phase = 'gap';
        a.until = f.doneAt + a.traj.steps[a.step].gap;
      }
    }
    // 5. sample timeline
    const m = tl[Math.min(minutes - 1, Math.floor(t / 60))];
    m.activeAgents += live.length;
    m.inflight += inflight.length;
    m.queued += queue.length;
    m.samples++;
    pendingWork = t < horizonS || live.length > 0 || unstarted > 0 || pendingRetries > 0;
  }

  // ---- summarise ------------------------------------------------------------------------------
  for (const m of tl) {
    if (m.samples) {
      m.activeAgents /= m.samples;
      m.inflight /= m.samples;
      m.queued /= m.samples;
    }
    delete m.samples;
  }
  const done = agents.filter((a) => a.end !== null);
  const durations = done.map((a) => a.end - a.start);
  // measured: the trajectory's real duration on the public endpoint (no contention)
  const measured = done.map((a) => a.traj.lead_s + a.traj.steps.reduce((s, x) => s + x.lat + x.gap, 0));
  // unloaded: the same trajectory on this backend with no other traffic
  const soloOpts = { baseLatency: backend.baseLatency, cachedWorkWeight: backend.cachedWorkWeight,
    efficiency: backend.efficiency ?? 1 };
  const unloaded = backend.kind === 'dedicated'
    ? done.map((a) => a.traj.lead_s + a.traj.steps.reduce((s, x) => s + soloRequestSeconds(backend.profile, x, soloOpts) + x.gap, 0))
    : measured;
  const slowdowns = done.map((a, i) => durations[i] / Math.max(unloaded[i], 1e-9));
  const vsPublic = done.map((a, i) => durations[i] / Math.max(measured[i], 1e-9));
  const pct = (arr, q) => {
    if (!arr.length) return null;
    const s = [...arr].sort((x, y) => x - y);
    const k = (s.length - 1) * q;
    const lo = Math.floor(k);
    const hi = Math.min(lo + 1, s.length - 1);
    return s[lo] + (s[hi] - s[lo]) * (k - lo);
  };
  const usedMinutes = tl.filter((m) => m.requestsStarted > 0 || m.activeAgents > 0);
  const peakRpm = Math.max(0, ...tl.map((m) => m.requestsStarted));
  const peakTpm = Math.max(0, ...tl.map((m) => m.tokensIn + m.tokensOut));
  const makespan = done.length ? Math.max(...done.map((a) => a.end)) : 0;
  let gpuUtil = null;
  let capacityUtil = null;
  if (backend.kind === 'dedicated') {
    // output produced vs decode-slot capacity at the target interactivity over the busy period
    const perGpu = capacityPerGpu(backend.profile, backend.targetInteractivity ?? 90, backend.efficiency ?? 1);
    capacityUtil = perGpu > 0 ? outputDone / (backend.replicas * gpr * perGpu * Math.max(makespan, 1)) : null;
    gpuUtil = gpuBusySeconds / (backend.replicas * capPerReplica * Math.max(makespan, 1));
  }
  return {
    timeline: tl.slice(0, Math.ceil(Math.max(makespan, horizonS) / 60) + 1),
    summary: {
      backend: backend.kind,
      tasksAttempted: agents.length,
      tasksCompleted: done.length,
      retries: agents.filter((a) => a.retry).length,
      successfulTasks: done.filter((a) => a.success).length,
      requests: reqLatencies.length,
      tokens,
      publicCostUsd: prices ? publicCost(tokens, prices) : null,
      peakActiveAgents: Math.max(0, ...tl.map((m) => m.activeAgents)),
      peakInflight: Math.max(0, ...tl.map((m) => m.inflight)),
      peakQueued: Math.max(0, ...tl.map((m) => m.queued)),
      maxInflightInstant,
      maxPerReplicaInstant,
      peakRpm,
      peakTpm,
      avgRpm: usedMinutes.length ? reqLatencies.length / usedMinutes.length : 0,
      taskDurationP50: pct(durations, 0.5),
      taskDurationP95: pct(durations, 0.95),
      slowdownP50: pct(slowdowns, 0.5),
      slowdownP95: pct(slowdowns, 0.95),
      vsMeasuredPublicP50: pct(vsPublic, 0.5),
      vsMeasuredPublicP95: pct(vsPublic, 0.95),
      unloadedTaskDurationP50: pct(unloaded, 0.5),
      requestLatencyP50: pct(reqLatencies, 0.5),
      requestLatencyP95: pct(reqLatencies, 0.95),
      requestWaitP95: pct(reqWaits, 0.95),
      meanWaitPerTask: done.length ? done.reduce((s, a) => s + a.waited, 0) / done.length : 0,
      makespanS: makespan,
      overranWindow: makespan > horizonS,
      capacityUtilization: capacityUtil,
      slotUtilization: gpuUtil,
      outputTokensGenerated: outputDone,
      rateLimitHistory: dynamic ? limitHistory : null,
    },
  };
}

/**
 * Smallest replica count whose p95 contention slowdown (task time / the same task on an idle
 * replica) is <= sloSlowdown and that finishes inside the window.
 * Returns {replicas, result} or {replicas:null} when maxReplicas is not enough.
 */
export function autoSize(trajectories, scenario, backendBase, prices, { sloSlowdown = 1.5, maxReplicas = 64 } = {}) {
  const run = (r) => simulate(trajectories, scenario, { ...backendBase, replicas: r }, prices);
  const ok = (res) => res.summary.slowdownP95 !== null && res.summary.slowdownP95 <= sloSlowdown && !res.summary.overranWindow;
  let hi = 1;
  let res = run(hi);
  while (!ok(res)) {
    if (hi >= maxReplicas) return { replicas: null, result: res };
    hi = Math.min(maxReplicas, hi * 2);
    res = run(hi);
  }
  let lo = Math.floor(hi / 2);
  let best = { replicas: hi, result: res };
  while (lo + 1 < hi) {
    const mid = Math.floor((lo + hi) / 2);
    const r = run(mid);
    if (ok(r)) {
      hi = mid;
      best = { replicas: mid, result: r };
    } else lo = mid;
  }
  if (hi === 1) best = { replicas: 1, result: res };
  return best;
}
