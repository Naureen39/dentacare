// Renders every public page to HTML after the build, so a visitor (and a search engine) gets
// the real content, title, meta tags and structured data before any JavaScript runs. The
// browser then attaches the interactive application to that HTML.
//
// Run by `npm run build`, after the client build (dist) and the server build (dist-server).
import { mkdir, readFile, rm, writeFile } from 'node:fs/promises'
import { dirname, join } from 'node:path'
import { pathToFileURL } from 'node:url'

const DIST = process.env.PRERENDER_DIST ?? 'dist'
const SERVER = 'dist-server'

const { render, publicPaths } = await import(pathToFileURL(join(SERVER, 'entry-server.js')).href)
const template = await readFile(join(DIST, 'index.html'), 'utf-8')

// The page is complete HTML and CSS, so it paints without any script. The application script is
// started once the page has loaded (from a small file, as the site's policy allows no inline
// scripts) so that downloading it never competes with showing the page.
const entry = template.match(/<script type="module" crossorigin src="([^"]+)"><\/script>/)
if (!entry) throw new Error('index.html has no application script')
await writeFile(
  join(DIST, 'start.js'),
  `addEventListener('load',function(){setTimeout(function(){import('${entry[1]}')},0)})
`,
)

// The template's own title, description and script tags are replaced by each page's own.
const base = template
  .replace(/<title>[\s\S]*?<\/title>/, '')
  .replace(/<meta\s+name="description"[^>]*>/, '')
  .replace(entry[0], '<script src="/start.js" defer></script>')
  .replace(/<link rel="modulepreload"[^>]*>\s*/g, '')

function page({ html, head }) {
  if (!base.includes('<div id="root"></div>'))
    throw new Error('index.html has no empty root element')
  return base
    .replace('</head>', `${head}</head>`)
    .replace('<div id="root"></div>', `<div id="root">${html}</div>`)
}

let count = 0
for (const path of publicPaths) {
  const rendered = await render(path)
  if (rendered.status !== 200) throw new Error(`${path} rendered with status ${rendered.status}`)
  const file = path === '/' ? join(DIST, 'index.html') : join(DIST, path, 'index.html')
  await mkdir(dirname(file), { recursive: true })
  await writeFile(file, page(rendered))
  count += 1
}

// The shell for addresses that are not prerendered (sign in, the account area): an empty page
// that the application fills in the browser.
await writeFile(join(DIST, 'app.html'), base)

await rm(SERVER, { recursive: true, force: true })
console.log(`Prerendered ${count} pages and the application shell.`)
