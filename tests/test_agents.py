"""The agents' reasoning, without a database: patterns, confidence, notes, checks, periods, close arithmetic."""

import datetime as dt

from hypothesis import given
from hypothesis import strategies as st

from cfa.agents.checks import Checker, normalise_number, valid_iban
from cfa.agents.close import close_month, parse_period
from cfa.agents.coding import CompanyModel, item_key, noted_centre, tax_key, wilson_lower

PEOPLE = [{"id": "u1", "department": "ENG"}, {"id": "u2", "department": "SALES"}]
CENTRES = [
    {"department": "ENG", "code": "4000"},
    {"department": "SALES", "code": "3000"},
    {"department": "ADMIN", "code": "1000"},
]


def booking(date, account, desc="Lizenz", supplier="s1", requester="u1", cc="4000", notes=""):
    return {
        "document_id": f"d{date}{account}",
        "line_no": 0,
        "supplier_id": supplier,
        "supplier_name": "Formfeld Software GmbH",
        "supplier_country": "DE",
        "date": date,
        "requester": requester,
        "line": {"description": desc, "vat_rate": 0.19},
        "account": account,
        "cost_centre": cc,
        "tax_key": "VSt19",
        "notes": notes,
    }


def doc(desc="Lizenz (3 Stk.)", supplier="s1", requester="u1", notes="", country="DE", rate=0.19, kind="invoice"):
    return {
        "id": "x",
        "kind": kind,
        "supplier_id": supplier,
        "supplier_name": "Formfeld Software GmbH",
        "supplier_country": country,
        "requester": requester,
        "notes": notes,
        "lines": [{"description": desc, "net": 1000, "vat_rate": rate, "vat": round(1000 * rate)}],
    }


def test_item_key_ignores_counts_and_positions():
    assert item_key("Lizenz (3 Stk.)") == item_key("Lizenz – Pauschale") == item_key("Lizenz Pos. 12") == "lizenz"
    assert item_key("Art.-Nr. 48213") == "art"


def test_wilson_rewards_more_evidence():
    assert wilson_lower(2, 2, 1.64) < wilson_lower(10, 10, 1.64) < 1
    assert wilson_lower(0, 0, 1.64) == 0


def test_recent_habits_win_over_old_ones():
    old = [booking(f"2026-0{m}-10", "6837") for m in range(1, 6)]
    new = [booking(f"2026-{m:02d}-10", "6495") for m in range(8, 11)]
    model = CompanyModel(old + new, PEOPLE, CENTRES)
    assert model.code_line(doc(), 0, doc()["lines"][0]).account == "6495"


def test_cost_centre_follows_the_requester_unless_a_note_says_otherwise():
    hist = [
        booking(f"2026-0{m}-1{r}", "6837", requester=u, cc=c)
        for m in range(1, 9)
        for r, (u, c) in enumerate([("u1", "4000"), ("u2", "3000")])
    ]
    model = CompanyModel(hist, PEOPLE, CENTRES)
    assert model.code_line(doc(requester="u2"), 0, doc()["lines"][0]).cost_centre == "3000"
    noted = doc(requester="u2", notes="Kostenübernahme durch Verwaltung.")
    lc = model.code_line(noted, 0, noted["lines"][0])
    assert lc.cost_centre == "1000" and "note" in lc.reason


def test_noted_centre_by_code_and_by_name():
    centre = {"ENG": "4000", "SALES": "3000"}
    assert noted_centre("Bitte auf Kostenstelle 3000 buchen.", centre)[0] == "3000"
    assert noted_centre("Charged to Engineering.", centre)[0] == "4000"
    assert noted_centre("Leistungszeitraum 11/2026", centre) is None
    assert noted_centre("Rechnung 3000 Stück", centre) is None  # a number is not a cost centre without saying so


def test_unknown_items_are_not_guessed():
    model = CompanyModel([booking("2026-01-01", "6837")], PEOPLE, CENTRES)  # one booking is not a pattern
    lc = model.code_line(doc(desc="Webcam", supplier="s9"), 0, doc()["lines"][0])
    assert lc.source == "none" and lc.account is None


def test_tax_key_is_read_from_the_invoice():
    assert tax_key(doc(country="IE", rate=0.0), {"vat_rate": 0.0}) == "RC19"
    assert tax_key(doc(), {"vat_rate": 0.07}) == "VSt7"
    assert tax_key(doc(), {"vat_rate": 0.0}) == "NONE"


@given(st.integers(1, 99999), st.sampled_from(["RE-2026-{:04d}", "RE2026/{}", " re-2026-{:05d} ", "Re.-2026-{}"]))
def test_invoice_numbers_normalise(n, fmt):
    assert normalise_number(fmt.format(n)) == normalise_number(f"RE-2026-{n}")


def test_bank_account_valid_on_the_invoice_date():
    s = {"iban": "NEW", "bank_changes": [{"old_iban": "OLD", "new_iban": "NEW", "verified_at": "2026-11-01"}]}
    assert valid_iban(s, "2026-10-20") == "OLD" and valid_iban(s, "2026-11-05") == "NEW"


