import {
  Award,
  CalendarCheck,
  HeartPulse,
  LogIn,
  Phone,
  ScanLine,
  Siren,
  Smile,
  Sparkles,
  Stethoscope,
  Star,
  ShieldCheck,
} from 'lucide-react'
import { Link } from 'react-router-dom'

import { LocationSection } from '@/components/site/LocationSection'
import { Picture } from '@/components/site/Picture'
import { Carousel, CtaBand, ReviewCard, Section } from '@/components/site/parts'
import { Seo } from '@/components/site/Seo'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/display'
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from '@/components/ui/disclosure'
import { AnimatedNumber, FadeUp } from '@/components/ui/motion'
import { Rating } from '@/components/ui/metrics'
import { groups, homeServices } from '@/content/services'
import { dentists } from '@/content/people'
import {
  clinic,
  comfortPoints,
  homeFaqs,
  insuranceCategories,
  patientJourney,
  pillars,
  stats,
} from '@/content/site'
import { useCatalog, useReviews } from '@/lib/public-api'
import { faqSchema, localBusinessSchema } from '@/lib/schema'

const money = (value: number) => `$${value.toLocaleString('en-US')}`
const pillarIcons = [Stethoscope, ScanLine, HeartPulse, ShieldCheck]

function Hero() {
  return (
    <section
      aria-labelledby="hero-heading"
      className="relative isolate overflow-hidden bg-primary text-white"
    >
      <Picture
        name="hero"
        alt=""
        sizes="100vw"
        priority
        className="absolute inset-0 -z-20 h-full w-full"
      />
      <div
        className="absolute inset-0 -z-10 bg-gradient-to-r from-primary via-primary/90 to-primary/40"
        aria-hidden="true"
      />
      <div className="container-page py-16 md:py-28">
        <div className="max-w-2xl">
          <p className="mb-4 inline-flex rounded-full bg-white/15 px-3 py-1 text-sm font-semibold">
            Springfield&rsquo;s family and specialist dental practice
          </p>
          <h1 id="hero-heading" className="text-4xl text-white md:text-6xl">
            Exceptional dental care for every stage of life
          </h1>
          <p className="mt-5 max-w-xl text-lg text-white/90">
            From a child&rsquo;s first visit to implants and aligners, seven specialists care for
            your whole family in one calm, modern practice.
          </p>
          <div className="mt-8 flex flex-wrap gap-3">
            <Button asChild size="lg" variant="accent">
              <Link to="/book">Book an Appointment</Link>
            </Button>
            <Button
              asChild
              size="lg"
              variant="secondary"
              className="border-white bg-transparent text-white hover:bg-white/10"
            >
              <Link to="/services">Explore Services</Link>
            </Button>
          </div>
        </div>
        <dl className="mt-12 grid max-w-3xl grid-cols-2 gap-6 border-t border-white/25 pt-8 sm:grid-cols-4">
          {[
            [`${stats.years}+`, 'years of service'],
            [`${stats.patients.toLocaleString('en-US')}+`, 'patients served'],
            [`${stats.rating} of 5`, 'patient rating'],
            ['Same day', 'emergency care'],
          ].map(([value, label]) => (
            <div key={label}>
              <dt className="sr-only">{label}</dt>
              <dd className="font-heading text-2xl font-extrabold">{value}</dd>
              <dd className="text-sm text-white/85" aria-hidden="true">
                {label}
              </dd>
            </div>
          ))}
        </dl>
      </div>
    </section>
  )
}

function QuickActions() {
  const items = [
    {
      icon: CalendarCheck,
      title: 'Book online',
      text: 'See open times and choose one.',
      to: '/book',
    },
    { icon: Phone, title: 'Call us', text: clinic.phone, href: clinic.phoneHref },
    {
      icon: Siren,
      title: 'Emergency care',
      text: `Same day: ${clinic.emergencyPhone}`,
      href: clinic.emergencyHref,
    },
    { icon: LogIn, title: 'Patient login', text: 'Appointments and invoices.', to: '/login' },
  ]
  return (
    <section aria-label="Quick actions" className="relative z-10 -mt-8">
      <ul className="container-page grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {items.map(({ icon: Icon, title, text, to, href }) => {
          const body = (
            <>
              <span className="flex size-12 shrink-0 items-center justify-center rounded-full bg-secondary text-accent-strong">
                <Icon className="size-6" aria-hidden="true" />
              </span>
              <span>
                <span className="block font-heading text-base font-bold text-primary">{title}</span>
                <span className="block text-sm text-muted-foreground">{text}</span>
              </span>
            </>
          )
          return (
            <li key={title}>
              <Card variant="interactive" className="h-full">
                {to ? (
                  <Link to={to} className="flex items-center gap-4 rounded-xl p-5">
                    {body}
                  </Link>
                ) : (
                  <a href={href} className="flex items-center gap-4 rounded-xl p-5">
                    {body}
                  </a>
                )}
              </Card>
            </li>
          )
        })}
      </ul>
    </section>
  )
}

