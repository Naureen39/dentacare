import { zodResolver } from '@hookform/resolvers/zod'
import { Award, BadgeCheck, Mail, MapPin, Phone, ShieldCheck, Siren } from 'lucide-react'
import { useForm } from 'react-hook-form'
import { Link } from 'react-router-dom'
import { z } from 'zod'

import { Button } from '@/components/ui/button'
import { Field } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { clinic, fullAddress, hours, legalLinks, socialLinks } from '@/content/site'
import { groups } from '@/content/services'
import { emailField } from '@/lib/forms'
import { useNewsletterMutation } from '@/lib/public-api'

const schema = z.object({ email: emailField })

const column =
  'text-sm text-primary-foreground [&_a]:rounded-sm [&_a]:text-primary-foreground [&_a:hover]:underline [&_li]:py-1'
const heading = 'mb-3 font-heading text-base font-bold text-white'

function SocialIcon({ name }: { name: string }) {
  const paths: Record<string, string> = {
    Facebook: 'M14 8h3V4h-3a4 4 0 0 0-4 4v2H7v4h3v8h4v-8h3l1-4h-4V8z',
    Instagram:
      'M7 3h10a4 4 0 0 1 4 4v10a4 4 0 0 1-4 4H7a4 4 0 0 1-4-4V7a4 4 0 0 1 4-4zm5 5a4 4 0 1 0 0 8 4 4 0 0 0 0-8zm5.5-2a1 1 0 1 0 0 2 1 1 0 0 0 0-2z',
    LinkedIn:
      'M4 9h4v11H4zM6 3a2 2 0 1 1 0 4 2 2 0 0 1 0-4zm5 6h4v2c.6-1.2 2-2.2 4-2.2 4 0 5 2.6 5 6V20h-4v-5c0-1.4-.1-3-2-3s-3 1.3-3 3v5h-4z',
    YouTube:
      'M22 8a3 3 0 0 0-2-2c-2-.5-8-.5-8-.5s-6 0-8 .5A3 3 0 0 0 2 8c-.5 2-.5 4-.5 4s0 2 .5 4a3 3 0 0 0 2 2c2 .5 8 .5 8 .5s6 0 8-.5a3 3 0 0 0 2-2c.5-2 .5-4 .5-4s0-2-.5-4zM10 15V9l5 3z',
  }
  return (
    <svg viewBox="0 0 24 24" className="size-5" fill="currentColor" aria-hidden="true">
      <path d={paths[name] ?? ''} />
    </svg>
  )
}

function Newsletter() {
  const form = useForm<z.infer<typeof schema>>({
    resolver: zodResolver(schema),
    defaultValues: { email: '' },
  })
  const mutation = useNewsletterMutation()
  const { errors } = form.formState
  return (
    <form
      noValidate
      onSubmit={form.handleSubmit((values) =>
        mutation.mutate(values.email, { onSuccess: () => form.reset() }),
      )}
      className="flex flex-col gap-3"
      aria-label="Newsletter signup"
    >
      <Field
        label="Email address"
        tone="inverted"
        error={
          errors.email?.message ??
          (mutation.isError ? 'We could not sign you up just now. Please try again.' : undefined)
        }
      >
        {(control) => (
          <Input
            {...control}
            type="email"
            autoComplete="email"
            placeholder="you@example.com"
            {...form.register('email')}
          />
        )}
      </Field>
      <Button type="submit" variant="accent" loading={mutation.isPending} className="w-fit">
        Subscribe
      </Button>
      <p role="status" className="text-sm text-primary-foreground/90">
        {mutation.isSuccess ? 'Thank you for subscribing.' : ''}
      </p>
    </form>
  )
}

