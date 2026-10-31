# Voyage Voyage — installation et exploitation

*English version: [INSTALL.md](INSTALL.md) · Retour au [README](README_FR.md)*

## Prérequis

- Python 3.11 ou plus récent
- PostgreSQL (testé avec la 18) et ses outils clients (`pg_dump`, `pg_restore`, `psql`, paquet
  `postgresql-client`) pour les sauvegardes
- Un accès réseau aux tuiles de carte, à Nominatim
  et, pour la recherche par numéro de vol, à adsbdb. Bootstrap, Font Awesome, Chart.js, la police Inter, Leaflet,
  MarkerCluster, d3-geo et d3-array sont fournis dans `app/static/vendor/` : aucune page n'appelle de CDN, l'adresse IP
  des visiteurs ne part donc que vers le serveur de tuiles.

## Installation

```bash
git clone https://github.com/JMousqueton/travellog.git && cd travellog
make install            # ou : python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env    # puis renseignez SECRET_KEY, NOMINATIM_USER_AGENT, POSTGRES_PASSWORD et DATABASE_URL
sudo docker compose -f deploy/postgres/compose.yml --env-file .env up -d   # ou tout serveur PostgreSQL
source .venv/bin/activate
flask translate compile # compile les .po en .mo (déjà fait par make install)
flask db upgrade        # crée les tables dans la base de DATABASE_URL
flask seed              # optionnel : demo@example.com / demo1234 avec 12 voyages
flask create-admin vous@example.com   # crée un administrateur (mot de passe demandé)
```

`flask create-admin` promeut aussi un compte existant. Les administrateurs accèdent à `/admin/`
(liste des utilisateurs) depuis le menu du compte.

## Lancement

```bash
flask run --debug       # ou : make run
```

L'application est disponible sur <http://127.0.0.1:5000>.
`flask seed --reset` réinitialise les voyages, la langue et le thème du compte de démonstration.

En production, utilisez `FLASK_CONFIG=production`, une vraie `SECRET_KEY` et un serveur WSGI, par
exemple `gunicorn "app:create_app()"`. Les cookies de session sont alors marqués `Secure`, et l'application
refuse de démarrer si `SECRET_KEY` est absente ou vaut une valeur d'exemple.

### Production sur ce serveur (voyage-voyage.app)

- Service systemd `travellog` (copie dans `deploy/travellog.service`) : gunicorn, 1 worker et 8 fils
  d'exécution sur `127.0.0.1:5012`, avec `FLASK_CONFIG=production`, `APP_BASE_URL=https://voyage-voyage.app`
  et `PROXY_FIX_COUNT=1` (le reste vient de `.env`). `sudo systemctl restart travellog` après une mise à jour
  du code ; journal : `journalctl -u travellog`.
- PostgreSQL 18 dans Docker : conteneur `travellog-postgres` (`deploy/postgres/compose.yml`, volume
  `travellog_pgdata`, relancé par Docker), à l'écoute sur `127.0.0.1:5432` seulement ; mot de passe dans `.env`
  (`POSTGRES_PASSWORD`). Console : `sudo docker exec -it travellog-postgres psql -U travel`.
  L'ancienne base SQLite a été copiée par `scripts/sqlite_to_postgres.py` (conservé pour les anciennes sauvegardes).
- nginx : `deploy/nginx/voyage-voyage.app.conf` (HTTPS, fichiers statiques servis directement, 64 Mo par
  envoi) ; `www.voyage-voyage.app` et l'ancienne adresse `travellog.julien.io` redirigent vers
  `https://voyage-voyage.app`. Les adresses des fichiers statiques portent l'empreinte de leur contenu (`?v=…`, voir
  `app/assets.py`) : nginx les met en cache un an, et un fichier modifié change d'adresse. Tant que le certificat n'existe pas, une configuration transitoire ne fait que la validation
  Let's Encrypt et la redirection vers HTTPS.
- Certificat (`voyage-voyage.app` et `www`) : une fois le DNS en place (A `213.32.17.149`, AAAA `2001:41d0:305:2100::1:1c4b`), lancer
  `deploy/enable-https.sh`. Le renouvellement est assuré par `certbot.timer`.
- Mise à jour : `git pull`, `.venv/bin/pip install -r requirements.txt`, `flask backup create`,
  `flask db upgrade`, `flask translate compile`, puis `sudo systemctl restart travellog`.

