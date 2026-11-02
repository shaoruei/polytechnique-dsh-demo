// Page 1 · Run an agent: replay one of the 9 recorded SWE-bench runs.
let replayTimer = null;
PAGES.run = {
  html: () => `
    <div class="section-head">
      <h2>1 · Watch an agent fix a real Django bug</h2>
      <p>Real issues from SWE-bench Verified. The agent reads the code, edits it and runs tests; the official SWE-bench tests decide whether it worked.</p>
    </div>
    <div class="grid run-grid">
      <div class="panel run-side">
        <label class="field" for="run-select">Recorded run · 3 issues × 3 trials</label>
        <select id="run-select">${runOptions()}</select>
        <div class="issue">
          <p class="issue-id" id="issue-id"></p>
          <h3 id="issue-title"></h3>
          <p id="issue-summary"></p>
          <details><summary>Full issue as given to the agent</summary><pre class="prompt" id="run-prompt"></pre></details>
        </div>
        <div class="mini3" id="run-metrics"></div>
        <p class="result" id="run-result"></p>
      </div>
      <div class="panel wide">
        <div class="panel-head">
          <h3>Agent trajectory</h3>
          <div class="btns">
            <button type="button" id="replay-play">Replay</button>
            <select id="replay-speed" aria-label="Replay speed"><option value="1">1×</option><option value="3">3×</option><option value="10" selected>10×</option></select>
            <button type="button" class="ghost" id="replay-all">Show all</button>
          </div>
        </div>
        <div class="lane" id="lane" aria-label="Time spent per step"></div>
        <div class="lane-key"><span class="k k-llm"></span>LLM request<span class="k k-tool"></span>tool execution<span class="k k-gap"></span>harness</div>
        <ol class="events" id="events"></ol>
      </div>
    </div>`,
  init() {
    $('run-select').addEventListener('change', (e) => { selectRun(e.target.value); this.draw(); });
    $('replay-play').addEventListener('click', () => playReplay());
    $('replay-all').addEventListener('click', () => drawEvents(Infinity));
  },
  draw() {
    clearInterval(replayTimer);
    const r = currentRun;
    const inst = SWE.instances[r.instance_id];
    $('run-select').value = r.run_id;
    $('issue-id').textContent = `${inst.instance_id} · Django ${inst.version}`;
    $('issue-title').textContent = inst.title;
    $('issue-summary').textContent = inst.summary;
    $('run-prompt').textContent = inst.issue;
    $('run-metrics').innerHTML = [['Time', secs(r.wall_time_s)], ['LLM requests', num(r.metrics.llm_requests)], ['Cost', usd(r.metrics.cost_usd, 4)]]
      .map(([k, v]) => `<div><span>${k}</span><b>${v}</b></div>`).join('');
    $('run-result').innerHTML = r.official.resolved
      ? '<span class="pill ok">RESOLVED</span> official SWE-bench tests pass'
      : '<span class="pill bad">NOT RESOLVED</span> one hidden test still fails';
    drawEvents(Infinity);
  },
};

