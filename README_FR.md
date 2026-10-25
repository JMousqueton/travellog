# Carnet de voyages

*English version: [README.md](README.md)*

Application web Flask pour suivre ses voyages sur une carte : trajets colorés par mode de transport,
arcs géodésiques pour l'avion, retours en pointillés, filtres, statistiques, thème clair/sombre,
et interface disponible en français, anglais, espagnol, allemand et italien.

## Fonctionnalités

- Comptes utilisateurs (inscription, connexion, mots de passe hachés). Chacun ne voit que ses voyages.
  Inscription par lien magique quand l'envoi d'e-mails est configuré : la personne saisit son adresse, reçoit
  un lien valable 15 minutes (`SIGNUP_LINK_MAX_AGE`) et à usage unique, puis choisit son mot de passe ; le
  compte n'est créé qu'à cette étape (l'adresse est donc vérifiée). Si l'adresse a déjà un compte, l'e-mail
  invite à se connecter, et la page affichée est la même dans les deux cas. Sans serveur d'e-mail,
  l'inscription reste directe avec mot de passe.
  Depuis ses préférences, chacun peut changer son mot de passe (ce qui déconnecte ses autres sessions)
  ou supprimer son compte. Mot de passe oublié : lien de réinitialisation par e-mail, à usage unique.
- Liens de partage en lecture seule, avec expiration facultative et date de dernière consultation. Le
  visiteur a son propre menu : Carte, Statistiques (depuis le début, une carte par année, badges), Voyages
  (liste regroupée par voyage, si le lien le prévoit) et Bilan. Les voyages à venir sont masqués par défaut
  (ils révèlent quand vous êtes absent) ; une option par lien les montre, estompés et signalés. Ni notes, ni
  photos, ni domicile.
- Pays : chaque trajet connaît son pays de départ et d'arrivée (code ISO renvoyé par Nominatim, ou déduit
  des coordonnées hors ligne). Couche « Pays visités » sur la carte, drapeaux dans la liste et les fiches.
- Statistiques (`/stats`) : vue d'ensemble de tous les voyages (chiffres clés, graphiques des trajets et de la
  distance par année et par mode avec Chart.js, une carte par année, badges, avion et train, pays, lieux,
  continents, régions, jours d'absence, émissions de CO₂ par mode). Chaque année a sa page
  (`/stats/<année>`) : chiffres et évolution par rapport à l'année précédente (à la même date pour l'année en
  cours), calendrier de l'année façon GitHub (une case par jour : jour de voyage, loin de chez moi, à la
  maison, prévu), départs par mois, distance par mode, pays visités (nouveaux signalés), faits marquants,
  badges de l'année, avion et train, étiquettes. Les jours loin de chez soi du calendrier viennent du
  domicile s'il est défini, sinon des allers-retours.
- Notes et photos sur chaque trajet et chaque voyage (fiche détaillée). Les photos sont ré-encodées en JPEG,
  sans métadonnées EXIF (donc sans position GPS), avec une miniature. Elles restent privées : les liens de
  partage n'affichent ni notes ni photos.
- Voyages à venir : badge « Dans 12 jours », « Demain » ou « En cours », trajets estompés sur la carte,
  filtre passés / à venir, carte « Prochain départ » dans le tableau de bord. Les statistiques ne comptent que
  les voyages déjà commencés.
- Agenda : export `.ics` d'un trajet ou d'un voyage, et abonnement (Google Agenda, Apple Calendrier,
  Outlook…) par une adresse secrète à activer, changer ou désactiver dans les préférences. Les notes ne sont
  pas transmises.
- Distances : itinéraire routier calculé par un serveur OSRM si `ROUTING_URL` est défini (voiture et bus par
  défaut), sinon distance à vol d'oiseau × facteur de détour par mode (`DETOUR_FACTORS` dans
  `app/transport.py` : route ×1,3, train ×1,25, bateau ×1,1, avion en ligne directe). La fiche indique
  l'origine de la distance.
