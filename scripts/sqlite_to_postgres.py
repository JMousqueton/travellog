"""Copie une ancienne base SQLite (travel.db) dans la base PostgreSQL de DATABASE_URL.

    .venv/bin/flask db upgrade                                    # schéma PostgreSQL à jour, tables vides
    .venv/bin/python scripts/sqlite_to_postgres.py instance/travel.db [--dry-run]

Arrêtez l'application et les tâches avant : la copie part d'un instantané de la base SQLite.
Tout est copié dans une seule transaction, puis les compteurs des clés (séquences) sont recalés et le nombre
de lignes de chaque table comparé à la source. --dry-run fait tout puis annule la transaction.
Les valeurs que PostgreSQL refuserait (texte trop long, clé étrangère orpheline) sont signalées avant copie.
"""
import argparse
import os
import sqlite3
import sys
import tempfile
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import sqlalchemy as sa  # noqa: E402

from app import create_app  # noqa: E402
from app.extensions import db  # noqa: E402

BATCH = 1000


def snapshot(path, folder):
    """Copie cohérente de la base (API de sauvegarde SQLite, WAL compris), vérifiée avant usage."""
    target = os.path.join(folder, "travel.db")
    source = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        dest = sqlite3.connect(target)
        with dest:
            source.backup(dest)
        if dest.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            sys.exit("La base SQLite est corrompue (PRAGMA integrity_check).")
        orphans = dest.execute("PRAGMA foreign_key_check").fetchall()
        if orphans:
            sys.exit(f"Clés étrangères orphelines dans la base SQLite : {orphans[:10]}")
        dest.close()
    finally:
        source.close()
    return target


def check_columns(source, tables):
    """Chaque colonne SQLite doit exister côté PostgreSQL, et chaque colonne obligatoire doit venir de SQLite."""
    inspector = sa.inspect(source)
    problems = []
    source_tables = set(inspector.get_table_names()) - {"alembic_version", "sqlite_sequence"}
    for name in sorted(source_tables - {t.name for t in tables}):
        problems.append(f"table {name} absente de PostgreSQL")
    for table in tables:
        if table.name not in source_tables:
            continue
        have = {c["name"] for c in inspector.get_columns(table.name)}
        for name in sorted(have - set(table.c.keys())):
            problems.append(f"{table.name}.{name} absente de PostgreSQL")
        for column in table.c:
            if column.name not in have and not (column.nullable or column.server_default is not None):
                problems.append(f"{table.name}.{column.name} obligatoire mais absente de SQLite")
    return problems


def as_utc(value):
    return value.replace(tzinfo=timezone.utc) if isinstance(value, datetime) and value.tzinfo is None else value


def read_rows(source, table, columns):
    """Lignes SQLite converties par les types des modèles (booléens, dates, JSON)."""
    typed = sa.table(table.name, *[sa.column(c.name, c.type) for c in columns])
    pk = [typed.c[c.name] for c in table.primary_key.columns if c.name in typed.c]
    with source.connect() as conn:
        for row in conn.execute(sa.select(typed).order_by(*pk)).mappings():
            yield {k: as_utc(v) for k, v in row.items()}


def too_long(table, row):
    for column in table.c:
        value = row.get(column.name)
        length = getattr(column.type, "length", None)
        if length and isinstance(value, str) and len(value) > length:
            yield f"{table.name}.{column.name} = {value[:40]!r}… ({len(value)} > {length})"


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("sqlite", help="chemin de travel.db")
    parser.add_argument("--dry-run", action="store_true", help="tout vérifier puis annuler la transaction")
    args = parser.parse_args()
    if not os.path.isfile(args.sqlite):
        sys.exit(f"{args.sqlite} introuvable.")

    app = create_app()
    with app.app_context(), tempfile.TemporaryDirectory() as tmp:
        source = sa.create_engine(f"sqlite:///{snapshot(args.sqlite, tmp)}")
        target = db.engine
        tables = db.metadata.sorted_tables
        print(f"Source : {args.sqlite}\nCible  : {target.url.render_as_string(hide_password=True)}")

        with source.connect() as conn:
            source_rev = conn.exec_driver_sql("SELECT version_num FROM alembic_version").scalar()
        with target.connect() as conn:
            target_rev = conn.exec_driver_sql("SELECT version_num FROM alembic_version").scalar()
        print(f"Révisions Alembic : SQLite {source_rev}, PostgreSQL {target_rev}")

        problems = check_columns(source, tables)
        source_tables = set(sa.inspect(source).get_table_names())
        data = {}
        for table in tables:
            if table.name not in source_tables:
                data[table] = []
                continue
            have = {c["name"] for c in sa.inspect(source).get_columns(table.name)}
            rows = list(read_rows(source, table, [c for c in table.c if c.name in have]))
            for row in rows:
                problems.extend(too_long(table, row))
            data[table] = rows
        if problems:
            sys.exit("Copie impossible :\n  " + "\n  ".join(problems))

        with target.connect() as conn:
            trans = conn.begin()
            try:
                for table in tables:
                    if conn.execute(sa.select(sa.func.count()).select_from(table)).scalar():
                        sys.exit(f"La table PostgreSQL {table.name} n'est pas vide : copie annulée.")
                for table in tables:
                    rows = data[table]
                    for start in range(0, len(rows), BATCH):
                        conn.execute(table.insert(), rows[start:start + BATCH])
                    # Les identifiants ont été copiés tels quels : la séquence repart après le plus grand.
                    pk = list(table.primary_key.columns)
                    if len(pk) == 1 and isinstance(pk[0].type, sa.Integer):
                        conn.execute(sa.text(
                            f"SELECT setval(pg_get_serial_sequence('{table.name}', '{pk[0].name}'), "
                            f"COALESCE(MAX({pk[0].name}), 1), MAX({pk[0].name}) IS NOT NULL) FROM {table.name}"))
                mismatches = []
                for table in tables:
                    copied = conn.execute(sa.select(sa.func.count()).select_from(table)).scalar()
                    print(f"  {table.name:<20} {copied:>7}")
                    if copied != len(data[table]):
                        mismatches.append(f"{table.name} : {copied} au lieu de {len(data[table])}")
                if mismatches:
                    sys.exit("Nombre de lignes différent, copie annulée : " + ", ".join(mismatches))
                if args.dry_run:
                    trans.rollback()
                    print("Essai réussi (--dry-run) : transaction annulée, rien n'a été écrit.")
                else:
                    trans.commit()
                    print("Copie terminée.")
            finally:
                if trans.is_active:
                    trans.rollback()


if __name__ == "__main__":
    main()
