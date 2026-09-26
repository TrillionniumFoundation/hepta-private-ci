#!/usr/bin/env python3
"""Validate auth.authbus metric, alert and dashboard contracts without PyYAML."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "docs/modules/auth.authbus/observability"
METRICS = BASE / "metrics.yaml"
ALERTS = BASE / "alerts.yaml"
DASHBOARD = BASE / "dashboard.json"
FORBIDDEN_LABELS = {
    "principal_id",
    "issuer_id",
    "message_id",
    "operation_id",
    "reservation_id",
    "subject_id",
}
METRIC_RE = re.compile(r"\bhepta_authbus_[a-z0-9_]+\b")


def fail(message: str) -> None:
    print(message, file=sys.stderr)
    raise SystemExit(1)


def main() -> int:
    for target in (METRICS, ALERTS, DASHBOARD):
        if not target.is_file():
            fail(f"missing observability asset: {target.relative_to(ROOT)}")

    metric_text = METRICS.read_text()
    alert_text = ALERTS.read_text()
    dashboard = json.loads(DASHBOARD.read_text())

    metrics = set(re.findall(r"(?m)^  - name: (hepta_authbus_[a-z0-9_]+)$", metric_text))
    if len(metrics) < 20:
        fail(f"metric catalog unexpectedly small: {len(metrics)}")

    declared_forbidden = set(re.findall(r"(?m)^    - ([a-z0-9_]+)$", metric_text.split("metrics:", 1)[0]))
    missing_forbidden = FORBIDDEN_LABELS.difference(declared_forbidden)
    if missing_forbidden:
        fail(f"forbidden raw labels not declared: {sorted(missing_forbidden)}")

    alert_metrics = set(METRIC_RE.findall(alert_text))
    dashboard_metrics = set()
    for row in dashboard.get("rows", []):
        for panel in row.get("panels", []):
            dashboard_metrics.update(METRIC_RE.findall(str(panel.get("query", ""))))
    referenced = alert_metrics | dashboard_metrics
    unknown = sorted(referenced.difference(metrics))
    # Deployment budget/validity constants are configuration gauges and are
    # deliberately outside the module-emitted metric catalog.
    unknown = [
        name
        for name in unknown
        if name not in {
            "hepta_authbus_database_budget_bytes",
            "hepta_authbus_trusted_time_validity_seconds",
        }
    ]
    if unknown:
        fail(f"alerts/dashboard reference unknown metrics: {unknown}")

    critical_blocks = re.split(r"(?m)^  - alert: ", alert_text)[1:]
    for block in critical_blocks:
        name = block.splitlines()[0].strip()
        severity = re.search(r"(?m)^    severity: ([a-z]+)$", block)
        if severity and severity.group(1) == "critical" and not re.search(r"(?m)^    runbook: \S+$", block):
            fail(f"critical alert has no runbook: {name}")

    serialized_dashboard = json.dumps(dashboard)
    leaked = sorted(label for label in FORBIDDEN_LABELS if label in serialized_dashboard)
    if leaked:
        fail(f"dashboard contains forbidden raw identifier labels: {leaked}")

    required_panels = {
        "Owner fence held",
        "Checkpoint dirty age",
        "Recovery required",
        "Expired sweep backlog",
        "Trusted-time age",
        "Maintenance result",
        "Outbox oldest age",
    }
    actual_panels = {
        panel.get("title")
        for row in dashboard.get("rows", [])
        for panel in row.get("panels", [])
    }
    missing_panels = sorted(required_panels.difference(actual_panels))
    if missing_panels:
        fail(f"dashboard missing required panels: {missing_panels}")

    print(
        "auth.authbus observability contract: PASS "
        f"({len(metrics)} metrics, {len(critical_blocks)} alerts, {len(actual_panels)} panels)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
