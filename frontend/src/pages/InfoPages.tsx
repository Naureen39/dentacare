import { Download, FileText, Search } from 'lucide-react'
import * as React from 'react'
import { Link } from 'react-router-dom'

import { Picture } from '@/components/site/Picture'
import { CtaBand, PageHeader, ReviewCard, Section } from '@/components/site/parts'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/display'
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from '@/components/ui/disclosure'
import { Field } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { Rating } from '@/components/ui/metrics'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { groups, type ServiceGroup } from '@/content/services'
import { clinic, homeFaqs, insuranceCategories, stats } from '@/content/site'
import { useCatalog, useReviews } from '@/lib/public-api'
import { faqSchema } from '@/lib/schema'

const money = (value: number) => `$${value.toLocaleString('en-US')}`

// --- About ---------------------------------------------------------------------------------------

const values = [
  {
    title: 'Honesty',
    text: 'We tell you what you need, what can wait and what it costs, and we never recommend treatment you do not need.',
  },
  {
    title: 'Comfort',
    text: 'A calm room, a gentle hand and time to ask questions make dental care easier to come back to.',
  },
  {
    title: 'Skill',
    text: 'Specialists in every field of dentistry work together, so you rarely need to go elsewhere.',
  },
  {
    title: 'Respect',
    text: 'Every patient is a person first. We listen, we explain, and the decision is always yours.',
  },
]
const timeline = [
  { year: String(clinic.founded), text: 'Dr. Raman opens the practice with two treatment rooms.' },
  {
    year: '2014',
    text: 'Orthodontics and pediatric dentistry join, and the practice moves to Harbor View Drive.',
  },
  { year: '2019', text: 'Digital imaging replaces film x-rays throughout the practice.' },
  {
    year: '2023',
    text: 'Oral surgery and implant care open in-house, so patients no longer need a referral.',
  },
  {
    year: String(new Date().getFullYear()),
    text: 'Cosmetic dentistry and online booking complete the service. Seven specialists now share the practice.',
  },
]
const community = [
  'Free dental screenings for local schools each spring',
  'Reduced-fee emergency care days for people without insurance',
  'Donated smile makeovers for community members in need',
  'Oral health talks for older adults at the neighbourhood centre',
]

export function AboutPage() {
  return (
    <>
      <PageHeader
        crumbs={[{ label: 'About' }]}
        title="About Meridian Dental Care"
        intro="A family and specialist practice built on honest advice and unhurried care."
        seo={{
          description:
            'The story, values and community work of Meridian Dental Care, a family and specialist dental practice in Springfield.',
          path: '/about',
          image: 'about',
        }}
      />
      <Section title="Our mission">
        <div className="grid items-center gap-10 md:grid-cols-2">
          <p className="text-xl">
            To make excellent dental care feel welcoming, understandable and fair, so that every
            patient leaves with a healthier mouth and the confidence to look after it.
          </p>
          <Picture
            name="about"
            alt="An illustration in the practice colours"
            sizes="(min-width: 768px) 50vw, 100vw"
            className="aspect-[4/3] rounded-xl"
          />
        </div>
      </Section>
      <Section title="What we value" tint>
        <ul className="grid gap-6 sm:grid-cols-2 lg:grid-cols-4">
          {values.map((v) => (
            <li key={v.title}>
              <Card className="h-full p-6">
                <h3 className="font-heading text-lg font-bold">{v.title}</h3>
                <p className="mt-2 text-sm text-muted-foreground">{v.text}</p>
              </Card>
            </li>
          ))}
        </ul>
      </Section>
      <Section title="Our story">
        <ol className="max-w-3xl space-y-6 border-l-2 border-accent-strong pl-6">
          {timeline.map((t) => (
            <li key={t.year}>
              <p className="font-heading text-xl font-bold text-primary">{t.year}</p>
              <p className="text-muted-foreground">{t.text}</p>
            </li>
          ))}
        </ol>
      </Section>
      <Section
        title="Our facility"
        intro="Bright treatment rooms, a quiet waiting area and step-free access throughout."
        tint
      >
        <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {[1, 2, 3, 4].map((n) => (
            <li key={n}>
              <Picture
                name={`gallery-${n}`}
                alt={`Illustration ${n} of the practice`}
                sizes="(min-width: 1024px) 25vw, (min-width: 640px) 50vw, 100vw"
                className="aspect-[3/2] rounded-xl"
              />
            </li>
          ))}
        </ul>
      </Section>
      <Section title="In our community">
        <ul className="grid max-w-3xl gap-3">
          {community.map((c) => (
            <li key={c} className="rounded-lg border bg-card p-4">
              {c}
            </li>
          ))}
        </ul>
        <p className="mt-4 text-sm text-muted-foreground">
          Community programmes on this demonstration site are examples.
        </p>
      </Section>
      <CtaBand />
    </>
  )
}

