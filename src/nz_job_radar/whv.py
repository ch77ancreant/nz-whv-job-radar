"""Conservative, evidence-based Taiwan WHV screening of job advertisements.

This is bounded English phrase matching, not a legal decision or general NLP.
Only an explicit current employment conflict produces a red label. Unclear
wording cannot supply the evidence required for a green label.
"""

import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Literal

from .jobs import Job
from .tenure import TenureAssessment, assess_tenure

RULES_CHECKED_AT = "2026-09-23"
RULES_VERSION = "tw-whv-1.0"
RULES_SOURCE_URL = "https://www.immigration.govt.nz/visas/taiwan-working-holiday-visa/"
DISCLAIMER = "僅供初步篩選，請確認現行簽證條件與聘僱契約。"


@dataclass(frozen=True)
class Evidence:
    field: str
    quote: str


@dataclass(frozen=True)
class WhvAssessment:
    label: Literal["likely_suitable", "needs_confirmation", "likely_incompatible"]
    score: int
    confidence: Literal["high", "medium", "low"]
    reasons: tuple[str, ...]
    evidence: tuple[Evidence, ...]
    questions: tuple[str, ...]
    tenure: TenureAssessment
    rule_version: str
    rules_checked_at: str
    source_url: str
    job_url: str
    assessed_at: str
    rules_stale: bool
    disclaimer: str


