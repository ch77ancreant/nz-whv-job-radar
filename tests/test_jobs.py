from dataclasses import asdict, replace
from pathlib import Path

import pytest

from nz_job_radar.jobs import JobError, match_job, normalize_job
from nz_job_radar.profiles import load_profiles


@pytest.fixture
def cafe():
    return load_profiles(Path(__file__).resolve().parents[1] / "profiles")["auckland-cafe-service"]


@pytest.fixture
def ski():
    return load_profiles(Path(__file__).resolve().parents[1] / "profiles")["nz-ski-fields"]


def raw_job(**updates: object) -> dict[str, object]:
    raw = {
        "seekJobId": "10000001",
        "jobId": "synthetic-hash-1",
        "title": "Front of House",
        "canonicalUrl": "https://nz.seek.com/job/10000001?tracking=test#apply",
        "company": "Example Cafe",
        "location": "Auckland CBD, Auckland",
        "locationCountry": "NZ",
        "employmentType": "Full time",
        "salaryText": "$25 per hour",
        "postedDate": "2026-09-01T00:00:00Z",
        "validThrough": "2026-09-30T00:00:00Z",
        "description": "Synthetic cafe service role. Coffee training provided.",
    }
    raw.update(updates)
    return raw


def test_normalize_allowlist_and_id_priority() -> None:
    job = normalize_job(raw_job(contactName="Private Person", email="private@example.invalid"))
    assert job.source_job_id == "10000001"
    assert job.source_url == "https://nz.seek.com/job/10000001"
    assert "email" not in asdict(job)
    assert "Private Person" not in repr(job)
    assert job.employment_type == "Full time"
    assert job.closes_at == "2026-09-30T00:00:00Z"


def test_id_fallbacks() -> None:
    assert normalize_job(raw_job(seekJobId=None)).source_job_id == "10000001"
    assert normalize_job(raw_job(seekJobId=None, jobId=None)).source_job_id == "10000001"


def test_actor_identifiers_cannot_override_canonical_seek_identity() -> None:
    first = normalize_job(raw_job(seekJobId=None, jobId="actor-first"))
    duplicate = normalize_job(raw_job(seekJobId=None, jobId="actor-second"))
    other = normalize_job(
        raw_job(
            seekJobId=None, jobId="actor-first", canonicalUrl="https://nz.seek.com/job/10000002"
        )
    )
    assert first.source_job_id == duplicate.source_job_id == "10000001"
    assert other.source_job_id == "10000002"


@pytest.mark.parametrize(
    "url",
    [
        "https://evil.invalid/job/10000001",
        "https://nz.seek.com.evil.invalid/job/10000001",
        "https://token@nz.seek.com/job/10000001",
        "file:///job/10000001",
        "https://nz.seek.com:444/job/10000001",
        "https://nz.seek.com/jobs",
        "https://www.seek.com.au/job/10000001",
        "https://nz.seek.com/job/not-an-id",
    ],
)
def test_url_validation(url: str) -> None:
    with pytest.raises(JobError):
        normalize_job(raw_job(canonicalUrl=url))


def test_legacy_nz_domain_and_tracking_removed() -> None:
    assert (
        normalize_job(raw_job(canonicalUrl="http://www.seek.co.nz/job/10000001/?x=y")).source_url
        == "https://nz.seek.com/job/10000001"
    )


@pytest.mark.parametrize(
    "updates",
    [{"title": " "}, {"title": {}}, {"company": []}, {"seekJobId": True}, {"seekJobId": "999"}],
)
def test_rejects_invalid_required_data(updates: dict) -> None:
    with pytest.raises(JobError):
        normalize_job(raw_job(**updates))


def test_contact_redaction_and_html_plain_text() -> None:
    description = """<p>Front of house work; starts 2026-10-01.</p>
    <p>Contact: Private Person</p><p>Email private@example.invalid; call +64 21 123 4567.</p>
    <p>https://instagram.com/private.person</p><script>alert('not job text')</script>"""
    job = normalize_job(raw_job(description=description))
    assert "private" not in job.description.lower()
    assert "123 4567" not in job.description
    assert "alert" not in job.description
    assert "2026-10-01" in job.description
    assert "[REDACTED_EMAIL]" in job.description
    assert "[REDACTED_PHONE]" in job.description


@pytest.mark.parametrize(
    "date_range",
    [
        "2026-10-01 - 2026-12-31",
        "2026-10-01 to 2026-12-31",
        "2026-10-01–2026-12-31",
        "2026-10-01 — 2026-12-31",
        "2026-10-01/2026-12-31",
        "2026/10/01 - 2026/12/31",
        "01/10/2026 - 31/12/2026",
        "1/10/2026 to 31/12/2026",
        "2026-10-01T00:00:00Z - 2026-12-31T23:59:59Z",
    ],
)
def test_date_range_evidence_survives_phone_redaction(date_range: str) -> None:
    description = f"Fixed term {date_range}; kitchen hand required."
    assert normalize_job(raw_job(description=description)).description == description


