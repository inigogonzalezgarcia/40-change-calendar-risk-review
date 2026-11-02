"""Command line: `demo` writes the fictional Fabrikam Bank exports to sample_data/ and builds the outputs; `review` runs on your own exports."""
from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

from . import report, simulate
from .checks import overall, pct, review, run_all, summary
from .model import load, parse_dt

OUTPUTS = ("report.html", "cab-pack.md", "calendar.csv", "collisions.csv", "readiness.csv", "outcomes.csv", "teams.csv", "actions.csv", "findings.csv")


def run(data: Path, out: Path, title: str, as_of: datetime | None = None) -> dict:
    d = load(data, as_of)
    rv = review(d)
    findings = run_all(d, rv)
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.html").write_text(report.render_html(d, rv, findings, title), encoding="utf-8")
    (out / "cab-pack.md").write_text(report.pack_md(d, rv, findings, title), encoding="utf-8")
    report.write_calendar(d, rv, out / "calendar.csv")
    report.write_collisions(d, rv, out / "collisions.csv")
    report.write_readiness(d, rv, out / "readiness.csv")
    report.write_outcomes(d, rv, out / "outcomes.csv")
    report.write_teams(d, rv, out / "teams.csv")
    report.write_actions(findings, out / "actions.csv")
    report.write_findings(findings, out / "findings.csv")
    sm = summary(d, rv)
    sm.update(overall=overall(findings), critical=sum(f.severity == "critical" for f in findings), warning=sum(f.severity == "warning" for f in findings))
    return sm


def _when(value: str) -> datetime:
    d = parse_dt(value)
    if not d:
        raise argparse.ArgumentTypeError(f"not a date (YYYY-MM-DD or 'YYYY-MM-DD HH:MM'): {value}")
    return d


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="changecal", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)
    dm = sub.add_parser("demo", help="write the fictional exports to sample_data/ and build the outputs")
    dm.add_argument("--data", type=Path, default=Path("sample_data"))
    dm.add_argument("--out", type=Path, default=Path("output"))
    rv = sub.add_parser("review", help="build the outputs from your own exports")
    rv.add_argument("data", type=Path, nargs="?", help="folder with changes.csv and the optional files")
    rv.add_argument("--data", dest="data_opt", type=Path, help="same as the positional folder")
    rv.add_argument("--out", type=Path, default=Path("output"))
    rv.add_argument("--title", default="Change calendar and risk review")
    rv.add_argument("--as-of", type=_when, help="reference date (default: settings.json, or now)")
    a = p.parse_args(argv)
    if a.cmd == "demo":
        simulate.write(a.data)
        sm = run(a.data, a.out, f"{simulate.ORG} · Change calendar and CAB review, week of 2 November 2026")
    else:
        folder = a.data or a.data_opt
        if not folder:
            print("error: give the folder with the exports", file=sys.stderr)
            return 2
        try:
            sm = run(folder, a.out, a.title, a.as_of)
        except (FileNotFoundError, ValueError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
    print(f"{sm['overall'].upper()} · next two weeks {sm['upcoming']} changes ({sm['not_ready']} with gaps, {sm['to_approve']} to approve) · "
          f"collisions {sm['pairs']} ({sm['pairs_critical']} critical) · in a freeze {sm['in_freeze']} · {sm['last']}: {sm['changes_last']} changes, "
          f"{pct(sm['rate_last'])} successful, emergency {pct(sm['emergency_share'])} · incidents after changes {sm['incidents']} ({sm['p1']} P1) · "
          f"unauthorised {sm['unauthorised']} · PIRs overdue {sm['pir_overdue']} · {sm['critical']} critical, {sm['warning']} warnings")
    print(f"outputs in {a.out}/: {', '.join(OUTPUTS)}")
    return 0
