"""Suggestions des champs compagnie / opérateur et appareil : principales compagnies et principaux avions.

Le formulaire propose d'abord les valeurs déjà saisies par l'utilisateur, puis ces listes (sans doublon).
"""
AIRLINES = [
    "Air France", "KLM", "Transavia", "HOP!", "Air Corsica", "Corsair", "Air Caraïbes", "French bee",
    "Air Tahiti Nui", "Lufthansa", "Eurowings", "Condor", "Swiss", "Austrian Airlines", "Brussels Airlines",
    "British Airways", "Virgin Atlantic", "Aer Lingus", "Iberia", "Vueling", "Air Europa", "Volotea",
    "TAP Air Portugal", "ITA Airways", "SAS", "Norwegian", "Finnair", "Icelandair", "LOT Polish Airlines",
    "Aegean Airlines", "Air Serbia", "Croatia Airlines", "easyJet", "Ryanair", "Wizz Air", "Turkish Airlines",
    "Pegasus Airlines", "Royal Air Maroc", "Tunisair", "Air Algérie", "EgyptAir", "Ethiopian Airlines",
    "Kenya Airways", "Air Mauritius", "Air Austral", "Emirates", "Qatar Airways", "Etihad Airways",
    "Saudia", "Air Canada", "Air Transat", "WestJet", "Delta Air Lines", "American Airlines",
    "United Airlines", "JetBlue", "Southwest Airlines", "Alaska Airlines", "Aeroméxico", "Copa Airlines",
    "Avianca", "LATAM Airlines", "Singapore Airlines", "Cathay Pacific", "Japan Airlines",
    "All Nippon Airways", "Korean Air", "Thai Airways", "Vietnam Airlines", "Air India", "Air China",
    "China Eastern", "China Southern", "Qantas", "Air New Zealand",
]

RAIL_OPERATORS = [
    "SNCF", "TGV inOui", "Ouigo", "TER", "Intercités", "Eurostar", "TGV Lyria", "Deutsche Bahn", "ÖBB",
    "Nightjet", "SBB CFF FFS", "Trenitalia", "Italo", "Renfe", "Iryo", "Ouigo España", "SNCB", "NS",
    "CFL", "Comboios de Portugal", "Avanti West Coast", "LNER", "Great Western Railway", "ScotRail",
    "Caledonian Sleeper", "Irish Rail", "PKP Intercity", "České dráhy", "RegioJet", "Leo Express", "MÁV",
    "SJ", "VR", "Vy", "DSB", "Flixtrain", "European Sleeper", "Westbahn", "Amtrak", "VIA Rail",
    "JR East", "JR Central", "JR West", "Korail", "China Railway", "Indian Railways",
]

AIRCRAFT = [
    "Airbus A220-100", "Airbus A220-300", "Airbus A318", "Airbus A319", "Airbus A319neo", "Airbus A320",
    "Airbus A320neo", "Airbus A321", "Airbus A321neo", "Airbus A321XLR", "Airbus A330-200", "Airbus A330-300",
    "Airbus A330-900neo", "Airbus A340-300", "Airbus A350-900", "Airbus A350-1000", "Airbus A380-800",
    "Boeing 717-200", "Boeing 737-700", "Boeing 737-800", "Boeing 737-900", "Boeing 737 MAX 8", "Boeing 737 MAX 9",
    "Boeing 747-400", "Boeing 747-8", "Boeing 757-200", "Boeing 767-300ER", "Boeing 777-200ER", "Boeing 777-300ER",
    "Boeing 787-8", "Boeing 787-9", "Boeing 787-10", "Embraer 170", "Embraer 175", "Embraer 190", "Embraer 195",
    "Embraer 190-E2", "Embraer 195-E2", "ATR 42-600", "ATR 72-600", "De Havilland Canada Dash 8-400",
    "Bombardier CRJ700", "Bombardier CRJ900", "Bombardier CRJ1000", "Comac C919",
]

SUGGESTIONS = {"carrier": {"plane": AIRLINES, "train": RAIL_OPERATORS}, "vehicle": {"plane": AIRCRAFT}}


def _suggestions(user, mode, field):
    """Valeurs déjà saisies par l'utilisateur pour ce mode (les plus fréquentes d'abord), puis la liste."""
    from collections import Counter

    used = Counter()
    for trip in user.trips.filter_by(transport_mode=mode):
        for name in (getattr(trip, field) or "").split(" / "):  # « A321 / A320 » : aller et retour
            if name.strip():
                used[name.strip()] += 1
    names = [name for name, _count in used.most_common()] + SUGGESTIONS[field].get(mode, [])
    return list(dict.fromkeys(names))


def carrier_suggestions(user, mode):
    return _suggestions(user, mode, "carrier")


def vehicle_suggestions(user, mode):
    return _suggestions(user, mode, "vehicle")


# --- Logos (logo.dev) ------------------------------------------------------------------------------------------

def logo_url(name):
    """Logo de la compagnie ou de l'opérateur, cherché par son nom (CDN logo.dev, clé publiable LOGO_DEV_TOKEN) ;
    None sans clé."""
    from urllib.parse import quote

    from flask import current_app

    token = current_app.config.get("LOGO_DEV_TOKEN")
    if not token or not name or not name.strip():
        return None
    return f"https://img.logo.dev/name/{quote(name.strip(), safe='')}?token={quote(token)}&size=64&format=webp&retina=true"
