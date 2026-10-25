"""Suggestions pour le champ compagnie / opérateur : principales compagnies aériennes et ferroviaires.

Le formulaire propose d'abord celles déjà saisies par l'utilisateur, puis ces listes (sans doublon).
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

SUGGESTIONS = {"plane": AIRLINES, "train": RAIL_OPERATORS}


def carrier_suggestions(user, mode):
    """Compagnies déjà saisies par l'utilisateur pour ce mode (les plus fréquentes d'abord), puis la liste."""
    from collections import Counter

    used = Counter()
    for trip in user.trips.filter_by(transport_mode=mode):
        for name in (trip.carrier or "").split(" / "):
            if name.strip():
                used[name.strip()] += 1
    names = [name for name, _count in used.most_common()] + SUGGESTIONS.get(mode, [])
    return list(dict.fromkeys(names))
