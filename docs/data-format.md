# Data format

Put the files in one folder and run `python -m changecal review <folder>`. Only `changes.csv` is required; every other file adds its checks when present. Comma, semicolon or tab separated, UTF-8. Column names are matched loosely (case, accents and punctuation are ignored), and the alternatives below are accepted, including the ServiceNow field names, common Jira Service Management export headers and common Spanish ones.

Values are read as the ServiceNow Table API returns them with `sysparm_display_value=true` (labels such as `Normal`, `Scheduled`, `2 - High`, `Successful with issues`, and the names of the CI, group and people), and the raw values are accepted too (`-2` for Scheduled, `2` for High risk). Dates as `yyyy-MM-dd HH:mm:ss`, ISO 8601 or `dd/mm/yyyy HH:mm`, in local time.

## How services, impact and collisions are worked out

| Step | Rule |
|---|---|
| Business services of a change | The change's `business_service`, plus every service its `cmdb_ci` belongs to in `ci-services.csv` |
| Tier | The lowest tier among those services (tier 1 is the most critical); 3 when unknown |
| Impacted services | The business services plus every service that depends on them, directly or through others (`service_depends_on`) |
| Night | The evening the change starts: 01:30 on Saturday belongs to Friday night (start − 6 hours) |
| Calendar | Changes not cancelled, not implemented yet, with a planned start from today 00:00 to `horizon_days` ahead |
| Collision | Planned windows overlap and the changes share a CI or a business service (COL-01), or an impacted service of tier `collision_max_tier` or above (COL-02) |
| Freeze | The window overlaps a freeze and the freeze is global or its scope includes one of the impacted services |
| History | Changes with a planned start in the last `trend_months` complete months; "last month" is the month before the reference date |

## changes.csv

ServiceNow `change_request` (Table API, `scripts/Export-ChangeData.ps1` writes it), or the change export of another tool. One row per change: the next weeks and the last months.

| Column | Also accepted | Notes |
|---|---|---|
| number | issue key, key, change id | |
| short_description | summary, title | |
| type | change type | `Standard`, `Normal`, `Emergency` |
| state | status | ServiceNow: New, Assess, Authorize, Scheduled, Implement, Review, Closed, Canceled (or -5 … 4). Jira: Planning, Awaiting approval, Awaiting implementation, Implementing, Completed, Declined, Canceled |
| risk | change risk | `1 - Very High` (or Critical), `2 - High`, `3 - Moderate` (or Medium), `4 - Low`; empty is "not assessed" |
| impact | | `1 - High`, `2 - Medium`, `3 - Low` |
| cmdb_ci | configuration item, ci | Joined with `ci-services.csv` (case ignored) |
| business_service | business service, affected services | |
| assignment_group, assigned_to | team, assignee | RDY-05 when empty |
| requested_by | reporter | Shown |
| opened_at | created, sys_created_on | With `start_date`, the lead time (RDY-03); after `work_start` is unauthorised (OUT-05) |
| start_date, end_date | planned start, planned end | The planned window |
| work_start, work_end | actual start, actual end | Overrun when `work_end` is later than `end_date` + `overrun_tolerance_minutes` (OUT-04) |
| approval | approval status | `Approved`, `Requested`, `Rejected`, `Not Yet Requested` |
| cab_date | | Shown in the readiness file |
| close_code | resolution, outcome | `Successful`, `Successful with issues` (both count as successful), `Unsuccessful` (also `Failed`, `Backed out`, `Rolled back`) |
| backout_plan, test_plan, implementation_plan | rollback plan, test plan | Empty, `N/A`, `TBD` or `to follow` is missing (RDY-01) |
| justification | reason | The emergency reasons (TYP-04) |
| outside_maintenance_schedule | | `true` is RDY-06 even inside the window of `settings.json` |
| review_status, review_date | pir status, pir date | The post-implementation review: `Complete`, `Completed`, `Done` or `Reviewed` is done |

## ci-services.csv (optional, strongly recommended)

The business service map from the CMDB: one row per CI and service (a CI can serve several services), with the service attributes repeated. A row with an empty `ci` only declares a service. From `cmdb_ci_service` and `cmdb_rel_ci` (relationship type `Depends on::Used by`, parent the service).

