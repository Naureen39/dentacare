import { act, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { axe } from 'vitest-axe'

import { parseEvents } from '@/chat/api'
import { buildTranscript, fromHistory, internalPath, type Msg } from '@/chat/model'
import { tokenStore } from '@/lib/api-client'
import { CROWN, RAMAN, ROUTINE } from '@/test/booking-fixtures'
import { json, mockApi, renderApp, type Handlers } from '@/test/utils'

const SESSION = 'a0000000-0000-4000-8000-000000000001'
const TOKEN = 'secret-token-for-the-chat'
const slow = { timeout: 10_000 }

const reply = (over: Record<string, unknown> = {}) => ({
  message_id: crypto.randomUUID(),
  text: 'Hello.',
  route: 'rule',
  intent: null,
  quick_replies: [],
  links: [],
  input_hint: null,
  picker: null,
  degraded: false,
  flow: null,
  step: null,
  ...over,
})

/** A reply the way the server streams it: a header, the words, then the whole reply. */
const stream = (r: ReturnType<typeof reply>) => {
  const words = r.text.split(' ')
  const events = [
    `event: meta\ndata: ${JSON.stringify({ message_id: r.message_id, route: r.route })}\n\n`,
    ...words.map(
      (w, i) =>
        `event: delta\ndata: ${JSON.stringify({ text: w + (i < words.length - 1 ? ' ' : '') })}\n\n`,
    ),
    `event: done\ndata: ${JSON.stringify(r)}\n\n`,
  ]
  return new Response(events.join(''), {
    status: 200,
    headers: { 'Content-Type': 'text/event-stream' },
  })
}

const menu = [
  { label: 'Book an appointment', kind: 'action', value: 'start_booking' },
  { label: 'Opening hours', kind: 'action', value: 'hours' },
]

function chatApi(
  next: (body: Record<string, unknown>) => ReturnType<typeof reply>,
  extra: Handlers = {},
): Handlers {
  return {
    'POST /chat/sessions': () =>
      json(
        {
          session_id: SESSION,
          session_token: TOKEN,
          greeting: reply({ text: 'Hi, how can I help?', quick_replies: menu }),
        },
        201,
      ),
    [`POST /chat/sessions/${SESSION}/messages`]: (init) =>
      stream(next(JSON.parse(String(init?.body)))),
    [`POST /chat/sessions/${SESSION}/feedback`]: { status: 204 },
    [`DELETE /chat/sessions/${SESSION}`]: { status: 204 },
    'GET /public/services': { status: 200, body: [ROUTINE, CROWN] },
    'GET /public/dentists': { status: 200, body: [RAMAN] },
    ...extra,
  }
}

async function openChat(user: ReturnType<typeof userEvent.setup>) {
  await user.click(await screen.findByRole('button', { name: /Chat with our assistant/ }, slow))
  return screen.findByRole('dialog', { name: 'Meridian Assistant' })
}

beforeEach(() => window.sessionStorage.clear())
afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
  tokenStore.set(null)
})

