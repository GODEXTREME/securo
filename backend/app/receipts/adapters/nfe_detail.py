"""Parser for the national "Consulta da NF-e" detailed view.

Several states render the full document through one shared XSLT — the
tabbed page (NFe, Emitente, Destinatário, Produtos e Serviços, Totais,
Transporte, Cobrança, Informações Adicionais) that Goiás reaches at
`render/NFCe` and Rio de Janeiro at `resultadoDfeDetalhado.faces`. The
markup is `<label>` / `<span>` pairs inside `div.GeralXslt` panels, one
per tab.

Why this view and not the DANFE the QR leads to: **it shows the
barcode**. `Código EAN Comercial` is on every item, which is precisely
what the consumer template withholds and the reason the catalogue is
confined to per-chain identity elsewhere.

The page does not contain that markup in its DOM. It arrives as a
JavaScript string literal handed to `new XmlNFE(...)`, escaped, and is
unwrapped here before anything is read — a state that serves the same
markup directly is handled too, since unwrapping a page that needs none
returns it unchanged.
"""
from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal
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

_EMBEDDED = re.compile(r"new\s+XmlNFE\(\s*'[^']*'\s*,\s*'[^']*'\s*,\s*'(.*?)'\s*\)\s*;", re.S)
_DIGITS = re.compile(r"\D")
#: `04/09/2026 15:07:36-03:00`, as the XSLT prints it.
_WHEN = re.compile(r"(\d{2})/(\d{2})/(\d{4})\s+(\d{2}):(\d{2}):(\d{2})\s*([+-]\d{2}:?\d{2})?")

#: `3 - Cartão de Crédito` — the code is what is stable, the words are
#: the XSLT's. Mapped onto the vocabulary the rest of the system speaks.
PAYMENT_TYPES = {
    "01": "cash", "02": "other", "03": "credit_card", "04": "debit_card",
    "05": "store_credit", "10": "food_voucher", "11": "meal_voucher",
    "12": "other", "13": "other", "15": "other", "16": "other",
    "17": "pix", "18": "other", "19": "other", "20": "pix",
    "21": "store_credit", "90": "other", "99": "other",
}


def unwrap_detail(body: str) -> str:
    """The detail markup, whether it was embedded or served directly."""
    found = _EMBEDDED.search(body)
    if found is None:
        return body
    inner = found.group(1)
    for escaped, plain in (("\\/", "/"), ("\\'", "'"), ('\\"', '"'), ("\\n", "\n"), ("\\t", "\t")):
        inner = inner.replace(escaped, plain)
    return inner.replace("\\\\", "\\")


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("\xa0", " ")).strip()


def _field(scope: Optional[Tag], label: str) -> Optional[str]:
    """The `<span>` that follows the `<label>` with this text.

    Labels repeat across tabs — "CNPJ" is in three of them — so every
    lookup is scoped to one panel and never to the whole page.
    """
    if scope is None:
        return None
    wanted = _clean(label).lower()
    for tag in scope.find_all("label"):
        if _clean(tag.get_text()).lower() != wanted:
            continue
        span = tag.find_next_sibling("span")
        if span is not None:
            value = _clean(span.get_text())
            return value or None
    return None


def _panel(soup: BeautifulSoup, panel_id: str) -> Optional[Tag]:
    found = soup.find(id=panel_id)
    return found if isinstance(found, Tag) else None


def _when(raw: Optional[str]) -> Optional[datetime]:
    if not raw:
        return None
    found = _WHEN.search(raw)
    if found is None:
        return None
    day, month, year, hour, minute, second, offset = found.groups()
    stamp = f"{year}-{month}-{day}T{hour}:{minute}:{second}"
    if offset:
        stamp += offset if ":" in offset else f"{offset[:3]}:{offset[3:]}"
    try:
        return datetime.fromisoformat(stamp)
    except ValueError:
        return None


def _money(raw: Optional[str], default: Decimal = ZERO) -> Decimal:
    value = parse_brl(raw)
    return default if value is None else value


def classify_nfe_detail(page: FetchedPage) -> PageKind:
    lowered = page.html.lower()
    if "cf-turnstile" in lowered or "g-recaptcha" in lowered or "grecaptcha" in lowered:
        return PageKind.CAPTCHA
    body = unwrap_detail(page.html)
    lowered = body.lower()
    if "cancelamento" in lowered or "cancelada" in lowered:
        return PageKind.CANCELLED
    if "situa" in lowered and "autorizada" in lowered:
        return PageKind.AUTHORIZED
    if "geralxslt" in lowered:
        return PageKind.ERROR_PAGE
    return PageKind.NOT_FOUND_YET


def _protocol(soup: BeautifulSoup) -> tuple[Optional[str], Optional[datetime]]:
    """The authorisation, which this one block lays out as a table with
    its labels in a header row rather than beside each value. The portal
    also writes the number into a hidden input, and that is what is read:
    a column position is a layout, an id is a name.
    """
    field = soup.find(id="nProt")
    number = field.get("value") if isinstance(field, Tag) else None
    row = field.find_parent("tr") if isinstance(field, Tag) else None
    when = None
    if isinstance(row, Tag):
        cells = [_clean(td.get_text()) for td in row.find_all("td")]
        when = next((_when(cell) for cell in cells if _when(cell) is not None), None)
    return (str(number) if number else None), when


