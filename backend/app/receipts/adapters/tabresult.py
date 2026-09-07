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
from dataclasses import dataclass
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
    # Dotted thousands first ("1.234,56"), otherwise plain digits ("2490,00",
    # "9,78", "3"): a 4-digit figure printed without a separator must not be
    # cut at its first three digits.
    match = re.search(r"-?\d{1,3}(?:\.\d{3})+(?:,\d+)?|-?\d+(?:,\d+)?", text)
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


_TAG_RE = re.compile(r"<[a-zA-Z!/]")


def looks_like_html(text: str) -> bool:
    return bool(_TAG_RE.search(text or ""))


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
    info = _info_from_text(info_text, access_key=access_key)
    return _build(expected_uf, info, issuer, totals, payments, items)


@dataclass(frozen=True)
class _Info:
    access_key: str
    number: int
    series: int
    issued_at: Optional[datetime]
    protocol: Optional[str]
    authorized_at: Optional[datetime]
    customer_cpf: Optional[str]


def _info_from_text(info_text: str, *, access_key: Optional[str] = None) -> _Info:
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
    return _Info(access_key, number, series, issued_at, protocol, authorized_at, customer_cpf)


def _build(
    expected_uf: str, info: _Info, issuer: Issuer, totals: Totals, payments: list[Payment], items: list[CanonicalItem],
    *, source: str = "sefaz_html",
) -> CanonicalReceipt:
    try:
        return CanonicalReceipt(
            access_key=info.access_key,
            uf=expected_uf,
            series=info.series,
            number=info.number,
            issued_at=info.issued_at,
            protocol=info.protocol,
            authorized_at=info.authorized_at,
            issuer=issuer,
            customer_cpf=info.customer_cpf,
            totals=totals,
            payments=payments,
            items=items,
            source=source,
        )
    except ValueError as exc:  # pydantic ValidationError is a ValueError
        code = _validation_code(exc)
        raise ParseError(code, str(exc)) from exc


# ---------------------------------------------------------------------------
# the same template, as text — what a phone's "select all → copy" gives
# ---------------------------------------------------------------------------
_TEXT_ITEM_RE = re.compile(
    r"\(C[óo]digo:\s*(?P<code>[^)]+?)\s*\)\s*"
    r"Qtde\.?\s*:\s*(?P<qty>[\d.,]+)\s*"
    r"UN\s*:\s*(?P<unit>[A-Za-zÀ-ú]+)\s*"
    r"Vl\.?\s*Unit\.?\s*:\s*(?P<price>[\d.,]+)\s*"
    r"(?:Vl\.?\s*Total\s*:?\s*)?(?P<total>[\d.,]+)",
    re.IGNORECASE | re.DOTALL,
)
_TEXT_TOTAL_LABELS: tuple[tuple[str, str], ...] = (
    ("Qtd. total de itens", "items_count"),
    ("Qtd total de itens", "items_count"),
    ("Valor total R$", "products_total"),
    ("Descontos R$", "discount"),
    ("Desconto R$", "discount"),
    ("Acréscimos R$", "addition"),
    ("Acréscimo R$", "addition"),
    ("Frete R$", "shipping"),
    ("Valor a pagar R$", "total"),
)


def parse_tabresult_text(text: str, *, expected_uf: str) -> CanonicalReceipt:
    """The rendered text of a tabResult page. Anchors on the labels, which
    survive copy-and-paste; layout does not. Handles one field per line
    (a view-source dump), one line per block (a phone's select-all), and
    everything on a single line (some browsers collapse it)."""
    text = text.replace("\xa0", " ")
    lowered = text.lower()
    if any(marker in lowered for marker in _CANCELLED_MARKERS):
        raise ParseError("cancelled", "the pasted text says the note was cancelled")

    issuer, body_start = _text_issuer(text, expected_uf)

    items: list[CanonicalItem] = []
    cursor = body_start
    for match in _TEXT_ITEM_RE.finditer(text, body_start):
        before = text[cursor:match.start()]
        # The description is the last non-empty line before "(Código:"; on a
        # single-line copy it is whatever sits after the previous total.
        lines = [line.strip() for line in before.splitlines() if line.strip()]
        description = lines[-1] if lines else before.strip()
        description = re.sub(r"^(?:Vl\.?\s*Total\s*:?\s*[\d.,]+)\s*", "", description).strip()
        if not description:
            raise ParseError("item_fields", f"item {len(items) + 1} has no description")
        quantity = parse_brl(match.group("qty"))
        unit_price = parse_brl(match.group("price"))
        total = parse_brl(match.group("total"))
        if quantity is None or unit_price is None or total is None:
            raise ParseError("item_fields", f"item {len(items) + 1} has an unreadable number")
        items.append(
            CanonicalItem(
                ordinal=len(items) + 1,
                product_code=match.group("code").strip(),
                gtin=None,
                description=description[:200],
                unit=match.group("unit")[:6],
                quantity=quantity,
                unit_price=unit_price,
                total=total,
            )
        )
        cursor = match.end()
    if not items:
        raise ParseError("no_items", "no '(Código: …) Qtde.: … UN: … Vl. Unit.: … Vl. Total …' lines found")

    values: dict[str, Decimal] = {}
    for label, key in _TEXT_TOTAL_LABELS:
        # The count is an integer; every other total is money with two
        # decimals. Label and value may sit on different lines.
        number = r"(\d+)" if key == "items_count" else r"(-?[\d.]+,\d{2})"
        found = re.search(re.escape(label) + r"\s*:?\s*" + number, text)
        if found and key not in values:
            amount = parse_brl(found.group(1))
            if amount is not None:
                values[key] = amount
    taxes = re.search(r"Tributos\s+Totais\s+Incidentes.*?R\$\s*:?\s*([\d.]+,\d{2})", text, re.IGNORECASE | re.DOTALL)
    if taxes:
        approx = parse_brl(taxes.group(1))
        if approx is not None:
            values["approx_taxes"] = approx
    if "items_count" not in values or ("products_total" not in values and "total" not in values):
        raise ParseError("no_totals", f"labels found: {sorted(values)}")
    items_sum = sum((item.total for item in items), ZERO)
    if "products_total" not in values:
        values["products_total"] = items_sum
        gap = items_sum - values["total"]
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

    payments = _text_payments(text)
    info = _info_from_text(text)
    return _build(expected_uf, info, issuer, totals, payments, items, source="pasted_text")


