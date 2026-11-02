"""Loading: the change requests (ServiceNow change_request, with aliases for Jira Service Management and other tools), the CI to business
service map with tiers and dependencies (cmdb_ci_service and cmdb_rel_ci), the change freezes and blackout windows, the incidents (with the
change that caused them), the approvals (sysapproval_approver) and settings.json, with forgiving column names, into plain dataclasses."""
from __future__ import annotations

import csv
import json
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

CHANGE_ALIASES = {
    "number": ["number", "change number", "change", "issue key", "key", "change id", "id"],
    "short_description": ["short_description", "short description", "summary", "title", "descripcion corta", "resumen"],
    "type": ["type", "change type", "change_type", "tipo"],
    "state": ["state", "status", "estado"],
    "risk": ["risk", "change risk", "riesgo"],
    "impact": ["impact", "change impact", "impacto"],
    "ci": ["cmdb_ci", "configuration item", "configuration_item", "ci", "affected ci", "elemento de configuracion"],
    "service": ["business_service", "business service", "service", "affected services", "affected service", "servicio"],
    "group": ["assignment_group", "assignment group", "team", "grupo asignado", "grupo"],
    "assigned_to": ["assigned_to", "assigned to", "assignee", "asignado a"],
    "requested_by": ["requested_by", "requested by", "reporter", "requester", "solicitado por"],
    "opened": ["opened_at", "opened", "created", "sys_created_on", "created at", "abierto"],
    "start": ["start_date", "planned start date", "planned start", "start", "inicio planificado"],
    "end": ["end_date", "planned end date", "planned end", "end", "fin planificado"],
    "work_start": ["work_start", "actual start date", "actual start", "inicio real"],
    "work_end": ["work_end", "actual end date", "actual end", "fin real"],
    "approval": ["approval", "approval status", "aprobacion"],
    "cab_date": ["cab_date", "cab date", "fecha cab"],
    "close_code": ["close_code", "close code", "resolution", "outcome", "codigo de cierre"],
    "backout": ["backout_plan", "backout plan", "rollback plan", "plan de marcha atras"],
    "test": ["test_plan", "test plan", "plan de pruebas"],
    "implementation": ["implementation_plan", "implementation plan", "plan de implementacion"],
    "justification": ["justification", "reason", "justificacion"],
    "outside_window": ["outside_maintenance_schedule", "outside maintenance schedule", "fuera de ventana"],
    "review_status": ["review_status", "review status", "pir status", "pir"],
    "review_date": ["review_date", "review date", "pir date"],
}
CI_ALIASES = {
    "ci": ["ci", "cmdb_ci", "configuration item", "child", "child name"],
    "ci_class": ["ci_class", "class", "sys_class_name", "child class"],
    "service": ["service", "business_service", "business service", "parent", "parent name", "servicio"],
    "tier": ["service_tier", "tier", "business_criticality", "criticality", "criticidad"],
    "owner": ["service_owner", "owner", "owned_by", "support_group", "owner group", "responsable"],
    "depends_on": ["service_depends_on", "depends_on", "depends on", "upstream", "depende de"],
}
FREEZE_ALIASES = {
    "name": ["name", "freeze", "title", "nombre"],
    "kind": ["kind", "type", "tipo"],
    "start": ["start", "start_date", "from", "inicio"],
    "end": ["end", "end_date", "to", "fin"],
    "scope": ["scope", "services", "business services", "alcance"],
    "exceptions": ["approved_exceptions", "approved exceptions", "exceptions", "excepciones"],
    "reason": ["reason", "description", "motivo"],
}
INCIDENT_ALIASES = {
    "number": ["number", "incident", "issue key", "key", "id"],
    "short_description": ["short_description", "short description", "summary", "title"],
    "priority": ["priority", "prioridad"],
    "opened": ["opened_at", "opened", "created", "sys_created_on"],
    "resolved": ["resolved_at", "resolved", "resolution date"],
    "ci": ["cmdb_ci", "configuration item", "ci", "affected ci"],
    "service": ["business_service", "business service", "service", "affected services"],
    "group": ["assignment_group", "assignment group", "team"],
    "caused_by": ["caused_by", "caused by", "caused by change", "related change", "causado por"],
}
APPROVAL_ALIASES = {
    "change": ["sysapproval", "approval for", "document_id", "change", "number", "change number"],
    "approver": ["approver", "approved by", "aprobador"],
    "state": ["state", "status", "estado"],
    "when": ["sys_updated_on", "updated", "approved on", "date", "fecha"],
}

