# Voyage Voyage

*English version: [README.md](README.md)*

**Votre carnet de voyages, sur une carte.** Notez chaque trajet en avion, train, voiture, bus, bateau,
vélo ou à pied, retrouvez-les sur une carte du monde ou un globe 3D, et vos années de voyage deviennent
des statistiques, des badges et un bilan de l'année. En français, anglais, espagnol, allemand et italien.

🌍 **En ligne :** <https://voyage-voyage.app>

![Carte des trajets](.github/screenshots/map.png)

| | |
|---|---|
| ![Statistiques](.github/screenshots/stats.png) | ![Bilan de l'année](.github/screenshots/review.png) |
| **Statistiques** | **Bilan de l'année** |
| ![Mes voyages](.github/screenshots/trips.png) | ![Thème sombre](.github/screenshots/map-dark.png) |
| **Mes voyages** | **Thème sombre** |
| ![Gratuit ou Premium](.github/screenshots/plans.png) | <img src=".github/screenshots/mobile.png" alt="Sur téléphone" width="300"> |
| **Gratuit ou Premium** | **Sur téléphone** |

## Fonctionnalités

- **Carte et globe** : trajets colorés par mode, arcs géodésiques pour l'avion, retours en pointillés,
  marqueurs regroupés, couches « Pays visités » et « Lieux visités », globe 3D et rejeu chronologique.
- **Statistiques** : chiffres clés et graphiques par année et par mode, une page par année avec un
  calendrier jour par jour, pages avion et train (compagnies, appareils, aéroports, gares), CO₂ estimé,
  jours loin de la maison.
- **Le monde, pays par pays** : pays et territoires visités sur 237, continents, régions de 14 grands
  pays, et badges pour l'ensemble de vos voyages et pour chaque année.
- **Bilan de l'année** : votre année en chiffres, et une image à partager.
- **Import et export** : historiques Flighty et myFlightradar24, CSV, GeoJSON et GPX sans perte, cartes
  d'embarquement Apple Wallet, recherche par numéro de vol, sauvegarde complète avec les photos.
- **Notes, photos et étiquettes** sur chaque trajet et chaque voyage ; voyages à venir et export vers
  l'agenda (`.ics`).
- **Partage** : liens en lecture seule avec date d'expiration, et profil public facultatif.
- **Partout** : application installable qui fonctionne hors ligne, thèmes clair et sombre.
- **Respect de la vie privée** : sans publicité, toutes les bibliothèques servies par le site (aucun CDN),
  mesure d'audience auto-hébergée et refusable, export et suppression du compte à tout moment.
- **Premium** (Stripe, 2 € par mois ou 12 € par an par défaut) : photos, import par e-mail, liens de
  partage, profil public et support. Sans clé Stripe, tout est gratuit.

Toutes les fonctionnalités en détail : [FEATURES_FR.md](FEATURES_FR.md).

## Démarrage rapide

```bash
git clone https://github.com/JMousqueton/travellog.git && cd travellog
make install && cp .env.example .env     # puis renseignez SECRET_KEY, NOMINATIM_USER_AGENT et DATABASE_URL
.venv/bin/flask db upgrade
.venv/bin/flask seed                      # facultatif : demo@example.com / demo1234
.venv/bin/flask run --debug               # http://127.0.0.1:5000
```

Prérequis, production, tâches périodiques, sauvegardes, Stripe, configuration, API, tests et traductions :
[INSTALL_FR.md](INSTALL_FR.md).

## Technologies

Python et Flask, PostgreSQL, Leaflet, d3-geo, Chart.js, Bootstrap, Font Awesome et la police Inter,
tous servis par l'application elle-même.

## Licence

[MIT](LICENSE). Les sources de données et leurs licences (Natural Earth, OurAirports, OpenFlights) sont
détaillées dans [INSTALL_FR.md](INSTALL_FR.md).

Voyage Voyage a été codé avec l'aide de l'IA.
