"""Trajets lus dans le texte : numéros de vol, codes d'aéroports et dates (en cinq langues)."""
import re
import unicodedata
from datetime import date, timedelta

from ..airports import find_airline_by_iata, find_airport
from .rows import airport_place, make_row

REGION_CHARS = 600  # texte lu autour d'un numéro de vol pour y trouver aéroports et date

FLIGHT_NUMBER = re.compile(r"\b([A-Z]{2}|[A-Z][0-9]|[0-9][A-Z]) ?(\d{1,4})\b")
# « Paris (CDG) », un code seul dans sa cellule, ou une paire « CDG → BCN ».
AIRPORT_CODES = [re.compile(r"\(([A-Z]{3})\)"), re.compile(r"^\s*([A-Z]{3})\s*$", re.M)]
AIRPORT_PAIR = re.compile(r"\b([A-Z]{3}) ?(?:→|⇒|➔|->|>|–|—|-|/|to|à|nach) ?([A-Z]{3})\b")

MONTHS = {}
for number, names in enumerate((
    "january jan janvier janv enero ene januar gennaio gen",
    "february feb fevrier fevr fev febrero februar febbraio",
    "march mar mars marzo marz maerz",
    "april apr avril avr abril abr aprile",
    "may mai mayo maggio mag",
    "june jun juin junio juni giugno giu",
    "july jul juillet juil julio juli luglio lug",
    "august aug aout agosto ago",
    "september sept sep septembre septiembre setiembre settembre set",
    "october oct octobre octubre oktober okt ottobre ott",
    "november nov novembre noviembre",
    "december dec decembre diciembre dic dezember dez dicembre",
), start=1):
    for name in names.split():
        MONTHS[name] = number
_MONTH = "|".join(sorted(MONTHS, key=len, reverse=True))
DATE_PATTERNS = [
    ("ymd", re.compile(r"\b(\d{4})-(\d{2})-(\d{2})(?=[T ]\d|\b)")),
    ("num", re.compile(r"\b(\d{1,2})[/.](\d{1,2})[/.](\d{4}|\d{2})\b")),
    # « 12 mars 2026 », « 1er avril », « 12MAR26 » (année sur deux chiffres seulement collée au mois).
    ("dmy", re.compile(rf"\b(\d{{1,2}})(?:er|st|nd|rd|th|\.)? ?(?:de )?({_MONTH})(?![a-z])\.?"
                       rf"(?:(\d{{2}})(?!\d)|,? ?(?:de )?(\d{{4}})(?!\d))?", re.I)),
    ("mdy", re.compile(rf"\b({_MONTH})(?![a-z])\.? (\d{{1,2}})(?:st|nd|rd|th)?(?!\d)(?:,? (\d{{4}})(?!\d))?", re.I)),
]


def _ascii(text):
    """Accents retirés caractère par caractère (les positions restent celles du texte d'origine)."""
    return "".join(unicodedata.normalize("NFKD", c)[0] if c.strip() else " " for c in text)


def find_dates(text, ref):
    """[(position, date)] des dates du texte. Une date sans année est la plus proche après l'e-mail
    (un mois plus tôt au plus : un e-mail transféré après le départ)."""
    plain = _ascii(text)
    order = _numeric_order([m.groups() for m in DATE_PATTERNS[1][1].finditer(plain)])
    found, taken = [], []
    for kind, pattern in DATE_PATTERNS:
        for match in pattern.finditer(plain):
            if any(start < match.end() and match.start() < end for start, end in taken):
                continue
            groups = match.groups()
            if kind == "ymd":
                year, month, day = groups
            elif kind == "num":
                day, month, year = groups if order == "dmy" else (groups[1], groups[0], groups[2])
            elif kind == "dmy":
                day, month, year = groups[0], MONTHS[groups[1].lower()], groups[2] or groups[3]
            else:
                month, day, year = MONTHS[groups[0].lower()], groups[1], groups[2]
            value = _make_date(year, month, day, ref)
            if value is not None:
                found.append((match.start(), value))
                taken.append(match.span())
    return sorted(found)


def _numeric_order(dates):
    """« dmy » ou « mdy » pour les dates JJ/MM/AAAA d'un e-mail, d'après celles qui lèvent le doute
    (jour d'abord par défaut, l'usage le plus courant hors des États-Unis)."""
    for first, second, _year in dates:
        if int(second) > 12:
            return "mdy"
        if int(first) > 12:
            return "dmy"
    return "dmy"