Derrière un proxy inverse, définissez `PROXY_FIX_COUNT` (sinon la limitation de débit voit l'adresse du
proxy pour tout le monde) et `APP_BASE_URL`. Avec plusieurs workers, donnez à la limitation de débit un
stockage partagé (`RATELIMIT_STORAGE_URI=redis://…`).

Les tâches périodiques sont des timers systemd (`deploy/systemd/`), chacune lancée par `flask jobs run <tâche>`
qui note chaque exécution (début, fin, résultat, trace en cas d'échec) dans la base :

| Tâche | Timer | Rôle |
|---|---|---|
| `mail-import` | toutes les 5 minutes | import par e-mail (sans objet tant que `IMAP_SERVER` est vide) |
| `backup` | chaque nuit à 3 h 15 | sauvegarde complète (`flask backup create`) |
| `maintenance` | chaque nuit à 4 h 30 | purge le cache de géocodage expiré, les liens de partage expirés, les entrées importées ou ignorées du journal de l'import par e-mail de plus de `MAIL_IMPORT_LOG_DAYS` jours (90) et l'historique des tâches de plus de 14 jours ; relit chez Stripe les abonnements dont la période payée est échue (au cas où un webhook se serait perdu) |

```bash
sudo deploy/systemd/install.sh     # installe et démarre les timers, retire les lignes cron qu'ils remplacent
flask jobs list                    # dernière exécution de chaque tâche
systemctl list-timers 'travellog-*'
journalctl -u 'travellog-job@*'
```

L'onglet « Tâches » de l'administration (`/admin/jobs`) montre la dernière exécution de chaque tâche, signale
les tâches en échec ou en retard (aucun succès depuis deux fois leur intervalle), compte les imports par e-mail
des dernières 24 heures et liste les dernières exécutions avec leur trace. Un timer ne relance jamais une tâche
encore en cours : plus besoin de fichier verrou. Les commandes individuelles restent disponibles pour un usage
manuel (`flask geocode purge [--all]`, `flask purge-share-links`, `flask mail-import --dry-run`…), sans être
notées.

Sauvegardes complètes du serveur (export PostgreSQL + photos, archive `.tar.gz` avec manifeste) :

```bash
flask backup create              # dans BACKUP_DIR (instance/backups par défaut), garde les BACKUP_KEEP plus récentes
flask backup list
flask backup restore instance/backups/travel-backup-AAAAMMJJ-HHMMSS.tar.gz   # application arrêtée
```

L'export (`pg_dump`, format custom) et les nombres de lignes du manifeste viennent du même instantané : la
sauvegarde est cohérente application en marche. La restauration vérifie l'archive (chemins, export lisible),
sauvegarde d'abord l'état actuel, remplace la base en une seule transaction, annulée si les nombres de lignes
diffèrent du manifeste, puis applique les migrations si l'archive est plus ancienne que le code. La sauvegarde nocturne est la tâche
`backup` ci-dessus.

Import par e-mail : réglages IMAP dans `.env` (`IMAP_SERVER`, `IMAP_USERNAME`, `IMAP_PASSWORD`…), relevé par la
tâche `mail-import`.

Premium (Stripe) :

1. Placez la clé secrète dans `.env` (`STRIPE_SECRET_KEY`, `sk_test_…` pour les essais, `sk_live_…` ou une clé
   restreinte `rk_live_…` en production). Une clé restreinte doit avoir l'écriture sur Products, Prices,
   Customers, Checkout Sessions et Subscriptions, et la lecture sur Invoices. Gardez la clé de test dans le
   `.env` d'une copie de développement, jamais à côté de la clé live.
2. Le produit (« Voyage Voyage Premium », code fiscal `STRIPE_TAX_CODE`) et les tarifs sont créés par
   l'application à la première utilisation, d'après `PREMIUM_PRICE_MONTHLY`, `PREMIUM_PRICE_YEARLY` et
   `PREMIUM_CURRENCY`. Un nouveau montant crée un nouveau tarif pour les nouveaux abonnés ; les abonnés
   existants gardent le leur (archivez l'ancien tarif dans Stripe pour qu'il ne serve plus).
3. Dans Stripe, ajoutez un webhook `https://<domaine>/billing/webhook` avec les événements
   `checkout.session.completed`, `customer.subscription.created`, `customer.subscription.updated`,
   `customer.subscription.deleted`, `invoice.paid` et `invoice.payment_failed`, et placez son secret dans
   `STRIPE_WEBHOOK_SECRET`. À chaque événement, l'abonnement est relu chez Stripe : doublons et événements
   dans le désordre sont sans effet. En local : `stripe listen --forward-to localhost:5000/billing/webhook`.
4. Taxes : avec Stripe Managed Payments activé, Stripe est le vendeur et facture la TVA ; désactivé
   (Settings → Managed Payments), les prix sont facturés tels quels. En franchise en base de TVA, ajoutez
   « TVA non applicable, art. 293 B du CGI » au pied des factures (Settings → Billing → Invoices).

Copiez régulièrement `instance/backups` sur une autre machine : une sauvegarde sur le même disque ne protège
pas d'une panne de celui-ci. Chaque utilisateur peut aussi télécharger sa propre sauvegarde (trajets + photos,
`.zip`) depuis ses préférences et la réimporter depuis la page Importer / exporter.

