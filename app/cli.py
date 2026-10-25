import os
import subprocess
import sys
import time
from datetime import date

import click

from .extensions import db

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
TRANSLATIONS = os.path.join(ROOT, "app", "translations")
POT = os.path.join(TRANSLATIONS, "messages.pot")

DEMO_EMAIL = "demo@example.com"
DEMO_PASSWORD = "demo1234"

# (origine, lat, lon, destination, lat, lon, départ, mode, retour)
DEMO_TRIPS = [
    ("Paris, France", 48.8566, 2.3522, "New York, États-Unis", 40.7128, -74.0060, date(2025, 4, 12), "plane", date(2025, 4, 26)),
    ("Paris, France", 48.8566, 2.3522, "Tokyo, Japon", 35.6762, 139.6503, date(2024, 10, 3), "plane", date(2024, 10, 20)),
    ("Lyon, France", 45.7640, 4.8357, "Milan, Italie", 45.4642, 9.1900, date(2025, 2, 8), "train", date(2025, 2, 11)),
    ("Paris, France", 48.8566, 2.3522, "Londres, Royaume-Uni", 51.5074, -0.1278, date(2025, 6, 14), "train", None),
    ("Bordeaux, France", 44.8378, -0.5792, "San Sebastián, Espagne", 43.3183, -1.9812, date(2025, 7, 19), "car", date(2025, 7, 27)),
    ("Marseille, France", 43.2965, 5.3698, "Ajaccio, France", 41.9192, 8.7386, date(2025, 8, 2), "boat", date(2025, 8, 16)),
    ("Berlin, Allemagne", 52.5200, 13.4050, "Prague, Tchéquie", 50.0755, 14.4378, date(2024, 5, 9), "bus", None),
    ("Amsterdam, Pays-Bas", 52.3676, 4.9041, "Utrecht, Pays-Bas", 52.0907, 5.1214, date(2024, 5, 4), "bike", None),
    ("Chamonix, France", 45.9237, 6.8694, "Zermatt, Suisse", 46.0207, 7.7491, date(2024, 7, 6), "walk", None),
    ("Barcelone, Espagne", 41.3874, 2.1686, "Madrid, Espagne", 40.4168, -3.7038, date(2025, 3, 21), "train", date(2025, 3, 24)),
    ("Paris, France", 48.8566, 2.3522, "Lisbonne, Portugal", 38.7223, -9.1393, date(2025, 9, 5), "plane", None),
    ("Nice, France", 43.7102, 7.2620, "Monaco, Monaco", 43.7384, 7.4246, date(2025, 9, 6), "bus", date(2025, 9, 6)),
]


def _pybabel(*args):
    cmd = [sys.executable, "-m", "babel.messages.frontend", *args]
    click.echo("$ pybabel " + " ".join(args))
    subprocess.run(cmd, check=True, cwd=ROOT)


