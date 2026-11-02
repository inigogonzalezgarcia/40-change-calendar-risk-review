import csv
import hashlib
import json
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path

from changecal import cli
from changecal.checks import CRITICAL, INFO, ORDER, WARNING, area_status, dependents, in_window, overall, review, run_all, summary
from changecal.model import (Approval, Change, Data, Freeze, Incident, Service, load, load_approvals, load_changes, load_ci_services, load_freezes,
                             load_incidents, months_before, settings_from_dict)

AS_OF = datetime(2026, 11, 2, 8, 0)          # Monday; the CAB meets on Tuesday 3 November at 10:00
SERVICES = {"Core": Service("Core", 1, "Network"), "App": Service("App", 1, "Apps", ["Core"]), "Rep": Service("Rep", 2, "Apps", ["App"]),
            "Desk": Service("Desk", 3, "EUC"), "Mail": Service("Mail", 2, "EUC")}
CIS = {"sw1": ["Core"], "app1": ["App"], "app2": ["App"], "rep1": ["Rep"], "pc": ["Desk"], "mx1": ["Mail"]}


def write(path: Path, header: list[str], rows: list[list], delimiter: str = ",") -> Path:
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh, delimiter=delimiter)
        w.writerow(header)
        w.writerows(rows)
    return path


def at(day: int, hour: int = 22, minute: int = 0, month: int = 11) -> datetime:
    return datetime(2026, month, day, hour, minute)


def chg(number="CHG1", start=None, hours=2, ci="app1", **kw) -> Change:
    start = start or at(5)
    c = Change(number, kw.pop("desc", "Change"), kw.pop("type", "normal"), kw.pop("state", "scheduled"), kw.pop("risk", "low"), kw.pop("impact", 3), ci,
               "", kw.pop("group", "Apps"), kw.pop("assigned_to", "A. Person"), "", kw.pop("opened", start - timedelta(days=20)), start,
               start + timedelta(hours=hours), approval=kw.pop("approval", "approved"), backout="Restore", test="Smoke test", implementation="Runbook")
    for k, v in kw.items():
        setattr(c, k, v)
    return c


def done(number, start, ok="successful", hours=2, **kw) -> Change:
    c = chg(number, start, hours, state="closed", **kw)
    c.close_code = ok
    c.work_start = c.work_start or start
    c.work_end = c.work_end or c.end
    return c


def data(changes=(), freezes=(), incidents=(), approvals=None, **raw) -> Data:
    raw.setdefault("maintenance_windows", {"1": [{"days": ["mon", "tue", "wed", "thu", "fri", "sat", "sun"], "start": "22:00", "end": "06:00"},
                                                 {"days": ["sat"], "start": "06:00", "end": "42:00"}]})
    return Data(settings_from_dict(raw), AS_OF, list(changes), dict(SERVICES), dict(CIS), list(freezes), list(incidents), approvals or {})


def issues(rows, code):
    return [i for r in rows for i in r["issues"] if i.code == code]


