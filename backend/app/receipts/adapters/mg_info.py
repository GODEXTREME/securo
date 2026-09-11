"""Parser for Minas Gerais's own NFC-e view (`infoqrcode.xhtml`).

A fourth layout, and the state's alone: not the shared ENCAT DANFE that
Espírito Santo and Rio de Janeiro render, not the national detailed XSLT
that Goiás and Rio de Janeiro reach one page further in, and not the raw
`procNFe` Pernambuco serves. It is a JSF page that prints the note into
Bootstrap tables, with the fiscal detail folded into an accordion.

Two consequences worth naming before the code.

**No barcode.** The item line carries the merchant's own product code
("Código: 2165") and nothing else, so Minas Gerais joins Espírito Santo
and Rio de Janeiro: a product from here is comparable within its chain
until somebody scans the barcode by hand.

**Two number formats on one page.** The item table prints money the
Brazilian way — `R$ 6,00` — and the summary rows print what Java's
`toString()` gives — `6.00`. Read a summary row as Brazilian and `6,50`
and `6.50` both come out as 6; read an item as plain and `1.234,56`
comes out as 1.234. So the two are read by different functions, on
purpose, and the arithmetic the canonical model checks is what catches
it if this page ever changes its mind.
"""
from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Optional

from bs4 import BeautifulSoup, Tag

from app.receipts.adapters.base import FetchedPage, PageKind, ParseError
from app.receipts.adapters.tabresult import parse_brl
from app.receipts.canonical import (
    ZERO,
    CanonicalItem,
    CanonicalReceipt,
    Issuer,
    Payment,
    Totals,
)

_DIGITS = re.compile(r"\D")
#: `05/09/2026 10:42:13`, as the portal prints it. No offset: the note is
#: stamped in the state's own time and the portal does not say so.
_WHEN = re.compile(r"(\d{2})/(\d{2})/(\d{4})\s+(\d{2}):(\d{2}):(\d{2})")
#: `(Código: 2165)` at the end of the item's first cell.
_CODE = re.compile(r"\(\s*C[óo]digo:\s*([^)]+?)\s*\)", re.I)
#: `CNPJ: 13482024000257 -, Inscrição Estadual: 0017567910179`
_IE = re.compile(r"Inscri[çc][ãa]o\s+Estadual:\s*(\S+)", re.I)
#: The IBPT string a merchant's own software writes into the free-text
#: block: `Trib aprox R$: 1,29 Fed e 1,08 Est`. It is the only place this
#: page names the approximate taxes, and it is the merchant's wording
#: rather than the state's — so anything else yields nothing at all,
#: which is the honest answer.
_TAXES = re.compile(
    r"Trib\w*\s*aprox\w*\s*R?\$?\s*:?\s*([\d.,]+)\s*Fed\w*\s*e\s*([\d.,]+)\s*Est", re.I
)

#: `04 - Cartão de Débito` — the code is the stable half.
PAYMENT_TYPES = {
    "01": "cash", "02": "other", "03": "credit_card", "04": "debit_card",
    "05": "store_credit", "10": "food_voucher", "11": "meal_voucher",
    "12": "other", "13": "other", "15": "other", "16": "other",
    "17": "pix", "18": "other", "19": "other", "20": "pix",
    "21": "store_credit", "90": "other", "99": "other",
}


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("\xa0", " ")).strip()


def _plain(raw: Optional[str]) -> Optional[Decimal]:
    """`6.00` → `Decimal('6.00')`.

    For the summary rows only, where the portal prints the number as Java
    renders a `BigDecimal`: a dot is a decimal point, never a thousands
    separator. Passing one of these through `parse_brl` silently drops
    the cents.
    """
    if raw is None:
        return None
    found = re.search(r"-?\d+(?:\.\d+)?", raw.replace("\xa0", " "))
    if found is None:
        return None
    try:
        return Decimal(found.group(0))
    except InvalidOperation:
        return None


def _after_label(cell_text: str, label: str) -> Optional[str]:
    """The item cells are `label: value` in one string — `UN: UN`,
    `Valor total R$: R$ 6,00`."""
    prefix = f"{label}:"
    text = _clean(cell_text)
    if not text.lower().startswith(prefix.lower()):
        return None
    return text[len(prefix):].strip() or None


def _column(soup_or_tag: BeautifulSoup | Tag, header: str) -> Optional[str]:
    """The value under a `<th>` with this text.

    The accordion's tables put their labels in a header row and the
    values in the row below, matched by column — the same arrangement the
    national XSLT uses for some of its blocks.
    """
    wanted = _clean(header).lower()
    for th in soup_or_tag.find_all("th"):
        if _clean(th.get_text()).lower() != wanted:
            continue
        row = th.find_parent("tr")
        table = th.find_parent("table")
        if row is None or table is None:
            continue
        cells = row.find_all("th")
        if th not in cells:
            continue
        index = cells.index(th)
        body = table.find("tbody")
        value_row = body.find("tr") if isinstance(body, Tag) else None
        if value_row is None:
            continue
        values = value_row.find_all("td")
        if index < len(values):
            return _clean(values[index].get_text()) or None
    return None