describe('opening the chat', () => {
  it('starts a conversation, shows the greeting and its buttons, and puts the cursor in the box', async () => {
    const user = userEvent.setup()
    const { calls } = mockApi(chatApi(() => reply()))
    renderApp('/pricing')
    const dialog = await openChat(user)
    expect(await within(dialog).findByText('Hi, how can I help?')).toBeInTheDocument()
    expect(within(dialog).getByRole('button', { name: 'Book an appointment' })).toBeInTheDocument()
    expect(within(dialog).getByRole('textbox', { name: 'Type your message' })).toHaveFocus()
    expect(calls.filter((c) => c.path === '/chat/sessions')).toHaveLength(1)
    expect(JSON.parse(window.sessionStorage.getItem('meridian-chat') ?? '{}')).toEqual({
      id: SESSION,
      token: TOKEN,
    })
  })

  it('picks up an earlier conversation after a reload, and starts again if it has gone', async () => {
    const user = userEvent.setup()
    window.sessionStorage.setItem('meridian-chat', JSON.stringify({ id: SESSION, token: TOKEN }))
    const { calls } = mockApi(
      chatApi(() => reply(), {
        [`GET /chat/sessions/${SESSION}`]: {
          status: 200,
          body: {
            id: SESSION,
            created_at: '2030-05-01T10:00:00Z',
            flow: null,
            step: null,
            messages: [
              {
                id: 'm1',
                role: 'user',
                content: 'what are your hours',
                intent: null,
                route: null,
                quick_replies: [],
                links: [],
                input_hint: null,
                picker: null,
                feedback: null,
                created_at: '2030-05-01T10:00:00Z',
              },
              {
                id: 'm2',
                role: 'assistant',
                content: 'We open at eight.',
                intent: 'hours',
                route: 'rule',
                quick_replies: menu,
                links: [],
                input_hint: null,
                picker: null,
                feedback: 'up',
                created_at: '2030-05-01T10:00:01Z',
              },
            ],
          },
        },
      }),
    )
    renderApp('/pricing')
    const dialog = await openChat(user)
    expect(await within(dialog).findByText('We open at eight.')).toBeInTheDocument()
    expect(within(dialog).getByText('what are your hours')).toBeInTheDocument()
    expect(
      calls.find((c) => c.path === `/chat/sessions/${SESSION}`)?.headers.get('X-Chat-Token'),
    ).toBe(TOKEN)
    expect(calls.some((c) => c.method === 'POST' && c.path === '/chat/sessions')).toBe(false)
    expect(within(dialog).getByRole('button', { name: 'Helpful' })).toHaveAttribute(
      'aria-pressed',
      'true',
    )
  })

  it('begins a new conversation when the old one no longer exists', async () => {
    const user = userEvent.setup()
    window.sessionStorage.setItem('meridian-chat', JSON.stringify({ id: 'gone', token: 'old' }))
    const { calls } = mockApi(
      chatApi(() => reply(), {
        'GET /chat/sessions/gone': { status: 404, body: { code: 'not_found', message: 'x' } },
      }),
    )
    renderApp('/pricing')
    const dialog = await openChat(user)
    expect(await within(dialog).findByText('Hi, how can I help?')).toBeInTheDocument()
    expect(calls.some((c) => c.method === 'POST' && c.path === '/chat/sessions')).toBe(true)
  })

  it('closes with Escape and gives the focus back to the button', async () => {
    const user = userEvent.setup()
    mockApi(chatApi(() => reply()))
    renderApp('/pricing')
    const launcher = await screen.findByRole('button', { name: /Chat with our assistant/ }, slow)
    await user.click(launcher)
    await screen.findByRole('dialog', { name: 'Meridian Assistant' })
    await user.keyboard('{Escape}')
    await waitFor(() =>
      expect(screen.queryByRole('dialog', { name: 'Meridian Assistant' })).not.toBeInTheDocument(),
    )
    expect(launcher).toHaveFocus()
  })

  it('has no detectable accessibility problems when open', async () => {
    const user = userEvent.setup()
    mockApi(chatApi(() => reply()))
    renderApp('/pricing')
    const dialog = await openChat(user)
    await within(dialog).findByText('Hi, how can I help?')
    expect(
      await axe(dialog, { rules: { 'color-contrast': { enabled: false } } }),
    ).toHaveNoViolations()
  })
})

