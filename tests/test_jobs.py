from datetime import timedelta

from app import jobs
from app.models import JobRun, ShareLink, utcnow

from .conftest import login, make_user


def test_run_job_records_success(app, db, monkeypatch):
    monkeypatch.setitem(jobs.JOBS, "backup", jobs.Job("backup", timedelta(days=1), lambda: "3 trajets", "x"))
    record = jobs.run_job("backup")
    assert record.status == "ok" and record.summary == "3 trajets" and record.finished_at is not None
    assert record.duration >= 0


def test_run_job_records_failure_with_traceback(app, db, monkeypatch):
    def boom():
        db.session.add(JobRun(name="x", status="ok"))  # écrit puis annulé
        raise RuntimeError("disque plein")

    monkeypatch.setitem(jobs.JOBS, "backup", jobs.Job("backup", timedelta(days=1), boom, "x"))
    record = jobs.run_job("backup")
    assert record.status == "failed" and record.summary == "RuntimeError : disque plein"
    assert "Traceback" in record.error
    assert db.session.execute(db.select(JobRun).filter_by(name="x")).first() is None


def test_mail_import_skipped_without_imap(app, db):
    record = jobs.run_job("mail-import")
    assert record.status == "skipped" and "IMAP_SERVER" in record.summary


def test_maintenance_purges(app, db, user):
    old = utcnow() - timedelta(days=jobs.JOB_HISTORY_DAYS + 1)
    db.session.add_all([JobRun(name="backup", status="ok", started_at=old),
                        ShareLink(user_id=user.id, token="old", expires_at=utcnow() - timedelta(days=1))])
    db.session.commit()
    record = jobs.run_job("maintenance")
    assert record.status == "ok" and "1 lien(s)" in record.summary and "1 exécution(s)" in record.summary
    assert db.session.execute(db.select(ShareLink)).first() is None


def test_overview_flags_late_and_failed_jobs(app, db):
    now = utcnow()
    db.session.add_all([
        JobRun(name="mail-import", status="ok", started_at=now - timedelta(minutes=3)),
        JobRun(name="backup", status="ok", started_at=now - timedelta(days=3)),
        JobRun(name="backup", status="failed", started_at=now - timedelta(hours=2)),
    ])
    db.session.commit()
    rows = {job.name: (last, late, failures) for job, last, _ok, late, failures in jobs.job_overview()}
    assert rows["mail-import"][1] is False
    assert rows["backup"][0].status == "failed" and rows["backup"][1] is True and rows["backup"][2] == 1
    assert rows["maintenance"][0] is None


def test_admin_jobs_page(client, db, app):
    admin = make_user("root@example.com")
    admin.is_admin = True
    db.session.add(JobRun(name="backup", status="failed", summary="RuntimeError : disque plein", error="Traceback…",
                          started_at=utcnow(), finished_at=utcnow()))
    db.session.commit()
    login(client, "root@example.com")
    html = client.get("/admin/jobs").text
    assert "disque plein" in html and "Traceback…" in html and "mail-import" in html and "Jamais exécutée" in html


def test_admin_jobs_page_forbidden_for_regular_user(auth_client):
    assert auth_client.get("/admin/jobs").status_code == 403


def test_jobs_cli(app, db, monkeypatch):
    monkeypatch.setitem(jobs.JOBS, "backup", jobs.Job("backup", timedelta(days=1), lambda: "fait", "x"))
    result = app.test_cli_runner().invoke(args=["jobs", "run", "backup"])
    assert result.exit_code == 0 and "backup : ok — fait" in result.output
    assert "backup       ok le" in app.test_cli_runner().invoke(args=["jobs", "list"]).output