Pour vérifier l'envoi d'e-mails : `flask mail-test vous@example.com`. Sur ce serveur, les e-mails partent de
`no-reply@voyage-voyage.app` par `mail.ransomware.live` (port 587, STARTTLS, authentifié ; mot de passe dans `.env`).

Autres commandes de maintenance :

```bash
flask trips backfill-countries   # renseigne les pays manquants à partir des coordonnées (--force : tout recalculer)
flask trips compute-routes       # calcule les distances routières manquantes (ROUTING_URL requis, 1 requête/s)
flask photos cleanup --dry-run   # liste (puis supprime sans --dry-run) les fichiers photo sans ligne en base
```

Les photos sont stockées dans `instance/uploads` (ou `UPLOAD_FOLDER`) : incluez ce dossier dans vos
sauvegardes, avec la base de données.

### Sécurité

- Limitation de débit (Flask-Limiter) : connexion (par adresse IP et par compte visé, seuls les échecs
  comptent), inscription, demande de réinitialisation, changement de mot de passe et suppression du compte.
  Une réponse 429 traduite est renvoyée au-delà.
- En-têtes : `Content-Security-Policy` avec nonce pour le script en ligne, `X-Frame-Options: DENY`,
  `X-Content-Type-Options`, `Referrer-Policy: strict-origin-when-cross-origin` (le jeton des liens de partage
  ne part pas vers les tuiles ou les CDN), `Permissions-Policy`, et HSTS en HTTPS (`HSTS_MAX_AGE`).
- `tests/test_csp.py` charge les pages principales et vérifie que chaque script, feuille de style et image
  est autorisé par la CSP et que chaque script en ligne porte le nonce : ajoutez l'origine d'une nouvelle
  bibliothèque ou d'un nouveau service dans `app/security.py`, sinon le test échoue.
- Mesure d'audience : Matomo auto-hébergé (`stats.mousqueton.io`, site 13), chargé dans `base.html`. Les
  jetons des liens de partage, d'inscription et de réinitialisation sont masqués avant l'envoi. La
  politique de confidentialité (`/privacy`) le décrit et propose un bouton d'opposition.
- Les fichiers CDN sont chargés avec un hash `integrity` (SRI). Après une mise à jour de version, recalculez
  le hash : `curl -sL URL | openssl dgst -sha384 -binary | openssl base64 -A`.
- L'identifiant de session contient une empreinte du mot de passe : changer ou réinitialiser le mot de passe
  invalide toutes les autres sessions, ainsi que les liens de réinitialisation déjà envoyés.

## Configuration (`.env`)

