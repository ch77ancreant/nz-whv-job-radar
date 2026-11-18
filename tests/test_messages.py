import unicodedata
from dataclasses import replace
from datetime import date

import pytest

from nz_job_radar.jobs import Job
from nz_job_radar.messages import render_notification
from nz_job_radar.whv import DISCLAIMER, RULES_SOURCE_URL, Evidence, WhvAssessment, assess_job


def example() -> tuple[Job, WhvAssessment]:
    job = Job(
        source_job_id="10000001",
        source_url="https://nz.seek.com/job/10000001",
        title="Front of House Assistant",
        employer="Example Cafe",
        location="Auckland",
        country="NZ",
        employment_type="Contract/Temp",
        salary="$25 per hour",
        posted_at=None,
        closes_at=None,
        description="Temporary role for two months. WHV holders welcome.",
    )
    return job, assess_job(job, today=date(2026, 9, 23))


def units(text: str) -> int:
    return len(text.encode("utf-16-le")) // 2


def test_message_contains_required_context_links_and_caveat() -> None:
    job, assessment = example()
    message = render_notification(job, assessment)
    for required in (
        "【新職缺】",
        job.title,
        job.employer,
        job.location,
        job.employment_type,
        job.salary,
        "可能適合",
        "理由：",
        "待確認：",
        job.source_url,
        RULES_SOURCE_URL,
        assessment.rules_checked_at,
        DISCLAIMER,
    ):
        assert required in message
    assert "不是機率" in message
    assert 1 <= units(message) <= 4096


def test_update_and_synthetic_markers_are_explicit() -> None:
    job, assessment = example()
    message = render_notification(job, assessment, kind="update", synthetic=True)
    assert "【重要更新】" in message
    assert "合成測試資料｜非真實職缺" in message
    assert "【新職缺】" not in message


def test_unknown_fields_are_not_fabricated() -> None:
    job, assessment = example()
    message = render_notification(
        replace(job, employer=None, location=None, employment_type=None, salary=None), assessment
    )
    assert "雇主：未知" in message
    assert "地點：未知" in message
    assert "聘僱類型：未知" in message
    assert "薪資：" not in message


@pytest.mark.parametrize("character", ["a", "繁", "😀", "𠀀"])
def test_huge_untrusted_fields_fit_utf16_limit_and_keep_complete_links(character: str) -> None:
    job, assessment = example()
    enormous = character * 20_000
    source_url = "https://nz.seek.com/job/" + "9" * 200
    job = replace(
        job,
        title=enormous,
        employer=enormous,
        location=enormous,
        employment_type=enormous,
        salary=enormous,
        description="PRIVATE_FULL_DESCRIPTION_" + enormous,
        source_url=source_url,
    )
    assessment = replace(
        assessment,
        reasons=(enormous,) * 50,
        questions=(enormous,) * 50,
        evidence=(Evidence("description", enormous),) * 50,
        rules_checked_at=enormous,
        rule_version=enormous,
        rules_stale=True,
    )
    message = render_notification(job, assessment, kind="update", synthetic=True)
    assert units(message) <= 4096
    assert source_url in message
    assert RULES_SOURCE_URL in message
    assert DISCLAIMER in message
    assert "PRIVATE_FULL_DESCRIPTION" not in message
    assert "完整結果請查看本機報告" in message
    assert "…" in message


def test_controls_and_surrogates_cannot_inject_terminal_or_extra_fields() -> None:
    job, assessment = example()
    tainted = "Hello\x1b[31m\x00\nFAKE FIELD\r\t\u202eREVERSED\ud800"
    job = replace(job, title=tainted, employer=tainted, location=tainted)
    assessment = replace(
        assessment,
        reasons=(tainted,),
        questions=(tainted,),
        evidence=(Evidence("description", tainted),),
    )
    message = render_notification(job, assessment)
    assert all(
        char == "\n" or unicodedata.category(char) not in {"Cc", "Cf", "Cs"} for char in message
    )
    assert "\nFAKE FIELD" not in message
    assert job.source_url in message
    assert units(message) <= 4096


def test_html_and_markdown_are_plain_text_not_generated_markup() -> None:
    job, assessment = example()
    job = replace(job, title="<b>Cafe</b> **Assistant** [link]")
    message = render_notification(job, assessment)
    assert "<b>Cafe</b> **Assistant** [link]" in message
    assert job.source_url in message


def test_stale_warning_is_explicit() -> None:
    job, assessment = example()
    message = render_notification(job, replace(assessment, rules_stale=True))
    assert "規則已超過 90 天未查核" in message


def test_red_notification_prioritizes_hard_conflict_over_four_positive_reasons() -> None:
    job, _ = example()
    job = replace(
        job,
        description=(
            "Fixed-term contract from 2026-10-01 to 2026-11-30. "
            "WHV holders welcome. This is a permanent position."
        ),
    )
    assessment = assess_job(job, today=date(2026, 9, 23))
    assert assessment.label == "likely_incompatible"
    assert all("+" in reason for reason in assessment.reasons[:4])
    message = render_notification(job, assessment)
    displayed_reasons = message.split("理由：\n", 1)[1].split("待確認：", 1)[0]
    assert "永久工作" in displayed_reasons
    assert "-70" in displayed_reasons.splitlines()[0]
    assert units(message) <= 4096


def test_empty_assessment_lists_have_confirmation_fallbacks() -> None:
    job, assessment = example()
    message = render_notification(job, replace(assessment, reasons=(), questions=(), evidence=()))
    assert "未提供明確理由" in message
    assert "請向雇主確認" in message
    assert "原文片段：" not in message


@pytest.mark.parametrize(
    "url", ["https://evil.invalid/job/1", "https://nz.seek.com/job/" + "1" * 5000]
)
def test_invalid_or_unbounded_job_url_is_not_cut_into_a_misleading_link(url: str) -> None:
    job, assessment = example()
    message = render_notification(replace(job, source_url=url), assessment)
    assert "連結格式無效" in message
    assert url not in message
    assert units(message) <= 4096


def test_invalid_notification_kind_fails_locally() -> None:
    job, assessment = example()
    with pytest.raises(ValueError):
        render_notification(job, assessment, kind="other")