describe('talking to the assistant', () => {
  it('sends a clicked button as a choice and shows the reply that streams back', async () => {
    const user = userEvent.setup()
    const seen: Record<string, unknown>[] = []
    const { calls } = mockApi(
      chatApi((body) => (seen.push(body), reply({ text: 'We are open from eight to six.' }))),
    )
    renderApp('/pricing')
    const dialog = await openChat(user)
    await user.click(await within(dialog).findByRole('button', { name: 'Opening hours' }))
    expect(await within(dialog).findByText('We are open from eight to six.')).toBeInTheDocument()
    expect(seen[0]).toEqual({ choice: { kind: 'action', value: 'hours', label: 'Opening hours' } })
    const sent = calls.find((c) => c.path.endsWith('/messages'))
    expect(sent?.headers.get('Accept')).toBe('text/event-stream')
    expect(sent?.headers.get('X-Chat-Token')).toBe(TOKEN)
    // The visitor's own button text is in the conversation too.
    expect(within(dialog).getAllByText('Opening hours').length).toBeGreaterThan(0)
  })

  it('sends typed text, and asks for the right keyboard when the assistant wants an email address', async () => {
    const user = userEvent.setup()
    const seen: Record<string, unknown>[] = []
    mockApi(
      chatApi((body) => {
        seen.push(body)
        return reply({ text: 'What is your email address?', input_hint: 'email' })
      }),
    )
    renderApp('/pricing')
    const dialog = await openChat(user)
    await user.type(
      await within(dialog).findByRole('textbox', { name: 'Type your message' }),
      'hello there',
    )
    await user.click(within(dialog).getByRole('button', { name: 'Send' }))
    expect(await within(dialog).findByText('What is your email address?')).toBeInTheDocument()
    expect(seen[0]).toEqual({ text: 'hello there' })
    const box = within(dialog).getByLabelText('Type your email address')
    expect(box).toHaveAttribute('type', 'email')
    expect(box).toHaveAttribute('autocomplete', 'email')
  })

  it('offers services and dentists as cards with what the assistant knows about them', async () => {
    const user = userEvent.setup()
    const seen: Record<string, unknown>[] = []
    mockApi(
      chatApi((body) => {
        seen.push(body)
        const kind = (body.choice as { kind: string }).kind
        return kind === 'service'
          ? reply({
              text: 'Which dentist?',
              quick_replies: [{ label: RAMAN.full_name, kind: 'dentist', value: RAMAN.id }],
            })
          : reply({
              text: 'What would you like to book?',
              quick_replies: [
                { label: ROUTINE.name, kind: 'service', value: ROUTINE.id },
                { label: CROWN.name, kind: 'service', value: CROWN.id },
              ],
            })
      }),
    )
    renderApp('/pricing')
    const dialog = await openChat(user)
    await user.click(await within(dialog).findByRole('button', { name: 'Book an appointment' }))
    const list = await within(dialog).findByRole('list', { name: 'Services' })
    expect(await within(list).findByText('45 min, from $120')).toBeInTheDocument()
    await user.click(within(list).getByRole('button', { name: /Porcelain Crown/ }))
    const dentists = await within(dialog).findByRole('list', { name: 'Dentists' })
    expect(await within(dentists).findByText('general')).toBeInTheDocument()
    expect(seen[1]).toEqual({ choice: { kind: 'service', value: CROWN.id, label: CROWN.name } })
  })

  it('shows days and times as picker cards', async () => {
    const user = userEvent.setup()
    mockApi(
      chatApi((body) => {
        const kind = (body.choice as { kind: string }).kind
        return kind === 'date'
          ? reply({
              text: 'Here are the times.',
              picker: 'slot',
              quick_replies: [
                { label: '9:00 AM', kind: 'slot', value: '2030-05-14T13:00:00Z|d' },
                { label: 'Another day', kind: 'action', value: 'change_day' },
              ],
            })
          : reply({
              text: 'Which day?',
              picker: 'date',
              quick_replies: [{ label: 'Tue, May 14 (3 open)', kind: 'date', value: '2030-05-14' }],
            })
      }),
    )
    renderApp('/pricing')
    const dialog = await openChat(user)
    await user.click(await within(dialog).findByRole('button', { name: 'Book an appointment' }))
    const days = await within(dialog).findByRole('group', { name: 'Choose a day' })
    await user.click(within(days).getByRole('button', { name: /May 14/ }))
    const times = await within(dialog).findByRole('group', { name: 'Choose a time' })
    expect(within(times).getByRole('button', { name: '9:00 AM' })).toBeInTheDocument()
    expect(within(dialog).getByRole('button', { name: 'Another day' })).toBeInTheDocument()
  })

  it('shows the booking as a summary card with the button that confirms it', async () => {
    const user = userEvent.setup()
    const seen: Record<string, unknown>[] = []
    mockApi(
      chatApi((body) => {
        seen.push(body)
        return (body.choice as { kind: string }).kind === 'confirm'
          ? reply({
              text: 'Your appointment is booked.',
              links: [{ label: 'Add to calendar', url: '/book/done' }],
            })
          : reply({
              text: 'Routine Exam and Cleaning with Dr. Priya Raman on Tuesday at 9:00 AM.',
              step: 'confirm',
              quick_replies: [
                { label: 'Confirm', kind: 'confirm', value: 'yes' },
                { label: 'Change time', kind: 'action', value: 'change_time' },
              ],
            })
      }),
    )
    renderApp('/pricing')
    const dialog = await openChat(user)
    await user.click(await within(dialog).findByRole('button', { name: 'Book an appointment' }))
    const card = await within(dialog).findByRole('region', { name: 'Booking summary' })
    expect(within(card).getByText(/Routine Exam and Cleaning/)).toBeInTheDocument()
    expect(within(dialog).getByRole('button', { name: 'Change time' })).toBeInTheDocument()
    await user.click(within(card).getByRole('button', { name: 'Confirm booking' }))
    expect(await within(dialog).findByText('Your appointment is booked.')).toBeInTheDocument()
    expect(seen[1]).toEqual({ choice: { kind: 'confirm', value: 'yes', label: 'Confirm' } })
  })

  it('keeps pages of this site inside the app and opens other links in a new tab', async () => {
    const user = userEvent.setup()
    mockApi(
      chatApi(() =>
        reply({
          text: 'Here you go.',
          links: [
            { label: 'Open the booking form', url: 'https://meridian.example/book' },
            { label: 'Our map', url: 'https://maps.example/x' },
          ],
        }),
      ),
    )
    renderApp('/pricing')
    const dialog = await openChat(user)
    await user.click(await within(dialog).findByRole('button', { name: 'Opening hours' }))
    const inside = await within(dialog).findByRole('link', { name: 'Open the booking form' })
    expect(inside).toHaveAttribute('href', '/book')
    const outside = within(dialog).getByRole('link', { name: /Our map/ })
    expect(outside).toHaveAttribute('target', '_blank')
    expect(outside).toHaveAttribute('rel', expect.stringContaining('noreferrer'))
  })

  it('asks for a person from the panel at any time', async () => {
    const user = userEvent.setup()
    const seen: Record<string, unknown>[] = []
    mockApi(chatApi((body) => (seen.push(body), reply({ text: 'I will pass this to our team.' }))))
    renderApp('/pricing')
    const dialog = await openChat(user)
    await user.click(await within(dialog).findByRole('button', { name: 'Talk to a person' }))
    expect(await within(dialog).findByText('I will pass this to our team.')).toBeInTheDocument()
    expect(seen[0]).toEqual({
      choice: { kind: 'action', value: 'handoff', label: 'Talk to a person' },
    })
  })

  it('records a thumbs up or down on a reply', async () => {
    const user = userEvent.setup()
    const { calls } = mockApi(chatApi(() => reply({ text: 'Done.' })))
    renderApp('/pricing')
    const dialog = await openChat(user)
    await user.click(await within(dialog).findByRole('button', { name: 'Not helpful' }))
    await waitFor(() =>
      expect(calls.find((c) => c.path.endsWith('/feedback'))?.body).toMatchObject({
        rating: 'down',
      }),
    )
    expect(within(dialog).getByRole('button', { name: 'Not helpful' })).toHaveAttribute(
      'aria-pressed',
      'true',
    )
    expect(within(dialog).getByRole('button', { name: 'Helpful' })).toBeDisabled()
  })
})

