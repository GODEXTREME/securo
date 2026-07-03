"""Cash-with-discount vs interest-free instalments decision helper.

In Brazil a shop often offers a discount for paying cash ("à vista") or the same
list price split into N interest-free instalments. Paying cash is only worth the
discount if it beats keeping the money invested while you pay the instalments
over time. This compares the present value of both options at a given investment
rate and reports which is cheaper, by how much, and the break-even discount.
"""
from datetime import date

MAX_N = 360


def _monthly_rate(rate: float, rate_period: str) -> float:
    r = rate / 100.0
    if rate_period == "monthly":
        return r
    return (1.0 + r) ** (1.0 / 12.0) - 1.0


def compare(
    cash_price: float,
    installment_total: float,
    n_installments: int,
    investment_rate: float,
    rate_period: str = "annual",
    first_installment_today: bool = True,
    currency: str = "USD",
) -> dict:
    cash_price = max(0.0, float(cash_price))
    installment_total = max(0.0, float(installment_total))
    n = max(1, min(int(n_installments), MAX_N))
    i = _monthly_rate(investment_rate, rate_period)
    per = installment_total / n

    # Present value of the instalment stream. First instalment at month 0
    # (typical) or month 1.
    offset = 0 if first_installment_today else 1
    pv_installments = sum(per / ((1.0 + i) ** (k + offset)) for k in range(n))

    # Paying cash costs cash_price now (PV = cash_price).
    pv_cash = cash_price

    diff = pv_installments - pv_cash  # >0 ⇒ cash is cheaper in today's money
    cheaper = "cash" if pv_installments > pv_cash else "installments"
    savings = round(abs(diff), 2)

    # Break-even: the cash discount (vs list price) that makes cash exactly worth
    # it — i.e. the cash_price whose PV equals the instalments' PV is
    # pv_installments itself. Expressed as a discount off the list price.
    breakeven_cash_price = round(pv_installments, 2)
    nominal_discount = installment_total - cash_price
    nominal_discount_pct = round(nominal_discount / installment_total * 100, 2) if installment_total > 0 else 0.0
    breakeven_discount_pct = round((installment_total - breakeven_cash_price) / installment_total * 100, 2) if installment_total > 0 else 0.0

    return {
        "currency": currency,
        "cash_price": round(cash_price, 2),
        "installment_total": round(installment_total, 2),
        "n_installments": n,
        "per_installment": round(per, 2),
        "monthly_rate": round(i * 100, 4),
        "pv_cash": round(pv_cash, 2),
        "pv_installments": round(pv_installments, 2),
        "cheaper": cheaper,
        "savings": savings,
        "nominal_discount": round(nominal_discount, 2),
        "nominal_discount_pct": nominal_discount_pct,
        "breakeven_cash_price": breakeven_cash_price,
        "breakeven_discount_pct": breakeven_discount_pct,
        "generated": date.today().isoformat(),
    }
