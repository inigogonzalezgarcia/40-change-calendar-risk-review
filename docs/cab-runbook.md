# CAB runbook

Two meetings run on the same outputs: the **weekly CAB** (45 minutes, the next two weeks and last week's outcomes) and the **monthly change review** (45 minutes, last month by team, with the team leads). The tool only reads exports; decisions are recorded in the ITSM tool as usual.

## Before the CAB (Monday, 30 minutes)

1. Export ServiceNow (read-only):
   ```powershell
   .\scripts\Export-ChangeData.ps1 -Instance contoso -OutputFolder .\data
   ```
   The user needs read access to `change_request`, `incident`, `sysapproval_approver`, `cmdb_ci_service` and `cmdb_rel_ci`. Another tool: export the same columns (see [data-format.md](data-format.md)).
2. Update `freezes.csv` with the freezes and blackout windows of the coming weeks and the exceptions approved since last week.
3. Check `settings.json`: `as_of`, the CAB day and time, the lead times and the maintenance windows by tier.
4. Build the outputs:
   ```bash
   python -m changecal review data/ --title "Change calendar and CAB review · week of 2 November 2026"
   ```
5. Send `cab-pack.md` with the agenda and `report.html` to the CAB members the day before. Ask the owners of every change with a gap (section 4 of the pack) to fix it before the meeting or to come to explain it.

## Weekly CAB (45 minutes)

| Minutes | Topic | From the pack (`cab-pack.md`) | Who |
|---|---|---|---|
| 5 | Overall status, last week's outcomes: unsuccessful, overruns, incidents after a change | Headlines, 6 | Change manager |
| 20 | Changes to approve, by start: risk, tier, plans, lead time, collisions, freeze. Decide: approve, approve with conditions, reschedule, reject | 1, 4 | Change owners, technical approvers |
| 10 | Collisions: which change moves; team nights with too many changes; changes inside a freeze and the exceptions requested | 2, 3 | Change manager, service owners |
| 5 | Standard and emergency: standard changes used for risky work, emergency changes to approve retrospectively | 5 | Change manager |
| 5 | PIRs overdue and due this week: owner and date | 8 | Change owners |

Record each decision in the change (approval, conditions, new dates) and in the *Decisions of the CAB* line of the pack. A change that starts before the next CAB and is not approved today does not go ahead unless the ECAB approves it.

## Monthly change review (first week of the month, 45 minutes)

| Minutes | Topic | From the pack and the CSVs |
|---|---|---|
| 10 | Success rate by month, unsuccessful changes and what they had in common (testing, environment, backout, timing) | 7, `outcomes.csv` |
| 10 | Incidents after changes: confirm the suspected links, PIR findings, actions | 7, `outcomes.csv` |
| 10 | Teams: success rate, emergency share and its reasons; problem records for repeated emergencies | 9, 5, `teams.csv` |
| 5 | Unauthorised changes and late approvals: what happened and how to stop it | 7 |
| 10 | Process: lead times, windows, standard change templates to review or retire, thresholds in `settings.json` | Findings, actions |

Keep each week's output folder (pack, CSVs and exports) as evidence of the CAB for audits.

## Freezes and exceptions

- Put every freeze in `freezes.csv` before it starts, with its scope: the business services that must not change (month-end close: the ledger, payments and the trading platform; an index rebalance: the trading platform and market data).
- A change that must run inside a freeze needs an exception approved by the business owner of the affected services, with the reason, the risk and the backout; add the change number to `approved_exceptions`.
- A blackout (an office move, a regulatory deadline) allows nothing, not even emergencies: anything inside is critical.
- Remember the dependencies: a change on the storage or the core network affects the trading platform even if it is not named in the change.

## How to read it

- **A collision is two backout plans for one symptom.** If two changes on the same path go wrong the same night, nobody knows which one to roll back.
- **The impact is through the dependencies.** The firewall and the core switches do not belong to the trading platform, but the trading platform stops when they do.
- **Lead time is time for others to look.** A high-risk change raised two days before its window has had no technical review, no CAB and no time to test the backout.
- **A standard change is pre-approved because it is boring.** A firmware upgrade on the storage of tier 1 services is not boring; the template should not allow it.
- **Emergency share is a symptom.** Repeated emergencies for the same reason are a problem record; planned work raised as emergency is a planning problem.
- **Success rate needs the incidents.** A change closed as successful that is followed by a P1 two hours later is not a success; link it and review it.
- **No PIR, no learning.** Unsuccessful changes, emergencies and changes followed by incidents get a review within days, not months.
- **A team with low success needs help, not blame.** Look at its test environments, its windows and its backout plans first.
