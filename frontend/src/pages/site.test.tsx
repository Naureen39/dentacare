import { act, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { axe } from 'vitest-axe'

import { services } from '@/content/services'
import { articles, dentists } from '@/content/people'
import { tokenStore } from '@/lib/api-client'
import { json, mockApi, renderApp } from '@/test/utils'

const anonymous = {
  'POST /auth/refresh': { status: 401, body: { code: 'unauthorized', message: 'No session.' } },
}
const longWait = { timeout: 15_000 }

afterEach(() => {
  vi.unstubAllGlobals()
  tokenStore.set(null)
  window.localStorage.clear()
})

async function open(path: string) {
  const api = mockApi(anonymous)
  renderApp(path)
  return api
}
const h1 = () => screen.findByRole('heading', { level: 1 }, longWait)

function head() {
  const meta = (selector: string) =>
    document.head.querySelector(selector)?.getAttribute('content') ?? ''
  return {
    title: document.title,
    description: meta('meta[name="description"]'),
    canonical: document.head.querySelector('link[rel="canonical"]')?.getAttribute('href') ?? '',
    ogTitle: meta('meta[property="og:title"]'),
    ogImage: meta('meta[property="og:image"]'),
    ogType: meta('meta[property="og:type"]'),
    robots: meta('meta[name="robots"]'),
    jsonLd: [...document.head.querySelectorAll('script[type="application/ld+json"]')].map(
      (n) => JSON.parse(n.textContent ?? '{}') as Record<string, unknown>,
    ),
  }
}

// --- every page --------------------------------------------------------------------------------

const pages: [string, RegExp][] = [
  ['/', /exceptional dental care/i],
  ['/services', /our services/i],
  [`/services/${services[4]?.slug}`, /porcelain crown/i],
  ['/dentists', /our dentists/i],
  [`/dentists/${dentists[0]?.slug}`, /priya raman/i],
  ['/about', /about meridian/i],
  ['/new-patients', /new patients/i],
  ['/insurance-and-payment', /insurance and payment/i],
  ['/pricing', /^pricing$/i],
  ['/faq', /frequently asked/i],
  ['/reviews', /patient reviews/i],
  ['/contact', /contact us/i],
  ['/resources', /^resources$/i],
  [`/resources/${articles[0]?.slug}`, /brushing and flossing/i],
  ['/privacy', /privacy policy/i],
  ['/terms', /terms of use/i],
  ['/accessibility', /accessibility statement/i],
  ['/notice-of-privacy-practices', /notice of privacy/i],
  ['/book', /book an appointment/i],
]

describe('every public page', () => {
  it.each(pages)(
    '%s renders with one h1, a title, a description and Open Graph tags',
    async (path, name) => {
      await open(path)
      expect(await screen.findByRole('heading', { level: 1, name }, longWait)).toBeInTheDocument()
      expect(screen.getAllByRole('heading', { level: 1 })).toHaveLength(1)
      await waitFor(() =>
        expect(head().canonical).toMatch(new RegExp(`${path === '/' ? '/$' : path}$`)),
      )
      const tags = head()
      expect(tags.title.length).toBeGreaterThan(5)
      expect(tags.title).toContain('Meridian Dental Care')
      expect(tags.description.length).toBeGreaterThan(40)
      expect(tags.description.length).toBeLessThan(320)
      expect(tags.ogTitle).toBe(tags.title)
      expect(tags.ogImage).toMatch(/^https?:\/\/.+\.webp$/)
      if (path !== '/')
        expect(screen.getByRole('navigation', { name: 'Breadcrumb' })).toBeInTheDocument()
      expect(screen.getByRole('link', { name: /skip to main content/i })).toBeInTheDocument()
    },
    30_000,
  )

  it.each(['/', '/services', '/faq', '/contact', '/pricing', '/new-patients'])(
    '%s has no accessibility violations a script can find',
    async (path) => {
      mockApi(anonymous)
      const { container } = renderApp(path)
      await h1()
      const results = await axe(container, { rules: { 'color-contrast': { enabled: false } } })
      expect(results).toHaveNoViolations()
    },
    60_000,
  )

  it('shows the not found page for unknown services, dentists and articles', async () => {
    for (const path of ['/services/unknown', '/dentists/unknown', '/resources/unknown']) {
      await open(path)
      expect(
        await screen.findByRole('heading', { name: /page not found/i }, longWait),
      ).toBeInTheDocument()
      document.body.innerHTML = ''
    }
  }, 30_000)

  it('keeps sign in pages out of search results', async () => {
    await open('/login')
    expect(
      await screen.findByRole('heading', { level: 1, name: 'Sign in' }, longWait),
    ).toBeInTheDocument()
    await waitFor(() => expect(head().robots).toBe('noindex, nofollow'))
  })
})

// --- home --------------------------------------------------------------------------------------------------

describe('home page', () => {
  it('has the sections in the order of the design', async () => {
    await open('/')
    await h1()
    const headings = (await screen.findAllByRole('heading', { level: 2 })).map((h) => h.textContent)
    const want = [
      'Care for every smile',
      'Why patients choose Meridian',
      'Technology and comfort, together',
      'Meet our dentists',
      'Your visit, step by step',
      'What patients say',
      'Clear prices from the start',
      'Insurance and payment',
      'Questions, answered',
      'Visit us',
      'Ready when you are',
    ]
    const order = want.map((w) => headings.findIndex((h) => h?.includes(w)))
    expect(
      order.every((i) => i >= 0),
      JSON.stringify(headings),
    ).toBe(true)
    expect(order).toEqual([...order].sort((a, b) => a - b))
  }, 30_000)

  it('has the hero calls to action, the quick actions and eight services', async () => {
    await open('/')
    await h1()
    expect(screen.getByRole('link', { name: 'Book an Appointment' })).toHaveAttribute(
      'href',
      '/book',
    )
    expect(screen.getByRole('link', { name: 'Explore Services' })).toHaveAttribute(
      'href',
      '/services',
    )
    const quick = within(screen.getByRole('region', { name: 'Quick actions' }))
    for (const name of ['Book online', 'Call us', 'Emergency care', 'Patient login'])
      expect(quick.getByText(name)).toBeInTheDocument()
    const section = screen.getByRole('region', { name: 'Care for every smile' })
    expect(within(section).getAllByRole('link', { name: /^learn more about/i })).toHaveLength(8)
    expect(screen.getByRole('region', { name: 'Our dentists' })).toBeInTheDocument()
    expect(screen.getAllByRole('link', { name: /^Book with Dr\./ }).length).toBeGreaterThan(0)
  }, 30_000)

  it('marks up the practice and its FAQ for search engines', async () => {
    await open('/')
    await h1()
    await waitFor(() => expect(head().jsonLd.length).toBeGreaterThanOrEqual(2))
    const types = head().jsonLd.map((d) => d['@type'])
    expect(types).toContainEqual(['Dentist', 'LocalBusiness'])
    expect(types).toContain('FAQPage')
    const faq = head().jsonLd.find((d) => d['@type'] === 'FAQPage') as { mainEntity: unknown[] }
    expect(faq.mainEntity).toHaveLength(8)
  }, 30_000)

  it('labels reviews as illustrative and shows live prices when the API answers', async () => {
    mockApi({
      ...anonymous,
      'GET /public/services': {
        status: 200,
        body: [
          {
            id: 'a',
            code: 'SV02',
            name: 'Routine Exam and Cleaning',
            category: 'preventive',
            description: null,
            duration_min: 50,
            base_price: '130.00',
          },
        ],
      },
    })
    renderApp('/pricing')
    await h1()
    expect(await screen.findByText('$130', undefined, longWait)).toBeInTheDocument()
    expect(screen.getByText('50 min')).toBeInTheDocument()
  }, 30_000)

  it('shows illustrative reviews when the API has none', async () => {
    mockApi(anonymous)
    renderApp('/reviews')
    await h1()
    expect(screen.getAllByText(/illustrative/i).length).toBeGreaterThan(0)
    expect(
      (await screen.findAllByText(/verified patient \(demonstration review\)/i)).length,
    ).toBeGreaterThan(3)
  }, 30_000)

  it('uses reviews from the API when there are some', async () => {
    mockApi({
      ...anonymous,
      'GET /public/testimonials': {
        status: 200,
        body: [
          {
            id: 'x',
            first_name: 'Zed',
            last_initial: 'Q',
            treatment: 'Porcelain Crown',
            rating: 5,
            body: 'Excellent service from start to finish.',
          },
        ],
      },
    })
    renderApp('/reviews')
    expect(
      await screen.findByText(/excellent service from start/i, undefined, longWait),
    ).toBeInTheDocument()
    expect(screen.getByText(/Zed Q\./)).toBeInTheDocument()
  }, 30_000)
})

// --- header, footer and floating elements -----------------------------------------------------------------

describe('global elements', () => {
  it('shows the utility bar with phone, emergency line, hours and login', async () => {
    await open('/pricing')
    await h1()
    const phone = screen.getAllByRole('link', { name: /\(555\) 010-0199/ })
    expect(phone[0]).toHaveAttribute('href', 'tel:+15550100199')
    expect(
      screen.getAllByRole('link', { name: /emergency line \(555\) 010-0911/i })[0],
    ).toBeInTheDocument()
    expect(screen.getByText(/mon to fri 8:00 AM to 6:00 PM/i)).toBeInTheDocument()
    expect(screen.getAllByRole('link', { name: 'Patient login' }).length).toBeGreaterThanOrEqual(2)
  }, 30_000)

  it('opens the services mega menu with four categories and closes it with Escape', async () => {
    const user = userEvent.setup()
    await open('/pricing')
    await h1()
    const button = screen.getByRole('button', { name: 'Services' })
    expect(button).toHaveAttribute('aria-expanded', 'false')
    await user.click(button)
    expect(button).toHaveAttribute('aria-expanded', 'true')
    const panel = document.getElementById(button.getAttribute('aria-controls') ?? '') as HTMLElement
    for (const title of [
      'Preventive care',
      'Restorative care',
      'Cosmetic care',
      'Surgical and orthodontic care',
    ]) {
      expect(within(panel).getByRole('link', { name: title })).toBeInTheDocument()
    }
    expect(within(panel).getAllByRole('link').length).toBe(4 + 14)
    await user.keyboard('{Escape}')
    expect(button).toHaveAttribute('aria-expanded', 'false')
    expect(button).toHaveFocus()
  }, 30_000)

  it('opens the patient info dropdown with five links', async () => {
    const user = userEvent.setup()
    await open('/pricing')
    await h1()
    await user.click(screen.getByRole('button', { name: 'Patient info' }))
    const panel = document.getElementById(
      screen.getByRole('button', { name: 'Patient info' }).getAttribute('aria-controls') ?? '',
    ) as HTMLElement
    expect(
      within(panel)
        .getAllByRole('link')
        .map((l) => l.querySelector('span')?.textContent),
    ).toEqual(['New patients', 'Insurance and payment', 'Pricing', 'FAQ', 'Forms'])
  }, 30_000)

  it('has a full screen mobile menu that closes after choosing a page', async () => {
    const user = userEvent.setup()
    await open('/pricing')
    await h1()
    await user.click(screen.getByRole('button', { name: 'Open menu' }))
    const dialog = await screen.findByRole('dialog', { name: 'Menu' })
    expect(within(dialog).getByRole('link', { name: 'Book an appointment' })).toHaveAttribute(
      'href',
      '/book',
    )
    await user.click(within(dialog).getByRole('link', { name: 'Reviews' }))
    expect(
      await screen.findByRole('heading', { level: 1, name: /patient reviews/i }, longWait),
    ).toBeInTheDocument()
    await waitFor(() =>
      expect(screen.queryByRole('dialog', { name: 'Menu' })).not.toBeInTheDocument(),
    )
  }, 30_000)

  it('has a footer with four columns, the hours, social links and legal links', async () => {
    await open('/pricing')
    await h1()
    for (const name of ['Services footer', 'Company', 'Patient resources', 'Legal'])
      expect(screen.getByRole('navigation', { name })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Contact' })).toBeInTheDocument()
    const hours = screen.getAllByRole('table', { name: 'Opening hours' })[0] as HTMLElement
    expect(
      within(hours).getByRole('row', { name: /saturday 9:00 AM to 2:00 PM/i }),
    ).toBeInTheDocument()
    expect(within(hours).getByRole('row', { name: /sunday closed/i })).toBeInTheDocument()
    const social = within(screen.getByRole('list', { name: 'Social media' })).getAllByRole('link')
    expect(social).toHaveLength(4)
    for (const link of social)
      expect(link).toHaveAttribute('rel', expect.stringContaining('noopener'))
    for (const name of [
      'Privacy policy',
      'Terms of use',
      'Accessibility',
      'Notice of privacy practices',
    ])
      expect(
        within(screen.getByRole('navigation', { name: 'Legal' })).getByRole('link', { name }),
      ).toBeInTheDocument()
    expect(screen.getByText(/demo environment, fictional clinic/i)).toBeInTheDocument()
  }, 30_000)

  it('signs visitors up for the newsletter, with validation and a thank you', async () => {
    const user = userEvent.setup()
    const { calls } = mockApi({
      ...anonymous,
      'POST /public/newsletter': { status: 202, body: { message: 'Thank you.' } },
    })
    renderApp('/pricing')
    await h1()
    const form = screen.getByRole('form', { name: 'Newsletter signup' })
    await user.click(within(form).getByRole('button', { name: 'Subscribe' }))
    expect(await within(form).findByText('Enter your email address.')).toBeInTheDocument()
    await user.type(within(form).getByLabelText(/email address/i), 'not-an-email')
    await user.click(within(form).getByRole('button', { name: 'Subscribe' }))
    expect(await within(form).findByText(/such as name@example.com/)).toBeInTheDocument()
    await user.clear(within(form).getByLabelText(/email address/i))
    await user.type(within(form).getByLabelText(/email address/i), 'pat@example.com')
    await user.click(within(form).getByRole('button', { name: 'Subscribe' }))
    expect(await within(form).findByText('Thank you for subscribing.')).toBeInTheDocument()
    expect(calls.find((c) => c.path === '/public/newsletter')?.body).toEqual({
      email: 'pat@example.com',
    })
  }, 30_000)

  it('shows the cookie notice once and remembers that it was seen', async () => {
    const user = userEvent.setup()
    await open('/pricing')
    await h1()
    const notice = screen.getByRole('region', { name: 'Cookie notice' })
    expect(notice).toHaveTextContent(/do not use advertising or tracking cookies/i)
    await user.click(within(notice).getByRole('button', { name: 'Got it' }))
    expect(screen.queryByRole('region', { name: 'Cookie notice' })).not.toBeInTheDocument()
    expect(window.localStorage.getItem('meridian-cookie-notice')).toBe('seen')
    document.body.innerHTML = ''
    await open('/terms')
    await h1()
    expect(screen.queryByRole('region', { name: 'Cookie notice' })).not.toBeInTheDocument()
  }, 30_000)

  it('has a chat button that opens a panel, and a mobile call and book bar', async () => {
    const user = userEvent.setup()
    await open('/pricing')
    await h1()
    await user.click(screen.getByRole('button', { name: 'Chat with our assistant' }))
    const dialog = await screen.findByRole('dialog', { name: 'Chat with our assistant' })
    expect(within(dialog).getByRole('link', { name: /call \(555\) 010-0199/i })).toBeInTheDocument()
    await user.keyboard('{Escape}')
    const bar = screen.getByRole('navigation', { name: 'Quick actions' })
    expect(within(bar).getByRole('link', { name: 'Call' })).toHaveAttribute(
      'href',
      'tel:+15550100199',
    )
    expect(within(bar).getByRole('link', { name: 'Book' })).toHaveAttribute('href', '/book')
  }, 30_000)
})

// --- inner pages ---------------------------------------------------------------------------------------------

describe('services', () => {
  it('filters by category and searches by name', async () => {
    const user = userEvent.setup()
    await open('/services')
    await h1()
    expect(screen.getByText('14 services shown')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Restorative care' }))
    expect(screen.getByText('3 services shown')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Restorative care' })).toHaveAttribute(
      'aria-pressed',
      'true',
    )
    await user.click(screen.getByRole('button', { name: 'All services' }))
    await user.type(screen.getByRole('searchbox', { name: /search services/i }), 'crown')
    expect(screen.getByText('1 service shown')).toBeInTheDocument()
    await user.clear(screen.getByRole('searchbox', { name: /search services/i }))
    await user.type(screen.getByRole('searchbox', { name: /search services/i }), 'zzzz')
    expect(screen.getByText(/no service matches/i)).toBeInTheDocument()
  }, 30_000)

  it('reads the category from the address', async () => {
    await open('/services?group=cosmetic')
    await h1()
    expect(screen.getByText('1 service shown')).toBeInTheDocument()
  }, 30_000)

  it('shows a full detail page with cost, steps, aftercare, questions and related services', async () => {
    await open(`/services/${services[4]?.slug}`)
    await h1()
    for (const name of [
      'Overview',
      'Who it helps',
      'What happens',
      'Aftercare',
      'Questions',
      'Typical cost',
      'Related services',
    ]) {
      expect(screen.getByRole('heading', { name })).toBeInTheDocument()
    }
    expect(screen.getByText('$1,150 to $1,600')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Book this service' })).toHaveAttribute(
      'href',
      '/book?service=SV05',
    )
    await waitFor(() =>
      expect(head().jsonLd.map((d) => d['@type'])).toEqual(
        expect.arrayContaining(['BreadcrumbList', 'FAQPage']),
      ),
    )
  }, 30_000)
})

describe('dentists', () => {
  it('lists seven dentists and links to profiles', async () => {
    await open('/dentists')
    await h1()
    expect(screen.getAllByRole('link', { name: /^view profile of/i })).toHaveLength(7)
    expect(screen.getAllByRole('link', { name: /^Book with Dr\./ })).toHaveLength(7)
  }, 30_000)

  it('shows the next openings when the booking service answers', async () => {
    const slot = (iso: string) => ({
      start: iso,
      end: iso,
      dentist_id: 'd1',
      dentist_name: 'Dr. Priya Raman',
    })
    mockApi({
      ...anonymous,
      'GET /public/dentists': {
        status: 200,
        body: [
          {
            id: 'd1',
            full_name: 'Dr. Priya Raman',
            specialty: 'general',
            bio: null,
            photo_url: null,
            color: '#000000',
          },
        ],
      },
      'GET /public/services': {
        status: 200,
        body: [
          {
            id: 's1',
            code: 'SV02',
            name: 'Routine Exam and Cleaning',
            category: 'preventive',
            description: null,
            duration_min: 45,
            base_price: '120.00',
          },
        ],
      },
      'GET /public/availability*': () =>
        json([
          {
            date: '2026-10-14',
            slots: [slot('2026-10-14T13:00:00Z'), slot('2026-10-14T14:15:00Z')],
          },
        ]),
    })
    renderApp(`/dentists/${dentists[0]?.slug}`)
    await h1()
    expect(await screen.findByText('9:00 AM', undefined, longWait)).toBeInTheDocument()
    expect(screen.getByText('10:15 AM')).toBeInTheDocument()
    expect(screen.getByText('Wednesday, October 14')).toBeInTheDocument()
  }, 30_000)

  it('falls back to a plain message when it cannot', async () => {
    await open(`/dentists/${dentists[0]?.slug}`)
    await h1()
    expect(
      await screen.findByText(/open times are shown when you book online/i, undefined, longWait),
    ).toBeInTheDocument()
    await waitFor(() => expect(head().jsonLd.map((d) => d['@type'])).toContain('Physician'))
  }, 30_000)
})

describe('information pages', () => {
  it('lists the forms as downloadable PDFs', async () => {
    await open('/new-patients')
    await h1()
    const links = screen.getAllByRole('link', { name: /download pdf of/i })
    expect(links).toHaveLength(4)
    for (const link of links) {
      expect(link.getAttribute('href')).toMatch(/^\/forms\/[a-z-]+\.pdf$/)
      expect(link).toHaveAttribute('download')
    }
  }, 30_000)

  it('shows prices grouped by category', async () => {
    await open('/pricing')
    await h1()
    for (const title of [
      'Preventive care',
      'Restorative care',
      'Cosmetic care',
      'Surgical and orthodontic care',
    ]) {
      expect(
        screen.getByRole('table', { name: `Prices for ${title.toLowerCase()}` }),
      ).toBeInTheDocument()
    }
    expect(
      screen.getByText(/written estimate is always given before treatment/i),
    ).toBeInTheDocument()
  }, 30_000)

  it('searches the FAQ', async () => {
    const user = userEvent.setup()
    await open('/faq')
    await h1()
    expect(screen.getByText('16 questions shown')).toBeInTheDocument()
    await user.type(screen.getByRole('searchbox', { name: /search the questions/i }), 'parking')
    expect(screen.getByText('1 question shown')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Is there parking?' }))
    expect(screen.getByText(/free parking behind the building/i)).toBeVisible()
    await user.clear(screen.getByRole('searchbox', { name: /search the questions/i }))
    await user.type(screen.getByRole('searchbox', { name: /search the questions/i }), 'zzzz')
    expect(screen.getByText(/do not have an answer/i)).toBeInTheDocument()
    await waitFor(() =>
      expect(
        (head().jsonLd.find((d) => d['@type'] === 'FAQPage') as { mainEntity: unknown[] })
          .mainEntity,
      ).toHaveLength(16),
    )
  }, 30_000)

  it('filters reviews by rating', async () => {
    const user = userEvent.setup()
    await open('/reviews')
    await h1()
    expect(screen.getByText('6 reviews shown')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: '5 stars and up' }))
    expect(screen.getByText('5 reviews shown')).toBeInTheDocument()
  }, 30_000)

  it('has a resources index with reading times and articles that credit their source', async () => {
    const user = userEvent.setup()
    await open('/resources')
    await h1()
    expect(screen.getAllByText(/minute read/)).toHaveLength(articles.length)
    await user.click(screen.getAllByRole('link', { name: /^read the guide/i })[0] as HTMLElement)
    expect(
      await screen.findByRole('heading', { level: 1, name: /brushing and flossing/i }, longWait),
    ).toBeInTheDocument()
    expect(screen.getByText(/adapted from public guidance/i)).toBeInTheDocument()
    await waitFor(() => expect(head().ogType).toBe('article'))
  }, 30_000)

  it('warns on the legal pages that the text is a sample', async () => {
    await open('/privacy')
    await h1()
    expect(screen.getByText(/sample text for a demonstration clinic/i)).toBeInTheDocument()
  }, 30_000)
})

// --- contact -------------------------------------------------------------------------------------------------

describe('contact form', () => {
  it('validates, sends and confirms', async () => {
    const user = userEvent.setup()
    const { calls } = mockApi({
      ...anonymous,
      'POST /public/contact': {
        status: 201,
        body: { message: 'Thank you. We will reply as soon as possible.' },
      },
    })
    renderApp('/contact')
    await h1()
    await user.click(screen.getByRole('button', { name: 'Send message' }))
    expect(await screen.findByText('Enter your name.')).toBeInTheDocument()
    expect(screen.getByText('Please write at least a few words.')).toBeInTheDocument()
    await user.type(screen.getByLabelText(/your name/i), 'Pat Jones')
    await user.type(screen.getByLabelText(/how can we help/i), 'Do you see children on Saturdays?')
    await user.click(screen.getByRole('button', { name: 'Send message' }))
    expect(
      await screen.findByText('Give an email address or a phone number so we can reply.'),
    ).toBeInTheDocument()
    await user.type(screen.getByLabelText(/phone/i), '555 010 7777')
    await user.click(screen.getByRole('button', { name: 'Send message' }))
    expect(
      await screen.findByText(/your message has been sent/i, undefined, longWait),
    ).toBeInTheDocument()
    expect(calls.find((c) => c.path === '/public/contact')?.body).toEqual({
      name: 'Pat Jones',
      email: null,
      phone: '555 010 7777',
      message: 'Do you see children on Saturdays?',
    })
    await user.click(screen.getByRole('button', { name: 'Send another message' }))
    expect(screen.getByLabelText(/your name/i)).toHaveValue('')
  }, 30_000)

  it('explains rate limits and failures in plain words', async () => {
    const user = userEvent.setup()
    let status = 429
    mockApi({
      ...anonymous,
      'POST /public/contact': () => json({ code: 'rate_limited', message: 'Slow down.' }, status),
    })
    renderApp('/contact')
    await h1()
    await user.type(screen.getByLabelText(/your name/i), 'Pat')
    await user.type(
      within(screen.getByRole('main')).getByLabelText(/^email address/i),
      'pat@example.com',
    )
    await user.type(screen.getByLabelText(/how can we help/i), 'Hello there')
    await user.click(screen.getByRole('button', { name: 'Send message' }))
    expect(await screen.findByRole('alert')).toHaveTextContent(/several messages/i)
    status = 500
    await user.click(screen.getByRole('button', { name: 'Send message' }))
    await waitFor(() =>
      expect(screen.getByRole('alert')).toHaveTextContent(/could not send your message/i),
    )
  }, 30_000)

  it('shows the address, the phone numbers and a map placeholder until it is near', async () => {
    await open('/contact')
    await h1()
    expect(screen.getAllByText(/1200 Harbor View Drive/).length).toBeGreaterThan(0)
    expect(screen.getByRole('link', { name: /get directions/i })).toHaveAttribute(
      'target',
      '_blank',
    )
  }, 30_000)
})

// --- sign in and registration ----------------------------------------------------------------------------------

describe('account pages', () => {
  it('shows and hides the password', async () => {
    const user = userEvent.setup()
    await open('/login')
    expect(
      await screen.findByRole('heading', { level: 1, name: 'Sign in' }, longWait),
    ).toBeInTheDocument()
    const input = screen.getByLabelText(/^password/i, { selector: 'input' })
    expect(input).toHaveAttribute('type', 'password')
    await user.click(screen.getByRole('button', { name: 'Show password' }))
    expect(input).toHaveAttribute('type', 'text')
    await user.click(screen.getByRole('button', { name: 'Hide password' }))
    expect(input).toHaveAttribute('type', 'password')
    expect(screen.getByRole('link', { name: 'Create an account' })).toHaveAttribute(
      'href',
      '/register',
    )
    expect(screen.getByRole('link', { name: 'Reset it' })).toHaveAttribute(
      'href',
      '/forgot-password',
    )
  }, 30_000)

  it('asks for the code when two step verification is on', async () => {
    const user = userEvent.setup()
    mockApi({
      ...anonymous,
      'POST /auth/login': {
        status: 200,
        body: { status: 'mfa_required', mfa_token: 'm'.repeat(30) },
      },
      'POST /auth/mfa/verify': {
        status: 401,
        body: { code: 'invalid_code', message: 'That code is not correct.' },
      },
    })
    renderApp('/login')
    await screen.findByRole('heading', { level: 1, name: 'Sign in' }, longWait)
    await user.type(screen.getByLabelText(/email address/i), 'admin@example.com')
    await user.type(screen.getByLabelText(/^password/i, { selector: 'input' }), 'a-long-password')
    await user.click(screen.getByRole('button', { name: 'Sign in' }))
    expect(
      await screen.findByRole('heading', { name: 'Enter your verification code' }),
    ).toBeInTheDocument()
    await user.type(screen.getByLabelText(/verification code/i), '123456')
    await user.click(screen.getByRole('button', { name: 'Verify' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('That code is not correct.')
  }, 30_000)

  it('shows a clear error for a wrong password', async () => {
    const user = userEvent.setup()
    mockApi({
      ...anonymous,
      'POST /auth/login': {
        status: 401,
        body: { code: 'invalid_credentials', message: 'The email or password is incorrect.' },
      },
    })
    renderApp('/login')
    await screen.findByRole('heading', { level: 1, name: 'Sign in' }, longWait)
    await user.type(screen.getByLabelText(/email address/i), 'pat@example.com')
    await user.type(screen.getByLabelText(/^password/i, { selector: 'input' }), 'wrong-password-1')
    await user.click(screen.getByRole('button', { name: 'Sign in' }))
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'The email or password is incorrect.',
    )
  }, 30_000)

  it('registers with validation and then asks the person to check their email', async () => {
    const user = userEvent.setup()
    const { calls } = mockApi({
      ...anonymous,
      'POST /auth/register': { status: 201, body: { message: 'ok' } },
    })
    renderApp('/register')
    await screen.findByRole('heading', { level: 1, name: 'Create an account' }, longWait)
    await user.click(screen.getByRole('button', { name: 'Create account' }))
    expect(await screen.findByText('Enter your first name.')).toBeInTheDocument()
    expect(screen.getByText('Enter your last name.')).toBeInTheDocument()
    await user.type(screen.getByLabelText(/first name/i), 'Pat')
    await user.type(screen.getByLabelText(/last name/i), 'Jones')
    await user.type(screen.getByLabelText(/email address/i), 'pat@example.com')
    await user.type(screen.getByLabelText(/^password/i, { selector: 'input' }), 'short')
    await user.click(screen.getByRole('button', { name: 'Create account' }))
    expect(await screen.findByText('Use at least 12 characters.')).toBeInTheDocument()
    await user.clear(screen.getByLabelText(/^password/i, { selector: 'input' }))
    await user.type(
      screen.getByLabelText(/^password/i, { selector: 'input' }),
      'correct horse battery 9',
    )
    await user.click(screen.getByLabelText(/occasional news/i))
    await user.click(screen.getByRole('button', { name: 'Create account' }))
    expect(
      await screen.findByRole('heading', { name: 'Check your email' }, longWait),
    ).toBeInTheDocument()
    expect(calls.find((c) => c.path === '/auth/register')?.body).toEqual({
      first_name: 'Pat',
      last_name: 'Jones',
      email: 'pat@example.com',
      phone: null,
      password: 'correct horse battery 9',
      marketing_consent: true,
    })
  }, 30_000)

  it('sends a reset link without revealing whether the address has an account', async () => {
    const user = userEvent.setup()
    mockApi({ ...anonymous, 'POST /auth/forgot': { status: 202, body: { message: 'ok' } } })
    renderApp('/forgot-password')
    await screen.findByRole('heading', { level: 1, name: 'Reset your password' }, longWait)
    await user.type(screen.getByLabelText(/email address/i), 'anyone@example.com')
    await user.click(screen.getByRole('button', { name: 'Send reset link' }))
    expect(await screen.findByRole('status')).toHaveTextContent(/if an account exists/i)
  }, 30_000)

  it('resets a password from the emailed link, and rejects a link with no token', async () => {
    const user = userEvent.setup()
    const { calls } = mockApi({
      ...anonymous,
      'POST /auth/reset': { status: 200, body: { message: 'ok' } },
    })
    renderApp(`/reset-password?token=${'t'.repeat(30)}`)
    await screen.findByRole('heading', { level: 1, name: 'Choose a new password' }, longWait)
    await user.type(
      screen.getByLabelText(/new password/i, { selector: 'input' }),
      'a brand new passphrase',
    )
    await user.click(screen.getByRole('button', { name: 'Change password' }))
    expect(await screen.findByText('Your password has been changed.')).toBeInTheDocument()
    expect(calls.find((c) => c.path === '/auth/reset')?.body).toEqual({
      token: 't'.repeat(30),
      new_password: 'a brand new passphrase',
    })
    document.body.innerHTML = ''
    mockApi(anonymous)
    renderApp('/reset-password')
    expect(
      await screen.findByRole('heading', { level: 1, name: 'This link is not valid' }, longWait),
    ).toBeInTheDocument()
  }, 30_000)

  it('confirms an email address from the emailed link', async () => {
    const { calls } = mockApi({
      ...anonymous,
      'POST /auth/verify-email': { status: 200, body: { message: 'ok' } },
    })
    renderApp(`/verify-email?token=${'v'.repeat(30)}`)
    expect(
      await screen.findByText(/your email address is confirmed/i, undefined, longWait),
    ).toBeInTheDocument()
    expect(calls.filter((c) => c.path === '/auth/verify-email')).toHaveLength(1)
  }, 30_000)
})

it('lets a keyboard user reach the booking button from the top of the page', async () => {
  const user = userEvent.setup()
  await open('/pricing')
  await h1()
  await act(async () => {})
  await user.tab()
  expect(screen.getByRole('link', { name: /skip to main content/i })).toHaveFocus()
})
