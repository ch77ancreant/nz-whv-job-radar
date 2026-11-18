from dataclasses import FrozenInstanceError, replace
from datetime import date, timedelta

import pytest

from nz_job_radar.jobs import Job
from nz_job_radar.whv import (
    DISCLAIMER,
    RULES_CHECKED_AT,
    RULES_SOURCE_URL,
    RULES_VERSION,
    assess_job,
)

CHECKED = date.fromisoformat(RULES_CHECKED_AT)


def job(description: str | None, **updates: object) -> Job:
    base = Job(
        source_job_id="10000001",
        source_url="https://nz.seek.com/job/10000001",
        title="Guest Services Assistant",
        employer="Example Resort",
        location="Queenstown",
        country="NZ",
        employment_type="Full time",
        salary=None,
        posted_at="2026-10-01",
        closes_at="2026-10-20",
        description=description,
    )
    return replace(base, **updates)


def test_explicit_temporary_whv_contract_is_green() -> None:
    result = assess_job(job("Temporary role for 2 months. WHV holders welcome."), today=CHECKED)
    assert result.label == "likely_suitable"
    assert result.score == 90
    assert result.tenure.status == "compatible"
    assert result.confidence == "medium"


def test_explicit_dated_nonpermanent_contract_reaches_threshold() -> None:
    result = assess_job(job("Fixed-term contract from 2026-10-01 to 2026-11-30."), today=CHECKED)
    assert result.label == "likely_suitable"
    assert result.score == 70
    assert result.tenure.start_date == "2026-10-01"


def test_bounded_term_without_enough_positive_evidence_is_yellow() -> None:
    result = assess_job(job("Temporary role for 2 months."), today=CHECKED)
    assert result.label == "needs_confirmation"
    assert result.score == 60


@pytest.mark.parametrize("employment_type", ["Casual/Vacation", "Contract/Temp"])
def test_actor_temporary_categories_supply_type_evidence_only(employment_type: str) -> None:
    result = assess_job(
        job("Guest services duties.", employment_type=employment_type), today=CHECKED
    )
    assert result.label == "needs_confirmation"
    assert result.score == 25
    assert result.tenure.status == "unknown"
    assert any(
        item.field == "employment_type" and item.quote == employment_type
        for item in result.evidence
    )


@pytest.mark.parametrize("employment_type", ["Casual/Vacation", "Contract/Temp", "contract / temp"])
def test_actor_temporary_categories_can_combine_with_sufficient_evidence(
    employment_type: str,
) -> None:
    result = assess_job(
        job("Employment for two months. WHV holders welcome.", employment_type=employment_type),
        today=CHECKED,
    )
    assert result.label == "likely_suitable"
    assert result.score == 90


@pytest.mark.parametrize(
    "employment_type", ["Full time", "Part time", "Full-time", "Part-time", "Not Contract/Temp"]
)
def test_other_category_values_do_not_imply_permanent_or_temporary(employment_type: str) -> None:
    result = assess_job(
        job("Guest services duties.", employment_type=employment_type), today=CHECKED
    )
    assert result.label == "needs_confirmation"
    assert result.score == 0


def test_actor_category_alias_does_not_apply_to_arbitrary_description_text() -> None:
    result = assess_job(
        job("Select Casual/Vacation or Contract/Temp in the search form."), today=CHECKED
    )
    assert result.label == "needs_confirmation"
    assert result.score == 0


@pytest.mark.parametrize(
    "description",
    [
        "Seasonal position. WHV holders welcome.",
        "Casual role. WHV holders welcome.",
        "Temporary role. Working holiday visa holders are welcome.",
        "Full time role. WHV holders welcome.",
    ],
)
def test_unknown_term_never_green(description: str) -> None:
    result = assess_job(job(description), today=CHECKED)
    assert result.label == "needs_confirmation"
    assert result.tenure.status == "unknown"


@pytest.mark.parametrize(
    "description",
    [
        "Permanent position. WHV holders welcome. Temporary contract for 2 months.",
        "This role is permanent.",
        "This is a permanent full-time job.",
        "Fixed-term contract for 6 months. WHV holders welcome.",
        "Temporary role. Minimum commitment of 4 months. WHV holders welcome.",
        "No working holiday visas. Temporary role for 2 months.",
        "Working holiday visa holders are not accepted.",
        "WHV holders cannot apply.",
        "We do not accept applicants on temporary visas.",
        "Applicants on temporary work visas are ineligible.",
        "NZ citizens or permanent residents only.",
        "New Zealand citizens/residents only.",
        "Applicants must be a NZ citizen or permanent resident.",
        "Only New Zealand citizens are eligible.",
    ],
)
def test_explicit_hard_conflicts_win(description: str) -> None:
    result = assess_job(job(description), today=CHECKED)
    assert result.label == "likely_incompatible"
    assert result.evidence


