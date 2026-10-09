// Builds the app, serves it, and audits pages with Lighthouse (mobile settings, the default).
//
//   npm run audit:site
//
// Home and one inner page must reach 90 for performance and 95 for accessibility, best
// practices and SEO. The style guide must reach 95 for accessibility. Needs Chrome or Chromium;
// set CHROME_PATH if it is not in a usual place. Only the process started here is stopped.
import { spawnSync } from 'node:child_process'
import { createReadStream, statSync } from 'node:fs'
import { createServer } from 'node:http'
import { extname, join, normalize } from 'node:path'
import { createGzip } from 'node:zlib'
import { existsSync, readFileSync, rmSync } from 'node:fs'

const PORT = 4173
const OUT = 'dist-audit'
const targets = [
  { path: '/', need: { performance: 0.9, accessibility: 0.95, 'best-practices': 0.95, seo: 0.95 } },
  {
    path: '/services/porcelain-crown',
    need: { performance: 0.9, accessibility: 0.95, 'best-practices': 0.95, seo: 0.95 },
  },
  { path: '/styleguide', need: { accessibility: 0.95 } },
]

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

// The same steps as `npm run build`, into a separate folder, with the style guide included.
const env = { VITE_ENABLE_STYLEGUIDE: 'true', PRERENDER_DIST: OUT }
for (const args of process.env.AUDIT_REUSE_BUILD
  ? []
  : [
      ['vite', 'build', '--outDir', OUT],
      ['vite', 'build', '--ssr', 'src/entry-server.tsx', '--outDir', 'dist-server'],
      [`"${process.execPath}"`, 'scripts/prerender.mjs'],
    ]) {
  const [command, ...rest] = args[0] === 'vite' ? ['npx', ...args] : args
  if (run(command, rest, env).status !== 0) process.exit(1)
}

// A small static server that compresses like the production proxy does, so the audit measures
// what visitors get and not an uncompressed development preview.
const types = {
  '.html': 'text/html',
  '.js': 'text/javascript',
  '.css': 'text/css',
  '.webp': 'image/webp',
  '.woff2': 'font/woff2',
  '.svg': 'image/svg+xml',
  '.json': 'application/json',
  '.xml': 'application/xml',
  '.txt': 'text/plain',
  '.pdf': 'application/pdf',
}
const server = createServer((request, response) => {
  const url = new URL(request.url ?? '/', 'http://localhost')
  let file = join(OUT, normalize(decodeURIComponent(url.pathname)))
  if (existsSync(file) && statSync(file).isDirectory()) file = join(file, 'index.html')
  if (!file.startsWith(OUT) || !existsSync(file)) file = join(OUT, 'app.html')
  const type = types[extname(file)] ?? 'application/octet-stream'
  const headers = {
    'Content-Type': type,
    'Cache-Control': file.includes('assets') ? 'public, max-age=31536000, immutable' : 'no-cache',
  }
  const compress =
    /(html|javascript|css|svg|json|xml|text)/.test(type) &&
    String(request.headers['accept-encoding']).includes('gzip')
  if (compress) {
    response.writeHead(200, { ...headers, 'Content-Encoding': 'gzip', Vary: 'Accept-Encoding' })
    createReadStream(file).pipe(createGzip()).pipe(response)
  } else {
    response.writeHead(200, headers)
    createReadStream(file).pipe(response)
  }
})
await new Promise((resolve) => server.listen(PORT, resolve))
const stop = () => server.close()

let failed = false
try {
  for (const { path, need } of targets) {
    const report = `lh-${path.replace(/\W+/g, '_')}.json`
    const result = run(
      'npx',
      [
        'lighthouse',
        `http://localhost:${PORT}${path}`,
        `--only-categories=${Object.keys(need).join(',')}`,
        '--chrome-flags="--headless=new --no-sandbox"',
        '--output=json',
        `--output-path=${report}`,
        '--quiet',
      ],
      { CHROME_PATH: chrome },
    )
    if (result.status !== 0) {
      failed = true
      continue
    }
    const data = JSON.parse(readFileSync(report, 'utf-8'))
    if (!process.env.AUDIT_KEEP) rmSync(report, { force: true })
    const line = Object.entries(need).map(([key, min]) => {
      const score = data.categories[key].score
      if (score < min) failed = true
      return `${key} ${Math.round(score * 100)}${score < min ? ` (needs ${min * 100})` : ''}`
    })
    console.log(`
${path}: ${line.join(', ')}`)
    const metric = (id) => data.audits[id]?.displayValue
    if (need.performance)
      console.log(
        `  FCP ${metric('first-contentful-paint')}, LCP ${metric('largest-contentful-paint')}, TBT ${metric('total-blocking-time')}, CLS ${metric('cumulative-layout-shift')}`,
      )
    for (const item of data.audits['color-contrast']?.details?.items ?? []) {
      console.log(
        `  contrast: ${item.node.snippet.slice(0, 80)} ${String(item.node.explanation).replace(/\s+/g, ' ').slice(0, 140)}`,
      )
    }
    for (const audit of Object.values(data.audits)) {
      if (audit.scoreDisplayMode === 'binary' && audit.score === 0)
        console.log(`  failed: ${audit.id} (${audit.title})`)
    }
  }
} finally {
  stop()
}
process.exitCode = failed ? 1 : 0
