// Drives the stock DSH Web UI exactly as a presenter would (used for the prep-sandbox rehearsals).
// Usage: node drive_webui.cjs URL_WITH_TOKEN WORKSPACE_DIR PROMPT_FILE OUT_DIR MAX_WAIT_SECONDS
// Takes a screenshot every 15 s, records (and accepts) any approval prompt, stops at 'Completed in'/'This turn failed'.
// Usage: node submit.cjs URL WORKSPACE PROMPT_FILE OUT_DIR WAIT_SECONDS [MODEL_LABEL]
const { chromium } = require('playwright');
const fs = require('fs');
(async () => {
  const [url, ws, promptFile, out, waitS, modelLabel] = process.argv.slice(2);
  fs.mkdirSync(out, { recursive: true });
  const b = await chromium.launch();
  const p = await b.newPage({ viewport: { width: 1440, height: 1000 } });
  await p.goto(url, { waitUntil: 'networkidle' });
  await p.waitForTimeout(2500);
  const c = p.getByRole('button', { name: 'Continue' });
  if (await c.count()) { await c.click(); await p.waitForTimeout(800); }
  const sel = p.getByText('Choose workspace');
  if (await sel.count()) {
    await sel.first().click({ force: true });
    await p.waitForTimeout(1000);
    await p.getByRole('button', { name: 'Edit path' }).click();
    await p.keyboard.press('Control+A'); await p.keyboard.type(ws); await p.keyboard.press('Enter');
    await p.waitForTimeout(1000);
    await p.getByRole('button', { name: 'Open' }).click();
    await p.waitForTimeout(2000);
  }
  if (modelLabel) {
    await p.getByText(/DeepSeek-V4\.1-Flash|gpt-oss/).first().click({ force: true });
    await p.waitForTimeout(1000);
    await p.screenshot({ path: `${out}/model-menu.png` });
    await p.getByText(modelLabel, { exact: false }).last().click({ force: true });
    await p.waitForTimeout(800);
  }
  const box = p.locator('textarea, [contenteditable="true"]').last();
  await box.click();
  await box.fill(fs.readFileSync(promptFile, 'utf8'));
  await p.waitForTimeout(500);
  await p.screenshot({ path: `${out}/01-prompt-pasted.png` });
  await p.keyboard.press('Enter');
  const t0 = Date.now(); let i = 0;
  while ((Date.now() - t0) / 1000 < Number(waitS)) {
    await p.waitForTimeout(15000); i++;
    for (const name of [/^Allow/i, /^Approve/i, /^Always allow/i, /^Run$/i, /^Yes$/i]) {
      const btn = p.getByRole('button', { name });
      if (await btn.count()) {
        const t = new Date().toISOString();
        await p.screenshot({ path: `${out}/approval-${String(i).padStart(2, '0')}.png` });
        fs.appendFileSync(`${out}/approvals.log`, `${t} clicked ${name}\n`);
        await btn.first().click({ force: true });
        await p.waitForTimeout(1000);
      }
    }
    await p.screenshot({ path: `${out}/progress-${String(i).padStart(2, '0')}.png`, fullPage: false });
    const txt = await p.evaluate(() => document.body.innerText);
    if (/Completed in \d|This turn failed|Interrupted/.test(txt)) break;
  }
  await p.screenshot({ path: `${out}/99-final.png`, fullPage: true });
  fs.writeFileSync(`${out}/page-text.txt`, await p.evaluate(() => document.body.innerText));
  console.log('elapsed_s', Math.round((Date.now() - t0) / 1000));
  await b.close();
})();