- Étiquettes (vacances, travail…) : saisie libre avec suggestions, filtre sur la carte, statistiques par
  étiquette (dont le CO₂ de l'année en cours), incluses dans les exports. Les étiquettes d'un voyage
  s'appliquent à tous ses trajets ; une étiquette qui n'est plus utilisée disparaît.
- Recherche dans « Mes voyages », insensible à la casse et aux accents : lieux, pays, notes, étiquettes,
  nom et notes du voyage. Boutons d'année (Tout, 2026, 2025…), conservés avec la recherche et le tri.
- Bilan de l'année (`/review`) : chiffres clés, pays découverts, trajet le plus long, destinations favorites,
  départs par mois, et image PNG 1080 × 1350 à télécharger ou partager (feuille de partage du système sur
  mobile). Les détenteurs d'un lien de partage voient le bilan de l'année en cours seulement (et celui de
  l'année écoulée en janvier et février), sans bouton de téléchargement ni de partage
  (`/s/<jeton>/review`).
- Jours d'absence (domicile à définir dans les préférences) : jours passés hors du domicile (rayon de 30 km),
  nuits à l'étranger, part de l'année, plus longue absence. Les allers simples s'enchaînent ; une absence
  commencée ailleurs s'arrête au retour dans cette ville ; un trajet qui ne part pas du dernier lieu atteint
  clôt l'absence en cours (déplacement non saisi). Le domicile n'apparaît jamais sur les liens de partage.
- Couverture du monde : pays et territoires visités sur les 237 de Natural Earth (et part des terres
  émergées), pays visités par continent avec une barre de progression, et régions visitées dans 14 grands
  pays (États américains, mexicains, brésiliens et indiens, provinces canadiennes, États australiens, Länder,
  cantons suisses, préfectures japonaises, provinces chinoises, régions françaises, espagnoles et italiennes,
  nations du Royaume-Uni), trouvées hors ligne d'après les extrémités des trajets (`app/regions.py`).
- Continents et badges (pays, continents, distance, nombre de voyages, modes…), datés du trajet qui a fait
  franchir le palier, avec la progression des badges restants. Deux séries : les badges de tous vos voyages
  (vue d'ensemble des statistiques), et ceux de chaque année (page de l'année), aux paliers adaptés à une
  année (12 voyages, 10 000 km, 3 continents…). Les badges obtenus dans l'année figurent dans
  le bilan.
- Lieux visités : extrémités des trajets regroupées dans un rayon de 15 km, liste et couche « Lieux visités »
  sur la carte (cercles proportionnels au nombre de trajets).
- Rejouer : sur la carte, les trajets se dessinent dans l'ordre chronologique (aller à la date de départ,
  retour à la date de retour) ; un curseur avec les années permet de se placer à n'importe quelle date.
- Globe : un bouton « Carte / Globe » sur la carte affiche les mêmes trajets sur un globe en 3D (projection
  orthographique d3-geo sur un canevas, sans WebGL) : les vols forment des arcs au-dessus de la surface, les
  pays visités sont colorés, le globe tourne seul jusqu'au premier geste et se fait glisser, zoomer (molette,
  pincement, boutons) et tourner avec les flèches du clavier. Cliquer sur un trajet (sur le globe ou dans la
  liste) tourne le globe vers lui et affiche sa fiche ; la relecture fonctionne aussi sur le globe. Le choix
  est mémorisé dans le navigateur.
- Import / export (`/import-export`) en CSV, GeoJSON et GPX. Les trois formats contiennent les mêmes champs
  (dont notes et regroupements en voyages) et se réimportent sans perte : c'est aussi une sauvegarde, hors
  photos. À l'import, un aperçu liste les trajets lus : décochez ceux à écarter (boutons tout / rien / par
  année) avant de confirmer ; les trajets déjà présents sont décochés et ignorés. Un fichier contenant une
  erreur n'importe rien (les erreurs sont listées avec leur numéro de ligne). Une sauvegarde complète (.zip)
  est restaurée directement, photos comprises.
