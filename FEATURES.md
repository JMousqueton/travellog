# Voyage Voyage — features in detail

*Version française : [FEATURES_FR.md](FEATURES_FR.md) · Back to the [README](README.md)*

- Premium subscription (`/billing`, "Premium" in the account menu), paid through Stripe: 2 € a month or 12 € a
  year by default (prices in `.env`). Photo upload, import by email, share links, the public profile and support
  are Premium features, marked everywhere with a diamond (menu, pages, About and home pages). An email
  sent by an account without Premium is not imported: the sender gets a reply saying why, with a link to
  subscribe. When Premium ends, share
  links and the public profile are no longer served (visitors get a 404) but are kept, and work again with a
  new subscription; they can still be revoked or removed. Payment happens on
  Stripe's hosted page (Checkout); subscribers then see their invoices (`/billing/invoices`, with the
  hosted invoice and its PDF, and a "Pay" button for an unpaid one) and can stop the subscription, which
  then ends at the close of the paid period with no further charge, or resume it until then. A failed
  payment keeps access while Stripe retries. Administrators can give Premium for free (gem button in the
  users tab). Deleting an account deletes its Stripe customer, which cancels the subscription at once.
  Without `STRIPE_SECRET_KEY`, billing is off and nothing is restricted.
- Support (Premium; `/support`, in the account menu): signed-in users open a ticket (subject and message) and follow the
  conversation, which can have as many exchanges as needed; they can close it, and replying reopens it.
  Administrators get a "Tickets" tab (`/admin/tickets`: to handle / answered / closed, with a counter of
  tickets waiting), reply, close or reopen. Each user message is emailed to the administrators, each reply to
  the user, in their own language. Emails are optional: the user chooses for each ticket (when opening it, then
  on its page), and each administrator can turn ticket emails off from the Tickets tab.