YES = {"yes", "y", "true", "1", "si", "x", "on"}
NONE_WORDS = {"", "none", "n a", "na", "tbd", "-", "no", "ninguno", "null", "see above", "to follow"}
PIR_DONE = {"complete", "completed", "done", "reviewed", "closed", "accepted", "yes"}
RISKS = ("very high", "high", "moderate", "low")
DATE_FORMATS = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d", "%d/%m/%Y %H:%M:%S",
                "%d/%m/%Y %H:%M", "%d/%m/%Y", "%m/%d/%Y %I:%M:%S %p", "%m/%d/%Y %H:%M", "%d %b %Y %H:%M", "%d %b %Y")
DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")

DEFAULT_OWNERS = {"readiness": "Change manager", "collisions": "Change manager", "types": "Change manager", "outcomes": "Change manager",
                  "teams": "Head of IT operations"}


def _norm(s) -> str:
    s = unicodedata.normalize("NFKD", str(s or "").lower())
    return re.sub(r"[^a-z0-9]+", " ", "".join(ch for ch in s if not unicodedata.combining(ch))).strip()


def parse_dt(v) -> datetime | None:
    s = str(v or "").strip()
    if not s or _norm(s) in {"n a", "na", "none", "null"}:
        return None
    s = re.sub(r"(\.\d+)?(Z|[+-]\d{2}:?\d{2})$", "", s)
    for f in DATE_FORMATS:
        try:
            return datetime.strptime(s, f)
        except ValueError:
            continue
    return None


def yes(v) -> bool:
    return _norm(v) in YES


def num(v) -> float | None:
    s = str(v or "").strip().replace(",", ".")
    try:
        return float(s) if s else None
    except ValueError:
        return None


def split_list(v) -> list[str]:
    return [x.strip() for x in re.split(r"[;|\n]+", str(v or "")) if x.strip()]


def has_text(v) -> bool:
    return _norm(v) not in NONE_WORDS


def _read(path: Path) -> tuple[list[str], list[dict]]:
    with open(path, newline="", encoding="utf-8-sig") as fh:
        header = fh.readline()
        fh.seek(0)
        delim = max(",;\t", key=header.count)
        reader = csv.DictReader(fh, delimiter=delim)
        return list(reader.fieldnames or []), list(reader)


def _map(fields: list[str], aliases: dict[str, list[str]]) -> dict[str, str]:
    heads = {_norm(h): h for h in fields}
    cols = {}
    for k, names in aliases.items():
        for n in names + [k.replace("_", " ")]:
            if _norm(n) in heads and heads[_norm(n)] not in cols.values():
                cols[k] = heads[_norm(n)]
                break
    return cols


def _rows(path: Path, aliases: dict[str, list[str]]) -> list[dict]:
    fields, raw = _read(path)
    cols = _map(fields, aliases)
    return [{k: (r.get(c) or "").strip() for k, c in cols.items()} for r in raw]


# ---------------------------------------------------------------- normalisation of choice fields

def change_type(v) -> str:
    n = _norm(v)
    return "emergency" if "emerg" in n or "expedit" in n else "standard" if "standard" in n or "pre approved" in n else "normal"


def risk_level(v) -> str:
    """ServiceNow change risk: 1 - Very High, 2 - High, 3 - Moderate, 4 - Low (labels or numbers); Jira: Critical, High, Medium, Low."""
    n = _norm(v)
    if not n or n in {"none", "not assessed", "0", "5"}:
        return ""
    if n.startswith("1") or "very high" in n or "critical" in n:
        return "very high"
    if n.startswith("2") or "high" in n:
        return "high"
    if n.startswith("3") or "moderate" in n or "medium" in n:
        return "moderate"
    if n.startswith("4") or "low" in n:
        return "low"
    return ""


def impact_level(v) -> int:
    """1 - High, 2 - Medium, 3 - Low; 0 when blank."""
    n = _norm(v)
    if n.startswith("1") or "high" in n or "extensive" in n:
        return 1
    if n.startswith("2") or "medium" in n or "significant" in n or "moderate" in n:
        return 2
    if n.startswith("3") or "low" in n or "minor" in n:
        return 3
    return 0


STATE_MAP = [("cancel", "canceled"), ("declin", "canceled"), ("reject", "canceled"), ("closed", "closed"), ("complet", "closed"),
             ("review", "review"), ("awaiting implementation", "scheduled"), ("implement", "implement"), ("schedul", "scheduled"),
             ("authori", "authorize"), ("awaiting approval", "authorize"), ("assess", "assess"), ("planning", "assess"), ("new", "new"),
             ("open", "new"), ("draft", "new")]
