"""Explicit collection, notification preview, and opt-in recoverable Telegram delivery."""

import argparse
import json
import sqlite3
import sys
from collections import Counter
from contextlib import ExitStack
from dataclasses import asdict
from pathlib import Path
from typing import Any

from nz_job_radar.apify import ApifyClient, ApifyError
from nz_job_radar.delivery import dispatch
from nz_job_radar.jobs import Job
from nz_job_radar.journal import Journal, JournalError
from nz_job_radar.locking import ProfileBusyError, profile_lock
from nz_job_radar.pipeline import (
    CollectionError,
    Report,
    collect_fixture,
    collect_live,
    fingerprint,
)
from nz_job_radar.profiles import ProfileError, load_profiles
from nz_job_radar.settings import (
    SettingsError,
    TelegramSettings,
    load_live_settings,
    load_telegram_settings,
)
from nz_job_radar.store import JobStore, StoreError, destination_key
from nz_job_radar.telegram import TelegramClient, TelegramError, normalize_chat_id
from nz_job_radar.whv import DISCLAIMER


def _positive_wait(value: str) -> float:
    try:
        wait = float(value)
    except ValueError:
        raise argparse.ArgumentTypeError("wait-seconds 必須是 1～3600 的數字。") from None
    if not 1 <= wait <= 3600:
        raise argparse.ArgumentTypeError("wait-seconds 必須介於 1 與 3600。")
    return wait


def _notification_limit(value: str) -> int:
    try:
        limit = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError("通知筆數上限必須是 1～100 的整數。") from None
    if not 1 <= limit <= 100:
        raise argparse.ArgumentTypeError("通知筆數上限必須介於 1 與 100。")
    return limit


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="NZ Job Radar（SEEK、WHV、通知預覽與明確啟用發送）")
    commands = root.add_subparsers(dest="command", required=True)
    for name in ("profiles", "run", "resume", "runs"):
        command = commands.add_parser(name)
        command.add_argument("--format", choices=("text", "json"), default="text")
        if name != "runs":
            command.add_argument("--profiles-dir", type=Path, default=Path("profiles"))
        if name != "profiles":
            command.add_argument("--state-dir", type=Path, default=Path("data"))
        if name in {"run", "resume"}:
            command.add_argument("--profile", required=True)
            command.add_argument("--show-excluded", action="store_true")
            command.add_argument("--env-file", type=Path, default=Path(".env"))
            command.add_argument("--wait-seconds", type=_positive_wait, default=180.0)
            notification = command.add_mutually_exclusive_group()
            notification.add_argument(
                "--dry-run", action="store_true", help="預覽通知，不排隊或發送"
            )
            notification.add_argument(
                "--notify", action="store_true", help="僅 live：保存並嘗試通知"
            )
            command.add_argument("--chat-id", help="僅 dry-run：依指定數字 Chat ID 查本機去重")
            command.add_argument(
                "--notify-limit",
                type=_notification_limit,
                default=20,
                help="--notify 本次最多處理的通知筆數（1～100，預設 20）",
            )
        if name == "run":
            mode = command.add_mutually_exclusive_group(required=True)
            mode.add_argument("--fixture", type=Path)
            mode.add_argument("--live", action="store_true")
        if name == "resume":
            command.add_argument("--run-id", required=True)
            command.add_argument("--attempt-id")
            command.add_argument("--live", action="store_true", required=True)
    for name in ("outbox", "deliver", "resolve-notification"):
        command = commands.add_parser(name)
        command.add_argument("--state-dir", type=Path, default=Path("data"))
        command.add_argument("--format", choices=("text", "json"), default="text")
        if name == "deliver":
            command.add_argument("--send", action="store_true", required=True)
            command.add_argument("--env-file", type=Path, default=Path(".env"))
            command.add_argument("--profiles-dir", type=Path, default=Path("profiles"))
            command.add_argument("--outbox-id")
            command.add_argument("--limit", type=_notification_limit, default=20)
        if name == "resolve-notification":
            command.add_argument("--id", required=True)
            command.add_argument("--action", choices=("sent", "retry", "skip"), required=True)
            command.add_argument("--message-id", type=int)
            command.add_argument("--acknowledge-duplicate-risk", action="store_true")
    return root


def _print(text: str, *, token: str = "", error: bool = False) -> None:
    if token:
        text = text.replace(token, "[REDACTED]")
    # Remove terminal control sequences' executable bytes from untrusted source text.
    text = "".join(
        char for char in text if char in "\n\t" or (ord(char) >= 32 and not 127 <= ord(char) <= 159)
    )
    print(text, file=sys.stderr if error else sys.stdout)


