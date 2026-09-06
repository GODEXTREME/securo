"""Parser for the shared "tabResult" DANFE template.

Several state portals — Espírito Santo among them — render the consumer
view of an NFC-e from one common template: a `#tabResult` table with one
row per item, a `#totalNota` block of label/value pairs, and an `#infos`
block with the key, number, series, emission and protocol. A state
adapter that uses this template is a binding (state code, hosts, parser
version) over these functions.

Everything numeric on the page is Brazilian-formatted (`1.234,56`) and is
read through `parse_brl` into `Decimal`. Nothing here is ever a float.

Known limit, and the reason the catalogue has a "chain" identity level:
this template does not show the GTIN. Every item parsed here carries
`gtin = None` and is identified by the store's own product code.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Optional

from bs4 import BeautifulSoup, Tag

from app.receipts.adapters.base import FetchedPage, PageKind, ParseError
from app.receipts.canonical import (
    ZERO,
    CanonicalItem,
    CanonicalReceipt,
    Issuer,
    Payment,
    Totals,
)

# Brazil has had no daylight-saving time since 2019; every NFC-e state in
# scope sits at UTC−3 year-round. A fixed offset is exact for the data and
# keeps the parser free of tz database dependencies.
BRT = timezone(timedelta(hours=-3), name="-03:00")

_PAYMENT_TYPES: tuple[tuple[str, str], ...] = (
    ("cartão de crédito", "credit_card"),
    ("cartao de credito", "credit_card"),
    ("cartão de débito", "debit_card"),
    ("cartao de debito", "debit_card"),
    ("dinheiro", "cash"),
    ("pix", "pix"),
    ("vale alimentação", "food_voucher"),
    ("vale alimentacao", "food_voucher"),
    ("vale refeição", "meal_voucher"),
    ("vale refeicao", "meal_voucher"),
    ("crédito loja", "store_credit"),
    ("credito loja", "store_credit"),
)

_CANCELLED_MARKERS = ("nfc-e cancelada", "nfce cancelada", "situação: cancelada", "evento de cancelamento")
# Cloudflare Turnstile is what Espírito Santo actually serves to an
# automated request (fixture: es/turnstile_challenge.html). It never says
# "captcha" anywhere in the page.
_CAPTCHA_MARKERS = ("cf-turnstile", "turnstile", "g-recaptcha", "h-captcha", "hcaptcha", "captcha")
_NOT_FOUND_MARKERS = (
    "não foi possível localizar",
    "nao foi possivel localizar",
    "não encontrada",
    "nao encontrada",
    "não localizada",
    "nao localizada",
    "ainda não",
    "rejeição",
    "rejeicao",
)


def parse_brl(raw: str | None) -> Optional[Decimal]:
    """`R$ 1.234,56` → Decimal('1234.56'). None when there is no number."""
    if raw is None:
        return None
    text = raw.replace("R$", "").replace("\xa0", " ").strip()
    match = re.search(r"-?\d{1,3}(?:\.\d{3})*(?:,\d+)?|-?\d+(?:,\d+)?", text)
    if not match:
        return None
    try:
        return Decimal(match.group(0).replace(".", "").replace(",", "."))
    except InvalidOperation:
        return None


def classify_tabresult(page: FetchedPage) -> PageKind:
    if page.status_code >= 500:
        return PageKind.ERROR_PAGE
    lowered = page.html.lower()
    if any(marker in lowered for marker in _CANCELLED_MARKERS):
        return PageKind.CANCELLED
    if 'id="tabresult"' in lowered:
        return PageKind.AUTHORIZED
    if any(marker in lowered for marker in _CAPTCHA_MARKERS):
        return PageKind.CAPTCHA
    if any(marker in lowered for marker in _NOT_FOUND_MARKERS):
        return PageKind.NOT_FOUND_YET
    return PageKind.ERROR_PAGE


def _text(node: Tag | None) -> str:
    return re.sub(r"\s+", " ", node.get_text(" ", strip=True)) if node is not None else ""


def _after(label: str, text: str) -> Optional[str]:
    """The value that follows `label` in a run of text, up to the next
    label-looking token or the end."""
    match = re.search(re.escape(label) + r"\s*:?\s*([^\n]*?)(?=\s+[A-ZÁ-Ú][\w./ ]{2,}:|$)", text)
    return match.group(1).strip() if match else None


def _payment_type(label: str) -> str:
    lowered = label.lower()
    for needle, kind in _PAYMENT_TYPES:
        if needle in lowered:
            return kind
    return "other"


def parse_tabresult(html: str, *, expected_uf: str) -> CanonicalReceipt:
    soup = BeautifulSoup(html, "html.parser")
    table = soup.select_one("#tabResult")
    if table is None:
        raise ParseError("layout_changed", "no #tabResult table")

    items = _parse_items(table)
    if not items:
        raise ParseError("no_items")

    totals, payments = _parse_totals(soup, sum((item.total for item in items), ZERO))
    issuer = _parse_issuer(soup, expected_uf)
    info_text = _text(soup.select_one("#infos")) or _text(soup)

    key_node = soup.select_one("span.chave")
    access_key = re.sub(r"\D", "", _text(key_node)) if key_node else None
    if not access_key:
        found = re.search(r"(?:\d[\s.]?){44}", info_text)
        access_key = re.sub(r"\D", "", found.group(0)) if found else None
    if not access_key or len(access_key) != 44:
        raise ParseError("no_access_key")

    number = _int(_after("Número", info_text))
    series = _int(_after("Série", info_text))
    if number is None or series is None:
        raise ParseError("no_number_series")

    issued_at = _datetime(_after("Emissão", info_text))
    protocol, authorized_at = _protocol(info_text)
    cpf_match = re.search(r"CPF\s*:?\s*([\d.\-]{11,14})", info_text)
    customer_cpf = re.sub(r"\D", "", cpf_match.group(1)) if cpf_match else None
    if customer_cpf is not None and len(customer_cpf) != 11:
        customer_cpf = None

    try:
        return CanonicalReceipt(
            access_key=access_key,
            uf=expected_uf,
            series=series,
            number=number,
            issued_at=issued_at,
            protocol=protocol,
            authorized_at=authorized_at,
            issuer=issuer,
            customer_cpf=customer_cpf,
            totals=totals,
            payments=payments,
            items=items,
        )
    except ValueError as exc:  # pydantic ValidationError is a ValueError
        code = _validation_code(exc)
        raise ParseError(code, str(exc)) from exc


def _validation_code(exc: ValueError) -> str:
    text = str(exc)
    for code in ("items_count_mismatch", "items_not_sequential", "products_total_mismatch", "total_mismatch"):
        if code in text:
            return code
    return "invalid_canonical"


def _int(raw: Optional[str]) -> Optional[int]:
    if not raw:
        return None
    match = re.search(r"\d+", raw)
    return int(match.group(0)) if match else None


def _datetime(raw: Optional[str]) -> Optional[datetime]:
    if not raw:
        return None
    match = re.search(r"(\d{2})/(\d{2})/(\d{4})\s+(\d{2}):(\d{2})(?::(\d{2}))?", raw)
    if not match:
        return None
    day, month, year, hour, minute, second = match.groups()
    return datetime(int(year), int(month), int(day), int(hour), int(minute), int(second or 0), tzinfo=BRT)


def _protocol(info_text: str) -> tuple[Optional[str], Optional[datetime]]:
    match = re.search(
        r"Protocolo de Autoriza[çc][ãa]o\s*:?\s*(\d+)\s+(\d{2}/\d{2}/\d{4}\s+(?:às\s+)?\d{2}:\d{2}(?::\d{2})?)",
        info_text,
    )
    if not match:
        return None, None
    return match.group(1), _datetime(match.group(2).replace("às ", ""))


def _parse_items(table: Tag) -> list[CanonicalItem]:
    items: list[CanonicalItem] = []
    for row in table.select("tr"):
        cells = row.find_all("td", recursive=False)
        value_cell = row.select_one("span.valor")
        if not cells or value_cell is None:
            continue
        # The first cell carries the item; on the live portal it has no
        # class of its own and the name sits in a `span.txtTit` inside it.
        title_cell = cells[0]
        name_node = (
            title_cell.select_one("span.txtTit")
            or title_cell.select_one("h7")
            or title_cell.select_one("span.txtTit2")
            or title_cell
        )
        description = _text(name_node)
        if name_node is title_cell:
            description = description.split("(Código", 1)[0].strip()
        code_text = _text(title_cell.select_one("span.RCod"))
        code_match = re.search(r"C[óo]digo\s*:?\s*([^)]+)", code_text)
        product_code = code_match.group(1).strip() if code_match else ""
        quantity = parse_brl(_text(title_cell.select_one("span.Rqtd")).split(":")[-1])
        unit_text = _text(title_cell.select_one("span.RUN")).split(":")[-1].strip()
        unit_price = parse_brl(_text(title_cell.select_one("span.RvlUnit")).split(":")[-1])
        total = parse_brl(_text(value_cell))
        if not product_code or quantity is None or unit_price is None or total is None or not unit_text:
            raise ParseError("item_fields", f"item {len(items) + 1} is missing a field")
        items.append(
            CanonicalItem(
                ordinal=len(items) + 1,
                product_code=product_code,
                gtin=None,
                description=description[:200],
                unit=unit_text[:6],
                quantity=quantity,
                unit_price=unit_price,
                total=total,
            )
        )
    return items


def _parse_totals(soup: BeautifulSoup, items_sum: Decimal) -> tuple[Totals, list[Payment]]:
    block = soup.select_one("#totalNota")
    if block is None:
        raise ParseError("no_totals")
    values: dict[str, Decimal] = {}
    payments: list[Payment] = []
    in_payments = False
    for line in block.select("div"):
        label_node = line.select_one("label")
        value_node = line.select_one("span.totalNumb")
        label = _text(label_node).rstrip(":").strip()
        if not label:
            continue
        lowered = label.lower()
        if lowered.startswith("forma de pagamento"):
            in_payments = True
            continue
        amount = parse_brl(_text(value_node)) if value_node is not None else None
        if amount is None:
            continue
        if lowered.startswith("qtd. total de itens") or lowered.startswith("qtd total de itens"):
            values["items_count"] = amount
        elif lowered.startswith("valor total"):
            values["products_total"] = amount
        elif lowered.startswith("desconto"):
            values["discount"] = amount
        elif lowered.startswith("acréscimo") or lowered.startswith("acrescimo"):
            values["addition"] = amount
        elif lowered.startswith("frete"):
            values["shipping"] = amount
        elif lowered.startswith("valor a pagar"):
            values["total"] = amount
        elif lowered.startswith("troco"):
            if payments:
                payments[-1] = payments[-1].model_copy(update={"change": amount})
        elif "tributos" in lowered:
            values["approx_taxes"] = amount
        elif in_payments:
            payments.append(Payment(type=_payment_type(label), label=label, amount=amount))
    if "items_count" not in values or ("products_total" not in values and "total" not in values):
        raise ParseError("no_totals", f"labels found: {sorted(values)}")
    if "products_total" not in values:
        # The live ES portal prints only "Valor a pagar". The products total
        # is the sum of the lines, and the gap to what was paid is a discount
        # (or, rarely, an addition) the portal chose not to itemise.
        products_total = items_sum
        total = values["total"]
        gap = products_total - total
        values["products_total"] = products_total
        if gap > ZERO and "discount" not in values:
            values["discount"] = gap
        elif gap < ZERO and "addition" not in values:
            values["addition"] = -gap
    total = values.get("total", values["products_total"] - values.get("discount", ZERO))
    totals = Totals(
        items_count=int(values["items_count"]),
        products_total=values["products_total"],
        discount=values.get("discount", ZERO),
        addition=values.get("addition", ZERO),
        shipping=values.get("shipping", ZERO),
        total=total,
        approx_taxes=values.get("approx_taxes"),
    )
    return totals, payments


def _parse_issuer(soup: BeautifulSoup, expected_uf: str) -> Issuer:
    header = soup.select_one("div.txtCenter")
    if header is None:
        raise ParseError("no_issuer")
    name = _text(header.select_one(".txtTopo"))
    lines = [_text(node) for node in header.select("div.text")]
    cnpj: Optional[str] = None
    address_lines: list[str] = []
    for line in lines:
        match = re.search(r"CNPJ\s*:?\s*([\d./\-]{14,18})", line)
        if match:
            cnpj = re.sub(r"\D", "", match.group(1))
        elif line:
            address_lines.append(line)
    if not name or not cnpj or len(cnpj) != 14:
        raise ParseError("no_issuer", f"name={name!r} cnpj={cnpj!r}")
    street = number = district = city = uf = None
    if address_lines:
        # "Av. X, 1905, , Bento Ferreira, Vitoria, ES": street, number, an
        # often-empty complement, district, city, state. Anchor on the right,
        # where the fields are fixed, so the blank in the middle costs nothing.
        parts = [p.strip() for p in address_lines[0].split(",")]
        if len(parts) >= 5 and len(parts[-1]) == 2:
            street, number, district, city, uf = parts[0], parts[1], parts[-3], parts[-2], parts[-1].upper()
        elif len(parts) == 4:
            street, number, district, city = parts
        else:
            street = address_lines[0]
    return Issuer(
        cnpj=cnpj,
        legal_name=name,
        street=street or None,
        number=number or None,
        district=district or None,
        city=city or None,
        uf=uf or expected_uf,
    )