_TEXT_PAYMENT_LINE_RE = re.compile(r"(?P<label>[A-Za-zÀ-ú][A-Za-zÀ-ú$ .()/-]{2,40}?)\s*:?\s+(?P<amount>[\d.]+,\d{2})")


def _text_payments(text: str) -> list[Payment]:
    block = re.search(
        r"Forma de pagamento\s*:?(.*?)(?:Tributos|Informa[çc][õo]es|Chave de acesso|$)", text, re.IGNORECASE | re.DOTALL
    )
    payments: list[Payment] = []
    if not block:
        return payments
    for found in _TEXT_PAYMENT_LINE_RE.finditer(block.group(1)):
        label = found.group("label").rstrip(":").strip()
        amount = parse_brl(found.group("amount"))
        if amount is None or label.lower().startswith("valor pago"):
            continue
        if label.lower().startswith("troco"):
            if payments:
                payments[-1] = payments[-1].model_copy(update={"change": amount})
            continue
        payments.append(Payment(type=_payment_type(label), label=label, amount=amount))
    return payments


def _text_issuer(text: str, expected_uf: str) -> tuple[Issuer, int]:
    """The issuer block, and the offset where the item lines begin (so a
    single-line copy does not fold the header into the first description)."""
    cnpj_match = re.search(r"CNPJ\s*:?\s*([\d./\-]{14,18})", text)
    if not cnpj_match:
        raise ParseError("no_issuer", "no CNPJ line")
    cnpj = re.sub(r"\D", "", cnpj_match.group(1))
    if len(cnpj) != 14:
        raise ParseError("no_issuer", f"cnpj={cnpj!r}")
    all_lines = text.splitlines()
    line_index = next((i for i, line in enumerate(all_lines) if cnpj in re.sub(r"\D", "", line)), None)
    if line_index is None:
        raise ParseError("no_issuer", "CNPJ not on any line")
    line = all_lines[line_index]
    one_line = "Código" in line or "Codigo" in line
    name = ""
    address_line = ""
    body_start = 0
    if one_line:
        # Everything is on this line. The name is what sits between the
        # DANFE title and "CNPJ"; the address runs up to the state code.
        value_at = line.find(cnpj_match.group(1))
        pre = line[:value_at]
        pre = re.sub(r"CNPJ\s*:?\s*$", "", pre.strip())
        pre = re.split(r"ELETR[ÔO]NICA|NFC-e\b", pre, flags=re.IGNORECASE)[-1]
        name = pre.strip(" :|-–")[-120:].strip()
        post = line[value_at + len(cnpj_match.group(1)):]
        address = re.match(r"\s*(.+?,\s*[A-Z]{2})(?=\s|$)", post)
        if address:
            address_line = address.group(1)
            body_start = text.find(line) + value_at + len(cnpj_match.group(1)) + address.end()
        else:
            body_start = text.find(line) + value_at + len(cnpj_match.group(1))
    else:
        for i in range(line_index - 1, -1, -1):
            candidate = all_lines[i].strip()
            if candidate and not candidate.upper().startswith("CNPJ"):
                name = candidate
                break
        pieces: list[str] = []
        for i in range(line_index + 1, min(line_index + 12, len(all_lines))):
            candidate = all_lines[i].strip()
            if not candidate:
                continue
            if re.search(r"C[óo]digo:|Qtde|Vl\.", candidate):
                break
            pieces.append(candidate)
            if (re.search(r"(?:,|\s)([A-Z]{2})$", candidate) and len(pieces) > 1) or len(candidate.split(",")) >= 5:
                break
        address_line = " ".join(pieces)
    if not name:
        raise ParseError("no_issuer", f"name={name!r} cnpj={cnpj!r}")
    return _issuer_from_parts(name, cnpj, [address_line] if address_line else [], expected_uf), body_start


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
    return _issuer_from_parts(name, cnpj, address_lines, expected_uf)


def _issuer_from_parts(name: str, cnpj: str, address_lines: list[str], expected_uf: str) -> Issuer:
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