def _issuer(soup: BeautifulSoup) -> Issuer:
    panel = _panel(soup, "Emitente")
    cnpj = _DIGITS.sub("", _field(panel, "CNPJ") or "")
    if len(cnpj) != 14:
        raise ParseError("layout_changed", f"issuer CNPJ is {cnpj!r}")
    city = _field(panel, "Município") or ""
    return Issuer(
        cnpj=cnpj,
        ie=_field(panel, "Inscrição Estadual"),
        legal_name=_field(panel, "Nome / Razão Social") or "",
        trade_name=_field(panel, "Nome Fantasia"),
        street=_field(panel, "Endereço"),
        district=_field(panel, "Bairro / Distrito"),
        # "5204508 - CALDAS NOVAS": the IBGE code is not the name.
        city=city.split("-", 1)[1].strip() if "-" in city else (city or None),
        uf=_field(panel, "UF"),
        zip=_DIGITS.sub("", _field(panel, "CEP") or "") or None,
    )


def _items(soup: BeautifulSoup) -> list[CanonicalItem]:
    panel = _panel(soup, "Prod")
    if panel is None:
        raise ParseError("layout_changed", "no products panel")
    out: list[CanonicalItem] = []
    for ordinal, summary in enumerate(panel.select("table.toggle"), start=1):
        detail = summary.find_next_sibling("table")
        cells = [_clean(td.get_text()) for td in summary.find_all("td")]
        if len(cells) < 5:
            raise ParseError("layout_changed", f"item {ordinal} has {len(cells)} cells")
        code = _field(detail, "Código do Produto")
        if not code:
            raise ParseError("layout_changed", f"item {ordinal} has no product code")
        out.append(
            CanonicalItem(
                ordinal=ordinal,
                product_code=code,
                gtin=_field(detail, "Código EAN Comercial"),
                description=cells[1],
                ncm=_field(detail, "Código NCM"),
                cfop=_field(detail, "CFOP"),
                unit=cells[3] or "UN",
                quantity=_money(cells[2]),
                unit_price=_money(_field(detail, "Valor unitário de comercialização")),
                total=_money(cells[4]),
                discount=_money(_field(detail, "Valor do Desconto")),
            )
        )
    if not out:
        raise ParseError("no_items", "the products panel lists no items")
    return out


def _payments(soup: BeautifulSoup) -> list[Payment]:
    panel = _panel(soup, "Cobranca")
    if panel is None:
        return []
    change = _money(_field(panel, "Troco"))
    out: list[Payment] = []
    for row in panel.select("table.toggle"):
        cells = [_clean(td.get_text()) for td in row.find_all("td")]
        if len(cells) < 3 or not cells[2]:
            continue
        # "3 - Cartão de Crédito": the code decides, the words are kept.
        code = cells[1].split("-", 1)[0].strip().zfill(2)
        out.append(
            Payment(
                type=PAYMENT_TYPES.get(code, "other"),
                label=cells[1] or None,
                brand=None,
                amount=_money(cells[2]),
                change=ZERO,
            )
        )
    if out and change > ZERO:
        out[-1] = out[-1].model_copy(update={"change": change})
    return out


def parse_nfe_detail(body: str) -> CanonicalReceipt:
    soup = BeautifulSoup(unwrap_detail(body), "html.parser")
    header = _panel(soup, "NFe")
    if header is None:
        raise ParseError("layout_changed", "no NFe panel")

    key = _DIGITS.sub("", _field(soup, "Chave de Acesso") or "")
    if len(key) != 44:
        raise ParseError("layout_changed", f"access key is {key!r}")

    totals_panel = _panel(soup, "Totais")
    protocol, authorized_at = _protocol(soup)
    items = _items(soup)
    return CanonicalReceipt(
        access_key=key,
        uf=_field(_panel(soup, "Emitente"), "UF") or "",
        model=_field(header, "Modelo") or "65",
        series=int(_field(header, "Série") or "0"),
        number=int(_DIGITS.sub("", _field(header, "Número") or "0") or "0"),
        issued_at=_when(_field(header, "Data de Emissão")),
        protocol=protocol,
        authorized_at=authorized_at,
        issuer=_issuer(soup),
        totals=Totals(
            items_count=len(items),
            products_total=_money(_field(totals_panel, "Valor Total dos Produtos")),
            discount=_money(_field(totals_panel, "Valor Total dos Descontos")),
            addition=_money(_field(totals_panel, "Outras Despesas Acessórias")),
            shipping=_money(_field(totals_panel, "Valor do Frete")),
            total=_money(_field(totals_panel, "Valor Total da NFe")),
            approx_taxes=parse_brl(_field(totals_panel, "Valor Aproximado dos Tributos")),
        ),
        payments=_payments(soup),
        items=items,
        source="sefaz_html",
    )