_ROLE = (
    r"(?:role|job|position|employment|work|contract|assignment)"
    r"(?!\s+(?:rights?|visas?|permits?)\b)"
)
_TEMP = r"(?:temporary|casual|fixed[ -]term|non[ -]permanent)"
_STRUCTURED_TEMP = re.compile(r"(?:Casual\s*/\s*Vacation|Contract\s*/\s*Temp)", re.IGNORECASE)
_VISA = (
    r"(?:WHV(?:s)?|working[ -]holiday(?:[ -]visas?|makers?)?"
    r"|temporary(?:[ -]work)?[ -]visas?)"
    r"(?:\s+(?:visa\s+)?(?:holders?|applicants?|candidates?|workers?))?"
)
_CITIZEN = r"(?:(?:NZ|New Zealand)\s+)?(?:citizens?|(?:permanent\s+)?residents?)"
_CITIZENS = _CITIZEN + r"(?:\s*(?:or|and|/)\s*" + _CITIZEN + r")?"
_CITIZENSHIP = r"(?:(?:NZ|New Zealand)\s+)?(?:citizenship|(?:permanent\s+)?residency)"
_NEGATION = re.compile(
    r"\b(?:not|no|never|without|isn't|aren't|isn’t|aren’t)\s+"
    r"(?:(?:a|an|any|necessarily|strictly)\s+){0,2}$|\bnon[- ]$",
    re.IGNORECASE,
)
_PLACEHOLDER = re.compile(
    r"(?:unknown|not (?:specified|provided|available)|n/?a|none|null|tba|tbc|"
    r"to be (?:confirmed|advised)|(?:no )?description(?: (?:unavailable|provided|available))?|"
    r"confidential|undisclosed|[-–—?]+|\[redacted[^]]*\])",
    re.IGNORECASE,
)
_PERMANENT = re.compile(
    rf"\bpermanent(?:\s*,\s*|\s+)(?:full[ -]time\s+|part[ -]time\s+)?{_ROLE}\b"
    rf"|\b{_ROLE}\s+(?:(?:is|will be|are)\s+)?(?:a\s+)?permanent\b",
    re.IGNORECASE,
)
_NONPERMANENT = re.compile(
    rf"\b{_TEMP}\s+(?:full[ -]time\s+|part[ -]time\s+)?{_ROLE}\b"
    rf"|\b{_ROLE}\s*(?:(?:is|will be|are)\s+|:\s*)?(?:a\s+)?{_TEMP}\b"
    rf"|\bcontract\s+(?:role|job|position|work|assignment)\b"
    rf"|\b(?:not\s+(?:a\s+)?permanent)\s+{_ROLE}\b"
    rf"|\b{_ROLE}\s+(?:is\s+)?not\s+permanent\b"
    r"|\bcontract\s+(?:for\s+\d|from\s+\d|duration\s*:|period\s*:)"
    r"|\b\d+[ -](?:week|month|day)s?[ -]contract\b",
    re.IGNORECASE,
)
_ALTERNATIVE = re.compile(
    rf"\bpermanent\s*(?:or|/)\s*(?:{_TEMP}|contract)\b"
    rf"|\b(?:{_TEMP}|contract)\s*(?:or|/)\s*permanent\b",
    re.IGNORECASE,
)
_CONDITIONAL = re.compile(
    r"\b(?:may|might|could|potential|possibility|opportunity|option|prospect)\b"
    r"[^.!?;\n]{0,65}\bpermanent\b|\bpermanent\b[^.!?;\n]{0,35}"
    r"\b(?:opportunities|opportunity|option|available later)\b",
    re.IGNORECASE,
)
_VISA_EXCLUDED = re.compile(
    rf"\b(?:no|not (?:suitable|available|open) for|(?:do not|don't|cannot|can't|unable to) "
    rf"(?:accept|hire|employ|consider|welcome)|not (?:accepting|hiring|considering)|"
    rf"must not (?:hold|have))\s+"
    rf"(?:applicants? (?:on|with|holding)\s+)?(?:a\s+|an\s+)?{_VISA}\b"
    rf"|\b{_VISA}\s+(?:(?:are|is|will be)\s+)?"
    r"(?:not\s+(?:accepted|eligible|suitable|considered|welcome|permitted)|"
    r"(?:cannot|can't|must not|may not|need not)\s+apply|ineligible|excluded)\b",
    re.IGNORECASE,
)
_CITIZEN_ONLY = re.compile(
    rf"\b{_CITIZENS}\s+(?:applicants?\s+|candidates?\s+)?only\b"
    rf"|\bonly\s+(?:accept(?:ing)?\s+|for\s+)?{_CITIZENS}\b"
    rf"|\bmust\s+be\s+(?:a\s+|an\s+)?{_CITIZENS}\b"
    r"|\b(?:NZ|New Zealand)\s+(?:citizenship|permanent residency)\s+(?:is\s+)?required\b"
    rf"|\bonly\s+(?:consider|accept|hire|employ)(?:ing)?\s+(?:applicants?|candidates?)\s+"
    rf"(?:with|holding)\s+{_CITIZENSHIP}\b"
    rf"|\b(?:applicants?|candidates?|people|workers?|anyone)\s+(?:who\s+)?(?:are|is)\s+"
    rf"not\s+(?:a\s+|an\s+)?{_CITIZENS}\s+(?:(?:are|is)\s+)?"
    r"(?:ineligible|not eligible|not considered|excluded|cannot apply)\b",
    re.IGNORECASE,
)
_VISA_ALTERNATIVE = re.compile(
    r"\bor\s+(?:(?:applicants?|candidates?|holders?)\s+(?:with|of)\s+|"
    r"(?:hold|have|holding)\s+)?(?:a\s+|an\s+)?(?:valid\s+|current\s+)?"
    r"(?:work(?:ing)?\s+visa|work(?:ing)?\s+rights|working[ -]holiday|WHV)\b",
    re.IGNORECASE,
)
_WHV_WELCOME = re.compile(
    r"\b(?:WHV(?:s)?|working[ -]holiday(?:[ -]visas?|makers?)?)"
    r"(?:\s+(?:visa\s+)?(?:holders?|applicants?|candidates?|workers?))?\s+"
    r"(?:(?:are|is)\s+)?(?:welcome|accepted|eligible|encouraged|can apply|may apply)\b"
    r"|\b(?:welcome|accept|accepting|encourage)\s+(?:applicants? (?:on|with)\s+)?"
    r"(?:WHV(?:s)?|working[ -]holiday(?:[ -]visas?|makers?)?)\b",
    re.IGNORECASE,
)
_RESTRICTED_RIGHTS = re.compile(
    r"\b(?:must (?:have|hold)|require[sd]?|only (?:applicants?|candidates?) with)\s+"
    r"(?:(?:full|current|valid|NZ|New Zealand)\s+)*"
    r"(?:unrestricted|permanent)\s+(?:work(?:ing)? rights|right to work|work visas?)\b"
    r"|\b(?:unrestricted|permanent)\s+(?:work(?:ing)? rights|right to work|work visas?)\s+"
    r"(?:are\s+|is\s+)?required\b",
    re.IGNORECASE,
)
_TENURE_REASONS = {
    "employment_dates_invalid_or_missing_year": "聘僱日期無效或缺少年份。",
    "employment_date_range_not_unambiguous": "廣告中的聘僱日期範圍無法唯一確認。",
    "employment_dates_reversed": "聘僱結束日早於開始日，需確認日期。",
    "employment_dates_out_of_range": "聘僱日期超出可安全計算的範圍。",
    "three_calendar_month_date_boundary": "起訖日正好位於三個日曆月邊界，需確認包含日。",
    "employment_dates_exceed_three_months": "明示起訖日超過三個日曆月。",
    "employment_dates_within_three_months": "明示起訖日短於三個日曆月。",
    "employment_duration_negated": "聘期文字含否定，不能當成已確認的聘期。",
    "employment_duration_invalid_or_unsupported": "聘期數值無效或不在支援的明確格式內。",
    "explicit_employment_duration_within_three_months": "明示聘期未超過三個日曆月。",
    "employment_duration_exceeds_three_months": "明示聘期超過三個日曆月。",
    "employment_duration_boundary_requires_confirmation": "聘期天數或週數位於日曆月邊界。",
    "employment_duration_has_no_confirmed_upper_bound": "聘期只有下限，缺少已確認的上限。",
    "employment_end_date_missing": "廣告明示開始日，但缺少可確認的結束日。",
    "no_explicit_employment_duration": "沒有找到明示的聘僱期間。",
    "explicit_minimum_employment_commitment_exceeds_three_months": "明確最低任職承諾超過三個月。",
    "conflicting_employment_terms": "多個聘期或起訖日期互相衝突，需確認實際契約。",
    "employment_term_approximate_flexible_or_extendable": "聘期含約略、選項或延長，需確認上限。",
}


