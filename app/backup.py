"""Sauvegarde et restauration complètes du serveur : base SQLite + photos, dans une archive .tar.gz.

La base est copiée avec l'API de sauvegarde de SQLite (instantané cohérent, même application en marche).
L'archive contient aussi un manifeste (date, révision Alembic, nombre de lignes) vérifié à la restauration.
"""
import io
import json
import os
import shutil
import sqlite3
import tarfile
import tempfile
from datetime import datetime, timezone

from flask import current_app
from sqlalchemy.engine import make_url

PREFIX = "travel-backup-"
SUFFIX = ".tar.gz"
COUNTED_TABLES = ("users", "trips", "journeys", "share_links", "photos", "tags")


class BackupError(RuntimeError):
    pass


def database_path():
    url = make_url(current_app.config["SQLALCHEMY_DATABASE_URI"])
    if url.get_backend_name() != "sqlite" or not url.database or url.database == ":memory:":
        raise BackupError("La sauvegarde intégrée ne prend en charge que SQLite sur fichier "
                          "(pour une autre base, utilisez son outil de sauvegarde).")
    return url.database


def backup_dir():
    folder = current_app.config["BACKUP_DIR"] or os.path.join(current_app.instance_path, "backups")
    os.makedirs(folder, exist_ok=True)
    return folder


def _counts(connection):
    counts = {}
    for table in COUNTED_TABLES:
        try:
            counts[table] = connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
        except sqlite3.OperationalError:
            counts[table] = None
    return counts


def _revision(connection):
    try:
        row = connection.execute("SELECT version_num FROM alembic_version").fetchone()
    except sqlite3.OperationalError:
        return None
    return row[0] if row else None


def create_backup(folder=None, keep=None):
    """Crée une archive et renvoie son chemin. `keep` : nombre d'archives à conserver (les plus récentes)."""
    folder = folder or backup_dir()
    os.makedirs(folder, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    target = os.path.join(folder, f"{PREFIX}{stamp}{SUFFIX}")
    with tempfile.TemporaryDirectory() as tmp:
        snapshot = os.path.join(tmp, "travel.db")
        source = sqlite3.connect(database_path())
        try:
            dest = sqlite3.connect(snapshot)
            with dest:
                source.backup(dest)
            if dest.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise BackupError("La copie de la base est corrompue : sauvegarde annulée.")
            manifest = {
                "format": 1,
                "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "revision": _revision(dest),
                "counts": _counts(dest),
            }
            dest.close()
        finally:
            source.close()
        uploads = current_app.config["UPLOAD_FOLDER"]
        partial = target + ".part"
        with tarfile.open(partial, "w:gz") as archive:
            archive.add(snapshot, arcname="travel.db")
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
        if name not in ("travel.db", "manifest.json", "uploads") and parts[0] != "uploads":
            raise BackupError(f"Archive refusée : entrée inattendue « {name} ».")


def restore_backup(path):
    """Remplace la base et les photos par celles de l'archive. L'application doit être arrêtée.

    Une sauvegarde de l'état actuel est faite d'abord ; son chemin est renvoyé avec le manifeste restauré."""
    manifest = read_manifest(path)
    with tempfile.TemporaryDirectory() as tmp:
        with tarfile.open(path, "r:gz") as archive:
            _check_members(archive)
            archive.extractall(tmp, filter="data")
        db_file = os.path.join(tmp, "travel.db")
        if not os.path.isfile(db_file):
            raise BackupError("Archive invalide : base de données absente.")
        check = sqlite3.connect(db_file)
        try:
            if check.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise BackupError("La base de l'archive est corrompue.")
            if _counts(check) != manifest.get("counts"):
                raise BackupError("La base de l'archive ne correspond pas à son manifeste.")
        finally:
            check.close()

        safety = create_backup()  # état actuel, au cas où
        target = database_path()
        partial = target + ".restore"
        shutil.copyfile(db_file, partial)
        os.replace(partial, target)
        for suffix in ("-wal", "-shm", "-journal"):
            if os.path.exists(target + suffix):
                os.remove(target + suffix)
        uploads = current_app.config["UPLOAD_FOLDER"]
        if os.path.isdir(uploads):
            shutil.rmtree(uploads)
        if os.path.isdir(os.path.join(tmp, "uploads")):
            shutil.copytree(os.path.join(tmp, "uploads"), uploads)
    return manifest, safety