// --- New patients ---------------------------------------------------------------------------------

const forms = [
  {
    file: 'new-patient-registration.pdf',
    title: 'New patient registration',
    text: 'Your details, emergency contact and insurance.',
  },
  {
    file: 'medical-history.pdf',
    title: 'Medical and dental history',
    text: 'Health, medicines, allergies and dental concerns.',
  },
  {
    file: 'consent-to-treatment.pdf',
    title: 'Consent to examination and treatment',
    text: 'Your agreement to an examination and x-rays.',
  },
  {
    file: 'insurance-information.pdf',
    title: 'Insurance and payment information',
    text: 'Your plan and how you plan to pay.',
  },
]

export function NewPatientsPage() {
  return (
    <>
      <PageHeader
        crumbs={[{ label: 'New patients' }]}
        title="New patients"
        intro="Welcome. Here is what to expect, what to bring, and the forms you can fill in before you arrive."
        seo={{
          description:
            'What to expect at your first visit to Meridian Dental Care, what to bring, and printable new patient forms.',
          path: '/new-patients',
        }}
      />
      <Section title="Your first visit in four steps">
        <ol className="grid gap-6 md:grid-cols-4">
          {[
            'Book a time online or by phone.',
            'Fill in your forms ahead, or arrive 15 minutes early.',
            'Meet your dentist for an examination and x-rays, about an hour.',
            'Leave with a clear plan and a written estimate.',
          ].map((text, i) => (
            <li key={text}>
              <Card className="h-full p-6">
                <span
                  className="flex size-10 items-center justify-center rounded-full bg-accent-strong font-bold text-white"
                  aria-hidden="true"
                >
                  {i + 1}
                </span>
                <p className="mt-4">
                  <span className="sr-only">Step {i + 1}: </span>
                  {text}
                </p>
              </Card>
            </li>
          ))}
        </ol>
      </Section>
      <Section title="What to bring" tint>
        <ul className="grid max-w-3xl list-disc gap-2 pl-6">
          <li>A photo ID</li>
          <li>Your insurance card, if you have one</li>
          <li>A list of the medicines you take</li>
          <li>Earlier dental x-rays, if you have them</li>
          <li>Any questions or worries you would like to talk about</li>
        </ul>
      </Section>
      <Section
        id="forms"
        title="Forms"
        intro="Print and fill in these forms, or fill them in at the front desk. They are sample forms for this demonstration clinic."
      >
        <ul className="grid gap-4 sm:grid-cols-2">
          {forms.map((f) => (
            <li key={f.file}>
              <Card className="flex h-full items-start gap-4 p-5">
                <FileText className="mt-1 size-8 shrink-0 text-accent-strong" aria-hidden="true" />
                <div className="flex-1">
                  <h3 className="font-heading font-bold">{f.title}</h3>
                  <p className="text-sm text-muted-foreground">{f.text}</p>
                  <a
                    href={`/forms/${f.file}`}
                    download
                    className="mt-2 inline-flex items-center gap-1.5 text-sm font-semibold text-accent-strong underline underline-offset-4"
                  >
                    <Download className="size-4" aria-hidden="true" />
                    Download PDF <span className="sr-only">of {f.title}</span>
                  </a>
                </div>
              </Card>
            </li>
          ))}
        </ul>
      </Section>
      <CtaBand />
    </>
  )
}

// --- Insurance and payment ------------------------------------------------------------------------

export function InsurancePage() {
  return (
    <>
      <PageHeader
        crumbs={[{ label: 'Insurance and payment' }]}
        title="Insurance and payment"
        intro="We work with most plans and make payment simple. You always know your share before treatment starts."
        seo={{
          description:
            'Insurance, self pay, payment plans and FSA or HSA accepted at Meridian Dental Care. A written estimate before every treatment.',
          path: '/insurance-and-payment',
        }}
      />
      <Section>
        <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {insuranceCategories.map((c) => (
            <li key={c.title}>
              <Card className="h-full p-6">
                <h2 className="font-heading text-lg font-bold">{c.title}</h2>
                <p className="mt-2 text-sm text-muted-foreground">{c.text}</p>
              </Card>
            </li>
          ))}
        </ul>
      </Section>
      <Section title="How it works" tint>
        <ol className="max-w-3xl list-decimal space-y-2 pl-6">
          <li>Tell us your plan when you book, or bring your card to your visit.</li>
          <li>We check your benefits and estimate what your plan pays and what you pay.</li>
          <li>You receive the estimate in writing before treatment begins.</li>
          <li>
            We file the claim. You pay your share at the visit by card, cash or bank transfer.
          </li>
        </ol>
        <p className="mt-6 text-sm text-muted-foreground">
          Insurers usually pay the practice 2 to 6 weeks after the visit. Estimates are not a
          guarantee of payment: your plan decides what it covers.
        </p>
      </Section>
      <CtaBand />
    </>
  )
}