def _known(value: str | None) -> bool:
    return bool(value and value.strip() and not _PLACEHOLDER.fullmatch(value.strip(" .")))


def _clauses(value: str) -> list[str]:
    return [part.strip() for part in re.split(r"[\n.!?;]+", value) if part.strip()]


def _affirmed(pattern: re.Pattern[str], clause: str) -> bool:
    return any(
        not _NEGATION.search(clause[: match.start()])
        and not re.match(
            r"\s+(?:is|are)\s+not\s+(?:offered|required|available)\b",
            clause[match.end() :],
            re.IGNORECASE,
        )
        and not (
            pattern is _VISA_EXCLUDED
            and re.match(
                r"\s+(?:(?:need|require)\s+)?sponsorship\b",
                clause[match.end() :],
                re.IGNORECASE,
            )
        )
        for match in pattern.finditer(clause)
    )


def _add_evidence(evidence: list[Evidence], field: str, quote: str) -> None:
    item = Evidence(field, quote[:240])
    comparison = item.quote.rstrip(" \t\r\n.!?;,:。！？；，：")
    if not any(
        existing.field == field and existing.quote.rstrip(" \t\r\n.!?;,:。！？；，：") == comparison
        for existing in evidence
    ):
        evidence.append(item)


def _add_clause_evidence(evidence: list[Evidence], field: str, clause: str) -> None:
    # Long sentences can put the decisive requirement well after character 240.
    # Keep a bounded, unchanged excerpt around each recognized wording instead.
    patterns = (
        _PERMANENT,
        _NONPERMANENT,
        _VISA_EXCLUDED,
        _CITIZEN_ONLY,
        _WHV_WELCOME,
        _ALTERNATIVE,
        _CONDITIONAL,
        _RESTRICTED_RIGHTS,
    )
    spans = [match.span() for pattern in patterns for match in pattern.finditer(clause)]
    if not spans:
        spans = [(0, min(len(clause), 100))]
    for start, end in spans:
        left = max(0, start - 60)
        right = min(len(clause), max(end + 60, left + 120), left + 240)
        _add_evidence(evidence, field, clause[left:right])