export function Footer() {
  return (
    <footer className="bg-primary text-primary-foreground">
      <div className="container-page grid gap-10 py-14 md:grid-cols-2 lg:grid-cols-4">
        <nav aria-label="Services footer">
          <h2 className={heading}>Services</h2>
          <ul className={column}>
            {Object.entries(groups).map(([key, group]) => (
              <li key={key}>
                <Link to={`/services?group=${key}`}>{group.title}</Link>
              </li>
            ))}
            <li>
              <Link to="/pricing">Pricing</Link>
            </li>
          </ul>
        </nav>
        <nav aria-label="Company">
          <h2 className={heading}>Company</h2>
          <ul className={column}>
            <li>
              <Link to="/about">About us</Link>
            </li>
            <li>
              <Link to="/dentists">Our dentists</Link>
            </li>
            <li>
              <Link to="/reviews">Patient reviews</Link>
            </li>
            <li>
              <Link to="/resources">Resources</Link>
            </li>
            <li>
              <Link to="/contact">Contact</Link>
            </li>
          </ul>
        </nav>
        <nav aria-label="Patient resources">
          <h2 className={heading}>Patient resources</h2>
          <ul className={column}>
            <li>
              <Link to="/new-patients">New patients</Link>
            </li>
            <li>
              <Link to="/insurance-and-payment">Insurance and payment</Link>
            </li>
            <li>
              <Link to="/faq">FAQ</Link>
            </li>
            <li>
              <Link to="/new-patients#forms">Forms</Link>
            </li>
            <li>
              <Link to="/login">Patient login</Link>
            </li>
          </ul>
        </nav>
        <div>
          <h2 className={heading}>Contact</h2>
          <address className={`${column} not-italic`}>
            <p className="flex gap-2 py-1">
              <MapPin className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
              {fullAddress}
            </p>
            <p className="flex gap-2 py-1">
              <Phone className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
              <a href={clinic.phoneHref}>{clinic.phone}</a>
            </p>
            <p className="flex gap-2 py-1">
              <Siren className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
              Emergency <a href={clinic.emergencyHref}>{clinic.emergencyPhone}</a>
            </p>
            <p className="flex gap-2 py-1">
              <Mail className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
              <a href={`mailto:${clinic.email}`}>{clinic.email}</a>
            </p>
          </address>
        </div>
      </div>

      <div className="border-t border-white/15">
        <div className="container-page grid gap-10 py-10 md:grid-cols-2">
          <div>
            <h2 className={heading}>Opening hours</h2>
            <table className="w-full max-w-sm text-sm">
              <caption className="sr-only">Opening hours</caption>
              <tbody>
                {hours.map((row) => (
                  <tr key={row.days} className="border-b border-white/15 last:border-0">
                    <th scope="row" className="py-1.5 pr-4 text-left font-medium">
                      {row.days}
                    </th>
                    <td className="py-1.5">
                      {row.opens ? `${row.opens} to ${row.closes}` : 'Closed'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div>
            <h2 className={heading}>Newsletter</h2>
            <p className="mb-3 text-sm text-primary-foreground/90">
              Seasonal oral health tips and news from the practice, a few times a year.
            </p>
            <Newsletter />
          </div>
        </div>
      </div>

      <div className="border-t border-white/15">
        <div className="container-page flex flex-col gap-6 py-8">
          <div className="flex flex-wrap items-center justify-between gap-4">
            <ul className="flex flex-wrap gap-3" aria-label="Our commitments">
              {[
                [ShieldCheck, 'Infection control'],
                [BadgeCheck, 'Licensed clinicians'],
                [Award, 'Quality care'],
              ].map(([Icon, label]) => {
                const I = Icon as typeof ShieldCheck
                return (
                  <li
                    key={label as string}
                    className="inline-flex items-center gap-2 rounded-full border border-white/25 px-3 py-1.5 text-sm"
                  >
                    <I className="size-4" aria-hidden="true" />
                    {label as string}
                  </li>
                )
              })}
            </ul>
            <ul className="flex gap-2" aria-label="Social media">
              {socialLinks.map((s) => (
                <li key={s.name}>
                  <a
                    href={s.href}
                    target="_blank"
                    rel="noopener noreferrer"
                    aria-label={`${s.name} (opens in a new tab)`}
                    className="inline-flex size-10 items-center justify-center rounded-full bg-white/10 hover:bg-white/20"
                  >
                    <SocialIcon name={s.name} />
                  </a>
                </li>
              ))}
            </ul>
          </div>
          <nav aria-label="Legal">
            <ul className="flex flex-wrap gap-x-6 gap-y-2 text-sm">
              {legalLinks.map((l) => (
                <li key={l.to}>
                  <Link to={l.to} className="hover:underline">
                    {l.label}
                  </Link>
                </li>
              ))}
            </ul>
          </nav>
          <p className="text-sm text-primary-foreground/90">
            &copy; {new Date().getFullYear()} {clinic.name}. Demo environment, fictional clinic:
            names, reviews and prices are illustrative.
          </p>
        </div>
      </div>
    </footer>
  )
}
