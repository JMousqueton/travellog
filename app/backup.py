"""Sauvegarde et restauration complètes du serveur : base PostgreSQL + photos, dans une archive .tar.gz.

La base est exportée par pg_dump (format custom) depuis un instantané exporté : le manifeste (date, révision
Alembic, nombre de lignes) est compté dans ce même instantané, cohérent même application en marche.
La restauration passe par psql en une seule transaction et vérifie le manifeste avant de valider.
"""
import io
import json
import os
import shutil
import subprocess
import tarfile
import tempfile
from datetime import datetime, timezone

from flask import current_app
from sqlalchemy.engine import make_url

from .extensions import db

PREFIX = "travel-backup-"
SUFFIX = ".tar.gz"
DUMP_NAME = "database.dump"
FORMAT = 2  # 1 : ancienne archive SQLite (travel.db)
COUNTED_TABLES = ("users", "trips", "journeys", "share_links", "photos", "tags")


class BackupError(RuntimeError):
    pass


def _tool(name):
    path = shutil.which(name)
    if not path:
        raise BackupError(f"{name} introuvable : installez le client PostgreSQL (paquet postgresql-client).")
    return path


def _libpq_env():
    """Connexion des outils PostgreSQL par variables d'environnement (le mot de passe n'apparaît pas dans ps)."""
    url = make_url(current_app.config["SQLALCHEMY_DATABASE_URI"])
    env = dict(os.environ)
    for key, value in (("PGHOST", url.host), ("PGPORT", url.port), ("PGUSER", url.username),
                       ("PGPASSWORD", url.password), ("PGDATABASE", url.database),
                       ("PGSSLMODE", url.query.get("sslmode"))):
        if value:
            env[key] = str(value)
    return env


def _run(args, what):
    result = subprocess.run(args, env=_libpq_env(), capture_output=True, text=True)
    if result.returncode != 0:
        lines = (result.stderr or result.stdout).strip().splitlines()
        errors = [line.split("ERROR:", 1)[1].strip() for line in lines if "ERROR:" in line]
        detail = errors[0] if errors else lines[-1] if lines else f"code {result.returncode}"
        raise BackupError(f"{what} : {detail}")
    return result.stdout


def backup_dir():
    folder = current_app.config["BACKUP_DIR"] or os.path.join(current_app.instance_path, "backups")
    os.makedirs(folder, exist_ok=True)
    return folder


def _counts(connection):
    counts = {}
    for table in COUNTED_TABLES:
        if connection.exec_driver_sql(f"SELECT to_regclass('public.{table}')").scalar() is None:
            counts[table] = None
        else:
            counts[table] = connection.exec_driver_sql(f"SELECT count(*) FROM {table}").scalar()
    return counts


def _revision(connection):
    if connection.exec_driver_sql("SELECT to_regclass('public.alembic_version')").scalar() is None:
        return None
    return connection.exec_driver_sql("SELECT version_num FROM alembic_version").scalar()