def report_payload(report: Report, show_excluded: bool) -> dict[str, Any]:
    def annotated_job(job: Job) -> dict[str, Any]:
        assessment = report.whv_assessments.get(job.source_job_id)
        return {
            **asdict(job),
            "whv": asdict(assessment) if assessment else None,
            "notification_eligible": job.source_job_id in report.notification_candidates,
        }

    payload: dict[str, Any] = {
        "summary": report.summary(),
        "jobs": [annotated_job(job) for job in report.matched],
        "disclaimer": DISCLAIMER,
        "notifications": report.notifications,
    }
    if show_excluded:
        payload["excluded"] = [
            {
                "job": asdict(job),
                "reasons": list(decision.reasons),
                "whv": asdict(report.whv_assessments[job.source_job_id]),
                "notification_eligible": False,
            }
            for job, decision in report.excluded
        ]
        payload["needs_profile_confirmation"] = [
            {
                "job": asdict(job),
                "reasons": list(decision.reasons),
                "whv": asdict(report.whv_assessments[job.source_job_id]),
                "notification_eligible": False,
            }
            for job, decision in report.pending
        ]
    return payload


def _assessment_lines(report: Report, job: Job) -> list[str]:
    assessment = report.whv_assessments.get(job.source_job_id)
    if assessment is None:
        return ["   WHV：尚無評估資料。"]
    labels = {
        "likely_suitable": "初步可能適合",
        "needs_confirmation": "需確認",
        "likely_incompatible": "初步可能不相容",
    }
    tenure_labels = {
        "compatible": "明示聘期在本版限制內",
        "exceeds_limit": "明示聘期超過限制",
        "boundary": "邊界不明，需確認",
        "unknown": "聘期不明或資訊矛盾",
    }
    lines = [
        f"   WHV: {assessment.label}（{labels[assessment.label]}）"
        f" | 規則分數 {assessment.score}/100 | 證據信心 {assessment.confidence}（非機率）",
        f"   聘期：{tenure_labels[assessment.tenure.status]}",
        "   通知政策："
        + (
            "符合標籤設定（實際送達狀態見通知摘要）"
            if job.source_job_id in report.notification_candidates
            else "不列入候選（職缺仍保留顯示）"
        ),
    ]
    if assessment.tenure.start_date or assessment.tenure.end_date:
        lines.append(
            f"   明示任職日：{assessment.tenure.start_date or '未知'}"
            f" → {assessment.tenure.end_date or '未知'}"
        )
    lines.extend(f"   理由：{reason}" for reason in assessment.reasons)
    lines.extend(f"   證據 [{entry.field}]：{entry.quote}" for entry in assessment.evidence)
    if not assessment.evidence:
        lines.append("   證據：缺少可辨識的聘期／工作權文字，沒有推定符合。")
    lines.extend(f"   待確認：{question}" for question in assessment.questions)
    return lines


