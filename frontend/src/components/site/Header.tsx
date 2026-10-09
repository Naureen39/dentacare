import { Clock, Menu, Phone, Siren } from 'lucide-react'
import * as React from 'react'
import { Link, NavLink, useLocation } from 'react-router-dom'

import { NavDisclosure } from '@/components/site/NavDisclosure'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog'
import { clinic, hours, mainNav } from '@/content/site'
import { groups, services, type ServiceGroup } from '@/content/services'
import { useAuth } from '@/lib/auth'
import { showStyleguide } from '@/lib/features'
import { cn } from '@/lib/utils'

const link =
  'rounded-full px-3 py-2 text-sm font-semibold text-primary hover:bg-secondary aria-[current=page]:bg-secondary focus-visible:outline-2 focus-visible:outline-ring'

export function TopBar() {
  const weekdays = hours[0]
  return (
    <div className="hidden bg-primary text-sm text-primary-foreground md:block">
      <div className="container-page flex items-center justify-between gap-4 py-2">
        <ul className="flex flex-wrap items-center gap-x-6 gap-y-1">
          <li>
            <a href={clinic.phoneHref} className="inline-flex items-center gap-1.5 hover:underline">
              <Phone className="size-4" aria-hidden="true" />
              {clinic.phone}
            </a>
          </li>
          <li>
            <a
              href={clinic.emergencyHref}
              className="inline-flex items-center gap-1.5 hover:underline"
            >
              <Siren className="size-4" aria-hidden="true" />
              Emergency line {clinic.emergencyPhone}
            </a>
          </li>
          <li className="inline-flex items-center gap-1.5">
            <Clock className="size-4" aria-hidden="true" />
            Mon to Fri {weekdays.opens} to {weekdays.closes}, Sat 9:00 AM to 2:00 PM
          </li>
        </ul>
        <Link to="/login" className="font-semibold hover:underline">
          Patient login
        </Link>
      </div>
    </div>
  )
}

const groupOrder: ServiceGroup[] = ['preventive', 'restorative', 'cosmetic', 'surgical-orthodontic']

function ServicesMenu({ close }: { close: () => void }) {
  return (
    <div className="grid w-[min(62rem,92vw)] gap-6 lg:grid-cols-4">
      {groupOrder.map((group) => (
        <div key={group}>
          <Link
            to={`/services?group=${group}`}
            onClick={close}
            className="font-heading text-base font-bold text-primary hover:text-accent-strong"
          >
            {groups[group].title}
          </Link>
          <p className="mt-1 text-sm text-muted-foreground">{groups[group].text}</p>
          <ul className="mt-3 space-y-1">
            {services
              .filter((s) => s.group === group)
              .map((s) => (
                <li key={s.code}>
                  <Link
                    to={`/services/${s.slug}`}
                    onClick={close}
                    className="block rounded-md px-2 py-1.5 text-sm hover:bg-secondary"
                  >
                    {s.name}
                  </Link>
                </li>
              ))}
          </ul>
        </div>
      ))}
    </div>
  )
}

function PatientInfoMenu({ close }: { close: () => void }) {
  return (
    <ul className="w-72 space-y-1">
      {mainNav.patientInfo.map((item) => (
        <li key={item.to}>
          <Link
            to={item.to}
            onClick={close}
            className="block rounded-md px-3 py-2 hover:bg-secondary"
          >
            <span className="block text-sm font-semibold text-primary">{item.label}</span>
            <span className="block text-sm text-muted-foreground">{item.text}</span>
          </Link>
        </li>
      ))}
    </ul>
  )
}

