# Voyage Voyage — les fonctionnalités en détail

*English version: [FEATURES.md](FEATURES.md) · Retour au [README](README_FR.md)*

- Abonnement Premium (`/billing`, « Premium » dans le menu du compte), payé avec Stripe : 2 € par mois ou 12 €
  par an par défaut (prix dans `.env`). L'ajout de photos, l'import par e-mail, les liens de partage, le profil
  public et le support sont des fonctions Premium, signalées partout par un diamant (menu, pages, pages
  À propos et d'accueil). Un e-mail envoyé par un compte sans Premium n'est pas importé : l'expéditeur
  reçoit une réponse qui l'explique, avec un lien pour s'abonner.
  À la fin du Premium, liens de partage et profil public ne sont plus servis (les visiteurs obtiennent une
  404) mais sont conservés, et fonctionnent de nouveau avec un nouvel abonnement ; on peut toujours les
  révoquer ou les retirer. Le
  paiement se fait sur la page hébergée de Stripe (Checkout) ; l'abonné voit ensuite ses factures
  (`/billing/invoices`, avec la facture en ligne et son PDF, et un bouton « Payer » pour une facture
  impayée) et peut arrêter l'abonnement, qui prend alors fin à l'échéance de la période payée sans nouveau
  prélèvement, ou le reprendre d'ici là. Un paiement refusé laisse l'accès le temps que Stripe réessaie. Les
  administrateurs peuvent offrir le Premium (bouton en forme de diamant dans l'onglet des utilisateurs). La
  suppression d'un compte supprime son client Stripe, ce qui résilie aussitôt l'abonnement. Sans
  `STRIPE_SECRET_KEY`, la fonction est désactivée et rien n'est réservé.
- Support (Premium ; `/support`, dans le menu du compte) : les utilisateurs connectés ouvrent un ticket (sujet et message)
  et suivent l'échange, qui peut compter autant d'allers-retours que nécessaire ; ils peuvent le fermer, et
  y répondre le rouvre. Les administrateurs ont un onglet « Tickets » (`/admin/tickets` : à traiter / répondus /
  fermés, avec un compteur des tickets en attente), répondent, ferment ou rouvrent. Chaque message d'un
  utilisateur part par e-mail aux administrateurs, chaque réponse à l'utilisateur, dans sa langue. Les e-mails sont facultatifs :
  l'utilisateur choisit pour chaque ticket (à l'ouverture, puis sur sa page), et chaque administrateur peut couper
  les e-mails des tickets depuis l'onglet Tickets.
- Page À propos (`/about`, en lien depuis l'accueil et le pied de page) : pourquoi le site s'appelle Voyage Voyage
  (clin d'œil à la chanson de Desireless, merci à Mallorie pour l'idée) et le détail de toutes les fonctionnalités.
- Comptes utilisateurs (inscription, connexion, mots de passe hachés). Chacun ne voit que ses voyages.
  Inscription par lien magique quand l'envoi d'e-mails est configuré : la personne saisit son adresse, reçoit
  un lien valable 15 minutes (`SIGNUP_LINK_MAX_AGE`) et à usage unique, puis choisit son mot de passe ; le
  compte n'est créé qu'à cette étape (l'adresse est donc vérifiée). Si l'adresse a déjà un compte, l'e-mail
  invite à se connecter, et la page affichée est la même dans les deux cas. Sans serveur d'e-mail,
  l'inscription reste directe avec mot de passe.
  Depuis ses préférences, chacun peut changer son mot de passe (ce qui déconnecte ses autres sessions)
  ou supprimer son compte. Mot de passe oublié : lien de réinitialisation par e-mail, à usage unique.
- Liens de partage en lecture seule (Premium), avec expiration facultative et date de dernière consultation. Le
  visiteur a son propre menu : Carte, Statistiques (depuis le début, une carte par année, badges), Voyages
  (liste regroupée par voyage, si le lien le prévoit) et Bilan. Les voyages à venir sont masqués par défaut
  (ils révèlent quand vous êtes absent) ; une option par lien les montre, estompés et signalés. Ni notes, ni
  photos, ni domicile.
- Profil public (Premium ; `/u/<nom>`) : depuis les préférences, chacun peut choisir un nom (3 à 30 lettres minuscules,
  chiffres, `-` ou `_`) pour publier un résumé de ses voyages passés : chiffres clés (voyages, distance, pays,
  continents, part des terres émergées), distance par mode, pays visités par continent et badges obtenus. Ni
  trajets, ni dates, ni notes, ni photos, ni domicile, ni voyages à venir ; la page n'est pas indexée par les
  moteurs de recherche (`noindex`). Vider le nom désactive le profil.
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
- Notes et photos sur chaque trajet et chaque voyage (fiche détaillée) ; l'ajout de photos est une fonction
  Premium, et les photos déjà ajoutées restent visibles et supprimables après la fin de l'abonnement. Les photos sont ré-encodées en JPEG,
  sans métadonnées EXIF dans le fichier conservé, avec une miniature. Appareil, réglages, date de prise de vue
  et position GPS sont relevés à l'envoi, gardés en base et affichés au seul propriétaire sur la page de la
  photo (`/photos/<id>`), avec une petite carte. Elles restent privées : les liens de
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
- Import par e-mail (Premium) : l'utilisateur transfère ses confirmations de vol ou de train à l'adresse d'import
  (`IMPORT_ADDRESS`, indiquée sur la page d'import) depuis l'adresse de son compte. `flask mail-import`, lancé
  toutes les 5 minutes par un timer systemd, relève la boîte IMAP : l'expéditeur doit être un compte et l'e-mail porter
  une signature DKIM valide du domaine de l'expéditeur (sinon n'importe qui pourrait usurper l'adresse From).
  Les trajets sont lus dans les données schema.org (JSON-LD) que la plupart des compagnies et agences
  ajoutent (vols, trains, bus, bateaux), puis dans les cartes d'embarquement Apple Wallet jointes (`.pkpass`,
  voir plus bas), sinon dans le texte (numéro de vol, codes d'aéroports, date en cinq langues) ; un vol et son retour deviennent un aller-retour. L'e-mail est alors supprimé de la boîte. Si rien
  n'est reconnu, un ticket est ouvert au nom du compte « Import Error » (`MAIL_IMPORT_ERROR_EMAIL`, qui ne
  peut pas se connecter) avec l'e-mail brut, et l'e-mail reste dans la boîte. Chaque e-mail est noté dans
  `mail_imports` : il n'est traité (et son ticket ouvert) qu'une fois. Les e-mails d'expéditeurs inconnus ou
  non authentifiés sont ignorés et laissés. `--dry-run` montre ce qui serait importé sans rien écrire ni
  supprimer.
  Supprimer un compte supprime aussi ses entrées du journal d'import et les tickets d'erreur qui contiennent ses
  e-mails bruts.
  Chaque utilisateur peut aussi autoriser d'autres adresses d'expédition (Préférences → Import par e-mail) :
  une adresse n'est ajoutée qu'après confirmation par un lien magique qui lui est envoyé, elle ne permet
  jamais de se connecter, et ne peut être ni l'adresse d'un compte ni l'adresse d'import d'un autre
  utilisateur ; l'inscription avec une adresse d'import est refusée.
- Import / export (`/import-export`) en CSV, GeoJSON et GPX. Les trois formats contiennent les mêmes champs
  (dont notes et regroupements en voyages) et se réimportent sans perte : c'est aussi une sauvegarde, hors
  photos. À l'import, un aperçu liste les trajets lus : décochez ceux à écarter (boutons tout / rien / par
  année) avant de confirmer ; les trajets déjà présents sont décochés et ignorés. Un fichier contenant une
  erreur n'importe rien (les erreurs sont listées avec leur numéro de ligne). Une sauvegarde complète (.zip)
  est restaurée directement, photos comprises.
- Cartes d'embarquement Apple Wallet (`.pkpass`, ou `.pkpasses` qui en regroupe plusieurs), jointes à un e-mail
  d'import ou envoyées depuis la page Importer / exporter (`app/mail_import/wallet.py`) : une carte aérienne est
  lue dans son code-barres (format IATA BCBP : aéroports, compagnie, numéro et jour de chacun de ses vols), sinon
  dans ses données « semantics » ou ses champs affichés (codes d'aéroports, numéro de vol, date de la carte) ;
  une carte de train, de bus ou de bateau dans ses données « semantics » (gares et leurs coordonnées, numéro,
  opérateur). Les autres cartes (événements, fidélité) sont ignorées. La signature de la carte n'est pas
  vérifiée : l'e-mail qui la porte est authentifié (DKIM), et un fichier envoyé passe par l'aperçu de l'import.
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