// --- Pricing --------------------------------------------------------------------------------------

export function PricingPage() {
  const { services } = useCatalog()
  const order = Object.keys(groups) as ServiceGroup[]
  return (
    <>
      <PageHeader
        crumbs={[{ label: 'Pricing' }]}
        title="Pricing"
        intro="Starting prices for our services. The final cost depends on your examination and your insurance."
        seo={{
          description:
            'Starting prices for dental services at Meridian Dental Care: exams, cleanings, fillings, crowns, root canals, whitening, implants and aligners.',
          path: '/pricing',
        }}
      />
      <Section>
        <div className="space-y-10">
          {order.map((key) => (
            <section key={key} aria-labelledby={`price-${key}`}>
              <h2 id={`price-${key}`} className="mb-3 text-2xl">
                {groups[key].title}
              </h2>
              <div className="overflow-x-auto rounded-xl border bg-card shadow-soft">
                <table className="w-full text-sm">
                  <caption className="sr-only">
                    Prices for {groups[key].title.toLowerCase()}
                  </caption>
                  <thead className="bg-secondary text-left">
                    <tr>
                      <th scope="col" className="px-4 py-3">
                        Service
                      </th>
                      <th scope="col" className="px-4 py-3">
                        Time
                      </th>
                      <th scope="col" className="px-4 py-3">
                        Typical range
                      </th>
                      <th scope="col" className="px-4 py-3 text-right">
                        Starting price
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {services
                      .filter((s) => s.group === key)
                      .map((s) => (
                        <tr key={s.code} className="border-t">
                          <th scope="row" className="px-4 py-3 text-left font-medium">
                            <Link to={`/services/${s.slug}`} className="hover:underline">
                              {s.name}
                            </Link>
                          </th>
                          <td className="px-4 py-3">{s.minutes} min</td>
                          <td className="px-4 py-3">
                            {s.range[0] === s.range[1]
                              ? money(s.range[0])
                              : `${money(s.range[0])} to ${money(s.range[1])}`}
                          </td>
                          <td className="px-4 py-3 text-right font-semibold tabular-nums">
                            {money(s.price)}
                          </td>
                        </tr>
                      ))}
                  </tbody>
                </table>
              </div>
            </section>
          ))}
        </div>
        <p className="mt-8 max-w-3xl text-sm text-muted-foreground">
          Prices are for a demonstration clinic and are before insurance. A written estimate is
          always given before treatment. See{' '}
          <Link to="/insurance-and-payment">insurance and payment</Link> for plans and payment
          options.
        </p>
      </Section>
      <CtaBand />
    </>
  )
}

// --- FAQ -------------------------------------------------------------------------------------------

const moreFaqs = [
  {
    q: 'Is there parking?',
    a: 'Yes. There is free parking behind the building with two accessible spaces next to the rear entrance.',
  },
  {
    q: 'Can I bring my child to my appointment?',
    a: 'Yes, but a second adult is welcome to wait with them so you can relax during treatment.',
  },
  {
    q: 'Do you offer sedation?',
    a: 'Yes. Nitrous oxide and oral sedation are available when your dentist advises them.',
  },
  {
    q: 'What if I am late for my appointment?',
    a: 'Call us. If you are more than 15 minutes late we may need to shorten treatment or offer a new time.',
  },
  {
    q: 'How do I pay for treatment?',
    a: 'By card, cash, bank transfer, or insurance. Payment plans are available for larger treatment.',
  },
  {
    q: 'Do you see patients who are not registered?',
    a: 'Yes. You can book as a guest. Creating an account is optional and lets you see your appointments and invoices.',
  },
  {
    q: 'Are my records private?',
    a: 'Yes. We follow our notice of privacy practices and keep sensitive details encrypted.',
  },
  {
    q: 'Can I get my x-rays sent to another dentist?',
    a: 'Yes. Ask the front desk and we will send them securely.',
  },
]
const allFaqs = [...homeFaqs, ...moreFaqs]

