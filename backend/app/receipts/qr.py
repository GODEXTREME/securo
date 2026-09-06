"""The QR code on the receipt, and the 44-digit access key inside it.

Pure: nothing here touches the network or the database, so a wrong key
is rejected before a single request is made, and every shape of input
the UI accepts — the URL read from the QR, the bare key typed from the
printed footer, a pasted block of text — collapses to one `QrPayload`.

Three QR layouts exist and the parser decides by shape, not by version
string, because the version string is one of the things that varies:

  - v1.00: named query parameters (`?chNFe=…&nVersao=100&tpAmb=…`)
  - v2.00 / v3.00, normal emission: `?p=chNFe|nVersao|tpAmb|cIdToken|cHash`
  - v2.00 / v3.00, contingency: nine fields, with `dhEmi|vNF|vICMS|digVal`
    inserted after `tpAmb`

Policy — whether a valid key is one we *want* (production only, NFC-e
only) — is separate from parsing (`policy_rejection`), so an NF-e key
parses fine and the service decides what to tell the user.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from itertools import cycle
from urllib.parse import parse_qs, unquote, urlsplit

from app.receipts.uf_table import UF_BY_CODE

NFCE_MODEL = "65"


class QrError(ValueError):
    """The payload cannot become a `QrPayload`. `code` is stable and
    machine-readable — the UI maps it to a message — and the text is
    for logs."""

    def __init__(self, code: str, message: str | None = None):
        super().__init__(message or code)
        self.code = code


def access_key_check_digit(first43: str) -> int:
    """Modulo-11 over the first 43 digits, weights 2…9 cycling from the
    right. A remainder of 0 or 1 yields 0."""
    total = sum(int(d) * w for d, w in zip(reversed(first43), cycle(range(2, 10))))
    remainder = total % 11
    return 0 if remainder < 2 else 11 - remainder


@dataclass(frozen=True)
class AccessKey:
    key: str
    c_uf: str
    uf: str
    year: int
    month: int
    issuer_cnpj: str
    model: str
    series: int
    number: int
    tp_emis: int
    c_nf: str
    check_digit: int

    @property
    def is_nfce(self) -> bool:
        return self.model == NFCE_MODEL

    @property
    def issuer_cnpj_root(self) -> str:
        """The first eight digits: the legal entity, shared by every branch
        of a chain. This is what scopes a store-internal product code."""
        return self.issuer_cnpj[:8]


_SEPARATORS = re.compile(r"[\s.\-]")


def parse_access_key(raw: str) -> AccessKey:
    digits = _SEPARATORS.sub("", raw or "")
    if not digits:
        raise QrError("empty")
    if not digits.isdigit():
        raise QrError("not_digits")
    if len(digits) != 44:
        raise QrError("length", f"expected 44 digits, got {len(digits)}")
    if access_key_check_digit(digits[:43]) != int(digits[43]):
        raise QrError("check_digit")
    c_uf = digits[0:2]
    uf = UF_BY_CODE.get(c_uf)
    if uf is None:
        raise QrError("unknown_uf", f"cUF {c_uf} is not a state")
    month = int(digits[4:6])
    if not 1 <= month <= 12:
        raise QrError("bad_month")
    return AccessKey(
        key=digits,
        c_uf=c_uf,
        uf=uf,
        year=2000 + int(digits[2:4]),
        month=month,
        issuer_cnpj=digits[6:20],
        model=digits[20:22],
        series=int(digits[22:25]),
        number=int(digits[25:34]),
        tp_emis=int(digits[34]),
        c_nf=digits[35:43],
        check_digit=int(digits[43]),
    )


@dataclass(frozen=True)
class QrPayload:
    key: AccessKey
    #: The URL exactly as read. Preferred over the state table for the
    #: consultation because it carries the signature the portal checks.
    url: str | None
    #: 100, 200 or 300. Zero when only the bare key was given.
    version: int
    tp_amb: int
    c_id_token: str | None
    signature: str | None
    contingency: bool = False
    issued_at: datetime | None = None
    total: Decimal | None = None
    icms: Decimal | None = None
    dig_val: str | None = None

    @property
    def has_signature(self) -> bool:
        return bool(self.signature)


_URL_RE = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)
_KEY_RE = re.compile(r"\d{44}")
_VERSIONS = {"1": 100, "100": 100, "2": 200, "200": 200, "3": 300, "300": 300}


def parse_qr_payload(text: str) -> QrPayload:
    """Accepts the QR URL, a pasted block containing one, or a bare key
    (with or without the printed grouping spaces)."""
    text = (text or "").strip()
    if not text:
        raise QrError("empty")
    found = _URL_RE.search(text)
    if found:
        return _parse_url(found.group(0).rstrip(".,;)"))
    compact = _SEPARATORS.sub("", text)
    key_match = _KEY_RE.search(compact)
    if key_match:
        key = parse_access_key(key_match.group(0))
        # A bare key says nothing about the environment; production is the
        # only one a printed receipt comes from.
        return QrPayload(key=key, url=None, version=0, tp_amb=1, c_id_token=None, signature=None)
    raise QrError("unrecognized")


def _parse_url(url: str) -> QrPayload:
    parts = urlsplit(url)
    query = parse_qs(parts.query, keep_blank_values=True)
    if "p" in query:
        return _parse_positional(url, query["p"][0])
    if "chNFe" in query:
        return _parse_named(url, query)
    if "|" in parts.query:
        # A few portals were seen dropping the `p=` name while keeping the
        # pipe-separated layout.
        return _parse_positional(url, unquote(parts.query))
    raise QrError("qr_format", "no `p=` and no `chNFe=` in the query string")


def _version(raw: str) -> int:
    try:
        return _VERSIONS[raw.strip()]
    except KeyError:
        raise QrError("qr_version", f"unknown nVersao {raw!r}") from None


def _tp_amb(raw: str) -> int:
    raw = raw.strip()
    if raw not in ("1", "2"):
        raise QrError("qr_tpamb", f"tpAmb must be 1 or 2, got {raw!r}")
    return int(raw)


def _decimal(raw: str | None) -> Decimal | None:
    if raw is None or raw.strip() == "":
        return None
    try:
        return Decimal(raw.strip().replace(",", "."))
    except InvalidOperation:
        return None


def _hex_datetime(raw: str | None) -> datetime | None:
    """v2 contingency carries `dhEmi` as the hex encoding of the ISO string;
    v1 carries it plain. Try both, answer None rather than guess."""
    if not raw:
        return None
    candidates = [raw.strip()]
    try:
        candidates.insert(0, bytes.fromhex(raw.strip()).decode("ascii"))
    except ValueError:
        pass
    for text in candidates:
        try:
            return datetime.fromisoformat(text)
        except ValueError:
            continue
    return None


def _parse_positional(url: str, p: str) -> QrPayload:
    fields = [f.strip() for f in p.split("|")]
    if len(fields) == 5:
        ch, ver, amb, token, sig = fields
        return QrPayload(
            key=parse_access_key(ch), url=url, version=_version(ver), tp_amb=_tp_amb(amb),
            c_id_token=token or None, signature=sig or None,
        )
    if len(fields) == 9:
        ch, ver, amb, dh, vnf, vicms, dig, token, sig = fields
        return QrPayload(
            key=parse_access_key(ch), url=url, version=_version(ver), tp_amb=_tp_amb(amb),
            c_id_token=token or None, signature=sig or None, contingency=True,
            issued_at=_hex_datetime(dh), total=_decimal(vnf), icms=_decimal(vicms),
            dig_val=dig or None,
        )
    raise QrError("qr_fields", f"expected 5 or 9 fields, got {len(fields)}")


def _parse_named(url: str, query: dict[str, list[str]]) -> QrPayload:
    def one(name: str) -> str | None:
        values = query.get(name)
        return values[0] if values and values[0] != "" else None

    ch = one("chNFe")
    if not ch:
        raise QrError("qr_format")
    ver = one("nVersao") or "100"
    return QrPayload(
        key=parse_access_key(ch), url=url, version=_version(ver), tp_amb=_tp_amb(one("tpAmb") or "1"),
        c_id_token=one("cIdToken"), signature=one("cHashQRCode"),
        contingency=one("dhEmi") is not None,
        issued_at=_hex_datetime(one("dhEmi")), total=_decimal(one("vNF")), icms=_decimal(one("vICMS")),
        dig_val=one("digVal"),
    )


def policy_rejection(payload: QrPayload) -> str | None:
    """Why a *valid* payload is still not one to fetch, or None.

    Kept apart from parsing so the reasons can be shown as what they are:
    a homologation note is a real note from a test environment, and an
    NF-e is a real invoice that simply is not a consumer receipt.
    """
    if payload.tp_amb == 2:
        return "homolog"
    if not payload.key.is_nfce:
        return "not_nfce"
    return None
