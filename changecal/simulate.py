"""Fictional demo: Fabrikam Bank, a made-up bank with a trading floor, reviewed on Monday 2 November 2026, the morning before the weekly
CAB: three months of change requests and the next two weeks, the CI to service map with tiers and dependencies, the freeze register, the
incidents and the approvals, as a ServiceNow export would give them (display values), with the problems placed on purpose among the
everyday changes. Every CI, change, incident and person is made up."""
from __future__ import annotations

import csv
import json
import random
from datetime import date, datetime, timedelta
from pathlib import Path

ORG = "Fabrikam Bank"
AS_OF = datetime(2026, 11, 2, 8, 0)
SEED = 40
NET, NSEC, WIN, UNX, DBA, STO, TPS, MID, EUC = ("Network", "Network Security", "Windows Server", "Unix & Linux", "Database", "Storage & Backup",
                                                "Trading Platform Support", "Middleware & Integration", "Workplace (EUC)")
TEAMS = [NET, NSEC, WIN, UNX, DBA, STO, TPS, MID, EUC]
ALL_DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]

SETTINGS = {
    "organisation": ORG,
    "as_of": "2026-11-02 08:00",
    "horizon_days": 14,
    "cab_weekday": "tue",
    "cab_time": "10:00",
    "lead_time_days": {"normal": {"very high": 10, "high": 10, "moderate": 5, "low": 3, "not assessed": 5}, "standard": {}, "emergency": {}},
    "plans_required": {"normal": ["backout", "test", "implementation"], "emergency": ["backout", "implementation"], "standard": []},
    "maintenance_windows": {
        "1": [{"days": ALL_DAYS, "start": "22:00", "end": "06:00"}, {"days": ["sat"], "start": "06:00", "end": "42:00"}],
        "2": [{"days": ALL_DAYS, "start": "20:00", "end": "06:00"}, {"days": ["sat"], "start": "06:00", "end": "54:00"}],
        "3": [],
    },
    "max_changes_per_team_night": 3,
    "collision_max_tier": 2,
    "freeze_allows_emergency": True,
    "freeze_allows_standard": False,
    "incident_window_hours": 24,
    "suspected_max_priority": 2,
    "pir_due_days": 5,
    "pir_required_for": ["unsuccessful", "successful_issues", "emergency", "incident"],
    "overrun_tolerance_minutes": 30,
    "retro_approval_days": 2,
    "success_target": 0.95,
    "team_success_min": 0.8,
    "team_min_changes": 5,
    "emergency_share_max": 0.1,
    "team_emergency_share_max": 0.2,
    "standard_risky_match": "firmware|upgrade|migrat|replace|re-?platform",
    "trend_months": 3,
    "teams": TEAMS,
    "owners": {"readiness": "Change manager", "collisions": "Change manager", "types": "Change manager", "outcomes": "Change manager",
               "teams": "Head of IT operations"},
}

