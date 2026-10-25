import io
from datetime import date

from app.airports import find_airport
from app.models import Trip

from .conftest import import_file

# Format réel d'un export Flighty : date américaine M/J/AA, horaires ISO, TRUE/FALSE en majuscules.
FLIGHTY_HEADER = ("Date,Airline,Flight,From,To,Dep Terminal,Dep Gate,Arr Terminal,Arr Gate,Canceled,Diverted To,"
                  "Gate Departure (Scheduled),Gate Departure (Actual),Take off (Scheduled),Take off (Actual),"
                  "Landing (Scheduled),Landing (Actual),Gate Arrival (Scheduled),Gate Arrival (Actual),"
                  "Aircraft Type Name,Tail Number,PNR,Seat,Seat Type,Cabin Class,Flight Reason,Notes,"
                  "Flight Flighty ID,Airline Flighty ID,Departure Airport Flighty ID,Arrival Airport Flighty ID,"
                  "Diverted To Airport Flighty ID,Aircraft Type Flighty ID")
FLIGHTY = FLIGHTY_HEADER + """
10/12/15,AFR,1148,CDG,BCN,2F,,1,,FALSE,,2015-10-12T07:40,2015-10-12T07:53,,2015-10-12T08:04,,,,,Airbus A321,FGTAZ,,,,,,,a,b,c,d,,e
2/8/19,JON,1434,CDG,TXL,2F,F30,,,FALSE,,2019-02-08T07:20,,,,,,,,Airbus A321,,,,,,,,a,b,c,d,,e
3/5/24,AFR,1181,LHR,CDG,4,,2E,,TRUE,,2024-03-05T19:45,,,,,,,,Airbus A220-300,,,,,,,,a,b,c,d,,e
5/25/23,AFR,23,JFK,CDG,1,3,2E,,FALSE,MAN,,,,,,,,,Boeing 777-300 ER,,,,,,,Orage,a,b,c,d,,e
"""
FLIGHTRADAR24 = """Date,Flight number,From,To,Dep time,Arr time,Duration,Airline,Aircraft,Registration,Seat number,Note
2024-10-12,DL49,Amsterdam / Schiphol (AMS/EHAM),New York / John F Kennedy (JFK/KJFK),12:10:00,14:30:00,08:20:00,Delta Air Lines (DL/DAL),Airbus A330-900neo (A339),N401DZ,1A,
2024-11-01,,Paris / Orly (/LFPO),Nice (NCE/),,,,,,,,
"""


def _import(client, content, filename="flights.csv"):
    return import_file(client, content, filename)


def _trips(db):
    return db.session.execute(db.select(Trip).order_by(Trip.depart_date)).scalars().all()


def test_find_airport_by_iata_or_icao():
    assert find_airport("cdg")["country"] == "FR"
    assert find_airport("LFPG") is find_airport("CDG")
    assert find_airport("ZZZ") is None and find_airport("") is None


def test_import_flighty(auth_client, db):
    assert _import(auth_client, FLIGHTY).status_code == 302
    trips = _trips(db)
    assert [(t.depart_date, t.origin_name, t.dest_name, t.transport_mode) for t in trips] == [
        (date(2015, 10, 12), "Charles de Gaulle International Airport (CDG)", "Josep Tarradellas Barcelona-El Prat Airport (BCN)", "plane"),
        # Aéroport fermé (Berlin-Tegel), connu grâce à OpenFlights.
        (date(2019, 2, 8), "Charles de Gaulle International Airport (CDG)", "Berlin-Tegel Airport (TXL)", "plane"),
        # Sans horaire, la colonne Date (M/J/AA) sert ; vol dérouté : arrivée à l'aéroport de déroutement.
        (date(2023, 5, 25), "John F. Kennedy International Airport (JFK)", "Manchester Airport (MAN)", "plane"),
    ]  # le vol annulé (TRUE) est ignoré
    assert (trips[0].origin_country, trips[0].dest_country, trips[1].dest_country) == ("FR", "ES", "DE")
    # Compagnie (nom d'après le code OACI), numéro IATA et appareil dans leurs champs ; la note reste la vôtre.
    assert (trips[0].carrier, trips[0].service_number, trips[0].vehicle) == ("Air France", "AF1148", "Airbus A321")
    assert trips[0].notes is None and trips[2].notes == "Orage"
    assert (trips[1].carrier, trips[1].service_number) == ("JON", "JON1434")  # compagnie disparue (Joon) : code
    # Réimporter le même fichier n'ajoute rien.
    _import(auth_client, FLIGHTY)
    assert len(_trips(db)) == 3