describe('when things go wrong', () => {
  it('shows the other ways to book when the assistant says it is limited', async () => {
    const user = userEvent.setup()
    mockApi(chatApi(() => reply({ text: 'I am having trouble.', degraded: true })))
    renderApp('/pricing')
    const dialog = await openChat(user)
    await user.click(await within(dialog).findByRole('button', { name: 'Opening hours' }))
    const link = await within(dialog).findByRole('link', { name: 'book with the form' })
    expect(link).toHaveAttribute('href', '/book')
    const phone = within(dialog).getAllByRole('link', { name: /\(555\) 010-0199/ })[0]
    expect(phone).toHaveAttribute('href', 'tel:+15550100199')
  })

  it('tells the visitor plainly when the server cannot be reached', async () => {
    const user = userEvent.setup()
    mockApi(
      chatApi(() => reply(), {
        [`POST /chat/sessions/${SESSION}/messages`]: {
          status: 500,
          body: { code: 'server_error', message: 'x' },
        },
      }),
    )
    renderApp('/pricing')
    const dialog = await openChat(user)
    await user.click(await within(dialog).findByRole('button', { name: 'Opening hours' }))
    expect(await within(dialog).findByText(/could not complete that just now/i)).toBeInTheDocument()
    expect(within(dialog).queryByText(/500|server_error/)).not.toBeInTheDocument()
    // The visitor can try again: the box is usable.
    expect(within(dialog).getByRole('textbox', { name: 'Type your message' })).toBeEnabled()
  })

  it('asks the visitor to wait when messages are sent too quickly', async () => {
    const user = userEvent.setup()
    mockApi(
      chatApi(() => reply(), {
        [`POST /chat/sessions/${SESSION}/messages`]: {
          status: 429,
          body: { code: 'rate_limited', message: 'x' },
        },
      }),
    )
    renderApp('/pricing')
    const dialog = await openChat(user)
    await user.click(await within(dialog).findByRole('button', { name: 'Opening hours' }))
    expect(await within(dialog).findByText(/sending messages quickly/i)).toBeInTheDocument()
  })

  it('starts over when the conversation was ended elsewhere', async () => {
    const user = userEvent.setup()
    let first = true
    const { calls } = mockApi(
      chatApi(() => reply(), {
        [`POST /chat/sessions/${SESSION}/messages`]: () => {
          if (first) {
            first = false
            return json({ code: 'not_found', message: 'x' }, 404)
          }
          return stream(reply({ text: 'Back again.' }))
        },
      }),
    )
    renderApp('/pricing')
    const dialog = await openChat(user)
    await user.click(await within(dialog).findByRole('button', { name: 'Opening hours' }))
    await within(dialog).findByText(/could not complete that just now/i)
    expect(window.sessionStorage.getItem('meridian-chat')).toBeNull()
    await user.click(within(dialog).getByRole('button', { name: 'Talk to a person' }))
    await waitFor(() =>
      expect(calls.filter((c) => c.method === 'POST' && c.path === '/chat/sessions').length).toBe(
        2,
      ),
    )
  })
})

