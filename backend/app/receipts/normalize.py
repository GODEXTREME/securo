"""Turning a receipt line into something comparable.

Three pure functions, each answering one question:

  - `fingerprint`: does this description *look like* that one? Only ever a
    suggestion for a human — never an identity. Uppercase, accents gone,
    size tokens gone, point-of-sale abbreviations expanded from a versioned
    dictionary, unit appended.
  - `parse_size`: what does the description say about the package —
    `450G`, `1,5L`, `C/12`, `6X350ML`?
  - `normalize_price`: what is the price per kilo / litre / unit, and is
    comparing on it honest? For a weighed item it is the only honest
    comparison; for a packaged SKU the identity already fixes the size.

`ABBREV_V1` is data. A new abbreviation is a one-line change here; the
version in the name is bumped when an existing entry changes meaning, so
stored fingerprints can be told apart from fresh ones.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

ABBREV_VERSION = 1

#: Point-of-sale abbreviations → words. Whole tokens only, applied after
#: accent stripping and upper-casing. Deliberately conservative: an entry
#: that could mean two things (`PRE`, `MAR`) is left out.
ABBREV_V1: dict[str, str] = {
    "IOG": "IOGURTE", "IOGT": "IOGURTE",
    "AG": "AGUA", "AGUA MIN": "AGUA MINERAL", "AG MIN": "AGUA MINERAL",
    "REFR": "REFRIGERANTE", "REFRIG": "REFRIGERANTE",
    "INT": "INTEGRAL", "INTE": "INTEGRAL",
    "DESN": "DESNATADO", "SEMIDESN": "SEMIDESNATADO",
    "TRAD": "TRADICIONAL", "NAT": "NATURAL",
    "CHOC": "CHOCOLATE", "MOR": "MORANGO", "MORG": "MORANGO",
    "BISC": "BISCOITO", "BOLACH": "BOLACHA",
    "CERV": "CERVEJA", "LEIT": "LEITE", "QJO": "QUEIJO", "PRES": "PRESUNTO",
    "MUSS": "MUSSARELA", "MUCA": "MUSSARELA",
    "SAB": "SABAO", "DET": "DETERGENTE", "AMAC": "AMACIANTE",
    "PAP": "PAPEL", "HIG": "HIGIENICO",
    "ARR": "ARROZ", "FEIJ": "FEIJAO", "ACUC": "ACUCAR", "CAF": "CAFE",
    "MANT": "MANTEIGA", "MARG": "MARGARINA", "OL": "OLEO",
    "SUC": "SUCO", "LAR": "LARANJA", "LARANJ": "LARANJA",
    "FR": "FRANGO", "FRG": "FRANGO", "CARN": "CARNE", "BOV": "BOVINA", "SUIN": "SUINA",
    "PC": "PACOTE", "PCT": "PACOTE", "CX": "CAIXA", "GARR": "GARRAFA", "LATA": "LATA",
    "UN": "UNIDADE", "UND": "UNIDADE", "UNID": "UNIDADE",
    "KG": "QUILO", "GR": "GRAMA", "LT": "LITRO",
    "C/GAS": "COM GAS", "S/GAS": "SEM GAS",
    "GRD": "GRANDE", "PEQ": "PEQUENO", "MED": "MEDIO",
    "TOMAT": "TOMATE", "CEB": "CEBOLA", "BAT": "BATATA", "CEN": "CENOURA",
    "BAN": "BANANA", "MAC": "MACA", "LIM": "LIMAO",
}

_SIZE_RE = re.compile(
    r"(?<![A-Z0-9])(?:(?P<pack>\d{1,3})\s*[Xx]\s*)?(?P<value>\d+(?:[.,]\d+)?)\s*(?P<unit>KG|G|GR|L|LT|ML|MG)(?![A-Z])",
    re.IGNORECASE,
)
_PACK_RE = re.compile(r"(?:C/\s*(?P<c>\d{1,3})\b)|(?:\b(?P<n>\d{1,3})\s*(?:UN|UND|UNID)\b)", re.IGNORECASE)

_UNIT_TO_BASE: dict[str, tuple[str, Decimal]] = {
    # commercial unit → (base unit, multiplier to base)
    "KG": ("kg", Decimal("1")),
    "KILO": ("kg", Decimal("1")),
    "G": ("kg", Decimal("0.001")),
    "GR": ("kg", Decimal("0.001")),
    "L": ("l", Decimal("1")),
    "LT": ("l", Decimal("1")),
    "LTS": ("l", Decimal("1")),
    "ML": ("l", Decimal("0.001")),
}
_SIZE_TO_BASE: dict[str, tuple[str, Decimal]] = {
    "KG": ("kg", Decimal("1")), "G": ("kg", Decimal("0.001")), "GR": ("kg", Decimal("0.001")),
    "MG": ("kg", Decimal("0.000001")),
    "L": ("l", Decimal("1")), "LT": ("l", Decimal("1")), "ML": ("l", Decimal("0.001")),
}


def strip_accents(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))


@dataclass(frozen=True)
class Size:
    value: Optional[Decimal]
    unit: Optional[str]      # canonical: kg | g | l | ml (lower-case)
    pack_count: Optional[int]


def parse_size(description: str) -> Size:
    """`AG MIN C/GAS 1,5L` → 1.5 l; `CAFE 500G` → 500 g; `CERV 6X350ML` →
    350 ml × 6; `OVOS C/12` → pack 12. Absence is `None`, never a guess."""
    text = strip_accents(description).upper()
    value: Optional[Decimal] = None
    unit: Optional[str] = None
    pack: Optional[int] = None
    m = _SIZE_RE.search(text)
    if m:
        value = Decimal(m.group("value").replace(",", "."))
        raw_unit = m.group("unit").upper()
        unit = {"GR": "g", "LT": "l"}.get(raw_unit, raw_unit.lower())
        if m.group("pack"):
            pack = int(m.group("pack"))
    p = _PACK_RE.search(text)
    if p and pack is None:
        pack = int(p.group("c") or p.group("n"))
    return Size(value=value, unit=unit, pack_count=pack)


def fingerprint(description: str, unit: str | None = None) -> str:
    text = strip_accents(description).upper()
    text = text.replace("C/", " C/").replace("S/", " S/")
    text = _SIZE_RE.sub(" ", text)
    text = _PACK_RE.sub(" ", text)
    text = re.sub(r"[^A-Z0-9/ ]+", " ", text)
    tokens = [t for t in text.split() if t]
    # Two-token expansions first ("AG MIN"), then single tokens.
    out: list[str] = []
    i = 0
    while i < len(tokens):
        pair = " ".join(tokens[i:i + 2])
        if pair in ABBREV_V1:
            out.extend(ABBREV_V1[pair].split())
            i += 2
            continue
        tok = tokens[i]
        out.extend(ABBREV_V1.get(tok, tok).split())
        i += 1
    if unit:
        out.append(strip_accents(unit).upper())
    return " ".join(out).strip()


@dataclass(frozen=True)
class Normalized:
    price: Optional[Decimal]
    base_unit: Optional[str]   # kg | l | un
    comparable: bool


def normalize_price(
    unit: str,
    quantity: Decimal,
    unit_price: Decimal,
    size: Size,
) -> Normalized:
    """Price per base unit. For a weighed or metered line the commercial
    unit *is* the base (R$/kg, R$/l). For a packaged line the size in the
    description gives R$/kg or R$/l when it is there and R$/unit when it
    is not; `pack_count` divides either way."""
    if unit_price <= 0 or quantity <= 0:
        return Normalized(None, None, False)
    commercial = strip_accents(unit).upper()
    if commercial in _UNIT_TO_BASE:
        base, factor = _UNIT_TO_BASE[commercial]
        # unit_price is per commercial unit; per base unit = price / factor
        return Normalized(_q(unit_price / factor), base, True)
    pack = Decimal(size.pack_count or 1)
    if size.value and size.unit and size.unit.upper() in _SIZE_TO_BASE:
        base, factor = _SIZE_TO_BASE[size.unit.upper()]
        amount_in_base = size.value * factor * pack
        if amount_in_base > 0:
            return Normalized(_q(unit_price / amount_in_base), base, True)
    return Normalized(_q(unit_price / pack), "un", True)


def _q(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.0001"))