| Column | Also accepted | Notes |
|---|---|---|
| ci | cmdb_ci, child | The CI name as in the changes |
| ci_class | sys_class_name | Shown |
| service | business_service, parent | |
| service_tier | tier, business_criticality | `1 - most critical` … `4 - not critical`, or `Tier 1`; the first digit is used |
| service_owner | owner, support_group | Shown |
| service_depends_on | depends_on, upstream | Services this one depends on, separated by `;` |

Without this file, only the `business_service` of each change is known and collisions are found by CI and service only.

## freezes.csv (optional)

The freeze and blackout register: month-end and quarter-end close, trading-critical dates (index rebalances, expiries), year-end, office moves.

| Column | Also accepted | Notes |
|---|---|---|
| name | freeze, title | |
| kind | type | `freeze`: only emergency changes (and standard ones if `freeze_allows_standard`) or an approved exception. `blackout`: no change at all, critical even for emergencies |
| start, end | from, to | |
| scope | services | Business services separated by `;`. Empty, `global` or `all` is every service |
| approved_exceptions | exceptions | Change numbers allowed inside the freeze (COL-05 for information) |
| reason | description | Shown in the pack |

## incidents.csv (optional)

ServiceNow `incident`, opened in the last months.

| Column | Also accepted | Notes |
|---|---|---|
| number, short_description | | |
| priority | | `1 - Critical` … `5 - Planning` |
| opened_at, resolved_at | created, resolved | |
| cmdb_ci, business_service | configuration item, service | For the suspected link |
| assignment_group | | Shown |
| caused_by | caused by change, related change | The 'Caused by Change' reference: a **linked** incident (OUT-03) |

A P1 or P2 (`suspected_max_priority`) with no `caused_by`, opened within `incident_window_hours` after a change finished on the same CI or on one of its impacted services, is **suspected**: confirm or rule out.

## approvals.csv (optional)

ServiceNow `sysapproval_approver` for change requests: one row per approver.

| Column | Also accepted | Notes |
|---|---|---|
| sysapproval | change, number | The change number |
| approver | approved by | |
| state | status | `Approved`, `Requested`, `Rejected`, `Not Required` |
| sys_updated_on | approved on, date | When the approval was given |

The time of the last approval of a normal change is compared with `work_start` (approved after the work started is OUT-05), and an emergency change needs one within `retro_approval_days` of the end of the work (TYP-03). Without this file the `approval` field of the change is used.

## settings.json

| Key | Default | What |
|---|---|---|
| `organisation`, `as_of` | | Name for the reports; reference date (otherwise now) |
| `horizon_days` | 14 | Days in the calendar |
| `cab_weekday`, `cab_time` | tue, 10:00 | The weekly CAB: a normal change not approved that starts before it is RDY-04 critical |
| `lead_time_days` | normal: very high 10, high 10, moderate 5, low 3, not assessed 5 | Minimum days between `opened_at` and `start_date`, by type and risk |
| `plans_required` | normal: backout, test, implementation; emergency: backout, implementation; standard: none | RDY-01 |
| `maintenance_windows` | none (any time) | By tier: `[{"days": ["mon", …], "start": "22:00", "end": "06:00"}]`. An end at or before the start runs into the next day; an end past 24:00 (`"42:00"`) runs further. A tier with no windows has no restriction |
| `max_changes_per_team_night` | 3 | COL-03 |
| `collision_max_tier` | 2 | Shared impacted services of this tier or more critical are a collision |
| `freeze_allows_emergency`, `freeze_allows_standard` | true, false | What a freeze lets through without an exception |
| `incident_window_hours`, `suspected_max_priority` | 24, 2 | Suspected change-caused incidents |
| `pir_due_days`, `pir_required_for` | 5; unsuccessful, successful_issues, emergency, incident | When a PIR is needed and how long after the end of the work |
| `overrun_tolerance_minutes` | 30 | OUT-04 |
| `retro_approval_days` | 2 | TYP-03 |
| `success_target`, `emergency_share_max` | 0.95, 0.10 | OUT-01, TYP-01 |
| `team_success_min`, `team_emergency_share_max`, `team_min_changes` | 0.80, 0.20, 5 | TEAM-01, TEAM-02 |
| `standard_risky_match` | firmware, upgrade, migrat, replace, re-platform | A standard change whose description matches, on a tier 1 or 2 service, is TYP-02 (also any standard change with high risk) |
| `trend_months` | 3 | Complete months of history |
| `teams` | | Assignment groups to list even with no changes |
| `owners` | | Owner per area: readiness, collisions, types, outcomes, teams |
