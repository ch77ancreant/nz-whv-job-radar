"""Allowlisted SEEK records and conservative local profile matching.

These decisions concern search relevance only, not WHV eligibility.
"""

import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from html.parser import HTMLParser
from typing import Literal
from urllib.parse import urlsplit

from .profiles import Profile


class JobError(ValueError):
    """A source item cannot safely identify a SEEK job."""


@dataclass(frozen=True)
class Job:
    source_job_id: str
    source_url: str
    title: str
    employer: str | None
    location: str | None
    country: str | None
    employment_type: str | None
    salary: str | None
    posted_at: str | None
    closes_at: str | None
    description: str | None


@dataclass(frozen=True)
class MatchDecision:
    status: Literal["matched", "excluded", "needs_confirmation"]
    reasons: tuple[str, ...]


class _PlainText(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.hidden = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style"}:
            self.hidden += 1
        elif tag in {"p", "br", "div", "li", "h1", "h2", "h3"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"}:
            self.hidden = max(0, self.hidden - 1)
        elif tag in {"p", "div", "li", "h1", "h2", "h3"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self.hidden:
            self.parts.append(data)


_EMAIL = re.compile(r"[\w.!#$%&'*+/=?^`{|}~-]+@[\w-]+(?:\.[\w-]+)+", re.IGNORECASE)
_PHONE = re.compile(r"(?<![\w\d])(?:\+?\d[\d ()-]{6,}\d)(?![\w\d])")
_DATE_TOKEN = re.compile(r"(?<!\w)(?:\d{4}[-/]\d{1,2}[-/]\d{1,2}|\d{1,2}/\d{1,2}/\d{4})(?!\d)")
_SOCIAL = re.compile(
    r"(?:https?://)?(?:www\.)?(?:facebook\.com|instagram\.com|linkedin\.com|"
    r"tiktok\.com|twitter\.com|x\.com|t\.me)/[^\s<>]+",
    re.IGNORECASE,
)
_CONTACT_LINE = re.compile(
    r"(?im)^\s*(?:contact(?: person)?|recruiter|hiring manager)\s*:\s*[^\n]+"
)


def _redact_phone(match: re.Match[str]) -> str:
    value = match.group()
    # Short salary figures are not phone numbers; masking is best effort.
    digits = re.sub(r"\D", "", value)
    if len(digits) >= 9 or (len(digits) >= 7 and (value.startswith("+") or "(" in value)):
        return "[REDACTED_PHONE]"
    return value


def _redact_phone_segment(text: str) -> str:
    text = re.sub(
        r"(?i)\b(?:phone|telephone|call|mobile|tel)\s*:?\s*\+?\d[\d ()-]{5,}\d",
        "[REDACTED_PHONE]",
        text,
    )
    return _PHONE.sub(_redact_phone, text)


def _redact_phones(text: str) -> str:
    # Preserve individual, valid date tokens, not an entire number-filled range.
    # A phone adjacent to a date still passes through the redactor independently.
    # This preserves evidence only; it does not infer employment duration.
    pieces: list[str] = []
    cursor = 0
    for match in _DATE_TOKEN.finditer(text):
        parts = match.group().replace("/", "-").split("-")
        year, month, day = parts if len(parts[0]) == 4 else list(reversed(parts))
        try:
            date(int(year), int(month), int(day))
        except ValueError:
            continue
        pieces.append(_redact_phone_segment(text[cursor : match.start()]))
        pieces.append(match.group())
        cursor = match.end()
    pieces.append(_redact_phone_segment(text[cursor:]))
    return "".join(pieces)


def _clean(value: str) -> str:
    parser = _PlainText()
    parser.feed(value)
    text = "".join(parser.parts)
    text = _CONTACT_LINE.sub("[REDACTED_CONTACT]", text)
    text = _EMAIL.sub("[REDACTED_EMAIL]", text)
    text = _SOCIAL.sub("[REDACTED_SOCIAL]", text)
    text = re.sub(
        r"(?i)\b(?:instagram|telegram|facebook|linkedin|twitter|tiktok)\s*:\s*@?[\w.-]+",
        "[REDACTED_SOCIAL]",
        text,
    )
    text = _redact_phones(text)
    # Keep newlines for later evidence extraction, but remove terminal controls.
    text = "".join(char for char in text if char in "\n\t" or unicodedata.category(char) != "Cc")
    return "\n".join(" ".join(line.split()) for line in text.splitlines() if line.strip())


def _field(raw: dict[str, object], *names: str) -> str | None:
    for name in names:
        value = raw.get(name)
        if value is None or value == "":
            continue
        if not isinstance(value, str):
            raise JobError(f"{name} must be a string or null")
        cleaned = _clean(value)
        if cleaned:
            return cleaned
    return None


def _job_url(raw: dict[str, object]) -> tuple[str, str]:
    value = next(
        (raw[key] for key in ("canonicalUrl", "sourceUrl", "url", "applyUrl") if raw.get(key)), None
    )
    if not isinstance(value, str):
        raise JobError("A SEEK NZ job URL is required")
    try:
        parsed = urlsplit(value.strip())
        allowed_hosts = {"nz.seek.com", "seek.co.nz", "www.seek.co.nz"}
        if (
            parsed.scheme.lower() not in {"http", "https"}
            or parsed.hostname not in allowed_hosts
            or parsed.username is not None
            or parsed.password is not None
            or parsed.port not in {None, 80, 443}
        ):
            raise JobError("Only public SEEK NZ job URLs are accepted")
        match = re.fullmatch(r"/job/([0-9]+)/?", parsed.path)
        if not match:
            raise JobError("URL must identify a SEEK job")
    except ValueError:
        raise JobError("Invalid SEEK NZ job URL") from None
    return "https://nz.seek.com/job/" + match.group(1), match.group(1)


def _identifier(raw: dict[str, object], url_id: str) -> str:
    """Validate supplied identifiers, but keep every downstream key on SEEK's URL ID.

    Actor jobId values may be hashes or differ across keyword searches. They are
    not a stable identity for a SEEK vacancy, including when seekJobId is absent.
    """
    for key in ("seekJobId", "jobId"):
        value = raw.get(key)
        if value is None or value == "":
            continue
        if type(value) not in {str, int}:
            raise JobError(f"{key} must be a string or integer")
        identifier = str(value).strip()
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,200}", identifier):
            raise JobError(f"Invalid {key}")
        if key == "seekJobId" and identifier != url_id:
            raise JobError("seekJobId disagrees with the SEEK URL")
        return url_id
    return url_id


def normalize_job(raw: dict[str, object]) -> Job:
    """Project one dataset item; raw contact/social fields are never retained."""
    if not isinstance(raw, dict):
        raise JobError("Dataset item must be an object")
    url, url_id = _job_url(raw)
    title = _field(raw, "title")
    if not title:
        raise JobError("Job title is required")
    country = _field(raw, "locationCountry", "country")
    if country and _fold(country) in {"nz", "new zealand", "aotearoa", "aotearoa new zealand"}:
        country = "NZ"
    elif country and _fold(country) in {"unknown", "n a", "not specified"}:
        country = None
    elif country:
        country = country.upper()
    return Job(
        source_job_id=_identifier(raw, url_id),
        source_url=url,
        title=title,
        employer=_field(raw, "company", "employer", "companyName"),
        location=_field(raw, "location"),
        country=country,
        employment_type=_field(raw, "employmentType", "workType"),
        salary=_field(raw, "salaryText", "salary"),
        posted_at=_field(raw, "postedDate", "postedAt", "datePosted"),
        closes_at=_field(raw, "validThrough", "closingDate"),
        description=_field(raw, "description", "jobDescription"),
    )


def _fold(text: str) -> str:
    value = unicodedata.normalize("NFKD", text.casefold())
    value = "".join(char for char in value if not unicodedata.combining(char))
    return " ".join("".join(char if char.isalnum() else " " for char in value).split())


def _contains(text: str, phrase: str, *, allow_plural: bool = False) -> bool:
    normalized = _fold(phrase)
    if not normalized:
        return False
    variants = [normalized]
    if allow_plural:
        # Limited regular s-plurals, not stemming/substrings (hand != handyman).
        last = normalized.split()[-1]
        if last.endswith("s") and not last.endswith(("ss", "is", "us")):
            variants.append(normalized[:-1])
        elif not last.endswith("s"):
            variants.append(normalized + "s")
    haystack = f" {_fold(text)} "
    return any(f" {variant} " in haystack for variant in variants)


def match_job(job: Job, profile: Profile) -> MatchDecision:
    """Known mismatches exclude; unknown constraints never become a match."""
    excluded: list[str] = []
    uncertain: list[str] = []
    if not profile.enabled:
        excluded.append("profile_disabled")
    if job.country is None:
        uncertain.append("country_unknown")
    elif job.country != profile.country:
        excluded.append("country_mismatch")
    if any(_contains(job.title, word, allow_plural=True) for word in profile.exclude_title):
        excluded.append("excluded_title")
    # Search title and body independently so a phrase cannot bridge their boundary.
    if not any(
        _contains(job.title, word, allow_plural=True)
        or _contains(job.description or "", word, allow_plural=True)
        for word in profile.keywords
    ):
        excluded.append("keyword_mismatch")
    if job.location is None:
        uncertain.append("location_unknown")
    elif not any(_contains(job.location, location) for location in profile.locations):
        excluded.append("location_mismatch")
    if profile.employers:
        if job.employer is None:
            uncertain.append("employer_unknown")
        elif not any(_contains(job.employer, employer) for employer in profile.employers):
            excluded.append("employer_mismatch")
    if excluded:
        return MatchDecision("excluded", tuple(excluded + uncertain))
    if uncertain:
        return MatchDecision("needs_confirmation", tuple(uncertain))
    return MatchDecision("matched", ("profile_match",))
