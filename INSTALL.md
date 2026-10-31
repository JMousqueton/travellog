# Voyage Voyage — installation and operations

*Version française : [INSTALL_FR.md](INSTALL_FR.md) · Back to the [README](README.md)*

## Requirements

- Python 3.11 or later
- PostgreSQL (tested with 18) and its client tools (`pg_dump`, `pg_restore`, `psql`, package
  `postgresql-client`) for backups
- Network access to the map tiles, Nominatim
  and, for flight number lookup, adsbdb.
  Bootstrap, Font Awesome, Chart.js, the Inter font, Leaflet, MarkerCluster, d3-geo and d3-array are bundled in
  `app/static/vendor/`: no page calls a CDN, so visitors' IP addresses only reach the map tile server.

## Installation

```bash
git clone https://github.com/JMousqueton/travellog.git && cd travellog
make install            # or: python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env    # then fill in SECRET_KEY, NOMINATIM_USER_AGENT, POSTGRES_PASSWORD and DATABASE_URL
sudo docker compose -f deploy/postgres/compose.yml --env-file .env up -d   # or any PostgreSQL server
source .venv/bin/activate
flask translate compile # compiles the .po files into .mo (already done by make install)
flask db upgrade        # creates the tables in the DATABASE_URL database
flask seed              # optional: demo@example.com / demo1234 with 12 trips
flask create-admin you@example.com   # creates an administrator (password prompted)
```

`flask create-admin` also promotes an existing account. Administrators reach `/admin/` (list of users) from
the account menu.

## Running

```bash
flask run --debug       # or: make run
```

The application is available at <http://127.0.0.1:5000>.
`flask seed --reset` resets the demo account's trips, language and theme.

In production, use `FLASK_CONFIG=production`, a real `SECRET_KEY` and a WSGI server, for example
`gunicorn "app:create_app()"`. Session cookies are then marked `Secure`, and the application refuses to start
if `SECRET_KEY` is missing or set to an example value.

### Production on this server (voyage-voyage.app)

- systemd service `travellog` (copy in `deploy/travellog.service`): gunicorn, 1 worker and 8 threads on
  `127.0.0.1:5012`, with `FLASK_CONFIG=production`, `APP_BASE_URL=https://voyage-voyage.app` and
  `PROXY_FIX_COUNT=1` (everything else comes from `.env`). `sudo systemctl restart travellog` after a code
  update; logs: `journalctl -u travellog`.
- PostgreSQL 18 in Docker: container `travellog-postgres` (`deploy/postgres/compose.yml`, volume
  `travellog_pgdata`, restarted by Docker), listening on `127.0.0.1:5432` only; password in `.env`
  (`POSTGRES_PASSWORD`). Shell: `sudo docker exec -it travellog-postgres psql -U travel`.
  The former SQLite database was copied with `scripts/sqlite_to_postgres.py` (kept for older backups).
- nginx: `deploy/nginx/voyage-voyage.app.conf` (HTTPS, static files served directly, 64 MB per upload);
  `www.voyage-voyage.app` and the former address `travellog.julien.io` redirect to `https://voyage-voyage.app`.
  Static file URLs carry a fingerprint of their content (`?v=…`, see `app/assets.py`): nginx caches them
  for a year, and a modified file gets a new URL.
  Until the certificate exists, a temporary configuration only handles Let's Encrypt validation and the
  redirect to HTTPS.
- Certificate (`voyage-voyage.app` and `www`): once DNS is in place (A `213.32.17.149`, AAAA `2001:41d0:305:2100::1:1c4b`), run
  `deploy/enable-https.sh`. Renewal is handled by `certbot.timer`.
- Updating: `git pull`, `.venv/bin/pip install -r requirements.txt`, `flask backup create`, `flask db upgrade`,
  `flask translate compile`, then `sudo systemctl restart travellog`.

Behind a reverse proxy, set `PROXY_FIX_COUNT` (otherwise rate limiting sees the proxy's address for
everyone) and `APP_BASE_URL`. With several workers, give rate limiting shared storage
(`RATELIMIT_STORAGE_URI=redis://…`).

Periodic tasks run as systemd timers (`deploy/systemd/`), each through `flask jobs run <task>`, which records
every run (start, end, result, traceback on failure) in the database:

