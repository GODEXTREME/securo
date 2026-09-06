"""Which state answers for which code, and which portal answers for which
state.

Two tables, both data. `UF_BY_CODE` is the IBGE code embedded in every
access key and never changes. `DEFAULT_CONSULTA_URLS` is the production
consultation endpoint per state as published by ENCAT; it changes, which
is why the service layer lets `app_settings` override it and why the URL
that came inside the QR code is always preferred over this table.

The table serves two purposes beyond fallback: it is the **allowlist** of
hosts the fetcher may ever contact (the QR URL is user input, so without
this the scan endpoint is a proxy into the network), and it is the
validation that a QR pointing somewhere else is treated as unsupported
rather than fetched.
"""
from __future__ import annotations

from urllib.parse import urlsplit

UF_BY_CODE: dict[str, str] = {
    "11": "RO", "12": "AC", "13": "AM", "14": "RR", "15": "PA", "16": "AP", "17": "TO",
    "21": "MA", "22": "PI", "23": "CE", "24": "RN", "25": "PB", "26": "PE", "27": "AL",
    "28": "SE", "29": "BA",
    "31": "MG", "32": "ES", "33": "RJ", "35": "SP",
    "41": "PR", "42": "SC", "43": "RS",
    "50": "MS", "51": "MT", "52": "GO", "53": "DF",
}

CODE_BY_UF: dict[str, str] = {uf: code for code, uf in UF_BY_CODE.items()}

# Production endpoints. Kept without a trailing "?" so a URL can be built
# uniformly; the QR versions that use named parameters append their own.
DEFAULT_CONSULTA_URLS: dict[str, str] = {
    "AC": "http://www.sefaznet.ac.gov.br/nfce/qrcode",
    "AL": "http://nfce.sefaz.al.gov.br/QRCode/consultarNFCe.jsp",
    "AM": "http://sistemas.sefaz.am.gov.br/nfceweb/consultarNFCe.jsp",
    "AP": "https://www.sefaz.ap.gov.br/nfce/nfcep.php",
    "BA": "http://nfe.sefaz.ba.gov.br/servicos/nfce/qrcode.aspx",
    "CE": "http://nfce.sefaz.ce.gov.br/pages/ShowNFCe.html",
    "DF": "http://www.fazenda.df.gov.br/nfce/qrcode",
    "ES": "http://app.sefaz.es.gov.br/ConsultaNFCe",
    "GO": "http://nfe.sefaz.go.gov.br/nfeweb/sites/nfce/danfeNFCe",
    "MA": "http://nfce.sefaz.ma.gov.br/portal/consultarNFCe.jsp",
    "MG": "https://nfce.fazenda.mg.gov.br/portalnfce/sistema/qrcode.xhtml",
    "MS": "http://www.dfe.ms.gov.br/nfce/qrcode",
    "MT": "http://www.sefaz.mt.gov.br/nfce/consultanfce",
    "PA": "https://appnfc.sefa.pa.gov.br/portal/view/consultas/nfce/nfceForm.seam",
    "PB": "http://www.receita.pb.gov.br/nfce",
    "PE": "http://nfce.sefaz.pe.gov.br/nfce/consulta",
    "PI": "http://www.sefaz.pi.gov.br/nfce/qrcode",
    "PR": "http://www.fazenda.pr.gov.br/nfce/qrcode",
    "RJ": "http://www4.fazenda.rj.gov.br/consultaNFCe/QRCode",
    "RN": "http://nfce.set.rn.gov.br/consultarNFCe.aspx",
    "RO": "http://www.nfce.sefin.ro.gov.br/consultanfce/consulta.jsp",
    "RR": "https://www.sefaz.rr.gov.br/nfce/servlet/qrcode",
    "RS": "https://www.sefaz.rs.gov.br/NFCE/NFCE-COM.aspx",
    # Not in the ENCAT table the design was written from; host taken from
    # the state's own portal. Allowlist only — no adapter exists yet.
    "SC": "https://sat.sef.sc.gov.br/nfce/consulta",
    "SE": "http://www.nfce.se.gov.br/nfce/qrcode",
    "SP": "https://www.nfce.fazenda.sp.gov.br/qrcode",
    "TO": "http://www.sefaz.to.gov.br/nfce/qrcode",
}


def host_of(url: str) -> str | None:
    """Lower-cased hostname of a URL, or None when it has none."""
    try:
        host = urlsplit(url).hostname
    except ValueError:
        return None
    return host.lower() if host else None


def allowed_hosts_for(uf: str, overrides: dict[str, str] | None = None) -> frozenset[str]:
    """Hosts the fetcher may contact for a state: the default portal's and,
    when an override is configured, that one's too. Both stay valid so a
    QR printed before the portal moved still resolves."""
    hosts: set[str] = set()
    for table in (DEFAULT_CONSULTA_URLS, overrides or {}):
        url = table.get(uf)
        host = host_of(url) if url else None
        if host:
            hosts.add(host)
    return frozenset(hosts)


def consulta_url_for(uf: str, overrides: dict[str, str] | None = None) -> str | None:
    if overrides and uf in overrides:
        return overrides[uf]
    return DEFAULT_CONSULTA_URLS.get(uf)
