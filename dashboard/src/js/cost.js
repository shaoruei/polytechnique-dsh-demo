// Page 4 · Cost curves: public pay-per-token vs one dedicated replica billed per hour, with its scenario capacity.
const COST_KEYS = ['gpuHour', 'gpus', 'reqPerReplica'];
PAGES.economics = {
  html: () => `
    <div class="section-head">
      <h2>4 · Pay per token or pay per GPU-hour?</h2>
      <p>Public cost grows with every SWE-bench task. One dedicated replica costs the same every billed hour, but can only carry so many tasks.</p>
    </div>
    <div class="grid econ-grid">
      ${assumptionControls('economics', COST_KEYS)}
      <div class="econ-out">
        <div class="tiles tiles-3" id="e-tiles"></div>
        <figure class="panel"><figcaption>Cost per billed hour vs SWE-bench tasks per hour</figcaption><div class="chart tall"><canvas id="c-curve"></canvas></div><p class="note" id="e-note"></p></figure>
      </div>
    </div>`,
  init() { bindAssumptions('economics', () => this.draw()); },
  draw() {
    const price = replicaHour();
    const be = price / costPerTask; // tasks/h at which one replica costs the same as public
    const cap = publicTasksPerHour(); // public default limits
    const ded = dedicatedTasksPerHour(); // one replica, scenario capacity
    const xmax = Math.ceil((Math.max(be, cap, ded) * 1.2) / 500) * 500;
    const ymax = Math.max(price, costPerTask * xmax) * 1.05;
    const verdict = be <= ded
      ? `Dedicated is cheaper from ${num(be)} to ${num(ded)} tasks per hour (one replica's capacity in this scenario), if it stays that busy every billed hour.`
      : `Not a recommendation: dedicated would only be cheaper above ${num(be)} tasks per hour, but one replica can carry about ${num(ded)} in this scenario.`;
    $('e-tiles').innerHTML = [
      tile('Public cost per task', usd(costPerTask, 4), `mean of the 9 runs · public limits allow ≈ ${num(cap)}/h`, 'measured'),
      tile('Break-even', `${num(be)} tasks/h`, `one replica at ${usd(price, 2)}/h`, 'estimate'),
      tile('Replica capacity', `≈ ${num(ded)} tasks/h`, `${scenarioName()} scenario · ${be <= ded ? 'covers the break-even' : 'below the break-even'}`, 'assumption'),
    ].join('');
    const vline = (x, label, color, dash) => ({ label, data: [{ x, y: 0 }, { x, y: ymax }], borderColor: color, backgroundColor: color, borderWidth: 1.5, borderDash: dash, pointRadius: 0 });
    chart('c-curve', {
      type: 'line',
      data: {
        datasets: [
          { label: 'Public · pay per token', data: [{ x: 0, y: 0 }, { x: xmax, y: costPerTask * xmax }], borderColor: css('--series'), backgroundColor: css('--series'), borderWidth: 4, pointRadius: 0 },
          { label: 'One dedicated replica · scenario', data: [{ x: 0, y: price }, { x: Math.min(ded, xmax), y: price }], borderColor: css('--tok-output'), backgroundColor: css('--tok-output'), borderWidth: 4, borderDash: [8, 5], pointRadius: 0 },
          vline(ded, 'Replica capacity · scenario', css('--tok-output'), [2, 3]),
          vline(cap, 'Public default limit', css('--muted'), [3, 4]),
        ],
      },
      options: {
        scales: {
          x: { type: 'linear', min: 0, max: xmax, title: { display: true, text: 'SWE-bench tasks per hour' } },
          y: { min: 0, max: ymax, title: { display: true, text: 'USD per billed hour' }, ticks: { callback: (y) => usd(y, 0) } },
        },
        plugins: { tooltip: { callbacks: { label: (c) => `${c.dataset.label}: ${num(c.raw.x)} tasks/h → ${usd(c.raw.y, 2)}` } } },
      },
    });
    $('e-note').textContent = verdict;
  },
};