def _employment_flags(
    fields: tuple[tuple[str, str], ...], evidence: list[Evidence]
) -> tuple[bool, bool, bool, bool, bool, bool]:
    permanent = nonpermanent = excludes_visa = welcomes_whv = ambiguous = False
    restricted_rights = False
    for field, value in fields:
        for clause in _clauses(value):
            alternative = bool(_ALTERNATIVE.search(clause))
            conditional = bool(_CONDITIONAL.search(clause))
            is_permanent = _affirmed(_PERMANENT, clause)
            is_temporary = _affirmed(_NONPERMANENT, clause)
            if field == "employment_type":
                is_permanent |= _affirmed(re.compile(r"\bpermanent\b", re.I), clause)
                is_temporary |= bool(re.fullmatch(rf"(?:{_TEMP}|contract)", clause, re.IGNORECASE))
                # These are exact SEEK/Actor category values, not free-text claims.
                is_temporary |= bool(_STRUCTURED_TEMP.fullmatch(value.strip()))
            elif field == "title":
                # Titles use modifiers without a word such as "role". Occupational
                # phrases such as Permanent Makeup Artist and Contract Manager do not.
                is_permanent |= bool(
                    _affirmed(
                        re.compile(r"\bpermanent\s*[-–—:(]|[-–—:(]\s*permanent\)?$", re.I),
                        clause,
                    )
                    or re.match(
                        r"permanent\s+(?!make[ -]?up\b|residen\w*\b|work rights\b)\w",
                        clause,
                        re.I,
                    )
                )
                is_temporary |= bool(_affirmed(re.compile(rf"\b{_TEMP}\b", re.IGNORECASE), clause))
            if alternative or conditional:
                ambiguous = True
                # A choice or future opportunity is not an established current term.
                is_permanent = False
                is_temporary = False
            is_excluded = _affirmed(_VISA_EXCLUDED, clause)
            citizen_only = _affirmed(_CITIZEN_ONLY, clause)
            if citizen_only and _VISA_ALTERNATIVE.search(clause):
                citizen_only = False
            is_excluded |= citizen_only
            is_welcome = _affirmed(_WHV_WELCOME, clause)
            is_restricted = _affirmed(_RESTRICTED_RIGHTS, clause)
            permanent |= is_permanent
            nonpermanent |= is_temporary
            excludes_visa |= is_excluded
            welcomes_whv |= is_welcome
            restricted_rights |= is_restricted
            if any(
                (
                    is_permanent,
                    is_temporary,
                    is_excluded,
                    is_welcome,
                    alternative,
                    conditional,
                    is_restricted,
                )
            ):
                _add_clause_evidence(evidence, field, clause)
    return permanent, nonpermanent, excludes_visa, welcomes_whv, ambiguous, restricted_rights


