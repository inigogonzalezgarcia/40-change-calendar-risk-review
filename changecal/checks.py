"""The checks. Every change scheduled in the next `horizon_days` gets its business services (from the CI or the business service field),
the services that depend on them (the impact through the dependency map), its tier and its operational night. Then five areas:
readiness for the CAB (plans, risk, lead time, approval, owner, maintenance window), collisions (same CI or service, shared dependent
services, too many changes for one team on one night, inside a freeze or blackout window), change types (emergency share and its reasons,
standard changes used for risky work, emergency changes without a retrospective approval), outcomes of the last month and the trend
(success rate, failed changes, change-caused incidents, overruns, unauthorised work, post-implementation reviews overdue) and teams (low
success rate, high or rising emergency share). Each finding says what to do and who owns it."""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from .model import DAYS, RISKS, Change, Data, Freeze, _norm, hhmm, month_key, months_before

CRITICAL, WARNING, INFO = "critical", "warning", "info"
ORDER = {CRITICAL: 0, WARNING: 1, INFO: 2}
AREAS = ("Readiness", "Collisions", "Change types", "Outcomes", "Teams")
VERDICT = {CRITICAL: "action needed", WARNING: "attention", None: "on track"}
PLAN_NAMES = {"backout": "backout plan", "test": "test plan", "implementation": "implementation plan"}
NO_GROUP = "(no assignment group)"


@dataclass
class Finding:
    severity: str
    area: str
    code: str
    subject: str
    detail: str
    fix: str
    owner: str = ""
    items: list[str] = field(default_factory=list)


@dataclass
class Issue:
    severity: str
    code: str
    text: str


def _n(k: int, word: str, plural: str | None = None) -> str:
    return f"{k} {word if k == 1 else (plural or word + 's')}"


def _top(items: list[str], k: int = 6, sep: str = ", ") -> str:
    return sep.join(items[:k]) + (f" and {len(items) - k} more" if len(items) > k else "")


def _d(v) -> str:
    if not v:
        return "never"
    return v.strftime("%a %d %b %H:%M") if isinstance(v, datetime) else v.strftime("%d %b %Y")


def pct(x: float | None) -> str:
    return "–" if x is None else f"{x:.0%}"


def worst(issues: list[Issue]) -> str | None:
    sev = {i.severity for i in issues}
    return CRITICAL if CRITICAL in sev else WARNING if WARNING in sev else None


def _row(**kw) -> dict:
    kw.setdefault("issues", [])
    kw["severity"] = worst(kw["issues"])
    kw["verdict"] = VERDICT[kw["severity"]]
    return kw


def night(dt: datetime) -> date:
    """The operational night of a change: 01:30 on Saturday belongs to Friday night."""
    return (dt - timedelta(hours=6)).date()


def overlap(a: Change, b: Change) -> bool:
    return bool(a.start and b.start and a.end and b.end and a.start < b.end and b.start < a.end)


# ---------------------------------------------------------------- services and impact

def direct_services(d: Data, c: Change) -> list[str]:
    out = []
    if c.service:
        out.append(c.service)
    for s in d.ci_services.get(c.ci.lower(), []):
        if s not in out:
            out.append(s)
    return out


def dependents(d: Data) -> dict[str, set[str]]:
    """service -> every service that depends on it, directly or through others."""
    up = defaultdict(set)
    for s in d.services.values():
        for dep in s.depends_on:
            up[dep].add(s.name)
    out = {}
    for name in set(d.services) | set(up):
        seen, todo = set(), [name]
        while todo:
            x = todo.pop()
            for y in up.get(x, ()):
                if y not in seen and y != name:
                    seen.add(y)
                    todo.append(y)
        out[name] = seen
    return out


def tier(d: Data, service: str) -> int:
    s = d.services.get(service)
    return s.tier if s else 3


def in_window(d: Data, t: int, start: datetime, end: datetime) -> bool:
    windows = d.settings.maintenance_windows.get(str(t)) or []
    if not windows:
        return True
    for w in windows:
        days_ = [_norm(x)[:3] for x in w.get("days", DAYS)]
        a, b = hhmm(w.get("start", "00:00")), hhmm(w.get("end", "00:00"))
        for off in (-1, 0):
            day = start.date() + timedelta(days=off)
            if DAYS[day.weekday()] not in days_:
                continue
            ws = datetime(day.year, day.month, day.day) + timedelta(minutes=a)
            we = datetime(day.year, day.month, day.day) + timedelta(minutes=b + (1440 if b <= a else 0))
            if ws <= start and end <= we:
                return True
    return False