| Variable | Rôle |
|---|---|
| `SECRET_KEY` | Clé secrète Flask (obligatoire en production) |
| `FLASK_CONFIG` | `development`, `production` ou `testing` |
| `DATABASE_URL` | URL PostgreSQL, obligatoire (`postgresql://utilisateur:motdepasse@hôte:5432/travel`) |
| `TEST_DATABASE_URL` | Base PostgreSQL des tests, vidée par eux (son nom doit se terminer par `_test`) |
| `NOMINATIM_URL` | Point d'accès de recherche Nominatim (instance publique ou auto-hébergée) |
| `NOMINATIM_USER_AGENT` | User-Agent identifiant l'application, **obligatoire** selon la politique Nominatim |
| `NOMINATIM_EMAIL` | Adresse de contact optionnelle (paramètre `email=`) |
| `NOMINATIM_MIN_INTERVAL` | Délai minimal entre deux requêtes, en secondes (1 par défaut) |
| `NOMINATIM_LOCK_FILE` | Fichier verrou partagé entre workers (par défaut `instance/nominatim.lock`) |
| `GEOCODE_CACHE_DAYS` | Durée de validité du cache de géocodage et de la recherche de vols |
| `FLIGHT_LOOKUP_URL`, `FLIGHT_LOOKUP_TIMEOUT` | Recherche de l'itinéraire d'un numéro de vol (adsbdb par défaut ; vide pour désactiver) |
| `MAP_TILE_URL`, `MAP_TILE_URL_DARK` | Tuiles claires et sombres (voir ci-dessous) |
| `MAP_TILE_SUBDOMAINS`, `MAP_TILE_ATTRIBUTION`, `MAP_TILE_MAX_ZOOM` | Options du fournisseur de tuiles |
| `LOGO_DEV_TOKEN` | Clé publiable logo.dev (`pk_…`) : logos des compagnies et opérateurs, cherchés par leur nom, sur `/stats/plane` et `/stats/train` ; aucun logo sans elle |
| `APP_BASE_URL` | Adresse publique, utilisée dans les liens envoyés par e-mail |
| `PROXY_FIX_COUNT` | Nombre de proxys inverses de confiance (`X-Forwarded-*`) |
| `RATELIMIT_STORAGE_URI` | Stockage de la limitation de débit (`memory://`, `redis://…`) |
| `LOGIN_RATE_LIMIT`, `REGISTER_RATE_LIMIT`, `PASSWORD_RESET_RATE_LIMIT` | Plafonds, par ex. `5 per minute;30 per hour` |
| `HSTS_MAX_AGE` | Durée HSTS en secondes (1 an par défaut en production, 0 pour désactiver) |
| `MAIL_SERVER`, `MAIL_PORT`, `MAIL_USE_TLS`, `MAIL_USE_SSL`, `MAIL_USERNAME`, `MAIL_PASSWORD`, `MAIL_FROM` | SMTP pour la réinitialisation du mot de passe |
| `SIGNUP_LINK_MAX_AGE` | Validité du lien magique d'inscription, en secondes (900 = 15 min) |
| `PASSWORD_RESET_MAX_AGE` | Validité du lien de réinitialisation, en secondes (3600) |
| `LOG_LEVEL` | Niveau de journalisation (`INFO` par défaut) |
| `SENTRY_DSN`, `SENTRY_TRACES_SAMPLE_RATE` | Suivi des erreurs Sentry (nécessite `sentry-sdk[flask]`) |
| `UPLOAD_FOLDER` | Dossier des photos (par défaut `instance/uploads`) |
| `IMPORT_FOLDER` | Aperçus d'import en attente de confirmation (par défaut `instance/imports`, une heure) |
| `BACKUP_DIR`, `BACKUP_KEEP` | Dossier des sauvegardes (par défaut `instance/backups`) et nombre d'archives conservées (14) |
| `ROUTING_URL`, `ROUTING_PROFILES`, `ROUTING_TIMEOUT` | Serveur OSRM et modes routés (par défaut `car:driving,bus:driving`) |
| `MAX_PHOTO_MB`, `MAX_UPLOAD_MB`, `MAX_PHOTOS_PER_ITEM` | Limites des photos (15 Mo par photo, 64 Mo par envoi, 30 par trajet ou voyage) |
| `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET` | Clé secrète Stripe et secret de signature du webhook (`whsec_…`) ; sans la clé, le Premium est désactivé |
| `PREMIUM_PRICE_MONTHLY`, `PREMIUM_PRICE_YEARLY`, `PREMIUM_CURRENCY` | Prix du Premium en unités de la devise (`2`, `12`, `eur` par défaut ; `2.50` accepté) |
| `STRIPE_TAX_CODE` | Code fiscal du produit Stripe (`txcd_10103000`, SaaS à usage personnel), exigé par Managed Payments |

### Fond de carte

Par défaut, l'application utilise les tuiles OpenStreetMap standard. En mode sombre, un filtre CSS les
assombrit. Pour des tuiles claires et sombres dédiées (CARTO, Stadia, MapTiler…), renseignez
`MAP_TILE_URL` et `MAP_TILE_URL_DARK` avec l'URL fournie par le service. Ces services demandent en
général une clé API : les tuiles `basemaps.cartocdn.com` sans clé affichent désormais
« API KEY REQUIRED ». Ajoutez l'attribution du fournisseur dans `MAP_TILE_ATTRIBUTION`.

### Géocodage