def test_import_flightradar24(auth_client, db):
    assert _import(auth_client, FLIGHTRADAR24).status_code == 302
    trips = _trips(db)
    assert [(t.origin_name, t.dest_name) for t in trips] == [
        ("Amsterdam Airport Schiphol (AMS)", "John F. Kennedy International Airport (JFK)"),
        ("Paris-Orly Airport (ORY)", "Nice-Côte d'Azur Airport (NCE)"),  # code OACI ou IATA seul
    ]
    assert (trips[0].carrier, trips[0].service_number, trips[0].vehicle) == (
        "Delta Air Lines", "DL49", "Airbus A330-900neo")
    assert trips[0].dest_lat == find_airport("JFK")["lat"]


def test_unknown_airport_blocks_import(auth_client, db):
    response = _import(auth_client, FLIGHTY.replace("CDG,TXL", "ZZZ,TXL"))
    assert response.status_code == 400
    assert "Ligne 3 : aéroport inconnu : « ZZZ »" in response.text
    assert "coordonnées invalides" not in response.text
    assert _trips(db) == []


def _flighty_line(day, number, origin, dest):
    return f"{day},AFR,{number},{origin},{dest},,,,,FALSE,,,,,,,,,,,,,,,,,,a,b,c,d,,e"


def test_flighty_round_trips_are_paired(auth_client, db):
    lines = [("10/12/15", 1, "CDG", "BCN"), ("10/15/15", 2, "BCN", "ORY"),   # aller-retour (CDG ≈ ORY)
             ("2/12/17", 3, "CDG", "ATL"), ("2/12/17", 4, "ATL", "DAL"),     # circuit : vols simples
             ("7/17/24", 5, "ORY", "MPL"),                                   # retour annulé
             ("10/23/24", 6, "CDG", "MPL"), ("10/24/24", 7, "MPL", "CDG"),
             ("1/1/25", 8, "CDG", "JFK"), ("1/3/25", 9, "JFK", "MIA"),       # aller-retour imbriqué
             ("1/5/25", 10, "MIA", "JFK"), ("1/9/25", 11, "JFK", "CDG")]
    csv_text = FLIGHTY_HEADER + "\n" + "\n".join(_flighty_line(*line) for line in lines) + "\n"
    assert _import(auth_client, csv_text).status_code == 302
    trips = [(t.depart_date.isoformat(), t.return_date and t.return_date.isoformat(), t.origin_name[-4:-1],
              t.dest_name[-4:-1]) for t in _trips(db)]
    assert sorted(trips) == [
        ("2015-10-12", "2015-10-15", "CDG", "BCN"),
        ("2017-02-12", None, "ATL", "DAL"),
        ("2017-02-12", None, "CDG", "ATL"),
        ("2024-07-17", None, "ORY", "MPL"),
        ("2024-10-23", "2024-10-24", "CDG", "MPL"),
        ("2025-01-01", "2025-01-09", "CDG", "JFK"),
        ("2025-01-03", "2025-01-05", "JFK", "MIA"),
    ]
    paris_barcelona = next(t for t in _trips(db) if t.dest_name.endswith("(BCN)"))
    assert paris_barcelona.is_round_trip and paris_barcelona.service_number == "AF1 / AF2"
    assert paris_barcelona.carrier == "Air France" and paris_barcelona.notes is None


def test_flight_dates():
    from app.transfer.formats import flight_date, slash_order

    assert slash_order(["1/2/20", "13/2/20"]) == "dmy" and slash_order(["1/2/20", "2/13/20"]) == "mdy"
    assert flight_date("10/12/15", "mdy") == "2015-10-12" and flight_date("10/12/15", "dmy") == "2015-12-10"
    assert flight_date("2024-10-12T07:40", "mdy") == "2024-10-12" and flight_date("29.09.2023", "dmy") == "2023-09-29"
    assert flight_date("2/30/24", "mdy") is None and flight_date("hier", "mdy") is None


def test_unreadable_date_is_shown(auth_client, db):
    response = _import(auth_client, FLIGHTRADAR24.replace("2024-10-12", "hier"))
    assert "date de départ invalide : « hier »" in response.text


def test_landing_mentions_flight_import(client):
    html = client.get("/?lang=en").text
    assert "Import your flight history" in html
    assert '<a href="https://flighty.com/" rel="noopener">Flighty</a>' in html
    assert '<a href="https://my.flightradar24.com/" rel="noopener">myFlightradar24</a>' in html