def cab_meetings(d: Data) -> tuple[datetime, datetime]:
    s = d.settings
    wd = DAYS.index(_norm(s.cab_weekday)[:3]) if _norm(s.cab_weekday)[:3] in DAYS else 1
    t = hhmm(s.cab_time)
    day = d.today + timedelta(days=(wd - d.today.weekday()) % 7)
    first = datetime(day.year, day.month, day.day) + timedelta(minutes=t)
    if first < d.as_of:
        first += timedelta(days=7)
    return first, first + timedelta(days=7)


def approved_at(d: Data, c: Change) -> datetime | None:
    xs = [a.when for a in d.approvals.get(c.number, []) if a.state == "approved" and a.when]
    return max(xs) if xs else None


@dataclass
class Item:
    """One change with its services, impact and tier."""
    c: Change
    services: list[str]
    impacted: list[str]
    tier: int

    @property
    def label(self) -> str:
        return self.c.number

    @property
    def team(self) -> str:
        return self.c.group or NO_GROUP


def items(d: Data) -> list[Item]:
    dep = dependents(d)
    out = []
    for c in d.changes:
        sv = direct_services(d, c)
        imp = list(sv)
        for s in sv:
            imp += sorted(x for x in dep.get(s, ()) if x not in imp)
        out.append(Item(c, sv, imp, min((tier(d, s) for s in sv), default=3)))
    return out


# ---------------------------------------------------------------- readiness

def readiness(d: Data, up: list[Item], cab: datetime, cab2: datetime) -> list[dict]:
    s = d.settings
    rows = []
    for it in up:
        c = it.c
        iss = []
        hot = c.risk in ("very high", "high") or it.tier == 1
        what = f"{c.number} {c.short_description}"
        missing = [PLAN_NAMES[p] for p in s.plans_required.get(c.type, []) if not getattr(c, p, "").strip() or _norm(getattr(c, p)) in
                   {"", "none", "n a", "na", "tbd", "to follow", "see above"}]
        if missing:
            iss.append(Issue(CRITICAL if hot else WARNING, "RDY-01", f"{what}: no {', no '.join(missing)} ({c.type}, risk {c.risk or 'not assessed'})"))
        if c.type != "standard":
            if not c.risk:
                iss.append(Issue(WARNING, "RDY-02", f"{what}: risk not assessed"))
            else:
                need = "high" if (c.impact == 1 and it.tier == 1) else "moderate" if (c.impact == 1 or it.tier == 1) else "low"
                if RISKS.index(c.risk) > RISKS.index(need):
                    iss.append(Issue(WARNING, "RDY-02", f"{what}: risk {c.risk} for impact {c.impact or '?'} on a tier {it.tier} service "
                                                        f"({', '.join(it.services) or 'no service'}): expected at least {need}"))
        lead = s.lead_days(c)
        if lead and c.opened and c.start:
            got = (c.start - c.opened).total_seconds() / 86400
            if got < lead:
                iss.append(Issue(CRITICAL if c.risk in ("very high", "high") else WARNING, "RDY-03",
                                 f"{what}: raised {_d(c.opened)}, {got:.1f} days before the start (lead time {lead} days for a {c.risk or 'unassessed'} "
                                 f"{c.type} change)"))
        if c.type != "standard" and c.approval != "approved":
            if c.approval == "rejected":
                iss.append(Issue(CRITICAL, "RDY-04", f"{what}: rejected and still scheduled for {_d(c.start)}"))
            elif c.type == "emergency":
                iss.append(Issue(WARNING, "RDY-04", f"{what}: emergency change not yet approved by the ECAB, starts {_d(c.start)}"))
            elif c.start < cab:
                iss.append(Issue(CRITICAL, "RDY-04", f"{what}: not approved, starts {_d(c.start)}, before the CAB of {_d(cab)}"))
            elif c.start < cab2:
                iss.append(Issue(INFO, "RDY-04", f"{what}: not approved ({c.approval}), starts {_d(c.start)}: decide at the CAB of {_d(cab)}"))
            else:
                iss.append(Issue(INFO, "RDY-04", f"{what}: not approved yet, starts {_d(c.start)}: CAB of {_d(cab2)}"))
        if not c.group or not c.assigned_to:
            iss.append(Issue(WARNING, "RDY-05", f"{what}: no {'assignment group' if not c.group else 'assignee'}"))
        if c.outside_window or not in_window(d, it.tier, c.start, c.end):
            iss.append(Issue(WARNING, "RDY-06", f"{what}: {_d(c.start)} to {c.end:%H:%M} is outside the maintenance window for tier {it.tier}"
                                                f"{' (flagged outside the maintenance schedule)' if c.outside_window else ''}"))
        rows.append(_row(item=it, missing=missing, lead=lead, issues=iss))
    return rows