describe('keeping and ending the conversation', () => {
  it('lets the visitor download what was said', async () => {
    const user = userEvent.setup()
    let blob: Blob | null = null
    URL.createObjectURL = vi.fn((b: Blob) => ((blob = b), 'blob:x'))
    URL.revokeObjectURL = vi.fn()
    mockApi(chatApi(() => reply({ text: 'We open at eight.' })))
    renderApp('/pricing')
    const dialog = await openChat(user)
    await user.click(await within(dialog).findByRole('button', { name: 'Opening hours' }))
    await within(dialog).findByText('We open at eight.')
    await user.click(within(dialog).getByRole('button', { name: 'Download transcript' }))
    expect(URL.createObjectURL).toHaveBeenCalled()
    const text = await (blob as unknown as Blob).text()
    expect(text).toContain('Meridian Dental Care chat transcript')
    expect(text).toContain('You: Opening hours')
    expect(text).toContain('Assistant: We open at eight.')
  })

  it('deletes the conversation when the visitor ends the chat', async () => {
    const user = userEvent.setup()
    const { calls } = mockApi(chatApi(() => reply()))
    renderApp('/pricing')
    const dialog = await openChat(user)
    await within(dialog).findByText('Hi, how can I help?')
    await user.click(within(dialog).getByRole('button', { name: 'End chat' }))
    expect(within(dialog).getByRole('alert')).toHaveTextContent(/deleted/)
    await user.click(within(dialog).getByRole('button', { name: 'Yes, end chat' }))
    await waitFor(() =>
      expect(calls.find((c) => c.method === 'DELETE')?.headers.get('X-Chat-Token')).toBe(TOKEN),
    )
    await waitFor(() =>
      expect(screen.queryByRole('dialog', { name: 'Meridian Assistant' })).not.toBeInTheDocument(),
    )
    expect(window.sessionStorage.getItem('meridian-chat')).toBeNull()
    // Opening it again begins a new conversation.
    await user.click(screen.getByRole('button', { name: /Chat with our assistant/ }))
    await waitFor(() =>
      expect(calls.filter((c) => c.method === 'POST' && c.path === '/chat/sessions')).toHaveLength(
        2,
      ),
    )
  })
})