def register_cli(app):
    @app.cli.command("seed")
    @click.option("--reset", is_flag=True, help="Supprime d'abord les voyages de démonstration existants.")
    def seed(reset):
        """Crée l'utilisateur demo@example.com (mot de passe demo1234) et des voyages de démonstration."""
        from .models import Trip, User

        user = db.session.execute(db.select(User).filter_by(email=DEMO_EMAIL)).scalar_one_or_none()
        if user is None:
            user = User(email=DEMO_EMAIL, locale="fr")
            user.set_password(DEMO_PASSWORD)
            db.session.add(user)
            db.session.flush()
        elif reset:
            Trip.query.filter_by(user_id=user.id).delete()
            user.locale, user.theme = "fr", None
        if user.trips.count() and not reset:
            click.echo("Les voyages de démonstration existent déjà (utilisez --reset).")
            return
        for o, olat, olon, d, dlat, dlon, dep, mode, ret in DEMO_TRIPS:
            trip = Trip(
                user=user, origin_name=o, origin_lat=olat, origin_lon=olon,
                dest_name=d, dest_lat=dlat, dest_lon=dlon, depart_date=dep,
                transport_mode=mode, is_round_trip=ret is not None, return_date=ret,
            )
            trip.fill_missing_countries()
            db.session.add(trip)
        db.session.commit()
        click.echo(f"{len(DEMO_TRIPS)} voyages créés pour {DEMO_EMAIL} / {DEMO_PASSWORD}")

    @app.cli.command("create-admin")
    @click.argument("email")
    @click.option("--password", help="Mot de passe (demandé de façon interactive si absent).")
    def create_admin(email, password):
        """Crée un compte administrateur, ou promeut un compte existant."""
        from .auth.forms import PASSWORD_MIN
        from .models import User

        email = email.strip().lower()
        user = db.session.execute(db.select(User).filter_by(email=email)).scalar_one_or_none()
        if user is None:
            if password is None:
                password = click.prompt("Mot de passe", hide_input=True, confirmation_prompt=True)
            if len(password) < PASSWORD_MIN:
                raise click.BadParameter(f"au moins {PASSWORD_MIN} caractères.", param_hint="--password")
            user = User(email=email, locale="fr", is_admin=True)
            user.set_password(password)
            db.session.add(user)
            click.echo(f"Administrateur {email} créé.")
        else:
            user.is_admin = True
            if password is not None:
                user.set_password(password)
            click.echo(f"{email} est désormais administrateur.")
        db.session.commit()

    @app.cli.group("geocode")
    def geocode_group():
        """Gestion du cache de géocodage."""

    @geocode_group.command("purge")
    @click.option("--all", "everything", is_flag=True, help="Vide tout le cache, pas seulement les entrées expirées.")
    def geocode_purge(everything):
        """Supprime les entrées expirées du cache de géocodage (à lancer par exemple chaque nuit)."""
        from .geo import purge_geocode_cache

        count = purge_geocode_cache(everything)
        click.echo(f"{count} entrée(s) supprimée(s) du cache de géocodage.")

    @app.cli.group("trips")
    def trips_group():
        """Maintenance des voyages."""

    @trips_group.command("backfill-countries")
    @click.option("--force", is_flag=True, help="Recalcule aussi les pays déjà renseignés.")
    def backfill_countries(force):
        """Déduit le pays de départ et d'arrivée des coordonnées (hors ligne, Natural Earth)."""
        from .models import Trip

        stmt = db.select(Trip)
        if not force:
            stmt = stmt.where((Trip.origin_country.is_(None)) | (Trip.dest_country.is_(None)))
        updated = unresolved = 0
        for trip in db.session.execute(stmt).scalars():
            if force:
                trip.origin_country = trip.dest_country = None
            trip.fill_missing_countries()
            updated += 1
            unresolved += not (trip.origin_country and trip.dest_country)
        db.session.commit()
        click.echo(f"{updated} trajet(s) traité(s), {unresolved} sans pays identifié (point en mer ?).")

    @trips_group.command("compute-routes")
    @click.option("--force", is_flag=True, help="Recalcule aussi les distances déjà connues.")
    def compute_routes(force):
        """Calcule la distance d'itinéraire (ROUTING_URL) des trajets routiers qui n'en ont pas."""
        from .models import Trip
        from .routing import enabled_for, profiles, update_route

        if not app.config["ROUTING_URL"]:
            raise click.UsageError("ROUTING_URL n'est pas configuré.")
        stmt = db.select(Trip).where(Trip.transport_mode.in_(list(profiles())))
        if not force:
            stmt = stmt.where(Trip.route_distance_km.is_(None))
        done = failed = 0
        for trip in db.session.execute(stmt).scalars():
            if enabled_for(trip.transport_mode):
                update_route(trip)
                done += trip.route_distance_km is not None
                failed += trip.route_distance_km is None
                db.session.commit()
                time.sleep(1)  # ménage le serveur de calcul
        click.echo(f"{done} distance(s) calculée(s), {failed} sans itinéraire (estimation conservée).")

    @app.cli.group("photos")
    def photos_group():
        """Maintenance des photos."""

    @photos_group.command("cleanup")
    @click.option("--dry-run", is_flag=True, help="Affiche les fichiers sans les supprimer.")
    def photos_cleanup(dry_run):
        """Supprime les fichiers de UPLOAD_FOLDER qui ne correspondent à aucune photo en base."""
        from .photos import orphan_files

        orphans = orphan_files()
        for path in orphans:
            click.echo(path)
            if not dry_run:
                os.remove(path)
        click.echo(f"{len(orphans)} fichier(s) orphelin(s){' (non supprimés)' if dry_run else ' supprimé(s)'}.")

    @app.cli.group("backup")
    def backup_group():
        """Sauvegardes complètes (base + photos)."""

    @backup_group.command("create")
    @click.option("--dir", "folder", help="Dossier de destination (par défaut BACKUP_DIR ou instance/backups).")
    @click.option("--keep", type=int, default=None, help="Archives à conserver (par défaut BACKUP_KEEP).")
    def backup_create(folder, keep):
        """Crée une archive datée et supprime les plus anciennes. À lancer chaque nuit (cron)."""
        from .backup import BackupError, create_backup, read_manifest

        try:
            path = create_backup(folder, keep if keep is not None else app.config["BACKUP_KEEP"])
        except BackupError as exc:
            raise click.ClickException(str(exc)) from None
        counts = read_manifest(path)["counts"]
        click.echo(f"{path} ({os.path.getsize(path) // 1024} Ko) : "
                   + ", ".join(f"{n} {t}" for t, n in counts.items() if n is not None))

    @backup_group.command("list")
    @click.option("--dir", "folder", help="Dossier des archives.")
    def backup_list(folder):
        """Liste les archives, de la plus récente à la plus ancienne."""
        from .backup import list_backups, read_manifest

        paths = list_backups(folder)
        for path in paths:
            manifest = read_manifest(path)
            click.echo(f"{os.path.basename(path)}  {manifest['created_at']}  "
                       f"{manifest['counts'].get('trips')} trajets  {os.path.getsize(path) // 1024} Ko")
        if not paths:
            click.echo("Aucune sauvegarde.")

    @backup_group.command("restore")
    @click.argument("archive", type=click.Path(exists=True, dir_okay=False))
    @click.option("--yes", is_flag=True, help="Ne pas demander de confirmation.")
    def backup_restore(archive, yes):
        """Restaure une archive (arrêtez d'abord l'application). L'état actuel est sauvegardé avant."""
        from flask_migrate import upgrade

        from .backup import BackupError, read_manifest, restore_backup

        try:
            manifest = read_manifest(archive)
        except (BackupError, OSError) as exc:
            raise click.ClickException(str(exc)) from None
        click.echo(f"Archive du {manifest['created_at']} : " + ", ".join(
            f"{n} {t}" for t, n in manifest["counts"].items() if n is not None))
        if not yes:
            click.confirm("Remplacer la base et les photos actuelles par cette archive ?", abort=True)
        db.session.remove()
        db.engine.dispose()  # ferme les connexions avant de remplacer le fichier
        try:
            manifest, safety = restore_backup(archive)
        except BackupError as exc:
            raise click.ClickException(str(exc)) from None
        click.echo(f"État précédent sauvegardé dans {safety}")
        upgrade()  # met le schéma restauré à jour si l'archive est plus ancienne que le code
        click.echo("Restauration terminée. Redémarrez l'application.")

    @app.cli.command("mail-test")
    @click.argument("to")
    def mail_test(to):
        """Envoie un e-mail de test pour vérifier la configuration SMTP (MAIL_SERVER…)."""
        from .mail import send_email

        if not app.config["MAIL_SERVER"]:
            raise click.ClickException("MAIL_SERVER n'est pas configuré.")
        ok = send_email(to, "Carnet de voyages : e-mail de test",
                        "Si vous lisez ce message, l'envoi d'e-mails du Carnet de voyages fonctionne.")
        if not ok:
            raise click.ClickException("Échec de l'envoi (voir le journal ci-dessus).")
        click.echo(f"E-mail de test remis au serveur {app.config['MAIL_SERVER']}:{app.config['MAIL_PORT']} pour {to}.")

    @app.cli.command("purge-share-links")
    def purge_share_links():
        """Supprime les liens de partage expirés."""
        from .models import ShareLink, utcnow

        result = db.session.execute(db.delete(ShareLink).where(ShareLink.expires_at <= utcnow()))
        db.session.commit()
        click.echo(f"{result.rowcount} lien(s) de partage expiré(s) supprimé(s).")

    @app.cli.group("translate")
    def translate():
        """Workflow de traduction (pybabel)."""

    @translate.command("extract")
    def extract():
        """Extrait les chaînes vers app/translations/messages.pot."""
        _pybabel("extract", "-F", "babel.cfg", "-k", "_l", "-k", "lazy_gettext",
                 "--sort-by-file", "--project=travel", "-o", POT, ".")

    @translate.command("init")
    @click.argument("lang")
    def init(lang):
        """Crée le catalogue d'une nouvelle langue."""
        _pybabel("init", "-i", POT, "-d", TRANSLATIONS, "-l", lang)

    @translate.command("update")
    def update():
        """Extrait puis fusionne les nouvelles chaînes dans tous les catalogues."""
        extract.callback()
        _pybabel("update", "-i", POT, "-d", TRANSLATIONS, "--no-fuzzy-matching", "--ignore-obsolete")

    @translate.command("compile")
    def compile_():
        """Compile les .po en .mo."""
        _pybabel("compile", "-d", TRANSLATIONS, "--statistics")