# ---------------------------------------------------------------- collisions

def collisions(d: Data, up: list[Item]) -> dict:
    s = d.settings
    pairs = []
    for i, a in enumerate(up):
        for b in up[i + 1:]:
            if not overlap(a.c, b.c):
                continue
            same_ci = bool(a.c.ci) and a.c.ci.lower() == b.c.ci.lower()
            shared = [x for x in a.services if x in b.services]
            w = f"{_d(max(a.c.start, b.c.start))} to {min(a.c.end, b.c.end):%H:%M}"
            if same_ci or shared:
                t = min((tier(d, x) for x in shared), default=a.tier)
                sev = CRITICAL if same_ci or t <= s.collision_max_tier else WARNING
                on = f"CI {a.c.ci}" if same_ci else ", ".join(shared)
                pairs.append(_row(a=a, b=b, on=on, issues=[Issue(sev, "COL-01", f"{a.label} and {b.label}: both on {on}, overlapping {w}")]))
                continue
            common = [x for x in a.impacted if x in b.impacted and tier(d, x) <= s.collision_max_tier]
            if common:
                sev = CRITICAL if any(tier(d, x) == 1 for x in common) else WARNING
                pairs.append(_row(a=a, b=b, on=", ".join(common),
                                  issues=[Issue(sev, "COL-02", f"{a.label} ({', '.join(a.services) or a.c.ci}) and {b.label} "
                                                               f"({', '.join(b.services) or b.c.ci}) overlap {w}; both affect {_top(common, 4)}")]))
    nights = defaultdict(list)
    for it in up:
        nights[(it.team, night(it.c.start))].append(it)
    load = []
    for (team, n), xs in sorted(nights.items(), key=lambda kv: (kv[0][1], kv[0][0])):
        if len(xs) > s.max_changes_per_team_night and team != NO_GROUP:
            load.append(_row(team=team, night=n, items=xs, issues=[Issue(WARNING, "COL-03", f"{team}: {len(xs)} changes on the night of "
                                                                                            f"{n:%a %d %b} ({', '.join(x.label for x in xs)}), "
                                                                                            f"max {s.max_changes_per_team_night}")]))
    frz = []
    for it in up:
        for f in d.freezes:
            if not (f.start and f.end and it.c.start < f.end and f.start < it.c.end):
                continue
            hit = it.impacted if f.is_global else [x for x in it.impacted if x in f.scope]
            if not hit and not f.is_global:
                continue
            what = f"{it.label} {it.c.short_description} ({it.c.type}, {_d(it.c.start)}): inside {f.kind} '{f.name}' ({_d(f.start)} to {_d(f.end)})"
            if it.c.number in f.exceptions:
                iss = Issue(INFO, "COL-05", f"{what} with an approved exception")
            elif f.kind == "blackout":
                iss = Issue(CRITICAL, "COL-04", f"{what}, no change allowed")
            elif it.c.type == "emergency" and s.freeze_allows_emergency:
                iss = Issue(INFO, "COL-05", f"{what}: emergency change, allowed by the freeze rules")
            elif it.c.type == "standard" and s.freeze_allows_standard:
                continue
            else:
                iss = Issue(CRITICAL, "COL-04", f"{what} without an approved exception; affects {_top(hit or it.impacted, 3)}")
            frz.append(_row(item=it, freeze=f, issues=[iss]))
    return dict(pairs=pairs, load=load, freeze=frz)


# ---------------------------------------------------------------- history: types, outcomes, teams

def history(d: Data, its: list[Item]) -> tuple[list[str], list[Item]]:
    months = months_before(d.today, d.settings.trend_months)
    return months, [it for it in its if it.c.active and it.c.start and month_key(it.c.start) in months and it.c.start < d.as_of]


