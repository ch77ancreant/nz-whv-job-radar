"""Bounded collection and WHV assessment; delivery is a separate post-collection step."""

import hashlib
import json
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from nz_job_radar.apify import ApifyClient, ApifyError, RunInfo, build_actor_input
from nz_job_radar.jobs import Job, JobError, MatchDecision, match_job, normalize_job
from nz_job_radar.journal import Attempt, Journal, JournalError
from nz_job_radar.profiles import Profile
from nz_job_radar.settings import LiveSettings
from nz_job_radar.whv import (
    RULES_CHECKED_AT,
    RULES_SOURCE_URL,
    RULES_VERSION,
    WhvAssessment,
    assess_job,
)

WHV_LABELS = ("likely_suitable", "needs_confirmation", "likely_incompatible")


class CollectionError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


@dataclass
class Report:
    profile_id: str
    mode: str
    attempt_id: str
    run_id: str | None = None
    dataset_id: str | None = None
    usage_usd: str | None = None
    charged_items: int | None = None
    fetched: int = 0
    duplicate_count: int = 0
    invalid_count: int = 0
    matched: list[Job] = field(default_factory=list)
    excluded: list[tuple[Job, MatchDecision]] = field(default_factory=list)
    pending: list[tuple[Job, MatchDecision]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    error_code: str | None = None
    dataset_complete: bool = True
    search_limits: dict[str, int] = field(default_factory=dict)
    whv_assessments: dict[str, WhvAssessment] = field(default_factory=dict)
    notification_candidates: set[str] = field(default_factory=set)
    assessed_at: str = field(default_factory=lambda: date.today().isoformat())
    notifications: dict[str, Any] = field(default_factory=lambda: {"mode": "not_requested"})

    def __post_init__(self) -> None:
        if (date.fromisoformat(self.assessed_at) - date.fromisoformat(RULES_CHECKED_AT)).days > 90:
            if "whv_rules_stale" not in self.warnings:
                self.warnings.append("whv_rules_stale")

    def summary(self) -> dict[str, Any]:
        reasons = Counter(
            reason for _, decision in self.excluded + self.pending for reason in decision.reasons
        )
        all_counts: Counter[str] = Counter(result.label for result in self.whv_assessments.values())
        matched_counts: Counter[str] = Counter(
            self.whv_assessments[job.source_job_id].label
            for job in self.matched
            if job.source_job_id in self.whv_assessments
        )
        return {
            "profile_id": self.profile_id,
            "mode": self.mode,
            "attempt_id": self.attempt_id,
            "run_id": self.run_id,
            "dataset_id": self.dataset_id,
            "usage_total_usd": self.usage_usd,
            "charged_item_count": self.charged_items,
            "fetched": self.fetched,
            "matched": len(self.matched),
            "excluded": len(self.excluded),
            "needs_profile_confirmation": len(self.pending),
            "invalid": self.invalid_count,
            "duplicates": self.duplicate_count,
            "reasons": dict(reasons),
            "dataset_complete": self.dataset_complete,
            "search_limits": self.search_limits,
            "search_coverage": "synthetic" if self.mode == "fixture" else "bounded_not_verified",
            "warnings": self.warnings,
            "error_code": self.error_code,
            "whv": "assessed_phase_2",
            "whv_counts": {label: matched_counts[label] for label in WHV_LABELS},
            "whv_all_counts": {label: all_counts[label] for label in WHV_LABELS},
            "whv_rules": {
                "version": RULES_VERSION,
                "checked_at": RULES_CHECKED_AT,
                "source_url": RULES_SOURCE_URL,
                "assessed_at": self.assessed_at,
                "stale": (
                    date.fromisoformat(self.assessed_at) - date.fromisoformat(RULES_CHECKED_AT)
                ).days
                > 90,
            },
            "notification_policy": {
                "eligible": len(self.notification_candidates),
                "suppressed": len(self.matched) - len(self.notification_candidates),
            },
            "telegram": self.notifications["mode"],
            "persistence": {
                key: self.notifications.get(key, 0)
                for key in ("persisted", "new_jobs", "changed_jobs")
            },
            "notifications": {
                **{
                    key: self.notifications.get(key, 0)
                    for key in ("queued", "deduplicated", "held")
                },
                **self.notifications.get("delivery", {}),
            },
        }


def fingerprint(profile: Profile) -> str:
    payload = json.dumps(asdict(profile), sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode()).hexdigest()


def process_items(report: Report, items: list[dict[str, object]], profile: Profile) -> None:
    seen: set[str] = set()
    report.fetched = len(items)
    for raw in items:
        try:
            job = normalize_job(raw)
        except JobError:
            report.invalid_count += 1
            continue
        if job.source_job_id in seen:
            report.duplicate_count += 1
            continue
        seen.add(job.source_job_id)
        decision = match_job(job, profile)
        assessment = assess_job(job, today=date.fromisoformat(report.assessed_at))
        report.whv_assessments[job.source_job_id] = assessment
        if assessment.rules_stale and "whv_rules_stale" not in report.warnings:
            report.warnings.append("whv_rules_stale")
        if decision.status == "matched":
            report.matched.append(job)
            if assessment.label in profile.notification_labels:
                report.notification_candidates.add(job.source_job_id)
        elif decision.status == "needs_confirmation":
            report.pending.append((job, decision))
        else:
            report.excluded.append((job, decision))
    if report.invalid_count:
        report.warnings.append("invalid_items_skipped")


def read_fixture(path: Path) -> list[dict[str, object]]:
    try:
        if path.stat().st_size > 20_000_000:
            raise CollectionError("fixture_too_large", "樣本檔超過 20 MB。")
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise CollectionError("fixture_invalid", "無法讀取 JSON 樣本。") from None
    if (
        not isinstance(payload, dict)
        or payload.get("fixtureKind")
        not in ("synthetic_phase1_dataset", "synthetic_phase2_dataset")
        or not isinstance(payload.get("items"), list)
        or any(not isinstance(item, dict) for item in payload["items"])
    ):
        raise CollectionError("fixture_invalid", "需使用 Phase 1／2 synthetic dataset 格式的樣本。")
    return list(payload["items"])


def collect_fixture(profile: Profile, path: Path, journal: Journal) -> Report:
    items = read_fixture(path)
    attempt = journal.fixture(profile.id, fingerprint(profile))
    report = Report(profile.id, "fixture", attempt.id, usage_usd="0")
    report.search_limits = {"max_results": profile.max_results, "max_pages": profile.max_pages}
    process_items(report, items, profile)
    journal.finish(attempt.id, report.summary(), complete=not report.invalid_count)
    return report


def _poll(
    client: ApifyClient,
    journal: Journal,
    attempt: Attempt,
    run: RunInfo,
    wait_seconds: float,
    sleep: Callable[[float], None],
) -> RunInfo:
    deadline = time.monotonic() + wait_seconds
    terminal_failures = {"FAILED", "ABORTED", "TIMED-OUT"}
    while True:
        journal.observe(attempt.id, run)
        if run.status == "SUCCEEDED":
            return run
        if run.status in terminal_failures:
            journal.state(attempt.id, "REMOTE_FAILED", "actor_failed")
            raise CollectionError("actor_failed", "Actor 執行失敗；不是零筆結果。請檢查已知 run。")
        if run.status not in {"READY", "RUNNING", "TIMING-OUT", "ABORTING"}:
            journal.state(attempt.id, "READ_FAILED", "run_status_unknown")
            raise CollectionError("run_status_unknown", "Actor 回傳未知狀態；請稍後 resume。")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            journal.state(attempt.id, "WAIT_TIMEOUT", "wait_timeout")
            raise CollectionError(
                "wait_timeout", "本機停止等待；遠端可能仍在執行。請 resume，不要重新啟動。"
            )
        journal.state(attempt.id, "RUNNING")
        sleep(min(5.0, remaining))
        run = client.get_run(run.id)


def _download(client: ApifyClient, run: RunInfo, report: Report) -> list[dict[str, object]]:
    if run.dataset_id is None:
        report.dataset_complete = False
        report.error_code = "missing_dataset"
        report.warnings.append("dataset_partial_resume_required")
        return []
    items: list[dict[str, object]] = []
    total: int | None = None
    while True:
        try:
            page = client.get_dataset_page(run.dataset_id, offset=len(items), limit=100)
            if page.offset != len(items):
                raise CollectionError("pagination_invalid", "dataset 分頁 offset 不一致。")
            if total is not None and page.total is not None and total != page.total:
                raise CollectionError("pagination_changed", "dataset 總數在下載期間改變。")
            if page.total is not None:
                total = page.total
            if not page.items and total is not None and len(items) < total:
                raise CollectionError("pagination_incomplete", "dataset 尚有資料但分頁為空。")
            if total is not None and len(items) + len(page.items) > total:
                raise CollectionError("pagination_invalid", "dataset 筆數超過回報總數。")
            items.extend(page.items)
            if total is not None and len(items) == total:
                return items
            if total is None and len(page.items) < 100:
                return items
            if len(items) >= 50_000:
                raise CollectionError("download_limit", "達本機下載安全上限 50000 筆。")
        except (ApifyError, CollectionError) as error:
            report.dataset_complete = False
            report.error_code = error.code
            report.warnings.append("dataset_partial_resume_required")
            return items


def collect_live(
    profile: Profile,
    settings: LiveSettings,
    journal: Journal,
    client: ApifyClient,
    *,
    resume_run_id: str | None = None,
    attempt_id: str | None = None,
    wait_seconds: float = 180,
    sleep: Callable[[float], None] = time.sleep,
    progress: Callable[[str], None] = print,
) -> Report:
    if resume_run_id is None:
        actor_input = build_actor_input(profile)
        attempt = journal.reserve(
            profile.id, fingerprint(profile), settings.max_charge_usd, settings.daily_budget_usd
        )
        progress(f"本機 attempt ID: {attempt.id}")
        try:
            run = client.start_run(
                actor_input,
                max_charge_usd=settings.max_charge_usd,
                timeout_seconds=settings.timeout_seconds,
            )
        except ApifyError as error:
            state = "START_UNKNOWN" if error.code == "start_unknown" else "START_REJECTED"
            journal.state(attempt.id, state, error.code)
            raise
    else:
        attempt = journal.get(attempt_id) if attempt_id else journal.by_run(resume_run_id)
        if attempt.mode != "live" or attempt.profile_id != profile.id:
            raise JournalError("resume 的 Profile／模式與原執行不符。")
        if attempt.fingerprint != fingerprint(profile):
            raise JournalError("Profile 已變更；請先還原原設定再 resume，避免混用搜尋條件。")
        if attempt.run_id and attempt.run_id != resume_run_id:
            raise JournalError("此 attempt 已綁定其他 run，不能覆蓋。")
        if not attempt.run_id and attempt.state not in {"START_UNKNOWN", "STARTING"}:
            raise JournalError("只有啟動結果不明的 attempt 才可手動連結 run ID。")
        run = client.get_run(resume_run_id)
    # Print identifiers first, even if writing the local journal subsequently fails.
    progress(f"Apify run ID: {run.id}；恢復使用 resume，不會再 POST 啟動。")
    try:
        journal.observe(attempt.id, run)
        run = _poll(client, journal, attempt, run, wait_seconds, sleep)
        report = Report(
            profile.id,
            "live",
            attempt.id,
            run.id,
            run.dataset_id,
            str(run.usage_usd) if run.usage_usd is not None else None,
            run.charged_item_count,
        )
        report.search_limits = {"max_results": profile.max_results, "max_pages": profile.max_pages}
        items = _download(client, run, report)
        process_items(report, items, profile)
        if len(items) >= profile.max_results:
            report.warnings.append("search_result_cap_possible")
        if run.usage_usd is not None and run.usage_usd >= attempt.reserved_usd:
            report.warnings.append("charge_cap_possible")
        journal.finish(
            attempt.id,
            report.summary(),
            complete=report.dataset_complete and not report.invalid_count,
        )
        return report
    except ApifyError as error:
        journal.state(attempt.id, "READ_FAILED", error.code)
        raise
