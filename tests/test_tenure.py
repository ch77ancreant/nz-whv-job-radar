from datetime import date

import pytest

from nz_job_radar.tenure import add_calendar_months, assess_tenure


@pytest.mark.parametrize(
    ("start", "months", "expected"),
    [
        (date(2026, 1, 31), 1, date(2026, 2, 28)),
        (date(2024, 1, 31), 1, date(2024, 2, 29)),
        (date(2024, 2, 29), 12, date(2025, 2, 28)),
        (date(2026, 11, 30), 3, date(2027, 2, 28)),
        (date(2026, 12, 31), 3, date(2027, 3, 31)),
        (date(2026, 3, 31), -1, date(2026, 2, 28)),
        (date(2026, 1, 31), 0, date(2026, 1, 31)),
    ],
)
def test_calendar_months(start: date, months: int, expected: date) -> None:
    assert add_calendar_months(start, months) == expected


@pytest.mark.parametrize(
    "text",
    [
        "Fixed-term contract for 2 months.",
        "A three-month temporary role.",
        "Employment duration: two to three months.",
        "Contract for 2–3 months.",
        "Contract for 2 months to 3 months.",
        "A 12-week contract.",
        "An eighty-eight day assignment.",
        "Temporary role for up to 3 months.",
        "Employment duration: maximum of three months.",
        "Contract: 3 months or less.",
        "Contract for 2 months, with no extension.",
        "Contract for between two and three months.",
    ],
)
def test_explicit_bounded_durations_are_compatible(text: str) -> None:
    result = assess_tenure(text)
    assert result.status == "compatible"
    assert result.evidence
    assert result.reasons


@pytest.mark.parametrize(
    "text",
    [
        "Six-month employment contract.",
        "Minimum commitment of four months.",
        "Must be available for at least 4 months.",
        "Contract for 4 to 6 months.",
        "Contract duration: fourteen weeks.",
        "Contract for 93 days.",
        "Contract for more than 3 months.",
        "One-year employment contract.",
        "Minimum required: four months of employment.",
        "Contract for four months. We offer flexible shifts.",
        "Contract for four months with flexible shifts.",
        "Contract for two months. Applicants must commit to a minimum of six months.",
        "Temporary role for 2 months. WHV holders welcome. "
        "Applicants must commit to a minimum of six months.",
    ],
)
def test_explicit_excessive_durations_are_incompatible(text: str) -> None:
    assert assess_tenure(text).status == "exceeds_limit"


@pytest.mark.parametrize(
    "text",
    [
        "Contract for 89 days.",
        "Contract for 90 days.",
        "Contract for 91 days.",
        "Contract for 92 days.",
        "Contract for 13 weeks.",
        "Contract for 2 to 4 months.",
        "Minimum commitment of 3 months.",
        "Contract for 3 months or more.",
        "Contract for up to 4 months.",
        "A minimum stay of 3 months in this role.",
        "Must commit to three months of work.",
        "You must be available for three months.",
        "Contract for at least a three-month period.",
        "Contract for between two and four months.",
    ],
)
def test_boundary_durations_need_confirmation(text: str) -> None:
    assert assess_tenure(text).status == "boundary"


@pytest.mark.parametrize(
    "text",
    [
        "",
        "Casual kitchen hand.",
        "Seasonal work.",
        "Minimum commitment of 2 months.",
        "Contract for approximately 2 months.",
        "Contract for 2 months, potentially longer.",
        "Contract for 2 months. Extension possible.",
        "Initial contract for 2 months.",
        "Contract for 2 or 3 months.",
        "Contract for 3 to 2 months.",
        "Contract for 0 months.",
        "Contract for 2.5 months.",
        "Contract for 2 weeks to 3 months.",
        "Contract for 2 months. Employment duration: 6 months.",
        "Contract for 2 months. Employment duration: 3 months.",
        "Contract for 1 year and 2 months.",
        "Contract for one hundred and two days.",
        "Contract for three months and a half.",
        "Contract for 2 months with an option to continue.",
        "Contract for 2 or 6 months.",
        "Contract for two months. Minimum commitment is approximately six months.",
        "Contract for two months plus a further two months.",
        "Contract for two and three months.",
        "This is not a two-month contract.",
        "The contract is not limited to three months.",
        "The contract is expected to last three months.",
        "Fixed-term role. Must have 3 months of experience.",
        "Casual role requiring at least 6 months experience.",
        "Work visa must remain valid for 6 months.",
        "A temporary role with 3 months training.",
        "Temporary role with 2 months notice required.",
        "Casual employment, 40 hours per week.",
        "Company established 3 months ago. Casual work available.",
    ],
)
def test_missing_ambiguous_or_unrelated_durations_are_unknown(text: str) -> None:
    assert assess_tenure(text).status == "unknown"


