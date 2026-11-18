"""Bounded plain-text notifications; job descriptions are never copied wholesale."""

import re
import unicodedata
from typing import Literal

from .jobs import Job
from .whv import DISCLAIMER, RULES_SOURCE_URL, WhvAssessment

_LABELS = {
    "likely_suitable": "🟢 可能適合",
    "needs_confirmation": "🟡 需要確認",
    "likely_incompatible": "🔴 可能不相容",
}
_CONFIDENCE = {"high": "高", "medium": "中", "low": "低"}
_JOB_URL = re.compile(r"https://nz\.seek\.com/job/[0-9]{1,200}\Z")


def _clean(value: str | None) -> str:
    if value is None:
        return ""
    return " ".join(
        "".join(
            " " if char in "\n\r\t" else char
            for char in value
            if char in "\n\r\t" or unicodedata.category(char) not in {"Cc", "Cf", "Cs"}
        ).split()
    )


def _units(value: str) -> int:
    return sum(2 if ord(char) > 0xFFFF else 1 for char in value)


def _clip(value: str | None, maximum: int) -> str:
    text = _clean(value)
    if _units(text) <= maximum:
        return text
    kept: list[str] = []
    size = 0
    for char in text:
        count = 2 if ord(char) > 0xFFFF else 1
        if size + count > maximum - 1:
            break
        kept.append(char)
        size += count
    return "".join(kept) + "…"


def render_notification(
    job: Job,
    assessment: WhvAssessment,
    *,
    kind: Literal["new", "update"] = "new",
    synthetic: bool = False,
) -> str:
    """Return one plain-text message with fixed budgets for every untrusted field."""
    if kind not in {"new", "update"}:
        raise ValueError("Notification kind must be new or update.")
    lines = ["【新職缺】" if kind == "new" else "【重要更新】"]
    if synthetic:
        lines.append("【合成測試資料｜非真實職缺】")
    lines.extend(
        [
            "職稱：" + (_clip(job.title, 160) or "未知"),
            "雇主：" + (_clip(job.employer, 100) or "未知"),
            "地點：" + (_clip(job.location, 100) or "未知"),
            "聘僱類型：" + (_clip(job.employment_type, 80) or "未知"),
        ]
    )
    if _clean(job.salary):
        lines.append("薪資：" + _clip(job.salary, 100))
    lines.extend(
        [
            "",
            "WHV 初篩：" + _LABELS.get(assessment.label, "🟡 需要確認"),
            "規則分數：" + _clip(str(assessment.score), 4) + "/100（不是機率）",
            "判讀信心：" + _CONFIDENCE.get(assessment.confidence, "未知"),
            "理由：",
        ]
    )
    reasons = assessment.reasons
    if assessment.label == "likely_incompatible":
        # A red label must explain its decisive conflict before any positive points.
        # The classifier attaches these deductions to every hard-conflict reason.
        hard_reasons = tuple(reason for reason in reasons if "-70" in reason or "-60" in reason)
        reasons = hard_reasons + tuple(reason for reason in reasons if reason not in hard_reasons)
    for reason in reasons[:4]:
        lines.append("• " + (_clip(reason, 180) or "需人工確認。"))
    if not assessment.reasons:
        lines.append("• 未提供明確理由，請人工確認。")
    elif len(assessment.reasons) > 4:
        lines.append("• 另有其他判斷理由，完整結果請查看本機報告。")
    lines.append("待確認：")
    for question in assessment.questions[:4]:
        lines.append("• " + (_clip(question, 160) or "請確認實際契約及簽證條件。"))
    if not assessment.questions:
        lines.append("• 請向雇主確認實際契約、工作權要求及你的簽證條件。")
    elif len(assessment.questions) > 4:
        lines.append("• 另有其他確認事項，完整結果請查看本機報告。")
    if assessment.evidence:
        lines.append("原文片段：")
        field_names = {"title": "職稱", "employment_type": "聘僱類型", "description": "內文"}
        for item in assessment.evidence[:2]:
            lines.append("• " + field_names.get(item.field, "原文") + "：" + _clip(item.quote, 140))
    if assessment.rules_stale:
        lines.append("⚠ 規則已超過 90 天未查核，請重新確認官方條件。")
    job_url = _clean(job.source_url)
    if _JOB_URL.fullmatch(job_url) is None:
        job_url = "連結格式無效，請回本機結果確認。"
    lines.extend(
        [
            "",
            "職缺：" + job_url,
            "規則查核：" + _clip(assessment.rules_checked_at, 40),
            "規則版本：" + _clip(assessment.rule_version, 40),
            "官方條件：" + RULES_SOURCE_URL,
            DISCLAIMER,
        ]
    )
    # Fixed field/array limits reserve room for both complete URLs and disclaimer.
    # This invariant is tested using worst-case supplementary-plane Unicode input.
    return "\n".join(lines)