def render_report(report: Report, show_excluded: bool) -> str:
    summary = report.summary()
    lines = [
        f"Profile: {report.profile_id} | 模式: {report.mode}",
        f"取得 {report.fetched} | 符合 {len(report.matched)} | 排除 {len(report.excluded)}"
        f" | Profile待確認 {len(report.pending)} | 無效 {report.invalid_count}"
        f" | 同批重複 {report.duplicate_count}",
        f"Run: {report.run_id or '—（離線）'} | Dataset: {report.dataset_id or '—'}",
        f"回讀毛額 USD: {report.usage_usd or '未知'} | 本機 attempt: {report.attempt_id}",
        f"WHV：已做規則式初篩；Telegram：{report.notifications['mode']}（Phase 3）。",
        "Profile 符合者的 WHV 分類："
        + "; ".join(f"{key}={value}" for key, value in summary["whv_counts"].items()),
        f"通知政策候選 {summary['notification_policy']['eligible']}"
        f" | 政策排除 {summary['notification_policy']['suppressed']}"
        "（候選數不代表送達數）",
        f"規則版本：{summary['whv_rules']['version']}"
        f" | 查核日期：{summary['whv_rules']['checked_at']}",
        f"官方來源：{summary['whv_rules']['source_url']}",
        DISCLAIMER,
    ]
    if report.mode == "fixture":
        lines.append("以下為合成樣本，不是真實職缺。沒有任何網路呼叫或費用。")
    else:
        lines.append("搜尋受結果／頁數上限限制，不代表完整市場；不推測職缺下架。")
        lines.append("費用可能延後更新；這不是信用卡扣款或帳戶餘額。")
        lines.append(
            f"搜尋設定上限：maxResults={report.search_limits.get('max_results', '未知')}，"
            f"maxPages={report.search_limits.get('max_pages', '未知')}；頁數截斷無法獨立確認。"
        )
    if not report.dataset_complete:
        lines.append(f"部分結果／下載失敗：{report.error_code}；請 resume，不能當成成功空結果。")
    if report.warnings:
        lines.append("警告：" + ", ".join(report.warnings))
    for index, job in enumerate(report.matched, 1):
        lines.extend(
            [
                f"\n{index}. {job.title} | {job.employer or '雇主未知'}",
                f"   {job.location or '地點未知'} | {job.employment_type or '類型未知'}"
                f" | {job.salary or '薪資未知'}",
                f"   刊登：{job.posted_at or '未知'} | "
                f"刊登有效期：{job.closes_at or '未知'}（不是聘期）",
                f"   {job.source_url}",
            ]
        )
        lines.extend(_assessment_lines(report, job))
    if not report.matched:
        lines.append("\n沒有已確認符合此 Profile 的職缺；請同時查看排除／待確認／失敗統計。")
    reasons = Counter(summary["reasons"])
    if reasons:
        lines.append(
            "\n匹配原因統計："
            + "; ".join(f"{key}={value}" for key, value in sorted(reasons.items()))
        )
    if show_excluded:
        for job, decision in report.excluded + report.pending:
            lines.append(f"  [{decision.status}] {job.title}: {', '.join(decision.reasons)}")
            lines.append(f"   {job.source_url}")
            lines.extend(_assessment_lines(report, job))
    notification = report.notifications
    lines.append(
        f"\n本機保存：{notification.get('persisted', 0)} 筆"
        f" | 新職缺 {notification.get('new_jobs', 0)}"
        f" | 重要更新 {notification.get('changed_jobs', 0)}"
    )
    lines.append(
        f"通知：新增待送 {notification.get('queued', 0)}"
        f" | 已有紀錄去重 {notification.get('deduplicated', 0)}"
        f" | 暫緩 {notification.get('held', 0)}"
    )
    if notification["mode"] == "not_requested":
        lines.append("未要求通知；未建立通知佇列／未發送。用 --dry-run 預覽或 --notify 明確發送。")
    elif notification["mode"] == "dry_run":
        lines.append("DRY RUN：未建立通知佇列／未發送，也未消耗既有待送紀錄。")
        if notification.get("preview_destination") == "preview":
            lines.append(
                "使用預覽目的地；未套用真實 Chat 的送達紀錄。可用 --chat-id 指定去重範圍。"
            )
        for message in notification.get("messages", []):
            lines.append(f"\n--- 通知預覽 {message['job_id']} ({message['kind']}) ---")
            lines.append(message["text"])
    if "delivery" in notification:
        lines.append("發送摘要：" + json.dumps(notification["delivery"], ensure_ascii=False))
        lines.append("delivery_unknown 不會自動重送；請先查看 outbox 並到 Telegram 人工核對。")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    journal: Journal | None = None
    client: ApifyClient | None = None
    telegram: TelegramClient | None = None
    store: JobStore | None = None
    target: TelegramSettings | None = None
    secrets: list[str] = []
    stack = ExitStack()

    def output(text: str, *, error: bool = False) -> None:
        for secret in secrets:
            text = text.replace(secret, "[REDACTED]")
        _print(text, error=error)

    try:
        if args.command in {"outbox", "resolve-notification"}:
            store = JobStore(args.state_dir / "runs.sqlite3")
            if args.command == "resolve-notification":
                store.recover_stale_sending()
                row = store.get(args.id)
                if (
                    args.action == "retry"
                    and row["status"] == "delivery_unknown"
                    and not args.acknowledge_duplicate_risk
                ):
                    raise SettingsError(
                        "結果不明的通知可能已送達；核對後若仍要重送，需加 "
                        "--acknowledge-duplicate-risk。"
                    )
                store.resolve(args.id, action=args.action, message_id=args.message_id)
                output(json.dumps(store.get(args.id), ensure_ascii=False, indent=2))
            else:
                output(json.dumps(store.list_outbox(limit=100), ensure_ascii=False, indent=2))
            return 0
        if args.command == "runs":
            journal = Journal(args.state_dir / "runs.sqlite3")
            output(json.dumps(journal.list_runs(), ensure_ascii=False, indent=2))
            return 0
        profiles = load_profiles(args.profiles_dir)
        if args.command == "profiles":
            rows = [{"id": p.id, "name": p.name, "enabled": p.enabled} for p in profiles.values()]
            if args.format == "json":
                output(json.dumps(rows, ensure_ascii=False, indent=2))
            else:
                output(
                    "\n".join(
                        f"{p.id}: {p.name} [{'enabled' if p.enabled else 'disabled'}]"
                        for p in profiles.values()
                    )
                )
            return 0
        if args.command == "deliver":
            if not 1 <= args.limit <= 100:
                raise SettingsError("--limit 必須介於 1 與 100。")
            target = load_telegram_settings(args.env_file)
            secrets.append(target.token)
            store = JobStore(args.state_dir / "runs.sqlite3")
            if args.outbox_id:
                queued = store.get(args.outbox_id)
                if queued["mode"] != "live" or queued["destination_key"] != destination_key(
                    target.chat_id
                ):
                    raise SettingsError("指定通知不是此目的 Chat 的 live 通知，未發送。")
            telegram = TelegramClient(target.token)
            with profile_lock(args.state_dir, "delivery", destination_key(target.chat_id)):
                result = dispatch(
                    store,
                    telegram,
                    target.chat_id,
                    profiles,
                    limit=args.limit,
                    outbox_ids=[args.outbox_id] if args.outbox_id else None,
                )
            output(json.dumps(result, ensure_ascii=False, indent=2))
            return 2 if result["remaining"] else 0
        profile = profiles.get(args.profile)
        if profile is None:
            raise ProfileError("找不到指定 Profile；先執行 profiles 查看 ID。")
        if not profile.enabled:
            raise ProfileError("此 Profile 已停用。")
        fixture = getattr(args, "fixture", None)
        if fixture is not None and args.notify:
            raise SettingsError("fixture 是合成資料，禁止 --notify；請改用 --dry-run。")
        if args.chat_id is not None and not args.dry_run:
            raise SettingsError("--chat-id 僅用於 --dry-run；實際發送使用 .env 的 Chat ID。")
        preview_chat = normalize_chat_id(args.chat_id) if args.chat_id is not None else "preview"
        target = load_telegram_settings(args.env_file) if args.notify else None
        if target is not None:
            secrets.append(target.token)
        # Validate all live configuration before creating journals or starting paid work.
        settings = None if fixture is not None else load_live_settings(args.env_file)
        if settings is not None:
            secrets.append(settings.token)
        stack.enter_context(
            profile_lock(args.state_dir, "fixture" if fixture else "live", profile.id)
        )
        if fixture is not None:
            journal = Journal(args.state_dir / "runs.sqlite3")
            report = collect_fixture(profile, fixture, journal)
        else:
            assert settings is not None
            journal = Journal(args.state_dir / "runs.sqlite3")
            client = ApifyClient(settings.token)
            report = collect_live(
                profile,
                settings,
                journal,
                client,
                resume_run_id=getattr(args, "run_id", None),
                attempt_id=getattr(args, "attempt_id", None),
                wait_seconds=args.wait_seconds,
                progress=lambda line: output(line, error=True),
            )
        store = JobStore(args.state_dir / "runs.sqlite3")
        plan = store.record(
            report,
            profile_fingerprint=fingerprint(profile),
            chat_id=target.chat_id if target else (preview_chat if args.dry_run else None),
            enqueue=args.notify,
            preview=args.dry_run,
        )
        report.notifications = {
            "mode": "send" if args.notify else "dry_run" if args.dry_run else "not_requested",
            **asdict(plan),
        }
        if args.dry_run:
            report.notifications["preview_destination"] = (
                "preview" if preview_chat == "preview" else "specified_chat"
            )
        if target is not None:
            telegram = TelegramClient(target.token)
            job_ids = {
                job.source_url.rsplit("/", 1)[-1]
                for job in report.matched
                if job.source_job_id in report.notification_candidates
            }
            with profile_lock(args.state_dir, "delivery", destination_key(target.chat_id)):
                report.notifications["delivery"] = dispatch(
                    store,
                    telegram,
                    target.chat_id,
                    profiles,
                    job_ids=job_ids,
                    limit=args.notify_limit,
                )
        journal.finish(
            report.attempt_id,
            report.summary(),
            complete=report.dataset_complete and not report.invalid_count,
        )
        if args.format == "json":
            output(
                json.dumps(
                    report_payload(report, args.show_excluded), ensure_ascii=False, indent=2
                ),
            )
        else:
            output(render_report(report, args.show_excluded))
        remaining = report.notifications.get("delivery", {}).get("remaining", 0)
        return 0 if report.dataset_complete and not report.invalid_count and not remaining else 2
    except (
        SettingsError,
        ProfileError,
        CollectionError,
        JournalError,
        ApifyError,
        StoreError,
        TelegramError,
        ProfileBusyError,
    ) as error:
        output(f"錯誤 [{getattr(error, 'code', 'configuration')}]: {error}", error=True)
        return 2
    except (OSError, sqlite3.Error):
        output(
            "檔案／本機資料庫操作失敗。保留 run ID，不要重新啟動。"
            "若發送已開始，先核對 outbox／Telegram，不要盲目重送。",
            error=True,
        )
        return 2
    except KeyboardInterrupt:
        output(
            "已停止本機等待。遠端 run 可能繼續；使用 runs／resume 恢復，不要重新 POST。"
            "若正在發送，先查 outbox／Telegram 確認結果。",
            error=True,
        )
        return 130
    finally:
        if telegram is not None:
            telegram.close()
        if store is not None:
            store.close()
        if client is not None:
            client.close()
        if journal is not None:
            journal.close()
        stack.close()


def entrypoint() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())
