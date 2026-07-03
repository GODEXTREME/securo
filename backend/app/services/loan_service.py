"""Loan / financing simulator (Price and SAC amortization).

Stateless calculator: given a principal, an interest rate, a term and (optionally)
an extra monthly payment, it builds the amortization schedule under both the
Price system (fixed instalments) and the SAC system (constant amortization,
decreasing instalments) so the user can compare total interest and how fast the
balance falls before signing a loan. No database access — pure math.
"""
from datetime import date

MAX_MONTHS = 600  # 50-year guard


def _monthly_rate(rate: float, rate_period: str) -> float:
    """Convert the quoted rate to an effective monthly rate.

    ``monthly`` rates are used as-is; ``annual`` rates are converted with the
    effective (compound) formula ``(1+a)^(1/12)-1`` — the Brazilian convention
    for financing quotes."""
    r = rate / 100.0
    if rate_period == "monthly":
        return r
    return (1.0 + r) ** (1.0 / 12.0) - 1.0


def _payoff_date(months: int) -> str:
    today = date.today()
    y = today.year + (today.month - 1 + months) // 12
    m = (today.month - 1 + months) % 12 + 1
    return date(y, m, 1).isoformat()


def _simulate(principal: float, i: float, n: int, method: str, extra: float) -> dict:
    """Build an amortization schedule.

    ``method`` is ``price`` (fixed instalment) or ``sac`` (constant amortization).
    ``extra`` is an optional additional payment applied to principal each month,
    which shortens the term. Returns the schedule plus summary totals.
    """
    balance = principal
    schedule: list[dict] = []
    total_interest = 0.0
    total_paid = 0.0

    if method == "price":
        if i > 0:
            base_payment = principal * i / (1.0 - (1.0 + i) ** (-n))
        else:
            base_payment = principal / n
    amort_sac = principal / n if n else 0.0

    month = 0
    while balance > 0.005 and month < MAX_MONTHS:
        month += 1
        interest = balance * i
        if method == "sac":
            amort = amort_sac
            payment = amort + interest
        else:  # price
            payment = base_payment
            amort = payment - interest
        # Optional extra payment straight to principal.
        amort += extra
        if amort >= balance:  # final (partial) instalment
            amort = balance
            payment = amort + interest
        balance -= amort
        total_interest += interest
        total_paid += payment
        schedule.append({
            "n": month,
            "payment": round(payment, 2),
            "interest": round(interest, 2),
            "principal": round(amort, 2),
            "balance": round(max(balance, 0.0), 2),
        })

    return {
        "method": method,
        "months": month,
        "first_payment": schedule[0]["payment"] if schedule else 0.0,
        "last_payment": schedule[-1]["payment"] if schedule else 0.0,
        "total_interest": round(total_interest, 2),
        "total_paid": round(total_paid, 2),
        "payoff_date": _payoff_date(month),
        "amortized": month < MAX_MONTHS,
        "schedule": schedule,
    }


def simulate(
    principal: float,
    rate: float,
    months: int,
    rate_period: str = "annual",
    extra_payment: float = 0.0,
    method: str = "both",
    currency: str = "USD",
) -> dict:
    principal = max(0.0, float(principal))
    months = max(1, min(int(months), MAX_MONTHS))
    extra = max(0.0, float(extra_payment))
    i = _monthly_rate(rate, rate_period)

    out: dict = {
        "currency": currency,
        "principal": round(principal, 2),
        "monthly_rate": round(i * 100, 4),
        "annual_rate": round(((1.0 + i) ** 12 - 1.0) * 100, 4),
        "term_months": months,
        "extra_payment": round(extra, 2),
    }
    methods = ["price", "sac"] if method == "both" else [method]
    results = {m: _simulate(principal, i, months, m, extra) for m in methods}
    out["results"] = results
    if "price" in results and "sac" in results:
        out["recommended"] = (
            "sac" if results["sac"]["total_interest"] <= results["price"]["total_interest"] else "price"
        )
    else:
        out["recommended"] = methods[0]
    return out
