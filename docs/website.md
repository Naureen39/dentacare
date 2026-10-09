# Public website

The public site of Meridian Dental Care: home page, services, dentists, patient information,
reviews, contact, resources, legal pages and sign in. Code is in `frontend/src`.

## Content and live data

Text lives in `src/content/` (`site.ts` for the clinic, `services.ts`, `people.ts`). The site
reads fine without the API. When the API answers, `src/lib/public-api.ts` overlays live service
prices and approved reviews on the same pages. The services in `services.ts` match the 14 in the
database seed, and `content.test.ts` checks that they stay in step.

The reviews, social links and the statements about the practice are demonstration content and
are labelled as such on the page.

## Rendering

`npm run build` makes the client bundle, then a server bundle, then `scripts/prerender.mjs`
renders every public address (the list comes from `vite-plugins/seo.ts`) into
`dist/<path>/index.html`. A visitor sees the finished page before any script runs; the
application script is started from `start.js` after the page has loaded and attaches to the HTML.
Sign in, the account area and unknown addresses get `app.html`, an empty shell the browser fills.
The web server (`infra/Caddyfile`) serves a page, then `<path>/index.html`, then `app.html`.

Content shown before scripts run must not depend on the browser. Things that need `window`,
storage or the clock are decided after the first render (see `CookieNotice`, `FadeUp`).

## Search engines

Each page sets its title, description, canonical address, Open Graph tags and JSON-LD through
`components/site/Seo.tsx`. The practice is marked up as `Dentist` and `LocalBusiness`; the FAQ as
`FAQPage`; articles and breadcrumbs have their own data. `sitemap.xml` and `robots.txt` are
written at build. Set `VITE_SITE_URL` to the public address. Demonstration reviews are not marked
up as ratings.

## Pictures

WebP with a `srcset`, a width and a height on every image, and `loading="lazy"` below the first
screen. See `frontend/src/assets/images/CREDITS.md`: they are generated illustrations, not photos.

## Checks

`npm run audit:site` builds the same way, serves it with compression and runs Lighthouse (mobile
settings) on the home page, a service page and the style guide. Required: performance 90 or more,
accessibility, best practices and SEO 95 or more. The accessibility checks also run in the unit
tests (`vitest-axe`), and a site wide text rule check runs with `python scripts/check_text_rules.py`.

## Booking and the assistant

The booking wizard and the patient portal are described in [booking-and-portal.md](booking-and-portal.md), the chat window in [chat-widget.md](chat-widget.md).