STATE_NUM = {"-5": "new", "-4": "assess", "-3": "authorize", "-2": "scheduled", "-1": "implement", "0": "review", "3": "closed", "4": "canceled"}


def state_of(v) -> str:
    s = str(v or "").strip()
    if s in STATE_NUM:
        return STATE_NUM[s]
    n = _norm(s)
    return next((x for k, x in STATE_MAP if k in n), "new" if not n else n)


def close_code(v) -> str:
    n = _norm(v)
    if not n:
        return ""
    if "unsuccess" in n or "fail" in n or "back" in n or "roll" in n or "not success" in n:
        return "unsuccessful"
    if "issue" in n:
        return "successful_issues"
    if "success" in n or n in {"done", "completed"}:
        return "successful"
    return n


def approval_of(v) -> str:
    n = _norm(v)
    return ("approved" if n.startswith("approved") else "rejected" if n.startswith("reject") else "requested" if n.startswith("request")
            else "not requested" if not n or "not" in n else n)


def priority_of(v) -> int:
    m = re.search(r"\d", str(v or ""))
    if m:
        return int(m.group())
    n = _norm(v)
    return 1 if n in {"critical", "highest", "p1"} else 2 if n in {"high", "p2"} else 3 if n in {"moderate", "medium", "p3"} else 4 if n else 0


def tier_of(v) -> int:
    m = re.search(r"\d", str(v or ""))
    return int(m.group()) if m else 3


def change_key(v) -> str:
    return str(v or "").strip().upper()


# ---------------------------------------------------------------- records

@dataclass
class Change:
    number: str
    short_description: str = ""
    type: str = "normal"            # standard, normal, emergency
    state: str = "new"              # new, assess, authorize, scheduled, implement, review, closed, canceled
    risk: str = ""                  # very high, high, moderate, low, '' (not assessed)
    impact: int = 0                 # 1 high, 2 medium, 3 low, 0 blank
    ci: str = ""
    service: str = ""
    group: str = ""
    assigned_to: str = ""
    requested_by: str = ""
    opened: datetime | None = None
    start: datetime | None = None
    end: datetime | None = None
    work_start: datetime | None = None
    work_end: datetime | None = None
    approval: str = "not requested"
    cab_date: datetime | None = None
    close_code: str = ""
    backout: str = ""
    test: str = ""
    implementation: str = ""
    justification: str = ""
    outside_window: bool = False
    review_status: str = ""
    review_date: datetime | None = None

    @property
    def active(self) -> bool:
        return self.state != "canceled"

    @property
    def done(self) -> bool:
        return self.state in ("review", "closed") or bool(self.close_code)

    @property
    def finished(self) -> datetime | None:
        return self.work_end or (self.end if self.done else None)

    @property
    def pir_done(self) -> bool:
        return _norm(self.review_status) in PIR_DONE


@dataclass
class Service:
    name: str
    tier: int = 3
    owner: str = ""
    depends_on: list[str] = field(default_factory=list)


@dataclass
class Freeze:
    name: str
    kind: str = "freeze"            # freeze or blackout
    start: datetime | None = None
    end: datetime | None = None
    scope: list[str] = field(default_factory=list)   # empty: every service
    exceptions: list[str] = field(default_factory=list)
    reason: str = ""

    @property
    def is_global(self) -> bool:
        return not self.scope


@dataclass
class Incident:
    number: str
    short_description: str = ""
    priority: int = 0
    opened: datetime | None = None
    resolved: datetime | None = None
    ci: str = ""
    service: str = ""
    group: str = ""
    caused_by: str = ""


@dataclass
class Approval:
    change: str
    approver: str = ""
    state: str = ""
    when: datetime | None = None


