#!/usr/bin/env python3
"""Evidence-manifest and experiment-runner contract for NDU qualification.

The manifest is the boundary between an experiment runner and the candidate
promotion gate.  It records *where* evidence came from, which snapshots and
future windows were independent, and whether any history replay or synthetic
fixture was used.  Structural validity is deliberately separate from
qualification eligibility: a well-formed synthetic shadow manifest is valid
but can never qualify a candidate.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Optional, Sequence

from ndu_receipt_schema import canonical_json, build_event


SCHEMA_ID = "urn:hepta:ndu:evidence-manifest:1"
SCHEMA_VERSION = 1
MANIFEST_TYPE = "ndu.experiment.evidence_manifest"
CANONICALIZATION = "canonical-json-v1"
DIGEST_ALGORITHM = "sha256"
MODE = "SHADOW_ONLY"
AUTHORITY = "DENY_ALL"
HEX = "0123456789abcdef"


class EvidenceManifestError(ValueError):
    """Malformed or semantically contradictory evidence manifest."""


def _digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _hex_digest(value: Any, label: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(c not in HEX for c in value):
        raise EvidenceManifestError(f"{label} must be a lowercase SHA-256 digest")
    return value


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise EvidenceManifestError(f"{label} must be an object")
    return value


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise EvidenceManifestError(f"{label} must be a non-empty string")
    return value


def _bool(value: Any, label: str) -> bool:
    if not isinstance(value, bool):
        raise EvidenceManifestError(f"{label} must be boolean")
    return value


def _integer(value: Any, label: str, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise EvidenceManifestError(f"{label} must be an integer >= {minimum}")
    return value


def _finite(value: Any, label: str, *, minimum: Optional[float] = None, maximum: Optional[float] = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise EvidenceManifestError(f"{label} must be finite")
    number = float(value)
    if minimum is not None and number < minimum:
        raise EvidenceManifestError(f"{label} must be >= {minimum}")
    if maximum is not None and number > maximum:
        raise EvidenceManifestError(f"{label} must be <= {maximum}")
    return number


def _unique(values: Iterable[str], label: str) -> None:
    values = list(values)
    if len(values) != len(set(values)):
        raise EvidenceManifestError(f"{label} contains duplicate identifiers")


def _protocol() -> Dict[str, Any]:
    return {
        "mode": MODE,
        "authority": AUTHORITY,
        "provider_dispatch": False,
        "real_model_call": False,
        "artifact_selection": False,
        "learned_fbsde": False,
        "production_activation": False,
    }


def _manifest_digest(manifest: Mapping[str, Any]) -> str:
    body = copy.deepcopy(dict(manifest))
    body.pop("integrity", None)
    return _digest(body)


def validate_manifest(manifest: Mapping[str, Any], *, require_observed: bool = False) -> Dict[str, Any]:
    """Validate structure, provenance, independence and digest integrity.

    ``require_observed`` is used by a real-evidence runner.  The default keeps
    the deterministic shadow fixture structurally valid while its eligibility
    remains false.
    """
    if not isinstance(manifest, Mapping):
        raise EvidenceManifestError("manifest must be an object")
    required = (
        "schema_id", "schema_version", "manifest_type", "manifest_id", "status",
        "candidate_snapshot_digest", "baseline_snapshot_digest", "protocol",
        "experiment", "trajectory_provenance", "future_windows",
        "independent_snapshots", "evaluations", "summary", "integrity",
    )
    for key in required:
        if key not in manifest:
            raise EvidenceManifestError(f"manifest missing required field: {key}")
    if manifest["schema_id"] != SCHEMA_ID or manifest["schema_version"] != SCHEMA_VERSION:
        raise EvidenceManifestError("unsupported schema id or version")
    if manifest["manifest_type"] != MANIFEST_TYPE or manifest["status"] != "shadow_evidence_manifest":
        raise EvidenceManifestError("unsupported manifest type or status")
    _text(manifest["manifest_id"], "manifest_id")
    candidate = _hex_digest(manifest["candidate_snapshot_digest"], "candidate_snapshot_digest")
    baseline = _hex_digest(manifest["baseline_snapshot_digest"], "baseline_snapshot_digest")
    protocol = _mapping(manifest["protocol"], "protocol")
    if protocol.get("mode") != MODE or protocol.get("authority") != AUTHORITY:
        raise EvidenceManifestError("protocol must remain SHADOW_ONLY/DENY_ALL")
    for key in ("provider_dispatch", "real_model_call", "artifact_selection", "learned_fbsde", "production_activation"):
        if _bool(protocol.get(key), f"protocol.{key}"):
            raise EvidenceManifestError(f"protocol.{key} must be false")

    experiment = _mapping(manifest["experiment"], "experiment")
    for key in ("experiment_id", "runner_id", "runner_version", "config_digest", "code_digest", "split_policy"):
        _text(experiment.get(key), f"experiment.{key}")
    _hex_digest(experiment["config_digest"], "experiment.config_digest")
    _hex_digest(experiment["code_digest"], "experiment.code_digest")
    if experiment["split_policy"] != "frozen_non_overlapping":
        raise EvidenceManifestError("experiment.split_policy must be frozen_non_overlapping")
    _bool(experiment.get("history_replay"), "experiment.history_replay")
    _bool(experiment.get("synthetic"), "experiment.synthetic")

    trajectories = manifest["trajectory_provenance"]
    if not isinstance(trajectories, list) or not trajectories:
        raise EvidenceManifestError("trajectory_provenance must be a non-empty array")
    trajectory_ids = []
    trajectory_by_id: Dict[str, Mapping[str, Any]] = {}
    for index, item in enumerate(trajectories):
        row = _mapping(item, f"trajectory_provenance[{index}]")
        for key in ("trajectory_id", "source_kind", "dataset_digest", "environment_digest", "runner_code_digest"):
            _text(row.get(key), f"trajectory_provenance[{index}].{key}")
        tid = row["trajectory_id"]
        trajectory_ids.append(tid)
        trajectory_by_id[tid] = row
        _hex_digest(row["dataset_digest"], f"trajectory_provenance[{index}].dataset_digest")
        _hex_digest(row["environment_digest"], f"trajectory_provenance[{index}].environment_digest")
        _hex_digest(row["runner_code_digest"], f"trajectory_provenance[{index}].runner_code_digest")
        if row["source_kind"] not in {"live_observed", "external_observed", "synthetic_shadow", "history_replay"}:
            raise EvidenceManifestError("unsupported trajectory source_kind")
        observed = _bool(row.get("observed"), f"trajectory_provenance[{index}].observed")
        replay = _bool(row.get("history_replay"), f"trajectory_provenance[{index}].history_replay")
        if replay or row["source_kind"] == "history_replay":
            raise EvidenceManifestError(f"trajectory {tid} is history replay")
        if observed and row["source_kind"] == "synthetic_shadow":
            raise EvidenceManifestError(f"synthetic trajectory {tid} cannot be observed evidence")
        if row["runner_code_digest"] != experiment["code_digest"]:
            raise EvidenceManifestError(f"trajectory {tid} runner code digest mismatch")
    _unique(trajectory_ids, "trajectory_provenance")
    if experiment["history_replay"]:
        raise EvidenceManifestError("experiment.history_replay must be false")

    windows = manifest["future_windows"]
    if not isinstance(windows, list):
        raise EvidenceManifestError("future_windows must be an array")
    window_ids = []
    used_window_trajectories = set()
    for index, item in enumerate(windows):
        row = _mapping(item, f"future_windows[{index}]")
        for key in ("window_id", "dataset_digest", "snapshot_digest"):
            _text(row.get(key), f"future_windows[{index}].{key}")
        wid = row["window_id"]
        window_ids.append(wid)
        _hex_digest(row["dataset_digest"], f"future_windows[{index}].dataset_digest")
        _hex_digest(row["snapshot_digest"], f"future_windows[{index}].snapshot_digest")
        start = _integer(row.get("start_step"), f"future_windows[{index}].start_step")
        end = _integer(row.get("end_step"), f"future_windows[{index}].end_step")
        if end <= start:
            raise EvidenceManifestError(f"future window {wid} must have end_step > start_step")
        _bool(row.get("observed"), f"future_windows[{index}].observed")
        if _bool(row.get("history_replay"), f"future_windows[{index}].history_replay"):
            raise EvidenceManifestError(f"future window {wid} is history replay")
        tids = row.get("trajectory_ids")
        if not isinstance(tids, list) or not tids or any(tid not in trajectory_by_id for tid in tids):
            raise EvidenceManifestError(f"future window {wid} has unknown/empty trajectory_ids")
        if used_window_trajectories.intersection(tids):
            raise EvidenceManifestError("future windows reuse trajectories and are not independent")
        used_window_trajectories.update(tids)
    _unique(window_ids, "future_windows")

    snapshots = manifest["independent_snapshots"]
    if not isinstance(snapshots, list):
        raise EvidenceManifestError("independent_snapshots must be an array")
    snapshot_ids = []
    training_runs = []
    snapshot_digests = []
    for index, item in enumerate(snapshots):
        row = _mapping(item, f"independent_snapshots[{index}]")
        for key in ("snapshot_id", "snapshot_digest", "training_run_id", "parent_snapshot_digest"):
            _text(row.get(key), f"independent_snapshots[{index}].{key}")
        snapshot_ids.append(row["snapshot_id"])
        training_runs.append(row["training_run_id"])
        snapshot_digests.append(row["snapshot_digest"])
        _hex_digest(row["snapshot_digest"], f"independent_snapshots[{index}].snapshot_digest")
        _hex_digest(row["parent_snapshot_digest"], f"independent_snapshots[{index}].parent_snapshot_digest")
        _bool(row.get("observed"), f"independent_snapshots[{index}].observed")
        if _bool(row.get("history_replay"), f"independent_snapshots[{index}].history_replay"):
            raise EvidenceManifestError("independent snapshot history replay is forbidden")
    _unique(snapshot_ids, "independent_snapshots.snapshot_id")
    _unique(training_runs, "independent_snapshots.training_run_id")
    _unique(snapshot_digests, "independent_snapshots.snapshot_digest")

    evaluations = _mapping(manifest["evaluations"], "evaluations")
    for key in ("future_utility", "old_task", "ood", "calibration", "safety", "privacy", "memory"):
        _mapping(evaluations.get(key), f"evaluations.{key}")
    # Metrics can be null in a shadow manifest, but never strings or NaN.
    for key in ("candidate_lcb", "baseline_ucb", "old_task_degradation", "ood_false_acceptance", "calibration_error"):
        value = evaluations["future_utility"].get(key) if key in {"candidate_lcb", "baseline_ucb"} else evaluations[{"old_task_degradation":"old_task", "ood_false_acceptance":"ood", "calibration_error":"calibration"}[key]].get("value")
        if value is not None:
            _finite(value, f"evaluations.{key}", minimum=0.0)
    for key in ("safety", "privacy"):
        _bool(evaluations[key].get("passed"), f"evaluations.{key}.passed")
    _integer(evaluations["memory"].get("deletion_non_resurrection_violations"), "evaluations.memory.deletion_non_resurrection_violations")

    summary = _mapping(manifest["summary"], "summary")
    expected_counts = {
        "future_windows": len(windows),
        "independent_snapshots": len(snapshots),
        "trajectory_count": len(trajectories),
        "observed_trajectory_count": sum(1 for row in trajectory_by_id.values() if row["observed"]),
    }
    for key, expected in expected_counts.items():
        if _integer(summary.get(key), f"summary.{key}") != expected:
            raise EvidenceManifestError(f"summary.{key} does not match manifest contents")
    for key in ("synthetic_only", "history_replay", "no_history_replay", "provenance_complete"):
        _bool(summary.get(key), f"summary.{key}")
    if summary["history_replay"] or not summary["no_history_replay"]:
        raise EvidenceManifestError("summary indicates history replay")
    if summary["synthetic_only"] != (summary["observed_trajectory_count"] == 0 or any(row["source_kind"] == "synthetic_shadow" for row in trajectory_by_id.values())):
        raise EvidenceManifestError("summary.synthetic_only is inconsistent with trajectory provenance")
    if not summary["provenance_complete"]:
        raise EvidenceManifestError("provenance_complete must be true")
    if require_observed and summary["synthetic_only"]:
        raise EvidenceManifestError("synthetic shadow manifest cannot satisfy real-evidence contract")
    if candidate == baseline:
        raise EvidenceManifestError("candidate and baseline snapshot digests must differ")

    integrity = _mapping(manifest["integrity"], "integrity")
    if integrity.get("digest_algorithm") != DIGEST_ALGORITHM or integrity.get("canonicalization") != CANONICALIZATION:
        raise EvidenceManifestError("unsupported integrity algorithm or canonicalization")
    expected_digest = _manifest_digest(manifest)
    if integrity.get("manifest_digest") != expected_digest:
        raise EvidenceManifestError("manifest digest mismatch")
    return dict(manifest)


def qualification_status(manifest: Mapping[str, Any]) -> Dict[str, Any]:
    """Return a conservative status without treating structure as evidence."""
    try:
        validate_manifest(manifest)
    except EvidenceManifestError as error:
        return {"valid": False, "eligible": False, "status": "REJECTED_FAIL_CLOSED", "reason": str(error)}
    summary = manifest["summary"]
    reasons = []
    if summary["synthetic_only"]:
        reasons.append("synthetic_shadow_manifest")
    if summary["observed_trajectory_count"] == 0:
        reasons.append("no_observed_trajectories")
    if len(manifest["future_windows"]) < 2:
        reasons.append("future_windows_below_minimum")
    if len(manifest["independent_snapshots"]) < 3:
        reasons.append("independent_snapshots_below_minimum")
    if not summary["no_history_replay"]:
        reasons.append("history_replay")
    return {
        "valid": True,
        "eligible": not reasons,
        "status": "ELIGIBLE_FOR_EXTERNAL_ACCEPTANCE" if not reasons else "VALID_BUT_NOT_QUALIFYING",
        "reason": "all provenance prerequisites present" if not reasons else "; ".join(reasons),
    }


def to_promotion_evidence(manifest: Mapping[str, Any]) -> Dict[str, Any]:
    """Flatten manifest measurements for candidate_promotion_gate.py."""
    validate_manifest(manifest)
    e = manifest["evaluations"]
    fu = e["future_utility"]
    return {
        "mode": MODE,
        "authority": AUTHORITY,
        "chosen_propensity": float(manifest["summary"].get("chosen_propensity", 0.0)),
        "propensity_sum": float(manifest["summary"].get("propensity_sum", 0.0)),
        "ope_valid": bool(manifest["summary"].get("ope_valid", False)),
        "ope_ess": manifest["summary"].get("ope_ess"),
        "ope_support_complete": bool(manifest["summary"].get("ope_support_complete", False)),
        "global_gap_detected": bool(manifest["summary"].get("global_gap_detected", True)),
        "local_composition_gap": manifest["summary"].get("local_composition_gap"),
        "future_windows": len(manifest["future_windows"]),
        "independent_snapshots": len(manifest["independent_snapshots"]),
        "candidate_lcb": fu.get("candidate_lcb"),
        "baseline_ucb": fu.get("baseline_ucb"),
        "old_task_degradation": e["old_task"].get("value"),
        "ood_false_acceptance": e["ood"].get("value"),
        "calibration_error": e["calibration"].get("value"),
        "deletion_non_resurrection_violations": e["memory"]["deletion_non_resurrection_violations"],
        "safety_gate": e["safety"]["passed"], "privacy_gate": e["privacy"]["passed"],
        "support_gate": bool(manifest["summary"].get("ope_support_complete", False)),
        "retention_gate": bool(e["memory"].get("retention_passed", False)),
        "lineage_gate": bool(manifest["summary"].get("lineage_gate", False)),
        "rollback_gate": bool(e["memory"].get("rollback_passed", False)),
        "provider_dispatch": False, "real_model_call": False, "artifact_selection": False,
        "learned_fbsde": False, "production_caller": False,
        "candidate_snapshot_digest": manifest["candidate_snapshot_digest"],
    }


def build_shadow_manifest(seed: int = 17) -> Dict[str, Any]:
    """Build a deterministic fixture. It is valid structure, never real evidence."""
    event = build_event(seed)
    candidate = event["payload"]["candidate_snapshot_digest"]
    code_digest = _digest("ndu-evidence-runner-shadow-v1")
    config_digest = _digest({"seed": int(seed), "fixture": "synthetic_shadow"})
    trajectory_digest = _digest({"seed": int(seed), "kind": "synthetic_shadow", "event": event["integrity"]["event_digest"]})
    traj = {
        "trajectory_id": f"shadow-trajectory-{seed}", "source_kind": "synthetic_shadow", "observed": False,
        "history_replay": False, "dataset_digest": _digest("synthetic-dataset"),
        "environment_digest": _digest("synthetic-environment"), "runner_code_digest": code_digest,
        "trajectory_digest": trajectory_digest,
    }
    manifest: Dict[str, Any] = {
        "schema_id": SCHEMA_ID, "schema_version": SCHEMA_VERSION, "manifest_type": MANIFEST_TYPE,
        "manifest_id": "evidence-manifest-" + _digest(f"seed:{seed}" )[:24], "status": "shadow_evidence_manifest",
        "candidate_snapshot_digest": candidate, "baseline_snapshot_digest": "b" * 64, "protocol": _protocol(),
        "experiment": {"experiment_id": "ndu-shadow-seed17", "runner_id": "ndu-evidence-runner",
                        "runner_version": "1", "config_digest": config_digest, "code_digest": code_digest,
                        "split_policy": "frozen_non_overlapping", "history_replay": False, "synthetic": True},
        "trajectory_provenance": [traj], "future_windows": [], "independent_snapshots": [],
        "evaluations": {"future_utility": {"candidate_lcb": None, "baseline_ucb": None},
                        "old_task": {"value": None}, "ood": {"value": None}, "calibration": {"value": None},
                        "safety": {"passed": False}, "privacy": {"passed": False},
                        "memory": {"deletion_non_resurrection_violations": 0, "retention_passed": True, "rollback_passed": True}},
        "summary": {"future_windows": 0, "independent_snapshots": 0, "trajectory_count": 1,
                     "observed_trajectory_count": 0, "synthetic_only": True, "history_replay": False,
                     "no_history_replay": True, "provenance_complete": True, "chosen_propensity": 0.25,
                     "propensity_sum": 1.0, "ope_valid": False, "ope_ess": 1.0,
                     "ope_support_complete": True, "global_gap_detected": True, "local_composition_gap": 0.01,
                     "lineage_gate": True},
    }
    manifest["integrity"] = {"digest_algorithm": DIGEST_ALGORITHM, "canonicalization": CANONICALIZATION,
                              "manifest_digest": _manifest_digest(manifest), "source": "ndu_evidence_manifest.build_shadow_manifest"}
    validate_manifest(manifest)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="NDU evidence manifest validator")
    parser.add_argument("--seed", type=int, default=17)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.manifest:
        try:
            value = json.loads(args.manifest.read_text(encoding="utf-8"))
            validate_manifest(value)
            result = {"status": "VALID", "qualification": qualification_status(value), "manifest": value}
        except (OSError, UnicodeError, json.JSONDecodeError, EvidenceManifestError) as error:
            result = {"status": "REJECTED_FAIL_CLOSED", "qualification": {"valid": False, "eligible": False, "reason": str(error)}}
    else:
        value = build_shadow_manifest(args.seed)
        result = {"status": "VALID_SHADOW_FIXTURE", "qualification": qualification_status(value), "manifest": value}
    rendered = json.dumps(result, indent=2, sort_keys=True)
    if args.output:
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)


if __name__ == "__main__":
    main()
