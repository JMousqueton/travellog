import io
import json
import os
import tarfile
import zipfile
from datetime import date

import pytest
from PIL import Image

from app.backup import BackupError, create_backup, list_backups, read_manifest, restore_backup
from app.extensions import db as _db
from app.models import Journey, Photo, Trip, User

from .conftest import login, make_trip, make_user


@pytest.fixture
def file_app(app, tmp_path):
    """Application dont les sauvegardes vont dans le dossier temporaire du test."""
    app.config["BACKUP_DIR"] = str(tmp_path / "backups")
    return app


def _jpeg():
    out = io.BytesIO()
    Image.new("RGB", (64, 64), (10, 120, 200)).save(out, "JPEG")
    return out.getvalue()


def test_backup_and_restore_roundtrip(file_app, tmp_path):
    user = make_user()
    make_trip(user)
    os.makedirs(tmp_path / "uploads")
    (tmp_path / "uploads" / "abc.jpg").write_bytes(b"photo")
    path = create_backup()
    manifest = read_manifest(path)
    assert manifest["counts"]["trips"] == 1 and manifest["counts"]["users"] == 1
    with tarfile.open(path) as archive:
        assert {"database.dump", "manifest.json", "uploads/abc.jpg"} <= set(archive.getnames())

    # On casse tout, puis on restaure.
    _db.session.execute(_db.delete(Trip))
    _db.session.commit()
    (tmp_path / "uploads" / "abc.jpg").unlink()
    _db.session.remove()
    _db.engine.dispose()
    restored, safety = restore_backup(path)
    assert os.path.exists(safety) and read_manifest(safety)["counts"]["trips"] == 0  # état d'avant restauration
    assert _db.session.scalar(_db.select(_db.func.count(Trip.id))) == 1
    assert _db.session.scalar(_db.select(User.email)) == "alice@example.com"
    assert (tmp_path / "uploads" / "abc.jpg").read_bytes() == b"photo"


def test_keep_only_recent_backups(file_app, monkeypatch):
    import app.backup as backup

    # Deux appels à now() par sauvegarde (nom du fichier, puis manifeste).
    stamps = iter(s for s in ["20250101-000000", "20250102-000000", "20250103-000000"] for _ in range(2))

    class FakeNow:
        @staticmethod
        def now(tz=None):
            from datetime import datetime
            return datetime.strptime(next(stamps), "%Y%m%d-%H%M%S").replace(tzinfo=tz)

    monkeypatch.setattr(backup, "datetime", FakeNow)
    for _ in range(3):
        create_backup(keep=2)
    assert [os.path.basename(p) for p in list_backups()] == [
        "travel-backup-20250103-000000.tar.gz", "travel-backup-20250102-000000.tar.gz"]


@pytest.mark.parametrize("name", ["../evil.txt", "/etc/passwd", "other.txt"])
def test_restore_rejects_unsafe_archives(file_app, tmp_path, name):
    path = tmp_path / "bad.tar.gz"
    with tarfile.open(path, "w:gz") as archive:
        for member, data in (("manifest.json", json.dumps({"format": 2, "counts": {}}).encode()), (name, b"x")):
            info = tarfile.TarInfo(member)
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
    with pytest.raises(BackupError):
        restore_backup(str(path))


def test_restore_rejects_tampered_database(file_app, tmp_path):
    make_user()
    path = create_backup()
    manifest = read_manifest(path)
    manifest["counts"]["users"] = 42
    tampered = tmp_path / "tampered.tar.gz"
    with tarfile.open(path) as src, tarfile.open(tampered, "w:gz") as dst:
        for member in src.getmembers():
            if member.name == "manifest.json":
                data = json.dumps(manifest).encode()
                member.size = len(data)
                dst.addfile(member, io.BytesIO(data))
            else:
                dst.addfile(member, src.extractfile(member) if member.isfile() else None)
    with pytest.raises(BackupError, match="manifeste"):
        restore_backup(str(tampered))
    assert _db.session.scalar(_db.select(_db.func.count(User.id))) == 1  # transaction annulée : base intacte


def test_backup_cli(file_app):
    make_user()
    runner = file_app.test_cli_runner()
    result = runner.invoke(args=["backup", "create"])
    assert result.exit_code == 0 and "1 users" in result.output
    assert "travel-backup-" in runner.invoke(args=["backup", "list"]).output


def test_restore_refuses_old_sqlite_archive(file_app, tmp_path):
    path = tmp_path / "old.tar.gz"
    with tarfile.open(path, "w:gz") as archive:
        for member, data in (("manifest.json", json.dumps({"format": 1, "counts": {}}).encode()),
                             ("travel.db", b"SQLite format 3")):
            info = tarfile.TarInfo(member)
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
    with pytest.raises(BackupError, match="SQLite"):
        restore_backup(str(path))


# --- Sauvegarde complète d'un compte (.zip) -------------------------------------------------

def test_account_archive_roundtrip_with_photos(app, client, db, user):
    a = make_trip(user, notes="Note A", depart_date=date(2025, 1, 1))
    b = make_trip(user, depart_date=date(2025, 1, 4))
    login(client)
    client.post("/journeys", data={"trip_ids": [a.id, b.id]})
    journey = db.session.execute(db.select(Journey)).scalar_one()
    client.post(f"/trips/{a.id}/photos", data={"photos": [(io.BytesIO(_jpeg()), "a.jpg")]},
                content_type="multipart/form-data")
    client.post(f"/journeys/{journey.id}/photos", data={"photos": [(io.BytesIO(_jpeg()), "j.jpg")]},
                content_type="multipart/form-data")
    response = client.get("/export.zip")
    assert response.mimetype == "application/zip"
    with zipfile.ZipFile(io.BytesIO(response.data)) as archive:
        assert len([n for n in archive.namelist() if n.startswith("photos/")]) == 2
    client.post("/auth/logout")

    make_user("carol@example.com")
    login(client, "carol@example.com")
    result = client.post("/import", data={"file": (io.BytesIO(response.data), "backup.zip")},
                         content_type="multipart/form-data", follow_redirects=True)
    assert "2 photos restaurées" in result.text
    carol = db.session.execute(db.select(User).filter_by(email="carol@example.com")).scalar_one()
    trips = carol.trips.order_by(Trip.depart_date).all()
    assert trips[0].notes == "Note A" and [p.original_name for p in trips[0].photos] == ["a.jpg"]
    assert [p.original_name for p in trips[0].journey.photos] == ["j.jpg"]


def test_invalid_zip_is_rejected(auth_client):
    response = auth_client.post("/import", data={"file": (io.BytesIO(b"not a zip"), "x.zip")},
                                content_type="multipart/form-data")
    assert response.status_code == 400 and "Archive .zip invalide" in response.text
    empty = io.BytesIO()
    with zipfile.ZipFile(empty, "w") as archive:
        archive.writestr("other.txt", "x")
    response = auth_client.post("/import", data={"file": (io.BytesIO(empty.getvalue()), "x.zip")},
                                content_type="multipart/form-data")
    assert "trips.geojson absent" in response.text