@pytest.mark.parametrize(
    ("text", "start", "end", "status"),
    [
        ("Contract from 2026-01-31 to 2026-04-29.", "2026-01-31", "2026-04-29", "compatible"),
        ("Contract from 2026-01-31 to 2026-04-30.", "2026-01-31", "2026-04-30", "boundary"),
        ("Contract from 2026-01-31 to 2026-05-01.", "2026-01-31", "2026-05-01", "exceeds_limit"),
        ("Contract: 31/01/2026 - 29/04/2026.", "2026-01-31", "2026-04-29", "compatible"),
        (
            "Employment from 1 June 2026 until 31 August 2026.",
            "2026-06-01",
            "2026-08-31",
            "compatible",
        ),
        ("Employment from 1 Jun 2026 until 1 Sep 2026.", "2026-06-01", "2026-09-01", "boundary"),
        (
            "Contract from 1st June 2026 to 2nd September 2026.",
            "2026-06-01",
            "2026-09-02",
            "exceeds_limit",
        ),
        (
            "Contract starts 30 November 2023 and ends 29 February 2024.",
            "2023-11-30",
            "2024-02-29",
            "boundary",
        ),
        (
            "Contract starts 30 November 2024 and ends 1 March 2025.",
            "2024-11-30",
            "2025-03-01",
            "exceeds_limit",
        ),
        ("Start date: 2026-01-01\nEnd date: 2026-02-28", "2026-01-01", "2026-02-28", "compatible"),
    ],
)
def test_full_date_ranges(text: str, start: str, end: str, status: str) -> None:
    result = assess_tenure(text)
    assert result.status == status
    assert result.start_date == start
    assert result.end_date == end


@pytest.mark.parametrize(
    "text",
    [
        "Contract from 31/02/2026 to 31/03/2026.",
        "Contract from 29 February 2025 to 29 March 2025.",
        "Contract from 2026-13-01 to 2026-14-01.",
        "Contract from 2026-05-01 to 2026-01-01.",
        "Contract from 1 June to 31 August.",
        "Contract from 01/06/26 to 31/08/26.",
        "Contract from 01/06 to 31/08.",
        "Contract starts 2026-06-01.",
        "Contract ends 2026-08-01.",
        "Contract dates: 2026-06-01 2026-08-01.",
        "Contract from 2026-06-01 to 2026-08-01 or 2026-09-01.",
        "Applications close 2026-06-01. Start date: 2026-07-01.",
        "Applications close 1 June 2026; casual contract available.",
        "Casual role. Interviews from 1 June 2026 to 1 July 2026.",
        "Work visa valid from 1 June 2026 to 1 July 2026.",
        "Contract for 2 months from 1 June to 1 August.",
        "Contract for 2 months from 2026-01-01 to 2026-03-31.",
        "Contract for 6 months from 2026-01-01 to 2026-02-01.",
    ],
)
def test_invalid_unrelated_or_conflicting_dates_are_unknown(text: str) -> None:
    assert assess_tenure(text).status == "unknown"


def test_application_deadline_does_not_join_employment_dates() -> None:
    result = assess_tenure(
        "Applications close 1 May 2026. Contract from 1 June 2026 to 31 July 2026."
    )
    assert result.status == "compatible"
    assert result.start_date == "2026-06-01"
    assert result.end_date == "2026-07-31"
    assert all("1 May" not in snippet for snippet in result.evidence)


@pytest.mark.parametrize(
    ("text", "status"),
    [
        ("Contract for 2 months from 2026-01-01 to 2026-03-01.", "compatible"),
        ("Contract for 2 months from 2026-01-01 to 2026-02-28.", "compatible"),
        ("Contract for 3 months from 2026-01-01 to 2026-04-01.", "boundary"),
        ("Contract for 90 days starting 2026-02-01.", "exceeds_limit"),
        ("Contract for 90 days starting 2026-07-01.", "compatible"),
        ("Contract for 89 days starting 2026-02-01.", "boundary"),
    ],
)
def test_duration_with_known_dates(text: str, status: str) -> None:
    assert assess_tenure(text).status == status


