"""Outputs: report.html (with the two-week calendar by day and service), cab-pack.md (the agenda and pack for this week's CAB and the monthly
change review), and the CSVs: the calendar, collisions, readiness, outcomes, teams, actions and findings."""
from __future__ import annotations

import csv
import html
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

from .checks import (AREAS, CRITICAL, INFO, VERDICT, WARNING, Finding, _n, area_status, dependents, night, now_label, overall, pct, summary)
from .model import FILES, Data, month_key

e = html.escape


# ---------------------------------------------------------------- csv

def _w(path: Path, header: list[str], rows: list[list]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(header)
        w.writerows(rows)


def _t(v) -> str:
    if not v:
        return ""
    return v.strftime("%Y-%m-%d %H:%M") if isinstance(v, datetime) else v.strftime("%Y-%m-%d")


def _iss(issues) -> str:
    return " | ".join(f"{i.code} {i.text}" for i in issues)


def write_findings(findings: list[Finding], path: Path) -> None:
    _w(path, ["severity", "area", "code", "subject", "detail", "next_step", "owner", "items"],
       [[f.severity, f.area, f.code, f.subject, f.detail, f.fix, f.owner, "; ".join(f.items)] for f in findings])


def write_actions(findings: list[Finding], path: Path) -> None:
    _w(path, ["ref", "action", "next_step", "owner", "severity", "due", "done"],
       [[f.code, f.subject, f.fix, f.owner, f.severity, "", ""] for f in findings if f.severity != INFO])


def per_change(rv: dict) -> dict[str, list]:
    """change number -> every issue that names it (readiness, collisions, freeze, type)."""
    out = defaultdict(list)
    for r in rv["readiness"]:
        out[r["item"].c.number] += r["issues"]
    for r in rv["pairs"]:
        out[r["a"].c.number] += r["issues"]
        out[r["b"].c.number] += r["issues"]
    for r in rv["load"]:
        for it in r["items"]:
            out[it.c.number] += r["issues"]
    for r in rv["freeze"] + rv["types"]["standard"]:
        out[r["item"].c.number] += r["issues"]
    return out


def _sev(issues) -> str | None:
    s = {i.severity for i in issues}
    return CRITICAL if CRITICAL in s else WARNING if WARNING in s else None


def write_calendar(d: Data, rv: dict, path: Path) -> None:
    pc = per_change(rv)
    partners = defaultdict(list)
    for r in rv["pairs"]:
        partners[r["a"].c.number].append(r["b"].c.number)
        partners[r["b"].c.number].append(r["a"].c.number)
    fz = defaultdict(list)
    for r in rv["freeze"]:
        fz[r["item"].c.number].append(r["freeze"].name + (" (exception)" if not r["severity"] else ""))
    rows = []
    for it in rv["upcoming"]:
        c = it.c
        iss = pc.get(c.number, [])
        rows.append([c.number, c.short_description, c.type, c.state, c.risk, c.impact or "", c.approval, c.ci, "; ".join(it.services), it.tier,
                     "; ".join(it.impacted), c.group, c.assigned_to, _t(c.start), _t(c.end), _t(night(c.start)), "; ".join(fz[c.number]),
                     "; ".join(partners[c.number]), VERDICT[_sev(iss)], _iss(iss)])
    _w(path, ["number", "short_description", "type", "state", "risk", "impact", "approval", "cmdb_ci", "business_services", "tier", "impacted_services",
              "assignment_group", "assigned_to", "start", "end", "night", "freeze", "collides_with", "verdict", "issues"], rows)


def write_collisions(d: Data, rv: dict, path: Path) -> None:
    rows = []
    for r in rv["pairs"]:
        a, b = r["a"].c, r["b"].c
        rows.append([r["issues"][0].code, f"{a.number}; {b.number}", f"{a.group}; {b.group}", r["on"], _t(max(a.start, b.start)), _t(min(a.end, b.end)),
                     "", r["verdict"], _iss(r["issues"])])
    for r in rv["load"]:
        xs = r["items"]
        rows.append(["COL-03", "; ".join(x.c.number for x in xs), r["team"], _t(r["night"]), _t(min(x.c.start for x in xs)), _t(max(x.c.end for x in xs)),
                     "", r["verdict"], _iss(r["issues"])])
    for r in rv["freeze"]:
        c = r["item"].c
        rows.append([r["issues"][0].code, c.number, c.group, "; ".join(r["item"].services), _t(c.start), _t(c.end), r["freeze"].name, r["verdict"],
                     _iss(r["issues"])])
    _w(path, ["check", "changes", "groups", "on", "from", "to", "freeze", "verdict", "issues"], rows)


def write_readiness(d: Data, rv: dict, path: Path) -> None:
    rows = []
    for r in rv["readiness"]:
        c, it = r["item"].c, r["item"]
        got = round((c.start - c.opened).total_seconds() / 86400, 1) if c.opened else ""
        rows.append([c.number, c.short_description, c.type, c.state, c.risk or "not assessed", c.impact or "", it.tier, "; ".join(it.services), c.group,
                     _t(c.opened), _t(c.start), got, r["lead"] or "", c.approval, _t(c.cab_date), "no" if "backout plan" in r["missing"] else "yes",
                     "no" if "test plan" in r["missing"] else "yes", "no" if "implementation plan" in r["missing"] else "yes",
                     "no" if any(i.code == "RDY-06" for i in r["issues"]) else "yes", r["verdict"], _iss(r["issues"])])
    _w(path, ["number", "short_description", "type", "state", "risk", "impact", "tier", "business_services", "assignment_group", "opened", "start",
              "lead_days", "lead_required", "approval", "cab_date", "backout_plan", "test_plan", "implementation_plan", "in_window", "verdict",
              "issues"], rows)


def write_outcomes(d: Data, rv: dict, path: Path) -> None:
    rows = []
    for r in rv["outcomes"]["rows"]:
        c = r["item"].c
        rows.append([c.number, c.short_description, r["month"], c.type, c.group, c.ci, "; ".join(r["item"].services), _t(c.start), _t(c.end),
                     _t(c.work_start), _t(c.work_end), c.close_code, "" if r["overrun"] is None else r["overrun"],
                     "; ".join(f"{x['inc'].number} P{x['inc'].priority} ({x['how']})" for x in r["incidents"]), "; ".join(r["pir_need"]),
                     _t(r["pir_due"]), c.review_status, r["verdict"], _iss(r["issues"])])
    _w(path, ["number", "short_description", "month", "type", "assignment_group", "cmdb_ci", "business_services", "start", "end", "work_start", "work_end",
              "close_code", "overrun_minutes", "incidents", "pir_required", "pir_due", "review_status", "verdict", "issues"], rows)


def write_teams(d: Data, rv: dict, path: Path) -> None:
    months = rv["outcomes"]["months"]
    _w(path, ["team", "changes", "closed", "successful_share", "unsuccessful", "emergency", "emergency_share"] + [f"emergency_share_{m}" for m in months]
       + ["upcoming", "verdict", "issues"],
       [[r["team"], r["changes"], r["closed"], "" if r["rate"] is None else f"{r['rate']:.3f}", r["failed"], r["emergency"], f"{r['share']:.3f}"]
        + ["" if x is None else f"{x:.3f}" for x in r["monthly"]] + [r["upcoming"], r["verdict"], _iss(r["issues"])] for r in rv["teams"]])


# ---------------------------------------------------------------- the pack

TODO = "**[TO COMPLETE]**"


def _short(issues, c=None, skip=("RDY-04",)) -> str:
    pre = f"{c.number} {c.short_description}: " if c else ""
    return "; ".join(f"{i.code} {i.text[len(pre):] if pre and i.text.startswith(pre) else i.text}" for i in issues
                     if i.code not in skip).replace("|", "/") or "–"


def pack_md(d: Data, rv: dict, findings: list[Finding], title: str) -> str:
    s, sm, st = d.settings, summary(d, rv), area_status(findings)
    pc = per_change(rv)
    o = rv["outcomes"]
    out = [f"# {title}", "",
           f"> Generated by changecal on {now_label(d.as_of)} from the exports listed under *Scope and evidence*. Read-only: nothing was changed in "
           f"the ITSM tool. Sections marked {TODO} are for the change manager before the CAB.", "",
           f"**Overall: {overall(findings).upper()}**", "", "| Area | Status | To act on |", "|---|---|---|"]
    for a in AREAS:
        n = sum(f.area == a and f.severity != INFO for f in findings)
        out.append(f"| {a} | {'ON TRACK' if st[a] == 'ok' else VERDICT[st[a]].upper()} | {n} |")
    rates = ", ".join(f"{m} {pct(r)}" for m, r in zip(sm["months"], sm["rates"]))
    out += ["", "## Headlines", "",
            f"- Next {s.horizon_days} days: {sm['upcoming']} changes ({sm['normal']} normal, {sm['standard']} standard, {sm['emergency']} emergency), "
            f"{sm['tier1']} on tier 1 services; {sm['ready']} ready, {sm['not_ready']} with something to fix; {sm['to_approve']} waiting for approval.",
            f"- Collisions: {_n(sm['pairs'], 'overlapping pair')} ({sm['pairs_critical']} on tier 1 or the same CI), {_n(sm['overloaded'], 'team night')} "
            f"over {s.max_changes_per_team_night} changes, {_n(sm['in_freeze'], 'change')} inside a freeze without exception, "
            f"{sm['freeze_exceptions']} with an exception or allowed.",
            f"- Last month ({sm['last']}): {sm['changes_last']} changes, {pct(sm['rate_last'])} successful (target {pct(s.success_target)}), "
            f"{sm['failed_last']} unsuccessful, {sm['emergency_last']} emergency ({pct(sm['emergency_share'])}).",
            f"- Incidents after changes since {sm['last']}: {sm['incidents']} ({sm['incidents_linked']} linked, {sm['p1']} P1); overruns {sm['overruns']}, "
            f"unauthorised {sm['unauthorised']}, PIRs overdue {sm['pir_overdue']}.",
            f"- Standard changes used for risky work: {sm['standard_risky']}; emergency changes without approval: {sm['emergency_unapproved']}.",
            f"- Success rate by month: {rates}; teams flagged: {', '.join(sm['teams_flagged']) or 'none'}.", "",
            "## Scope and evidence", "", f"- Organisation: {s.organisation}", f"- Reference date: {d.as_of:%a %d %b %Y %H:%M}",
            f"- CAB: {rv['cab']:%a %d %b %Y %H:%M}; calendar {rv['horizon'][0]:%d %b} to {rv['horizon'][1] - timedelta(days=1):%d %b}", "",
            "| Source | File | Records |", "|---|---|---|"]
    out += [f"| {FILES.get(k, k)} | `{k}` | {v} |" for k, v in d.sources.items()]
    # 1 approve
    agenda = [r for r in rv["readiness"] if any(i.code == "RDY-04" for i in r["issues"])]
    out += ["", f"## 1. Changes to approve at the CAB of {rv['cab']:%a %d %b}", "",
            "Normal and emergency changes in the calendar not approved yet, by start. Gaps are the readiness, collision and freeze checks.", "",
            "| Change | Description | Risk | Tier | Start | Group | Gaps | Decision |", "|---|---|---|---|---|---|---|---|"]
    for r in agenda:
        c, it = r["item"].c, r["item"]
        out.append(f"| {c.number} | {c.short_description} | {c.risk or 'not assessed'} | {it.tier} | {c.start:%a %d %b %H:%M} | {c.group or '–'} | "
                   f"{_short(pc[c.number], c)} | {TODO} |")
    # 2 collisions
    out += ["", "## 2. Collisions to resolve", "", "| Check | Changes | On | Detail | Status |", "|---|---|---|---|---|"]
    for r in rv["pairs"]:
        out.append(f"| {r['issues'][0].code} | {r['a'].c.number}, {r['b'].c.number} | {r['on']} | {r['issues'][0].text} | {r['verdict'].upper()} |")
    for r in rv["load"]:
        out.append(f"| COL-03 | {', '.join(x.c.number for x in r['items'])} | {r['team']} | {r['issues'][0].text} | {r['verdict'].upper()} |")
    if not rv["pairs"] and not rv["load"]:
        out.append("| – | none | | | |")
    # 3 freezes
    out += ["", "## 3. Freezes and blackout windows", "", "| Freeze | From | To | Scope | Approved exceptions |", "|---|---|---|---|---|"]
    for f in sorted(d.freezes, key=lambda f: f.start or datetime.min):
        if f.end and f.end < rv["horizon"][0] - timedelta(days=7):
            continue
        out.append(f"| {f.name} ({f.kind}) | {_t(f.start)} | {_t(f.end)} | {', '.join(f.scope) or 'every service'} | {', '.join(f.exceptions) or '–'} |")
    out += ["", "| Change | Freeze | Status | Detail |", "|---|---|---|---|"]
    for r in rv["freeze"]:
        out.append(f"| {r['item'].c.number} | {r['freeze'].name} | {'OK' if not r['severity'] else r['verdict'].upper()} | {r['issues'][0].text} |")
    # 4 not ready
    out += ["", "## 4. Readiness gaps in the calendar", "", "| Change | Description | Type | Start | Gaps |", "|---|---|---|---|---|"]
    for r in rv["readiness"]:
        if any(i.severity != INFO for i in r["issues"]):
            c = r["item"].c
            out.append(f"| {c.number} | {c.short_description} | {c.type} | {c.start:%a %d %b %H:%M} | {_short(r['issues'], c)} |")
    # 5 types
    ty = rv["types"]
    out += ["", "## 5. Standard and emergency changes", "",
            "Emergency share by month: " + ", ".join(f"{m} {pct(x)}" for m, x in zip(o["months"], ty["shares"])) + f" (max {pct(s.emergency_share_max)}).", ""]
    if ty["reasons"]:
        out += [f"Emergency reasons in {sm['last']}:", ""] + [f"- {k} ({v})" for k, v in ty["reasons"].most_common()] + [""]
    for r in ty["standard"] + ty["emergency"]:
        out.append(f"- **{r['issues'][0].code}** {r['issues'][0].text}")
    # 6 last week
    wk0 = d.as_of - timedelta(days=7)
    lw = [r for r in o["rows"] if r["item"].c.finished and wk0 <= r["item"].c.finished < d.as_of]
    out += ["", f"## 6. Last week's outcomes ({wk0:%d %b} to {d.as_of - timedelta(days=1):%d %b})", "",
            "| Change | Description | Group | Outcome | Incidents | Issues |", "|---|---|---|---|---|---|"]
    for r in lw:
        c = r["item"].c
        out.append(f"| {c.number} | {c.short_description} | {c.group} | {c.close_code.replace('_', ' with ') or c.state} | "
                   f"{', '.join(x['inc'].number + ' P' + str(x['inc'].priority) for x in r['incidents']) or '–'} | {_short(r['issues'], c, ())} |")
    # 7 month
    out += ["", "## 7. Change review by month", "", "| Month | Changes | Normal | Standard | Emergency | Closed | Successful | Unsuccessful |",
            "|---|---|---|---|---|---|---|---|"]
    for m, rate in zip(o["months"], o["rates"]):
        b = o["by_month"][m]
        out.append(f"| {m} | {b['changes']} | {b['normal']} | {b['standard']} | {b['emergency']} | {b['closed']} | {pct(rate)} | {b['failed']} |")
    out += ["", "Incidents after changes:", "", "| Incident | P | Opened | Change | Link | Hours after |", "|---|---|---|---|---|---|"]
    for x in o["incidents"]:
        if month_key(x["inc"].opened) in (sm["last"], month_key(d.today)):
            out.append(f"| {x['inc'].number} {x['inc'].short_description} | {x['inc'].priority} | {_t(x['inc'].opened)} | {x['item'].c.number} | {x['how']} | "
                       f"{'' if x['hours'] is None else round(x['hours'], 1)} |")
    una = [i for r in o["rows"] for i in r["issues"] if i.code in ("OUT-05", "OUT-04")]
    if una:
        out += ["", "Unauthorised and overruns:", ""] + [f"- **{i.code}** {i.text}" for i in una]
    # 8 PIRs
    pirs = [r for r in o["rows"] if r["pir_due"] and not r["item"].c.pir_done]
    out += ["", "## 8. Post-implementation reviews due", "", "| Change | Why | Group | Due | Status |", "|---|---|---|---|---|"]
    for r in sorted(pirs, key=lambda r: r["pir_due"]):
        c = r["item"].c
        out.append(f"| {c.number} {c.short_description} | {', '.join(r['pir_need'])} | {c.group} | {_t(r['pir_due'].date())} | "
                   f"{'OVERDUE' if r['pir_due'] < d.as_of else 'due'} |")
    # 9 teams
    out += ["", "## 9. Teams", "", "| Team | Changes | Successful | Emergency share by month | Upcoming | Status |", "|---|---|---|---|---|---|"]
    for r in rv["teams"]:
        out.append(f"| {r['team']} | {r['changes']} | {pct(r['rate'])} | {' → '.join(pct(x) for x in r['monthly'])} | {r['upcoming']} | {r['verdict'].upper()} |")
    out += ["", "## Findings", ""]
    for f in findings:
        if f.severity == INFO:
            continue
        out += [f"### {f.code} · {f.subject} ({f.severity})", "", f.detail.replace("|", "/"), "", f"Next step: {f.fix} Owner: {f.owner}.", ""]
    out += ["## Actions", "", "| Ref | Action | Next step | Owner | Due |", "|---|---|---|---|---|"]
    out += [f"| {f.code} | {f.subject} | {f.fix} | {f.owner} | {TODO if f.severity == CRITICAL else ''} |" for f in findings if f.severity != INFO]
    out += ["", "## Notes", "",
            "- Services come from the change's business service and the services of its CI; the impact adds every service that depends on them "
            "(from the dependency map), directly or through others.",
            f"- Two changes collide when their planned windows overlap and they share a CI, a business service, or an affected service of tier "
            f"{s.collision_max_tier} or above.",
            "- The night of a change is the evening it starts: a change at 01:30 on Saturday belongs to Friday night.",
            f"- Incidents after a change: linked through 'caused by', or suspected when a P1 or P2 opens on the same CI or an affected service within "
            f"{s.incident_window_hours} hours with no change recorded.",
            f"- Decisions of the CAB: {TODO}", "",
            "## Sign-off", "", f"- Prepared by (change manager): {TODO}", f"- CAB chair: {TODO}", f"- Date: {TODO}", ""]
    return "\n".join(out)


# ---------------------------------------------------------------- html

CSS = """
:root{--bg:#f6f7f8;--card:#fff;--ink:#1b2128;--muted:#66717c;--line:#e2e5e9;--ok:#1e7a4c;--warn:#a46200;--bad:#b42318;--info:#0b6bcb;--bar:#3d6fb4;--frz:#eef1f6}
@media (prefers-color-scheme:dark){:root{--bg:#13171b;--card:#1b2127;--ink:#e7eaee;--muted:#9aa5b0;--line:#2b333b;--ok:#4cc38a;--warn:#f0a83a;--bad:#f2685c;--info:#5aa9f0;--bar:#6c9be0;--frz:#232b35}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,-apple-system,Segoe UI,sans-serif}
main{max-width:1100px;margin:0 auto;padding:28px 18px 60px}h1{font-size:26px;margin:0 0 4px}h2{font-size:18px;margin:34px 0 12px}
.muted{color:var(--muted)}.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:10px;margin-top:20px}
.tile{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px 16px}.tile b{display:block;font-size:26px}
.overall{display:inline-block;margin-top:14px;padding:6px 14px;border-radius:99px;font-weight:700;border:2px solid currentColor}
.areas{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px}
.area{background:var(--card);border:1px solid var(--line);border-left:5px solid var(--ok);border-radius:10px;padding:10px 14px}
.area.critical{border-left-color:var(--bad)}.area.warning{border-left-color:var(--warn)}
.area .lbl{display:block;font-size:12px;text-transform:uppercase;letter-spacing:.04em;color:var(--muted);margin-bottom:4px}.area .cnt{display:block;font-size:13px;color:var(--muted);margin-top:4px}
table{width:100%;border-collapse:collapse;background:var(--card);border:1px solid var(--line);border-radius:10px;overflow:hidden}
th,td{text-align:left;padding:8px 10px;border-bottom:1px solid var(--line);vertical-align:top}th{font-size:12px;text-transform:uppercase;letter-spacing:.04em;color:var(--muted)}
tr:last-child td{border-bottom:0}.wrap{overflow-x:auto}.num{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
.pill{display:inline-block;white-space:nowrap;padding:1px 8px;border-radius:99px;font-size:12px;font-weight:600;border:1px solid currentColor}
.critical{color:var(--bad)}.warning{color:var(--warn)}.info{color:var(--info)}.ok{color:var(--ok)}
.area.critical,.area.warning,.area.ok{color:inherit}
.pill.on-track{color:var(--ok)}.pill.attention{color:var(--warn)}.pill.action-needed{color:var(--bad)}
td.subj{min-width:190px}td.nw{white-space:nowrap}td.fix{font-size:13px;color:var(--muted);min-width:200px;max-width:380px}td.sm{font-size:13px}
.brk{overflow-wrap:anywhere;word-break:break-word}
table.cal{table-layout:fixed;min-width:980px}table.cal th,table.cal td{padding:4px 3px;font-size:11px;border-left:1px solid var(--line)}
table.cal th.svc,table.cal td.svc{width:150px;font-size:12px}table.cal th.we{background:var(--frz)}table.cal td.frz{background:repeating-linear-gradient(135deg,var(--frz),var(--frz) 4px,transparent 4px,transparent 8px)}
.chg{display:block;margin:1px 0;padding:1px 3px;border-radius:4px;border:1px solid var(--line);background:var(--card);line-height:1.25;text-align:center}
.chg.critical{border:2px solid var(--bad);color:var(--bad);font-weight:700}.chg.warning{border:2px solid var(--warn);color:var(--warn)}
.chg i{font-style:normal;color:var(--muted)}.legend span{margin-right:14px;font-size:13px}
.bars{display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:10px;align-items:end;background:var(--card);border:1px solid var(--line);border-radius:10px;padding:16px 16px 12px;margin-bottom:12px}
.col{display:flex;flex-direction:column;align-items:stretch;text-align:center;font-size:13px}.col .b{background:var(--bar);border-radius:4px 4px 0 0;min-height:2px}
.col .b.over{background:var(--bad)}.col .v{font-variant-numeric:tabular-nums;font-weight:600;margin-bottom:4px}.col .k{color:var(--muted);margin-top:6px}
footer{margin-top:40px;font-size:13px}
"""


def _pill(cls: str, text: str) -> str:
    return f"<span class='pill {cls}'>{e(text)}</span>"


def _vpill(v: str) -> str:
    return _pill(v.replace(" ", "-"), v.upper())


def _issues(issues) -> str:
    xs = sorted(issues, key=lambda x: (x.severity != CRITICAL, x.severity == INFO))
    return "<br>".join(f"<span class='{x.severity}'>●</span> <b>{e(x.code)}</b> {e(x.text)}" for x in xs) or "<span class='muted'>–</span>"


def _table(head: list[str], rows: list[str]) -> str:
    return "<div class='wrap'><table><tr>" + "".join(f"<th>{e(h)}</th>" for h in head) + "</tr>" + "".join(rows) + "</table></div>"


def _sect(h: list, n: int, title: str, area: str | None, st: dict, note: str) -> None:
    pill = _vpill("on track" if st[area] == "ok" else VERDICT[st[area]]) if area else ""
    h.append(f"<h2>{n}. {e(title)} {pill}</h2><p class='muted'>{e(note)}</p>")


def calendar_grid(d: Data, rv: dict) -> str:
    h0, h1 = rv["horizon"]
    days = [(h0 + timedelta(days=k)).date() for k in range((h1 - h0).days)]
    pc = per_change(rv)
    svcs = sorted({(it.tier, s) for it in rv["upcoming"] for s in (it.services or ["(no service)"])})
    dep = dependents(d)
    reach = {sv: {sv} | dep.get(sv, set()) for _, sv in svcs}
    cell = defaultdict(list)
    for it in rv["upcoming"]:
        for s in it.services or ["(no service)"]:
            cell[(s, night(it.c.start))].append(it)
    head = "<tr><th class='svc'>Service</th>" + "".join(f"<th class='{'we' if x.weekday() >= 5 else ''}'>{x:%a}<br>{x:%d %b}</th>" for x in days) + "</tr>"
    rows = []
    for t, s in svcs:
        tds = []
        for x in days:
            x0 = datetime(x.year, x.month, x.day, 18)
            frozen = any(f.start and f.end and f.start < x0 + timedelta(hours=12) and x0 < f.end and (f.is_global or any(
                x in f.scope for x in reach[s])) for f in d.freezes)
            chips = "".join(f"<span class='chg {_sev(pc.get(it.c.number, [])) or ''}' title='{e(it.c.number + ' ' + it.c.short_description)}'>"
                            f"{e(it.c.number[-4:])}<br><i>{it.c.start:%H:%M}{' E' if it.c.type == 'emergency' else ' S' if it.c.type == 'standard' else ''}</i></span>"
                            for it in cell.get((s, x), []))
            tds.append(f"<td class='{'frz' if frozen else ''}'>{chips}</td>")
        rows.append(f"<tr><td class='svc'><b>{e(s)}</b><br><span class='muted'>tier {t}</span></td>{''.join(tds)}</tr>")
    legend = ("<p class='legend muted'><span><span class='chg critical' style='display:inline-block'>red</span> collision, freeze or gap to act on</span>"
              "<span><span class='chg warning' style='display:inline-block'>amber</span> attention</span><span>E emergency · S standard · last four digits of "
              "the change number and the start time</span><span>hatched: freeze</span></p>")
    return legend + "<div class='wrap'><table class='cal'>" + head + "".join(rows) + "</table></div>"


def render_html(d: Data, rv: dict, findings: list[Finding], title: str) -> str:
    s, sm, st = d.settings, summary(d, rv), area_status(findings)
    ov = overall(findings)
    o = rv["outcomes"]
    h = [f"<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
         f"<title>{e(title)}</title><style>{CSS}</style></head><body><main>",
         f"<h1>{e(title)}</h1><p class='muted'>Change calendar and risk review for the CAB of {rv['cab']:%a %d %b %H:%M}, and the change review of "
         f"{sm['last']} · as of {now_label(d.as_of)}</p>",
         f"<span class='overall {'critical' if ov == 'action needed' else 'warning' if ov == 'attention' else 'ok'}'>Overall: {e(ov.upper())}</span>"
         "<div class='tiles'>"]
    tiles = [("Next two weeks", str(sm["upcoming"]), f"changes, {sm['tier1']} on tier 1"),
             ("Ready for CAB", str(sm["ready"]), f"{sm['not_ready']} with gaps"),
             ("To approve", str(sm["to_approve"]), f"at the CAB of {rv['cab']:%a %d %b}"),
             ("Collisions", str(sm["pairs"]), f"{sm['pairs_critical']} critical, {_n(sm['overloaded'], 'team night')} overloaded"),
             ("In a freeze", str(sm["in_freeze"]), "without an approved exception"),
             ("Success last month", pct(sm["rate_last"]), f"{sm['failed_last']} unsuccessful (target {pct(s.success_target)})"),
             ("Emergency share", pct(sm["emergency_share"]), f"{sm['emergency_last']} in {sm['last']}"),
             ("Incidents after changes", str(sm["incidents"]), f"{sm['p1']} P1, {sm['incidents_linked']} linked"),
             ("PIRs overdue", str(sm["pir_overdue"]), f"unauthorised {sm['unauthorised']}")]
    h += [f"<div class='tile'><span class='muted'>{e(a)}</span><b>{e(x)}</b><span class='muted'>{e(y)}</span></div>" for a, x, y in tiles]
    h.append("</div><h2>Status by area</h2><div class='areas'>")
    for a in AREAS:
        n = sum(f.area == a and f.severity != INFO for f in findings)
        h.append(f"<div class='area {st[a]}'><span class='lbl'>{e(a)}</span>{_pill(st[a], 'ON TRACK' if st[a] == 'ok' else VERDICT[st[a]].upper())}"
                 f"<span class='cnt'>{n} to act on</span></div>")
    h.append("</div>")
    crit = [f for f in findings if f.severity == CRITICAL]
    if crit:
        h.append("<h2>Fix first</h2>")
        h.append(_table(["Subject", "What", "Next step", "Owner"],
                        [f"<tr><td class='subj'><b>{e(f.subject)}</b><br><span class='muted'>{e(f.area)} · {e(f.code)}</span></td>"
                         f"<td class='sm brk'>{e(f.detail)}</td><td class='fix'>{e(f.fix)}</td><td class='nw'>{e(f.owner)}</td></tr>" for f in crit]))
    # 1 calendar
    h.append(f"<h2>1. The next {s.horizon_days} days</h2><p class='muted'>Every change by business service and night. A change that affects "
             "several services shows on each. calendar.csv has every change with its impacted services.</p>")
    h.append(calendar_grid(d, rv))
    # 2 readiness
    _sect(h, 2, "Readiness for the CAB", "Readiness", st,
          "Plans, risk against impact and tier, lead time, approval, owner and maintenance window: the changes with something to fix. The CAB "
          "agenda (changes waiting for approval) is in cab-pack.md and every change is in readiness.csv.")
    rows = [r for r in rv["readiness"] if r["severity"]]
    h.append(_table(["Change", "Type / risk", "Start", "Group", "Status", "Issues"],
                    [f"<tr><td class='sm'><b>{e(c.number)}</b><br>{e(c.short_description)}</td><td class='sm nw'>{e(c.type)}<br>"
                     f"<span class='muted'>{e(c.risk or 'not assessed')} · tier {r['item'].tier}</span></td><td class='nw sm'>{c.start:%a %d %b %H:%M}</td>"
                     f"<td class='sm'>{e(c.group or '–')}</td><td>{_vpill(r['verdict'])}</td><td class='sm'>{_issues(r['issues'])}</td></tr>"
                     for r in rows for c in [r["item"].c]]))
    # 3 collisions
    _sect(h, 3, "Collisions and freezes", "Collisions", st,
          f"Overlapping changes on the same CI or service, or affecting the same tier 1-{s.collision_max_tier} services through the dependencies; "
          f"more than {s.max_changes_per_team_night} changes for one team on one night; changes inside a freeze or blackout. collisions.csv has them all.")
    crow = ([f"<tr><td class='nw'><b>{e(r['a'].c.number)}</b><br><b>{e(r['b'].c.number)}</b></td><td class='sm'>{e(r['on'])}</td><td>{_vpill(r['verdict'])}</td>"
             f"<td class='sm'>{_issues(r['issues'])}</td></tr>" for r in rv["pairs"]]
            + [f"<tr><td class='nw'><b>{e(r['team'])}</b></td><td class='sm'>{r['night']:%a %d %b}</td><td>{_vpill(r['verdict'])}</td>"
               f"<td class='sm'>{_issues(r['issues'])}</td></tr>" for r in rv["load"]]
            + [f"<tr><td class='nw'><b>{e(r['item'].c.number)}</b></td><td class='sm'>{e(r['freeze'].name)}</td><td>{_vpill(r['verdict'])}</td>"
               f"<td class='sm'>{_issues(r['issues'])}</td></tr>" for r in rv["freeze"]])
    h.append(_table(["Changes", "On", "Status", "Issues"], crow))
    # 4 types
    ty = rv["types"]
    _sect(h, 4, "Emergency and standard changes", "Change types", st,
          f"Emergency share by month (max {pct(s.emergency_share_max)}) and its reasons, standard changes used for risky work, and emergency changes "
          f"without an approval within {s.retro_approval_days} days.")
    h.append("<div class='bars'>" + "".join(
        f"<div class='col'><span class='v'>{pct(x)}</span><span class='b{' over' if x is not None and x > s.emergency_share_max else ''}' "
        f"style='height:{max(2, round(400 * (x or 0)))}px'></span><span class='k'>{e(m)}<br>{o['by_month'][m]['emergency']} of "
        f"{o['by_month'][m]['changes']}</span></div>" for m, x in zip(o["months"], ty["shares"])) + "</div>")
    trow = [f"<tr><td class='nw'><b>{e(r['item'].c.number)}</b></td><td class='sm'>{e(r['item'].c.short_description)}</td><td>{_vpill(r['verdict'])}</td>"
            f"<td class='sm'>{_issues(r['issues'])}</td></tr>" for r in ty["standard"] + ty["emergency"]]
    if ty["overall"]["issues"]:
        trow.insert(0, f"<tr><td class='nw'><b>{e(sm['last'])}</b></td><td class='sm'>Emergency share and reasons</td><td>{_vpill(ty['overall']['verdict'])}</td>"
                       f"<td class='sm'>{_issues(ty['overall']['issues'])}</td></tr>")
    h.append(_table(["Item", "What", "Status", "Issues"], trow))
    # 5 outcomes
    _sect(h, 5, "Outcomes", "Outcomes", st,
          f"Changes of the last {len(o['months'])} months: success rate by month, unsuccessful changes, incidents after a change, overruns over "
          f"{s.overrun_tolerance_minutes} minutes, unauthorised work and post-implementation reviews overdue ({s.pir_due_days} days). outcomes.csv has every change.")
    h.append("<div class='bars'>" + "".join(
        f"<div class='col'><span class='v'>{pct(r)}</span><span class='b{' over' if r is not None and r < s.success_target else ''}' "
        f"style='height:{max(2, round(150 * (r or 0)))}px'></span><span class='k'>{e(m)}<br>{o['by_month'][m]['closed']} closed, "
        f"{o['by_month'][m]['failed']} unsuccessful</span></div>" for m, r in zip(o["months"], o["rates"])) + "</div>")
    orow = [r for r in o["rows"] if r["issues"]]
    h.append(_table(["Change", "Group", "Outcome", "Status", "Issues"],
                    [f"<tr><td class='sm'><b>{e(c.number)}</b><br>{e(c.short_description)}</td><td class='sm'>{e(c.group or '–')}</td>"
                     f"<td class='sm nw'>{e(c.close_code.replace('_', ' with ') or c.state)}<br><span class='muted'>{c.start:%d %b}</span></td>"
                     f"<td>{_vpill(r['verdict'])}</td><td class='sm'>{_issues(r['issues'])}</td></tr>" for r in orow for c in [r["item"].c]]))
    # 6 teams
    _sect(h, 6, "Teams", "Teams", st,
          f"Success rate over {o['months'][0]} to {o['months'][-1]} (minimum {pct(s.team_success_min)}) and emergency share by month (max "
          f"{pct(s.team_emergency_share_max)}). teams.csv has the numbers.")
    h.append(_table(["Team", "Changes", "Successful", "Emergency by month", "Upcoming", "Status", "Issues"],
                    [f"<tr><td class='nw'><b>{e(r['team'])}</b></td><td class='num'>{r['changes']}</td><td class='num'>{pct(r['rate'])}<br>"
                     f"<span class='muted'>{r['failed']} unsuccessful</span></td><td class='nw sm'>{' → '.join(pct(x) for x in r['monthly'])}</td>"
                     f"<td class='num'>{r['upcoming']}</td><td>{_vpill(r['verdict'])}</td><td class='sm'>{_issues(r['issues'])}</td></tr>" for r in rv["teams"]]))
    h.append("<h2>All findings</h2>")
    h.append(_table(["Severity", "Area", "Subject", "Detail", "Next step", "Owner"],
                    [f"<tr><td>{_pill(f.severity, f.severity.upper())}</td><td class='nw'>{e(f.area)}</td><td>{e(f.subject)}</td>"
                     f"<td class='sm brk'>{e(f.detail)}</td><td class='fix'>{e(f.fix)}</td><td class='nw'>{e(f.owner)}</td></tr>" for f in findings]))
    h.append("<footer class='muted'>Generated by changecal. Fictional demo data unless you ran it on your own exports. The CAB pack is "
             "cab-pack.md.</footer></main></body></html>")
    return "".join(h)


__all__ = ["render_html", "pack_md", "WARNING"]