- Les recherches passent par le serveur (`/api/geocode`), jamais directement du navigateur vers Nominatim.
- Les résultats sont mis en cache dans la table `geocode_cache`, avec une clé `(requête normalisée, langue)`.
- Un fichier verrou (`flock`) garantit au plus une requête par `NOMINATIM_MIN_INTERVAL` secondes pour
  tous les workers d'une même machine. Sur plusieurs machines, chacune applique sa propre limite : utilisez
  alors une instance Nominatim dédiée. Sous Windows, le verrou ne vaut que pour le processus.
- Côté client, la saisie est temporisée (450 ms, 3 caractères minimum).
- La [politique d'utilisation](https://operations.osmfoundation.org/policies/nominatim/) de l'instance
  publique déconseille l'autocomplétion intensive. Pour un usage réel, préférez une instance auto-hébergée
  ou un service commercial compatible, via `NOMINATIM_URL`.
- Si l'utilisateur valide un lieu sans choisir de suggestion, le serveur géocode le texte saisi.

## Structure

```
app/
  __init__.py        application factory, gestion des erreurs
  extensions.py      db, migrate, login, csrf, babel
  models.py          User, Trip, GeocodeCache (contraintes CHECK, index)
  i18n.py            sélection de la langue, formatage, chaînes JS
  geo.py             haversine, client Nominatim et cache
  security.py        en-têtes de sécurité (CSP avec nonce, HSTS…)
  airports.py        aéroports par code IATA ou OACI, compagnies par code OACI ou IATA
  flights.py         itinéraire d'un numéro de vol (adsbdb, en cache)
  carriers.py        suggestions de compagnies, d'opérateurs et d'appareils
  pwa.py             service worker et page hors ligne
  assets.py          fichiers statiques versionnés (?v=empreinte) et import map des modules JS
  countries.py       pays : recherche hors ligne, noms localisés, drapeaux, surfaces
  photos.py          photos : validation et ré-encodage (Pillow), miniatures, fichiers
  data/              contours des pays (Natural Earth), aéroports (OurAirports), police Inter (SIL OFL) pour l'image du bilan
  ics.py             agenda iCalendar
  routing.py         distances d'itinéraire (OSRM)
  tags.py            étiquettes
  backup.py          sauvegarde et restauration du serveur
  trips/absences.py  jours d'absence ; trips/badges.py badges et continents ; trips/places.py lieux visités
  review_image.py    image du bilan annuel (Pillow)
  mail.py            envoi d'e-mails SMTP
  transport.py       modes de transport (libellé, icône, couleurs)
  cli.py             flask seed, flask translate …
  auth/ trips/ api/ main/ share/ admin/ transfer/ support/ billing/   blueprints (transfer : import / export) ; support : tickets ; billing : abonnement Premium avec Stripe
  templates/  static/  translations/
migrations/          Alembic (Flask-Migrate)
tests/               pytest
config.py  run.py  babel.cfg  Makefile  requirements.txt  .env.example
```

## API JSON

Toutes les routes exigent une session (sinon 401 en JSON). Les messages d'erreur sont traduits.

| Route | Description |
|---|---|
| `GET /api/trips` | Voyages de l'utilisateur. Filtres : `from`, `to` (AAAA-MM-JJ, sur la date de départ), `modes=plane,train`, `kind=all\|oneway\|round` |
| `GET /api/stats` | Mêmes filtres : nombre, distance totale, répartition par mode (valeurs brutes et formatées) |
| Filtres communs | `when=all\|past\|upcoming`, `tags=1,4` (identifiants d'étiquettes, au moins une), `q=…` (recherche) |
| `GET /api/places` | Mêmes filtres : lieux visités `{name, lat, lon, visits, country}` |
| `GET /api/countries` | Mêmes filtres : pays visités en GeoJSON (contours, nom localisé, drapeau, nombre de trajets) |
| `GET /api/geocode?q=…&lang=…` | Suggestions de lieux `{name, label, lat, lon, type, country_code}` |

Les liens de partage ont les équivalents `/api/shared/<jeton>/trips`, `/stats` et `/countries`.

### Pays et CO₂

- Les contours des pays viennent de [Natural Earth](https://www.naturalearthdata.com/) au 1:50m (domaine
  public), simplifiés dans `app/data/countries.geojson` (237 pays et territoires). Un point côtier qui tombe
  juste hors du tracé est rattaché au pays le plus proche dans un rayon de 25 km.
- Les noms de pays sont localisés par Babel (CLDR).
- Les aéroports (9 227 ayant un code IATA, avec leur code OACI) sont dans `app/data/airports.csv`. Ils viennent
  d'[OurAirports](https://ourairports.com/data/) (domaine public), complété par
  [OpenFlights](https://openflights.org/data.php) (licence [ODbL](https://opendatacommons.org/licenses/odbl/1-0/))
  pour 174 aéroports fermés dont OurAirports a retiré le code (Berlin-Tegel, Schönefeld…), qui figurent pourtant
  dans les historiques de vols. Ce fichier est donc diffusé sous ODbL. Les compagnies (1 026 en activité,
  code OACI, code IATA et nom) viennent aussi d'OpenFlights, dans `app/data/airlines.csv` (ODbL) ; une
  compagnie disparue garde son code, son code OACI ayant pu être réattribué. Mise à jour des deux fichiers :
  `.venv/bin/python scripts/make_flight_data.py`.
- Les contours du globe (`app/static/data/world.json`, simplifiés depuis `app/data/countries.geojson`) viennent
  de `scripts/make_globe_data.py`. Les régions des grands pays (`app/data/regions.json`) viennent des
  subdivisions Natural Earth 1:10m (domaine public), simplifiées et regroupées par
  `scripts/make_region_data.py` (la source de 40 Mo est téléchargée si elle n'est pas fournie).
- Le CO₂ est une estimation par voyageur : distance à vol d'oiseau × facteur moyen de l'ADEME (Base Carbone),
  défini dans `app/transport.py` (`CO2_KG_PER_KM`, `PLANE_CO2_BANDS`). Avion : 258, 187 ou 152 g/km selon
  la distance du vol, traînées comprises ; train et autocar 30 g/km ; voiture 218 g/km (une personne à bord) ;
  ferry 120 g/km ; vélo et marche 0.

## Tests

```bash
make test               # ou : pytest
```

Les tests utilisent leur propre base PostgreSQL, `TEST_DATABASE_URL` (son nom doit se terminer par `_test` ; elle
est vidée après chaque test), par exemple `sudo docker exec travellog-postgres createdb -U travel travel_test`.

La suite couvre les modèles et contraintes, la validation aller-retour, l'isolation entre utilisateurs,
l'API (filtres, statistiques, géocodage simulé, cache, limite de débit), l'authentification, la protection
CSRF, la conformité de chaque page à la CSP et l'i18n. Pour l'i18n, elle vérifie la détection de la langue, le changement de langue, le
formatage des dates et distances, l'absence de clé manquante, non traduite ou fuzzy dans chaque `.po`
(comparaison avec une extraction à jour du code), la cohérence des variables `%(x)s` et l'absence
de texte en dur dans le JavaScript. Les tests ne font aucun appel réseau.

## Internationalisation

- Ordre de détection de la langue : profil de l'utilisateur, puis cookie `lang`, puis en-tête
  `Accept-Language`, puis français.
- Les chaînes sources sont en français : `_()` dans les templates, `gettext` / `lazy_gettext` (`_l`)
  en Python.
- Les textes JavaScript sont injectés dans `base.html` (`<script type="application/json" id="i18n-data">`)
  par `app/i18n.py:js_strings()`. Les fichiers JS ne contiennent que des clés.
- Dates, nombres et distances sont formatés par Babel côté serveur. Le JSON de l'API renvoie à la fois
  les valeurs brutes et les valeurs formatées.

### Workflow de traduction

```bash
flask translate extract     # make extract  : code -> app/translations/messages.pot
flask translate update      # make update   : extract + fusion dans chaque .po
# … traduire les nouvelles entrées dans app/translations/<langue>/LC_MESSAGES/messages.po
flask translate compile     # make compile  : .po -> .mo
pytest tests/test_i18n.py   # vérifie qu'aucune traduction ne manque
```

Ces commandes appellent `pybabel extract -F babel.cfg -k _l -k lazy_gettext`, `pybabel update` et
`pybabel compile`. Les fichiers `.mo` sont générés et ne sont pas versionnés.

### Ajouter une langue

1. Déclarez-la dans `LANGUAGES` (`app/i18n.py`), par exemple `"pt": {"name": "Português"}`.
2. Créez le catalogue : `flask translate init pt` (ou `make init-lang LOCALE=pt`).
3. Traduisez `app/translations/pt/LC_MESSAGES/messages.po`.
4. Compilez : `flask translate compile`.
5. Lancez `pytest` : les tests i18n prennent automatiquement en compte la nouvelle langue et signalent
   toute chaîne manquante.

Les formats de date et de nombre viennent de Babel (CLDR), et les messages intégrés de WTForms ont leurs
propres traductions : aucune autre étape n'est nécessaire.