def test_evidence_is_original_and_bounded() -> None:
    text = "A welcoming team " * 25 + "offers a fixed-term contract for TWO MONTHS."
    result = assess_tenure(text)
    assert result.status == "compatible"
    assert result.evidence
    assert all(len(snippet) <= 240 and snippet in text for snippet in result.evidence)
    assert any("TWO MONTHS" in snippet for snippet in result.evidence)


def test_long_date_evidence_keeps_both_dates() -> None:
    text = "A welcoming team " * 25 + "offers a contract from 2026-01-01 to 2026-02-28."
    result = assess_tenure(text)
    assert result.status == "compatible"
    assert all(len(snippet) <= 240 and snippet in text for snippet in result.evidence)
    assert any("2026-01-01" in snippet for snippet in result.evidence)
    assert any("2026-02-28" in snippet for snippet in result.evidence)


def test_separate_date_labels_retain_original_evidence() -> None:
    text = "Start date: 2026-01-01\nEnd date: 2026-02-28"
    result = assess_tenure(text)
    assert result.status == "compatible"
    assert all(snippet in text for snippet in result.evidence)


def test_unrelated_flexibility_does_not_erase_explicit_tenure() -> None:
    result = assess_tenure(
        "Contract for two months. We offer flexible shifts and a negotiable salary."
    )
    assert result.status == "compatible"


@pytest.mark.parametrize(
    "text",
    [
        "Contract for 2 months starting 9999-12-01.",
        "Contract for 2 days starting 9999-12-01.",
        "Contract from 9999-12-01 to 9999-12-31.",
    ],
)
def test_extreme_calendar_dates_do_not_crash(text: str) -> None:
    assert assess_tenure(text).status == "unknown"


def test_extension_reason_preserves_original_extension_evidence() -> None:
    result = assess_tenure("Contract for two months. Extension possible.")
    assert result.status == "unknown"
    assert "Extension possible." in result.evidence


def test_small_calendar_year_does_not_underflow() -> None:
    result = assess_tenure("Contract for up to two months from 0001-01-01 to 0001-02-01.")
    assert result.status == "compatible"


@pytest.mark.parametrize(
    "historical",
    [
        "We require work experience from 2026-01-01 to 2026-03-01.",
        "Previous employment from 2026-01-01 to 2026-03-01 is required.",
        "Prior contract from 2026-01-01 to 2026-03-01 must be listed on your CV.",
        "Employment history from 2026-01-01 to 2026-03-01 is required.",
        "This contract does not run from 2026-01-01 to 2026-03-01.",
        "The contract won't run from 2026-01-01 to 2026-03-01.",
    ],
)
def test_historical_or_negated_dates_do_not_establish_current_tenure(historical: str) -> None:
    result = assess_tenure(
        "Temporary fixed-term position. Working holiday visa holders welcome. " + historical
    )
    assert result.status == "unknown"
    assert result.start_date is None
    assert result.end_date is None


@pytest.mark.parametrize(
    "prefix",
    [
        "Previous employment from 2025-01-01 to 2025-09-01 is required. ",
        "Work experience from 2025-01-01 to 2025-09-01 is required; ",
        "Previous employment from 2025-01-01 to 2025-09-01, ",
        "Applications close 2026-05-01, ",
        "This contract does not run from 2025-01-01 to 2025-09-01. ",
    ],
)
def test_historical_or_deadline_pair_does_not_block_current_contract(prefix: str) -> None:
    result = assess_tenure(prefix + "current contract from 2026-06-01 to 2026-07-31.")
    assert result.status == "compatible"
    assert result.start_date == "2026-06-01"
    assert result.end_date == "2026-07-31"


def test_current_contract_dates_ignore_a_following_historical_pair() -> None:
    result = assess_tenure(
        "Current contract from 2026-06-01 to 2026-07-31; "
        "previous employment from 2025-01-01 to 2025-09-01 is required."
    )
    assert result.status == "compatible"
    assert result.start_date == "2026-06-01"
    assert result.end_date == "2026-07-31"
