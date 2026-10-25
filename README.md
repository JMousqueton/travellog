# Travel Log

*Version française : [README_FR.md](README_FR.md)*

A Flask web application for keeping track of your travels on a map: trips coloured by mode of transport,
geodesic arcs for flights, dashed return legs, filters, statistics, light/dark theme, and an interface
available in French, English, Spanish, German and Italian.

## Features

- User accounts (sign-up, sign-in, hashed passwords). Each user only sees their own trips.
  Sign-up by magic link when email sending is configured: the person enters their address, receives a
  single-use link valid for 15 minutes (`SIGNUP_LINK_MAX_AGE`), then chooses their password; the account is
  only created at that step (so the address is verified). If the address already has an account, the email
  invites them to sign in, and the page shown is the same in both cases. Without a mail server, sign-up
  stays direct, with a password.
  From their preferences, users can change their password (which signs out their other sessions) or delete
  their account. Forgotten password: single-use reset link by email.
- Read-only share links, with optional expiry and the date they were last viewed.
- Countries: each trip knows its departure and arrival country (ISO code returned by Nominatim, or derived
  offline from the coordinates). "Countries visited" layer on the map, flags in the list and detail pages.
- Statistics (`/stats`): totals, year by year (distance, modes, countries discovered), estimated CO₂
  emissions by mode, share of the world's land covered, list of countries visited.
- Notes and photos on every trip and journey (detail page). Photos are re-encoded as JPEG, without EXIF
  metadata (so without GPS location), with a thumbnail. They stay private: share links show neither notes
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
- Year in review (`/review`): key figures, countries discovered, longest trip, favourite destinations,
  departures by month, and a 1080 × 1350 PNG image to download or share (system share sheet on mobile).
  People with a share link can see the review too (`/s/<token>/review`).
- Days away (home city to set in the preferences): days spent away from home (30 km radius), nights abroad,
  share of the year, longest time away. One-way trips are chained; an absence that started elsewhere ends on
  returning to that city; a trip that doesn't leave from the last place reached closes the current absence
  (unrecorded travel). Home is never shown on share links.
- Continents and badges (countries, continents, distance, number of trips, modes…), dated by the trip that
  crossed the threshold, with progress towards the remaining badges. The year's badges appear in the review.
- Places visited: trip endpoints grouped within a 15 km radius, a list and a "Places visited" layer on the
  map (circles sized by the number of trips).
- Replay: on the map, trips are drawn in chronological order (outbound leg on the departure date, return leg
  on the return date); a slider with the years lets you jump to any date.