describe('the offer to help', () => {
  it('appears once, after twenty seconds, on the home page, with a dot on the button', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    mockApi(chatApi(() => reply()))
    renderApp('/')
    await screen.findByRole('button', { name: /Chat with our assistant/ }, slow)
    expect(screen.queryByText(/Can I help you book/)).not.toBeInTheDocument()
    act(() => void vi.advanceTimersByTime(19_000))
    expect(screen.queryByText(/Can I help you book/)).not.toBeInTheDocument()
    act(() => void vi.advanceTimersByTime(1_500))
    expect(await screen.findByText(/Can I help you book a visit/)).toBeInTheDocument()
    expect(
      screen.getByRole('button', { name: /Chat with our assistant.*new message/ }),
    ).toBeInTheDocument()
    expect(window.sessionStorage.getItem('meridian-chat-greeted')).toBe('1')
  })

  it('does not appear on other pages or a second time in the same visit', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    mockApi(chatApi(() => reply()))
    renderApp('/pricing')
    await screen.findByRole('button', { name: /Chat with our assistant/ }, slow)
    act(() => void vi.advanceTimersByTime(30_000))
    expect(screen.queryByText(/Can I help you book/)).not.toBeInTheDocument()
  })

  it('stays away when it was already shown during this visit', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    window.sessionStorage.setItem('meridian-chat-greeted', '1')
    mockApi(chatApi(() => reply()))
    renderApp('/')
    await screen.findByRole('button', { name: /Chat with our assistant/ }, slow)
    act(() => void vi.advanceTimersByTime(30_000))
    expect(screen.queryByText(/Can I help you book/)).not.toBeInTheDocument()
  })
})

describe('plain functions', () => {
  it('reads streamed events', () => {
    const events = parseEvents(
      'event: delta\ndata: {"text":"Hi "}\n\nevent: done\ndata: {"text":"Hi there"}\n\n',
    )
    expect(events).toEqual([
      { event: 'delta', data: { text: 'Hi ' } },
      { event: 'done', data: { text: 'Hi there' } },
    ])
    expect(parseEvents('event: delta\n\n')).toEqual([])
  })

  it('tells pages of this site from other addresses', () => {
    expect(internalPath('/book?service=SV02')).toBe('/book?service=SV02')
    expect(internalPath('https://meridian.example/faq#hours')).toBe('/faq#hours')
    expect(internalPath('//evil.example/x')).toBeNull()
    expect(internalPath('https://other.example/book')).toBeNull()
    expect(internalPath('not a url')).toBeNull()
  })

  it('writes a transcript with times in the clinic zone', () => {
    const messages = [
      { role: 'user', text: 'Hi', at: '2030-05-14T14:00:00Z' },
      { role: 'assistant', text: 'Hello.', at: '2030-05-14T14:00:05Z' },
    ] as Msg[]
    const text = buildTranscript(messages, new Date('2030-05-14T15:00:00Z'))
    expect(text).toContain('[10:00 AM] You: Hi')
    expect(text).toContain('[10:00 AM] Assistant: Hello.')
    expect(text.startsWith('Meridian Dental Care chat transcript\nSaved May 14, 2030')).toBe(true)
  })

  it('leaves out system messages when restoring a conversation and keeps the step on the last reply', () => {
    const m = (role: string, id: string) => ({
      id,
      role,
      content: id,
      intent: null,
      route: null,
      quick_replies: [],
      links: [],
      input_hint: null,
      picker: null,
      feedback: null,
      created_at: '2030-05-14T14:00:00Z',
    })
    const restored = fromHistory(
      [m('system', 's'), m('user', 'u'), m('assistant', 'a')] as never,
      'confirm',
    )
    expect(restored.map((x) => x.id)).toEqual(['u', 'a'])
    expect(restored.map((x) => x.step)).toEqual([null, 'confirm'])
  })
})