SERVICES = [  # name, tier, owner group, depends on
    ("Core network", 1, NET, []),
    ("Data centre firewalls", 1, NSEC, ["Core network"]),
    ("SAN storage", 1, STO, ["Core network"]),
    ("Active Directory and DNS", 1, WIN, ["Core network"]),
    ("Trading database", 1, DBA, ["SAN storage", "Core network"]),
    ("Market data distribution", 1, TPS, ["Core network", "Data centre firewalls"]),
    ("Trading platform", 1, TPS, ["Trading database", "Market data distribution", "Data centre firewalls", "Active Directory and DNS"]),
    ("Payments gateway", 1, MID, ["Data centre firewalls", "SAN storage", "Active Directory and DNS"]),
    ("General ledger", 2, MID, ["SAN storage", "Active Directory and DNS"]),
    ("Client portal", 2, MID, ["Data centre firewalls", "Active Directory and DNS"]),
    ("Risk reporting", 2, UNX, ["Trading database"]),
    ("Backup", 2, STO, ["SAN storage"]),
    ("Monitoring", 2, UNX, ["Core network"]),
    ("Email and collaboration", 2, EUC, ["Active Directory and DNS"]),
    ("Workplace devices", 3, EUC, ["Active Directory and DNS"]),
    ("Print and scan", 3, EUC, []),
]
TIER_LABEL = {1: "1 - most critical", 2: "2 - somewhat critical", 3: "3 - less critical"}
CIS = [  # ci, class, service
    ("fbk-cs-core01", "cmdb_ci_ip_switch", "Core network"), ("fbk-cs-core02", "cmdb_ci_ip_switch", "Core network"),
    ("fbk-as-fl301", "cmdb_ci_ip_switch", "Workplace devices"),
    ("fbk-fw-dc01", "cmdb_ci_ip_firewall", "Data centre firewalls"), ("fbk-fw-dc02", "cmdb_ci_ip_firewall", "Data centre firewalls"),
    ("fbk-san01", "cmdb_ci_storage_device", "SAN storage"),
    ("fbk-dc01", "cmdb_ci_win_server", "Active Directory and DNS"), ("fbk-dc02", "cmdb_ci_win_server", "Active Directory and DNS"),
    ("fbk-trd-db01", "cmdb_ci_db_ora_instance", "Trading database"), ("fbk-trd-db02", "cmdb_ci_db_ora_instance", "Trading database"),
    ("fbk-md-dist01", "cmdb_ci_linux_server", "Market data distribution"), ("fbk-md-dist02", "cmdb_ci_linux_server", "Market data distribution"),
    ("fbk-md-lb01", "cmdb_ci_lb", "Market data distribution"),
    ("fbk-trd-app01", "cmdb_ci_linux_server", "Trading platform"), ("fbk-trd-app02", "cmdb_ci_linux_server", "Trading platform"),
    ("fbk-trd-oms", "cmdb_ci_appl", "Trading platform"), ("fbk-trd-fix01", "cmdb_ci_linux_server", "Trading platform"),
    ("fbk-pay-gw01", "cmdb_ci_linux_server", "Payments gateway"), ("fbk-pay-gw02", "cmdb_ci_linux_server", "Payments gateway"),
    ("fbk-pay-mq01", "cmdb_ci_linux_server", "Payments gateway"),
    ("fbk-gl-app01", "cmdb_ci_win_server", "General ledger"), ("fbk-gl-app02", "cmdb_ci_win_server", "General ledger"),
    ("fbk-gl-db01", "cmdb_ci_db_mssql_instance", "General ledger"),
    ("fbk-portal-web01", "cmdb_ci_linux_server", "Client portal"), ("fbk-portal-web02", "cmdb_ci_linux_server", "Client portal"),
    ("fbk-risk-app01", "cmdb_ci_linux_server", "Risk reporting"), ("fbk-risk-db01", "cmdb_ci_db_ora_instance", "Risk reporting"),
    ("fbk-bkp01", "cmdb_ci_server", "Backup"), ("fbk-bkp02", "cmdb_ci_server", "Backup"),
    ("fbk-mon01", "cmdb_ci_linux_server", "Monitoring"),
    ("fbk-exch-hyb01", "cmdb_ci_win_server", "Email and collaboration"), ("fbk-mtr-pool", "cmdb_ci_appl", "Email and collaboration"),
    ("fbk-mecm01", "cmdb_ci_win_server", "Workplace devices"), ("fbk-fs01", "cmdb_ci_win_server", "Workplace devices"),
    ("fbk-fs02", "cmdb_ci_win_server", "Workplace devices"), ("fbk-intune", "cmdb_ci_appl", "Workplace devices"),
    ("fbk-prn01", "cmdb_ci_win_server", "Print and scan"),
]
SVC_OF = {c: s for c, _, s in CIS}
TIER = {n: t for n, t, _, _ in SERVICES}

PEOPLE = {
    NET: ("Tomasz Kowal", "Aisha Rahman"), NSEC: ("Noah Fischer", "Lucía Romero"), WIN: ("Daniel Okoro", "Hannah Weber"),
    UNX: ("Marco Bianchi", "Sven Larsen"), DBA: ("Ravi Menon", "Claire Dubois"), STO: ("Pieter de Vries", "Olga Petrova"),
    TPS: ("James Whitfield", "Mei Lin"), MID: ("Kofi Mensah", "Laura Gómez"), EUC: ("Sophie Martin", "Arjun Patel"),
}
MANAGERS = {NET: "Grace Holloway", NSEC: "Ivan Horvat", WIN: "Fatima Zahra", UNX: "Lars Nilsson", DBA: "Anna Kowalczyk", STO: "Bruno Costa",
            TPS: "Oliver Grant", MID: "Nadia Haddad", EUC: "Tom Becker"}
CHANGE_MANAGER = "Elena Vasquez"

