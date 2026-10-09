# Chat assistant

The assistant answers questions and handles booking, rescheduling and cancellation. Its design
rule is that the database and code do the work and the language model is the last resort: most
turns end before any model is called. The model gateway is described in
[llm-gateway.md](llm-gateway.md), the knowledge base in [knowledge-base.md](knowledge-base.md).

## How a turn is handled

`backend/app/chat/router.py` runs these steps in order and stops at the first that answers.

1. **Safety checks, no model.** Messages over 500 characters get a polite refusal and are stored
   as "message too long". Control and invisible characters are removed. Emergency wording
   (trouble breathing, spreading or severe swelling, bleeding that will not stop, facial
   trauma) returns a fixed message with 911 and the clinic's emergency line, even in the middle
   of a booking. Obvious attempts to override the instructions get a fixed refusal. Requests
   for diagnosis or medicine advice get a fixed disclaimer and an offer to book.
2. **Personal data.** Card numbers and government identifiers are masked before anything is
   stored or sent anywhere. The one time code a visitor types is stored as `[code]`.
3. **Active flow.** If a booking, reschedule, cancel or callback conversation is in progress,
   the state machine takes the message.
4. **Booking requests that name what they want** ("cleaning next Tuesday morning with Dr Raman")
   start a booking directly.
5. **Intent by similarity.** The message is embedded (cached) and compared with the intent
   examples. At 0.80 or more the intent is accepted. Greeting, thanks, opening hours, location
   and prices are answered from templates filled from the database. Booking, rescheduling,
   cancelling and a request for a person start a flow. A question about a *policy* or a *price*
   that uses the word "cancel" or "book" is answered, not acted on.
6. **Knowledge base.** Anything else that reads like a question goes to `search_kb`:
   * top score 0.82 or more: the stored short answer, with a "Read more" link, no model;
   * 0.65 to 0.82: one model call with the two best chunks (at most 350 tokens of context);
   * below 0.65: it says it cannot answer and offers a callback, the contact form or the phone.
7. **Response cache.** A model answer is cached in Redis for 24 hours under the normalized
   question and the ids of the chunks it was built from, so editing a document makes the old
   answer unreachable.

A failure anywhere inside a turn becomes a fixed apology with the clinic phone number. The
visitor never sees an error message, a status code or a provider name.

The plan's "fallback rephrase" model call is not used: below 0.65 the assistant says it cannot
answer instead of asking a model to rephrase. Its token budget is still defined in
`app/chat/budget.py`.

## Booking, rescheduling, cancelling

Every step offers buttons or a picker, so most input is a click; typed answers work too. The
state lives in `chat_sessions.state`.

* **Booking:** service, dentist (skipped when only one offers the service), day, time, then for
  a guest name, email, optional phone, consent to the privacy policy and reminders, a summary,
  and a six digit code sent by email. A signed in patient skips contact, consent and the code.
  Times always come from the availability service. Choosing a time takes a five minute hold; if
  it lapses while the visitor types, it is taken again when the time is still free, otherwise
  the visitor is shown the times that remain.
* **Free text:** a rule based parser reads the service, dentist, date and time of day first.
  Dates are resolved in code against the clinic time zone, never by the model. A model is asked
  only when the rules left three or more words unexplained and found at most one detail, with
  one structured extraction call (at most 350 prompt and 80 completion tokens) per conversation.
* **Reschedule and cancel:** a signed in patient picks one of their upcoming appointments.
  Anyone else must prove they own the mailbox with a code first; the same prompt is shown for
  addresses with and without a patient, so the chat does not reveal who is a patient. The proof
  lasts 20 minutes in that conversation only. Cancelling inside the free window is flagged as a
  late cancellation, and the visitor is told before they confirm.
* **Callback and "talk to a person":** asks for a name and an email or phone, stores a
  `contact_inquiries` row with the last few messages, and shows the clinic phone and hours.
* **Interruptions:** a question asked in the middle of a flow is answered and the step repeats.
  "Never mind" leaves the flow and frees any held time; "start over" restarts it. Three inputs
  in a row that do not fit offer a person.

## Context sent to the model

At most the last four turns, each cut to 50 tokens, plus a rule based summary of at most 80
tokens that is made only once a conversation passes eight turns (no extra model call). Old
turns are dropped first when the prompt would exceed its 700 token budget. The visitor's text
sits in a delimited user message; the system prompt is fixed and never contains visitor text.
Angle brackets in visitor text are neutralized so it cannot close the delimiters. Model output is
validated: at most three sentences and 600 characters, links only to the clinic's own site, only
the clinic's email and phone numbers, and nothing that repeats the system prompt. A rejected
answer is replaced by the stored short answer.

## Endpoints

| Endpoint | Purpose |
|---|---|
| `POST /chat/sessions` | Start a conversation. Returns the id, a secret token (shown once) and the greeting. |
| `POST /chat/sessions/{id}/messages` | Send `text` or a button `choice`. Send `Accept: text/event-stream` to receive the reply as server sent events. |
| `GET /chat/sessions/{id}` | The conversation with the buttons of each reply, for reloading. |
| `POST /chat/sessions/{id}/feedback` | Thumbs up or down on an assistant reply. |
| `GET /admin/chat/metrics` | Zero model share, tokens per conversation, booking funnel, handoffs, feedback, unanswered questions. |

Every call after the first needs the token in `X-Chat-Token`; it is stored only as a hash. A
bearer token is optional and links the conversation to the signed in patient. Messages for one
conversation are handled one at a time. The chat is limited per address by
`RATE_LIMIT_CHAT_PER_MINUTE`.

Streaming sends the finished reply in small pieces (a `meta` event, `delta` events, then `done`
with the full reply and its buttons). The gateway does not stream from the model, so this saves
the interface from handling two formats rather than reducing latency.

## Measured against the targets

The tests count real calls to scripted providers. In the 25 message mixed set used by
`test_most_turns_need_no_model_and_the_dashboard_says_so` at least 70 percent of replies need
no model call; the dashboard reports the same figure from live data. The average cost of a
conversation in tokens is reported per conversation and per completed booking.

## Known limits

* A visitor's contact details are kept in the conversation state until the booking finishes or
  the flow ends, then cleared. Conversations are purged after `chat_retention_days`.
* The intent examples are English. Other languages fall back to the knowledge base lookup and
  usually to "I'm not sure".
* Questions that mix several requests are handled one at a time.
