from datetime import date

from app.models import Journey, Trip

from .conftest import make_trip


def iceland_legs(user):
    return [
        make_trip(user, origin_name="Paris", dest_name="Reykjavik", dest_lat=64.15, dest_lon=-21.94,
                  depart_date=date(2026, 1, 26), transport_mode="plane"),
        make_trip(user, origin_name="Reykjavik", origin_lat=64.15, origin_lon=-21.94, dest_name="Amsterdam",
                  dest_lat=52.31, dest_lon=4.76, depart_date=date(2026, 1, 30), transport_mode="plane"),
        make_trip(user, origin_name="Amsterdam", origin_lat=52.31, origin_lon=4.76, dest_name="Paris",
                  dest_lat=48.86, dest_lon=2.35, depart_date=date(2026, 1, 30), transport_mode="plane"),
    ]


def group(client, trips):
    return client.post("/journeys", data={"trip_ids": [t.id for t in trips]})


def journeys(db):
    return db.session.execute(db.select(Journey)).scalars().all()


def test_group_legs_into_journey(auth_client, db, user):
    legs = iceland_legs(user)
    assert group(auth_client, legs).status_code == 302
    (journey,) = journeys(db)
    assert [leg.id for leg in journey.legs] == [leg.id for leg in legs]
    assert journey.route_label == "Paris → Reykjavik → Amsterdam → Paris"
    assert journey.start_date == date(2026, 1, 26) and journey.end_date == date(2026, 1, 30)
    page = auth_client.get("/trips").text
    assert "Paris → Reykjavik → Amsterdam → Paris" in page and "3 trajets" in page


def test_journey_counts_once_in_stats(auth_client, user):
    group(auth_client, iceland_legs(user))
    make_trip(user)
    stats = auth_client.get("/api/stats").get_json()
    assert stats["count"] == 2 and stats["legs"] == 4
    assert sum(m["count"] for m in stats["by_mode"]) == 4
    data = auth_client.get("/api/trips").get_json()
    assert data["count"] == 2 and len(data["trips"]) == 4
    assert {t["journey"]["name"] for t in data["trips"] if t["journey"]} == {"Paris → Reykjavik → Amsterdam → Paris"}


def test_group_needs_two_own_trips(auth_client, db, user, other_user):
    mine = make_trip(user)
    theirs = make_trip(other_user)
    group(auth_client, [mine, theirs])
    assert journeys(db) == []
    assert db.session.get(Trip, theirs.id).journey_id is None


def test_grouping_merges_existing_journeys(auth_client, db, user):
    a, b, c = iceland_legs(user)
    d = make_trip(user, depart_date=date(2026, 2, 1))
    group(auth_client, [a, b])
    group(auth_client, [c, d])
    group(auth_client, [b, c])
    (journey,) = journeys(db)
    assert len(journey.legs) == 4


def test_rename_journey(auth_client, db, user):
    group(auth_client, iceland_legs(user))
    journey = journeys(db)[0]
    auth_client.post(f"/journeys/{journey.id}/edit", data={"name": "  Islande  "})
    assert db.session.get(Journey, journey.id).display_name == "Islande"
    auth_client.post(f"/journeys/{journey.id}/edit", data={"name": ""})
    assert db.session.get(Journey, journey.id).name is None


def test_ungroup_keeps_trips(auth_client, db, user):
    legs = iceland_legs(user)
    group(auth_client, legs)
    auth_client.post(f"/journeys/{journeys(db)[0].id}/ungroup")
    assert journeys(db) == []
    assert all(db.session.get(Trip, leg.id).journey_id is None for leg in legs)


def test_detach_and_delete_dissolve_small_journeys(auth_client, db, user):
    a, b, c = iceland_legs(user)
    group(auth_client, [a, b, c])
    auth_client.post(f"/trips/{a.id}/detach")
    assert len(journeys(db)[0].legs) == 2
    auth_client.post(f"/trips/{b.id}/delete")
    assert journeys(db) == []
    assert db.session.get(Trip, c.id).journey_id is None


def test_other_users_journey_is_404(client, db, user, other_user):
    from .conftest import login

    login(client)
    group(client, iceland_legs(user))
    journey = journeys(db)[0]
    client.post("/auth/logout")
    login(client, "bob@example.com")
    assert client.get(f"/journeys/{journey.id}/edit").status_code == 404
    assert client.post(f"/journeys/{journey.id}/ungroup").status_code == 404