- About page (`/about`, linked from the home page and the footer): why the site is called Voyage Voyage
  (a nod to Desireless's song, thanks to Mallorie for the idea) and every feature in detail.
- User accounts (sign-up, sign-in, hashed passwords). Each user only sees their own trips.
  Sign-up by magic link when email sending is configured: the person enters their address, receives a
  single-use link valid for 15 minutes (`SIGNUP_LINK_MAX_AGE`), then chooses their password; the account is
  only created at that step (so the address is verified). If the address already has an account, the email
  invites them to sign in, and the page shown is the same in both cases. Without a mail server, sign-up
  stays direct, with a password.
  From their preferences, users can change their password (which signs out their other sessions) or delete
  their account. Forgotten password: single-use reset link by email.
- Read-only share links (Premium), with optional expiry and the date they were last viewed. Visitors get their own
  menu: Map, Statistics (since the beginning, one card per year, badges), Trips (list grouped by journey, if
  the link allows it) and Review. Upcoming trips are hidden by default (they reveal when you're away); an
  option per link shows them, faded and flagged. No notes, photos or home.
- Public profile (Premium; `/u/<name>`): from Preferences, users can choose a name (3 to 30 lowercase letters, digits,
  `-` or `_`) to publish a summary of their past trips: key figures (trips, distance, countries, continents,
  share of the world's land), distance by mode, countries visited per continent and the badges earned. No trips,
  dates, notes, photos, home or upcoming trips; the page is not indexed by search engines (`noindex`). Clearing
  the name turns the profile off.
- Countries: each trip knows its departure and arrival country (ISO code returned by Nominatim, or derived
  offline from the coordinates). "Countries visited" layer on the map, flags in the list and detail pages.
- Statistics (`/stats`): overview of all trips (key figures, Chart.js charts of trips and distance per year
  and mode, one card per year, badges, plane and train, countries, places, continents, regions, days away,
  CO₂ by mode). Each year has its own page (`/stats/<year>`): figures and change from the previous year (at the
  same date for the current year), a GitHub-style calendar of the year (one square per day: travel day, away
  from home, at home, planned), departures per month, distance by mode, countries visited (new ones flagged),
  highlights, the year's badges, plane and train, tags. The calendar's days away come from the home city when
  it is set, otherwise from round trips.
- Notes and photos on every trip and journey (detail page); adding photos is a Premium feature, and photos
  already added stay visible and can be deleted after the subscription ends. Photos are re-encoded as JPEG, without EXIF
  metadata in the stored file, with a thumbnail. Camera, settings, date taken and GPS position are read at
  upload, kept in the database and shown only to the owner on the photo page (`/photos/<id>`), with a
  small map. They stay private: share links show neither notes
  nor photos.
- Upcoming trips: "In 12 days", "Tomorrow" or "Ongoing" badge, faded routes on the map, past / upcoming
  filter, "Next departure" card on the dashboard. Statistics only count trips that have already started.
- Calendar: `.ics` export of a trip or journey, and a subscription (Google Calendar, Apple Calendar,
  Outlook…) through a secret address that can be enabled, changed or disabled in the preferences. Notes are
  not included.
- Distances: road route calculated by an OSRM server if `ROUTING_URL` is set (car and bus by default),
  otherwise straight-line distance × a detour factor per mode (`DETOUR_FACTORS` in `app/transport.py`:
  road ×1.3, train ×1.25, boat ×1.1, plane in a straight line). The detail page states where the distance
  comes from.
- Tags (holiday, work…): free entry with suggestions, map filter, statistics per tag (including CO₂ for the
  current year), included in exports. A journey's tags apply to all its legs; a tag that is no longer used
  disappears.
- Search in "My trips", ignoring case and accents: places, countries, notes, tags, journey name and notes.
  Year buttons (All, 2026, 2025…), kept along with the search and sort order.
- Year in review (`/review`): key figures, countries discovered, longest trip, favourite destinations,
  departures by month, and a 1080 × 1350 PNG image to download or share (system share sheet on mobile).
  People with a share link only see the current year's review (and the past year's in January and February),
  without download or share buttons (`/s/<token>/review`).
- Days away (home city to set in the preferences): days spent away from home (30 km radius), nights abroad,
  share of the year, longest time away. One-way trips are chained; an absence that started elsewhere ends on
  returning to that city; a trip that doesn't leave from the last place reached closes the current absence
  (unrecorded travel). Home is never shown on share links.
- World coverage: countries and territories visited out of the 237 in Natural Earth (and share of the
  world's land), countries visited per continent with a progress bar, and the regions visited in 14 large
  countries (US, Mexican, Brazilian and Indian states, Canadian provinces, Australian states, German Länder,
  Swiss cantons, Japanese prefectures, Chinese provinces, French, Spanish and Italian regions, UK nations),
  found offline from the trip endpoints (`app/regions.py`).
- Continents and badges (countries, continents, distance, number of trips, modes…), dated by the trip that
  crossed the threshold, with progress towards the remaining badges. Two sets: badges for all your trips
  (statistics overview), and badges for each year (year page), with thresholds suited to a single year
  (12 trips, 10,000 km, 3 continents…). Badges earned during a year appear in its review.
- Places visited: trip endpoints grouped within a 15 km radius, a list and a "Places visited" layer on the
  map (circles sized by the number of trips).
- Replay: on the map, trips are drawn in chronological order (outbound leg on the departure date, return leg
  on the return date); a slider with the years lets you jump to any date.
- Globe: a "Map / Globe" switch on the map shows the same trips on a 3D globe (d3-geo orthographic projection
  on a canvas, no WebGL): flights arc above the surface, visited countries are tinted, the globe spins until
  touched and can be dragged, zoomed (wheel, pinch, buttons) and turned with the arrow keys. Clicking a trip
  (on the globe or in the list) turns the globe towards it and shows its card; replay works on the globe too.
  The choice is remembered in the browser.
- Import by email (Premium): users forward their flight or train confirmations to the import address (`IMPORT_ADDRESS`,
  shown on the import page) from the address of their account. `flask mail-import`, run every 5 minutes by
  a systemd timer, reads the IMAP mailbox: the sender must be an account and the email must carry a valid DKIM signature
  from the sender's domain (otherwise anyone could forge the From address). Trips are read from the schema.org
  JSON-LD data most airlines and agencies embed (flights, trains, buses, boats), then from attached Apple Wallet
  boarding passes (`.pkpass`, see below), otherwise from the text (flight number, airport codes, date in five
  languages); a flight and its return become a round trip. The
  email is then deleted from the mailbox. When nothing is recognised, a ticket is opened by the "Import
  Error" account (`MAIL_IMPORT_ERROR_EMAIL`, which cannot sign in) with the raw email, and the email stays in
  the mailbox. Every email is recorded in `mail_imports`, so it is processed, and its ticket opened, only
  once. Emails from unknown or unauthenticated senders are ignored and left. `--dry-run` shows what would be
  imported without writing or deleting anything.
  Deleting an account also deletes its email import log entries and the error tickets holding its raw emails.
  Each user can also allow other sender addresses (Preferences → Import by email): an address is only added
  once confirmed through a magic link sent to it, it can never be used to sign in, and it can be neither
  an account's address nor another user's import address; signing up with an import address is refused.
- Import / export (`/import-export`) as CSV, GeoJSON and GPX. All three formats carry the same fields
  (including notes and journey groupings) and can be imported back without loss: they also serve as a
  backup, photos excepted. On import, a preview lists the trips read: untick the ones to leave out (all /
  none / per-year buttons) before confirming; trips already present are unticked and skipped. A file
  containing an error imports nothing (errors are listed with their line number). A full backup (.zip) is
  restored directly, photos included.
- Apple Wallet boarding passes (`.pkpass`, or `.pkpasses` holding several), attached to an import email or sent
  from the Import / export page (`app/mail_import/wallet.py`): a plane pass is read from its barcode (IATA BCBP
  format: airports, airline, flight number and day of every flight it holds), otherwise from its "semantics"
  data or its displayed fields (airport codes, flight number, date of the pass); a train, bus or boat pass from
  its "semantics" data (stations and their coordinates, number, operator). Other passes (events, loyalty
  cards) are ignored. The pass signature is not checked: the email carrying it is authenticated (DKIM), and an
  uploaded file goes through the import preview.
- Flight history import: CSV exports from Flighty and myFlightradar24 are recognised automatically. Each
  flight becomes a plane trip between the two airports (cancelled flights skipped, diversion airport used as
  the arrival, US M/D/YY or DD/MM/YYYY dates detected from the file). The airline (name looked up from its
  ICAO code), flight number ("AF1148") and aircraft go into the trip's fields; cancelled flights are listed in
  the preview.
  A flight followed by its return flight (within 50 km: CDG out, ORY back) becomes a round trip; multi-stop
  itineraries stay as one-way flights, and a cancelled or missing return does not throw off later ones.
- Plane and train: airline, flight number and aircraft for planes, operator for trains, entered in the
  form (labels follow the mode; the airline or operator field autocompletes, first with the ones already
  entered, then with the main airlines or rail operators from `app/carriers.py`) or filled by the flight
  import. The aircraft field autocompletes too (aircraft already entered, then the main models). Entering a
  flight number ("AF1148") fills in the airline, departure and arrival when they're empty: the airline from
  the prefix (offline), the number's usual route from the free [adsbdb](https://www.adsbdb.com) service,
  queried by the server and cached (`/api/flight`, `app/flights.py`; empty `FLIGHT_LOOKUP_URL` disables it).
  It's today's route: check it for an old flight. The statistics derive, per mode, the number of flights or
  trips and the most frequent airlines, aircraft and airports or stations (a round trip "AF1148 / AF1549"
  counts twice), with a detail page (`/stats/plane`, `/stats/train`, filterable by year): each airline's
  share, first and last flight, manufacturers, most frequent routes.
- Trips: origin, destination, date, mode of transport (plane, train, car, bus, boat, bike, on foot), round
  trip option with a mandatory return date on or after the departure date.
- Form with place autocompletion (Nominatim, server-side geocoding with a database cache).
- Full-screen Leaflet map: clustered markers (markercluster), localised popups, legend.
- Side panel (drawer on mobile): year buttons (All, 2026, 2025…) that fill in the period, dashboard for the
  chosen year (the current year with "All"), filters (period, modes, type), sortable list kept in sync with
  the map. Filters are kept in the URL.
- Light/dark theme (saved preference and `prefers-color-scheme` detection).
- Installable app that works offline: a service worker (`/sw.js`, `app/pwa.py`) caches static files and
  libraries, plus the latest version of pages and data already opened (map, list, statistics, trip pages).
  Map tiles are not kept: offline, the map shows the trips without a base map (the globe stays complete).
  Account pages are removed from the cache on logout.
- Passport-style 404 page: marble cover, world map (generated from the Natural Earth outlines by
  `scripts/make_world_svg.py`), plane and a "404 · Destination not found" stamp.
- Full internationalisation with Flask-Babel. Dates, numbers and distances are formatted for each language.
