#!/usr/bin/env python3
"""Validate source-controlled learning.artifacts operational assets.

This is a repository qualification check only. Passing it does not establish
target-host SLOs, operator acceptance, activation, promotion, or release.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEPLOY = ROOT / "deploy" / "learning-artifacts"
DASHBOARD = DEPLOY / "grafana-dashboard.json"
RULES = DEPLOY / "prometheus-rules.yml"
README = DEPLOY / "README.md"

REQUIRED_METRICS = {
    "hepta_learning_artifact_oldest_pending_attempt_age_seconds",
    "hepta_learning_artifact_drain_age_seconds",
    "hepta_learning_artifact_recovery_reconciliation_failures_total",
    "hepta_learning_artifact_withdrawal_blocks_total",
    "hepta_learning_artifact_identity_conflicts_total",
    "hepta_learning_artifact_persistence_unknown_total",
    "hepta_learning_artifact_pinned_bytes",
    "hepta_learning_artifact_pending_physical_erase_bytes",
}
REQUIRED_ALERTS = {
    "LearningArtifactPersistenceOutcomeUnknown",
    "LearningArtifactRecoveryReconciliationFailure",
    "LearningArtifactPendingAttemptStale",
    "LearningArtifactDrainStalled",
    "LearningArtifactWithdrawalBlocked",
    "LearningArtifactIdentityConflict",
}
MAX_ASSET_BYTES = 512 * 1024


def read_bounded(path: Path) -> str:
    if not path.is_file() or path.is_symlink():
        raise ValueError(f"operational asset is not a regular file: {path.relative_to(ROOT)}")
    size = path.stat().st_size
    if size == 0 or size > MAX_ASSET_BYTES:
        raise ValueError(f"operational asset size is invalid: {path.relative_to(ROOT)}")
    return path.read_text(encoding="utf-8")


def dashboard_metrics(value: object) -> set[str]:
    metrics: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "expr" and isinstance(item, str):
                for metric in REQUIRED_METRICS:
                    if metric in item:
                        metrics.add(metric)
            metrics.update(dashboard_metrics(item))
    elif isinstance(value, list):
        for item in value:
            metrics.update(dashboard_metrics(item))
    return metrics


def main() -> int:
    dashboard_text = read_bounded(DASHBOARD)
    rules = read_bounded(RULES)
    readme = read_bounded(README)

    dashboard = json.loads(dashboard_text)
    if not isinstance(dashboard, dict):
        raise ValueError("dashboard root must be an object")
    if dashboard.get("uid") != "hepta-learning-artifacts":
        raise ValueError("dashboard uid is not canonical")
    panels = dashboard.get("panels")
    if not isinstance(panels, list) or len(panels) < 6:
        raise ValueError("dashboard does not contain the required operational panels")

    dashboard_seen = dashboard_metrics(dashboard)
    missing_dashboard = REQUIRED_METRICS - dashboard_seen
    if missing_dashboard:
        raise ValueError(f"dashboard missing metrics: {sorted(missing_dashboard)}")

    for alert in REQUIRED_ALERTS:
        if f"alert: {alert}" not in rules:
            raise ValueError(f"Prometheus rules missing alert: {alert}")
    for metric in REQUIRED_METRICS - {
        "hepta_learning_artifact_pinned_bytes",
        "hepta_learning_artifact_pending_physical_erase_bytes",
    }:
        if metric not in rules:
            raise ValueError(f"Prometheus rules missing metric reference: {metric}")

    lowered = readme.lower()
    for phrase in (
        "unknown owner-supplied retention values are omitted",
        "target-host durability",
        "operator acceptance",
        "activation",
        "release authority",
    ):
        if phrase not in lowered:
            raise ValueError(f"operational README missing claim boundary: {phrase}")

    print("learning.artifacts operational assets: verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