def success(c: Change) -> bool:
    return c.close_code in ("successful", "successful_issues")


def incidents_of(d: Data, its: list[Item], since: datetime) -> list[dict]:
    """Incidents linked to a change (caused_by), and P1/P2 incidents on the same CI or an affected service within `incident_window_hours`
    after a change finished, with no change recorded (suspected)."""
    s = d.settings
    by_num = {it.c.number: it for it in its}
    done = [it for it in its if it.c.done and it.c.finished]
    out = []
    for inc in sorted(d.incidents, key=lambda i: (i.opened or datetime.min, i.number)):
        if not inc.opened or inc.opened < since or inc.opened > d.as_of:
            continue
        it = by_num.get(inc.caused_by)
        how = "linked"
        if not it:
            if inc.caused_by or not inc.priority or inc.priority > s.suspected_max_priority:
                continue
            svc = [inc.service] if inc.service else d.ci_services.get(inc.ci.lower(), [])
            cands = [x for x in done if timedelta(0) <= inc.opened - x.c.finished <= timedelta(hours=s.incident_window_hours)
                     and ((inc.ci and inc.ci.lower() == x.c.ci.lower()) or any(v in x.impacted for v in svc))]
            if not cands:
                continue
            it = max(cands, key=lambda x: (x.c.finished, x.c.number))
            how = "suspected"
        gap = (inc.opened - it.c.finished).total_seconds() / 3600 if it.c.finished else None
        out.append(dict(inc=inc, item=it, how=how, hours=gap))
    return out


def outcomes(d: Data, its: list[Item]) -> dict:
    s = d.settings
    months, hist = history(d, its)
    last = months[-1]
    start0 = datetime.strptime(months[0] + "-01", "%Y-%m-%d")
    recent = [it for it in its if it.c.active and it.c.start and start0 <= it.c.start < d.as_of]
    incs = incidents_of(d, its, start0)
    inc_by = defaultdict(list)
    for x in incs:
        inc_by[x["item"].c.number].append(x)
    rows = []
    for it in sorted(recent, key=lambda x: (x.c.start, x.c.number)):
        c = it.c
        if not c.done and not c.work_start:
            continue
        iss = []
        m = month_key(c.start)
        lm = m == last
        what = f"{c.number} {c.short_description}"
        if lm and c.close_code == "unsuccessful":
            iss.append(Issue(WARNING, "OUT-02", f"{what} ({c.group or NO_GROUP}, {_d(c.start)}): unsuccessful"))
        for x in inc_by.get(c.number, []):
            inc = x["inc"]
            if month_key(inc.opened) not in (last, month_key(d.today)):
                continue
            when = f"{x['hours']:.1f} h after the change finished" if x["hours"] is not None and x["hours"] >= 0 else "during the change"
            if x["how"] == "linked":
                iss.append(Issue(CRITICAL if inc.priority <= 2 else WARNING, "OUT-03",
                                 f"{c.number}: P{inc.priority} {inc.number} {inc.short_description}, opened {when}"))
            else:
                iss.append(Issue(WARNING, "OUT-03", f"{c.number}: P{inc.priority} {inc.number} {inc.short_description} on {inc.ci or inc.service}, "
                                                    f"opened {when}, not linked to a change: confirm or rule out"))
        over = None
        if c.work_end and c.end:
            over = round((c.work_end - c.end).total_seconds() / 60)
            if lm and over > s.overrun_tolerance_minutes:
                iss.append(Issue(WARNING, "OUT-04", f"{what}: finished {_d(c.work_end)}, {over} minutes past the planned end"))
        why = []
        if c.work_start and c.opened:
            if c.type == "emergency" and c.work_end and c.opened > c.work_end:
                why.append(f"raised {_d(c.opened)}, after the work finished")
            elif c.type != "emergency" and c.opened > c.work_start + timedelta(hours=1):
                why.append(f"raised {_d(c.opened)}, after the work started {_d(c.work_start)}")
        if c.work_start and c.type == "normal":
            ap = approved_at(d, c)
            if d.approvals and ap and ap > c.work_start:
                why.append(f"approved {_d(ap)}, after the work started {_d(c.work_start)}")
            elif (not d.approvals or not ap) and c.approval != "approved":
                why.append(f"implemented {_d(c.work_start)} with approval '{c.approval}'")
        if why:
            iss.append(Issue(CRITICAL, "OUT-05", f"{what} ({c.group or NO_GROUP}): " + "; ".join(why)))
        need = []
        if c.close_code in s.pir_required_for:
            need.append(c.close_code.replace("_", " with "))
        if c.type == "emergency" and "emergency" in s.pir_required_for:
            need.append("emergency")
        if inc_by.get(c.number) and "incident" in s.pir_required_for:
            need.append("incident")
        due = (c.finished + timedelta(days=s.pir_due_days)) if (need and c.finished) else None
        if due and not c.pir_done and due < d.as_of:
            late = (d.as_of - due).days
            p1 = any(x["inc"].priority == 1 for x in inc_by.get(c.number, []))
            iss.append(Issue(CRITICAL if p1 or late > 2 * s.pir_due_days else WARNING, "OUT-06",
                             f"{c.number} ({', '.join(need)}): PIR due {_d(due.date())}, {_n(late, 'day')} overdue, owner {c.group or NO_GROUP}"))
        rows.append(_row(item=it, month=m, last=lm, overrun=over, incidents=inc_by.get(c.number, []), pir_need=need, pir_due=due, issues=iss))
    # success rate by month
    by_month = {mm: dict(changes=0, closed=0, ok=0, issues=0, failed=0, emergency=0, standard=0, normal=0) for mm in months}
    for it in hist:
        b = by_month[month_key(it.c.start)]
        b["changes"] += 1
        b[it.c.type] += 1
        if it.c.close_code:
            b["closed"] += 1
            b["ok"] += success(it.c)
            b["issues"] += it.c.close_code == "successful_issues"
            b["failed"] += it.c.close_code == "unsuccessful"
    rates = [by_month[mm]["ok"] / by_month[mm]["closed"] if by_month[mm]["closed"] else None for mm in months]
    iss = []
    if rates[-1] is not None and rates[-1] < s.success_target:
        b = by_month[last]
        iss.append(Issue(CRITICAL if rates[-1] < s.success_target - 0.1 else WARNING, "OUT-01",
                         f"{last}: {pct(rates[-1])} of {b['closed']} closed changes successful (target {pct(s.success_target)}), {b['failed']} unsuccessful; "
                         + ", ".join(f"{mm} {pct(r)}" for mm, r in zip(months, rates))))
    return dict(months=months, rows=rows, by_month=by_month, rates=rates, overall=_row(issues=iss), incidents=incs)