function MobileMenu() {
  const [open, setOpen] = React.useState(false)
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button variant="ghost" size="icon" className="lg:hidden" aria-label="Open menu">
          <Menu className="size-6" aria-hidden="true" />
        </Button>
      </DialogTrigger>
      <DialogContent
        side="left"
        className="max-w-none sm:max-w-none"
        aria-describedby="mobile-menu-help"
      >
        <DialogTitle>Menu</DialogTitle>
        <DialogDescription id="mobile-menu-help" className="sr-only">
          Site navigation
        </DialogDescription>
        {/* Choosing any link closes the menu, so the next page is not hidden behind it. */}
        <div onClick={(event) => (event.target as HTMLElement).closest('a') && setOpen(false)}>
          <nav aria-label="Mobile">
            <ul className="space-y-1 text-lg">
              <li>
                <Link className="block rounded-md px-2 py-2.5 font-semibold" to="/">
                  Home
                </Link>
              </li>
              <li>
                <Link className="block rounded-md px-2 py-2.5 font-semibold" to="/services">
                  Services
                </Link>
              </li>
              <li>
                <ul className="mb-2 ml-3 grid grid-cols-1 gap-0.5 border-l pl-3 text-base">
                  {groupOrder.map((g) => (
                    <li key={g}>
                      <Link className="block py-1.5" to={`/services?group=${g}`}>
                        {groups[g].title}
                      </Link>
                    </li>
                  ))}
                </ul>
              </li>
              <li>
                <Link className="block rounded-md px-2 py-2.5 font-semibold" to="/dentists">
                  Our dentists
                </Link>
              </li>
              <li>
                <span className="block px-2 pt-2.5 font-semibold">Patient info</span>
                <ul className="mb-2 ml-3 border-l pl-3 text-base">
                  {mainNav.patientInfo.map((i) => (
                    <li key={i.to}>
                      <Link className="block py-1.5" to={i.to}>
                        {i.label}
                      </Link>
                    </li>
                  ))}
                </ul>
              </li>
              {[
                ['Reviews', '/reviews'],
                ['About', '/about'],
                ['Contact', '/contact'],
              ].map(([label, to]) => (
                <li key={to}>
                  <Link className="block rounded-md px-2 py-2.5 font-semibold" to={to as string}>
                    {label}
                  </Link>
                </li>
              ))}
            </ul>
          </nav>
          <div className="mt-4 grid gap-3">
            <Button asChild size="lg">
              <Link to="/book">Book an appointment</Link>
            </Button>
            <Button asChild size="lg" variant="secondary">
              <Link to="/login">Patient login</Link>
            </Button>
            <Button asChild size="lg" variant="ghost">
              <a href={clinic.phoneHref}>Call {clinic.phone}</a>
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  )
}

export function Header() {
  const { status, user, logout } = useAuth()
  const location = useLocation()
  const inServices = location.pathname.startsWith('/services')
  const inInfo = mainNav.patientInfo.some((i) => location.pathname === i.to.split('#')[0])
  return (
    <header className="sticky top-0 z-40 border-b bg-white/95 backdrop-blur">
      <div className="container-page flex h-16 items-center justify-between gap-4 lg:h-[72px]">
        <Link
          to="/"
          className="font-heading text-xl font-extrabold text-primary"
          aria-label={`${clinic.name}, home`}
        >
          Meridian <span className="text-accent-strong">Dental</span>
        </Link>
        <nav aria-label="Main" className="hidden lg:block">
          <ul className="flex items-center gap-0.5">
            <li>
              <NavLink to="/" end className={link}>
                Home
              </NavLink>
            </li>
            <NavDisclosure label="Services" active={inServices} panelClassName="-left-40">
              {(close) => <ServicesMenu close={close} />}
            </NavDisclosure>
            <li>
              <NavLink to="/dentists" className={link}>
                Our dentists
              </NavLink>
            </li>
            <NavDisclosure label="Patient info" active={inInfo}>
              {(close) => <PatientInfoMenu close={close} />}
            </NavDisclosure>
            <li>
              <NavLink to="/reviews" className={link}>
                Reviews
              </NavLink>
            </li>
            <li>
              <NavLink to="/about" className={link}>
                About
              </NavLink>
            </li>
            <li>
              <NavLink to="/contact" className={link}>
                Contact
              </NavLink>
            </li>
            {showStyleguide && (
              <li>
                <NavLink to="/styleguide" className={link}>
                  Style guide
                </NavLink>
              </li>
            )}
          </ul>
        </nav>
        <div className="flex items-center gap-2">
          {status === 'authenticated' && user ? (
            <>
              <Button asChild variant="secondary" size="sm" className="hidden sm:inline-flex">
                <Link to="/account">Account</Link>
              </Button>
              <Button
                variant="ghost"
                size="sm"
                className="hidden sm:inline-flex"
                onClick={() => void logout()}
              >
                Sign out
              </Button>
            </>
          ) : (
            <Button
              asChild
              variant="secondary"
              size="sm"
              className={cn('hidden', 'lg:inline-flex')}
            >
              <Link to="/login">Patient login</Link>
            </Button>
          )}
          <Button asChild size="sm" className="hidden sm:inline-flex">
            <Link to="/book">Book appointment</Link>
          </Button>
          <MobileMenu />
        </div>
      </div>
    </header>
  )
}
