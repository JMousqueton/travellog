"""Onglet Base de données de l'administration : serveur PostgreSQL, tables, migrations et dernière sauvegarde."""
import os
from dataclasses import dataclass
from datetime import datetime

from alembic.script import ScriptDirectory
from flask import current_app

from ..extensions import db


@dataclass
class TableInfo:
    name: str
    rows: int
    total_bytes: int
    index_bytes: int
    dead_rows: int
    last_vacuum: datetime | None
    last_analyze: datetime | None


def _scalar(sql):
    return db.session.execute(db.text(sql)).scalar()


def server_info():
    stats = db.session.execute(db.text(
        "SELECT numbackends, blks_hit, blks_read FROM pg_stat_database WHERE datname = current_database()")).one()
    reads = stats.blks_hit + stats.blks_read
    return {
        "version": _scalar("SHOW server_version").split()[0],
        "database": _scalar("SELECT current_database()"),
        "user": _scalar("SELECT current_user"),
        "started_at": _scalar("SELECT pg_postmaster_start_time()"),
        "size": _scalar("SELECT pg_database_size(current_database())"),
        "connections": stats.numbackends,
        "max_connections": int(_scalar("SHOW max_connections")),
        # Part des lectures servies par le cache de PostgreSQL depuis le dernier redémarrage.
        "cache_hit": stats.blks_hit / reads if reads else None,
    }


def tables():
    """Tables de l'application, les plus volumineuses d'abord. Nombre de lignes exact (count), pas l'estimation."""
    rows = db.session.execute(db.text(
        "SELECT relname, pg_total_relation_size(relid) AS total, pg_indexes_size(relid) AS indexes, n_dead_tup, "
        "GREATEST(last_vacuum, last_autovacuum) AS vacuum, GREATEST(last_analyze, last_autoanalyze) AS analyze "
        "FROM pg_stat_user_tables WHERE schemaname = 'public' ORDER BY total DESC, relname")).all()
    result = []
    for row in rows:
        quoted = '"' + row.relname.replace('"', '""') + '"'
        result.append(TableInfo(row.relname, _scalar(f"SELECT count(*) FROM public.{quoted}"), row.total,
                                row.indexes, row.n_dead_tup, row.vacuum, row.analyze))
    return result


def migration_info():
    migrate = current_app.extensions["migrate"]
    heads = ScriptDirectory.from_config(migrate.migrate.get_config(migrate.directory)).get_heads()
    current = None
    if _scalar("SELECT to_regclass('public.alembic_version')") is not None:  # absente si créée sans migrations
        current = _scalar("SELECT version_num FROM alembic_version")
    return {"current": current, "heads": heads, "up_to_date": current in heads and len(heads) == 1}


def latest_backup():
    """Archive la plus récente et nombre d'archives conservées (None si aucune ou dossier illisible)."""
    from ..backup import BackupError, list_backups, read_manifest

    try:
        paths = list_backups()
        if not paths:
            return None
        manifest = read_manifest(paths[0])
        return {"name": os.path.basename(paths[0]), "size": os.path.getsize(paths[0]), "count": len(paths),
                "created_at": datetime.fromisoformat(manifest["created_at"]), "counts": manifest.get("counts") or {}}
    except (OSError, BackupError, KeyError, ValueError):
        return None