export function FaqPage() {
  const [query, setQuery] = React.useState('')
  const needle = query.trim().toLowerCase()
  const shown = allFaqs.filter((f) => !needle || `${f.q} ${f.a}`.toLowerCase().includes(needle))
  return (
    <>
      <PageHeader
        crumbs={[{ label: 'FAQ' }]}
        title="Frequently asked questions"
        intro="Quick answers about visits, costs, emergencies and more."
        seo={{
          description:
            'Answers to common questions about appointments, insurance, emergencies, children and costs at Meridian Dental Care.',
          path: '/faq',
          jsonLd: [faqSchema(allFaqs)],
        }}
      />
      <Section>
        <Field label="Search the questions" className="max-w-md">
          {(c) => (
            <div className="relative">
              <Search
                className="pointer-events-none absolute top-3.5 left-3 size-4 text-muted-foreground"
                aria-hidden="true"
              />
              <Input
                {...c}
                type="search"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                className="pl-9"
                placeholder="For example, parking"
              />
            </div>
          )}
        </Field>
        <p role="status" className="mt-3 text-sm text-muted-foreground">
          {shown.length} {shown.length === 1 ? 'question' : 'questions'} shown
        </p>
        {shown.length === 0 ? (
          <p className="mt-6 rounded-xl border border-dashed p-8 text-center">
            We do not have an answer for that yet. <Link to="/contact">Ask us</Link> and we will
            reply.
          </p>
        ) : (
          <Accordion type="multiple" className="mt-6 max-w-3xl">
            {shown.map((f) => (
              <AccordionItem key={f.q} value={f.q}>
                <AccordionTrigger level={2}>{f.q}</AccordionTrigger>
                <AccordionContent>{f.a}</AccordionContent>
              </AccordionItem>
            ))}
          </Accordion>
        )}
      </Section>
      <CtaBand />
    </>
  )
}

// --- Reviews ---------------------------------------------------------------------------------------

export function ReviewsPage() {
  const reviews = useReviews()
  const [treatment, setTreatment] = React.useState('all')
  const [minimum, setMinimum] = React.useState(0)
  const treatments = [
    ...new Set(reviews.map((r) => r.treatment).filter((t): t is string => Boolean(t))),
  ].sort()
  const shown = reviews.filter(
    (r) => (treatment === 'all' || r.treatment === treatment) && r.rating >= minimum,
  )
  return (
    <>
      <PageHeader
        crumbs={[{ label: 'Reviews' }]}
        title="Patient reviews"
        intro="Reviews on this demonstration site are illustrative and written for the example clinic."
        seo={{
          description: 'What patients say about Meridian Dental Care. Demonstration reviews.',
          path: '/reviews',
        }}
      >
        <div className="mt-6 flex items-center gap-3">
          <Rating value={stats.rating} />
          <span className="text-sm">
            {stats.rating} average from {stats.reviews} demonstration reviews
          </span>
        </div>
      </PageHeader>
      <Section>
        <div className="mb-8 grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
          <Field label="Treatment">
            {(c) => (
              <Select value={treatment} onValueChange={setTreatment}>
                <SelectTrigger {...c}>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All treatments</SelectItem>
                  {treatments.map((t) => (
                    <SelectItem key={t} value={t}>
                      {t}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            )}
          </Field>
          <div role="group" aria-label="Minimum rating" className="flex flex-wrap items-end gap-2">
            {[0, 4, 5].map((n) => (
              <Button
                key={n}
                size="sm"
                variant={minimum === n ? 'primary' : 'secondary'}
                aria-pressed={minimum === n}
                onClick={() => setMinimum(n)}
              >
                {n === 0 ? 'Any rating' : `${n} stars and up`}
              </Button>
            ))}
          </div>
        </div>
        <p role="status" className="mb-4 text-sm text-muted-foreground">
          {shown.length} {shown.length === 1 ? 'review' : 'reviews'} shown
        </p>
        {shown.length === 0 ? (
          <p className="rounded-xl border border-dashed p-8 text-center">
            No reviews match these filters.
          </p>
        ) : (
          <ul className="grid gap-6 md:grid-cols-2 lg:grid-cols-3">
            {shown.map((r) => (
              <li key={r.id}>
                <ReviewCard review={r} />
              </li>
            ))}
          </ul>
        )}
      </Section>
      <CtaBand />
    </>
  )
}