@pytest.mark.parametrize(
    "restriction",
    [
        "Candidates on working holiday visas need not apply.",
        "Applicants on temporary visas need not apply.",
        "We cannot accept applicants with a working holiday visa.",
        "We are unable to hire working holiday visa holders.",
        "Not accepting working holiday visas.",
        "Working holiday visas are not accepted.",
        "Applicants must commit to a minimum of six months.",
        "Permanent, full-time position.",
        "We do not accept applicants holding a working holiday visa.",
        "Applicants must not hold a working holiday visa.",
        "Applicants who are not New Zealand citizens or residents are ineligible.",
        "We only consider applicants with New Zealand citizenship or permanent residency.",
    ],
)
def test_exclusion_words_override_an_otherwise_green_advertisement(restriction: str) -> None:
    result = assess_job(
        job("Temporary role for 2 months. WHV holders welcome. " + restriction), today=CHECKED
    )
    assert result.label == "likely_incompatible"


@pytest.mark.parametrize(
    "description",
    [
        "This role is not permanent.",
        "This is a non-permanent role.",
        "This is not a permanent position.",
        "Permanent employment is not offered.",
        "No permanent employment is offered.",
        "No sponsorship is available.",
        "No WHV sponsorship is available.",
        "No working holiday visa sponsorship is provided.",
        "Sponsorship is not provided.",
        "Applicants may be permanent residents or hold a valid work visa.",
        "Applicants must be NZ citizens or permanent residents or hold a valid work visa.",
        "Applicants must be a permanent resident or valid work visa holder.",
        "NZ citizens and residents are preferred.",
        "We do not exclude working holiday visa holders.",
        "WHV holders are not excluded.",
        "We welcome diversity and permanent residents.",
        "We provide permanent makeup services.",
        "No experience required. Full time work is available.",
    ],
)
def test_negation_alternatives_and_unrelated_words_are_not_red(description: str) -> None:
    result = assess_job(job(description), today=CHECKED)
    assert result.label == "needs_confirmation"


@pytest.mark.parametrize(
    "description",
    [
        "Permanent or fixed-term position for 2 months. WHV holders welcome.",
        "Temporary role for 2 months with an option to become permanent. WHV holders welcome.",
        "Temporary role for 2 months. Permanent opportunities may be available later. WHV welcome.",
    ],
)
def test_unclear_current_employment_type_blocks_green(description: str) -> None:
    assert assess_job(job(description), today=CHECKED).label == "needs_confirmation"


@pytest.mark.parametrize(
    "title", ["Permanent Guest Services Assistant", "Guest Services - Permanent"]
)
def test_permanent_title_is_hard_conflict(title: str) -> None:
    assert (
        assess_job(job("WHV holders welcome.", title=title), today=CHECKED).label
        == "likely_incompatible"
    )


@pytest.mark.parametrize(
    "title,description",
    [
        ("Permanent Makeup Artist", "Training offered."),
        ("Contract Manager", "Manage supplier contracts. WHV holders welcome."),
        ("Guest Services", "Casual dress code. WHV holders welcome."),
        ("Guest Services", "We have temporary accommodation available."),
    ],
)
def test_occupational_or_benefit_words_are_not_employment_flags(
    title: str, description: str
) -> None:
    result = assess_job(job(description, title=title), today=CHECKED)
    assert result.label == "needs_confirmation"
    assert result.score in {0, 30}


def test_negative_whv_statement_cannot_add_welcome_points() -> None:
    result = assess_job(job("We do not welcome WHV holders."), today=CHECKED)
    assert result.score == 0
    assert result.label == "likely_incompatible"


@pytest.mark.parametrize(
    "requirement", ["Must have unrestricted work rights.", "Permanent work rights are required."]
)
def test_unrestricted_rights_require_confirmation(requirement: str) -> None:
    result = assess_job(
        job("Temporary role for 2 months. WHV holders welcome. " + requirement), today=CHECKED
    )
    assert result.label == "needs_confirmation"
    assert any("工作權" in question for question in result.questions)


def test_generic_work_rights_requirement_is_not_a_conflict() -> None:
    result = assess_job(
        job("Temporary role for 2 months. WHV holders welcome. Must have the right to work in NZ."),
        today=CHECKED,
    )
    assert result.label == "likely_suitable"


def test_resident_preference_does_not_exclude_or_add_points() -> None:
    result = assess_job(
        job("Temporary role for 2 months. WHV holders welcome. NZ residents preferred."),
        today=CHECKED,
    )
    assert result.label == "likely_suitable"
    assert result.score == 90


