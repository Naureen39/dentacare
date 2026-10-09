import { Clock } from 'lucide-react'
import { Link, useParams } from 'react-router-dom'

import { Picture } from '@/components/site/Picture'
import { CtaBand, PageHeader, Section } from '@/components/site/parts'
import { Seo } from '@/components/site/Seo'
import { Card } from '@/components/ui/display'
import { Breadcrumbs } from '@/components/ui/navigation'
import { articleBySlug, articles } from '@/content/people'
import { clinic } from '@/content/site'
import { articleSchema, breadcrumbSchema } from '@/lib/schema'
import { NotFoundPage } from '@/pages/NotFoundPage'

const date = (iso: string) =>
  new Date(`${iso}T00:00:00`).toLocaleDateString('en-US', {
    year: 'numeric',
    month: 'long',
    day: 'numeric',
  })

export function ResourcesPage() {
  return (
    <>
      <PageHeader
        crumbs={[{ label: 'Resources' }]}
        title="Resources"
        intro="Short, plain guides to looking after your teeth, adapted from public health guidance."
        seo={{
          description:
            'Short guides to brushing, children’s first visits, dental emergencies and gum disease from Meridian Dental Care.',
          path: '/resources',
          image: 'article-1',
        }}
      />
      <Section>
        <ul className="grid gap-6 md:grid-cols-2">
          {articles.map((a) => (
            <li key={a.slug}>
              <Card variant="interactive" className="flex h-full flex-col overflow-hidden">
                <Picture
                  name={a.image}
                  alt=""
                  sizes="(min-width: 768px) 50vw, 100vw"
                  className="aspect-video"
                />
                <div className="flex flex-1 flex-col gap-2 p-6">
                  <p className="flex items-center gap-1.5 text-sm text-muted-foreground">
                    <Clock className="size-4" aria-hidden="true" />
                    {a.minutes} minute read
                  </p>
                  <h2 className="font-heading text-xl font-bold">{a.title}</h2>
                  <p className="flex-1 text-muted-foreground">{a.summary}</p>
                  <Link
                    to={`/resources/${a.slug}`}
                    className="font-semibold text-accent-strong underline underline-offset-4"
                  >
                    Read the guide<span className="sr-only">: {a.title}</span>
                  </Link>
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

export function ArticlePage() {
  const { slug = '' } = useParams()
  const article = articleBySlug(slug)
  if (!article) return <NotFoundPage />
  const trail = [
    { label: 'Home', to: '/' },
    { label: 'Resources', to: '/resources' },
    { label: article.title },
  ]
  return (
    <>
      <Seo
        title={article.title}
        description={article.summary}
        path={`/resources/${article.slug}`}
        image={article.image}
        type="article"
        jsonLd={[breadcrumbSchema(trail), articleSchema(article)]}
      />
      <article>
        <div className="bg-secondary">
          <div className="container-page py-10 md:py-14">
            <Breadcrumbs items={trail} />
            <h1 className="mt-4 max-w-3xl text-3xl md:text-5xl">{article.title}</h1>
            <p className="mt-4 text-muted-foreground">
              {article.minutes} minute read &middot; {date(article.published)}
            </p>
          </div>
        </div>
        <div className="container-page grid gap-8 py-10 md:py-14">
          <Picture
            name={article.image}
            alt=""
            sizes="(min-width: 1240px) 1100px, 100vw"
            priority
            className="aspect-video max-w-4xl rounded-xl"
          />
          <div className="max-w-3xl space-y-5 text-lg leading-relaxed">
            <p className="text-xl font-medium">{article.summary}</p>
            {article.body.map((block, i) => (
              <section key={i}>
                {block.heading && <h2 className="mb-2 text-2xl">{block.heading}</h2>}
                <p>{block.text}</p>
              </section>
            ))}
            {article.source && (
              <p className="border-t pt-4 text-sm text-muted-foreground">
                {article.source} This guide is general information, not a diagnosis. Please see a
                dentist for advice about your own mouth.
              </p>
            )}
          </div>
        </div>
      </article>
      <CtaBand />
    </>
  )
}

// --- Legal pages --------------------------------------------------------------------------------

interface LegalBlock {
  heading: string
  text: string[]
}

function LegalPage({
  title,
  path,
  intro,
  blocks,
}: {
  title: string
  path: string
  intro: string
  blocks: LegalBlock[]
}) {
  return (
    <>
      <PageHeader
        crumbs={[{ label: title }]}
        title={title}
        intro={intro}
        seo={{ description: `${title} of ${clinic.name}. ${intro}`, path }}
      />
      <Section>
        <div className="max-w-3xl space-y-8">
          <p className="rounded-lg border border-warning bg-warning-soft p-4 text-sm text-warning-strong">
            This is sample text for a demonstration clinic. A real practice must have its own policy
            reviewed by a qualified professional.
          </p>
          {blocks.map((b) => (
            <section key={b.heading} aria-labelledby={b.heading.replace(/\W+/g, '-')}>
              <h2 id={b.heading.replace(/\W+/g, '-')} className="text-2xl">
                {b.heading}
              </h2>
              {b.text.map((t) => (
                <p key={t} className="mt-3">
                  {t}
                </p>
              ))}
            </section>
          ))}
          <p className="text-sm text-muted-foreground">Last updated: 1 October 2026.</p>
        </div>
      </Section>
    </>
  )
}

export const PrivacyPage = () => (
  <LegalPage
    title="Privacy policy"
    path="/privacy"
    intro="How this website collects, uses and protects information."
    blocks={[
      {
        heading: 'What we collect',
        text: [
          'When you book, register or write to us we collect the details you give: name, contact details, date of birth and insurance information where needed for care.',
          'The website itself uses only the cookies it needs to keep you signed in. It does not use advertising or tracking cookies.',
        ],
      },
      {
        heading: 'How we use it',
        text: [
          'We use your information to provide and bill for care, to send appointment confirmations and reminders, and to answer your messages. With your agreement we send the newsletter; you can stop it at any time.',
        ],
      },
      {
        heading: 'How we protect it',
        text: [
          'Sensitive details such as date of birth and phone number are encrypted in our records. Access is limited by role and recorded. We keep chat conversations for a limited time and then delete them.',
        ],
      },
      {
        heading: 'Your choices',
        text: [
          'You may ask to see, correct or delete your information, subject to the records we must keep by law. Contact the front desk to make a request.',
        ],
      },
    ]}
  />
)
export const TermsPage = () => (
  <LegalPage
    title="Terms of use"
    path="/terms"
    intro="The terms for using this website."
    blocks={[
      {
        heading: 'General information only',
        text: [
          'The content of this site is general information. It is not a diagnosis or medical advice, and it does not replace an examination by a dentist.',
        ],
      },
      {
        heading: 'Appointments',
        text: [
          'Appointments can be changed or cancelled free of charge up to 24 hours before the visit. Later changes may be recorded as a late cancellation.',
        ],
      },
      {
        heading: 'Accounts',
        text: [
          'Keep your sign in details private. Tell us at once if you think someone else has used your account.',
        ],
      },
      {
        heading: 'Emergencies',
        text: [
          'This website is not for emergencies. For trouble breathing, spreading swelling or bleeding that will not stop, call 911.',
        ],
      },
    ]}
  />
)
export const AccessibilityPage = () => (
  <LegalPage
    title="Accessibility statement"
    path="/accessibility"
    intro="Our aim is a site that everyone can use."
    blocks={[
      {
        heading: 'Our commitment',
        text: [
          'We design this site to meet the Web Content Accessibility Guidelines (WCAG) 2.2 level AA. It works with a keyboard, with screen readers, with zoom, and with reduced motion settings.',
        ],
      },
      {
        heading: 'What we have done',
        text: [
          'Text and controls meet colour contrast requirements, every image has a text alternative or is marked as decoration, forms have labels and clear messages, and each page has a skip link and a logical heading order.',
        ],
      },
      {
        heading: 'Known limits',
        text: [
          'The map is a visual aid; the address and directions are given in text. If you find something hard to use, please tell us and we will help directly and fix it.',
        ],
      },
      {
        heading: 'Visiting us',
        text: [
          'The practice has step-free access, accessible parking next to the rear entrance and an accessible restroom. Tell us in advance if you need other support.',
        ],
      },
    ]}
  />
)
export const NoticePage = () => (
  <LegalPage
    title="Notice of privacy practices"
    path="/notice-of-privacy-practices"
    intro="How your health information may be used and shared, and your rights."
    blocks={[
      {
        heading: 'How we may use and share your health information',
        text: [
          'We use your information for treatment, payment and the running of the practice. We share it with other care providers and insurers only as needed for those purposes, or when the law requires it.',
        ],
      },
      {
        heading: 'Your rights',
        text: [
          'You may ask to see and receive a copy of your record, to correct it, to know who it was shared with, to ask us to limit its use, and to ask that we contact you in a particular way.',
        ],
      },
      {
        heading: 'Our duties',
        text: [
          'We are required to keep your information private, to tell you about this notice, and to tell you if there is a breach affecting your information.',
        ],
      },
      {
        heading: 'Questions or complaints',
        text: [
          `Contact the privacy officer at ${clinic.email} or ${clinic.phone}. You will not be treated differently for making a complaint.`,
        ],
      },
    ]}
  />
)