def create_backup(folder=None, keep=None):
    """Crée une archive et renvoie son chemin. `keep` : nombre d'archives à conserver (les plus récentes)."""
    folder = folder or backup_dir()
    os.makedirs(folder, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    target = os.path.join(folder, f"{PREFIX}{stamp}{SUFFIX}")
    pg_dump, pg_restore = _tool("pg_dump"), _tool("pg_restore")
    with tempfile.TemporaryDirectory() as tmp:
        dump = os.path.join(tmp, DUMP_NAME)
        with db.engine.connect() as conn:
            conn = conn.execution_options(isolation_level="REPEATABLE READ")
            with conn.begin():
                snapshot = conn.exec_driver_sql("SELECT pg_export_snapshot()").scalar()
                manifest = {
                    "format": FORMAT,
                    "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    "revision": _revision(conn),
                    "counts": _counts(conn),
                }
                # L'instantané n'existe que tant que cette transaction reste ouverte.
                _run([pg_dump, "--format=custom", "--no-owner", "--no-privileges", f"--snapshot={snapshot}",
                      f"--file={dump}"], "Échec de pg_dump")
        _run([pg_restore, "--list", dump], "La copie de la base est illisible : sauvegarde annulée")
        uploads = current_app.config["UPLOAD_FOLDER"]
        partial = target + ".part"
        with tarfile.open(partial, "w:gz") as archive:
            archive.add(dump, arcname=DUMP_NAME)
            if os.path.isdir(uploads):
                archive.add(uploads, arcname="uploads")
            data = json.dumps(manifest, indent=2).encode()
            info = tarfile.TarInfo("manifest.json")
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
        os.replace(partial, target)  # jamais d'archive à moitié écrite sous le nom final
    if keep:
        prune(folder, keep)
    return target


def list_backups(folder=None):
    folder = folder or backup_dir()
    names = sorted((n for n in os.listdir(folder) if n.startswith(PREFIX) and n.endswith(SUFFIX)), reverse=True)
    return [os.path.join(folder, n) for n in names]


def prune(folder, keep):
    removed = []
    for path in list_backups(folder)[keep:]:
        os.remove(path)
        removed.append(path)
    return removed


def read_manifest(path):
    with tarfile.open(path, "r:gz") as archive:
        try:
            member = archive.getmember("manifest.json")
        except KeyError:
            raise BackupError("Archive invalide : manifeste absent.") from None
        return json.load(archive.extractfile(member))


def _check_members(archive):
    """Refuse les chemins absolus, les « .. », les liens et tout ce qui n'est pas base, photos ou manifeste."""
    for member in archive.getmembers():
        name = member.name
        parts = name.split("/")
        if name.startswith("/") or ".." in parts or not (member.isfile() or member.isdir()):
            raise BackupError(f"Archive refusée : entrée suspecte « {name} ».")
        if name not in (DUMP_NAME, "manifest.json", "uploads") and parts[0] != "uploads":
            raise BackupError(f"Archive refusée : entrée inattendue « {name} ».")


def _manifest_check_sql(counts):
    """Bloc exécuté en fin de restauration : toute différence avec le manifeste annule la transaction."""
    checks = []
    for table, expected in counts.items():
        if table not in COUNTED_TABLES:
            raise BackupError("Archive invalide : manifeste inattendu.")
        if expected is not None:
            checks.append(f"  IF (SELECT count(*) FROM public.{table}) <> {int(expected)} THEN\n"
                          f"    RAISE EXCEPTION 'La base de l''archive ne correspond pas à son manifeste ({table}).';\n"
                          "  END IF;\n")
    return "DO $$\nBEGIN\n" + "".join(checks) + "END\n$$;\n"


def restore_backup(path):
    """Remplace la base et les photos par celles de l'archive. L'application doit être arrêtée.

    Une sauvegarde de l'état actuel est faite d'abord ; son chemin est renvoyé avec le manifeste restauré."""
    manifest = read_manifest(path)
    if manifest.get("format") != FORMAT:
        raise BackupError("Archive d'un ancien format (base SQLite) : importez-la avec "
                          "scripts/sqlite_to_postgres.py après l'avoir extraite.")
    psql, pg_restore = _tool("psql"), _tool("pg_restore")
    with tempfile.TemporaryDirectory() as tmp:
        with tarfile.open(path, "r:gz") as archive:
            _check_members(archive)
            archive.extractall(tmp, filter="data")
        dump = os.path.join(tmp, DUMP_NAME)
        if not os.path.isfile(dump):
            raise BackupError("Archive invalide : base de données absente.")
        _run([pg_restore, "--list", dump], "La base de l'archive est illisible")
        check = os.path.join(tmp, "check.sql")
        with open(check, "w") as fh:
            fh.write(_manifest_check_sql(manifest.get("counts") or {}))

        safety = create_backup()  # état actuel, au cas où
        db.session.remove()
        db.engine.dispose()  # aucune connexion de l'application ne doit bloquer le DROP SCHEMA
        script = os.path.join(tmp, "restore.sql")
        _run([pg_restore, "--no-owner", "--no-privileges", f"--file={script}", dump], "Échec de pg_restore")
        # Tout ou rien : schéma vidé, données rechargées puis comparées au manifeste dans une seule transaction.
        _run([psql, "--no-psqlrc", "--quiet", "--single-transaction", "--set=ON_ERROR_STOP=1",
              "--command=DROP SCHEMA public CASCADE", "--command=CREATE SCHEMA public",
              f"--file={script}", f"--file={check}"], "Restauration annulée, base inchangée")

        uploads = current_app.config["UPLOAD_FOLDER"]
        if os.path.isdir(uploads):
            shutil.rmtree(uploads)
        if os.path.isdir(os.path.join(tmp, "uploads")):
            shutil.copytree(os.path.join(tmp, "uploads"), uploads)
    return manifest, safety
