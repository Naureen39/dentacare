import { Outlet } from 'react-router-dom'

export function RootLayout() {
  return (
    <div className="flex min-h-screen flex-col">
      <a
        href="#main-content"
        className="sr-only z-50 rounded-md bg-primary px-4 py-2 text-primary-foreground focus:not-sr-only focus:absolute focus:top-2 focus:left-2"
      >
        Skip to main content
      </a>
      <header className="border-b bg-white">
        <div className="mx-auto flex h-16 max-w-[1240px] items-center px-4">
          <span className="font-heading text-xl font-extrabold text-primary">
            Meridian <span className="text-accent">Dental</span>
          </span>
        </div>
      </header>
      <main id="main-content" className="flex-1">
        <Outlet />
      </main>
      <footer className="bg-primary text-sm text-primary-foreground/80">
        <div className="mx-auto max-w-[1240px] px-4 py-6">Demo environment, fictional clinic.</div>
      </footer>
    </div>
  )
}