| Task | Timer | What it does |
|---|---|---|
| `mail-import` | every 5 minutes | import by email (skipped while `IMAP_SERVER` is empty) |
| `backup` | every night at 03:15 | full backup (`flask backup create`) |
| `maintenance` | every night at 04:30 | purges the expired geocoding cache, expired share links, imported or ignored entries of the email import log older than `MAIL_IMPORT_LOG_DAYS` (90 days) and task history older than 14 days; re-reads from Stripe the subscriptions whose paid period has ended (in case a webhook was lost) |

```bash
sudo deploy/systemd/install.sh     # installs and starts the timers, removes the cron lines they replace
flask jobs list                    # last run of each task
systemctl list-timers 'travellog-*'
journalctl -u 'travellog-job@*'
```

The administration's "Tasks" tab (`/admin/jobs`) shows the last run of each task, flags failed tasks and tasks
that are late (no success for twice their interval), counts the past 24 hours of email imports and lists the
latest runs with their traceback. A timer never starts a task that is still running, so no lock file is needed.
The individual commands still exist for manual use (`flask geocode purge [--all]`, `flask purge-share-links`,
`flask mail-import --dry-run`…), but they are not recorded.

Full server backups (PostgreSQL dump + photos, `.tar.gz` archive with a manifest):

```bash
flask backup create              # into BACKUP_DIR (instance/backups by default), keeps the BACKUP_KEEP most recent
flask backup list
flask backup restore instance/backups/travel-backup-YYYYMMDD-HHMMSS.tar.gz   # with the application stopped
```

The dump (`pg_dump`, custom format) and the manifest's row counts come from the same snapshot, so a backup is
consistent while the application runs. Restoring checks the archive (paths, readable dump), first backs up
the current state, then replaces the database in a single transaction that is cancelled if the row counts
differ from the manifest, and applies migrations if the archive is older than the code. The nightly backup is the `backup` task above.

Import by email: IMAP settings in `.env` (`IMAP_SERVER`, `IMAP_USERNAME`, `IMAP_PASSWORD`…), run by the
`mail-import` task.

Premium (Stripe):

1. Put the secret key in `.env` (`STRIPE_SECRET_KEY`, `sk_test_…` for testing, `sk_live_…` or a restricted
   `rk_live_…` in production). A restricted key needs write access to Products, Prices, Customers, Checkout
   Sessions and Subscriptions, and read access to Invoices. Keep the test key in a development copy's
   `.env`, never next to the live one.