def types(d: Data, its: list[Item], up: list[Item], out: dict) -> dict:
    s = d.settings
    months, hist = history(d, its)
    last = months[-1]
    bm = out["by_month"]
    shares = [bm[m]["emergency"] / bm[m]["changes"] if bm[m]["changes"] else None for m in months]
    iss = []
    reasons = Counter(it.c.justification.strip().rstrip(".") or "No reason recorded" for it in hist if month_key(it.c.start) == last
                      and it.c.type == "emergency")
    if shares[-1] is not None and shares[-1] > s.emergency_share_max:
        iss.append(Issue(CRITICAL if shares[-1] > 2 * s.emergency_share_max else WARNING, "TYP-01",
                         f"{last}: {bm[last]['emergency']} of {bm[last]['changes']} changes were emergency ({pct(shares[-1])}, max "
                         f"{pct(s.emergency_share_max)}); " + ", ".join(f"{m} {pct(x)}" for m, x in zip(months, shares))))
    if reasons:
        iss.append(Issue(INFO, "TYP-04", f"{last} emergency reasons: " + "; ".join(f"{k} ({v})" for k, v in reasons.most_common(6))))
    rx = re.compile(s.standard_risky_match, re.I) if s.standard_risky_match else None
    std = []
    for it in up + [x for x in hist if month_key(x.c.start) == last]:
        c = it.c
        if c.type != "standard":
            continue
        why = []
        if c.risk in ("very high", "high"):
            why.append(f"risk {c.risk}")
        if rx and rx.search(c.short_description) and it.tier <= 2:
            why.append(f"'{rx.search(c.short_description).group()}' on a tier {it.tier} service")
        if why:
            future = c.start >= d.as_of
            std.append(_row(item=it, issues=[Issue(CRITICAL if future and it.tier == 1 else WARNING, "TYP-02",
                                                   f"{c.number} {c.short_description} ({_d(c.start)}): standard change with {', '.join(why)}")]))
    emg = []
    for it in hist:
        c = it.c
        if c.type != "emergency" or not c.done:
            continue
        ap = approved_at(d, c) if d.approvals else None
        if not ap and (d.approvals or c.approval != "approved"):
            emg.append(_row(item=it, issues=[Issue(CRITICAL, "TYP-03", f"{c.number} {c.short_description} ({c.group or NO_GROUP}, {_d(c.start)}): "
                                                                     f"no approval recorded")]))
        elif ap and c.finished and ap > c.finished + timedelta(days=s.retro_approval_days):
            emg.append(_row(item=it, issues=[Issue(WARNING, "TYP-03", f"{c.number} {c.short_description}: approved {_d(ap)}, "
                                                                    f"{(ap - c.finished).days} days after the work")]))
    return dict(shares=shares, overall=_row(issues=iss), standard=std, emergency=emg, reasons=reasons)


