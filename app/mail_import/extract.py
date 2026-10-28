"""Lecture des trajets d'un e-mail : corps texte et HTML (e-mails transférés compris), JSON-LD d'abord, puis
cartes Wallet jointes, puis texte."""
import re
from datetime import date
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser

from ..transfer.formats import pair_round_trips, validate_record
from .json_ld import json_ld_rows
from .text import text_rows
from .wallet import WalletError, is_pass, pass_rows


class _TextExtractor(HTMLParser):
    """Texte d'une page HTML, un bloc (cellule, paragraphe…) par ligne."""

    BLOCKS = {"br", "p", "div", "tr", "td", "th", "li", "table", "h1", "h2", "h3", "h4", "h5", "h6", "section"}

    def __init__(self):
        super().__init__()
        self.parts, self.skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "head"):
            self.skip += 1
        elif tag in self.BLOCKS:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style", "head"):
            self.skip = max(0, self.skip - 1)
        elif tag in self.BLOCKS:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)

    def text(self):
        lines = (re.sub(r"[ \t\xa0]+", " ", line).strip() for line in "".join(self.parts).splitlines())
        return "\n".join(line for line in lines if line)


def html_to_text(markup):
    parser = _TextExtractor()
    parser.feed(markup)
    parser.close()
    return parser.text()


def _bodies(msg):
    """(textes, pages HTML, cartes Wallet) de l'e-mail, y compris ceux d'un e-mail transféré en pièce jointe."""
    texts, pages, passes = [], [], []
    for part in msg.walk():
        if part.is_multipart():
            continue
        if is_pass(part.get_filename(), part.get_content_type()):
            passes.append(part.get_payload(decode=True) or b"")
            continue
        if part.get_content_maintype() != "text":
            continue
        try:
            content = part.get_content()
        except (LookupError, ValueError):  # jeu de caractères inconnu
            content = (part.get_payload(decode=True) or b"").decode("utf-8", "replace")
        if part.get_content_subtype() == "html":
            pages.append(content)
        elif part.get_content_subtype() == "plain":
            texts.append(content)
    return texts, pages, passes


def _reference_date(msg):
    try:
        return parsedate_to_datetime(str(msg.get("Date"))).date()
    except (TypeError, ValueError):
        return date.today()


def extract_trips(msg, lang):
    """(trajets validés, problèmes) d'un e-mail ; les trajets sont au format de validate_record."""
    texts, pages, passes = _bodies(msg)
    ref = _reference_date(msg)
    records, problems = [], []
    rows = [r for page in pages for r in json_ld_rows(page, lang)]
    # Cartes d'embarquement Wallet jointes : leur code-barres est plus sûr que le texte de l'e-mail.
    for data in passes if not rows else ():
        try:
            rows.extend(pass_rows(data, ref, lang))
        except WalletError as exc:
            problems.append(str(exc))
    if not rows:
        # Le texte tiré du HTML garde la structure (une cellule par ligne) ; le texte brut sert de secours.
        for text in [html_to_text(p) for p in pages] + texts:
            rows = text_rows(text, ref)
            if rows:
                break
    unique = {}
    for row in rows:
        unique.setdefault((row["transport_mode"], row["origin_name"], row["dest_name"], row["depart_date"]), row)
    paired = pair_round_trips(list(enumerate(unique.values())))
    for _line, raw in paired:
        record, errors = validate_record(raw)
        if errors:
            problems.extend(str(e) for e in errors)
        else:
            records.append(record)
    return records, problems
