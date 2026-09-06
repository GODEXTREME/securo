"""GTIN normalisation: one canonical 14-digit key for every barcode that
names the same trade item.

EAN-8, UPC-A (12), EAN-13 and ITF-14 all encode the same identifier at
different widths; GS1 defines them as equal once left-padded with zeros
to 14 digits, and the check digit survives the padding because a zero
weighs nothing. So the catalogue keys on GTIN-14 and every reader — the
portal's `cEAN`, the phone's barcode scanner, a typed number — goes
through here first.

`None` is the honest answer for anything that is not a valid GTIN: the
portal's literal `SEM GTIN`, an all-zero placeholder, a wrong check
digit. A wrong digit is far more likely to be an OCR or typing error
than a real product, and a wrong key in the catalogue is worse than a
missing one.
"""
from __future__ import annotations

import re

_LENGTHS = (8, 12, 13, 14)


def gs1_check_digit(body: str) -> int:
    """Check digit for a GS1 body (the identifier without its last digit).
    Weights alternate 3, 1, … starting from the rightmost body digit."""
    total = 0
    for index, char in enumerate(reversed(body)):
        total += int(char) * (3 if index % 2 == 0 else 1)
    return (10 - total % 10) % 10


def normalize_gtin(raw: str | None) -> str | None:
    """A GTIN-14 with a valid check digit, or None."""
    if not raw:
        return None
    digits = re.sub(r"\D", "", raw)
    if len(digits) not in _LENGTHS:
        return None
    if set(digits) == {"0"}:
        return None
    padded = digits.zfill(14)
    if gs1_check_digit(padded[:13]) != int(padded[13]):
        return None
    return padded