class TestLoading(unittest.TestCase):
    def test_changes_servicenow_display_values_and_jira_headers(self):
        with tempfile.TemporaryDirectory() as t:
            sn = write(Path(t) / "sn.csv", ["number", "short_description", "type", "state", "risk", "impact", "cmdb_ci", "assignment_group", "opened_at",
                                            "start_date", "end_date", "work_start", "work_end", "approval", "close_code", "backout_plan",
                                            "outside_maintenance_schedule", "review_status"],
                       [["CHG0041001", "Core switch upgrade", "Normal", "Closed", "2 - High", "1 - High", "fbk-cs-core01", "Network", "2026-10-01 09:00:00",
                         "2026-10-10 22:00:00", "2026-10-11 02:00:00", "2026-10-10 22:05:00", "2026-10-11 01:40:00", "Approved", "Successful with issues",
                         "Reload previous image", "true", "Complete"],
                        ["chg0041002", "Patch", "Emergency", "-2", "", "3 - Low", "", "", "", "01/11/2026 20:00", "", "", "", "Requested", "", "", "", ""]],
                       delimiter=";")
            jira = write(Path(t) / "jira.csv", ["Issue key", "Summary", "Change type", "Status", "Change risk", "Planned start", "Planned end",
                                                "Affected services"],
                         [["ITCM-12", "Firmware upgrade", "Standard", "Awaiting implementation", "Medium", "2026-11-07T20:00:00Z", "2026-11-08T02:00:00Z",
                           "SAN storage"]])
            a, b = load_changes(sn)
            j = load_changes(jira)[0]
        self.assertEqual((a.type, a.state, a.risk, a.impact, a.close_code, a.outside_window, a.pir_done, a.done),
                         ("normal", "closed", "high", 1, "successful_issues", True, True, True))
        self.assertEqual((a.work_end, a.finished), (datetime(2026, 10, 11, 1, 40), datetime(2026, 10, 11, 1, 40)))
        self.assertEqual((b.number, b.type, b.state, b.risk, b.approval, b.start), ("CHG0041002", "emergency", "scheduled", "", "requested",
                                                                                    datetime(2026, 11, 1, 20, 0)))
        self.assertEqual((j.number, j.type, j.state, j.risk, j.service, j.start), ("ITCM-12", "standard", "scheduled", "moderate", "SAN storage",
                                                                                   datetime(2026, 11, 7, 20, 0)))

    def test_services_freezes_incidents_approvals_and_settings(self):
        with tempfile.TemporaryDirectory() as t:
            ci = write(Path(t) / "ci.csv", ["ci", "ci_class", "service", "service_tier", "service_owner", "service_depends_on"],
                       [["fbk-trd-db01", "cmdb_ci_db_ora_instance", "Trading database", "1 - most critical", "Database", "SAN storage;Core network"],
                        ["fbk-trd-app01", "cmdb_ci_linux_server", "Trading platform", "1 - most critical", "TPS", "Trading database"],
                        ["fbk-trd-db01", "cmdb_ci_db_ora_instance", "Risk reporting", "2 - somewhat critical", "Unix", ""]])
            fz = write(Path(t) / "fz.csv", ["name", "kind", "start", "end", "scope", "approved_exceptions"],
                       [["Month-end", "freeze", "2026-10-29 18:00", "2026-11-04 07:00", "Trading platform; General ledger", "chg1;CHG2"],
                        ["DC move", "Blackout", "2026-11-20 18:00", "2026-11-22 18:00", "global", ""]])
            inc = write(Path(t) / "inc.csv", ["number", "short_description", "priority", "opened_at", "cmdb_ci", "caused_by"],
                        [["INC1", "Stale prices", "1 - Critical", "2026-10-21 07:44:00", "fbk-md-lb01", "chg0041185"]])
            ap = write(Path(t) / "ap.csv", ["sysapproval", "approver", "state", "sys_updated_on"],
                       [["CHG1", "CAB", "Approved", "2026-10-27 10:00:00"], ["CHG1", "Manager", "Approved", "2026-10-20 09:00:00"]])
            sv, cis = load_ci_services(ci)
            f, i, a = load_freezes(fz), load_incidents(inc), load_approvals(ap)
        self.assertEqual((sv["Trading database"].tier, sv["Risk reporting"].tier, sv["SAN storage"].tier), (1, 2, 3))
        self.assertEqual(cis["fbk-trd-db01"], ["Trading database", "Risk reporting"])
        d = Data(settings_from_dict({}), AS_OF, services=sv, ci_services=cis)
        self.assertEqual(dependents(d)["SAN storage"], {"Trading database", "Trading platform"})
        self.assertEqual((f[0].scope, f[0].exceptions, f[0].is_global, f[1].kind, f[1].is_global), (["Trading platform", "General ledger"], ["CHG1", "CHG2"],
                                                                                                      False, "blackout", True))
        self.assertEqual((i[0].priority, i[0].caused_by), (1, "CHG0041185"))
        self.assertEqual([x.approver for x in a["CHG1"]], ["Manager", "CAB"])
        s = settings_from_dict({"lead_time_days": {"Normal": {"High": 15, "not assessed": 7}}, "owners": {"teams": "COO"}})
        self.assertEqual((s.lead_days(chg(risk="high")), s.lead_days(chg(risk="")), s.lead_days(chg(type="standard")), s.owner("teams"),
                          s.owner("readiness")), (15, 7, 0, "COO", "Change manager"))
        self.assertEqual(months_before(date(2026, 1, 5), 3), ["2025-10", "2025-11", "2025-12"])
        with tempfile.TemporaryDirectory() as t, self.assertRaises(FileNotFoundError):
            write(Path(t) / "incidents.csv", ["number"], [["INC1"]])
            load(Path(t))