def _summary(soup: BeautifulSoup, label: str) -> Optional[str]:
    """The value beside one of the `div.row` summary lines.

    Each is a label in one column and a `<strong>` in the next; the
    payment block repeats the pair once per payment, which is why this
    returns the first and `_payments` walks them all.
    """
    for value in _summary_all(soup, label):
        return value
    return None


def _summary_all(soup: BeautifulSoup, label: str) -> list[str]:
    wanted = _clean(label).lower()
    out: list[str] = []
    for row in soup.select("div.row"):
        columns = [child for child in row.find_all("div", recursive=False)]
        if len(columns) < 2:
            continue
        if _clean(columns[0].get_text()).lower() != wanted:
            continue
        out.append(_clean(columns[1].get_text()))
    return out


def _panel(soup: BeautifulSoup, heading: str) -> Optional[Tag]:
    """The accordion body whose heading carries this text."""
    wanted = _clean(heading).lower()
    for head in soup.select("div.panel-heading"):
        if wanted not in _clean(head.get_text()).lower():
            continue
        # `.get` is typed as possibly returning a list of values; `href`
        # never is one, but the checker cannot know that.
        target = str(head.get("href") or "")
        body = soup.find(id=target.lstrip("#")) if target else None
        if isinstance(body, Tag):
            return body
    return None


def classify_mg_info(page: FetchedPage) -> PageKind:
    if page.status_code >= 500:
        return PageKind.ERROR_PAGE
    lowered = page.html.lower()
    # The note itself is the only page with the item table. Checked first
    # and by that marker, because the challenge page carries the same
    # title — "Nota Fiscal de Consumidor Eletrônica" is on both.
    if 'id="mytable"' in lowered:
        return PageKind.AUTHORIZED
    if "cf-turnstile" in lowered or "g-recaptcha" in lowered or "grecaptcha" in lowered:
        return PageKind.CAPTCHA
    if "cancelad" in lowered:
        return PageKind.CANCELLED
    if "não encontrada" in lowered or "nao encontrada" in lowered or "inexistente" in lowered:
        return PageKind.NOT_FOUND_YET
    return PageKind.ERROR_PAGE


def _when(raw: Optional[str]) -> Optional[datetime]:
    if not raw:
        return None
    found = _WHEN.search(raw)
    if found is None:
        return None
    day, month, year, hour, minute, second = found.groups()
    try:
        return datetime.fromisoformat(f"{year}-{month}-{day}T{hour}:{minute}:{second}")
    except ValueError:
        return None


def _issuer(soup: BeautifulSoup) -> Issuer:
    general = _panel(soup, "Informações gerais da Nota")
    cnpj = _DIGITS.sub("", _column(general, "CNPJ") or "" if general else "")
    if len(cnpj) != 14:
        raise ParseError("layout_changed", f"issuer CNPJ is {cnpj!r}")
    name = (_column(general, "Nome / Razão Social") if general else None) or ""
    if not name:
        raise ParseError("layout_changed", "issuer has no name")
    return Issuer(
        cnpj=cnpj,
        ie=(_column(general, "Inscrição Estadual") if general else None),
        legal_name=name,
        uf=(_column(general, "UF") if general else None),
        **_address(soup),
    )


def _address(soup: BeautifulSoup) -> dict[str, Optional[str]]:
    """The header's italic line, the only place the address appears:
    `AV CRISTIANO MACHADO, 1950, CIDADE NOVA, 3106200 - BELO HORIZONTE, MG`.

    Comma-separated with the IBGE code glued to the city. Parsed
    positionally, which is fragile, so every field is optional and a line
    that does not have this shape simply yields none of them rather than
    guessing.
    """
    empty: dict[str, Optional[str]] = {"street": None, "number": None, "district": None, "city": None}
    header = soup.select_one("table.text-center tbody")
    if header is None:
        return empty
    rows = header.find_all("tr")
    if len(rows) < 2:
        return empty
    parts = [part.strip() for part in _clean(rows[1].get_text()).split(",")]
    if len(parts) < 4:
        return empty
    city = parts[3]
    if " - " in city:
        city = city.split(" - ", 1)[1].strip()
    return {
        "street": parts[0] or None,
        "number": parts[1] or None,
        "district": parts[2] or None,
        "city": city or None,
    }


