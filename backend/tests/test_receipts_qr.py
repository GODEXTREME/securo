"""The QR code and the access key: pure parsing, no network, no database."""
from datetime import datetime
from decimal import Decimal

import pytest

from app.receipts.gtin import gs1_check_digit, normalize_gtin
from app.receipts.qr import (
    QrError,
    access_key_check_digit,
    parse_access_key,
    parse_qr_payload,
    policy_rejection,
)

KEY = "32260800063960006050650050003784571128411294"
URL_V2 = f"http://app.sefaz.es.gov.br/ConsultaNFCe?p={KEY}|2|1|1|4020a74fad969d92f6bb16ba1a7b4a177771fb3e"


def _with_dv(first43: str) -> str:
    return first43 + str(access_key_check_digit(first43))


class TestAccessKey:
    def test_decodes_every_field_of_the_example(self):
        key = parse_access_key(KEY)
        assert key.c_uf == "32" and key.uf == "ES"
        assert (key.year, key.month) == (2026, 8)
        assert key.issuer_cnpj == "00063960006050"
        assert key.issuer_cnpj_root == "00063960"
        assert key.model == "65" and key.is_nfce
        assert key.series == 5
        assert key.number == 378457
        assert key.tp_emis == 1
        assert key.c_nf == "12841129"
        assert key.check_digit == 4

    def test_accepts_the_printed_grouping(self):
        grouped = " ".join(KEY[i:i + 4] for i in range(0, 44, 4))
        assert parse_access_key(grouped).key == KEY

    def test_check_digit_remainder_below_two_is_zero(self):
        # Search for a body whose weighted sum leaves remainder 0 or 1.
        for n in range(100000):
            body = f"{KEY[:34]}{n:09d}"[:43]
            total = sum(int(d) * w for d, w in zip(reversed(body), [2, 3, 4, 5, 6, 7, 8, 9] * 6))
            if total % 11 < 2:
                assert access_key_check_digit(body) == 0
                return
        pytest.fail("no body with remainder < 2 found")

    @pytest.mark.parametrize(
        "raw,code",
        [
            ("", "empty"),
            ("abc", "not_digits"),
            (KEY[:-1], "length"),
            (KEY[:-1] + "5", "check_digit"),
            (_with_dv("99" + KEY[2:43]), "unknown_uf"),
            (_with_dv(KEY[:4] + "13" + KEY[6:43]), "bad_month"),
        ],
    )
    def test_rejects_with_a_stable_code(self, raw, code):
        with pytest.raises(QrError) as exc:
            parse_access_key(raw)
        assert exc.value.code == code


class TestQrPayload:
    def test_v2_positional(self):
        p = parse_qr_payload(URL_V2)
        assert p.key.key == KEY
        assert p.url == URL_V2
        assert p.version == 200 and p.tp_amb == 1
        assert p.c_id_token == "1"
        assert p.signature == "4020a74fad969d92f6bb16ba1a7b4a177771fb3e"
        assert not p.contingency and p.has_signature

    def test_v3_and_six_digit_token(self):
        p = parse_qr_payload(f"https://x.gov.br/q?p={KEY}|3|1|000001|abc")
        assert p.version == 300 and p.c_id_token == "000001"

    def test_contingency_nine_fields_with_hex_date(self):
        dh = "2026-08-14T18:32:00-03:00".encode().hex()
        p = parse_qr_payload(f"http://app.sefaz.es.gov.br/ConsultaNFCe?p={KEY}|2|1|{dh}|81.87|0.00|abcd|1|deadbeef")
        assert p.contingency
        assert p.issued_at == datetime.fromisoformat("2026-08-14T18:32:00-03:00")
        assert p.total == Decimal("81.87") and p.icms == Decimal("0.00")
        assert p.dig_val == "abcd"

    def test_v1_named_parameters(self):
        p = parse_qr_payload(
            f"http://nfce.sefaz.xx.gov.br/consulta?chNFe={KEY}&nVersao=100&tpAmb=1&dhEmi=2026-08-14T18:32:00-03:00&vNF=81.87&vICMS=0.00&digVal=x&cIdToken=000001&cHashQRCode=ff"
        )
        assert p.version == 100 and p.signature == "ff" and p.contingency
        assert p.total == Decimal("81.87")

    def test_pasted_text_around_the_url(self):
        p = parse_qr_payload(f"veja a nota: {URL_V2} obrigado")
        assert p.url == URL_V2

    def test_bare_key_has_no_signature(self):
        p = parse_qr_payload(KEY)
        assert p.url is None and p.version == 0 and p.tp_amb == 1
        assert not p.has_signature

    def test_homologation_and_nfe_are_policy_not_parse(self):
        homolog = parse_qr_payload(f"http://x.gov.br/q?p={KEY}|2|2|1|abc")
        assert policy_rejection(homolog) == "homolog"
        nfe_key = _with_dv(KEY[:20] + "55" + KEY[22:43])
        nfe = parse_qr_payload(nfe_key)
        assert nfe.key.model == "55" and policy_rejection(nfe) == "not_nfce"
        assert policy_rejection(parse_qr_payload(URL_V2)) is None

    @pytest.mark.parametrize(
        "text,code",
        [
            ("", "empty"),
            ("nada aqui", "unrecognized"),
            (f"http://x.gov.br/q?p={KEY}|2|1", "qr_fields"),
            (f"http://x.gov.br/q?p={KEY}|9|1|1|x", "qr_version"),
            (f"http://x.gov.br/q?p={KEY}|2|3|1|x", "qr_tpamb"),
            ("http://x.gov.br/q?foo=bar", "qr_format"),
        ],
    )
    def test_rejects_with_a_stable_code(self, text, code):
        with pytest.raises(QrError) as exc:
            parse_qr_payload(text)
        assert exc.value.code == code


class TestGtin:
    def test_ean13_pads_to_fourteen(self):
        assert normalize_gtin("7891000100103") == "07891000100103"

    def test_upc_a_and_ean8(self):
        assert normalize_gtin("012345678905") == "00012345678905"
        assert normalize_gtin("96385074") == "00000096385074"

    @pytest.mark.parametrize("raw", [None, "", "SEM GTIN", "0000000000000", "7891000100104", "12345", "abc"])
    def test_anything_else_is_none(self, raw):
        assert normalize_gtin(raw) is None

    def test_check_digit(self):
        assert gs1_check_digit("789100010010") == 3