def assess_job(job: Job, *, today: date | None = None) -> WhvAssessment:
    """Screen normalized fields without network calls or personal visa assumptions."""
    assessment_date = today if today is not None else datetime.now(UTC).date()
    fields = (
        ("title", job.title),
        ("employment_type", job.employment_type or ""),
        ("description", job.description or ""),
    )
    evidence: list[Evidence] = []
    permanent, nonpermanent, excludes_visa, welcome, ambiguous, restricted_rights = (
        _employment_flags(fields, evidence)
    )
    # Posting and application closing dates must never enter the tenure parser.
    tenure = assess_tenure(job.title + "\n" + (job.description or ""))
    for snippet in tenure.evidence:
        for field, value in fields:
            if snippet and snippet in value:
                _add_evidence(evidence, field, snippet)
            elif "\n" in snippet:
                for part in snippet.splitlines():
                    if part and part in value:
                        _add_evidence(evidence, field, part)

    score = 0
    reasons: list[str] = []
    questions: list[str] = []
    if welcome:
        score += 30
        reasons.append("廣告明示接受打工度假簽證持有人（+30）。")
    if nonpermanent:
        score += 25
        reasons.append("廣告明示臨時、非永久或限定契約工作（+25）。")
    if tenure.status == "compatible":
        score += 35
        reasons.append("廣告明示的聘期在本工具三個日曆月判定範圍內（+35）。")
        if nonpermanent and tenure.start_date and tenure.end_date:
            score += 10
            reasons.append("非永久聘僱具有具體起訖日（+10）。")
    elif tenure.status == "exceeds_limit":
        score -= 60
        reasons.append("廣告明示聘期或最低承諾超過同一雇主三個月限制（-60）。")
    else:
        reasons.append(
            "聘期位於計算邊界，需確認。" if tenure.status == "boundary" else "聘期不明或證據不足。"
        )
        questions.append("實際開始日、最後工作日及同一雇主最低承諾期間為何？")
    reasons.extend(
        _TENURE_REASONS.get(reason, "聘期規則無法明確解讀，需確認實際契約。")
        for reason in tenure.reasons
    )
    if permanent:
        score -= 70
        reasons.append("廣告明示永久工作，與目前查核的台灣 WHV 條件衝突（-70）。")
    if excludes_visa:
        score -= 70
        reasons.append("廣告明示排除打工度假／臨時簽證，或限定公民／居民（-70）。")
    if not nonpermanent:
        reasons.append("缺少可確認此職缺為非永久聘僱的明確文字。")
        questions.append("這份實際提供的聘僱契約是否為臨時或非永久工作？")
    if ambiguous or (permanent and nonpermanent) or (excludes_visa and welcome):
        ambiguous = True
        reasons.append("聘僱或工作權文字包含選項、未來可能性或互相衝突的證據。")
        questions.append("廣告中的不同聘僱／工作權說明，哪一項適用於這份職缺？")
    if restricted_rights:
        reasons.append("廣告要求永久或不受限制的工作權，尚未確認接受你的實際簽證條件。")
        questions.append("雇主所稱永久／不受限制工作權，是否排除有同雇主期限的台灣 WHV？")
    employer_known = _known(job.employer)
    description_known = _known(job.description)
    if not employer_known:
        reasons.append("實際雇主未明，無法確認同一雇主限制。")
        questions.append("簽訂契約及實際聘僱你的雇主是哪一家公司？")
    if not description_known:
        reasons.append("缺少有效職缺內文，無法完成保守判讀。")
        questions.append("能否提供完整職缺內文與聘僱條件？")
    if job.country != "NZ":
        reasons.append("工作國別未確認為紐西蘭。")
        questions.append("此職缺的實際工作地點是否在紐西蘭？")
    rules_stale = (assessment_date - date.fromisoformat(RULES_CHECKED_AT)).days > 90
    if rules_stale:
        reasons.append("警示：規則已超過 90 天未查核；重新查核官方條件前不標為可能適合。")
        questions.append("請重新查核 Immigration New Zealand 現行台灣打工度假簽證條件。")
    score = max(0, min(100, score))
    hard_conflict = permanent or excludes_visa or tenure.status == "exceeds_limit"
    label: Literal["likely_suitable", "needs_confirmation", "likely_incompatible"]
    confidence: Literal["high", "medium", "low"]
    if hard_conflict:
        label = "likely_incompatible"
        confidence = "medium" if rules_stale else "high"
    elif (
        score >= 70
        and employer_known
        and description_known
        and job.country == "NZ"
        and tenure.status == "compatible"
        and nonpermanent
        and not ambiguous
        and not restricted_rights
        and not rules_stale
    ):
        label = "likely_suitable"
        confidence = "medium"
    else:
        label = "needs_confirmation"
        confidence = "low"
        if score < 70:
            reasons.append("目前證據分數未達 70 分；分數不是獲准工作或錄取的機率。")
    questions.append("請向雇主確認實際契約、工作權要求及你的簽證剩餘效期與過往同雇主任職期間。")
    return WhvAssessment(
        label=label,
        score=score,
        confidence=confidence,
        reasons=tuple(dict.fromkeys(reasons)),
        evidence=tuple(evidence),
        questions=tuple(dict.fromkeys(questions)),
        tenure=tenure,
        rule_version=RULES_VERSION,
        rules_checked_at=RULES_CHECKED_AT,
        source_url=RULES_SOURCE_URL,
        job_url=job.source_url,
        assessed_at=assessment_date.isoformat(),
        rules_stale=rules_stale,
        disclaimer=DISCLAIMER,
    )