class TestReadiness(unittest.TestCase):
    def test_plans_risk_and_lead_time(self):
        cs = [chg("C1", at(6), risk="high", backout="", test="TBD"),                       # no backout, no test, high: critical
              chg("C2", at(6, 1), ci="rep1", type="standard", backout=""),                    # standard: no plans needed
              chg("C3", at(9), ci="app2", risk="low", impact=1),                             # tier 1, impact high -> at least high
              chg("C4", at(10), ci="rep1", risk=""),                                         # not assessed
              chg("C5", at(4), ci="pc", risk="high", opened=at(2, 7, 30)),                   # 2.6 days, lead 10 -> critical
              chg("C6", at(12), ci="mx1", risk="moderate", opened=at(8, 9))]                 # 4.5 days, lead 5 -> warning
        rv = review(data(cs))
        r1 = issues(rv["readiness"], "RDY-01")
        self.assertEqual([(i.severity, i.text.split(" ")[0]) for i in r1], [(CRITICAL, "C1")])
        self.assertIn("no backout plan, no test plan", r1[0].text)
        self.assertEqual(sorted((i.text.split(" ")[0], i.severity) for i in issues(rv["readiness"], "RDY-02")), [("C3", WARNING), ("C4", WARNING)])
        self.assertIn("expected at least high", issues(rv["readiness"], "RDY-02")[0].text)
        self.assertEqual(sorted((i.text.split(" ")[0], i.severity) for i in issues(rv["readiness"], "RDY-03")), [("C5", CRITICAL), ("C6", WARNING)])

    def test_approval_owner_and_maintenance_window(self):
        cs = [chg("C1", at(2, 23), approval="requested"),                                    # before the CAB of Tue 10:00
              chg("C2", at(5), ci="app2", approval="requested"),                             # decide at this CAB
              chg("C3", at(12), ci="rep1", approval="requested"),                            # next week's CAB
              chg("C4", at(6), ci="rep1", approval="rejected"),
              chg("C5", at(7, 20), ci="sw1", group="", assigned_to=""),                      # Sat 20:00 inside the weekend window of tier 1
              chg("C6", at(4, 14), ci="mx1"),                                                # tier 2 has no window in this test: any time
              chg("C7", at(11, 13), ci="sw1"),                                               # Wednesday 13:00 on tier 1: outside
              chg("C8", at(8, 21), hours=12, ci="sw1")]                                      # Sat 06:00 to Sun 18:00 window ends before 09:00 Mon
        rv = review(data(cs))
        self.assertEqual((rv["cab"], rv["cab2"]), (at(3, 10), at(10, 10)))
        got = {i.text.split(" ")[0]: i.severity for i in issues(rv["readiness"], "RDY-04")}
        self.assertEqual(got, {"C1": CRITICAL, "C2": INFO, "C3": INFO, "C4": CRITICAL})
        self.assertEqual([i.text.split(" ")[0] for i in issues(rv["readiness"], "RDY-05")], ["C5"])
        self.assertEqual(sorted(i.text.split(" ")[0] for i in issues(rv["readiness"], "RDY-06")), ["C7", "C8"])
        d = data()
        self.assertTrue(in_window(d, 1, at(7, 1, 0), at(7, 5, 0)))       # Saturday 01:00 to 05:00, the Friday night window
        self.assertFalse(in_window(d, 1, at(6, 21, 0), at(6, 23, 0)))    # starts before 22:00