function StatsBand() {
  const items = [
    { value: stats.patients, suffix: '+', label: 'Patients served' },
    { value: stats.specialists, suffix: '', label: 'Specialists' },
    { value: stats.years, suffix: '+', label: 'Years of care' },
    { value: stats.rating, suffix: ' / 5', label: 'Patient satisfaction', decimals: 1 },
  ]
  return (
    <section aria-label="The practice in numbers" className="bg-primary py-12 text-white">
      <dl className="container-page grid grid-cols-2 gap-8 text-center lg:grid-cols-4">
        {items.map((item) => (
          <div key={item.label}>
            <dd className="font-heading text-4xl font-extrabold md:text-5xl">
              <AnimatedNumber
                value={item.value}
                format={(v) =>
                  `${item.decimals ? v.toFixed(item.decimals) : Math.round(v).toLocaleString('en-US')}${item.suffix}`
                }
              />
            </dd>
            <dt className="mt-1 text-sm text-white/85">{item.label}</dt>
          </div>
        ))}
      </dl>
    </section>
  )
}

export default function HomePage() {
  const { services } = useCatalog()
  const reviews = useReviews()
  const common = services.filter((s) => homeServices.some((h) => h.code === s.code))
  const pricing = services.filter((s) =>
    ['SV01', 'SV02', 'SV03', 'SV04', 'SV05', 'SV06', 'SV11', 'SV12'].includes(s.code),
  )
  return (
    <>
      <Seo
        title={clinic.name}
        description="Modern family and specialist dental care in Springfield. General, pediatric, orthodontic, implant and cosmetic dentistry, with same day emergency care."
        path="/"
        jsonLd={[localBusinessSchema(), faqSchema(homeFaqs)]}
      />
      <Hero />
      <QuickActions />
      <StatsBand />

      <Section
        id="services"
        title="Care for every smile"
        intro="Preventive, restorative, cosmetic, surgical and orthodontic care from one team."
      >
        <ul className="grid gap-6 sm:grid-cols-2 lg:grid-cols-4">
          {common.map((s, index) => (
            <li key={s.code}>
              <FadeUp delay={(index % 4) * 0.05} className="h-full">
                <Card variant="interactive" className="flex h-full flex-col overflow-hidden">
                  <Picture
                    name={groups[s.group].image}
                    alt=""
                    sizes="(min-width: 1024px) 25vw, (min-width: 640px) 50vw, 100vw"
                    className="aspect-[3/2]"
                  />
                  <div className="flex flex-1 flex-col gap-2 p-5">
                    <h3 className="font-heading text-lg font-bold">{s.name}</h3>
                    <p className="flex-1 text-sm text-muted-foreground">{s.summary}</p>
                    <Link
                      to={`/services/${s.slug}`}
                      className="inline-flex items-center gap-1 text-sm font-semibold text-accent-strong underline underline-offset-4"
                    >
                      Learn more <span className="sr-only">about {s.name}</span>
                    </Link>
                  </div>
                </Card>
              </FadeUp>
            </li>
          ))}
        </ul>
        <div className="mt-8 text-center">
          <Button asChild variant="secondary">
            <Link to="/services">See all services</Link>
          </Button>
        </div>
      </Section>

      <Section id="why" title="Why patients choose Meridian" tint>
        <ul className="grid gap-6 sm:grid-cols-2 lg:grid-cols-4">
          {pillars.map((p, i) => {
            const Icon = pillarIcons[i] ?? Smile
            return (
              <li key={p.title}>
                <Card className="h-full p-6">
                  <span className="flex size-12 items-center justify-center rounded-full bg-secondary text-accent-strong">
                    <Icon className="size-6" aria-hidden="true" />
                  </span>
                  <h3 className="mt-4 font-heading text-lg font-bold">{p.title}</h3>
                  <p className="mt-2 text-sm text-muted-foreground">{p.text}</p>
                </Card>
              </li>
            )
          })}
        </ul>
      </Section>

      <Section id="technology">
        <div className="grid items-center gap-10 md:grid-cols-2">
          <Picture
            name="technology"
            alt="An illustration in the practice colours"
            sizes="(min-width: 768px) 50vw, 100vw"
            className="aspect-[4/3] rounded-xl"
          />
          <div>
            <h2 className="text-2xl md:text-4xl">Technology and comfort, together</h2>
            <p className="mt-3 text-lg text-muted-foreground">
              Better tools should mean a better visit. We invest in both the equipment and the small
              comforts.
            </p>
            <ul className="mt-6 space-y-3">
              {comfortPoints.map((point) => (
                <li key={point} className="flex gap-3">
                  <Sparkles
                    className="mt-1 size-5 shrink-0 text-accent-strong"
                    aria-hidden="true"
                  />
                  {point}
                </li>
              ))}
            </ul>
          </div>
        </div>
      </Section>

      <Section
        id="team"
        title="Meet our dentists"
        intro="Seven specialists who work as one team."
        tint
      >
        <Carousel label="Our dentists">
          {dentists.map((d) => (
            <Card key={d.slug} className="flex h-full flex-col overflow-hidden">
              <Picture
                name={d.image}
                alt={`Portrait of ${d.name}`}
                sizes="(min-width: 1024px) 30vw, 85vw"
                className="aspect-square"
              />
              <div className="flex flex-1 flex-col gap-1 p-5">
                <h3 className="font-heading text-lg font-bold">{d.name}</h3>
                <p className="text-sm text-muted-foreground">
                  {d.credentials}, {d.specialty}
                </p>
                <div className="mt-auto flex flex-wrap gap-2 pt-4">
                  <Button asChild size="sm">
                    <Link to={`/book?dentist=${d.slug}`}>Book with {d.short}</Link>
                  </Button>
                  <Button asChild size="sm" variant="ghost">
                    <Link to={`/dentists/${d.slug}`}>
                      Profile <span className="sr-only">of {d.name}</span>
                    </Link>
                  </Button>
                </div>
              </div>
            </Card>
          ))}
        </Carousel>
      </Section>

      <Section id="journey" title="Your visit, step by step">
        <ol className="grid gap-6 md:grid-cols-4">
          {patientJourney.map((step, i) => (
            <li
              key={step.title}
              className="relative rounded-xl border bg-card p-6 shadow-soft md:before:absolute md:before:top-10 md:before:-right-4 md:before:h-0.5 md:before:w-4 md:before:bg-accent-strong md:last:before:hidden"
            >
              <span
                className="flex size-10 items-center justify-center rounded-full bg-accent-strong font-heading font-bold text-white"
                aria-hidden="true"
              >
                {i + 1}
              </span>
              <h3 className="mt-4 font-heading text-lg font-bold">
                <span className="sr-only">Step {i + 1}: </span>
                {step.title}
              </h3>
              <p className="mt-2 text-sm text-muted-foreground">{step.text}</p>
            </li>
          ))}
        </ol>
      </Section>

      <Section
        id="reviews"
        title="What patients say"
        intro="Reviews on this demonstration site are illustrative."
        tint
      >
        <div className="mb-6 flex items-center gap-3">
          <Rating value={stats.rating} />
          <span className="text-sm text-muted-foreground">
            {stats.rating} average from {stats.reviews} demonstration reviews
          </span>
        </div>
        <Carousel label="Patient reviews">
          {reviews.map((r) => (
            <ReviewCard key={r.id} review={r} />
          ))}
        </Carousel>
        <div className="mt-6">
          <Button asChild variant="secondary">
            <Link to="/reviews">Read more reviews</Link>
          </Button>
        </div>
      </Section>

      <Section
        id="pricing"
        title="Clear prices from the start"
        intro="Starting prices for common care. Your dentist confirms the exact cost, in writing, before any treatment."
      >
        <div className="overflow-x-auto rounded-xl border bg-card shadow-soft">
          <table className="w-full text-sm">
            <caption className="sr-only">Starting prices for common services</caption>
            <thead className="bg-secondary text-left">
              <tr>
                <th scope="col" className="px-4 py-3">
                  Service
                </th>
                <th scope="col" className="px-4 py-3">
                  Time
                </th>
                <th scope="col" className="px-4 py-3 text-right">
                  Starting price
                </th>
              </tr>
            </thead>
            <tbody>
              {pricing.map((s) => (
                <tr key={s.code} className="border-t">
                  <th scope="row" className="px-4 py-3 text-left font-medium">
                    <Link to={`/services/${s.slug}`} className="hover:underline">
                      {s.name}
                    </Link>
                  </th>
                  <td className="px-4 py-3">{s.minutes} min</td>
                  <td className="px-4 py-3 text-right font-semibold tabular-nums">
                    {money(s.price)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="mt-4 text-sm text-muted-foreground">
          Insurance can lower what you pay. We check your plan and tell you your share before you
          decide. <Link to="/pricing">See the full price list</Link>.
        </p>
      </Section>

      <Section id="insurance" title="Insurance and payment" tint>
        <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {insuranceCategories.map((c) => (
            <li key={c.title}>
              <Card className="h-full p-6">
                <h3 className="flex items-center gap-2 font-heading text-lg font-bold">
                  <Award className="size-5 text-accent-strong" aria-hidden="true" />
                  {c.title}
                </h3>
                <p className="mt-2 text-sm text-muted-foreground">{c.text}</p>
              </Card>
            </li>
          ))}
        </ul>
      </Section>

      <Section id="faq" title="Questions, answered">
        <Accordion type="single" collapsible className="max-w-3xl">
          {homeFaqs.map((f, i) => (
            <AccordionItem key={f.q} value={`q${i}`}>
              <AccordionTrigger>{f.q}</AccordionTrigger>
              <AccordionContent>{f.a}</AccordionContent>
            </AccordionItem>
          ))}
        </Accordion>
        <p className="mt-6 flex items-center gap-2 text-sm">
          <Star className="size-4 text-accent-strong" aria-hidden="true" />
          <Link to="/faq">More questions and a searchable list</Link>
        </p>
      </Section>

      <LocationSection />
      <CtaBand />
    </>
  )
}