2. The product ("Voyage Voyage Premium", tax code `STRIPE_TAX_CODE`) and the prices are created by the
   application on first use, from `PREMIUM_PRICE_MONTHLY`, `PREMIUM_PRICE_YEARLY` and `PREMIUM_CURRENCY`.
   A new amount creates a new price for new subscribers; existing subscribers keep theirs (archive the old
   price in Stripe so it can't be reused).
3. In Stripe, add a webhook endpoint `https://<domain>/billing/webhook` with the events
   `checkout.session.completed`, `customer.subscription.created`, `customer.subscription.updated`,
   `customer.subscription.deleted`, `invoice.paid` and `invoice.payment_failed`, and put its secret in
   `STRIPE_WEBHOOK_SECRET`. On each event the subscription is re-read from Stripe, so duplicates and events
   out of order don't matter. Locally: `stripe listen --forward-to localhost:5000/billing/webhook`.
4. Taxes: with Stripe Managed Payments turned on, Stripe is the seller and charges VAT; turned off
   (Settings → Managed Payments), the prices are charged as is. Under the French VAT exemption, add
   "TVA non applicable, art. 293 B du CGI" to the invoice footer (Settings → Billing → Invoices).

Copy `instance/backups` to another machine regularly: a backup on the same disk doesn't protect against that
disk failing. Each user can also download their own backup (trips + photos, `.zip`) from their preferences and
import it back from the Import / export page.

To check email sending: `flask mail-test you@example.com`. On this server, emails go out from
`no-reply@voyage-voyage.app` through `mail.ransomware.live` (port 587, STARTTLS, authenticated; password in `.env`).

Other maintenance commands:

```bash
flask trips backfill-countries   # fills in missing countries from the coordinates (--force: recalculate all)
flask trips compute-routes       # calculates missing road distances (ROUTING_URL required, 1 request/s)
flask photos cleanup --dry-run   # lists (then deletes, without --dry-run) photo files with no database row
```

Photos are stored in `instance/uploads` (or `UPLOAD_FOLDER`): include this folder in your backups, along with
the database.

### Security

- Rate limiting (Flask-Limiter): sign-in (per IP address and per targeted account, only failures count),
  sign-up, reset requests, password change and account deletion. A translated 429 response is returned
  beyond the limit.
- Headers: `Content-Security-Policy` with a nonce for the inline script, `X-Frame-Options: DENY`,
  `X-Content-Type-Options`, `Referrer-Policy: strict-origin-when-cross-origin` (share link tokens are not
  sent to tile servers or CDNs), `Permissions-Policy`, and HSTS over HTTPS (`HSTS_MAX_AGE`).
- `tests/test_csp.py` loads the main pages and checks that every script, stylesheet and image is allowed by
  the CSP and that every inline script carries the nonce: add the origin of a new library or service to
  `app/security.py`, or the test fails.
- Audience measurement: self-hosted Matomo (`stats.mousqueton.io`, site 13), loaded in `base.html`. Tokens in
  share, sign-up and password reset links are masked before sending. The privacy policy (`/privacy`)
  describes it and offers an opt-out button.
- CDN files are loaded with an `integrity` hash (SRI). After a version upgrade, recompute the hash:
  `curl -sL URL | openssl dgst -sha384 -binary | openssl base64 -A`.
- The session identifier contains a fingerprint of the password: changing or resetting the password
  invalidates all other sessions, as well as reset links already sent.

## Configuration (`.env`)

| Variable | Purpose |
|---|---|
| `SECRET_KEY` | Flask secret key (mandatory in production) |
| `FLASK_CONFIG` | `development`, `production` or `testing` |
| `DATABASE_URL` | PostgreSQL URL, required (`postgresql://user:password@host:5432/travel`) |
| `TEST_DATABASE_URL` | PostgreSQL database for the tests, emptied by them (name must end in `_test`) |
| `NOMINATIM_URL` | Nominatim search endpoint (public or self-hosted instance) |
| `NOMINATIM_USER_AGENT` | User-Agent identifying the application, **mandatory** under the Nominatim policy |
| `NOMINATIM_EMAIL` | Optional contact address (`email=` parameter) |
| `NOMINATIM_MIN_INTERVAL` | Minimum delay between two requests, in seconds (1 by default) |
| `NOMINATIM_LOCK_FILE` | Lock file shared between workers (default `instance/nominatim.lock`) |
| `GEOCODE_CACHE_DAYS` | How long the geocoding and flight lookup cache stays valid |
| `FLIGHT_LOOKUP_URL`, `FLIGHT_LOOKUP_TIMEOUT` | Route lookup for a flight number (adsbdb by default; empty to disable) |
| `MAP_TILE_URL`, `MAP_TILE_URL_DARK` | Light and dark tiles (see below) |
| `MAP_TILE_SUBDOMAINS`, `MAP_TILE_ATTRIBUTION`, `MAP_TILE_MAX_ZOOM` | Tile provider options |
| `LOGO_DEV_TOKEN` | logo.dev publishable key (`pk_…`): shows airline and rail operator logos, looked up by name, on `/stats/plane` and `/stats/train`; none without it |
| `APP_BASE_URL` | Public address, used in links sent by email |
| `PROXY_FIX_COUNT` | Number of trusted reverse proxies (`X-Forwarded-*`) |
| `RATELIMIT_STORAGE_URI` | Rate limiting storage (`memory://`, `redis://…`) |
| `LOGIN_RATE_LIMIT`, `REGISTER_RATE_LIMIT`, `PASSWORD_RESET_RATE_LIMIT` | Limits, e.g. `5 per minute;30 per hour` |
| `HSTS_MAX_AGE` | HSTS duration in seconds (1 year by default in production, 0 to disable) |
| `MAIL_SERVER`, `MAIL_PORT`, `MAIL_USE_TLS`, `MAIL_USE_SSL`, `MAIL_USERNAME`, `MAIL_PASSWORD`, `MAIL_FROM` | SMTP for sign-up and password reset emails |
| `SIGNUP_LINK_MAX_AGE` | Validity of the sign-up magic link, in seconds (900 = 15 min) |
| `PASSWORD_RESET_MAX_AGE` | Validity of the reset link, in seconds (3600) |
| `LOG_LEVEL` | Logging level (`INFO` by default) |
| `SENTRY_DSN`, `SENTRY_TRACES_SAMPLE_RATE` | Sentry error tracking (requires `sentry-sdk[flask]`) |
| `UPLOAD_FOLDER` | Photo folder (default `instance/uploads`) |
| `IMPORT_FOLDER` | Import previews awaiting confirmation (default `instance/imports`, one hour) |
| `BACKUP_DIR`, `BACKUP_KEEP` | Backup folder (default `instance/backups`) and number of archives kept (14) |
| `ROUTING_URL`, `ROUTING_PROFILES`, `ROUTING_TIMEOUT` | OSRM server and routed modes (default `car:driving,bus:driving`) |
| `MAX_PHOTO_MB`, `MAX_UPLOAD_MB`, `MAX_PHOTOS_PER_ITEM` | Photo limits (15 MB per photo, 64 MB per upload, 30 per trip or journey) |
| `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET` | Stripe secret key and webhook signing secret (`whsec_…`); without the key, Premium is off |
| `PREMIUM_PRICE_MONTHLY`, `PREMIUM_PRICE_YEARLY`, `PREMIUM_CURRENCY` | Premium prices in currency units (`2`, `12`, `eur` by default; `2.50` accepted) |
| `STRIPE_TAX_CODE` | Tax code of the Stripe product (`txcd_10103000`, SaaS for personal use), required by Managed Payments |

### Base map

By default, the application uses the standard OpenStreetMap tiles. In dark mode, a CSS filter darkens them.
For dedicated light and dark tiles (CARTO, Stadia, MapTiler…), set `MAP_TILE_URL` and `MAP_TILE_URL_DARK` to
the URL given by the provider. These services usually require an API key: `basemaps.cartocdn.com` tiles
without a key now display "API KEY REQUIRED". Add the provider's attribution in `MAP_TILE_ATTRIBUTION`.

### Geocoding

- Searches go through the server (`/api/geocode`), never directly from the browser to Nominatim.
- Results are cached in the `geocode_cache` table, keyed by `(normalised query, language)`.
- A lock file (`flock`) guarantees at most one request every `NOMINATIM_MIN_INTERVAL` seconds across all
  workers on the same machine. On several machines, each applies its own limit: use a dedicated Nominatim
  instance in that case. On Windows, the lock only applies within the process.
- On the client side, typing is debounced (450 ms, at least 3 characters).
- The public instance's [usage policy](https://operations.osmfoundation.org/policies/nominatim/) discourages
  heavy autocompletion. For real-world use, prefer a self-hosted instance or a compatible commercial service,
  through `NOMINATIM_URL`.
- If the user submits a place without choosing a suggestion, the server geocodes the text entered.

## Structure

```
app/
  __init__.py        application factory, error handling
  extensions.py      db, migrate, login, csrf, babel
  models.py          User, Trip, GeocodeCache (CHECK constraints, indexes)
  i18n.py            language selection, formatting, JS strings
  geo.py             haversine, Nominatim client and cache
  security.py        security headers (CSP with nonce, HSTS…)
  airports.py        airports by IATA or ICAO code, airlines by ICAO or IATA code
  flights.py         route of a flight number (adsbdb, cached)
  carriers.py        airline, operator and aircraft suggestions
  pwa.py             service worker and offline page
  assets.py          versioned static files (?v=fingerprint) and import map for JS modules
  countries.py       countries: offline lookup, localised names, flags, areas
  photos.py          photos: validation and re-encoding (Pillow), thumbnails, files
  data/              country borders (Natural Earth), airports (OurAirports), Inter font (SIL OFL) for the review image
  ics.py             iCalendar feed
  routing.py         route distances (OSRM)
  tags.py            tags
  backup.py          server backup and restore
  trips/absences.py  days away; trips/badges.py badges and continents; trips/places.py places visited
  review_image.py    year-in-review image (Pillow)
  mail.py            SMTP email sending
  transport.py       modes of transport (label, icon, colours)
  cli.py             flask seed, flask translate …
  auth/ trips/ api/ main/ share/ admin/ transfer/ support/ billing/   blueprints (transfer: import / export; support: tickets; billing: Premium subscription with Stripe)
  templates/  static/  translations/
migrations/          Alembic (Flask-Migrate)
tests/               pytest
config.py  run.py  babel.cfg  Makefile  requirements.txt  .env.example
```

## JSON API

All routes require a session (otherwise 401 as JSON). Error messages are translated.

| Route | Description |
|---|---|
| `GET /api/trips` | The user's trips. Filters: `from`, `to` (YYYY-MM-DD, on the departure date), `modes=plane,train`, `kind=all\|oneway\|round` |
| `GET /api/stats` | Same filters: count, total distance, breakdown by mode (raw and formatted values) |
| Common filters | `when=all\|past\|upcoming`, `tags=1,4` (tag IDs, at least one), `q=…` (search) |
| `GET /api/places` | Same filters: places visited `{name, lat, lon, visits, country}` |
| `GET /api/countries` | Same filters: countries visited as GeoJSON (borders, localised name, flag, number of trips) |
| `GET /api/geocode?q=…&lang=…` | Place suggestions `{name, label, lat, lon, type, country_code}` |

Share links have the equivalents `/api/shared/<token>/trips`, `/stats` and `/countries`.

### Countries and CO₂

- Country borders come from [Natural Earth](https://www.naturalearthdata.com/) at 1:50m (public domain),
  simplified in `app/data/countries.geojson` (237 countries and territories). A coastal point that falls just
  outside the outline is attached to the nearest country within 25 km.
- Country names are localised by Babel (CLDR).
- Airports (the 9,227 with an IATA code, plus their ICAO code) are in `app/data/airports.csv`. They come from
  [OurAirports](https://ourairports.com/data/) (public domain), supplemented by
  [OpenFlights](https://openflights.org/data.php) ([ODbL](https://opendatacommons.org/licenses/odbl/1-0/)) for 174
  closed airports whose code OurAirports removed (Berlin-Tegel, Schönefeld…) but which still appear in flight
  histories. That file is therefore distributed under the ODbL. Airlines (1,026 active ones: ICAO code, IATA
  code and name) also come from OpenFlights, in `app/data/airlines.csv` (ODbL); a defunct airline keeps its
  code, since its ICAO code may have been reassigned. To refresh both files:
  `.venv/bin/python scripts/make_flight_data.py`.
- The globe's outlines (`app/static/data/world.json`, simplified from `app/data/countries.geojson`) come from
  `scripts/make_globe_data.py`. The regions of large countries (`app/data/regions.json`) come from the Natural
  Earth 1:10m admin-1 subdivisions (public domain), simplified and grouped by
  `scripts/make_region_data.py` (the 40 MB source is downloaded if not given).
- CO₂ is an estimate per traveller: straight-line distance × an average factor from ADEME (Base Carbone),
  defined in `app/transport.py` (`CO2_KG_PER_KM`, `PLANE_CO2_BANDS`). Plane: 258, 187 or 152 g/km depending
  on flight distance, contrails included; train and coach 30 g/km; car 218 g/km (one person on board);
  ferry 120 g/km; bike and walking 0.

## Tests

```bash
make test               # or: pytest
```

The tests need a PostgreSQL database of their own in `TEST_DATABASE_URL` (its name must end in `_test`, and it is
emptied after each test), for example `sudo docker exec travellog-postgres createdb -U travel travel_test`.

The suite covers the models and constraints, round-trip validation, isolation between users, the API
(filters, statistics, mocked geocoding, cache, rate limit), authentication, CSRF protection, CSP compliance of every page and i18n. For
i18n, it checks language detection, language switching, date and distance formatting, that no key is
missing, untranslated or fuzzy in any `.po` file (compared against a fresh extraction from the code), that
`%(x)s` variables are consistent, and that the JavaScript contains no hard-coded text. The tests make no
network calls.

## Internationalisation

- Language detection order: the user's profile, then the `lang` cookie, then the `Accept-Language` header,
  then French.
- Source strings are in French: `_()` in templates, `gettext` / `lazy_gettext` (`_l`) in Python.
- JavaScript texts are injected into `base.html` (`<script type="application/json" id="i18n-data">`) by
  `app/i18n.py:js_strings()`. The JS files contain only keys.
- Dates, numbers and distances are formatted by Babel on the server. The API's JSON returns both raw and
  formatted values.

### Translation workflow

```bash
flask translate extract     # make extract : code -> app/translations/messages.pot
flask translate update      # make update  : extract + merge into each .po
# … translate the new entries in app/translations/<language>/LC_MESSAGES/messages.po
flask translate compile     # make compile : .po -> .mo
pytest tests/test_i18n.py   # checks that no translation is missing
```

These commands call `pybabel extract -F babel.cfg -k _l -k lazy_gettext`, `pybabel update` and
`pybabel compile`. The `.mo` files are generated and not version-controlled.

### Adding a language

1. Declare it in `LANGUAGES` (`app/i18n.py`), for example `"pt": {"name": "Português"}`.
2. Create the catalogue: `flask translate init pt` (or `make init-lang LOCALE=pt`).
3. Translate `app/translations/pt/LC_MESSAGES/messages.po`.
4. Compile: `flask translate compile`.
5. Run `pytest`: the i18n tests automatically take the new language into account and flag any missing string.

Date and number formats come from Babel (CLDR), and WTForms' built-in messages have their own translations:
no other step is needed.