class TestCollisions(unittest.TestCase):
    def test_same_ci_service_and_dependencies(self):
        cs = [chg("FW", at(5, 22), hours=4, ci="sw1"),          # Core: everything depends on it
              chg("APP", at(5, 23), hours=2, ci="app1"),        # App depends on Core -> shared App and Rep
              chg("APP2", at(6, 0, 30), hours=1, ci="app1"),    # same CI as APP, overlapping
              chg("PC", at(5, 22), hours=3, ci="pc"),            # Desk: tier 3, nothing shared
              chg("REP", at(9, 22), ci="rep1"), chg("REP2", at(9, 23), ci="", service="Rep", type="standard"),   # same service, tier 2
              chg("LATER", at(12, 22), ci="app1")]
        rv = review(data(cs))
        codes = {(r["issues"][0].code, frozenset((r["a"].c.number, r["b"].c.number))): r["severity"] for r in rv["pairs"]}
        self.assertEqual(codes, {("COL-02", frozenset({"FW", "APP"})): CRITICAL, ("COL-02", frozenset({"FW", "APP2"})): CRITICAL,
                                 ("COL-01", frozenset({"APP", "APP2"})): CRITICAL, ("COL-01", frozenset({"REP", "REP2"})): CRITICAL})
        self.assertIn("both affect App, Rep", next(r for r in rv["pairs"] if r["on"] == "App, Rep")["issues"][0].text)
        rv = review(data(cs, collision_max_tier=1))
        self.assertEqual(next(r for r in rv["pairs"] if r["on"] == "Rep")["severity"], WARNING)

    def test_team_night_and_freezes(self):
        cs = [chg(f"W{k}", at(8, 19) + timedelta(minutes=90 * k), hours=1, ci="pc", group="Windows") for k in range(4)]
        cs += [chg("DB", at(3, 22), ci="app1"), chg("EM", at(2, 22), ci="app2", type="emergency"), chg("OK", at(3, 1), ci="app2"),
               chg("STD", at(4, 1), ci="app2", type="standard"), chg("BL", at(14, 10), ci="pc")]
        frz = [Freeze("Month-end", "freeze", at(29, 18, month=10), at(4, 7), ["App"], ["OK"]),
               Freeze("Office move", "blackout", at(14, 0), at(15, 0), [])]
        rv = review(data(cs, frz))
        self.assertEqual([(r["team"], len(r["items"]), r["severity"]) for r in rv["load"]], [("Windows", 4, WARNING)])
        got = {r["item"].c.number: (r["issues"][0].code, r["issues"][0].severity) for r in rv["freeze"]}
        self.assertEqual(got, {"DB": ("COL-04", CRITICAL), "EM": ("COL-05", INFO), "OK": ("COL-05", INFO), "STD": ("COL-04", CRITICAL),
                               "BL": ("COL-04", CRITICAL)})
        rv = review(data(cs, frz, freeze_allows_standard=True))
        self.assertNotIn("STD", {r["item"].c.number for r in rv["freeze"]})


