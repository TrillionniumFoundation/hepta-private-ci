"""Synthetic source/Cell pairing fixtures only; no production signatures."""
from datetime import datetime, timezone
import hashlib
from pathlib import Path

from four_gate_baseline import OWNER_SOURCE, PROFILE, _micros
from four_gate_common import canonical, digest
from qualified_eval import audit_dataset
from test_four_gate_learning_bridge import ExistingLearningBridgeTests
from test_four_gate_controls import DEPTHS, validation_fixture
from test_four_gate_selective import selective_fixture


def fixture():
    old = ExistingLearningBridgeTests()
    old.setUp()
    # Do not retain the unrelated unittest tempdir just to construct input data.
    old.doCleanups()
    cell, plan = old.old, old.plan
    plan.update(schema="hepta.four-gate.plan.v2", assessment_time="2026-01-08T00:00:00Z")
    for gate in ("reasoning", "ndu"):
        plan[gate].update(validation_sha256=digest(validation_fixture(plan)),
                         validation_depths=list(DEPTHS), selection_cost_weights={})
    plan["reasoning"]["exact_algorithm_applicable"] = True
    plan["learning"]["selective"] = selective_fixture()[0]["learning"]["selective"]
    scope = digest("synthetic-scope")
    for row in cell.rows:
        row.update(domain="fixture-domain", native_scope_digest=scope)
    cell.trial["dataset_audit"] = audit_dataset(cell.rows)
    freeze = _micros(plan["selection_cutoff"])
    current = _micros("2026-01-07T23:59:58Z")
    descriptor = {k: digest(k) for k in ("policy_digest", "route_digest", "checkpoint_digest",
        "runtime_receipt_digest", "artifact_load_receipt_digest", "source_use_receipt_digest")}
    descriptor.update(kind="deployed_deterministic", scope_digest=scope,
        objective_digest=plan["objective_sha256"], generation=3, frozen_at_unix_micros=freeze,
        model_manifest_digest=None, weights_digest=None, code_digest=digest("deterministic-code"))
    sealed, sources, observations = [], [], {}
    for row in cell.rows:
        if row["split"] == "ood":
            continue
        split = row.get("future_window") if row["split"] == "future" else {
            "train": "train", "calibration": "calibration", "test": "holdout"}[row["split"]]
        gold = {k: row[k] for k in ("state", "question", "language", "domain")}
        at = _micros(row["event_time"])
        gold.update(id=row["case_id"], option_order=row["options"], gold=row["options"][row["label"]],
                    source_group=row["group_id"], split=split, observed_at_ms=at // 1000)
        sealed.append(gold)
        obs = digest({k: gold[k] for k in ("state", "question", "option_order", "language", "domain")})
        source = {"id": row["case_id"], "episode_id": row["case_id"], "split": split,
            "source_group": row["group_id"], "decision_record_digest": digest(["decision", row["case_id"]]),
            "terminal_outcome_record_digest": digest(["outcome", row["case_id"]]),
            "observation_sha256": obs, "observed_at_unix_micros": at,
            "terminal_at_unix_micros": at + 500_000, "terminality": "Terminal"}
        sources.append(source)
        if split != "train":
            observations[row["case_id"]] = {k: source[k] for k in (
                "id", "split", "decision_record_digest", "observation_sha256")}
            observations[row["case_id"]].update(generation=3, decision_at_unix_micros=at + 10,
                production_runtime_receipt_digest=digest(["runtime", row["case_id"]]),
                disposition="selected", selected_option="no")
    sealed_raw = b"".join(canonical(r) + b"\n" for r in sealed)
    payload = {"schema": "hepta.neuron.real-cohort.v1", "family": "decisions",
        "source": "hepta.learning-ledger.LedgerWriter", "no_change": descriptor,
        "frozen_plan_digest": digest("frozen-native-plan"), "sealed_dataset_sha256": hashlib.sha256(sealed_raw).hexdigest(),
        "source_current_revalidated_at_unix_micros": current, "rows": sources}
    ds = {k: digest(k) for k in ("dataset_digest", "ledger_head_digest", "correction_cut_digest",
        "revocation_cut_digest", "inclusion_policy_digest")}
    ds.update(receipt_schema="DatasetSnapshotReceiptV3", snapshot_id="synthetic-snapshot",
        objective_digest=plan["objective_sha256"], eligible_frontier=1000, outcome_watermark=1000,
        source_record_digests=sorted({s[k] for s in sources for k in ("decision_record_digest", "terminal_outcome_record_digest")}))
    payload["dataset"] = ds
    cohort = {"schema": "hepta.neuron.real-cohort.v1", "payload": payload,
              "attestations": {r: {"signed_at_unix_micros": current + 100} for r in (
                  "ledger_owner", "observation_owner", "baseline_owner", "evaluator", "observer")}}
    packet = {"schema": "hepta.neuron.production-baseline-pair.v1", "body": {},
              "owner_signature": {"signed_at_unix_micros": current + 200}}
    verified = {"observations": observations, "verification": {"fixture_only": True},
                "owner_signature_payload_sha256": digest("synthetic-owner-signature")}
    plan["production_baseline"] = {"profile": PROFILE, "owner_source_sha": OWNER_SOURCE,
        "expected_descriptor_sha256": digest(descriptor), "owner_frozen_plan_sha256": payload["frozen_plan_digest"],
        "max_revalidation_age_us": 5_000_000}
    return plan, cell, cohort, sealed, packet, verified


def write_cell(root, cell):
    originals = {"dataset": b"".join(canonical(r) + b"\n" for r in cell.rows),
                 "trial": canonical(cell.trial), "prelabel_journal": cell.journal}
    refs = {}
    for name, raw in originals.items():
        (Path(root) / name).write_bytes(raw)
        refs[name] = {"path": name, "sha256": hashlib.sha256(raw).hexdigest()}
    return refs
