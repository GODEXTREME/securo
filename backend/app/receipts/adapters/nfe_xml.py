"""Parser for the authorised NF-e document itself (`procNFe` 4.00).

Pernambuco answers a QR consultation with the **XML**, not a rendered
DANFE. That is a better source than any page, for three reasons that
show up directly in this file:

  * **The GTIN is in it.** `det/prod/cEAN` is the barcode the shared HTML
    template never shows, which is what confines the catalogue to
    per-chain identity everywhere else. Here every item arrives globally
    identifiable, with nobody scanning anything.
  * **The state is stated, not inferred.** `protNFe/infProt/cStat` says
    authorised (100), cancelled (101/151) or unknown (217) with a code.
    No hunting for "QR Code Inválido" in prose that each portal words
    differently.
  * **The layout is a published schema.** An HTML template changes when a
    designer feels like it; `procNFe_v4.00` does not.

Numbers here use a decimal point, not the Brazilian comma, so they are
read with `Decimal` directly rather than through `parse_brl`. Quantities
and unit prices carry four and ten decimal places respectively; both are
kept exactly as written and never become floats.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Optional
from xml.etree import ElementTree

from app.receipts.adapters.base import FetchedPage, PageKind, ParseError
from app.receipts.canonical import (
    ZERO,
    CanonicalItem,
    CanonicalReceipt,
    Issuer,
    Payment,
    Totals,
)

NS = {"n": "http://www.portalfiscal.inf.br/nfe"}

#: `cStat` on the authorisation protocol. The full list is long; these are
#: the ones that decide what happens to a receipt.
AUTHORIZED = {"100", "150"}
CANCELLED = {"101", "151", "135", "155"}
NOT_FOUND = {"217", "999"}

#: `tPag`, as published in the NF-e manual, mapped onto the vocabulary the
#: rest of the system already speaks. Anything unlisted keeps its code in
#: `label` rather than being flattened into "other" silently.
PAYMENT_TYPES = {
    "01": "cash",
    "02": "other",          # cheque
    "03": "credit_card",
    "04": "debit_card",
    "05": "store_credit",
    "10": "food_voucher",
    "11": "meal_voucher",
    "12": "other",          # vale presente
    "13": "other",          # vale combustível
    "15": "other",          # boleto
    "16": "other",          # depósito
    "17": "pix",
    "18": "other",          # transferência
    "19": "other",          # fidelidade
    "20": "pix",
    "21": "store_credit",
    "90": "other",          # sem pagamento
    "99": "other",
}


def _text(node: Optional[ElementTree.Element], path: str) -> Optional[str]:
    if node is None:
        return None
    found = node.find(path, NS)
    return found.text.strip() if found is not None and found.text else None


def _decimal(node: Optional[ElementTree.Element], path: str, default: Decimal = ZERO) -> Decimal:
    raw = _text(node, path)
    if raw is None:
        return default
    try:
        return Decimal(raw)
    except InvalidOperation as exc:
        raise ParseError("bad_number", f"{path}: {raw!r}") from exc


def _root(xml: str) -> ElementTree.Element:
    try:
        return ElementTree.fromstring(xml)
    except ElementTree.ParseError as exc:
        raise ParseError("layout_changed", f"not xml: {exc}") from exc


def _inf_nfe(root: ElementTree.Element) -> Optional[ElementTree.Element]:
    """The note itself, wherever the state wrapped it.

    Pernambuco nests the real `nfeProc` inside a `proc` element of its own
    consultation envelope, so the document is not always the root's own
    child. Searching for `infNFe` anywhere is both simpler and immune to
    the next state that wraps it differently.
    """
    return root.find(".//n:infNFe", NS)


def _prot(root: ElementTree.Element) -> Optional[ElementTree.Element]:
    return root.find(".//n:protNFe/n:infProt", NS)


def classify_nfe_xml(page: FetchedPage) -> PageKind:
    """What the document says about itself.

    A body that is not XML at all is the portal answering with something
    else — a maintenance page, a challenge — and that is an error page,
    not a broken parser.
    """
    try:
        root = ElementTree.fromstring(page.html)
    except ElementTree.ParseError:
        return PageKind.ERROR_PAGE
    # Well-formed is not the same as ours: a maintenance page can be valid
    # XML and would otherwise be read as "the note is not published yet",
    # which schedules retries against a portal that is simply down.
    if not root.tag.startswith("{" + NS["n"] + "}"):
        return PageKind.ERROR_PAGE
    status = _text(_prot(root), "n:cStat") or _text(root, ".//n:cStat")
    if status in AUTHORIZED:
        return PageKind.AUTHORIZED
    if status in CANCELLED:
        return PageKind.CANCELLED
    if status in NOT_FOUND:
        return PageKind.NOT_FOUND_YET
    if _inf_nfe(root) is not None:
        # A note is here with a status we do not have a rule for. Better
        # to stop and be looked at than to guess at a fiscal state.
        return PageKind.ERROR_PAGE
    return PageKind.NOT_FOUND_YET


def _issuer(emit: ElementTree.Element) -> Issuer:
    address = emit.find("n:enderEmit", NS)
    cnpj = _text(emit, "n:CNPJ")
    if not cnpj:
        raise ParseError("layout_changed", "issuer has no CNPJ")
    return Issuer(
        cnpj=cnpj,
        ie=_text(emit, "n:IE"),
        legal_name=_text(emit, "n:xNome") or "",
        trade_name=_text(emit, "n:xFant"),
        street=_text(address, "n:xLgr"),
        number=_text(address, "n:nro"),
        district=_text(address, "n:xBairro"),
        city=_text(address, "n:xMun"),
        uf=_text(address, "n:UF"),
        zip=_text(address, "n:CEP"),
    )


def _item(det: ElementTree.Element, ordinal: int) -> CanonicalItem:
    prod = det.find("n:prod", NS)
    if prod is None:
        raise ParseError("layout_changed", f"item {ordinal} has no prod")
    code = _text(prod, "n:cProd")
    description = _text(prod, "n:xProd")
    if not code or not description:
        raise ParseError("layout_changed", f"item {ordinal} has no code or description")
    return CanonicalItem(
        ordinal=ordinal,
        product_code=code,
        # `SEM GTIN` and other placeholders are the portal's way of saying
        # the item has no barcode; the model's validator turns anything
        # that is not a real GTIN into None.
        gtin=_text(prod, "n:cEAN"),
        description=description,
        ncm=_text(prod, "n:NCM"),
        cfop=_text(prod, "n:CFOP"),
        unit=_text(prod, "n:uCom") or "UN",
        quantity=_decimal(prod, "n:qCom"),
        unit_price=_decimal(prod, "n:vUnCom"),
        total=_decimal(prod, "n:vProd"),
        discount=_decimal(prod, "n:vDesc"),
    )


def _payments(pag: Optional[ElementTree.Element]) -> list[Payment]:
    if pag is None:
        return []
    change = _decimal(pag, "n:vTroco")
    out: list[Payment] = []
    for detpag in pag.findall("n:detPag", NS):
        code = _text(detpag, "n:tPag") or "99"
        card = detpag.find("n:card", NS)
        out.append(
            Payment(
                type=PAYMENT_TYPES.get(code, "other"),
                label=code,
                brand=_text(card, "n:tBand"),
                amount=_decimal(detpag, "n:vPag"),
                change=ZERO,
            )
        )
    # Change belongs to the transaction, not to a line of it. It is put on
    # the last payment because that is the one the customer handed over.
    if out and change > ZERO:
        out[-1] = out[-1].model_copy(update={"change": change})
    return out


def _when(raw: Optional[str]) -> Optional[datetime]:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def parse_nfe_xml(xml: str) -> CanonicalReceipt:
    root = _root(xml)
    inf = _inf_nfe(root)
    if inf is None:
        raise ParseError("layout_changed", "no infNFe in the document")

    key = (inf.get("Id") or "").removeprefix("NFe")
    if len(key) != 44:
        raise ParseError("layout_changed", f"infNFe Id is not an access key: {inf.get('Id')!r}")

    ide, emit = inf.find("n:ide", NS), inf.find("n:emit", NS)
    if ide is None or emit is None:
        raise ParseError("layout_changed", "document has no ide or emit")

    items = [_item(det, index) for index, det in enumerate(inf.findall("n:det", NS), start=1)]
    if not items:
        raise ParseError("no_items", "the document lists no items")

    icms_tot = inf.find("n:total/n:ICMSTot", NS)
    if icms_tot is None:
        raise ParseError("no_totals", "the document has no ICMSTot")

    prot = _prot(root)
    return CanonicalReceipt(
        access_key=key,
        uf=_text(emit, "n:enderEmit/n:UF") or "",
        tp_amb=int(_text(ide, "n:tpAmb") or "1"),
        model=_text(ide, "n:mod") or "65",
        series=int(_text(ide, "n:serie") or "0"),
        number=int(_text(ide, "n:nNF") or "0"),
        issued_at=_when(_text(ide, "n:dhEmi")),
        protocol=_text(prot, "n:nProt"),
        authorized_at=_when(_text(prot, "n:dhRecbto")),
        issuer=_issuer(emit),
        customer_cpf=_text(inf, "n:dest/n:CPF"),
        totals=Totals(
            items_count=len(items),
            products_total=_decimal(icms_tot, "n:vProd"),
            discount=_decimal(icms_tot, "n:vDesc"),
            addition=ZERO,
            shipping=_decimal(icms_tot, "n:vFrete"),
            total=_decimal(icms_tot, "n:vNF"),
            approx_taxes=_decimal(icms_tot, "n:vTotTrib"),
        ),
        payments=_payments(inf.find("n:pag", NS)),
        items=items,
        source="dfe_xml",
    )
