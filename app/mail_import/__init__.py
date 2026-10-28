"""Import de voyages par e-mail : `flask mail-import` relève la boîte IMAP (IMAP_SERVER…), toutes les 5 minutes
par cron.

Un e-mail n'est accepté que si son expéditeur (From) est un compte, ou une adresse d'import confirmée
d'un compte (ImportAddress), et que l'e-mail porte une signature DKIM
valide de ce domaine (sans elle, n'importe qui pourrait ajouter des trajets à un compte). Les trajets sont
lus d'abord dans les données schema.org (JSON-LD) que la plupart des compagnies et agences ajoutent à leurs
confirmations, sinon dans le texte : numéro de vol, codes d'aéroports et date.

- trajets trouvés : ajoutés au compte (sauf doublons), e-mail supprimé de la boîte ;
- rien de reconnu : ticket ouvert au nom du compte « Import Error » avec l'e-mail brut, e-mail laissé ;
- expéditeur inconnu ou non authentifié : e-mail ignoré et laissé.

Chaque e-mail est noté dans la table mail_imports : il n'est traité (et son ticket ouvert) qu'une fois.

Modules :
- mailbox : relève de la boîte IMAP ;
- processing : traitement d'un e-mail (expéditeur, trajets enregistrés, ticket d'échec, compte rendu) ;
- authentication : signature DKIM de l'expéditeur ;
- extract : lecture des trajets, d'abord en JSON-LD (json_ld), sinon dans le texte (text).
"""
from .authentication import dkim_aligned
from .extract import extract_trips, html_to_text
from .mailbox import run
from .processing import Outcome, account_for, import_error_account, process
from .text import find_dates, strip_forward_headers

__all__ = ["Outcome", "account_for", "dkim_aligned", "extract_trips", "find_dates", "html_to_text",
           "import_error_account", "process", "run", "strip_forward_headers"]