function callText(e) {
  try {
    const a = JSON.parse(e.text);
    if (e.name === 'bash' && a.command) return '$ ' + a.command;
    if (a.file_path || a.path || a.pattern) return [a.file_path ?? a.path, a.pattern].filter(Boolean).join('  ');
  } catch { /* truncated or not JSON: show as recorded */ }
  return e.text;
}
function eventRow(e) {
  const t = `<span class="t">${num(e.t, 1)}s</span>`;
  switch (e.k) {
    case 'step': return `<li class="step">${t}<span class="kind">request</span><span class="body">LLM request #${e.step}</span></li>`;
    case 'think': return `<li class="think">${t}<span class="kind">thinking</span><span class="body">${esc(e.text)}</span></li>`;
    case 'say': return `<li>${t}<span class="kind say">answer</span><span class="body">${esc(e.text)}</span></li>`;
    case 'call':
      if (e.edit) {
        const lines = (txt, sign) => (txt ? txt.split('\n').map((l) => sign + l).join('\n') : '');
        return `<li>${t}<span class="kind call">edit</span><span class="body edit"><code>${esc(e.edit.file)}</code><pre class="diff">${diffHtml([lines(e.edit.old, '-'), lines(e.edit.new, '+')].filter(Boolean).join('\n'))}</pre></span></li>`;
      }
      return `<li>${t}<span class="kind call">${esc(e.name)}</span><span class="body"><code>${esc(callText(e))}</code></span></li>`;
    case 'result': return `<li>${t}<span class="kind result${e.err ? ' err' : ''}">${e.err ? 'error' : 'result'}</span><span class="body"><code>${esc(e.text)}</code></span></li>`;
    case 'usage': return `<li>${t}<span class="kind">tokens</span><span class="body mono">in ${num(e.u + e.c)} (cached ${num(e.c)}) · out ${num(e.o)}</span></li>`;
    case 'end': return `<li class="step">${t}<span class="kind">done</span><span class="body">turn ended: ${esc(e.text)}</span></li>`;
    default: return '';
  }
}
function diffHtml(text) {
  return text.split('\n').map((l) => {
    const cls = l.startsWith('diff --git') || l.startsWith('+++') || l.startsWith('---') ? 'file' : l.startsWith('@@') ? 'hunk' : l.startsWith('+') ? 'add' : l.startsWith('-') ? 'del' : '';
    return cls ? `<span class="${cls}">${esc(l)}</span>` : esc(l);
  }).join('\n');
}
function laneSegments(events) {
  // step start -> assistant message (LLM) -> tool result(s) (tool) -> next step start (harness)
  const segs = [];
  let stepStart = null;
  let llmEnd = null;
  let toolEnd = null;
  const flush = (next) => {
    if (stepStart === null) return;
    const end = llmEnd ?? next;
    segs.push({ kind: 'llm', from: stepStart, to: end });
    if (toolEnd !== null) segs.push({ kind: 'tool', from: end, to: toolEnd });
    const last = toolEnd ?? end;
    if (next !== null && next > last) segs.push({ kind: 'gap', from: last, to: next });
  };
  for (const e of events) {
    if (e.k === 'step') {
      flush(e.t);
      stepStart = e.t;
      llmEnd = null;
      toolEnd = null;
    } else if (e.k === 'usage') llmEnd = e.t;
    else if (e.k === 'result') toolEnd = e.t;
    else if (e.k === 'end') {
      flush(null);
      stepStart = null;
    }
  }
  return segs;
}

function drawLane(r, upTo = Infinity) {
  const events = SWE.replays[r.run_id];
  const segs = laneSegments(events);
  const total = Math.max(...segs.map((s) => s.to), 0.001);
  $('lane').innerHTML = segs.map((s) =>
    `<span class="${s.kind}${s.from > upTo ? ' dim' : ''}" style="width:${((s.to - s.from) / total) * 100}%" title="${s.kind} ${num(s.to - s.from, 2)} s"></span>`).join('');
}

function drawEvents(upTo, animateFrom = Infinity) {
  const events = SWE.replays[currentRun.run_id];
  const shown = events.filter((e) => e.t <= upTo);
  const list = $('events');
  list.innerHTML = shown.map(eventRow).join('');
  if (Number.isFinite(animateFrom)) {
    const items = list.children;
    for (let i = animateFrom; i < items.length; i++) items[i].classList.add('enter');
    list.scrollTop = list.scrollHeight;
  }
  drawLane(currentRun, upTo);
}

function playReplay() {
  clearInterval(replayTimer);
  const events = SWE.replays[currentRun.run_id];
  const end = events.at(-1).t;
  const speed = Number($('replay-speed').value);
  const start = performance.now();
  let lastCount = 0;
  drawEvents(-1);
  replayTimer = setInterval(() => {
    const t = ((performance.now() - start) / 1000) * speed;
    const count = events.filter((e) => e.t <= t).length;
    if (count !== lastCount) {
      drawEvents(t, lastCount);
      lastCount = count;
    }
    if (t > end) clearInterval(replayTimer);
  }, 100);
}


