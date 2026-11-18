# 歷史參考：原多來源完整版規格

> 2026-09-23 因使用者縮小 MVP 範圍而保留於此。下方是原規格內容，不是目前開發或驗收依據。
> 目前規格：[SEEK-only MVP](../../NZ_WORKING_HOLIDAY_JOB_RADAR_SPEC.md)；開發順序：[Roadmap](../../MVP_ROADMAP.md)。
> 原文的 Trade Me、官方滑雪場監測、Dashboard、舊 kickoff prompt 與多來源驗收要求，均不得直接用於目前 MVP。

---

# NZ Working Holiday Job Radar — Project Specification

> Status: implementation-ready draft  
> Audience: Codex coding session / solo developer  
> Last verified: 2026-09-22  
> Product principle: **Coverage + Freshness + Explainable WHV filtering + Useful notifications**

## 1. Product summary

Build a small, personal tool that regularly collects New Zealand job listings, normalizes them into one schema, identifies new or materially changed jobs, estimates whether each listing is compatible with a Taiwan Working Holiday Visa (WHV), and sends concise alerts.

The tool is deliberately focused on short-term New Zealand working-holiday work. It is separate from any future long-term career-intelligence product.

Initial use cases:

1. New Zealand ski-field and winter-season jobs around Queenstown, Wānaka, and Methven.
2. Entry-level cafe service, counter, kitchen-hand, and front-of-house jobs in Auckland that do not primarily require coffee-making skills.

Optional profiles should support other short-term service jobs, initially dessert/bakery shops and vehicle-rental companies, without changing application code when the jobs are available through an existing source.

The tool must not claim that a job is legally eligible with certainty. It should show the evidence used, identify conflicts, and tell the user what to confirm with the employer.

## 2. Goals

- Avoid missing newly posted jobs across several New Zealand sources.
- Search by reusable, editable profiles instead of hard-coded queries.
- Normalize results from SEEK NZ, Trade Me Jobs, and official ski-resort career pages.
- Apply Taiwan-WHV-specific rules, especially the same-employer three-month limit and the prohibition on permanent work.
- Label every job with an explainable suitability result: likely suitable, needs confirmation, or likely incompatible as advertised.
- Detect new, changed, expired, and reposted listings without sending duplicate alerts.
- Provide a lightweight Explore view for reviewing the current market.
- Keep the system inexpensive, understandable, and maintainable by one person.
- Preserve raw source evidence so parsing and classification decisions can be audited.

## 3. Non-goals

- Automatically applying for jobs or submitting personal data.
- Logging into job sites with the user's account or bypassing anti-bot controls.
- Providing legal or immigration advice.
- Guaranteeing that a listing or employer will accept a Taiwan WHV holder.
- Building a general global job-search platform.
- Resume tailoring, deep skill-gap analysis, role clustering, or AI career coaching in the MVP.
- Replacing the user's own record of time already worked for an employer.
- Recording, calculating, or warning about cumulative time the user has personally worked for the same employer.
- Scraping at high volume or redistributing job-board content.
- Building native mobile apps in the MVP.

## 4. Target users

### Primary user

A Taiwan passport holder planning or undertaking a New Zealand working holiday who wants timely, focused alerts for short-term jobs.

### User needs

- See which jobs are newly available.
- Know where the job is, what type it is, and when it starts.
- Know whether the advertised duration appears to fit the three-month same-employer limit.
- See whether the job is permanent, casual, temporary, seasonal, contract, or fixed-term.
- Know whether WHV holders or temporary work rights are explicitly accepted.
- See practical details such as pay, hours, experience, staff transport, and accommodation.
- Open the original listing quickly and decide whether to apply.

## 5. Core scenarios

### 5.1 Ski-field jobs

The user wants to monitor NZSki, Cardrona, Treble Cone, and relevant SEEK/Trade Me listings for roles such as:

- Lift operator / lift attendant
- Guest services
- Rentals, retail, and workshop assistant
- Food and beverage attendant
- Kitchen hand
- Housekeeping or cleaning
- Snow-sports support roles
- Seasonal transport or resort operations

Important fields:

- Resort and employer
- Mountain/base location
- Recruitment open/close dates
- Expected start and end dates
- Advertised season or contract duration
- Staff transport
- Staff accommodation or housing guidance
- Required certification or experience
- Work-right or visa wording

Key rule: a full winter season may exceed three months. The word `seasonal` alone must never produce a green result.

### 5.2 Auckland entry-level cafe and front-of-house jobs

The user wants to monitor jobs matching terms such as:

- Cafe assistant
- Front of house / FOH
- Food and beverage attendant
- Counter staff
- Kitchen hand
- Dishwasher

Important fields:

- Auckland area or suburb
- Casual, part-time, temporary, contract, or fixed-term status
- Weekly hours and roster expectations
- Pay range
- Immediate-start wording
- Minimum commitment
- Customer-service, food-handling, and entry-level experience requirements
- Whether coffee-making or prior barista experience is mandatory
- Visa/work-right wording

The system must search ordinary cafe-service terms, not only `working holiday visa`, because suitable jobs may never mention WHV explicitly. Do not actively search for `barista`, `coffee maker`, or `cafe all-rounder`. Exclude titles centered on those roles, while retaining broader front-of-house jobs that merely mention coffee as a minor or trainable duty.

### 5.3 Dessert, bakery, and sweet-shop jobs

This is an optional profile built from the same SEEK and Trade Me adapters. Useful search terms include:

- Bakery assistant
- Pastry assistant
- Cake decorator
- Dessert cafe
- Gelato / ice cream shop
- Kitchen hand
- Counter staff
- Front of house

Important fields remain the same as cafe jobs: location, employment type, hours, pay, minimum commitment, experience, and visa/work-right wording. The profile should include several specific job terms instead of relying on the broad word `dessert`, which may create unrelated results.

### 5.4 Vehicle-rental company jobs

This is another optional profile that can reuse SEEK and Trade Me collection. Useful search terms include:

- Vehicle rental agent
- Rental car customer service
- Vehicle groomer / car groomer
- Fleet assistant
- Branch assistant
- Shuttle driver
- Customer service representative

Useful locations include Auckland, Auckland Airport, Queenstown, Christchurch, and other arrival hubs chosen by the user. The profile may also include an employer allowlist when the user wants to follow specific rental companies.

Configuration boundary:

- If the jobs are listed on an already-supported source such as SEEK or Trade Me, adding these areas is a YAML profile change only.
- If the user wants to monitor a rental company's or dessert shop's own careers page, add a configured change-detection watch when possible.
- A new source adapter is required only when the direct careers site exposes a new page/API/ATS structure that existing generic monitoring cannot normalize reliably.

