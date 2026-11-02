// main.js: boot.
themeDefaults();
$('self-check').addEventListener('click', () => selfCheck().catch((err) => reportProblem('self-check', err)));
$('foot').textContent = `Built ${D.builtAt.slice(0, 16).replace('T', ' ')} UTC · ${SWE.runs.length} SWE-bench runs and ${num(BENCH.totalRequests)} API test requests · ${SWE.model} on Nebius Token Factory Public · works offline.`;
show(currentView());
const redraw = () => {
  themeDefaults();
  for (const v of inited) dirty.add(v);
  show(currentView());
};
window.matchMedia('(prefers-color-scheme: dark)').addEventListener?.('change', redraw);