# group: [(description, ci, risk, impact, can be standard)]
TEMPLATES = {
    NET: [("Core switches: add VLAN and trunk for new rack", "fbk-cs-core01", "Moderate", 2, False),
          ("Core uplink: replace faulty optic", "fbk-cs-core02", "Moderate", 2, False),
          ("Network devices: update NTP and syslog targets", "fbk-cs-core01", "Low", 3, True),
          ("Floor 3 access switch: IOS XE update", "fbk-as-fl301", "Low", 3, True)],
    NSEC: [("Firewall rule request: new application flow", "fbk-fw-dc01", "Low", 3, True),
           ("Firewall: remove unused rules", "fbk-fw-dc01", "Moderate", 2, False),
           ("Firewall: threat prevention content update", "fbk-fw-dc02", "Low", 3, True),
           ("Remote access VPN: renew gateway certificate", "fbk-fw-dc02", "Moderate", 2, False)],
    WIN: [("Monthly Windows updates: file servers", "fbk-fs01", "Low", 3, True),
          ("Monthly Windows updates: domain controllers", "fbk-dc01", "Moderate", 2, False),
          ("Monthly Windows updates: general ledger application servers", "fbk-gl-app01", "Low", 3, True),
          ("Exchange hybrid server: cumulative update", "fbk-exch-hyb01", "Moderate", 2, False),
          ("Group Policy: screen lock settings", "fbk-dc02", "Low", 3, False)],
    UNX: [("RHEL monthly patching: risk reporting servers", "fbk-risk-app01", "Low", 3, True),
          ("RHEL monthly patching: monitoring server", "fbk-mon01", "Low", 3, True),
          ("Monitoring: new alert rules for trading hosts", "fbk-mon01", "Low", 3, True),
          ("Risk engine: JVM memory settings", "fbk-risk-app01", "Moderate", 2, False)],
    DBA: [("Trading database: statistics job schedule", "fbk-trd-db01", "Low", 3, False),
          ("Trading database: index rebuild", "fbk-trd-db02", "Moderate", 2, False),
          ("Trading database: add datafile to tablespace", "fbk-trd-db01", "Low", 3, True),
          ("Risk reporting database: parameter change", "fbk-risk-db01", "Low", 3, False)],
    STO: [("Backup: retention policy change", "fbk-bkp01", "Low", 3, True),
          ("SAN: expand volume for the general ledger", "fbk-san01", "Moderate", 2, True),
          ("Backup servers: monthly patching", "fbk-bkp02", "Low", 3, True),
          ("SAN: zoning for new host", "fbk-san01", "Moderate", 2, False)],
    TPS: [("Trading platform: OMS release", "fbk-trd-oms", "High", 1, False),
          ("Market data: add exchange feed", "fbk-md-dist01", "Moderate", 2, False),
          ("Trading platform: new instrument set-up", "fbk-trd-app01", "Low", 3, True),
          ("Trading platform: hotfix from the vendor", "fbk-trd-app02", "Moderate", 2, False)],
    MID: [("Payments gateway: release", "fbk-pay-gw01", "High", 1, False),
          ("General ledger: interface mapping change", "fbk-gl-app02", "Moderate", 2, False),
          ("Client portal: release", "fbk-portal-web01", "Moderate", 2, False),
          ("Payments message queue: configuration change", "fbk-pay-mq01", "Moderate", 2, False),
          ("Client portal: renew TLS certificate", "fbk-portal-web02", "Low", 3, True)],
    EUC: [("Intune: compliance policy change", "fbk-intune", "Low", 3, True),
          ("Desktops: deploy application update", "fbk-mecm01", "Low", 3, True),
          ("Meeting rooms: Teams Rooms update", "fbk-mtr-pool", "Low", 3, True),
          ("Printers: driver update", "fbk-prn01", "Low", 3, True)],
}
MONTHLY = {NET: 6, NSEC: 8, WIN: 10, UNX: 7, DBA: 6, STO: 5, TPS: 0, MID: 10, EUC: 9}
TPS_PLAN = {"2026-08": (10, 1), "2026-09": (9, 2), "2026-10": (13, 5)}          # changes, emergencies
MID_FAILED = {"2026-08": 3, "2026-09": 4, "2026-10": 4}
TPS_REASONS = ["Order routing rejects on the FIX gateway reported by the desk", "Market data feed handler crash after an exchange change",
               "Vendor hotfix for the allocation bug", "Order routing rejects on the FIX gateway reported by the desk",
               "Pricing latency at the open"]
OTHER_REASONS = ["Security fix for an actively exploited vulnerability", "Service down: restore after a failed disk", "Expired certificate"]

CHG_HEADER = ["number", "short_description", "type", "state", "risk", "impact", "cmdb_ci", "business_service", "assignment_group", "assigned_to",
              "requested_by", "opened_at", "start_date", "end_date", "work_start", "work_end", "approval", "cab_date", "close_code", "backout_plan",
              "test_plan", "implementation_plan", "justification", "outside_maintenance_schedule", "review_status", "review_date"]
