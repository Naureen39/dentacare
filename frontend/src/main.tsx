import { StrictMode } from 'react'
import { createRoot, hydrateRoot } from 'react-dom/client'

import { App } from '@/app/App'
import { createAppRouter } from '@/app/routes'
import '@/styles/globals.css'

const container = document.getElementById('root')
if (!container) throw new Error('Root element not found')

const router = createAppRouter()
const app = (
  <StrictMode>
    <App router={router} />
  </StrictMode>
)

if (container.hasChildNodes()) {
  // The page arrived already rendered. Wait until the route's code is loaded so the first
  // client render matches the HTML exactly, then attach to it.
  if (!router.state.initialized) {
    await new Promise<void>((resolve) => {
      const stop = router.subscribe((state) => {
        if (state.initialized) {
          stop()
          resolve()
        }
      })
    })
  }
  hydrateRoot(container, app)
} else {
  createRoot(container).render(app)
}