@pytest.mark.parametrize(
    "description",
    [
        "Fixed term 2026-10-01 - 2026-12-31 021 123 4567.",
        "0211234567 / 2026-10-01 - 2026-12-31 / +64 21 123 4567.",
        "Call 0211234567 during 2026-10-01–2026-12-31.",
        "Phone: 123 4567. Fixed term 2026-10-01/2026-12-31.",
    ],
)
def test_date_exception_does_not_leak_adjacent_phone_numbers(description: str) -> None:
    cleaned = normalize_job(raw_job(description=description)).description
    assert "2026-10-01" in cleaned
    assert "2026-12-31" in cleaned
    assert "123 4567" not in cleaned
    assert "0211234567" not in cleaned
    assert "[REDACTED_PHONE]" in cleaned


def test_invalid_date_shaped_phone_number_is_not_exempt() -> None:
    job = normalize_job(raw_job(description="Telephone 0210-99-9999 for this role."))
    assert "0210-99-9999" not in job.description
    assert "[REDACTED_PHONE]" in job.description


@pytest.mark.parametrize(
    "salary",
    ["$50,000 - $60,000", "$50000 - $60000", "$25.50 - $28.50", "NZD 50,000–60,000"],
)
def test_salary_ranges_survive_phone_redaction(salary: str) -> None:
    job = normalize_job(raw_job(salaryText=salary, description=f"Salary {salary} per year."))
    assert job.salary == salary
    assert job.description == f"Salary {salary} per year."


def test_basic_match_does_not_filter_whv(cafe) -> None:
    job = normalize_job(raw_job(description="Permanent role. Coffee training provided."))
    assert match_job(job, cafe).status == "matched"


@pytest.mark.parametrize(
    "title",
    [
        "Barista / Front of House",
        "Café All-Rounder",
        "CAFÉ ALL ROUNDER",
        "Kitchen Hand / Coffee Maker",
    ],
)
def test_excluded_titles_normalize_accents_and_punctuation(cafe, title: str) -> None:
    decision = match_job(
        normalize_job(raw_job(title=title, description="Cafe assistant required")), cafe
    )
    assert decision.status == "excluded"
    assert "excluded_title" in decision.reasons


def test_title_exclusion_does_not_scan_description(cafe) -> None:
    job = normalize_job(
        raw_job(description="Front of house; barista and coffee maker training provided.")
    )
    assert match_job(job, cafe).status == "matched"


def test_phrases_require_word_boundaries(cafe) -> None:
    job = normalize_job(
        raw_job(title="Kitchen Handyman", description="Synthetic unrelated maintenance work")
    )
    assert "keyword_mismatch" in match_job(job, cafe).reasons


def test_regular_plurals_but_not_substrings(cafe) -> None:
    job = normalize_job(raw_job(title="Kitchen Hands", description="Synthetic role"))
    assert match_job(job, cafe).status == "matched"
    job = normalize_job(raw_job(title="Baristas / Front of House", description="Synthetic role"))
    assert "excluded_title" in match_job(job, cafe).reasons


def test_keyword_cannot_bridge_title_and_description(cafe) -> None:
    job = normalize_job(raw_job(title="Front of", description="house"))
    assert match_job(job, cafe).status == "excluded"


def test_accented_location_and_employer_aliases(ski) -> None:
    job = normalize_job(
        raw_job(title="Rentals", company="Cardrona Alpine Resort Ltd", location="Wānaka, Otago")
    )
    assert match_job(job, ski).status == "matched"


def test_car_rental_company_is_not_ski_employer(ski) -> None:
    job = normalize_job(
        raw_job(title="Rentals", company="Example Car Rentals", location="Queenstown")
    )
    decision = match_job(job, ski)
    assert decision.status == "excluded"
    assert "employer_mismatch" in decision.reasons


def test_missing_employer_needs_confirmation(ski) -> None:
    job = normalize_job(raw_job(title="Lift operator", company=None, location="Queenstown"))
    assert match_job(job, ski).status == "needs_confirmation"


@pytest.mark.parametrize(
    "field,reason", [("location", "location_unknown"), ("locationCountry", "country_unknown")]
)
def test_unknown_constraints_never_match(cafe, field: str, reason: str) -> None:
    decision = match_job(normalize_job(raw_job(**{field: None})), cafe)
    assert decision.status == "needs_confirmation"
    assert reason in decision.reasons


def test_non_nz_and_wrong_location_excluded(cafe) -> None:
    assert (
        "country_mismatch" in match_job(normalize_job(raw_job(locationCountry="AU")), cafe).reasons
    )
    assert (
        "location_mismatch"
        in match_job(normalize_job(raw_job(location="Wellington")), cafe).reasons
    )
    assert (
        match_job(normalize_job(raw_job(locationCountry="New Zealand")), cafe).status == "matched"
    )


def test_known_mismatch_wins_over_missing_data(ski) -> None:
    job = normalize_job(
        raw_job(title="Lift operator", company=None, location="Sydney", locationCountry="AU")
    )
    assert match_job(job, ski).status == "excluded"


def test_disabled_profile_is_excluded(cafe) -> None:
    assert (
        "profile_disabled"
        in match_job(normalize_job(raw_job()), replace(cafe, enabled=False)).reasons
    )
