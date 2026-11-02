// Page 3 · Public vs Dedicated: measured public agent-step latency under load vs a dedicated scenario.
PAGES.endpoints = {
  html: () => `
    <div class="section-head">
      <h2>3 · Public vs Dedicated</h2>
      <p>One agent step (~10k tokens in, 512 out) as more students hit the endpoint at once. Public is measured; dedicated is simulated for one 2× B200 replica.</p>
    </div>
    <div class="grid econ-grid">
      ${scenarioControl('endpoints')}
      <div class="econ-out">
        <div class="tiles tiles-3" id="ep-tiles"></div>
        <figure class="panel"><figcaption>Time for one agent step vs requests at the same time · public ${ev('measured')} dedicated ${ev('assumption', 'Simulated')}</figcaption><div class="chart tall"><canvas id="c-ep-speed"></canvas></div></figure>
      </div>
    </div>
    <h3 class="msec">Public rate limits ${ev('verified')}</h3>
    <div class="tiles tiles-3" id="ep-limits"></div>`,
  init() {
    bindAssumptions('endpoints', () => this.draw());
    const ramp = BENCH.firstRateLimited;
    $('ep-limits').innerHTML = [
      tile('Requests', `${num(LIMITS.requests_per_minute)} / min`, `first 429 after ${num(ramp.first_429_s / 60)} min at ${num(ramp.offered_rpm)} req/min`),
      tile('Tokens', `${big(LIMITS.tokens_per_minute)} / min`, `cached tokens count: ≈ ${num(publicTasksPerHour())} SWE-bench tasks per hour`),
      tile('Over the limit', `≈ ${num(ramp.wait_429_s, 1)} s wait`, 'then HTTP 429'),
    ].join('');
  },
  draw() {
    const pub = BENCH.scaling; // agent-step profile, public, measured at 1-30 concurrent requests
    const conc = pub.map((x) => x.c);
    const at = (c) => pub.find((x) => x.c === c);
    $('ep-tiles').innerHTML = [1, 10, 30].map((c) => {
      const p = at(c).lat_p50;
      const d = dedicatedLatency(c);
      return `<div class="tile"><span class="label">${c === 1 ? 'One request alone' : `${c} at the same time`}</span>
        <span class="value">${num(p, 1)} s <small>public</small></span>
        <span class="detail">dedicated (simulated) ${num(d, 1)} s · ${d < p ? 'faster' : 'slower'}</span></div>`;
    }).join('');
    chart('c-ep-speed', {
      type: 'line',
      data: {
        labels: conc,
        datasets: [
          { label: 'Public · measured (median)', data: conc.map((c) => at(c).lat_p50), borderColor: css('--series'), backgroundColor: css('--series'), borderWidth: 4, pointRadius: 5 },
          { label: `Dedicated · ${scenarioName()} scenario`, data: conc.map((c) => dedicatedLatency(c)), borderColor: css('--tok-output'), backgroundColor: css('--tok-output'), borderWidth: 3, borderDash: [8, 5], pointRadius: 4 },
        ],
      },
      options: { scales: { x: { title: { display: true, text: 'requests running at the same time' } }, y: { min: 0, title: { display: true, text: 'seconds per agent step' } } } },
    });
  },
};