class TestTypes(unittest.TestCase):
    def test_emergency_share_reasons_and_standard_for_risky_work(self):
        cs = [done(f"N{k}", at(1 + k, month=10)) for k in range(8)]
        cs += [done("E1", at(10, month=10), type="emergency", justification="Expired certificate"),
               done("E2", at(12, month=10), type="emergency", justification="Expired certificate."),
               done("E3", at(14, month=10), type="emergency", justification="")]
        cs += [chg("FW", at(7, 20), ci="sw1", type="standard", desc="SAN controller firmware upgrade"),
               chg("PRN", at(7, 20), ci="pc", type="standard", desc="Printer firmware upgrade"),
               chg("HI", at(9), ci="rep1", type="standard", risk="high", desc="Config")]
        rv = review(data(cs))
        ty = rv["types"]
        self.assertAlmostEqual(ty["shares"][-1], 3 / 11)
        t1 = issues([ty["overall"]], "TYP-01")
        self.assertEqual(t1[0].severity, CRITICAL)                       # 27% > twice the 10% target
        self.assertIn("Expired certificate (2); No reason recorded (1)", issues([ty["overall"]], "TYP-04")[0].text)
        got = {r["item"].c.number: r["severity"] for r in ty["standard"]}
        self.assertEqual(got, {"FW": CRITICAL, "HI": WARNING})           # the printer is tier 3

    def test_emergency_retrospective_approval(self):
        cs = [done("E1", at(10, 2, month=10), type="emergency"), done("E2", at(12, 2, month=10), type="emergency"),
              done("E3", at(14, 2, month=10), type="emergency")]
        ap = {"E2": [Approval("E2", "ECAB", "approved", at(12, 1, month=10))], "E3": [Approval("E3", "ECAB", "approved", at(20, 10, month=10))]}
        rv = review(data(cs, approvals=ap))
        self.assertEqual({r["item"].c.number: r["severity"] for r in rv["types"]["emergency"]}, {"E1": CRITICAL, "E3": WARNING})


