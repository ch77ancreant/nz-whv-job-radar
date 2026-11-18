"""Conservative extraction of explicitly advertised employment terms.

This is a bounded English grammar, not a general natural-language parser. Only
employment-linked durations and complete, labelled date ranges are actionable.
Dates never come from listing metadata. Three calendar months are not 90 days:
without a start date, 89--92 days and 13 weeks remain boundary cases.
"""

from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Literal

TenureStatus = Literal["compatible", "exceeds_limit", "unknown", "boundary"]


@dataclass(frozen=True)
class TenureAssessment:
    status: TenureStatus
    start_date: str | None = None
    end_date: str | None = None
    evidence: tuple[str, ...] = ()
    reasons: tuple[str, ...] = ()


def add_calendar_months(start: date, months: int) -> date:
    """Add whole months, clamping the day to the destination month's last day."""
    absolute_month = start.year * 12 + start.month - 1 + months
    year, month_zero = divmod(absolute_month, 12)
    month = month_zero + 1
    return date(year, month, min(start.day, calendar.monthrange(year, month)[1]))


_SMALL_NUMBERS = {
    "zero": 0,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
    "twenty": 20,
    "thirty": 30,
    "forty": 40,
    "fifty": 50,
    "sixty": 60,
    "seventy": 70,
    "eighty": 80,
    "ninety": 90,
}
_ONES = "one|two|three|four|five|six|seven|eight|nine"
_TENS = "twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety"
_NUMBER = (
    rf"(?:\d+(?:\.\d+)?|(?:{_TENS})(?:[ -](?:{_ONES}))?|"
    + "|".join(sorted(_SMALL_NUMBERS, key=len, reverse=True))
    + ")"
)
_UNIT = r"(?:years?|months?|weeks?|days?)"
_DURATION = re.compile(
    rf"\b(?P<low>{_NUMBER})[ -]*(?:(?P<first_unit>{_UNIT})\s*)?"
    rf"(?:(?P<range>to|and|[-–—])\s*(?P<high>{_NUMBER})[ -]*)?"
    rf"(?P<unit>{_UNIT})\b",
    re.IGNORECASE,
)
_EMPLOYMENT = re.compile(
    r"\b(?:contracts?|fixed[ -]term|temporary|casual|seasonal|season|employment|"
    r"jobs?|roles?|positions?|assignments?|placements?|tenure|duration|"
    r"work(?:ing)?|commit(?:ment)?|available|availability)\b",
    re.IGNORECASE,
)
_EXCLUDED_DURATION = re.compile(
    r"\b(?:experience|experienced|visa|visas|passport|validity|valid|notice|"
    r"probation|training|induction|annual leave|parental leave|holiday entitlement|"
    r"established|founded|operating|in business|company history|salary|pay|wage)\b",
    re.IGNORECASE,
)
_MINIMUM = re.compile(
    r"\b(?:at least|minimum|no less than|more than|over|longer than)"
    r"(?:\s+(?:a|an|required|term|length|duration|commitment|availability|stay|period|of))*"
    r"\s*[:=-]?\s*$",
    re.IGNORECASE,
)
_MAXIMUM = re.compile(
    r"\b(?:up to|at most|maximum(?:\s+of)?|no more than|less than|under)\s*$",
    re.IGNORECASE,
)
_APPROXIMATE = re.compile(
    r"\b(?:approximately|approx\.?|about|around|roughly|circa|potentially|"
    r"flexible|negotiable|tbc|to be confirmed|depending on|subject to|"
    r"ongoing|open[ -]ended|initial(?:ly)?|half|option(?:al|ally)?|"
    r"expected|estimated|anticipated|possibly|maybe|might|could|further|additional)\b",
    re.IGNORECASE,
)
_EXTENSION = re.compile(
    r"\b(?:extend(?:ed|able|ing)?|extension|renew(?:al|able|ed)?)\b",
    re.IGNORECASE,
)
_SEGMENT = re.compile(r"[\n;]+|(?<=[.!?])\s+(?=[A-Z])")
_MONTH_NAMES = (
    "January|February|March|April|May|June|July|August|September|October|November|"
    "December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sept|Sep|Oct|Nov|Dec"
)
_DATE = re.compile(
    rf"\b(?:\d{{4}}-\d{{1,2}}-\d{{1,2}}|\d{{1,2}}/\d{{1,2}}(?:/\d{{2,4}})?|"
    rf"\d{{1,2}}(?:st|nd|rd|th)?\s+(?:{_MONTH_NAMES})\.?"
    rf"(?:\s*,?\s*\d{{2,4}})?)\b",
    re.IGNORECASE,
)
_DATE_START = re.compile(
    r"\b(?:from|starts?|starting|commences?|commencing|start date)\s*(?:on\s*)?[:=-]?\s*$",
    re.IGNORECASE,
)
_DATE_END = re.compile(
    r"(?:\b(?:to|until|through|ends?|ending|finishes?|finishing|end date)"
    r"\s*(?:on\s*)?[:=]?|[–—-])\s*$",
    re.IGNORECASE,
)
_EXCLUDED_DATE = re.compile(
    r"\b(?:applications?|apply|closes?|closing|deadline|posted|advertised|"
    r"interviews?|visa|passport|established|founded|experience|experienced|"
    r"previous|prior|past|history|historical|formerly)\b",
    re.IGNORECASE,
)
_NEGATED_DATE = re.compile(
    r"\b(?:not|never|isn't|aren't|doesn't|don't|won't|cannot)\b",
    re.IGNORECASE,
)
_NEW_DATE_CONTEXT = re.compile(
    r"\b(?:contracts?|fixed[ -]term|start date|"
    r"(?:current|this|new|our)\s+(?:job|role|position|employment))\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class _Claim:
    status: TenureStatus
    evidence: str
    reason: str
    low: int | None = None
    high: int | None = None
    unit: Literal["months", "days"] | None = None
    minimum: bool = False


@dataclass(frozen=True)
class _DateToken:
    value: date | None
    evidence: str
    role: Literal["start", "end", "unknown"]


def _snippet(text: str, start: int = 0, end: int = 0) -> str:
    """Retain original text; centre a long snippet around the matching evidence."""
    if len(text) <= 240:
        return text.strip()
    left = max(0, min(start - 60, end - 240))
    return text[left : left + 240].strip()


def _number(value: str) -> int | None:
    if value.isdigit():
        return int(value) if len(value) <= 9 else None
    if "." in value:
        return None
    return sum(_SMALL_NUMBERS[word] for word in re.split(r"[ -]", value.lower()))


def _parse_date(value: str) -> date | None:
    try:
        if "-" in value:
            year, month, day = (int(part) for part in value.split("-"))
        elif "/" in value:
            parts = value.split("/")
            if len(parts) != 3 or len(parts[2]) != 4:
                return None
            day, month, year = (int(part) for part in parts)
        else:
            normalized = re.sub(r"(\d)(?:st|nd|rd|th)\b", r"\1", value.lower())
            fields = normalized.replace(".", "").replace(",", " ").split()
            if len(fields) != 3 or len(fields[2]) != 4:
                return None
            month_lookup = {
                name.lower()[:3]: number for number, name in enumerate(calendar.month_name) if name
            }
            day, month, year = int(fields[0]), month_lookup[fields[1][:3]], int(fields[2])
        return date(year, month, day)
    except (ValueError, KeyError):
        return None


def _date_information(
    text: str,
) -> tuple[_Claim | None, date | None, date | None, tuple[str, ...]]:
    tokens: list[_DateToken] = []
    for segment in _SEGMENT.split(text):
        if not (
            _EMPLOYMENT.search(segment)
            or re.search(
                r"\b(?:start date|end date|starts?|ends?|commenc\w*)\b", segment, re.IGNORECASE
            )
        ):
            continue
        previous_end = 0
        excluded_context = False
        for match in _DATE.finditer(segment):
            prefix = segment[previous_end : match.start()]
            suffix = segment[match.end() : match.end() + 30]
            previous_end = match.end()
            if _EXCLUDED_DATE.search(prefix) or _NEGATED_DATE.search(prefix):
                excluded_context = True
            elif _NEW_DATE_CONTEXT.search(prefix):
                excluded_context = False
            if excluded_context or re.match(
                r"\s*(?:is the\s+)?(?:deadline|closing date)\b", suffix, re.IGNORECASE
            ):
                continue
            role: Literal["start", "end", "unknown"] = "unknown"
            if _DATE_START.search(prefix):
                role = "start"
            elif _DATE_END.search(prefix):
                role = "end"
            tokens.append(
                _DateToken(
                    _parse_date(match.group()), _snippet(segment, match.start(), match.end()), role
                )
            )
    if not tokens:
        return None, None, None, ()
    snippets = tuple(dict.fromkeys(token.evidence for token in tokens))
    evidence = snippets[0]
    if any(token.value is None for token in tokens):
        return (
            _Claim("unknown", evidence, "employment_dates_invalid_or_missing_year"),
            None,
            None,
            snippets,
        )
    if len(tokens) == 1 and tokens[0].role == "start":
        assert tokens[0].value is not None
        try:
            add_calendar_months(tokens[0].value, 3)
        except ValueError:
            return (
                _Claim("unknown", evidence, "employment_dates_out_of_range"),
                tokens[0].value,
                None,
                snippets,
            )
        return None, tokens[0].value, None, snippets
    if len(tokens) != 2 or tokens[1].role != "end" or tokens[0].role == "end":
        return (
            _Claim("unknown", evidence, "employment_date_range_not_unambiguous"),
            None,
            None,
            snippets,
        )
    start, end = tokens[0].value, tokens[1].value
    assert start is not None and end is not None
    if end < start:
        return _Claim("unknown", evidence, "employment_dates_reversed"), start, end, snippets
    try:
        boundary = add_calendar_months(start, 3)
    except ValueError:
        return _Claim("unknown", evidence, "employment_dates_out_of_range"), start, end, snippets
    if end == boundary:
        return (
            _Claim("boundary", evidence, "three_calendar_month_date_boundary"),
            start,
            end,
            snippets,
        )
    if end > boundary:
        return (
            _Claim("exceeds_limit", evidence, "employment_dates_exceed_three_months"),
            start,
            end,
            snippets,
        )
    return (
        _Claim("compatible", evidence, "employment_dates_within_three_months"),
        start,
        end,
        snippets,
    )


def _duration_status(
    low: int, high: int | None, unit: Literal["months", "days"], start: date | None
) -> TenureStatus:
    if unit == "months":
        if low > 3:
            return "exceeds_limit"
        if high is None:
            return "boundary" if low == 3 else "unknown"
        return "compatible" if high <= 3 else "boundary"
    try:
        threshold = (add_calendar_months(start, 3) - start).days if start else None
    except ValueError:
        return "unknown"
    if threshold is not None:
        if low > threshold:
            return "exceeds_limit"
        if high is None:
            return "boundary" if low == threshold else "unknown"
        return "compatible" if high < threshold else "boundary"
    if low >= 93:
        return "exceeds_limit"
    if high is None:
        return "boundary" if low >= 89 else "unknown"
    return "compatible" if high <= 88 else "boundary"


def _duration_claims(text: str, start: date | None) -> list[_Claim]:
    claims: list[_Claim] = []
    for segment in _SEGMENT.split(text):
        if not _EMPLOYMENT.search(segment):
            continue
        previous_end = 0
        matches = list(_DURATION.finditer(segment))
        for index, match in enumerate(matches):
            prefix = segment[previous_end : match.start()]
            next_start = matches[index + 1].start() if index + 1 < len(matches) else len(segment)
            suffix = segment[match.end() : next_start]
            previous_end = match.end()
            # Experience, visa validity, salary periods, training and notice are not tenure.
            local = prefix[-45:] + " " + suffix[:45]
            if _EXCLUDED_DURATION.search(local):
                continue
            evidence = _snippet(segment, match.start(), match.end())
            negated = re.sub(r"\bno (?:more|less) than\b", "", local, flags=re.IGNORECASE)
            if re.search(r"\b(?:not|no|never|isn't|aren't)\b", negated, re.IGNORECASE) and not (
                re.search(r"\b(?:no extension|no renewal)\b", negated, re.IGNORECASE)
            ):
                claims.append(_Claim("unknown", evidence, "employment_duration_negated"))
                continue
            low = _number(match["low"])
            high = _number(match["high"]) if match["high"] else low
            first_unit = match["first_unit"]
            unit_text = match["unit"].lower()
            if (
                low is None
                or high is None
                or low <= 0
                or high < low
                or re.search(r"\b(?:hundred|thousand|million|dozen)\b", prefix, re.IGNORECASE)
                or (
                    match["range"] == "and"
                    and not re.search(r"\bbetween\s*$", prefix, re.IGNORECASE)
                )
                or (first_unit and first_unit.lower().rstrip("s") != unit_text.rstrip("s"))
            ):
                claims.append(
                    _Claim("unknown", evidence, "employment_duration_invalid_or_unsupported")
                )
                continue
            unit: Literal["months", "days"] = (
                "months" if unit_text.startswith(("year", "month")) else "days"
            )
            if unit_text.startswith("year"):
                low, high = low * 12, high * 12
            if unit_text.startswith("week"):
                low, high = low * 7, high * 7
            is_minimum = bool(_MINIMUM.search(prefix)) or bool(
                re.match(
                    r"\s*(?:\+|(?:minimum|or (?:more|longer)|at least)\b)", suffix, re.IGNORECASE
                )
            )
            if re.search(
                r"\b(?:must\s+commit|commitment|availability|available)\b", prefix, re.IGNORECASE
            ) and not re.search(r"\b(?:contract|fixed[ -]term|duration)\b", prefix, re.IGNORECASE):
                is_minimum = True
            is_maximum = bool(_MAXIMUM.search(prefix)) or bool(
                re.match(r"\s*(?:maximum|or less|at most)\b", suffix, re.IGNORECASE)
            )
            if is_minimum and not match["high"]:
                if re.search(r"\b(?:more than|over|longer than)\s*$", prefix, re.IGNORECASE):
                    low += 1
                high = None
            elif is_maximum:
                low = 0
            status = _duration_status(low, high, unit, start)
            reason = {
                "compatible": "explicit_employment_duration_within_three_months",
                "exceeds_limit": "employment_duration_exceeds_three_months",
                "boundary": "employment_duration_boundary_requires_confirmation",
                "unknown": "employment_duration_has_no_confirmed_upper_bound",
            }[status]
            claims.append(_Claim(status, evidence, reason, low, high, unit, is_minimum))
    return claims


def _term_ambiguous(segment: str) -> bool:
    # Modifiers of salary, shift patterns or benefits do not change the contract's length.
    relevant = re.sub(
        r"\bflexible\s+(?:working\s+)?(?:hours|shifts|roster|schedule|arrangements)\b|"
        r"\b(?:salary|pay|wages?)\s+(?:is\s+)?negotiable\b|"
        r"\b(?:no|without)\s+(?:possibility\s+of\s+)?(?:extension|renewal)\b",
        "",
        segment,
        flags=re.IGNORECASE,
    )
    return bool(_APPROXIMATE.search(relevant) or _EXTENSION.search(relevant))


def _term_alternatives(segment: str) -> bool:
    return bool(
        re.search(r"\bor\b", segment, re.IGNORECASE)
        and _DURATION.search(segment)
        and not re.search(r"\bor (?:less|more|longer)\b", segment, re.IGNORECASE)
    )


def _dates_disagree(claim: _Claim, start: date, end: date) -> bool:
    if claim.low is None or claim.unit is None:
        return False
    try:
        low_end = (
            add_calendar_months(start, claim.low)
            if claim.unit == "months"
            else start + timedelta(days=claim.low)
        )
        high_end = (
            None
            if claim.high is None
            else (
                add_calendar_months(start, claim.high)
                if claim.unit == "months"
                else start + timedelta(days=claim.high)
            )
        )
    except (ValueError, OverflowError):
        return True
    # An inclusive last work day may be one day before the exclusive duration end.
    return (end - low_end).days < -1 or (high_end is not None and end > high_end)


def assess_tenure(text: str) -> TenureAssessment:
    """Assess job-title/description text; unknown information cannot establish fit."""
    date_claim, start, end, date_evidence = _date_information(text)
    durations = _duration_claims(text, start)
    claims = durations + ([date_claim] if date_claim else [])
    evidence = tuple(dict.fromkeys([claim.evidence for claim in claims] + list(date_evidence)))
    reasons = tuple(dict.fromkeys(claim.reason for claim in claims))
    start_text, end_text = start.isoformat() if start else None, end.isoformat() if end else None
    if not claims:
        return TenureAssessment(
            "unknown",
            start_text,
            end_text,
            evidence=evidence,
            reasons=(
                "employment_end_date_missing" if start else "no_explicit_employment_duration",
            ),
        )

    duration_keys = {
        (claim.low, claim.high, claim.unit) for claim in durations if claim.unit is not None
    }
    conflicts = len(duration_keys) > 1 or (
        start is not None
        and end is not None
        and any(_dates_disagree(claim, start, end) for claim in durations)
    )
    segments = _SEGMENT.split(text)
    relevant_segments = [
        segment
        for segment in segments
        if any(snippet in segment for snippet in evidence)
        or (_EXTENSION.search(segment) and not _EXCLUDED_DURATION.search(segment))
    ]
    ambiguous = any(_term_ambiguous(segment) for segment in relevant_segments)
    alternatives = any(_term_alternatives(segment) for segment in relevant_segments)
    for segment in relevant_segments:
        if _term_ambiguous(segment) or _term_alternatives(segment):
            match = (
                _EXTENSION.search(segment)
                or _APPROXIMATE.search(segment)
                or re.search(r"\bor\b", segment, re.IGNORECASE)
            )
            if match:
                evidence += (_snippet(segment, match.start(), match.end()),)
    evidence = tuple(dict.fromkeys(evidence))
    hard_minimum = any(
        claim.minimum
        and claim.status == "exceeds_limit"
        and any(
            claim.evidence in segment
            and not _term_ambiguous(segment)
            and not _term_alternatives(segment)
            for segment in segments
        )
        for claim in durations
    )
    if hard_minimum:
        status: TenureStatus = "exceeds_limit"
        reasons += ("explicit_minimum_employment_commitment_exceeds_three_months",)
    elif conflicts:
        status = "unknown"
        reasons += ("conflicting_employment_terms",)
    elif ambiguous or alternatives:
        status = "unknown"
        reasons += ("employment_term_approximate_flexible_or_extendable",)
    elif any(claim.status == "unknown" for claim in claims):
        status = "unknown"
    elif any(claim.status == "exceeds_limit" for claim in claims):
        status = "exceeds_limit"
    elif any(claim.status == "boundary" for claim in claims):
        status = "boundary"
    else:
        status = "compatible"
    return TenureAssessment(status, start_text, end_text, evidence, reasons)
