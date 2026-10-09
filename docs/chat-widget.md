# Chat widget

The assistant's window, on every public page. Code: `frontend/src/chat`. The assistant itself,
and what it answers, is described in [chatbot.md](chatbot.md).

## What a visitor gets

- A round button, bottom right. A red dot shows when the assistant has something the visitor has
  not seen. On the home page, 20 seconds after arriving, a short offer of help appears once per
  visit; it is not shown on other pages or a second time.
- A panel: on a phone a full screen sheet, on larger screens a window in the corner. It is a
  dialog: focus moves into it (to the message box), stays inside while it is open, Escape closes it
  and the focus goes back to the button.
- The greeting, with buttons. Most things can be done by tapping: services and dentists appear as
  cards (with how long a service takes and what it starts at), days and times as picker cards, and
  the booking as a summary card with a "Confirm booking" button. Typing always works too, and the
  keyboard offered matches what is asked for (email, phone, a six digit code).
- The reply appears as it is written. The words are not read out piece by piece; the whole reply is
  announced once it is complete (the conversation is a live region). A typing indicator shows
  before the first words.
- Thumbs up and down under each reply, "Talk to a person" at any time, a link to the full booking
  page, and links from replies that stay inside the site when they point at it.
- **Download transcript** saves the conversation as a text file. **End chat** asks first, then
  deletes the conversation from the server and the browser.

## Where the conversation lives

The id and secret of the conversation are kept in the tab's session storage. Reloading or moving
between pages carries on where it was (the messages are read back from the server); closing the tab
forgets it. If the server no longer knows the conversation, a new one starts. If storage is blocked
the chat still works until the page is closed.

`DELETE /chat/sessions/{id}` (with the conversation's token) ends a conversation: its messages are
deleted, a time held in the middle of booking is released, and the token stops working.

## When something is wrong

The visitor never sees an error code. If the assistant reports it is working in a limited way, or a
request fails, a banner offers the booking form and the phone number, and the reply says what to do
in plain words. Messages sent too fast and a reply still being written get their own short notes.

## Tests

`frontend/src/chat/chat.test.tsx` (opening, restoring, streaming, cards, pickers, summary,
feedback, links, failures, transcript, ending, the offer of help, accessibility) and
`frontend/e2e/chat.spec.ts`: a signed in patient books a visit through the widget with taps only, in
six interactions (the target is fewer than eight), and the chat works from the keyboard.