def _items(soup: BeautifulSoup) -> list[CanonicalItem]:
    table = soup.find(id="myTable")
    if not isinstance(table, Tag):
        raise ParseError("layout_changed", "no item table")
    out: list[CanonicalItem] = []
    for ordinal, row in enumerate(table.find_all("tr"), start=1):
        cells = row.find_all("td")
        if len(cells) < 4:
            raise ParseError("layout_changed", f"item {ordinal} has {len(cells)} cells")
        first = _clean(cells[0].get_text())
        found = _CODE.search(first)
        if found is None:
            raise ParseError("layout_changed", f"item {ordinal} has no product code")
        description = _clean(first[: found.start()])
        quantity = _plain(_after_label(cells[1].get_text(), "Qtde total de ítens"))
        total = parse_brl(_after_label(cells[3].get_text(), "Valor total R$"))
        if quantity is None or total is None:
            raise ParseError("layout_changed", f"item {ordinal} has no quantity or total")
        out.append(
            CanonicalItem(
                ordinal=ordinal,
                product_code=found.group(1),
                # The page shows the merchant's code and never a barcode.
                gtin=None,
                description=description or found.group(1),
                unit=_after_label(cells[2].get_text(), "UN") or "UN",
                quantity=quantity,
                # Not printed: the line gives what was bought and what it
                # cost, and the price for one is the division. Kept at
                # four places, which is what the column stores.
                unit_price=(total / quantity) if quantity else total,
                total=total,
            )
        )
    if not out:
        raise ParseError("no_items", "the item table lists no items")
    return out


def _payments(soup: BeautifulSoup, fallback: Decimal) -> list[Payment]:
    """One payment per "Forma de Pagamento" row, taking the amount from
    the "Valor pago R$" row that precedes it.

    The two are rendered together by the same JSF repeater. Only
    single-payment notes have been seen, so when the counts disagree the
    note's total is used for a lone payment and the rest are left out
    rather than split by a rule nobody has verified.
    """
    labels = _summary_all(soup, "Forma de Pagamento")
    amounts = [_plain(value) for value in _summary_all(soup, "Valor pago R$")]
    out: list[Payment] = []
    for index, label in enumerate(labels):
        amount = amounts[index] if index < len(amounts) else None
        if amount is None:
            if len(labels) != 1:
                continue
            amount = fallback
        code = label.split("-", 1)[0].strip().zfill(2)
        out.append(
            Payment(
                type=PAYMENT_TYPES.get(code, "other"),
                label=label or None,
                amount=amount,
            )
        )
    return out


def _approx_taxes(soup: BeautifulSoup) -> Optional[Decimal]:
    panel = _panel(soup, "Informações Complementares")
    if panel is None:
        return None
    found = _TAXES.search(_clean(panel.get_text()))
    if found is None:
        return None
    federal, state = parse_brl(found.group(1)), parse_brl(found.group(2))
    if federal is None or state is None:
        return None
    return federal + state


def parse_mg_info(html: str) -> CanonicalReceipt:
    soup = BeautifulSoup(html, "html.parser")

    key_panel = _panel(soup, "Chave de acesso")
    key = _DIGITS.sub("", key_panel.get_text() if key_panel else "")
    if len(key) != 44:
        raise ParseError("layout_changed", f"access key is {key!r}")

    general = _panel(soup, "Informações gerais da Nota")
    if general is None:
        raise ParseError("layout_changed", "no general information panel")

    items = _items(soup)
    products_total = _plain(_summary(soup, "Valor total R$"))
    paid = _plain(_summary(soup, "Valor pago R$"))
    if products_total is None:
        raise ParseError("layout_changed", "no products total")
    if paid is None:
        paid = products_total

    # The page prints no discount line. What it prints is what the
    # products came to and what was handed over, and the difference is
    # one or the other — named rather than dropped, so the totals still
    # add up the way the canonical model insists they do.
    difference = products_total - paid
    return CanonicalReceipt(
        access_key=key,
        uf=_column(general, "UF") or "MG",
        model=_column(general, "Modelo") or "65",
        series=int(_DIGITS.sub("", _column(general, "Série") or "0") or "0"),
        number=int(_DIGITS.sub("", _column(general, "Número") or "0") or "0"),
        issued_at=_when(_column(general, "Data Emissão")),
        protocol=_column(general, "Protocolo"),
        issuer=_issuer(soup),
        # The consumer panel names only "Nome / Razão Social" and "UF";
        # this page never carries a CPF.
        customer_cpf=None,
        totals=Totals(
            items_count=len(items),
            products_total=products_total,
            discount=difference if difference > ZERO else ZERO,
            addition=-difference if difference < ZERO else ZERO,
            total=paid,
            approx_taxes=_approx_taxes(soup),
        ),
        payments=_payments(soup, paid),
        items=items,
        source="sefaz_html",
    )