class TestOutcomes(unittest.TestCase):
    def test_success_rate_unsuccessful_and_overrun(self):
        cs = [done(f"S{k}", at(1 + k, month=10)) for k in range(8)] + [done("F1", at(20, month=10), ok="unsuccessful"),
                                                                        done("F2", at(21, month=10), ok="unsuccessful"),
                                                                        done("SEP", at(15, month=9), ok="unsuccessful")]
        cs[0].work_end = cs[0].end + timedelta(minutes=50)
        cs[1].work_end = cs[1].end + timedelta(minutes=20)
        o = review(data(cs))["outcomes"]
        self.assertEqual(o["months"], ["2026-08", "2026-09", "2026-10"])
        self.assertEqual([None if r is None else round(r, 2) for r in o["rates"]], [None, 0.0, 0.8])
        self.assertEqual(issues([o["overall"]], "OUT-01")[0].severity, CRITICAL)          # 80% < 95% - 10 points
        self.assertEqual(sorted(i.text.split(" ")[0] for i in issues(o["rows"], "OUT-02")), ["F1", "F2"])     # September is not last month
        ov = issues(o["rows"], "OUT-04")
        self.assertEqual([(i.text.split(" ")[0], i.severity) for i in ov], [("S0", WARNING)])
        self.assertIn("50 minutes past the planned end", ov[0].text)

    def test_change_caused_incidents_linked_and_suspected(self):
        cs = [done("LB", at(21, 5, month=10), hours=1, ci="app1"), done("WEB", at(26, 22, month=10), ci="rep1"),
              done("OLD", at(3, 22, month=10), ci="pc")]
        cs[0].work_end = at(21, 5, 41, month=10)
        incs = [Incident("P1", "Stale prices", 1, at(21, 7, 44, month=10), ci="app2", caused_by="LB"),
                Incident("P2", "Login errors", 2, at(27, 8, 15, month=10), ci="rep1"),
                Incident("P3", "Slow", 3, at(27, 9, month=10), ci="rep1"),                 # P3 not linked: not suspected
                Incident("P2b", "Desk", 2, at(5, 9, month=10), ci="pc")]                   # 35 hours later: outside the window
        rv = review(data(cs, incidents=incs))
        o = rv["outcomes"]
        got = [(x["inc"].number, x["item"].c.number, x["how"], round(x["hours"], 1)) for x in o["incidents"]]
        self.assertEqual(got, [("P1", "LB", "linked", 2.0), ("P2", "WEB", "suspected", 8.2)])
        sev = {i.text.split(":")[0]: i.severity for i in issues(o["rows"], "OUT-03")}
        self.assertEqual(sev, {"LB": CRITICAL, "WEB": WARNING})
        self.assertEqual((summary(data(cs, incidents=incs), rv)["p1"], summary(data(cs, incidents=incs), rv)["incidents"]), (1, 2))

    def test_unauthorised_work_and_overdue_reviews(self):
        cert = done("CERT", at(13, 18, month=10), hours=1, ok="successful_issues", opened=at(14, 11, 30, month=10))
        sql = done("SQL", at(24, 22, month=10))
        emg = done("EMG", at(20, 9, month=10), type="emergency", opened=at(21, 9, month=10))
        late = done("LATE", at(26, 20, month=10), ok="unsuccessful")                           # due 31 Oct 22:00 -> 1 day overdue
        okp = done("OKP", at(5, 22, month=10), ok="unsuccessful", review_status="Complete")
        p1 = done("P1C", at(26, 5, month=10), hours=1)
        cs = [cert, sql, emg, late, okp, p1]
        ap = {"SQL": [Approval("SQL", "CAB", "approved", at(27, 10, month=10))], "CERT": [Approval("CERT", "CAB", "approved", at(20, 10, month=10))],
              "EMG": [Approval("EMG", "ECAB", "approved", at(20, 8, month=10))], "LATE": [Approval("LATE", "CAB", "approved", at(20, 10, month=10))],
              "OKP": [Approval("OKP", "CAB", "approved", at(1, 10, month=10))], "P1C": [Approval("P1C", "CAB", "approved", at(20, 10, month=10))]}
        incs = [Incident("INC1", "Outage", 1, at(26, 8, month=10), ci="app1", caused_by="P1C")]
        rv = review(data(cs, incidents=incs, approvals=ap, pir_due_days=5))
        un = {i.text.split(" ")[0]: i.text for i in issues(rv["outcomes"]["rows"], "OUT-05")}
        self.assertEqual(sorted(un), ["CERT", "EMG", "SQL"])
        self.assertIn("raised Wed 14 Oct 11:30, after the work started", un["CERT"])
        self.assertIn("approved Tue 27 Oct 10:00, after the work started", un["SQL"])
        pir = {i.text.split(" ")[0]: i.severity for i in issues(rv["outcomes"]["rows"], "OUT-06")}
        self.assertEqual(pir, {"CERT": CRITICAL, "EMG": WARNING, "LATE": WARNING, "P1C": CRITICAL})   # CERT 13 days late; P1C caused a P1


class TestTeamsAndVerdict(unittest.TestCase):
    def test_teams_low_success_and_rising_emergencies(self):
        cs = []
        for m, (n, e) in {8: (10, 1), 9: (9, 2), 10: (10, 4)}.items():
            cs += [done(f"T{m}-{k}", at(1 + k, month=m), group="Trading", type="emergency" if k < e else "normal") for k in range(n)]
            cs += [done(f"M{m}-{k}", at(1 + k, month=m), group="Middleware", ok="unsuccessful" if k < 4 else "successful") for k in range(10)]
        rv = review(data(cs))
        t = {r["team"]: r for r in rv["teams"]}
        self.assertEqual([round(x, 2) for x in t["Trading"]["monthly"]], [0.1, 0.22, 0.4])
        self.assertEqual([(i.code, i.severity) for i in t["Trading"]["issues"]], [("TEAM-02", WARNING)])
        self.assertIn("rising", t["Trading"]["issues"][0].text)
        self.assertEqual([(i.code, i.severity) for i in t["Middleware"]["issues"]], [("TEAM-01", CRITICAL)])
        self.assertAlmostEqual(t["Middleware"]["rate"], 0.6)

    def test_status_by_area_and_overall(self):
        hist = [done(f"S{k}", at(1 + k, month=10)) for k in range(10)]
        f = run_all(data(hist + [chg("OK", at(5), ci="rep1")]))
        self.assertEqual((overall(f), set(area_status(f).values())), ("on track", {"ok"}))
        f = run_all(data(hist + [chg("OK", at(5), ci="rep1", risk="")]))
        self.assertEqual((overall(f), area_status(f)["Readiness"]), ("attention", WARNING))
        f = run_all(data(hist + [chg("OK", at(5), ci="rep1", risk="high", backout="")]))
        self.assertEqual((overall(f), area_status(f)["Readiness"], area_status(f)["Outcomes"]), ("action needed", CRITICAL, "ok"))


