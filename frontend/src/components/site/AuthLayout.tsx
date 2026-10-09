import { ShieldCheck } from 'lucide-react'
import { Link } from 'react-router-dom'

import { Picture } from '@/components/site/Picture'
import { Seo } from '@/components/site/Seo'
import { skipLinkClass } from '@/components/layout/RootLayout'
import { clinic } from '@/content/site'

/** Split layout for sign in and registration: brand picture on one side, the form on the other. */
export function AuthLayout({
  title,
  path,
  children,
  subtitle,
}: {
  title: string
  path: string
  subtitle?: string
  children: React.ReactNode
}) {
  return (
    <div className="grid min-h-screen lg:grid-cols-2">
      <Seo
        title={title}
        description={`${title} to your ${clinic.name} account.`}
        path={path}
        noindex
      />
      <a href="#main-content" className={skipLinkClass}>
        Skip to main content
      </a>
      <aside
        className="relative hidden overflow-hidden bg-primary text-white lg:block"
        aria-label="Meridian Dental Care"
      >
        <Picture
          name="interior"
          alt=""
          sizes="50vw"
          priority
          className="absolute inset-0 h-full w-full opacity-60"
        />
        <div
          className="absolute inset-0 bg-gradient-to-t from-primary via-primary/70 to-primary/30"
          aria-hidden="true"
        />
        <div className="relative flex h-full flex-col justify-between p-12">
          <Link to="/" className="font-heading text-2xl font-extrabold text-white">
            Meridian <span className="text-accent">Dental</span>
          </Link>
          <div>
            <p className="max-w-md font-heading text-3xl font-bold text-white">{clinic.tagline}</p>
            <p className="mt-4 flex max-w-md items-start gap-2 text-white/90">
              <ShieldCheck className="mt-1 size-5 shrink-0" aria-hidden="true" />
              Your appointments, invoices and records in one private place, protected by encryption
              and two step verification for staff.
            </p>
          </div>
        </div>
      </aside>
      <main
        id="main-content"
        tabIndex={-1}
        className="flex items-center justify-center px-4 py-12 focus:outline-none"
      >
        <div className="w-full max-w-md">
          <Link
            to="/"
            className="mb-8 block font-heading text-xl font-extrabold text-primary lg:hidden"
          >
            Meridian <span className="text-accent-strong">Dental</span>
          </Link>
          <h1 className="text-3xl">{title}</h1>
          {subtitle && <p className="mt-2 text-muted-foreground">{subtitle}</p>}
          {children}
        </div>
      </main>
    </div>
  )
}
