// Shared Chromium launcher for the e2e checks.
// Playwright is a pinned devDependency (package.json + package-lock.json). Fresh checkout:
//   npm ci && npx playwright install chromium
// To use a Chromium that is already installed instead of Playwright's download, set
//   CHROMIUM_PATH=/path/to/chromium
let chromium;
try {
  ({ chromium } = require('playwright'));
} catch (err) {
  if (err && err.code === 'MODULE_NOT_FOUND') {
    console.error('Playwright is not installed. Run:  npm ci && npx playwright install chromium');
    process.exit(2);
  }
  throw err;
}

function launch() {
  const executablePath = process.env.CHROMIUM_PATH || undefined;
  return chromium.launch(executablePath ? { executablePath } : {}).catch((err) => {
    if (/Executable doesn't exist|browserType\.launch/i.test(String(err && err.message))) {
      console.error('Chromium for Playwright is missing. Run:  npx playwright install chromium  (or set CHROMIUM_PATH)');
    }
    throw err;
  });
}

module.exports = { launch };