## 6. WHV rule baseline and disclaimer

The official Immigration New Zealand Taiwan Working Holiday Visa page currently states that a holder may:

- work in temporary jobs;
- work for any one employer for up to three months; and
- not take a permanent job.

Official source: [Immigration New Zealand — Taiwan Working Holiday Visa](https://www.immigration.govt.nz/visas/taiwan-working-holiday-visa/)

Implementation rules:

- Store the rule source URL and `verified_at` date in configuration.
- Show a dashboard warning when the rule verification date is older than 90 days.
- Treat **three months as a calendar-duration rule**, not automatically as 90 days.
- A listing-level result only evaluates the advertised job. It cannot account for previous time the user has already worked for the same employer.
- When dates, employer identity, or contract length are unclear, label the job `needs_confirmation`.
- Every eligibility display must include: `Informational screening only — confirm current visa conditions and contract terms.`

## 7. Data sources and acquisition policy

| Source | MVP role | Preferred method | Fallback | Notes |
|---|---|---|---|---|
| SEEK NZ | Broad coverage for required and optional profiles | Apify SEEK Scraper adapter | Approved alternative adapter | Use incremental output when available; do not make the whole application depend on one vendor. |
| Trade Me Jobs | Additional NZ coverage | Trade Me API-compatible adapter | Trade Me MCP reference implementation | Confirm credentials, API terms, and permitted usage before enabling live collection. |
| NZSki careers | Coronet Peak, The Remarkables, Mt Hutt | Official jobs endpoint or structured page parser | Change-detection watch that triggers a targeted rescan | Preserve recruitment-page evidence. |
| Cardrona / Treble Cone careers | Wānaka-area seasonal jobs | Official employment/ATS endpoint or structured page parser | Change-detection watch that triggers a targeted rescan | The employer/ATS URL may change; discover it from the official landing page. |

Source policy:

- Prefer official APIs, feeds, public structured endpoints, or authorized third-party services.
- Respect each site's terms, robots guidance, rate limits, and content-retention restrictions.
- Do not evade CAPTCHAs, authentication, access controls, or blocking.
- Use clear user-agent identification where permitted.
- Rate-limit each source independently and add exponential backoff with jitter.
- A source failure must not erase prior jobs or mark all jobs expired.
- Store only the content needed for personal search, deduplication, and explainable filtering.

Official entry points:

- [SEEK New Zealand](https://www.seek.co.nz/)
- [Trade Me Jobs](https://www.trademe.co.nz/a/jobs/search)
- [NZSki Employment](https://www.nzski.com/employment)
- [Cardrona / Treble Cone Employment](https://cardrona-treblecone.com/employment)
- [RealNZ Careers](https://www.realnz.com/en/careers/)

## 8. Architecture

```text
Search Profiles
    |
    v
Scheduler / Run Orchestrator
    |
    +--> SEEK adapter -----------+
    +--> Trade Me adapter -------+--> Raw observations
    +--> Ski careers adapters ---+          |
                                           v
                                      Normalize
                                           |
                                           v
                                  Deduplicate / Version
                                           |
                         +-----------------+------------------+
                         |                                    |
                         v                                    v
                 WHV eligibility engine               Incremental diff
                         |                                    |
                         +-----------------+------------------+
                                           |
                                           v
                                      SQLite store
                                      /          \
                                     v            v
                             Explore dashboard   Notification outbox
                                                      |
                                                      v
                                              Telegram / console
```

Design boundaries:

- `adapters` know how to communicate with sources.
- `normalization` converts source payloads into the canonical schema.
- `eligibility` is deterministic, evidence-based, and independently testable.
- `deduplication` and `monitoring` own identity, versions, and state transitions.
- `notifications` read from an outbox and are idempotent.
- `dashboard` reads the database and never runs scrapers inside a page request.

## 9. Source adapter contract

Every adapter implements the same conceptual interface:

```python
class JobSourceAdapter(Protocol):
    source_name: str

    async def fetch(
        self,
        profile: SearchProfile,
        checkpoint: SourceCheckpoint | None,
    ) -> FetchResult:
        """Return raw jobs, next checkpoint, timing, and source-health metadata."""
```

`FetchResult` must contain:

- `run_id`
- `source`
- `profile_id`
- `started_at` and `finished_at`
- `status`: `success`, `partial`, or `failed`
- `raw_jobs`
- `next_checkpoint`
- `request_count`
- `warning_messages`
- `error_code` and sanitized error details

Adapter requirements:

- Accept one search profile and its source-specific settings.
- Support pagination and a configurable result cap.
- Return zero results as a valid success only when the upstream response was complete and valid.
- Retain source job ID, canonical URL, and raw payload or permitted raw excerpt.
- Never write directly to normalized job tables.
- Provide fixture-based tests that require no live network access.
- Expose a live smoke-test command that is disabled in normal automated tests.

### 9.1 SEEK/Apify adapter contract

The SEEK adapter uses [Black Falcon Data's SEEK Job Scraper on Apify](https://apify.com/blackfalcondata/seek-scraper). Pricing and schema details below were verified on 2026-09-22 and must be rechecked before deployment.

Recommended Actor behavior:

- Always send `country: "NZ"`; the Actor defaults to Australia.
- Batch the keywords belonging to one profile into a single Actor run. The API field `query` is a string; multiple terms must be sent as a JSON-encoded list string, not as a raw array.
- Use `sortMode: "date"` for monitoring.
- Keep `includeDetails: true`, `compact: false`, and `descriptionFormat: "text"` because WHV classification needs the full description and screening questions.
- Set `includeApplicantInsights: false` in MVP. Applicant-demand data is not needed for WHV eligibility and is unavailable for some external-apply jobs.
- Set `incrementalMode: true` and use a stable, explicit, versioned `stateKey` per profile, for example `nz-whv-auckland-cafe-service-v2`.
- Keep `skipReposts: false`; retain repost evidence and let the local system decide whether to notify.
- Set `emitExpired: true` if the local system needs disappearance signals, but interpret them cautiously.
- Do not use Actor-direct Telegram/Slack/Discord delivery for final user alerts. The listing must pass through normalization, local deduplication, and WHV eligibility first.
- Do not store extracted email addresses, phone numbers, or social profiles by default. They are unnecessary for this personal job-search MVP and create additional privacy obligations.

Recommended Auckland entry-level cafe-service input sent through the API:

```json
{
  "query": "[\"cafe assistant\",\"front of house\",\"food and beverage attendant\",\"counter staff\",\"kitchen hand\"]",
  "country": "NZ",
  "location": "Auckland",
  "sortMode": "date",
  "maxResults": 200,
  "includeDetails": true,
  "includeApplicantInsights": false,
  "descriptionFormat": "text",
  "compact": false,
  "incrementalMode": true,
  "stateKey": "nz-whv-auckland-cafe-service-v2",
  "emitUnchanged": false,
  "emitExpired": true,
  "skipReposts": false
}
```

Do not use a short rolling `dateRange` by default. A job can leave a seven-day or one-day window while still being open, which makes disappearance unsuitable as proof of real expiry.

Actor-to-canonical mapping:

| Actor field | Canonical use |
|---|---|
| `seekJobId` | Preferred SEEK source identity |
| `jobId` | Actor-generated stable identity/fallback |
| `canonicalUrl`, `sourceUrl`, `applyUrl` | Canonical/source/application links |
| `advertiserId`, `company` | Employer identity and alias matching |
| `location*` | Country, region, suburb, postcode normalization |
| `employmentType`, `workArrangement` | Employment and remote/onsite classification |
| `salary*` | Structured NZD pay fields |
| `postedDate`, `validThrough` | Posting and advertised-validity dates |
| `description`, `bulletPoints`, `screeningQuestions` | WHV evidence extraction |
| `contentHash`, `trackedHash` | Source change hints; keep a local independent hash too |
| `changeType` | Source event hint: `NEW`, `UPDATED`, `UNCHANGED`, `REAPPEARED`, `EXPIRED` |
| `firstSeenAt`, `lastSeenAt` | Actor observation timestamps |
| `isRepost`, `repostOfId`, `repostDetectedAt` | Repost evidence |

Incremental-state rules:

- The Actor's `stateKey` is upstream state; the local database remains the system of record across all sources.
- Changing auto-derived search inputs can create a different state universe. Use explicit keys and deliberately increment the suffix when profile semantics materially change.
- `maxPages` defines how much of a search is tracked. A job outside that window is not reliably monitored for expiry.
- Treat Actor `EXPIRED` as `left_actor_tracking_universe` until the local system confirms closure through `validThrough`, the detail page, or repeated complete observations.
- The Actor's generic webhook performs a single attempt with a 15-second timeout. If used, the endpoint must authenticate, persist/enqueue quickly, and return; it must not run the whole pipeline synchronously. Dataset retrieval through the Apify API remains the recovery path.

## 10. Canonical job schema

The normalized model should cover these fields. Optional values are `null`, not omitted.

```yaml
Job:
  id: uuid
  source: seek_nz | trademe_jobs | nzski | cardrona_treblecone | other
  source_job_id: string | null
  source_url: string
  canonical_url: string
  title: string
  title_normalized: string
  employer: string | null
  employer_normalized: string | null
  resort: string | null
  description_text: string | null
  description_hash: string | null

  location_text: string | null
  city: string | null
  region: string | null
  country_code: NZ
  remote_type: onsite | hybrid | remote | unknown

  employment_type:
    - casual
    - temporary
    - fixed_term
    - contract
    - seasonal
    - part_time
    - full_time
    - permanent
    - unknown
  hours_min_per_week: number | null
  hours_max_per_week: number | null
  salary_min: number | null
  salary_max: number | null
  salary_currency: NZD | null
  salary_period: hour | day | week | year | unknown | null

  posted_at: datetime | null
  closes_at: datetime | null
  expected_start_date: date | null
  expected_end_date: date | null
  duration_value: number | null
  duration_unit: day | week | calendar_month | season | unknown | null
  duration_precision: exact | approximate | inferred | unknown

  working_holiday_mentioned: boolean | null
  work_rights_text: string | null
  permanent_conflict: boolean
  minimum_commitment_text: string | null
  accommodation_status: provided | available | assistance | not_provided | unknown
  staff_transport_status: provided | available | not_provided | unknown
  experience_text: string | null

  eligibility_label: likely_suitable | needs_confirmation | likely_incompatible
  eligibility_score: integer 0..100
  eligibility_confidence: high | medium | low
  eligibility_reasons: list[string]
  eligibility_evidence: list[Evidence]

  first_seen_at: datetime
  last_seen_at: datetime
  last_changed_at: datetime
  status: active | expired | removed | unknown
  content_hash: string
  raw_observation_id: uuid
```

```yaml
Evidence:
  rule_code: string
  field: string
  excerpt: string
  source_url: string
  extraction_method: structured | regex | parser | manual
```

Supporting tables:

- `search_profiles`
- `source_runs`
- `source_checkpoints`
- `raw_observations`
- `jobs`
- `job_versions`
- `job_profile_matches`
- `notification_outbox`
- `notification_deliveries`
- `employer_aliases`
- `user_job_states` (`saved`, `applied`, `dismissed`, notes)

## 11. Search profiles

Profiles live in version-controlled YAML. Secrets and credentials must not be stored there.

### 11.1 Auckland entry-level cafe-service profile

```yaml
id: auckland-cafe-service
name: Auckland Entry-Level Cafe Service
enabled: true
locations:
  include:
    - Auckland
keywords:
  any:
    - cafe assistant
    - front of house
    - FOH
    - food and beverage attendant
    - counter staff
    - kitchen hand
    - dishwasher
  exclude_title:
    - barista
    - coffee maker
    - cafe all-rounder
    - head barista
sources:
  seek_nz:
    enabled: true
    max_results: 200
  trademe_jobs:
    enabled: true
    max_results: 200
preferences:
  employment_types:
    - casual
    - temporary
    - fixed_term
    - contract
    - part_time
notification:
  minimum_label: needs_confirmation
  mode: immediate
```

### 11.2 Ski-field profile

```yaml
id: nz-ski-fields
name: New Zealand Ski Fields
enabled: true
locations:
  include:
    - Queenstown
    - Wanaka
    - Wānaka
    - Methven
    - Otago
    - Canterbury
keywords:
  any:
    - lift operator
    - lift attendant
    - guest services
    - rentals
    - retail
    - food and beverage
    - kitchen hand
    - housekeeping
    - seasonal
  exclude: []
employers:
  include:
    - NZSki
    - Coronet Peak
    - The Remarkables
    - Mt Hutt
    - Cardrona
    - Treble Cone
sources:
  seek_nz:
    enabled: true
  trademe_jobs:
    enabled: true
  nzski:
    enabled: true
  cardrona_treblecone:
    enabled: true
notification:
  minimum_label: needs_confirmation
  mode: immediate
```

### 11.3 Dessert and bakery profile

This optional template reuses existing adapters and is disabled until needed.

```yaml
id: auckland-dessert-bakery
name: Auckland Dessert and Bakery Jobs
enabled: false
locations:
  include:
    - Auckland
keywords:
  any:
    - bakery assistant
    - pastry assistant
    - cake decorator
    - dessert cafe
    - gelato
    - ice cream shop
    - kitchen hand
    - counter staff
  exclude: []
  exclude_title:
    - barista
    - coffee maker
    - cafe all-rounder
sources:
  seek_nz:
    enabled: true
    max_results: 100
  trademe_jobs:
    enabled: true
    max_results: 100
notification:
  minimum_label: needs_confirmation
  mode: immediate
```

### 11.4 Vehicle-rental profile

This optional template also reuses existing adapters. Locations and employer names are user-editable.

```yaml
id: nz-vehicle-rental
name: New Zealand Vehicle Rental Jobs
enabled: false
locations:
  include:
    - Auckland
    - Auckland Airport
    - Queenstown
    - Christchurch
keywords:
  any:
    - vehicle rental agent
    - rental car customer service
    - vehicle groomer
    - car groomer
    - fleet assistant
    - branch assistant
    - shuttle driver
employers:
  include: []
sources:
  seek_nz:
    enabled: true
    max_results: 100
  trademe_jobs:
    enabled: true
    max_results: 100
notification:
  minimum_label: needs_confirmation
  mode: immediate
```

Profile behavior:

- Query terms may be split into multiple source requests.
- A job matches a profile if it passes location/source rules and at least one include term or employer rule.
- `exclude_title` is applied locally after collection and rejects jobs whose normalized title contains one of the listed phrases. It must not remove a broader front-of-house role merely because its description mentions coffee.
- Do not remove permanent or long-duration jobs during ingestion; retain them and show why they are incompatible.
- Source-specific query syntax stays inside adapter configuration.

## 12. WHV eligibility engine

### 12.1 Principles

- Deterministic rules first; no LLM is required for MVP scoring.
- Keep the score, label, confidence, reasons, and quoted evidence separate.
- A preference such as accommodation must not improve legal suitability.
- `seasonal`, `part_time`, and `full_time` do not prove that a job fits the three-month limit.
- Unknown duration or ambiguous employer identity prevents a green label.

### 12.2 Signals

Positive signals:

- Explicitly accepts working-holiday visa holders.
- Explicitly temporary, casual, fixed-term, or contract.
- Exact start/end dates fit within three calendar months.
- Explicit contract duration is three calendar months or less.
- Explicitly says short-term and gives a compatible duration.

Conflict signals:

- Permanent position.
- Minimum commitment longer than three calendar months.
- Advertised fixed term or season longer than three calendar months with the same employer.
- Requires a status that excludes the user's current work rights, such as NZ citizenship/residency only.
- Wording explicitly rejects temporary visa holders.

Uncertain signals:

- Seasonal role with no exact duration.
- Casual or part-time role with no end date or commitment information.
- Employer omitted or inconsistent across sources.
- Only generic wording such as `must have the right to work in New Zealand`.
- Dates extracted from promotional page text rather than the specific vacancy.

### 12.3 Suggested score

Start at `0`, cap to `0..100`:

| Rule | Score |
|---|---:|
| Explicit WHV acceptance | +30 |
| Temporary/casual/fixed-term/contract classification | +25 |
| Explicit duration of three calendar months or less | +35 |
| Specific non-permanent start/end dates are present | +10 |
| Permanent role | -70 and hard conflict |
| Explicit duration or minimum commitment over three calendar months | -60 and hard conflict |
| Explicit visa/work-right exclusion | -70 and hard conflict |

Label resolution:

```text
if hard_conflict:
    likely_incompatible
else if score >= 70 and compatible duration is explicit:
    likely_suitable
else:
    needs_confirmation
```

Confidence:

- `high`: structured employment type plus explicit dates/duration or direct visa statement.
- `medium`: clear job-description wording but no structured duration.
- `low`: inferred from title/snippet or generic source-page text.

Required reason examples:

- `Fixed-term dates appear to fit within three calendar months.`
- `Casual role, but the minimum commitment is not stated.`
- `Advertised winter season appears longer than three months.`
- `Permanent work conflicts with the current Taiwan WHV conditions.`
- `Working-holiday visa holders are explicitly mentioned.`

### 12.4 Duration calculation

- When exact dates exist, compare `end_date` with `start_date + 3 calendar months`.
- Preserve inclusivity assumptions and flag exact-boundary cases for confirmation.
- Never convert `3 months` to a fixed 90-day constant.
- If only a season name or month range is known, record it as inferred and avoid green status unless a specific compatible duration is also present.

### 12.5 Scope boundary

The eligibility engine evaluates only the job advertisement currently being reviewed. It does not record employment history, combine prior work periods, or calculate the user's cumulative time with an employer. That responsibility remains outside this product and is not planned for a later phase.

## 13. Deduplication and identity

Apply identity rules in order:

1. Exact `(source, source_job_id)` match.
2. Exact normalized canonical URL match.
3. Exact source-provided content identity or stable listing ID embedded in the URL.
4. Conservative cross-source fingerprint using normalized employer, normalized title, city/region, and compatible posting dates.
5. Optional near-duplicate candidate using token similarity; do not auto-merge low-confidence matches.

Fingerprint inputs must exclude volatile fields such as `scraped_at`, tracking parameters, and display formatting.

Behavior:

- One canonical job may have multiple source listings.
- Preserve all source URLs and observations.
- A description or date change creates a `job_version`, not a new job.
- A new source ID with the same strong cross-source fingerprint may be marked `reposted`; retain both observations.
- When uncertain, keep separate jobs and expose a possible-duplicate flag.

## 14. Incremental monitoring

Each successful source/profile run compares current normalized observations with stored state.

Events:

- `new`: first confirmed observation of a canonical job.
- `updated`: material fields changed.
- `eligibility_changed`: label or reasons changed.
- `reposted`: likely same role published under a new source identity.
- `expired`: source explicitly closes it or it is absent for a configured number of successful complete runs.
- `source_recovered`: a previously failing adapter succeeds again.

Material fields:

- title, employer, location;
- employment type;
- pay;
- start/end dates or duration;
- work-right wording;
- accommodation/transport;
- closing date;
- description hash when the text change is meaningful.

Safety rules:

- Do not expire jobs after failed or partial source runs.
- Default inferred expiry threshold: missing from three consecutive complete runs, configurable per source.
- Write run results and job state in one transaction where practical.
- Use a unique event/idempotency key such as `job_id:event_type:job_version`.
- Preserve the last successful checkpoint until the next run commits successfully.

## 15. Notification design

### MVP channels

- Telegram bot: primary.
- Console/log sink: required for development and tests.
- Email or Discord: later adapters using the same outbox contract.

### Trigger policy

- Notify immediately for a new job matching an enabled profile.
- Notify on updates only when eligibility, closing date, duration, pay, location, or accommodation changes materially.
- Do not notify again for cosmetic description changes.
- Never send the same idempotency key twice to the same channel.
- Allow per-profile minimum labels and optional quiet hours.
- Offer a daily digest mode after MVP.

### Message example

```text
🔔 New job — Auckland Entry-Level Cafe Service

Front of House Assistant | Example Cafe
Auckland CBD · Casual · NZ$25–28/hour
🟡 Taiwan WHV: Needs confirmation
Reason: Casual role, but contract duration is not stated.
Ask: Can the contract be limited to no more than 3 months?

Posted: 22 Sep 2026
Source: SEEK NZ
Open: https://...
```

Ski example:

```text
⚠️ New ski-field job

Food & Beverage Attendant | Example Resort
Queenstown · Winter seasonal
🔴 Taiwan WHV: Likely incompatible as advertised
Reason: Advertised dates span more than 3 calendar months.
Possible next step: Ask whether a shorter fixed-term contract is available.

Open: https://...
```

## 16. Data storage

### MVP

- SQLite with WAL mode.
- SQLAlchemy 2.x or SQLModel models.
- Alembic migrations from the first schema change.
- UTC timestamps in storage; render local time using `Pacific/Auckland` by default.
- JSON columns/text for source metadata and evidence when relational querying is not needed.

### Retention

- Canonical job metadata: retain while the project is active.
- Job versions and notification delivery records: retain for audit and deduplication.
- Raw payloads: configurable retention, default 90 days, subject to source terms.
- Secrets: environment variables or local secret store only; never committed.

### Upgrade path

Move to PostgreSQL only if hosted concurrency, multiple users, or much larger history makes SQLite limiting. The domain layer must not depend on SQLite-specific query behavior.

## 17. Scheduling and operations

### 17.1 Suggested schedule

Suggested default schedule:

| Source/profile | Frequency | Notes |
|---|---:|---|
| SEEK NZ | Every 2–4 hours | Prefer the Apify scheduler/webhook or application scheduler, not both. |
| Trade Me Jobs | Every 2–4 hours | Stay within API limits. |
| Official ski career pages | Every 6 hours normally; every 1–2 hours during recruitment opening | Use change detection to trigger targeted rescans if useful. |
| Eligibility-rule freshness check | Weekly | Warn when the official rule has not been manually verified in 90 days. |
| Daily health digest | Daily | Only failures, stale sources, and job counts; optional for MVP. |

Begin with daily SEEK runs during development and inactive job-search periods. Increase to every four hours only while actively applying or during a known seasonal recruitment window. Every two hours is an opt-in high-frequency mode, not the default.

### 17.2 Apify billing model

The Actor page currently lists pay-per-event pricing:

- Actor start: **US$0.01 per run**.
- Emitted result: **US$0.002 per job record**.
- The first incremental run emits the full baseline.
- Later incremental runs normally emit only `NEW`, `UPDATED`, and `REAPPEARED`; enabling `emitExpired` can add expired/disappearance records.
- The page currently advertises a US$5 monthly Apify platform credit. Treat this as a credit, not as a product guarantee; verify eligibility and whether other Actors consume it.

Gross cost formulas, before credits, tax, and currency conversion:

```text
run_count = active_profiles × checks_per_day × 30

later_month_cost =
    (run_count × $0.01)
    + (monthly_emitted_change_records × $0.002)

first_month_cost =
    (run_count × $0.01)
    + (initial_baseline_records × $0.002)
    + (change_records_after_the_baseline × $0.002)
```

Frequency mainly changes the run-start component. With incremental mode, the variable component depends primarily on how many jobs are actually emitted as new, updated, reappeared, or expired.

### 17.3 Verified single-profile examples

The following reproduces the Actor page's examples for one profile tracking 200 jobs, checked daily for 30 days:

| Daily changed share | Changed records/day | Later month | First month including baseline |
|---:|---:|---:|---:|
| 5% | 10 | US$0.90 | US$1.28 |
| 15% | 30 | US$2.10 | US$2.44 |
| 30% | 60 | US$3.90 | US$4.18 |

Example for the 5% case:

```text
Later month:
30 starts × $0.01                     = $0.30
300 emitted changes × $0.002          = $0.60
Total                                 = $0.90

First month:
30 starts × $0.01                     = $0.30
200-record baseline × $0.002          = $0.40
29 days × 10 changes × $0.002         = $0.58
Total                                 = $1.28
```

### 17.4 Project budget estimates

These are planning estimates, not a promise of actual result volume.

Assumptions:

- Every profile is scheduled separately so it has an independent `stateKey` and run history.
- All keywords inside one profile are batched into one Actor run.
- Two-profile baseline: 200 Auckland entry-level cafe-service jobs + 100 ski jobs = 300 records.
- Four-profile baseline: the two required profiles plus 100 dessert/bakery and 100 vehicle-rental jobs = 500 records.
- Medium four-profile activity: 40 emitted changes per day across all profiles.
- High four-profile activity: 80 emitted changes per day across all profiles.

| Plan | Active profiles | Frequency | Runs/month | Baseline | Changes/month | First month | Later month |
|---|---:|---:|---:|---:|---:|---:|---:|
| Lean trial | 2 | Daily | 60 | 300 | 600 | **US$2.36** | **US$1.80** |
| Four-profile daily | 4 | Daily | 120 | 500 | 1,200 | **US$4.52** | **US$3.60** |
| Recommended active search | 4 | Every 4 hours | 720 | 500 | 1,200 | **US$10.59** | **US$9.60** |
| High-frequency / high activity | 4 | Every 2 hours | 1,440 | 500 | 2,400 | **US$20.19** | **US$19.20** |

How the recommended later-month estimate is calculated:

```text
4 profiles × 6 runs/day × 30 days = 720 starts
720 × $0.01                        = $7.20
1,200 changed records × $0.002     = $2.40
Gross monthly total                = $9.60
```

If the advertised US$5 monthly credit fully applies and is unused elsewhere, the recommended plan's effective Actor charge would be approximately **US$4.60 after the baseline month** and **US$5.59 in the first month**. Always budget using the gross figure because credits and pricing can change.

Recommended budget policy:

- Development/inactive period: two to four profiles once daily; expected gross Actor cost roughly **US$2–4 per month** under the assumptions above.
- Active applications: four profiles every four hours; reserve **US$10–12 per month gross**.
- Do not use two-hour monitoring unless faster alerts have demonstrated value; reserve **US$20–25 per month gross**.
- Configure a monthly budget alert at US$5 for daily mode and US$12 for recommended four-hour mode.
- Log per-profile runs, emitted records, and estimated cost so the dashboard can compare actual spend with budget.
- Recalculate from actual `source_runs` after the first seven days instead of continuing to rely on assumed change rates.

### 17.5 Operational choices

Operational choices:

- Use one scheduler of record to avoid duplicate runs.
- MVP may use APScheduler inside a single always-on worker, or platform cron calling a CLI command.
- GitHub Actions is acceptable for low-frequency experiments but must not be assumed perfectly punctual.
- Lock by `(source, profile_id)` so overlapping runs cannot race.
- Record duration, counts, error category, and last success for every adapter.
- Display New Zealand time and optionally Taiwan time in the dashboard.

## 18. Dashboard / Explore mode

The dashboard is a practical review surface, not an analytics product.

### Required views

1. **Jobs** — searchable, filterable table/cards.
2. **New since last visit** — jobs first seen after the user's last review marker.
3. **Needs confirmation** — unresolved duration or work-right cases.
4. **Source health** — last success, last error, results, and next scheduled run.

### Filters

- Search profile
- Source
- Location
- Employer/resort
- Employment type
- Eligibility label
- First-seen date
- Accommodation status
- Active/expired status

### Job detail

- Original listing link
- Normalized fields
- Suitability label, score, confidence, reasons, and evidence excerpts
- First seen / last seen / last changed
- Version history
- Source links when several listings map to one canonical job
- Personal state: saved, applied, dismissed, note

### Deferred analytics

- Role and employer counts
- Recruitment timing by source
- Typical pay/hours
- Skill frequency
- Employer response or application tracking

## 19. MVP scope

MVP is complete when it provides an end-to-end vertical slice for the two required scenarios while proving that additional SEEK/Trade Me job families can be added through configuration.

Included:

- Repository scaffold, configuration, migrations, and local setup.
- Two enabled built-in search profiles: Auckland entry-level cafe service and NZ ski fields.
- Two disabled example profiles: dessert/bakery jobs and vehicle-rental jobs.
- SEEK NZ adapter through the configured Apify Actor.
- Trade Me Jobs adapter when valid API access is available; otherwise a fixture-complete disabled adapter with a clear setup requirement.
- NZSki and Cardrona/Treble Cone official-career-page adapters.
- Canonical normalization and raw observation storage.
- Deterministic Taiwan WHV suitability rules with evidence.
- Conservative deduplication and new/updated/expired state handling.
- Telegram and console notifications with an outbox.
- Lightweight server-rendered Explore dashboard.
- Manual CLI commands and scheduled run command.
- Unit, integration-fixture, and live-smoke test layers.
- Setup, operations, and source-limit documentation.
- Per-profile Apify cost estimation from actual run and emitted-record counts.

Explicitly deferred:

- LLM extraction or scoring.
- Native app or browser extension.
- Multi-user accounts.
- Automatic application submission.
- Broad NZ employer coverage beyond configured sources.

## 20. Phased roadmap

### Phase 0 — Feasibility spikes

- Confirm each source's allowed access method, schema, rate limits, and credentials.
- Capture one representative fixture per source.
- Verify current employment/ATS URLs for NZSki and Cardrona/Treble Cone.
- Decide whether the Apify SEEK adapter's incremental mode or local diff is the source of truth. Keep local diff regardless for auditability.
- Document any license restrictions before copying code from reference repositories.

Exit: every source has an adapter decision and a saved fixture, or is explicitly marked blocked/disabled.

### Phase 1 — SEEK vertical slice

- Scaffold Python project, settings, models, and migrations.
- Implement Auckland profile.
- Fetch and normalize SEEK data.
- Implement eligibility engine, deduplication, SQLite storage, and console notification.
- Add unit and fixture integration tests.

Exit: one command produces stored, labeled, deduplicated Auckland entry-level cafe-service jobs.

### Phase 2 — Monitoring and notifications

- Add checkpoints, run state, versioning, and event generation.
- Add notification outbox and Telegram delivery.
- Add ski profile.
- Verify notification idempotency and failure retries.

Exit: repeated runs notify once for new jobs and only for material updates thereafter.

### Phase 3 — Multi-source coverage

- Add Trade Me adapter.
- Add NZSki and Cardrona/Treble Cone adapters.
- Add cross-source deduplication and source health.
- Add change-detection triggers only where they improve official-career-page reliability.

Exit: the ski profile produces combined results without losing source evidence.

### Phase 4 — Explore dashboard and operations

- Add filters, job detail, reasons/evidence, and user states.
- Add scheduler, locks, health checks, retention, backup, and recovery documentation.
- Add rule-freshness warning.

Exit: the tool can run unattended and failures are visible without corrupting job state.

### Phase 5 — Optional enhancements

- Daily digest and more notification channels.
- More seasonal employers and direct ATS adapters.
- Rule-based extraction improvements, then optional LLM fallback for ambiguous descriptions.
- Simple market summaries and recruitment-calendar insights.

## 21. Suggested technology stack

### Recommended default

- Python 3.12+
- FastAPI for health/API endpoints
- Jinja2 + HTMX for the lightweight dashboard
- Pydantic v2 for settings and schemas
- SQLAlchemy 2.x + Alembic
- SQLite in WAL mode
- `httpx` for HTTP clients
- Beautiful Soup or `selectolax` for permitted static HTML parsing
- Playwright only for official pages that require JavaScript and permit automated access
- APScheduler or external cron as the single scheduler
- `python-telegram-bot` or direct Telegram Bot API client
- `structlog` or standard structured JSON logging
- `pytest`, `pytest-asyncio`, `respx`, and fixture snapshots
- Ruff and mypy/pyright for quality checks

Why this stack:

- Python suits data ingestion, parsing, date handling, and quick personal-tool development.
- Server-rendered HTML avoids a separate frontend build during MVP.
- SQLite keeps deployment simple while preserving a clean upgrade path.
- Deterministic parsing and scoring remain easy to test.

## 22. Suggested repository layout

```text
nz-whv-job-radar/
├─ README.md
├─ pyproject.toml
├─ .env.example
├─ alembic.ini
├─ migrations/
├─ profiles/
│  ├─ auckland-cafe-service.yaml
│  ├─ nz-ski-fields.yaml
│  ├─ auckland-dessert-bakery.yaml
│  └─ nz-vehicle-rental.yaml
├─ src/nz_job_radar/
│  ├─ config.py
│  ├─ cli.py
│  ├─ db/
│  ├─ domain/
│  │  ├─ models.py
│  │  ├─ events.py
│  │  └─ enums.py
│  ├─ adapters/
│  │  ├─ base.py
│  │  ├─ seek_apify.py
│  │  ├─ trademe.py
│  │  ├─ nzski.py
│  │  └─ cardrona_treblecone.py
│  ├─ normalization/
│  ├─ eligibility/
│  ├─ deduplication/
│  ├─ monitoring/
│  ├─ notifications/
│  ├─ scheduler/
│  └─ web/
├─ tests/
│  ├─ fixtures/
│  ├─ unit/
│  ├─ integration/
│  └─ smoke/
└─ docs/
   ├─ source-access.md
   ├─ operations.md
   └─ whv-rule-review.md
```

## 23. Implementation task list

### Foundation

- [ ] Create project scaffold, dependency groups, lint/type/test commands.
- [ ] Add `.env.example` without secrets.
- [ ] Implement typed settings and profile loading with validation.
- [ ] Define domain enums and canonical schemas.
- [ ] Add SQLite engine, migrations, and transaction helpers.

### Sources

- [ ] Define adapter interface and `FetchResult`.
- [ ] Implement SEEK/Apify adapter with versioned `stateKey`, pagination, incremental events, retries, dataset recovery, and fixtures.
- [ ] Map Actor fields and statuses without treating Actor `EXPIRED` as confirmed closure.
- [ ] Batch all keywords within a profile into one Actor run and record its run/dataset IDs.
- [ ] Implement Trade Me adapter with an explicit disabled state when credentials are missing.
- [ ] Implement NZSki official career adapter.
- [ ] Implement Cardrona/Treble Cone official career/ATS adapter.
- [ ] Add per-source rate limits and sanitized structured errors.
- [ ] Add live-smoke commands that do not run in normal tests.

### Normalization and identity

- [ ] Normalize titles, employer names, locations, job types, pay, and URLs.
- [ ] Implement local `exclude_title` filtering after normalization, independently of broad description keyword matching.
- [ ] Extract dates, duration, work-right wording, accommodation, and transport evidence.
- [ ] Compute content hashes and conservative fingerprints.
- [ ] Implement exact and cross-source deduplication.
- [ ] Store raw observations and canonical job versions.

### WHV eligibility

- [ ] Implement the deterministic score and label resolver.
- [ ] Implement calendar-month duration comparison.
- [ ] Preserve evidence excerpts and extraction methods.
- [ ] Add rule-source metadata and stale-verification warning.
- [ ] Cover permanent, over-three-month, seasonal-unknown, casual-unknown, and explicit-WHV cases with tests.

### Monitoring

- [ ] Store source runs and checkpoints.
- [ ] Generate new, updated, eligibility-changed, reposted, and expired events.
- [ ] Prevent failed/partial runs from causing expiry.
- [ ] Add `(source, profile)` run locking.
- [ ] Add source-health queries.

### Notifications

- [ ] Implement transactional outbox creation.
- [ ] Implement console sink.
- [ ] Implement Telegram sink and retries.
- [ ] Add per-channel idempotency and delivery records.
- [ ] Render clear labels, reasons, confirmation questions, and original links.

### Dashboard and operations

- [ ] Add Jobs, New, Needs confirmation, and Source health views.
- [ ] Add filters and job detail evidence/version views.
- [ ] Add saved/applied/dismissed state and notes.
- [ ] Add scheduled CLI entry point and documented deployment option.
- [ ] Add backup, restore, retention, and troubleshooting docs.
- [ ] Add health endpoint and non-secret diagnostics.
- [ ] Show Apify runs, emitted records, gross estimated cost, credit-adjusted estimate, and monthly budget threshold.
- [ ] Reforecast the monthly budget from the first seven days of actual run data.
- [ ] Unit-test the cost formula against every example in section 17; display credits separately from gross cost.

## 24. Acceptance criteria

### Functional

- [ ] A user can edit YAML profiles without changing application code.
- [ ] The Auckland cafe-service profile does not query coffee-making roles and rejects titles centered on barista, coffee maker, cafe all-rounder, or head barista.
- [ ] A front-of-house listing is not rejected solely because its description says coffee training is available or mentions coffee as a minor duty.
- [ ] Enabling the dessert/bakery or vehicle-rental example profile requires no application-code change when using SEEK or Trade Me.
- [ ] A manual run can execute one profile, one source, or all enabled sources.
- [ ] Each enabled adapter returns normalized jobs or a recorded, understandable failure.
- [ ] Repeating the same successful fixture run creates no duplicate canonical jobs or notifications.
- [ ] A changed duration or employment type creates a new version and recalculates eligibility.
- [ ] Failed or partial fetches never mass-expire existing jobs.
- [ ] Jobs from different sources can be conservatively linked while preserving every source URL.
- [ ] New qualifying jobs create one outbox event and one Telegram delivery at most.
- [ ] The dashboard filters by profile, source, location, employment type, and eligibility label.
- [ ] The original job page is reachable from every displayed job.
- [ ] Each SEEK profile uses an independent, explicit, versioned Actor `stateKey`.
- [ ] The application records the Actor run ID, dataset ID, emitted record count, and calculated gross cost.
- [ ] The cost estimator reproduces the section 17 examples to the nearest cent and never silently subtracts promotional credit from gross cost.
- [ ] Changing a profile's tracking universe requires a deliberate `stateKey` version change or migration decision.

### WHV-specific

- [ ] A permanent role is labeled `likely_incompatible` with a permanent-work reason.
- [ ] A job explicitly longer than three calendar months is labeled `likely_incompatible`.
- [ ] A seasonal job with unknown dates is labeled `needs_confirmation`, never green.
- [ ] A casual role with unknown duration is labeled `needs_confirmation`.
- [ ] A non-permanent job with explicit compatible dates and sufficient evidence can be labeled `likely_suitable`.
- [ ] Exact-boundary date cases are calculated with calendar months and surface the assumption.
- [ ] Every label displays reasons, evidence, confidence, disclaimer, and rule verification date.

### Reliability and security

- [ ] Credentials and tokens are never logged, stored in fixtures, or committed.
- [ ] Source retries are bounded and respect rate limits.
- [ ] Notification delivery is retryable and idempotent.
- [ ] Database migrations work on a fresh database and on the previous schema version.
- [ ] Fixture-based tests run without network access.
- [ ] Live smoke tests are opt-in and report the source, query, result count, and sanitized failure.
- [ ] A documented backup can be restored into a fresh local environment.
- [ ] Actor `EXPIRED` events cannot directly expire a local job without local confirmation rules.
- [ ] Extracted contact details are discarded unless a later, explicitly approved feature needs them.
- [ ] The generic Actor webhook is not the only recovery path for completed run data.

### Quality gate

- [ ] Formatting, linting, type checks, unit tests, and integration-fixture tests pass.
- [ ] README contains setup, first run, scheduler, Telegram configuration, and troubleshooting.
- [ ] Source access methods and terms/limits assumptions are documented.
- [ ] No claim of live success is made unless a live smoke run was actually performed.

## 25. Key risks and mitigations

| Risk | Mitigation |
|---|---|
| Source markup/API changes | Isolate adapters, retain fixtures, monitor zero-result anomalies, keep source health visible. |
| Anti-bot or access restrictions | Prefer authorized APIs/services; do not bypass controls; disable source cleanly. |
| False green WHV result | Require explicit compatible duration for green; show evidence and disclaimer. |
| Full ski season exceeds three months | Extract exact dates; red-label explicit over-limit contracts; ask about shorter contracts. |
| Duplicate alerts | Canonical identity, versioned events, transactional outbox, per-channel idempotency. |
| Source outage causes false expiry | Expire only after complete successful runs and a configurable absence threshold. |
| Vendor lock-in to Apify | Stable internal adapter contract and local normalized history. |
| Unexpected Apify cost | Batch per-profile queries, start daily, store actual emitted counts, set budget alerts, and reforecast after seven days. |
| False expiry from rolling window or page cap | Avoid short `dateRange`; size `maxPages` deliberately; treat Actor `EXPIRED` only as a disappearance hint. |
| Old immigration rule | Store source and verification date; show stale-rule warning; manually recheck. |
| Ambiguous employer identity | Normalize conservatively; retain aliases and require confirmation when uncertain. |

## 26. Reference projects and links mentioned in the planning conversation

These are references, not automatic dependencies. Inspect current license, maintenance status, security, and source terms before reusing code.

### Directly relevant

- [BlackFalconData-org/seek-scraper](https://github.com/BlackFalconData-org/seek-scraper) — SEEK AU/NZ scraper and incremental-tracking reference.
- [Apify SEEK Scraper Actor](https://apify.com/blackfalcondata/seek-scraper) — hosted execution, scheduler, datasets, API, and webhook path.
- [Apify SEEK Scraper Input Schema](https://apify.com/blackfalcondata/seek-scraper/input-schema) — current input types, tracking controls, notification fields, and limits.
- [Apify SEEK Scraper Python API](https://apify.com/blackfalcondata/seek-scraper/api/python) — official client invocation and dataset retrieval example.
- [giussepe198/trademe-mcp](https://github.com/giussepe198/trademe-mcp) — Trade Me API/MCP wrapper with job search support.
- [dgtlmoon/changedetection.io](https://github.com/dgtlmoon/changedetection.io) — generic page-change monitoring and notifications.
- [GEOFAIRY/Seek-Job-Scraper](https://github.com/GEOFAIRY/Seek-Job-Scraper) — older SEEK monitoring concept reference.

### Broader job-radar references

- [ScottCoffin/Job_Scraper](https://github.com/ScottCoffin/Job_Scraper) — scheduled job watching, deduplication, dashboard, and notifications.
- [speedyapply/JobSpy](https://github.com/speedyapply/JobSpy) — multi-board collection reference (the older Bunsly URL now redirects here); not a required NZ source.
- [TheDevRo/Jobsmith](https://github.com/TheDevRo/Jobsmith) — broader job aggregation/application assistant reference; outside MVP scope.

### Official references

- [Immigration New Zealand — Taiwan Working Holiday Visa](https://www.immigration.govt.nz/visas/taiwan-working-holiday-visa/)
- [SEEK New Zealand](https://www.seek.co.nz/)
- [Trade Me Jobs](https://www.trademe.co.nz/a/jobs/search)
- [NZSki Employment](https://www.nzski.com/employment)
- [Cardrona / Treble Cone Employment](https://cardrona-treblecone.com/employment)
- [RealNZ Careers](https://www.realnz.com/en/careers/)

## 27. Codex kickoff prompt

Copy the following prompt into a new Codex coding session together with this specification file:

```text
Build the NZ Working Holiday Job Radar described in NZ_WORKING_HOLIDAY_JOB_RADAR_SPEC.md.

Start by reading the entire specification. Treat it as the product baseline, but verify the current repository state and do not assume any live source works until tested.

For this first session:

1. Inspect the workspace and report any existing files or constraints.
2. Create a short implementation plan mapped to Phase 0 and Phase 1.
3. Confirm the allowed access method, credentials, terms/limits, and representative response shape for each planned source. Do not bypass authentication, CAPTCHAs, anti-bot controls, or rate limits.
4. Scaffold the Python project and implement the Phase 1 SEEK vertical slice:
   - typed configuration and YAML profile loading;
   - canonical job/domain schemas;
   - SQLite + Alembic persistence;
   - source adapter interface;
   - SEEK/Apify adapter using fixtures first;
   - normalization;
   - deterministic Taiwan-WHV eligibility rules with evidence;
   - exact deduplication and job versioning;
   - console notification;
   - unit and fixture integration tests.
5. Add the enabled Auckland entry-level cafe-service and NZ ski-field profiles, plus disabled dessert/bakery and vehicle-rental examples. Do not actively search for coffee-making roles; reject job titles centered on barista, coffee maker, cafe all-rounder, or head barista. Existing SEEK/Trade Me job families must be addable by YAML without application-code changes.
6. Use calendar-month arithmetic for the three-month rule. Never label seasonal or unknown-duration work as likely suitable merely because it is casual, part-time, or seasonal.
7. Keep every suitability result explainable: label, score, confidence, reasons, evidence excerpt, source URL, disclaimer, and rule verification date.
8. Keep secrets out of the repository. Provide .env.example and clear setup instructions.
9. Do not add LLM scoring, auto-apply features, a SPA frontend, or unrelated career-intelligence features.
10. Record Actor run ID, dataset ID, emitted-record count, and estimated gross cost. Treat Actor EXPIRED as a disappearance hint, not confirmed closure.
11. Run formatting, linting, type checks, unit tests, and fixture integration tests. Report exactly what was verified and what still requires credentials or live source access.

Before changing direction or expanding scope, explain the tradeoff and ask for approval. Prefer the smallest end-to-end implementation that satisfies the Phase 1 acceptance criteria.
```