- Import d'historiques de vols : les exports CSV de Flighty et de myFlightradar24 sont reconnus
  automatiquement. Chaque vol devient un trajet en avion entre les deux aéroports (vols annulés ignorés,
  aéroport de déroutement pris comme arrivée, date américaine M/J/AA ou
  JJ/MM/AAAA reconnue d'après le fichier). La compagnie (nom retrouvé d'après son code OACI), le numéro de vol
  (« AF1148 ») et l'appareil vont dans les champs du trajet ; les vols annulés sont listés dans l'aperçu.
  Un vol suivi de son vol retour (à 50 km près : CDG à l'aller, ORY au retour) devient un trajet
  aller-retour ; les circuits restent en vols simples, et un retour annulé ou absent ne fausse pas les suivants.
- Avion et train : compagnie, numéro de vol et appareil pour l'avion, opérateur pour le train, saisis
  dans le formulaire (libellés selon le mode ; la compagnie se complète automatiquement, avec d'abord celles
  déjà saisies puis les principales compagnies aériennes ou ferroviaires de `app/carriers.py`) ou remplis par
  l'import des vols. L'appareil se complète aussi (appareils déjà saisis, puis principaux modèles). Saisir un
  numéro de vol (« AF1148 ») remplit la compagnie, le départ et l'arrivée s'ils sont vides : la compagnie
  d'après le préfixe (hors ligne), l'itinéraire habituel du numéro d'après le service gratuit
  [adsbdb](https://www.adsbdb.com), interrogé par le serveur et gardé en cache (`/api/flight`,
  `app/flights.py` ; `FLIGHT_LOOKUP_URL` vide pour désactiver). C'est l'itinéraire d'aujourd'hui : à vérifier
  pour un vol ancien. Les statistiques en tirent, pour chaque mode, le nombre de vols ou de trajets et les
  compagnies, appareils et aéroports ou gares les plus fréquents (un aller-retour « AF1148 / AF1549 » compte
  pour deux), avec une page de détail (`/stats/plane`, `/stats/train`, filtrable par année) : part de chaque
  compagnie, premier et dernier vol, constructeurs, lignes les plus fréquentes.
- Voyages : origine, destination, date, mode de transport (avion, train, voiture, bus, bateau, vélo, à pied),
  option aller-retour avec date de retour obligatoire et postérieure ou égale au départ.
- Formulaire avec autocomplétion des lieux (Nominatim, géocodage côté serveur avec cache en base).
- Carte Leaflet plein écran : marqueurs regroupés (markercluster), popups localisées, légende.
- Panneau latéral (tiroir sur mobile) : boutons d'année (Tout, 2026, 2025…) qui remplissent la période,
  tableau de bord de l'année choisie (l'année en cours avec « Tout »), filtres (période, modes, type), liste
  triable synchronisée avec la carte. Les filtres sont conservés dans l'URL.
- Thème clair/sombre (préférence enregistrée et détection de `prefers-color-scheme`).
- Application installable et consultable hors ligne : un service worker (`/sw.js`, `app/pwa.py`) garde les
  fichiers statiques et les bibliothèques en cache, et la dernière version des pages et des données déjà
  ouvertes (carte, liste, statistiques, fiches). Les tuiles de la carte ne sont pas gardées : hors ligne, la
  carte montre les trajets sans fond de carte (le globe, lui, reste complet). Les pages du compte sont
  effacées du cache à la déconnexion.
- Page 404 en forme de passeport : couverture en marbre, carte du monde (générée depuis les contours Natural
  Earth par `scripts/make_world_svg.py`), avion et tampon « 404 · Destination introuvable ».
- Internationalisation complète avec Flask-Babel. Dates, nombres et distances sont formatés selon la langue.

## Prérequis

- Python 3.11 ou plus récent
- Un accès réseau aux CDN (Bootstrap, Font Awesome, Chart.js, Google Fonts), aux tuiles de carte, à Nominatim
  et, pour la recherche par numéro de vol, à adsbdb. Leaflet, MarkerCluster, d3-geo et d3-array sont fournis dans
  `app/static/vendor/`.

## Installation

```bash
git clone https://github.com/JMousqueton/travellog.git && cd travellog
make install            # ou : python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env    # puis renseignez SECRET_KEY et NOMINATIM_USER_AGENT
source .venv/bin/activate
flask translate compile # compile les .po en .mo (déjà fait par make install)
flask db upgrade        # crée instance/travel.db
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

### Production sur ce serveur (travellog.julien.io)

- Service systemd `travellog` (copie dans `deploy/travellog.service`) : gunicorn, 1 worker et 8 fils
  d'exécution sur `127.0.0.1:5012`, avec `FLASK_CONFIG=production`, `APP_BASE_URL=https://travellog.julien.io`
  et `PROXY_FIX_COUNT=1` (le reste vient de `.env`). `sudo systemctl restart travellog` après une mise à jour
  du code ; journal : `journalctl -u travellog`.