@dataclass
class Settings:
    organisation: str = "Change calendar and risk review"
    as_of: datetime | None = None
    horizon_days: int = 14
    cab_weekday: str = "tue"
    cab_time: str = "10:00"
    lead_time_days: dict = field(default_factory=lambda: {"normal": {"very high": 10, "high": 10, "moderate": 5, "low": 3, "": 5},
                                                          "standard": {}, "emergency": {}})
    plans_required: dict = field(default_factory=lambda: {"normal": ["backout", "test", "implementation"],
                                                          "emergency": ["backout", "implementation"], "standard": []})
    maintenance_windows: dict = field(default_factory=dict)  # tier -> [{"days": [...], "start": "HH:MM", "end": "HH:MM"}]; none: any time
    max_changes_per_team_night: int = 3
    collision_max_tier: int = 2
    freeze_allows_emergency: bool = True
    freeze_allows_standard: bool = False
    incident_window_hours: int = 24
    suspected_max_priority: int = 2
    pir_due_days: int = 5
    pir_required_for: list = field(default_factory=lambda: ["unsuccessful", "successful_issues", "emergency", "incident"])
    overrun_tolerance_minutes: int = 30
    retro_approval_days: int = 2
    success_target: float = 0.95
    team_success_min: float = 0.8
    team_min_changes: int = 5
    emergency_share_max: float = 0.1
    team_emergency_share_max: float = 0.2
    standard_risky_match: str = r"firmware|upgrade|migrat|replace|re-?platform"
    trend_months: int = 3
    teams: list = field(default_factory=list)
    owners: dict = field(default_factory=lambda: dict(DEFAULT_OWNERS))

    def owner(self, area: str) -> str:
        return self.owners.get(area) or DEFAULT_OWNERS.get(area, "IT")

    def lead_days(self, c: Change) -> int:
        t = self.lead_time_days.get(c.type) or {}
        return int(t.get(c.risk, t.get("", 0)) or 0)


def settings_from_dict(raw: dict) -> Settings:
    s = Settings()
    for k, v in raw.items():
        if not hasattr(s, k) or v is None:
            continue
        cur = getattr(s, k)
        if k == "as_of":
            s.as_of = parse_dt(v)
        elif k == "owners":
            cur.update(v)
        elif k == "lead_time_days":
            for typ, m in v.items():
                cur[change_type(typ)] = {("" if _norm(r) in {"", "none", "not assessed"} else risk_level(r)): int(x) for r, x in m.items()}
        elif k == "maintenance_windows":
            s.maintenance_windows = {str(tier_of(t)): list(w) for t, w in v.items()}
        elif isinstance(cur, bool):
            setattr(s, k, bool(v))
        elif isinstance(cur, int):
            setattr(s, k, int(num(v) or 0))
        elif isinstance(cur, float):
            setattr(s, k, float(num(v) or 0))
        else:
            setattr(s, k, v)
    return s


@dataclass
class Data:
    settings: Settings
    as_of: datetime
    changes: list[Change] = field(default_factory=list)
    services: dict = field(default_factory=dict)        # service name -> Service
    ci_services: dict = field(default_factory=dict)     # ci (lower) -> [service names]
    freezes: list[Freeze] = field(default_factory=list)
    incidents: list[Incident] = field(default_factory=list)
    approvals: dict = field(default_factory=dict)       # change number -> [Approval]
    sources: dict = field(default_factory=dict)

    @property
    def today(self) -> date:
        return self.as_of.date()


# ---------------------------------------------------------------- loaders

def load_changes(path: Path) -> list[Change]:
    out = []
    for r in _rows(path, CHANGE_ALIASES):
        if not r.get("number"):
            continue
        out.append(Change(change_key(r["number"]), r.get("short_description", ""), change_type(r.get("type")), state_of(r.get("state")),
                          risk_level(r.get("risk")), impact_level(r.get("impact")), r.get("ci", ""), r.get("service", ""), r.get("group", ""),
                          r.get("assigned_to", ""), r.get("requested_by", ""), parse_dt(r.get("opened")), parse_dt(r.get("start")),
                          parse_dt(r.get("end")), parse_dt(r.get("work_start")), parse_dt(r.get("work_end")), approval_of(r.get("approval")),
                          parse_dt(r.get("cab_date")), close_code(r.get("close_code")), r.get("backout", ""), r.get("test", ""),
                          r.get("implementation", ""), r.get("justification", ""), yes(r.get("outside_window")), r.get("review_status", ""),
                          parse_dt(r.get("review_date"))))
    return out


def load_ci_services(path: Path) -> tuple[dict, dict]:
    services: dict[str, Service] = {}
    cis: dict[str, list[str]] = {}
    for r in _rows(path, CI_ALIASES):
        name = r.get("service", "")
        if not name:
            continue
        s = services.setdefault(name, Service(name, tier_of(r.get("tier"))))
        if r.get("tier"):
            s.tier = tier_of(r["tier"])
        if r.get("owner") and not s.owner:
            s.owner = r["owner"]
        for dep in split_list(r.get("depends_on")):
            if dep not in s.depends_on and dep != name:
                s.depends_on.append(dep)
        if r.get("ci"):
            lst = cis.setdefault(r["ci"].lower(), [])
            if name not in lst:
                lst.append(name)
    for s in list(services.values()):
        for dep in s.depends_on:
            services.setdefault(dep, Service(dep))
    return services, cis