def test_negated_temporary_title_does_not_supply_nonpermanent_evidence() -> None:
    result = assess_job(
        job("Work for 2 months. WHV holders welcome.", title="Not a temporary role"), today=CHECKED
    )
    assert result.label == "needs_confirmation"
    assert result.score == 65


@pytest.mark.parametrize("employer", [None, "", " ", "unknown", "N/A", "Confidential"])
def test_missing_or_placeholder_employer_blocks_green(employer: str | None) -> None:
    result = assess_job(
        job("Temporary role for 2 months. WHV holders welcome.", employer=employer), today=CHECKED
    )
    assert result.label == "needs_confirmation"
    assert any("雇主未明" in reason for reason in result.reasons)


@pytest.mark.parametrize("description", [None, "", " ", "N/A", "Description unavailable"])
def test_missing_or_placeholder_description_blocks_green(description: str | None) -> None:
    result = assess_job(
        job(description, title="Temporary role for 2 months. WHV holders welcome."), today=CHECKED
    )
    assert result.label == "needs_confirmation"
    assert any("缺少有效職缺內文" in reason for reason in result.reasons)


@pytest.mark.parametrize("country", [None, "AU", "unknown"])
def test_missing_or_non_nz_country_blocks_green(country: str | None) -> None:
    result = assess_job(
        job("Temporary role for 2 months. WHV holders welcome.", country=country), today=CHECKED
    )
    assert result.label == "needs_confirmation"


def test_posted_and_closing_dates_never_supply_tenure() -> None:
    result = assess_job(job("Temporary role. WHV holders welcome."), today=CHECKED)
    assert result.tenure.status == "unknown"
    assert result.label == "needs_confirmation"
    assert not any(item.field in {"posted_at", "closes_at"} for item in result.evidence)


def test_rule_provenance_and_immutable_output() -> None:
    result = assess_job(job("Temporary role for 2 months. WHV holders welcome."), today=CHECKED)
    assert result.rule_version == RULES_VERSION
    assert result.rules_checked_at == RULES_CHECKED_AT
    assert result.source_url == RULES_SOURCE_URL
    assert result.job_url == "https://nz.seek.com/job/10000001"
    assert result.assessed_at == RULES_CHECKED_AT
    assert result.disclaimer == DISCLAIMER
    assert result.questions
    assert all(any("\u4e00" <= char <= "\u9fff" for char in reason) for reason in result.reasons)
    with pytest.raises(FrozenInstanceError):
        result.score = 100


@pytest.mark.parametrize(
    "days,stale,label", [(90, False, "likely_suitable"), (91, True, "needs_confirmation")]
)
def test_stale_rules_block_green_only_after_90_days(days: int, stale: bool, label: str) -> None:
    result = assess_job(
        job("Temporary role for 2 months. WHV holders welcome."),
        today=CHECKED + timedelta(days=days),
    )
    assert result.rules_stale is stale
    assert result.label == label
    assert any("90 天" in reason for reason in result.reasons) is stale


def test_stale_rules_do_not_erase_hard_conflict() -> None:
    result = assess_job(job("Permanent position."), today=CHECKED + timedelta(days=91))
    assert result.rules_stale
    assert result.label == "likely_incompatible"


def test_score_is_clamped_and_multiple_matches_do_not_stack() -> None:
    result = assess_job(
        job(
            "Temporary role. Casual role. WHV welcome. WHV accepted. "
            "Fixed-term contract from 2026-10-01 to 2026-11-30."
        ),
        today=CHECKED,
    )
    assert result.score == 100
    result = assess_job(job("Permanent position. No WHV. Contract for 6 months."), today=CHECKED)
    assert result.score == 0


def test_evidence_is_an_exact_bounded_fragment_of_its_named_field() -> None:
    original = job(
        "Temporary role for 2 months " + "with paid breaks " * 30 + ". WHV holders welcome."
    )
    result = assess_job(original, today=CHECKED)
    assert result.evidence
    for item in result.evidence:
        assert item.quote in getattr(original, item.field)
        assert 0 < len(item.quote) <= 240


def test_long_clause_evidence_retains_the_actual_conflict() -> None:
    result = assess_job(job("We offer " + "excellent facilities " * 30 + "and a permanent role."))
    assert result.label == "likely_incompatible"
    assert any("permanent role" in item.quote for item in result.evidence)


def test_evidence_deduplicates_trailing_punctuation_without_rewriting_quote() -> None:
    original = job("Fixed-term contract for two months. WHV holders welcome.")
    result = assess_job(original, today=CHECKED)
    duplicates = [
        item
        for item in result.evidence
        if item.field == "description"
        and item.quote.rstrip(".") == "Fixed-term contract for two months"
    ]
    assert len(duplicates) == 1
    assert duplicates[0].quote in original.description