FILES = {
    "changes.csv": ("chg", CHG_HEADER),
    "ci-services.csv": ("ci", ["ci", "ci_class", "service", "service_tier", "service_owner", "service_depends_on"]),
    "freezes.csv": ("frz", ["name", "kind", "start", "end", "scope", "approved_exceptions", "reason"]),
    "incidents.csv": ("inc", ["number", "short_description", "priority", "state", "opened_at", "resolved_at", "cmdb_ci", "business_service",
                              "assignment_group", "caused_by"]),
    "approvals.csv": ("apr", ["sysapproval", "approver", "state", "sys_updated_on"]),
}
IMPACT = {1: "1 - High", 2: "2 - Medium", 3: "3 - Low"}
CLOSE = {"successful": "Successful", "successful_issues": "Successful with issues", "unsuccessful": "Unsuccessful"}
FREEZES = [
    ["October month-end close", "freeze", "2026-10-29 18:00", "2026-11-04 07:00", "Trading platform;Trading database;General ledger;Payments gateway",
     "", "Month-end close and regulatory reporting until working day 3"],
    ["Index rebalance", "freeze", "2026-11-13 12:00", "2026-11-14 02:00", "Trading platform;Market data distribution;Trading database", "@FW-FEED",
     "Semi-annual index rebalance: high volumes at the close"],
    ["Year-end change freeze", "freeze", "2026-12-18 18:00", "2027-01-04 07:00", "global", "", "Year-end: emergency changes only"],
]


def _t(v: datetime | None) -> str:
    return v.strftime("%Y-%m-%d %H:%M:%S") if v else ""


def impacted(service: str) -> set[str]:
    up = {}
    for n, _, _, deps in SERVICES:
        for x in deps:
            up.setdefault(x, set()).add(n)
    out, todo = {service}, [service]
    while todo:
        for y in up.get(todo.pop(), ()):
            if y not in out:
                out.add(y)
                todo.append(y)
    return out


def plans(desc: str, ci: str, rnd: random.Random) -> tuple[str, str, str]:
    mins = rnd.choice([15, 20, 30, 45])
    return (f"Roll back to the previous version/configuration of {ci} (backup taken before the change); about {mins} minutes; decision point at "
            f"half the window",
            rnd.choice(["Smoke test from the runbook and sign-off by the service owner", "Health checks and a test transaction, monitored for 30 minutes",
                        "Tested in the UAT environment; post-change checks in the runbook"]),
            f"Step by step in the attached runbook for '{desc}'")


class Gen:
    def __init__(self) -> None:
        self.rnd = random.Random(SEED)
        self.chg: list[dict] = []
        self.inc: list[dict] = []
        self.apr: list[list] = []
        self.busy: list[tuple[datetime, datetime, set[str]]] = []

    def change(self, group, desc, ci, typ, risk, impact, start, minutes, **kw) -> dict:
        rnd = self.rnd
        b, t, i = plans(desc, ci, rnd)
        lead = {"Normal": timedelta(days=rnd.randint(6, 14), hours=rnd.randint(0, 8)), "Standard": timedelta(days=rnd.randint(1, 4), hours=rnd.randint(0, 8)),
                "Emergency": timedelta(minutes=rnd.randint(30, 240))}[typ]
        c = dict(group=group, desc=desc, ci=ci, service=SVC_OF[ci] if rnd.random() < 0.6 else "", type=typ, risk=risk, impact=impact, start=start,
                 end=start + timedelta(minutes=minutes), opened=start - lead, backout=b, test=t, impl=i, justification="", approval="Approved",
                 state="Closed", close="successful", work=None, review="", pir_pending=False, assigned=PEOPLE[group][rnd.randint(0, 1)],
                 cab=None, approvals="auto", outside="false")
        if typ == "Standard":
            c["test"] = ""
        c.update(kw)
        self.chg.append(c)
        return c


def _night_start(rnd: random.Random, day: date, tier: int, standard: bool) -> datetime:
    if tier == 3 and standard and rnd.random() < 0.5:
        h = rnd.choice([12, 13, 17, 18])
    elif day.weekday() == 5 and rnd.random() < 0.5:
        h = rnd.choice([8, 10, 14])
    else:
        h = rnd.choice([22, 22, 23]) if tier == 1 else rnd.choice([20, 21, 22])
    return datetime(day.year, day.month, day.day, h, rnd.choice([0, 0, 30]))