def teams(d: Data, its: list[Item], up: list[Item]) -> list[dict]:
    s = d.settings
    months, hist = history(d, its)
    t = defaultdict(lambda: dict(changes=0, closed=0, ok=0, failed=0, emergency=0, upcoming=0, by_month={m: [0, 0] for m in months}))
    for it in hist:
        x = t[it.team]
        x["changes"] += 1
        x["emergency"] += it.c.type == "emergency"
        x["by_month"][month_key(it.c.start)][0] += 1
        x["by_month"][month_key(it.c.start)][1] += it.c.type == "emergency"
        if it.c.close_code:
            x["closed"] += 1
            x["ok"] += success(it.c)
            x["failed"] += it.c.close_code == "unsuccessful"
    for it in up:
        t[it.team]["upcoming"] += 1
    for name in s.teams:
        t[name]
    rows = []
    for name, x in sorted(t.items()):
        if name == NO_GROUP and not x["changes"]:
            continue
        rate = x["ok"] / x["closed"] if x["closed"] else None
        share = x["emergency"] / x["changes"] if x["changes"] else 0.0
        monthly = [b[1] / b[0] if b[0] else None for b in x["by_month"].values()]
        iss = []
        if rate is not None and x["closed"] >= s.team_min_changes and rate < s.team_success_min:
            iss.append(Issue(CRITICAL if rate < s.team_success_min - 0.15 else WARNING, "TEAM-01",
                             f"{name}: {pct(rate)} of {x['closed']} changes successful in {months[0]} to {months[-1]} ({x['failed']} unsuccessful), "
                             f"minimum {pct(s.team_success_min)}"))
        known = [m for m in monthly if m is not None]
        rising = len(known) >= 2 and known[-1] > known[0] and all(b >= a for a, b in zip(known, known[1:]))
        lastm = monthly[-1]
        if x["changes"] >= s.team_min_changes and lastm is not None and lastm > s.team_emergency_share_max and (rising or share > s.team_emergency_share_max):
            iss.append(Issue(CRITICAL if lastm > 2 * s.team_emergency_share_max else WARNING, "TEAM-02",
                             f"{name}: emergency share {' → '.join(pct(m) for m in monthly)} ({months[0]} to {months[-1]}), max "
                             f"{pct(s.team_emergency_share_max)}{', rising' if rising else ''}"))
        rows.append(_row(team=name, rate=rate, share=share, monthly=monthly, **x, issues=iss))
    return rows


def review(d: Data) -> dict:
    s = d.settings
    its = items(d)
    h0 = datetime(d.today.year, d.today.month, d.today.day)
    h1 = h0 + timedelta(days=s.horizon_days)
    up = sorted([it for it in its if it.c.active and not it.c.done and it.c.start and it.c.end and h0 <= it.c.start < h1],
                key=lambda it: (it.c.start, it.c.number))
    cab, cab2 = cab_meetings(d)
    out = outcomes(d, its)
    return dict(items=its, upcoming=up, horizon=(h0, h1), cab=cab, cab2=cab2, readiness=readiness(d, up, cab, cab2), **collisions(d, up),
                outcomes=out, types=types(d, its, up, out), teams=teams(d, its, up))


