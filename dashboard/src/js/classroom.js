// Page 5 · Classroom: students replay the 9 recorded runs against the public limits; dedicated cost from the assumptions.
const SWE_TRAJ = SWE.runs.map((r) => ({ task: r.instance_id, effort: r.effort, success: r.success, lead_s: r.trajectory.lead_s, steps: r.trajectory.steps }));
let simTimer = null;
PAGES.classroom = {
  html: () => `
    <div class="section-head">
      <h2>5 · A classroom of agents</h2>
      <p>Each simulated student replays one of the 9 recorded SWE-bench runs: same requests, tokens and tool time.</p>
    </div>
    <div class="grid econ-grid">
      <form class="panel controls" id="sim-form" autocomplete="off">
        <div class="presets" role="group" aria-label="Students"><button type="button" data-n="10">10</button><button type="button" data-n="30">30</button><button type="button" data-n="60">60</button><button type="button" data-n="120">120</button></div>
        <label class="field" for="s-students">Students <output id="s-students-o"></output></label>
        <input id="s-students" type="range" min="5" max="200" step="5" value="30">
        <label class="field" for="s-tasks">Agent tasks per student <output id="s-tasks-o"></output></label>
        <input id="s-tasks" type="range" min="1" max="6" step="1" value="3">
        <label class="field" for="s-hours">Session length <output id="s-hours-o"></output></label>
        <input id="s-hours" type="range" min="1" max="3" step="0.5" value="2">
        <p class="hint">Dedicated: one 2× B200 replica, scenario from pages 3–4 ${ev('assumption')}.</p>
      </form>
      <div class="econ-out">
        <div class="tiles tiles-3" id="s-tiles"></div>
        <figure class="panel"><figcaption>Public tokens per minute vs the account limit ${ev('estimate', 'Simulated')}</figcaption><div class="chart tall"><canvas id="c-tpm"></canvas></div></figure>
      </div>
    </div>`,
  init() {
    const again = () => { clearTimeout(simTimer); simTimer = setTimeout(() => this.draw(), 120); };
    $('sim-form').addEventListener('input', again);
    for (const b of document.querySelectorAll('.presets button')) b.addEventListener('click', () => { $('s-students').value = b.dataset.n; again(); });
  },
  draw() {
    const sc = { students: +$('s-students').value, tasksPerStudent: +$('s-tasks').value, pattern: 'class', windowHours: +$('s-hours').value,
      syncMinutes: 3, releaseSpan: 0.8, reviewMinutes: 2, retryFailed: false, seed: 7 };
    $('s-students-o').textContent = sc.students;
    $('s-tasks-o').textContent = sc.tasksPerStudent;
    $('s-hours-o').textContent = num(sc.windowHours, 1) + ' h';
    for (const b of document.querySelectorAll('.presets button')) b.setAttribute('aria-pressed', String(+b.dataset.n === sc.students));
    const pubBackend = { kind: 'public', rpm: LIMITS.requests_per_minute, tpm: LIMITS.tokens_per_minute, tpmCountsCached: true };
    const res = simulate(SWE_TRAJ, sc, pubBackend, PR); // public, measured limits
    const demand = simulate(SWE_TRAJ, sc, { ...pubBackend, rateLimitMultiplier: 1e6 }, PR).summary; // the class unthrottled
    const s = res.summary;
    const pubOk = s.tasksCompleted >= s.tasksAttempted && s.slowdownP95 <= 1.5;
    const dedCost = replicaHour() * sc.windowHours; // one replica billed for the session
    const peakReq = Math.ceil(demand.maxInflightInstant);
    const dedFits = peakReq <= ASSUME.reqPerReplica;
    const verdict = dedFits && dedCost < s.publicCostUsd ? ['ok', 'Dedicated: cheaper and fits']
      : !dedFits ? ['bad', 'Dedicated: over capacity']
        : ['warn', pubOk ? 'Public: cheaper and keeps up' : 'Public: cheaper, but throttled'];
    $('s-tiles').innerHTML = [
      tile('Public · session cost', usd(s.publicCostUsd, 2), `${pubOk ? 'keeps up' : 'throttled'}: task time p95 ${secs(s.taskDurationP95)} (${num(s.slowdownP95, 1)}× recorded)`, 'estimate'),
      tile('Dedicated · session cost', usd(dedCost, 2), `1 replica · peak ${peakReq} requests at once vs ${ASSUME.reqPerReplica} it serves (${scenarioName()})`, 'assumption'),
      `<div class="tile"><span class="label">Verdict</span><span class="value"><span class="pill ${verdict[0]}">${verdict[1]}</span></span><span class="detail">peak public ${big(s.peakTpm)} tokens/min = ${pct(s.peakTpm / LIMITS.tokens_per_minute)} of the limit</span></div>`,
    ].join('');
    const tl = res.timeline;
    chart('c-tpm', {
      type: 'line',
      data: { labels: tl.map((x) => x.minute), datasets: [
        { label: 'tokens/min sent', data: tl.map((x) => x.tokensIn + x.tokensOut), borderColor: css('--series'), backgroundColor: alpha(css('--series'), 0.15), fill: true, pointRadius: 0, borderWidth: 2.5 },
        { label: `limit ${big(LIMITS.tokens_per_minute)}/min`, data: tl.map(() => LIMITS.tokens_per_minute), borderColor: css('--bad'), borderDash: [6, 4], pointRadius: 0, borderWidth: 2 },
      ] },
      options: { scales: { x: { title: { display: true, text: 'minute of the session' }, ticks: { maxTicksLimit: 12 } }, y: { min: 0, ticks: { callback: (v) => big(v) } } } },
    });
  },
};
