"""데이터 포맷터 단위 테스트."""

from data.formatter import KEY_ACCOUNTS, _fmt_amount, _pick_accounts


def test_fmt_amount_billions():
    assert _fmt_amount(1_234_567_890_000) == "12,345.7억원"


def test_fmt_amount_zero():
    assert _fmt_amount(0) == "0"


def test_pick_accounts_filters():
    data = [
        {"account_nm": "매출액", "thstrm_amount": "1000"},
        {"account_nm": "기타항목", "thstrm_amount": "500"},
    ]
    picked = _pick_accounts(data)
    assert "매출액" in picked
    assert "기타항목" not in picked
    assert set(picked) <= set(KEY_ACCOUNTS)