def history(g: Gen) -> None:
    rnd = g.rnd
    for month, ndays in (("2026-08", 31), ("2026-09", 30), ("2026-10", 31)):
        y, m = map(int, month.split("-"))
        for group in TEAMS:
            if group == TPS:
                n, n_emg = TPS_PLAN[month]
            else:
                n, n_emg = MONTHLY[group] + rnd.randint(-1, 1), 0
            made = []
            for k in range(n):
                desc, ci, risk, impact, std_ok = TEMPLATES[group][rnd.randrange(len(TEMPLATES[group]))]
                day = date(y, m, rnd.randint(1, ndays))
                typ = "Standard" if std_ok and rnd.random() < 0.7 else "Normal"
                if group == TPS and k < n_emg:
                    typ = "Emergency"
                elif group != TPS and rnd.random() < 0.035:
                    typ = "Emergency"
                start = _night_start(rnd, day, TIER[SVC_OF[ci]], typ == "Standard")
                c = g.change(group, desc if typ != "Emergency" else desc.split(":")[0] + ": emergency fix", ci, typ, risk, impact, start,
                             rnd.choice([60, 90, 120, 180]))
                if typ == "Emergency":
                    c["justification"] = TPS_REASONS[(k + len(month)) % len(TPS_REASONS)] if group == TPS else rnd.choice(OTHER_REASONS)
                if rnd.random() < 0.025:
                    c["close"] = "unsuccessful"
                elif rnd.random() < 0.06:
                    c["close"] = "successful_issues"
                made.append(c)
            if group == MID:
                for c in rnd.sample(made, MID_FAILED[month]):
                    c["close"] = "unsuccessful"
            if group == TPS and month == "2026-10":
                made[0]["approvals"] = made[1]["approvals"] = "none"       # emergency changes never approved
                made[0]["approval"] = made[1]["approval"] = "Requested"
                made[0]["pir_pending"] = True
            if group == MID and month in ("2026-09", "2026-10"):
                failed = sorted((c for c in made if c["close"] == "unsuccessful"), key=lambda c: c["start"])
                for c in failed[: 2 if month == "2026-10" else 1]:
                    c["pir_pending"] = True
    # overruns in October
    octo = sorted((c for c in g.chg if c["start"].month == 10 and c["type"] == "Normal"), key=lambda c: (c["start"], c["desc"]))
    for c in rnd.sample(octo, 3):
        c["overrun"] = rnd.choice([45, 70, 110])


def planted_history(g: Gen) -> None:
    # 1. The market data load balancer change that preceded a P1 two hours after it finished.
    lb = g.change(TPS, "Market data: load balancer pool change on fbk-md-lb01", "fbk-md-lb01", "Normal", "Moderate", 2, datetime(2026, 10, 21, 5, 0), 60,
                  service="Market data distribution", work=(datetime(2026, 10, 21, 5, 2), datetime(2026, 10, 21, 5, 41)), pir_pending=True)
    g.inc.append(dict(desc="Trading desks: market data prices stale on all screens at the open", prio=1, opened=datetime(2026, 10, 21, 7, 44),
                      resolved=datetime(2026, 10, 21, 9, 5), ci="fbk-md-lb01", service="Market data distribution", group=TPS, caused=lb))
    # 2. Certificate replaced without a change; transfers fail next morning; the change is raised afterwards.
    cert = g.change(MID, "Payments gateway: replace certificate on the SFTP endpoint", "fbk-pay-gw01", "Normal", "Moderate", 2,
                    datetime(2026, 10, 13, 18, 0), 30, opened=datetime(2026, 10, 14, 11, 30), close="successful_issues",
                    work=(datetime(2026, 10, 13, 18, 2), datetime(2026, 10, 13, 18, 25)), approvals="late", review="Complete")
    g.inc.append(dict(desc="Payments gateway: SFTP transfers to the clearing house failing", prio=2, opened=datetime(2026, 10, 14, 9, 10),
                      resolved=datetime(2026, 10, 14, 12, 40), ci="fbk-pay-gw01", service="Payments gateway", group=MID, caused=cert))
    # 3. Implemented on Saturday, approved at the CAB the Tuesday after.
    g.change(DBA, "General ledger database: SQL Server cumulative update", "fbk-gl-db01", "Normal", "Moderate", 2, datetime(2026, 10, 24, 22, 0), 120,
             opened=datetime(2026, 10, 16, 15, 20), approvals="after")
    # 4. A release followed by a P2 the next morning, not linked to the change.
    g.change(MID, "Client portal: release 26.10", "fbk-portal-web01", "Normal", "Moderate", 2, datetime(2026, 10, 26, 22, 0), 90,
             work=(datetime(2026, 10, 26, 22, 4), datetime(2026, 10, 26, 23, 26)))
    g.inc.append(dict(desc="Client portal: login errors for some clients", prio=2, opened=datetime(2026, 10, 27, 8, 15),
                      resolved=datetime(2026, 10, 27, 10, 50), ci="fbk-portal-web01", service="Client portal", group=MID, caused=None))


