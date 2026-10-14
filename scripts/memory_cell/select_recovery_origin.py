"""Explicit provenance bridge from one-arm recovery to SELECT followthrough.

No optimizer, model loader, network call, fallback artifact or semantic grade.
The old cancelled run remains cancelled; the new recovery must independently
finish successfully and bind every preserved/restarted output before use.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import re

import five_causal_experiments as c
import relevance_recovery as recovery
import select_question_relevance as protocol

PROFILE = "hepta.reader.select-recovery-origin.v1"
RECOVERY_RUN = 38518485794
RECOVERY_SOURCE = "61e909b2b413661a412aba5714afdbe36c4435b6"
RECOVERY_WORKFLOW = ".github/workflows/hepta-relevance-recovery.yml"
ARTIFACT_NAME = "hepta-question-relevance-recovered-development"
REPOSITORY = "TrillionniumFoundation/hepta-private-ci"


def validate_source(value):
    c.require(value == RECOVERY_SOURCE, "unregistered recovery source; no latest-ref substitution")


def select_completed_artifact(run, artifacts):
    """Select exact successful run metadata, never the newest available model.

    Caller must obtain metadata through the authenticated GitHub repository
    endpoint. Local JSON cannot establish its own external authority. A run
    not completed/successful is explicitly deferred, not a model test pass.
    """
    c.require(isinstance(run, dict) and isinstance(artifacts, dict), "GitHub metadata objects required")
    c.require(type(run.get("id")) is int and run["id"] == RECOVERY_RUN
              and run.get("head_sha") == RECOVERY_SOURCE and run.get("path") == RECOVERY_WORKFLOW,
              "wrong recovery run/source/workflow")
    c.require(run.get("repository", {}).get("full_name") == REPOSITORY
              and run.get("head_repository", {}).get("full_name") == REPOSITORY,
              "recovery repository identity mismatch")
    c.require(type(run.get("run_attempt")) is int and run["run_attempt"] >= 1, "run attempt missing")
    common = {"schema": PROFILE + ".dependency", "recovery_run": RECOVERY_RUN,
              "recovery_source": RECOVERY_SOURCE, "run_attempt": run["run_attempt"],
              "observed_status": run.get("status"), "observed_conclusion": run.get("conclusion"),
              "metadata_sha256": c.digest({"run": run, "artifacts": artifacts}),
              "original_run": recovery.CANCELLED_RUN, "original_status": "cancelled",
              "model_execution_completed": False, "production_accepted": False}
    if run.get("status") != "completed" or run.get("conclusion") != "success":
        return common | {"status": "deferred_upstream_not_successful", "ready": False,
                         "artifact_id": None, "artifact_sha256": None}
    entries = artifacts.get("artifacts")
    c.require(isinstance(entries, list) and type(artifacts.get("total_count")) is int
              and artifacts["total_count"] == len(entries) <= 100,
              "artifact metadata page incomplete; do not guess a candidate")
    c.require(all(isinstance(x, dict) for x in entries), "invalid artifact entry")
    chosen = [x for x in entries if x.get("name") == ARTIFACT_NAME]
    c.require(len(chosen) == 1, "one exact completed recovery artifact required")
    a = chosen[0]
    digest = a.get("digest")
    c.require(type(a.get("id")) is int and a["id"] > 0 and a.get("expired") is False
              and type(a.get("size_in_bytes")) is int and a["size_in_bytes"] > 0
              and isinstance(digest, str) and re.fullmatch(r"sha256:[0-9a-f]{64}", digest),
              "recovery artifact identity/expiry/digest invalid")
    w = a.get("workflow_run", {})
    c.require(w.get("id") == RECOVERY_RUN and w.get("head_sha") == RECOVERY_SOURCE,
              "artifact belongs to another recovery run/source")
    return common | {"status": "ready_for_verified_read_only_followthrough", "ready": True,
                     "artifact_id": a["id"], "artifact_sha256": digest.split(":", 1)[1],
                     "artifact_bytes": a["size_in_bytes"]}


def execution_plan(base, training_sha256, original_sha256, expected_recovery_source=None):
    """Default output is exactly the historical plan; recovery is versioned."""
    c.require(c.sha(training_sha256) and c.sha(original_sha256), "external archive pins required")
    config = base | {"training_archive_sha256": training_sha256,
                     "original_archive_sha256": original_sha256}
    if expected_recovery_source is None:
        return config
    validate_source(expected_recovery_source)
    config.update(schema="hepta.reader.select-question-recovered-followthrough.v1",
                  original_training_source=base["training_source"],
                  original_training_run=base["training_run"],
                  original_training_status="cancelled", training_source=RECOVERY_SOURCE,
                  training_run=RECOVERY_RUN, training_origin_profile=PROFILE,
                  original_cancelled_archive_sha256=recovery.CANCELLED_SHA,
                  historical_and_restarted_outputs_separately_bound=True)
    return config


def validate_recovery_training(root, expected_source):
    """Validate actual recovered material after external ZIP/member checking.

    Calls the canonical recovery validator, then checks the original/restarted
    journal joins, raw seals, all slot denominators, per-arm origins and paid
    abandoned work. No report is transformed into an old successful report.
    """
    validate_source(expected_source)
    root = Path(root)
    c.require(not (root / "failure.json").exists() and not (root / "restarted/failure.json").exists(),
              "failed recovery output cannot supply candidates")
    manifest = c.load(root / "recovery-manifest.json")
    c.require(manifest.get("execution_source") == expected_source, "different recovered execution source")
    study, report, cases, joined = recovery.validate_completed(root)
    from question_relevance_trial import PLAN
    plan = c.load(study / "plan.json")
    c.require(c.canonical({k: v for k, v in plan.items() if k != "training"}) == c.canonical(PLAN),
              "recovery changed the registered scientific plan")
    c.require(len(cases) == 28 and sum(x["request"] is not None for x in cases) == 27,
              "recovered input census differs")
    for key in ("reader_adequacy_established", "independent_confirmation", "production_accepted", "five_experiments_completed"):
        c.require(report.get(key) is False, "recovery cannot create model authority")
    c.require(manifest.get("original_artifact") == recovery.CANCELLED_ARTIFACT
              and manifest.get("production_accepted") is False and report.get("old_interrupted_cost_is_additional") is True,
              "original provenance or abandoned costs omitted")
    cancelled_events = recovery.read_chain(root / "provenance/cancelled-events.jsonl")
    restarted_events = recovery.read_chain(root / "restarted/events.jsonl")
    interrupted = recovery.optimizer_census(recovery.read_chain(root / "provenance/interrupted-optimizer.jsonl"))
    c.require(interrupted == manifest["interrupted_work"], "abandoned work differs from actual journal")
    all_raw, initial = [], set()
    for arm in protocol.ARMS:
        events = restarted_events if arm == recovery.RESTART else cancelled_events
        checked = recovery.check_arm(study, arm, cases, events)
        summary = report["arms"][arm]
        origin = "restarted_from_base" if arm == recovery.RESTART else "verified_cancelled_artifact_completed_arm"
        c.require(summary.get("origin") == origin
                  and summary.get("integrity_basis") == "fresh_strict_saved_checkpoint_reload_no_new_generation"
                  and summary.get("historical_in_memory_integrity_receipt_available") is (arm == recovery.RESTART),
                  "historical and restarted integrity provenance mixed")
        all_raw.extend(checked["raw"])
        if checked["training"] is not None:
            initial.add(checked["training"]["initial_adapter_sha256"])
    c.require(len(initial) == 1 and all_raw == c.load(study / "raw-answers.json"),
              "initial adapter or original arm ordering changed")
    c.require(report.get("planned_rows") == len(all_raw) == 112
              and report.get("successful_model_calls_across_origins") == sum(x["status"] == "succeeded" for x in all_raw) == 108
              and report.get("new_generation_calls") == 27 and report.get("reused_generation_calls") == 81
              and report.get("new_optimizer_updates") == 112 and report.get("new_training_forwards") == 864,
              "recovered actual-work census differs from registered completion")
    return study, report, cases, joined


def origin_receipt(root):
    m = c.load(Path(root) / "recovery-manifest.json")
    report = c.load(Path(root) / "study/report.json")
    return {"profile": PROFILE, "recovery_run": RECOVERY_RUN, "recovery_source": RECOVERY_SOURCE,
            "manifest_sha256": c.digest(m), "original_run": m["original_run"],
            "original_status": m["original_status"], "original_artifact_sha256": m["original_artifact_sha256"],
            "reused_arms": m["reused_arms"], "restarted_arms": m["restarted_arms"],
            "interrupted_work": m["interrupted_work"],
            "upstream_new_optimizer_updates": report["new_optimizer_updates"],
            "upstream_new_training_forwards": report["new_training_forwards"],
            "upstream_reuse_is_not_free_verification": True,
            "new_followthrough_optimizer_updates": 0, "original_failure_relabelled": False,
            "reader_adequacy_established": False, "production_accepted": False}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--run-json", type=Path, required=True)
    p.add_argument("--artifacts-json", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args(argv)
    result = select_completed_artifact(c.load(a.run_json), c.load(a.artifacts_json))
    c.write_new(a.output, result)
    print(c.canonical(result).decode(), flush=True)
    return 0 if result["ready"] else 3


if __name__ == "__main__":
    raise SystemExit(main())