CODES = {  # code: (area, owner key, subject, next step, word)
    "RDY-01": ("Readiness", "readiness", "changes without a backout, test or implementation plan",
               "Send back to the change owner: no plan, no CAB approval. The backout plan says how long the rollback takes and who decides it.", "change"),
    "RDY-02": ("Readiness", "readiness", "changes with the risk not assessed or below what the impact and tier suggest",
               "Re-run the risk assessment with the change owner before the CAB; the impact and the tier of the service set the floor.", "change"),
    "RDY-03": ("Readiness", "readiness", "normal changes raised inside the lead time",
               "Move the date to respect the lead time, or raise it as emergency with the reason and ECAB approval.", "change"),
    "RDY-04": ("Readiness", "readiness", "changes not approved yet",
               "Put them on this week's CAB agenda; anything that starts before the CAB is postponed unless the ECAB approves it.", "change"),
    "RDY-05": ("Readiness", "readiness", "changes without an assignment group or assignee",
               "Assign a group and an implementer: somebody has to be awake and accountable that night.", "change"),
    "RDY-06": ("Readiness", "readiness", "changes outside the maintenance window of their tier",
               "Move into the window, or approve it at the CAB with the business owner's agreement recorded.", "change"),
    "COL-01": ("Collisions", "collisions", "overlapping changes on the same CI or business service",
               "Sequence them: one change per CI or service at a time, or merge them into one change with one backout plan.", "pair"),
    "COL-02": ("Collisions", "collisions", "overlapping changes that affect the same dependent services",
               "Move one of them to another night: if both go wrong, nobody will know which one to roll back.", "pair"),
    "COL-03": ("Collisions", "collisions", "teams with too many changes on one night",
               "Spread them over the next nights or add implementers; check the on-call cover.", "night"),
    "COL-04": ("Collisions", "collisions", "changes inside a freeze or blackout without an approved exception",
               "Move them after the freeze, or get the exception approved by the business owner and record it in the freeze register.", "change"),
    "COL-05": ("Collisions", "collisions", "changes inside a freeze with an approved exception", "Confirm the exception is still valid.", "change"),
    "TYP-01": ("Change types", "types", "emergency changes above the target share",
               "Review the reasons: planned work raised as emergency is a lead time or planning problem, not an emergency.", "month"),
    "TYP-02": ("Change types", "types", "standard changes used for risky work",
               "Raise it as a normal change with a risk assessment; review the standard change template so it cannot be used for this.", "change"),
    "TYP-03": ("Change types", "types", "emergency changes without a retrospective approval",
               "Get the ECAB approval recorded now and review the change at the next CAB.", "change"),
    "TYP-04": ("Change types", "types", "emergency change reasons", "Look for repeats and planned work in the list.", "month"),
    "OUT-01": ("Outcomes", "outcomes", "success rate below the target",
               "Review the unsuccessful changes at the CAB: test, backout and timing; agree an action per team.", "month"),
    "OUT-02": ("Outcomes", "outcomes", "unsuccessful changes last month",
               "Each needs a PIR: what failed, whether the backout worked, and what changes in the next attempt.", "change"),
    "OUT-03": ("Outcomes", "outcomes", "changes followed by incidents",
               "Confirm the link in the incident (caused by), run the PIR, and check whether testing could have caught it.", "change"),
    "OUT-04": ("Outcomes", "outcomes", "changes that overran their window",
               "Check the time estimates of the team and the backout decision point; an overrun at night ends in the trading day.", "change"),
    "OUT-05": ("Outcomes", "outcomes", "unauthorised changes",
               "Escalate to the team lead: work without an approved change is a process breach; record it and review it at the CAB.", "change"),
    "OUT-06": ("Outcomes", "outcomes", "post-implementation reviews overdue",
               "Book the PIR with the change owner this week; close the change only with the review done.", "change"),
    "TEAM-01": ("Teams", "teams", "teams with a low change success rate",
                "Review the team's failed changes with its lead: testing, environments, backout plans and estimates.", "team"),
    "TEAM-02": ("Teams", "teams", "teams with a high or rising emergency share",
                "Look at the team's emergencies: repeats point to a problem record; planned work points to planning and lead times.", "team"),
}


def all_issues(rv: dict) -> list[Issue]:
    rows = (rv["readiness"] + rv["pairs"] + rv["load"] + rv["freeze"] + rv["outcomes"]["rows"] + [rv["outcomes"]["overall"]]
            + [rv["types"]["overall"]] + rv["types"]["standard"] + rv["types"]["emergency"] + rv["teams"])
    return [i for r in rows for i in r["issues"]]


