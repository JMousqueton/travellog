"""Authentification de l'expéditeur : signature DKIM alignée sur le domaine de son adresse."""
import re

from flask import current_app


def dkim_aligned(raw, domain, dnsfunc=None):
    """Vrai si une signature DKIM valide de l'e-mail vient du domaine de l'expéditeur (ou d'un domaine parent
    ou enfant : alignement « relaxed » de DMARC). Les clés publiques sont lues dans le DNS (ou par dnsfunc)."""
    import dkim

    verifier = dkim.DKIM(raw, logger=current_app.logger, minkey=1024)
    signatures = len(re.findall(rb"^DKIM-Signature:", raw, flags=re.I | re.M))
    for index in range(signatures):
        try:
            if not verifier.verify(idx=index, **({"dnsfunc": dnsfunc} if dnsfunc else {})):
                continue
        except Exception:  # signature mal formée, DNS injoignable…
            continue
        signer = (verifier.domain or b"").decode("ascii", "replace").lower()
        if signer and (signer == domain or domain.endswith("." + signer) or signer.endswith("." + domain)):
            return True
    return False
