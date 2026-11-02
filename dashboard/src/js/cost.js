// Page 4 · Cost curves: a month of class usage. Public pays per measured SWE-bench task; one dedicated replica
// pays per billed hour and can only serve so many tasks in those hours (scenario capacity).
const COST_KEYS = ['gpuHour', 'gpus', 'reqPerReplica'];
PAGES.economics = {
  html: () => `
    <div class="section-head">
      <h2>4 · Pay per token or pay per GPU-hour?</h2>
      <p>One month of class usage. Public cost grows with every task; one dedicated replica costs the same for its billed hours, and can only carry so many tasks in them.</p>
    </div>
    <div class="grid econ-grid">
      <div class="stack">
        <form class="panel controls" id="usage-form" autocomplete="off"><h3>Usage</h3>
          <label class="field" for="u-tasks">SWE-bench tasks per student per month <output id="u-tasks-o"></output></label>
          <input id="u-tasks" type="range" min="5" max="200" step="5" value="40">
          <label class="field" for="u-hours">Billed dedicated hours per month <output id="u-hours-o"></output></label>
          <input id="u-hours" type="range" min="8" max="730" step="2" value="32">
          <p class="hint">e.g. 8 class sessions × 4 h; 730 h = always on.</p>
        </form>
        ${assumptionControls('economics', COST_KEYS)}
      </div>
      <div class="econ-out">
        <div class="tiles tiles-3" id="e-tiles"></div>
        <figure class="panel"><figcaption>Cost per month vs number of students</figcaption><div class="chart tall"><canvas id="c-curve"></canvas></div><p class="note" id="e-note"></p></figure>
      </div>
    </div>`,
  init() {
    bindAssumptions('economics', () => this.draw());
    $('usage-form').addEventListener('input', () => this.draw());
  },
  draw() {
    const tasks = +$('u-tasks').value;
    const hours = +$('u-hours').value;
    $('u-tasks-o').textContent = tasks;
    $('u-hours-o').textContent = `${hours} h`;
    const dedMonth = replicaHour() * hours;
    const perStudent = tasks * costPerTask; // public, per month
    const beStudents = dedMonth / perStudent; // where one replica costs the same as public
    const capStudents = (dedicatedTasksPerHour() * hours) / tasks; // most students one replica can serve in its billed hours
    const pubCapStudents = (publicTasksPerHour() * hours) / tasks; // same hours on public default limits
    const xmax = Math.ceil((Math.max(beStudents, capStudents) * 1.25) / 50) * 50 || 50;
    const ymax = Math.max(dedMonth, perStudent * xmax) * 1.05;
    const attractive = beStudents <= capStudents;
    $('e-tiles').innerHTML = [
      tile('Public per student', `${usd(perStudent, 2)} / month`, `${tasks} tasks × ${usd(costPerTask, 4)} measured`, 'measured'),
      tile('One dedicated replica', `${usd(dedMonth, 0)} / month`, `${hours} h × ${usd(replicaHour(), 2)} (${scenarioName()})`, 'assumption'),
      tile('Break-even', `${num(beStudents)} students`, `one replica fits ≈ ${num(capStudents)} · ${attractive ? 'feasible' : 'not feasible'}`, 'estimate'),
    ].join('');
    const vline = (x, label, color, dash) => ({ label, data: [{ x, y: 0 }, { x, y: ymax }], borderColor: color, backgroundColor: color, borderWidth: 1.5, borderDash: dash, pointRadius: 0 });
    chart('c-curve', {
      type: 'line',
      data: {
        datasets: [
          { label: 'Public · pay per token', data: [{ x: 0, y: 0 }, { x: xmax, y: perStudent * xmax }], borderColor: css('--series'), backgroundColor: css('--series'), borderWidth: 4, pointRadius: 0 },
          { label: 'One dedicated replica · scenario', data: [{ x: 0, y: dedMonth }, { x: Math.min(capStudents, xmax), y: dedMonth }], borderColor: css('--tok-output'), backgroundColor: css('--tok-output'), borderWidth: 4, borderDash: [8, 5], pointRadius: 0 },
          vline(capStudents, 'Replica capacity · scenario', css('--tok-output'), [2, 3]),
          vline(pubCapStudents, 'Public default limit (same hours)', css('--muted'), [3, 4]),
        ],
      },
      options: {
        scales: {
          x: { type: 'linear', min: 0, max: xmax, title: { display: true, text: 'students' } },
          y: { min: 0, max: ymax, title: { display: true, text: 'USD per month' }, ticks: { callback: (y) => usd(y, 0) } },
        },
        plugins: { tooltip: { callbacks: { label: (c) => `${c.dataset.label}: ${num(c.raw.x)} students → ${usd(c.raw.y, 0)}` } } },
      },
    });
    $('e-note').textContent = attractive
      ? `Dedicated is cheaper from ${num(beStudents)} to ${num(capStudents)} students (one replica's capacity in this scenario), assuming the class's tasks fall within the billed hours.`
      : `Not a recommendation: dedicated would only be cheaper above ${num(beStudents)} students, but one replica can serve about ${num(capStudents)} in ${hours} billed hours.`;
  },
};