def run_all(d: Data, rv: dict | None = None) -> list[Finding]:
    rv = rv if rv is not None else review(d)
    s = d.settings
    hits = defaultdict(list)
    for i in all_issues(rv):
        hits[i.code].append(i)
    out: list[Finding] = []
    for code, (area, owner, subject, fix, word) in CODES.items():
        for sev in (CRITICAL, WARNING, INFO):
            xs = list({i.text: i for i in hits.get(code, []) if i.severity == sev}.values())
            if not xs:
                continue
            subj = f"{_n(len(xs), word)}: {subject}" if sev != INFO else f"{_n(len(xs), word)} for information ({code}): {subject}"
            out.append(Finding(sev, area, code, subj, _top([i.text for i in xs], 5, "; "),
                               fix if sev != INFO or code in ("COL-05", "TYP-04", "RDY-04") else "No action unless it changes before the next CAB.",
                               s.owner(owner), [i.text.split(":")[0] for i in xs]))
    sm = summary(d, rv)
    out.append(Finding(INFO, "Readiness", "MET-01", f"{sm['upcoming']} changes in the next {s.horizon_days} days, {sm['ready']} ready for the CAB",
                       f"{sm['normal']} normal, {sm['standard']} standard, {sm['emergency']} emergency; {sm['to_approve']} to approve, {sm['pairs']} collisions, "
                       f"{sm['in_freeze']} inside a freeze without exception; last month {pct(sm['rate_last'])} successful",
                       "Track the trend week by week.", s.owner("readiness")))
    out.sort(key=lambda f: (ORDER[f.severity], AREAS.index(f.area), f.code))
    return out


def summary(d: Data, rv: dict) -> dict:
    up, o = rv["upcoming"], rv["outcomes"]
    last = o["months"][-1]
    bm = o["by_month"][last]
    rows = o["rows"]
    code = lambda c: sum(1 for r in rows if any(i.code == c for i in r["issues"]))  # noqa: E731
    incs = [x for x in o["incidents"] if month_key(x["inc"].opened) in (last, month_key(d.today))]
    ready = sum(1 for r in rv["readiness"] if not r["severity"])
    return dict(
        upcoming=len(up), normal=sum(it.c.type == "normal" for it in up), standard=sum(it.c.type == "standard" for it in up),
        emergency=sum(it.c.type == "emergency" for it in up), ready=ready, not_ready=len(up) - ready,
        to_approve=sum(1 for r in rv["readiness"] if any(i.code == "RDY-04" for i in r["issues"])),
        pairs=len(rv["pairs"]), pairs_critical=sum(1 for r in rv["pairs"] if r["severity"] == CRITICAL),
        overloaded=len(rv["load"]), in_freeze=sum(1 for r in rv["freeze"] if r["severity"]),
        freeze_exceptions=sum(1 for r in rv["freeze"] if not r["severity"]), tier1=sum(it.tier == 1 for it in up),
        last=last, months=o["months"], rates=o["rates"], rate_last=o["rates"][-1], changes_last=bm["changes"], closed_last=bm["closed"],
        failed_last=bm["failed"], emergency_last=bm["emergency"], emergency_share=rv["types"]["shares"][-1], shares=rv["types"]["shares"],
        incidents=len(incs), incidents_linked=sum(x["how"] == "linked" for x in incs), p1=sum(x["inc"].priority == 1 for x in incs),
        overruns=code("OUT-04"), unauthorised=code("OUT-05"), pir_overdue=code("OUT-06"),
        standard_risky=len(rv["types"]["standard"]), emergency_unapproved=len(rv["types"]["emergency"]),
        teams_flagged=[r["team"] for r in rv["teams"] if r["issues"]],
    )


def area_status(findings: list[Finding]) -> dict[str, str]:
    st = {}
    for a in AREAS:
        sev = [f.severity for f in findings if f.area == a and f.severity != INFO]
        st[a] = CRITICAL if CRITICAL in sev else WARNING if sev else "ok"
    return st


def overall(findings: list[Finding]) -> str:
    st = set(area_status(findings).values())
    return VERDICT[CRITICAL] if CRITICAL in st else VERDICT[WARNING] if WARNING in st else VERDICT[None]


def now_label(when: datetime) -> str:
    return f"{when:%a %d %b %Y}"


__all__ = ["AREAS", "CRITICAL", "WARNING", "INFO", "Finding", "Issue", "Item", "review", "run_all", "summary", "area_status", "overall", "Freeze"]