class TestDemo(unittest.TestCase):
    def test_demo_end_to_end_is_deterministic(self):
        hashes = []
        with tempfile.TemporaryDirectory() as t:
            for k in range(2):
                out = Path(t) / f"out{k}"
                self.assertEqual(cli.main(["demo", "--data", str(Path(t) / f"data{k}"), "--out", str(out)]), 0)
                self.assertEqual(sorted(p.name for p in out.iterdir()), sorted(cli.OUTPUTS))
                hashes.append({n: hashlib.sha1((out / n).read_bytes()).hexdigest() for n in cli.OUTPUTS}
                              | {n.name: hashlib.sha1(n.read_bytes()).hexdigest() for n in (Path(t) / f"data{k}").iterdir()})
            self.assertEqual(hashes[0], hashes[1])
            d = load(Path(t) / "data0")
            self.assertEqual(json.loads((Path(t) / "data0" / "settings.json").read_text(encoding="utf-8"))["as_of"], "2026-11-02 08:00")
        rv = review(d)
        f = run_all(d, rv)
        sm = summary(d, rv)
        self.assertEqual([x.severity for x in f], sorted((x.severity for x in f), key=ORDER.get))
        self.assertEqual(overall(f), "action needed")
        for c in ("RDY-01", "RDY-02", "RDY-03", "RDY-05", "RDY-06", "COL-02", "COL-03", "COL-04", "COL-05", "TYP-02", "TYP-03", "OUT-01", "OUT-02",
                  "OUT-03", "OUT-04", "OUT-05", "OUT-06", "TEAM-01", "TEAM-02"):
            self.assertIn(c, {x.code for x in f})
        self.assertEqual(d.settings.organisation, "Fabrikam Bank")
        self.assertEqual((sm["pairs"], sm["pairs_critical"], sm["in_freeze"], sm["p1"], sm["unauthorised"], sm["pir_overdue"]), (1, 1, 1, 1, 2, 6))
        pair = rv["pairs"][0]
        self.assertEqual({pair["a"].services[0], pair["b"].services[0]}, {"Data centre firewalls", "Core network"})
        self.assertIn("Trading platform", pair["on"])
        frz = next(r for r in rv["freeze"] if r["severity"])
        self.assertIn("Oracle", frz["item"].c.short_description)
        self.assertEqual(sm["teams_flagged"], ["Middleware & Integration", "Trading Platform Support"])
        mid = next(r for r in rv["teams"] if r["team"] == "Middleware & Integration")
        self.assertTrue(0.55 <= mid["rate"] <= 0.65)
        p1 = next(x for x in rv["outcomes"]["incidents"] if x["inc"].priority == 1)
        self.assertEqual((p1["how"], round(p1["hours"])), ("linked", 2))

    def test_review_reports_missing_changes(self):
        with tempfile.TemporaryDirectory() as t:
            self.assertEqual(cli.main(["review", t, "--out", str(Path(t) / "o")]), 2)
            self.assertEqual(cli.main(["review", "--out", str(Path(t) / "o")]), 2)


if __name__ == "__main__":
    unittest.main()