def _inv(id_, number, gross=1190, date="2026-11-10", iban="DE1", lines=None, country="DE", vat=190):
    lines = lines or [{"description": "Toner", "net": 1000, "vat_rate": 0.19, "vat": 190}]
    return {
        "id": id_,
        "kind": "invoice",
        "supplier_id": "s1",
        "supplier_country": country,
        "number": number,
        "date": date,
        "iban": iban,
        "lines": lines,
        "net_total": sum(x["net"] for x in lines),
        "vat_total": vat,
        "gross_total": gross,
    }


def test_checks_find_each_issue_and_leave_clean_invoices_alone():
    history = [_inv(f"h{i}", f"R{i}", date=f"2026-0{i}-05") for i in range(1, 6)]
    bookings = [{"supplier_id": "s1", "supplier_country": "DE", "line": {"description": "Toner", "vat_rate": 0.19}}] * 5
    ch = Checker(history, bookings, {"s1": {"iban": "DE1", "bank_changes": []}})
    assert ch.check(_inv("c", "R100"), []) == []
    assert [f.issue for f in ch.check(_inv("d", "r-0003"), [])] == ["duplicate"]
    assert [f.issue for f in ch.check(_inv("i", "R101", iban="DE2"), [])] == ["iban_changed"]
    seven = [{"description": "Toner", "net": 1000, "vat_rate": 0.07, "vat": 70}]
    assert [f.issue for f in ch.check(_inv("v", "R102", lines=seven, gross=1070, vat=70), [])] == ["vat_rate_wrong"]
    assert [f.issue for f in ch.check(_inv("a", "R103", gross=1200), [])] == ["arithmetic"]
    assert [f.issue for f in ch.check(_inv("rc", "R104", country="IE"), [])] == ["reverse_charge_missing"]


@given(st.dates(dt.date(2025, 1, 1), dt.date(2030, 12, 1)), st.integers(30, 730))
def test_periods_written_the_usual_ways_are_read(start, days):
    end = start + dt.timedelta(days=days)
    for text in (
        f"Leistungszeitraum: {start:%d.%m.%Y} – {end:%d.%m.%Y}",
        f"Subscription term: {start:%b %d, %Y} to {end:%b %d, %Y}",
        f"Period {start:%Y-%m-%d} – {end:%Y-%m-%d}.",
        f"Versicherungsjahr {start:%d.%m.%Y} bis {end:%d.%m.%Y}",
    ):
        assert parse_period(text) == (start, end), text


def test_period_in_months():
    assert parse_period("Laufzeit 12 Monate ab dem 15.11.2026") == (dt.date(2026, 11, 15), dt.date(2027, 11, 14))
    assert parse_period("Leistungszeitraum 11/2026") is None


def test_deferral_is_day_based_and_respects_materiality():
    d = {
        "id": "a",
        "supplier_id": "s",
        "supplier_name": "Formfeld",
        "date": "2026-11-13",
        "net_total": 365_00,
        "notes": "Leistungszeitraum: 13.11.2026 – 12.11.2027",
        "lines": [{"net": 365_00}],
    }
    res = close_month(
        "2026-11", [d], {"a": [{"account": "6837", "cost_centre": "4000"}]}, [], 100_00, set(), use_llm=False
    )
    (e,) = res.entries
    # 365 days; 18 of them in November; 347 after
    assert (e.debit, e.credit, e.amount_cents) == ("1900", "6837", round(365_00 * 347 / 365))
    assert (
        close_month(
            "2026-11", [d], {"a": [{"account": "6837", "cost_centre": "4000"}]}, [], 1000_00, set(), use_llm=False
        ).entries
        == []
    )


def _monthly(month, net, notes="Leistungszeitraum"):
    return {
        "id": month,
        "supplier_id": "tel",
        "supplier_name": "Funknetz",
        "month": month,
        "date": f"{month}-03",
        "net_total": net,
        "notes": notes,
        "coding": [{"account": "6805", "cost_centre": "4000"}],
    }


def test_accruals_for_missing_recurring_invoices_but_not_ended_contracts():
    hist = [_monthly("2026-08", 300), _monthly("2026-09", 330), _monthly("2026-10", 360)]
    (e,) = close_month("2026-11", [], {}, hist, 0, set(), use_llm=False).entries
    assert (e.debit, e.credit, e.amount_cents, e.supplier_id) == ("6805", "3070", 330, "tel")
    ended = hist[:2] + [_monthly("2026-10", 360, "Vertrag gekündigt zum 31.10.2026 – letzte Rechnung")]
    assert close_month("2026-11", [], {}, ended, 0, set(), use_llm=False).entries == []
    irregular = [_monthly("2026-08", 100), _monthly("2026-09", 900), _monthly("2026-10", 300)]
    assert close_month("2026-11", [], {}, irregular, 0, set(), use_llm=False).entries == []