def _make_date(year, month, day, ref):
    try:
        if year:
            year = int(year) + (2000 if len(str(year)) == 2 else 0)
            value = date(year, int(month), int(day))
        else:
            value = date(ref.year, int(month), int(day))
            if value < ref - timedelta(days=31):
                value = date(ref.year + 1, int(month), int(day))
    except ValueError:
        return None
    return value if date(1950, 1, 1) <= value <= ref + timedelta(days=2 * 366) else None


def _airport_codes(text):
    """[(position, aéroport)] des codes d'aéroports connus, dans l'ordre du texte."""
    found = {}
    for pattern in AIRPORT_CODES:
        for match in pattern.finditer(text):
            found.setdefault(match.start(1), match.group(1))
    for match in AIRPORT_PAIR.finditer(text):
        found.setdefault(match.start(1), match.group(1))
        found.setdefault(match.start(2), match.group(2))
    return [(pos, airport) for pos, code in sorted(found.items()) if (airport := find_airport(code))]


# En-tête d'un e-mail transféré (« From: … / Sent: … / Subject: … », en cinq langues) : sa date est celle du
# transfert et son objet répète l'itinéraire ; il est effacé avant la lecture.
FORWARD_FIELD = re.compile(r"^[ >*]*(from|sent|date|to|cc|subject|de|envoy[ée]|le|[àa]|objet|von|gesendet|an|"
                           r"betreff|datum|enviado|para|asunto|fecha|da|inviato|data|oggetto)\s*:", re.I)
FORWARD_SENDER = {"from", "de", "von", "da"}


def strip_forward_headers(text):
    """Remplace par des espaces (les positions ne changent pas) chaque bloc d'au moins deux lignes d'en-tête
    consécutives qui commence par l'expéditeur."""
    lines = text.splitlines(keepends=True)
    out, i = [], 0
    while i < len(lines):
        j = i
        while j < len(lines) and FORWARD_FIELD.match(lines[j]):
            j += 1
        block = lines[i:j]
        if len(block) >= 2 and FORWARD_FIELD.match(block[0]).group(1).lower() in FORWARD_SENDER:
            out.extend(re.sub(r"[^\n]", " ", line) for line in block)
            i = j
        else:
            out.append(lines[i])
            i += 1
    return "".join(out)


def text_rows(text, ref):
    """Vols du texte : chaque numéro de vol avec les deux premiers aéroports et la première date de sa zone.
    La zone est d'abord ce qui suit le numéro (jusqu'au suivant) ; à défaut, ce qui le précède (aéroports
    écrits avant le numéro). Un numéro cité plusieurs fois (résumé, puis détail) ne donne qu'un vol."""
    text = strip_forward_headers(text)
    codes, dates = _airport_codes(text), find_dates(text, ref)
    numbers = [(m.start(), m.end(), airline, m.group(1) + str(int(m.group(2))))
               for m in FLIGHT_NUMBER.finditer(text) if (airline := find_airline_by_iata(m.group(1)))]
    numbers = [n for n in numbers if any(n[0] - REGION_CHARS <= pos <= n[1] + REGION_CHARS for pos, _a in codes)]
    if numbers:
        found = {}  # numéro → (zone suivante ?, ligne)
        for i, (start, end, airline, number) in enumerate(numbers):
            after = _flight_in(codes, dates, start, numbers[i + 1][0] if i + 1 < len(numbers) else end + REGION_CHARS,
                               start, airline["name"], number)
            row = after or _flight_in(codes, dates, numbers[i - 1][1] if i else max(0, start - REGION_CHARS), end,
                                      start, airline["name"], number)
            if row and (number not in found or (after and not found[number][0])):
                found[number] = (bool(after), row)
        return [row for _after, row in found.values()]
    rows = []
    for match in AIRPORT_PAIR.finditer(text):  # sans numéro de vol : paires « CDG → BCN »
        origin, dest = find_airport(match.group(1)), find_airport(match.group(2))
        if origin and dest:
            row = _flight_in([(match.start(1), origin), (match.start(2), dest)], dates,
                             match.start(), match.end() + REGION_CHARS, match.start())
            if row:
                rows.append(row)
    return rows


def _flight_in(codes, dates, low, high, anchor, carrier="", number=""):
    airports = []
    for pos, airport in codes:
        if low <= pos <= high and (not airports or airports[-1]["iata"] != airport["iata"]):
            airports.append(airport)
    day = next((d for pos, d in dates if low <= pos <= high), None)
    if day is None:  # date écrite avant la zone (en tête de l'e-mail, par exemple)
        near = [(abs(pos - anchor), d) for pos, d in dates if abs(pos - anchor) <= REGION_CHARS]
        day = min(near)[1] if near else None
    if len(airports) < 2 or day is None:
        return None
    return make_row(day.isoformat(), "plane", airport_place(airports[0]), airport_place(airports[1]),
                carrier=carrier, number=number)