def upcoming(g: Gen) -> None:
    U = dict(state="Scheduled", close="", review="")
    a = g.change(NSEC, "Data centre firewalls: PAN-OS upgrade on the HA pair", "fbk-fw-dc01", "Normal", "High", 1, datetime(2026, 11, 5, 22, 0), 240,
                 opened=datetime(2026, 10, 22, 11, 5), state="Authorize", approval="Requested", cab=datetime(2026, 11, 3, 10, 0), **{"close": "", "review": ""})
    b = g.change(NET, "Core switches: NX-OS upgrade on fbk-cs-core01", "fbk-cs-core01", "Normal", "High", 1, datetime(2026, 11, 5, 23, 0), 240,
                 opened=datetime(2026, 10, 23, 9, 40), state="Authorize", approval="Requested", cab=datetime(2026, 11, 3, 10, 0), **{"close": "", "review": ""})
    c = g.change(DBA, "Trading database: Oracle 19c release update on fbk-trd-db01", "fbk-trd-db01", "Normal", "High", 1, datetime(2026, 11, 3, 22, 0), 180,
                 opened=datetime(2026, 10, 19, 14, 10), cab=datetime(2026, 10, 27, 10, 0), **U)
    d = g.change(MID, "Payments gateway: move the message store to a new storage volume", "fbk-pay-mq01", "Normal", "High", 1,
                 datetime(2026, 11, 4, 22, 0), 240, opened=datetime(2026, 11, 2, 7, 30), state="Authorize", approval="Requested",
                 cab=datetime(2026, 11, 3, 10, 0), backout="", **{"close": "", "review": ""})
    e = g.change(STO, "SAN controller firmware upgrade on fbk-san01", "fbk-san01", "Standard", "Low", 2, datetime(2026, 11, 7, 20, 0), 360,
                 opened=datetime(2026, 10, 30, 16, 0), **U)
    f = g.change(TPS, "Trading platform: fix for order routing rejects on the FIX gateway", "fbk-trd-fix01", "Emergency", "Moderate", 2,
                 datetime(2026, 11, 2, 22, 0), 60, opened=datetime(2026, 11, 2, 7, 10), justification=TPS_REASONS[0], **U)
    win = []
    for k, (desc, ci) in enumerate([("Monthly Windows updates: file servers", "fbk-fs01"), ("Monthly Windows updates: print server", "fbk-prn01"),
                                    ("Monthly Windows updates: general ledger application servers", "fbk-gl-app01"),
                                    ("Monthly Windows updates: MECM site server", "fbk-mecm01")]):
        win.append(g.change(WIN, desc, ci, "Standard", "Low", 3, datetime(2026, 11, 8, 19, 0) + timedelta(minutes=90 * k), 80,
                            opened=datetime(2026, 10, 29, 10, 0) + timedelta(hours=k), **U))
    h = g.change(MID, "Client portal: renew TLS certificate on fbk-portal-web02", "fbk-portal-web02", "Normal", "Low", 3, datetime(2026, 11, 11, 13, 0), 30,
                 opened=datetime(2026, 10, 26, 9, 0), cab=datetime(2026, 10, 27, 10, 0), **U)
    fw = g.change(NSEC, "Market data: firewall rule for the new exchange feed", "fbk-fw-dc02", "Normal", "Moderate", 2, datetime(2026, 11, 13, 22, 0), 60,
                  opened=datetime(2026, 10, 20, 13, 0), cab=datetime(2026, 10, 27, 10, 0), **U)
    FREEZES[1][5] = "@FW-FEED"
    fw["tag"] = "FW-FEED"
    j = g.change(UNX, "Risk reporting: Python runtime upgrade", "fbk-risk-app01", "Normal", "", 2, datetime(2026, 11, 10, 21, 0), 120,
                 opened=datetime(2026, 10, 28, 12, 0), state="Assess", approval="Requested", cab=datetime(2026, 11, 10, 10, 0), **{"close": "", "review": ""})
    k = g.change(DBA, "Trading database: purge of 2019 order history", "fbk-trd-db02", "Normal", "Low", 1, datetime(2026, 11, 9, 22, 0), 180,
                 opened=datetime(2026, 10, 21, 10, 0), state="Authorize", approval="Requested", cab=datetime(2026, 11, 3, 10, 0), **{"close": "", "review": ""})
    m = g.change(EUC, "Meeting rooms: Teams Rooms update", "fbk-mtr-pool", "Standard", "Low", 3, datetime(2026, 11, 12, 20, 0), 60,
                 opened=datetime(2026, 10, 30, 9, 0), assigned="", **U)
    m["group"] = ""
    for x in [a, b, c, d, e, f, h, fw, j, k, m] + win:
        x["service"] = x["service"] or ""
        g.busy.append((x["start"], x["end"], impacted(SVC_OF[x["ci"]])))
    # everyday changes in the next two weeks, kept clear of each other, of the freezes and of the planted ones
    rnd = g.rnd
    nights: dict = {}
    for x in [a, b, c, d, e, f, h, fw, j, k, m] + win:
        nights[(x["group"], (x["start"] - timedelta(hours=6)).date())] = nights.get((x["group"], (x["start"] - timedelta(hours=6)).date()), 0) + 1
    frz = [(datetime.strptime(s, "%Y-%m-%d %H:%M"), datetime.strptime(e2, "%Y-%m-%d %H:%M"), set(sc.split(";"))) for _, _, s, e2, sc, _, _ in FREEZES[:2]]
    for dd in range(14):
        day = date(2026, 11, 2) + timedelta(days=dd)
        for group in TEAMS:
            if rnd.random() > (0.42 if day.weekday() < 5 else 0.2):
                continue
            desc, ci, risk, impact, std_ok = TEMPLATES[group][rnd.randrange(len(TEMPLATES[group]))]
            typ = "Standard" if std_ok and rnd.random() < 0.7 else "Normal"
            svc = SVC_OF[ci]
            start = _night_start(rnd, day, TIER[svc], typ == "Standard")
            if start < datetime(2026, 11, 2, 18, 0):
                continue
            end = start + timedelta(minutes=rnd.choice([60, 90, 120]))
            imp = impacted(svc)
            if any(s0 < end and start < e0 and (imp & i0) for s0, e0, i0 in g.busy):
                continue
            if any(s0 < end and start < e0 and (imp & sc) for s0, e0, sc in frz):
                continue
            key = (group, (start - timedelta(hours=6)).date())
            if nights.get(key, 0) >= 2:
                continue
            nights[key] = nights.get(key, 0) + 1
            g.busy.append((start, end, imp))
            st = dict(state="Scheduled", approval="Approved", close="", review="")
            if typ == "Normal" and start >= datetime(2026, 11, 3, 10, 0) and rnd.random() < 0.6:
                st = dict(state="Authorize", approval="Requested", close="", review="",
                          cab=datetime(2026, 11, 3, 10, 0) if start < datetime(2026, 11, 10, 10, 0) else datetime(2026, 11, 10, 10, 0))
            elif typ == "Normal":
                st["cab"] = datetime(2026, 10, 27, 10, 0)
            x = g.change(group, desc, ci, typ, risk, impact, start, int((end - start).total_seconds() // 60), **st)
            lead = (x["start"] - AS_OF).days
            if typ == "Normal" and (x["start"] - x["opened"]).days < 6:
                x["opened"] = x["start"] - timedelta(days=7 + rnd.randint(0, 5))
            if x["opened"] > AS_OF:
                x["opened"] = AS_OF - timedelta(hours=rnd.randint(2, 30) + lead)


def finish(g: Gen) -> dict:
    rnd = g.rnd
    out = {"chg": [], "ci": [], "frz": [], "inc": [], "apr": []}
    chg = sorted(g.chg, key=lambda c: (c["opened"], c["desc"], c["ci"]))
    for k, c in enumerate(chg):
        c["number"] = f"CHG{41000 + k:07d}"
    tags = {c.get("tag"): c["number"] for c in chg if c.get("tag")}
    for f in FREEZES:
        f[5] = ";".join(tags.get(x[1:], x) for x in f[5].split(";")) if f[5] else ""
    for c in chg:
        future = c["start"] >= AS_OF
        ws = we = None
        if not future:
            if c["work"]:
                ws, we = c["work"]
            else:
                ws = c["start"] + timedelta(minutes=rnd.randint(0, 10))
                dur = (c["end"] - c["start"]).total_seconds() / 60
                we = ws + timedelta(minutes=round(dur * (rnd.uniform(0.9, 1.0) if c["close"] == "unsuccessful" else rnd.uniform(0.5, 0.92))))
                if c.get("overrun"):
                    we = c["end"] + timedelta(minutes=c["overrun"])
            if we >= AS_OF - timedelta(days=3) and c["state"] == "Closed":
                c["state"] = "Review"
        need_pir = c["close"] in ("unsuccessful", "successful_issues") or c["type"] == "Emergency" or any(i["caused"] is c for i in g.inc)
        review, rdate = "", None
        if not future and need_pir and not c["pir_pending"]:
            if we + timedelta(days=5) < AS_OF or c["review"] == "Complete":
                review, rdate = "Complete", we + timedelta(days=rnd.randint(2, 4), hours=rnd.randint(1, 6))
        # approvals
        cab = c["cab"]
        if c["type"] == "Normal" and not future and not cab:
            day = c["start"].date() - timedelta(days=(c["start"].weekday() - 1) % 7 or 7)
            cab = datetime(day.year, day.month, day.day, 10, 0)
            if cab < c["opened"]:
                cab = c["opened"] + timedelta(hours=3)
        if c["type"] == "Normal":
            tech = c["opened"] + timedelta(hours=rnd.randint(3, 26))
            if c["approvals"] == "late":
                tech, cab = datetime(2026, 10, 14, 15, 0), datetime(2026, 10, 20, 10, 0)
            if c["approvals"] == "after":
                cab = datetime(2026, 10, 27, 10, 0)
            tech = min(tech, cab - timedelta(hours=1))
            mgr = MANAGERS[c["group"]] if c["group"] else CHANGE_MANAGER
            if tech < AS_OF:
                out["apr"].append([c["number"], mgr, "Approved", _t(tech)])
            else:
                out["apr"].append([c["number"], mgr, "Requested", _t(c["opened"] + timedelta(minutes=5))])
            if c["approval"] == "Approved":
                out["apr"].append([c["number"], CHANGE_MANAGER, "Approved", _t(cab)])
            else:
                out["apr"].append([c["number"], CHANGE_MANAGER, "Requested", _t(min(c["opened"] + timedelta(hours=2), AS_OF - timedelta(minutes=10)))])
        elif c["type"] == "Emergency" and c["approvals"] != "none":
            when = min(c["start"] - timedelta(minutes=rnd.randint(10, 25)), c["opened"] + timedelta(minutes=20))
            out["apr"].append([c["number"], f"{MANAGERS[c['group']]} (ECAB)", "Approved", _t(when)])
        out["chg"].append([c["number"], c["desc"], c["type"], c["state"], c["risk"], IMPACT[c["impact"]], c["ci"], c["service"], c["group"], c["assigned"],
                           PEOPLE[c["group"]][1] if c["group"] else "Arjun Patel", _t(c["opened"]), _t(c["start"]), _t(c["end"]), _t(ws), _t(we), c["approval"],
                           _t(cab), CLOSE.get(c["close"], "") if not future else "", c["backout"], c["test"], c["impl"], c["justification"], c["outside"],
                           review, _t(rdate)])
    # background incidents: mostly workplace, a few on servers; some linked to unsuccessful changes
    cis = [x for x in CIS if x[2] in ("Workplace devices", "Print and scan", "Email and collaboration")]
    other = [x for x in CIS if x not in cis]
    t = datetime(2026, 8, 1, 7, 0)
    while t < AS_OF - timedelta(hours=4):
        t += timedelta(hours=rnd.randint(8, 30))
        if t >= AS_OF:
            break
        ci, _, svc = rnd.choice(cis) if rnd.random() < 0.75 else rnd.choice(other)
        grp = next(o for n, _, o, _ in SERVICES if n == svc)
        g.inc.append(dict(desc=rnd.choice(["User cannot connect", "Application slow", "Error opening file", "Printing fails", "Alert: disk space",
                                           "Job failed overnight"]) + f" ({ci})", prio=rnd.choice([3, 4, 4, 4]), opened=t,
                          resolved=t + timedelta(hours=rnd.randint(1, 20)), ci=ci, service=svc, group=grp, caused=None))
    for c in chg:
        if c["close"] == "unsuccessful" and c["start"] < AS_OF and rnd.random() < 0.5 and not any(i["caused"] is c for i in g.inc):
            op = c["end"] + timedelta(minutes=rnd.randint(30, 300))
            if op < AS_OF:
                g.inc.append(dict(desc=f"{SVC_OF[c['ci']]}: errors after the change window", prio=3, opened=op, resolved=op + timedelta(hours=3),
                                  ci=c["ci"], service=SVC_OF[c["ci"]], group=c["group"], caused=c))
    for k, i in enumerate(sorted(g.inc, key=lambda i: (i["opened"], i["desc"]))):
        out["inc"].append([f"INC{102000 + k:07d}", i["desc"], {1: "1 - Critical", 2: "2 - High", 3: "3 - Moderate", 4: "4 - Low"}[i["prio"]],
                           "Closed" if i["resolved"] < AS_OF - timedelta(days=1) else "Resolved", _t(i["opened"]), _t(i["resolved"]), i["ci"], i["service"],
                           i["group"], i["caused"]["number"] if i["caused"] else ""])
    deps = {n: d for n, _, _, d in SERVICES}
    owner = {n: o for n, _, o, _ in SERVICES}
    for ci, cls, svc in sorted(CIS, key=lambda x: (x[2], x[0])):
        out["ci"].append([ci, cls, svc, TIER_LABEL[TIER[svc]], owner[svc], ";".join(deps[svc])])
    out["frz"] = [list(f) for f in FREEZES]
    out["apr"].sort(key=lambda r: (r[0], r[3], r[1]))
    return out


def write(folder: Path) -> Path:
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    FREEZES[1][5] = "@FW-FEED"
    g = Gen()
    history(g)
    planted_history(g)
    upcoming(g)
    rows = finish(g)
    for name, (k, header) in FILES.items():
        with open(folder / name, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh, lineterminator="\n")
            w.writerow(header)
            w.writerows(rows[k])
    (folder / "settings.json").write_text(json.dumps(SETTINGS, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return folder