- nginx : `deploy/nginx/travellog.julien.io.conf` (HTTPS, fichiers statiques servis directement, 64 Mo par
  envoi). Les adresses des fichiers statiques portent l'empreinte de leur contenu (`?v=…`, voir
  `app/assets.py`) : nginx les met en cache un an, et un fichier modifié change d'adresse. Tant que le certificat n'existe pas, une configuration transitoire ne fait que la validation
  Let's Encrypt et la redirection vers HTTPS.
- Certificat : une fois le DNS en place (A `213.32.17.149`, AAAA `2001:41d0:305:2100::1:1c4b`), lancer
  `deploy/enable-https.sh`. Le renouvellement est assuré par `certbot.timer`.
- Mise à jour : `git pull`, `.venv/bin/pip install -r requirements.txt`, `flask backup create`,
  `flask db upgrade`, `flask translate compile`, puis `sudo systemctl restart travellog`.

Derrière un proxy inverse, définissez `PROXY_FIX_COUNT` (sinon la limitation de débit voit l'adresse du
proxy pour tout le monde) et `APP_BASE_URL`. Avec plusieurs workers, donnez à la limitation de débit un
stockage partagé (`RATELIMIT_STORAGE_URI=redis://…`).

Tâches périodiques conseillées (cron) :

```bash
flask geocode purge        # supprime les entrées expirées du cache de géocodage (--all : tout)
flask purge-share-links    # supprime les liens de partage expirés
```

Sauvegardes complètes du serveur (base SQLite + photos, archive `.tar.gz` avec manifeste) :

```bash
flask backup create              # dans BACKUP_DIR (instance/backups par défaut), garde les BACKUP_KEEP plus récentes
flask backup list
flask backup restore instance/backups/travel-backup-AAAAMMJJ-HHMMSS.tar.gz   # application arrêtée
```

La restauration vérifie l'archive (chemins, intégrité SQLite, manifeste), sauvegarde d'abord l'état actuel,
puis applique les migrations si l'archive est plus ancienne que le code. Exemple de tâche nocturne (cron) :

```
15 3 * * * cd /opt/travel && .venv/bin/flask backup create >> instance/backups/backup.log 2>&1
```

Copiez régulièrement `instance/backups` sur une autre machine : une sauvegarde sur le même disque ne protège
pas d'une panne de celui-ci. Chaque utilisateur peut aussi télécharger sa propre sauvegarde (trajets + photos,
`.zip`) depuis ses préférences et la réimporter depuis la page Importer / exporter.

Pour vérifier l'envoi d'e-mails : `flask mail-test vous@example.com`. Sur ce serveur, les e-mails partent par
le Postfix local (`MAIL_SERVER=localhost`, port 25, sans authentification), comme pour Yet-Another-Blog.

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
| `DATABASE_URL` | URL SQLAlchemy (par défaut `instance/travel.db`) |
| `NOMINATIM_URL` | Point d'accès de recherche Nominatim (instance publique ou auto-hébergée) |
| `NOMINATIM_USER_AGENT` | User-Agent identifiant l'application, **obligatoire** selon la politique Nominatim |
| `NOMINATIM_EMAIL` | Adresse de contact optionnelle (paramètre `email=`) |
| `NOMINATIM_MIN_INTERVAL` | Délai minimal entre deux requêtes, en secondes (1 par défaut) |
| `NOMINATIM_LOCK_FILE` | Fichier verrou partagé entre workers (par défaut `instance/nominatim.lock`) |
| `GEOCODE_CACHE_DAYS` | Durée de validité du cache de géocodage et de la recherche de vols |
| `FLIGHT_LOOKUP_URL`, `FLIGHT_LOOKUP_TIMEOUT` | Recherche de l'itinéraire d'un numéro de vol (adsbdb par défaut ; vide pour désactiver) |
| `MAP_TILE_URL`, `MAP_TILE_URL_DARK` | Tuiles claires et sombres (voir ci-dessous) |
| `MAP_TILE_SUBDOMAINS`, `MAP_TILE_ATTRIBUTION`, `MAP_TILE_MAX_ZOOM` | Options du fournisseur de tuiles |
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
  auth/ trips/ api/ main/ share/ admin/ transfer/   blueprints (transfer : import / export)
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
