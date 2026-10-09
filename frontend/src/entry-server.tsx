import { renderToString } from 'react-dom/server'
import { createStaticHandler, createStaticRouter, StaticRouterProvider } from 'react-router-dom'

import { Providers, type HelmetContext } from '@/app/Providers'
import { buildRoutes } from '@/app/routes'
import { sitemapPaths } from '../vite-plugins/seo'

/** The addresses that are rendered ahead of time: every public page. */
export const publicPaths = sitemapPaths()

export interface Rendered {
  html: string
  head: string
  status: number
}

/** Render one address to HTML, plus the title and meta tags its page asked for. */
export async function render(path: string): Promise<Rendered> {
  const handler = createStaticHandler(buildRoutes(false))
  const context = await handler.query(new Request(`http://localhost${path}`))
  if (context instanceof Response) throw new Error(`Unexpected redirect while rendering ${path}`)
  const router = createStaticRouter(handler.dataRoutes, context)
  const helmetContext: HelmetContext = {}
  const html = renderToString(
    <Providers helmetContext={helmetContext}>
      <StaticRouterProvider router={router} context={context} hydrate={false} />
    </Providers>,
  )
  const h = helmetContext.helmet
  const head = h ? [h.title, h.meta, h.link, h.script].map((part) => part.toString()).join('') : ''
  return { html, head, status: context.statusCode }
}
