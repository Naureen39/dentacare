# Frontend foundation and design system

React 18, Vite, TypeScript (strict), Tailwind CSS v4, TanStack Query. Components are built on
Radix UI primitives (focus handling, keyboard support and ARIA come from there) and styled with
the project's tokens. Every component is shown, with its states, on the `/styleguide` route.

## Running it

```bash
cd frontend
npm run dev                # http://localhost:5173, /styleguide is available
npm test                   # 105 tests: components, auth client, route guards, contrast
npm run lint && npm run typecheck && npm run format:check
npm run audit:styleguide   # production build + Lighthouse accessibility audit
npm run gen:api            # regenerate src/lib/api-types.ts from the backend OpenAPI document
```

The style guide is for the team. It is served in development and in builds made with
`VITE_ENABLE_STYLEGUIDE=true` (the audit script does this). In any other production build the
route and the whole page, including the chart library it pulls in, are absent from the bundle.

## Brand and tokens

All tokens are CSS variables in `src/styles/globals.css` and are exposed to Tailwind as utilities
(`bg-primary`, `text-accent-strong`, `rounded-lg`, `shadow-raised`).

| Role | Token | Value |
|---|---|---|
| Primary (deep navy) | `--primary` | `#0B2545` |
| Accent (clinical teal) | `--accent` | `#13A3A1` |
| Surface tint (soft mint) | `--secondary` | `#E8F6F5` |
| Background (warm white) | `--background` | `#FAFBFC` |
| Success, warning, danger | `--success`, `--warning`, `--danger` | `#1E9E6A`, `#E39B1D`, `#D64545` |

**Contrast.** The brand teal, green, amber and red do not reach 4.5:1 against white (3.1, 3.4,
2.3 and 4.4), so they are used for fills, icons and large display text only. Wherever a colour
carries text, or sits under white text, a stronger variant is used: `--accent-strong` `#0B7371`
(5.7:1), `--success-strong` `#12704A`, `--warning-strong` `#8A5A00`, and `--destructive`
`#B42323` (6.6:1). Form control edges (`--input` `#78879D`, 3.6:1) and the focus ring meet the
3:1 needed for interface parts. `src/styles/contrast.test.ts` reads the CSS and checks every
pair that is used, so a token change that breaks a pair fails the build.

**Type.** Plus Jakarta Sans for headings and Inter for body text, both self hosted through
Fontsource (no request leaves the site). The scale is Tailwind's 12, 14, 16, 18, 20, 24, 30, 36,
48 and 60 px; body line height is 1.5 and headings from 30 px up use 1.15.

**Layout.** `container-page` is 1240 px wide with 16 px (24 px from the tablet width) gutters,
`section-space` gives 56 px of vertical space on phones and 96 px from the tablet width, `grid-12`
is the 12 column grid. Spacing uses Tailwind's 4 px unit in steps of 8 px. Cards use a 12 px
radius, pills 999 px, with layered soft shadows (`shadow-soft`, `shadow-raised`) and hairline
borders.

**Motion.** `FadeUp` rises at most 24 px over 400 ms once, `AnimatedNumber` counts up when it
scrolls into view, cards lift on hover. All of it stops when the visitor has asked for reduced
motion, in both the CSS and the Motion components.

## Components

`src/components/ui`: Button (primary, accent, secondary, ghost, destructive, link, loading), Input,
Textarea, Field (label, hint and error wired to the control), Select, Checkbox, RadioGroup,
Switch, Tabs, Accordion, Dialog, Drawer, Toast, Tooltip, Badge, Avatar, Card (default, elevated,
tinted, outline, interactive), DataTable (sortable, paginated, sticky header, loading and empty
states), Skeleton, EmptyState, Stepper, Breadcrumbs, Pagination, Calendar, DatePicker,
SlotPicker, Rating and RatingInput, StatCard with Sparkline, and Chart.

Things worth knowing when using them:

* **Field** passes `id`, `aria-describedby`, `aria-invalid` and `aria-required` to the control
  through a render function, so any input works and the error is announced when it appears.
* **Calendar** follows the ARIA date grid pattern: one day in the tab order, arrow keys move by
  day and week, Home and End jump to the ends of the week, Page Up and Page Down change month.
  Dates are plain `YYYY-MM-DD` strings in the clinic's calendar (`src/lib/dates.ts`), never
  instants, so "Tuesday the 14th" is the same for every visitor whatever their time zone.
* **SlotPicker** combines the calendar (days without openings are disabled) with a radio group
  of times.
* **DataTable** requires a `caption`, names its scroll region, sets `aria-sort`, and gives each
  pagination its own landmark name.
* **Chart** frames any recharts chart, hides the picture from assistive technology and offers
  the same numbers as a table, visible with "Show data".
* **Toast** is provided once; errors are announced assertively, everything else politely.

## Foundations

* **Errors:** `ErrorBoundary` around the app, a 404 page, a 500 page (the router `errorElement`)
  and a 403 page for a signed in user without the right role.
* **Code splitting:** every page is a lazy route with a skeleton fallback.
* **Forms:** react-hook-form with zod. `src/lib/forms.ts` holds reusable fields and their
  messages, written for patients ("Enter your email address.").
* **Accessibility:** a skip link, focus moves to the content after each navigation, visible focus
  rings, labelled landmarks, text alternatives for charts, ratings and icons.
* **Server state:** TanStack Query. It retries once for network and server errors and never for
  a refusal such as 401 or 404.

## Authentication client

`src/lib/api-client.ts` and `src/lib/auth.tsx`.

* The short lived **access token lives only in memory**, never in local storage or a cookie
  script can write. A reload loses it; the HttpOnly refresh cookie brings a new one.
* On load the app asks `POST /auth/refresh` and then `GET /auth/me`, so a returning visitor is
  signed in without seeing a form. A first time visitor has no session cookie, so no request is
  made.
* Requests send `Authorization: Bearer`. State changing requests also echo the readable
  `csrf_token` cookie in `X-CSRF-Token` (double submit, as the backend requires).
* A **401** triggers one renewal and one repeat of the request, never a loop. Requests that
  expire together **share one renewal**, because the server rotates refresh tokens and two
  parallel renewals would look like a stolen token. If renewal fails the interface returns to
  signed out.
* `RequireAuth` guards routes: anonymous visitors go to `/login` and come back to where they
  were headed; the wrong role gets the 403 page. This only decides what is shown, the server
  checks the role on every request.
* The sign in page handles the password, the verification code for MFA, and enrolment (setup
  key, first code, one time recovery codes) for roles that must use it.

## Tests and the accessibility target

* `src/styles/contrast.test.ts`: every colour pair against WCAG 2.2 AA.
* `src/lib/api-client.test.ts`: token handling, CSRF, single renewal, no loop, expiry.
* `src/app/routes.test.tsx`: public pages, route guards, role checks, hidden style guide.
* `src/components/ui/components.test.tsx`: keyboard behaviour and automated accessibility checks
  (axe) of the components.
* `src/pages/StyleguidePage.test.tsx`: the whole style guide passes axe and the form validation
  messages read well.
* `npm run audit:styleguide`: builds, serves and runs Lighthouse. Result at the time of writing:
  **accessibility 100, best practices 100** (the exit criterion is 95). jsdom cannot compute
  colour contrast, so contrast is covered by the token test and by Lighthouse.

Automated checks find about a third of accessibility problems. The style guide has not been
reviewed with a screen reader, and that is worth doing before the public site is built on it.