- Share links: upcoming trips are hidden by default (they reveal when you're away); an option per link
  shows them.
- Import / export (`/import-export`) as CSV, GeoJSON and GPX. All three formats carry the same fields
  (including notes and journey groupings) and can be imported back without loss: they also serve as a
  backup, photos excepted. On import, trips already present are skipped, and a file containing an error
  imports nothing (errors are listed with their line number).
- Trips: origin, destination, date, mode of transport (plane, train, car, bus, boat, bike, on foot), round
  trip option with a mandatory return date on or after the departure date.
- Form with place autocompletion (Nominatim, server-side geocoding with a database cache).
- Full-screen Leaflet map: clustered markers (markercluster), localised popups, legend.
- Side panel (drawer on mobile): dashboard, filters (period, modes, type), sortable list kept in sync with
  the map. Filters are kept in the URL.
- Light/dark theme (saved preference and `prefers-color-scheme` detection).
- Full internationalisation with Flask-Babel. Dates, numbers and distances are formatted for each language.

## Requirements

- Python 3.11 or later
- Network access to the CDNs (Bootstrap, Font Awesome, Leaflet, Google Fonts), the map tiles and Nominatim

## Installation

```bash
git clone https://github.com/JMousqueton/travellog.git && cd travellog
make install            # or: python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env    # then fill in SECRET_KEY and NOMINATIM_USER_AGENT
source .venv/bin/activate
flask translate compile # compiles the .po files into .mo (already done by make install)
flask db upgrade        # creates instance/travel.db
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

### Production on this server (travellog.julien.io)

- systemd service `travellog` (copy in `deploy/travellog.service`): gunicorn, 1 worker and 8 threads on
  `127.0.0.1:5012`, with `FLASK_CONFIG=production`, `APP_BASE_URL=https://travellog.julien.io` and
  `PROXY_FIX_COUNT=1` (everything else comes from `.env`). `sudo systemctl restart travellog` after a code
  update; logs: `journalctl -u travellog`.
- nginx: `deploy/nginx/travellog.julien.io.conf` (HTTPS, static files served directly, 64 MB per upload).
  Until the certificate exists, a temporary configuration only handles Let's Encrypt validation and the
  redirect to HTTPS.
- Certificate: once DNS is in place (A `213.32.17.149`, AAAA `2001:41d0:305:2100::1:1c4b`), run
  `deploy/enable-https.sh`. Renewal is handled by `certbot.timer`.
- Updating: `git pull`, `.venv/bin/pip install -r requirements.txt`, `flask backup create`, `flask db upgrade`,
  `flask translate compile`, then `sudo systemctl restart travellog`.

Behind a reverse proxy, set `PROXY_FIX_COUNT` (otherwise rate limiting sees the proxy's address for
everyone) and `APP_BASE_URL`. With several workers, give rate limiting shared storage
(`RATELIMIT_STORAGE_URI=redis://…`).

Recommended periodic tasks (cron):

```bash
flask geocode purge        # removes expired entries from the geocoding cache (--all: everything)
flask purge-share-links    # removes expired share links
```

Full server backups (SQLite database + photos, `.tar.gz` archive with a manifest):

```bash
flask backup create              # into BACKUP_DIR (instance/backups by default), keeps the BACKUP_KEEP most recent
flask backup list
flask backup restore instance/backups/travel-backup-YYYYMMDD-HHMMSS.tar.gz   # with the application stopped
```

Restoring checks the archive (paths, SQLite integrity, manifest), first backs up the current state, then
applies migrations if the archive is older than the code. Example nightly task (cron):

```
15 3 * * * cd /opt/travel && .venv/bin/flask backup create >> instance/backups/backup.log 2>&1
```

Copy `instance/backups` to another machine regularly: a backup on the same disk doesn't protect against that
disk failing. Each user can also download their own backup (trips + photos, `.zip`) from their preferences and
import it back from the Import / export page.

To check email sending: `flask mail-test you@example.com`. On this server, emails go out through the local
Postfix (`MAIL_SERVER=localhost`, port 25, no authentication), as for Yet-Another-Blog.

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
- CDN files are loaded with an `integrity` hash (SRI). After a version upgrade, recompute the hash:
  `curl -sL URL | openssl dgst -sha384 -binary | openssl base64 -A`.
- The session identifier contains a fingerprint of the password: changing or resetting the password
  invalidates all other sessions, as well as reset links already sent.

## Configuration (`.env`)

| Variable | Purpose |
|---|---|
| `SECRET_KEY` | Flask secret key (mandatory in production) |
| `FLASK_CONFIG` | `development`, `production` or `testing` |
| `DATABASE_URL` | SQLAlchemy URL (default `instance/travel.db`) |
| `NOMINATIM_URL` | Nominatim search endpoint (public or self-hosted instance) |
| `NOMINATIM_USER_AGENT` | User-Agent identifying the application, **mandatory** under the Nominatim policy |
| `NOMINATIM_EMAIL` | Optional contact address (`email=` parameter) |
| `NOMINATIM_MIN_INTERVAL` | Minimum delay between two requests, in seconds (1 by default) |
| `NOMINATIM_LOCK_FILE` | Lock file shared between workers (default `instance/nominatim.lock`) |
| `GEOCODE_CACHE_DAYS` | How long the geocoding cache stays valid |
| `MAP_TILE_URL`, `MAP_TILE_URL_DARK` | Light and dark tiles (see below) |
| `MAP_TILE_SUBDOMAINS`, `MAP_TILE_ATTRIBUTION`, `MAP_TILE_MAX_ZOOM` | Tile provider options |
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
| `BACKUP_DIR`, `BACKUP_KEEP` | Backup folder (default `instance/backups`) and number of archives kept (14) |
| `ROUTING_URL`, `ROUTING_PROFILES`, `ROUTING_TIMEOUT` | OSRM server and routed modes (default `car:driving,bus:driving`) |
| `MAX_PHOTO_MB`, `MAX_UPLOAD_MB`, `MAX_PHOTOS_PER_ITEM` | Photo limits (15 MB per photo, 64 MB per upload, 30 per trip or journey) |

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
  countries.py       countries: offline lookup, localised names, flags, areas
  photos.py          photos: validation and re-encoding (Pillow), thumbnails, files
  data/              country borders (Natural Earth), Inter font (SIL OFL) for the review image
  ics.py             iCalendar feed
  routing.py         route distances (OSRM)
  tags.py            tags
  backup.py          server backup and restore
  trips/absences.py  days away; trips/badges.py badges and continents; trips/places.py places visited
  review_image.py    year-in-review image (Pillow)
  mail.py            SMTP email sending
  transport.py       modes of transport (label, icon, colours)
  cli.py             flask seed, flask translate …
  auth/ trips/ api/ main/ share/ admin/ transfer/   blueprints (transfer: import / export)
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
- CO₂ is an estimate per traveller: straight-line distance × an average factor from ADEME (Base Carbone),
  defined in `app/transport.py` (`CO2_KG_PER_KM`, `PLANE_CO2_BANDS`). Plane: 258, 187 or 152 g/km depending
  on flight distance, contrails included; train and coach 30 g/km; car 218 g/km (one person on board);
  ferry 120 g/km; bike and walking 0.

## Tests

```bash
make test               # or: pytest
```

The suite covers the models and constraints, round-trip validation, isolation between users, the API
(filters, statistics, mocked geocoding, cache, rate limit), authentication, CSRF protection and i18n. For
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
