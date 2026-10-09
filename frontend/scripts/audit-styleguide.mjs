// Builds the app with the style guide switched on, serves it, and runs a Lighthouse accessibility
// audit of /styleguide. Exits with an error if the score is below the threshold.
//
//   npm run audit:styleguide
//
// Needs Chrome or Chromium. Set CHROME_PATH if it is not in a usual place.
import { spawn, spawnSync } from 'node:child_process'
import { existsSync, readFileSync, rmSync } from 'node:fs'

const PORT = 4173
const THRESHOLD = 0.95
const OUT = 'dist-audit'
const REPORT = 'lh-styleguide.json'

const candidates = [
  process.env.CHROME_PATH,
  'C:/Program Files/Google/Chrome/Application/chrome.exe',
  'C:/Program Files (x86)/Google/Chrome/Application/chrome.exe',
  '/usr/bin/google-chrome',
  '/usr/bin/chromium',
  '/usr/bin/chromium-browser',
  '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
].filter(Boolean)
const chrome = candidates.find((path) => existsSync(path))
if (!chrome) {
  console.error('Chrome was not found. Set CHROME_PATH to the browser executable.')
  process.exit(2)
}

const run = (command, args, env = {}) =>
  spawnSync(command, args, { stdio: 'inherit', shell: true, env: { ...process.env, ...env } })

if (
  run('npx', ['vite', 'build', '--outDir', OUT], { VITE_ENABLE_STYLEGUIDE: 'true' }).status !== 0
) {
  process.exit(1)
}

const server = spawn(
  'npx',
  ['vite', 'preview', '--outDir', OUT, '--port', String(PORT), '--strictPort'],
  {
    stdio: 'ignore',
    shell: true,
  },
)
const stop = () => {
  if (process.platform === 'win32')
    spawnSync('taskkill', ['/pid', String(server.pid), '/T', '/F'], { shell: true })
  else server.kill()
}

try {
  for (let i = 0; i < 50; i += 1) {
    try {
      if ((await fetch(`http://localhost:${PORT}/styleguide`)).ok) break
    } catch {
      /* not up yet */
    }
    await new Promise((resolve) => setTimeout(resolve, 200))
  }
  const result = run(
    'npx',
    [
      'lighthouse',
      `http://localhost:${PORT}/styleguide`,
      '--only-categories=accessibility,best-practices',
      '--chrome-flags="--headless=new --no-sandbox"',
      '--output=json',
      `--output-path=${REPORT}`,
      '--quiet',
    ],
    { CHROME_PATH: chrome },
  )
  if (result.status !== 0) process.exit(result.status ?? 1)
  const report = JSON.parse(readFileSync(REPORT, 'utf-8'))
  const accessibility = report.categories.accessibility.score
  const practices = report.categories['best-practices'].score
  const failed = Object.values(report.audits).filter(
    (a) => a.scoreDisplayMode === 'binary' && a.score === 0,
  )
  console.log(
    `\nAccessibility ${Math.round(accessibility * 100)}, best practices ${Math.round(practices * 100)}`,
  )
  for (const audit of failed) console.log(`  failed: ${audit.id} (${audit.title})`)
  if (accessibility < THRESHOLD) {
    console.error(`Accessibility is below ${THRESHOLD * 100}.`)
    process.exitCode = 1
  }
} finally {
  stop()
  rmSync(REPORT, { force: true })
}