def load_freezes(path: Path) -> list[Freeze]:
    out = []
    for r in _rows(path, FREEZE_ALIASES):
        if not r.get("start") or not r.get("end"):
            continue
        scope = [x for x in split_list(r.get("scope")) if _norm(x) not in {"global", "all", "all services", "every service", "*"}]
        out.append(Freeze(r.get("name") or "Freeze", "blackout" if "black" in _norm(r.get("kind")) else "freeze", parse_dt(r.get("start")),
                          parse_dt(r.get("end")), scope, [change_key(x) for x in split_list(r.get("exceptions"))], r.get("reason", "")))
    return out


def load_incidents(path: Path) -> list[Incident]:
    return [Incident(r["number"], r.get("short_description", ""), priority_of(r.get("priority")), parse_dt(r.get("opened")), parse_dt(r.get("resolved")),
                     r.get("ci", ""), r.get("service", ""), r.get("group", ""), change_key(r.get("caused_by")))
            for r in _rows(path, INCIDENT_ALIASES) if r.get("number")]


def load_approvals(path: Path) -> dict[str, list[Approval]]:
    out: dict[str, list[Approval]] = {}
    for r in _rows(path, APPROVAL_ALIASES):
        if r.get("change"):
            k = change_key(r["change"])
            out.setdefault(k, []).append(Approval(k, r.get("approver", ""), approval_of(r.get("state")), parse_dt(r.get("when"))))
    for v in out.values():
        v.sort(key=lambda a: (a.when or datetime.max, a.approver))
    return out


FILES = {
    "changes.csv": "Change requests (ServiceNow change_request)",
    "ci-services.csv": "CI to business service, tier, owner and dependencies (cmdb_ci_service, cmdb_rel_ci)",
    "freezes.csv": "Change freezes and blackout windows",
    "incidents.csv": "Incidents with the change that caused them (incident.caused_by)",
    "approvals.csv": "Approvals per change (sysapproval_approver)",
}


def _find(folder: Path, name: str) -> Path | None:
    p = folder / name
    if p.exists():
        return p
    alts = sorted(folder.glob(f"{name.rsplit('.', 1)[0]}*.csv"))
    return alts[0] if alts else None


def load(folder: Path, as_of: datetime | None = None) -> Data:
    folder = Path(folder)
    if not folder.is_dir():
        raise FileNotFoundError(f"no folder {folder}")
    sp = folder / "settings.json"
    s = settings_from_dict(json.loads(sp.read_text(encoding="utf-8"))) if sp.exists() else Settings()
    when = as_of or s.as_of or datetime.now().replace(second=0, microsecond=0)
    paths = {n: _find(folder, n) for n in FILES}
    if not paths["changes.csv"]:
        raise FileNotFoundError(f"{folder}: need changes.csv (the change requests export)")
    d = Data(s, when)
    d.changes = load_changes(paths["changes.csv"])
    if paths["ci-services.csv"]:
        d.services, d.ci_services = load_ci_services(paths["ci-services.csv"])
    if paths["freezes.csv"]:
        d.freezes = load_freezes(paths["freezes.csv"])
    if paths["incidents.csv"]:
        d.incidents = load_incidents(paths["incidents.csv"])
    if paths["approvals.csv"]:
        d.approvals = load_approvals(paths["approvals.csv"])
    counts = {"changes.csv": len(d.changes), "ci-services.csv": len(d.ci_services) or len(d.services), "freezes.csv": len(d.freezes),
              "incidents.csv": len(d.incidents), "approvals.csv": sum(len(v) for v in d.approvals.values())}
    d.sources = {n: counts[n] for n in FILES if paths[n]}
    return d


def month_key(d) -> str:
    return f"{d.year}-{d.month:02d}"


def months_before(today: date, n: int) -> list[str]:
    """The n complete months before today, oldest first: 2026-11-02, 3 -> ['2026-08', '2026-09', '2026-10']."""
    y, m = today.year, today.month
    out = []
    for _ in range(n):
        y, m = (y - 1, 12) if m == 1 else (y, m - 1)
        out.append(f"{y}-{m:02d}")
    return out[::-1]


def hhmm(v: str) -> int:
    h, _, m = str(v).partition(":")
    return int(h) * 60 + int(m or 0)


__all__ = ["Data", "Settings", "Change", "Service", "Freeze", "Incident", "Approval", "load", "timedelta"]
