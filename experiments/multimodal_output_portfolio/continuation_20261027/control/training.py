"""Fit only a state readout; record actual delivery and original-owner states."""
import json
from pathlib import Path
import time

import numpy as np

from ...repair_20261026.risk_feedback.media import emit, readback
from .client import Q, continuation, digest, write


def prefix(native, cue):
    return [native.tick(0, 0, {"cue": cue, "candidate": action, "stage": "current_scan"}) for action in range(4)]


def prepare(native, root, protocol):
    calibration = root / "ENCODER_DOMAIN_PROOF.json"
    write(calibration, {"schema": "hepta.continuation.encoder-domain-proof.v1",
        "confidence_target": "registered_public_encoder_domain_validity",
        "semantic_quality_qualification": False,
        "finite_domain_ece_ppm": 0, "finite_domain_false_acceptance_ppm": 0,
        "definition": "On active calibration sequences, the registered deterministic encoder exactly copies its computed drive to prediction. Invalid phase/scalar combinations are rejected before journal mutation.",
        "basis": "Finite-domain algebraic identity, subsequently checked through actual owner calls; no empirical speaker/writer or semantic quality qualification.",
        "valid_feedback_symbols": [-1, -0.5, 0, 1], "active_sequence_only": True,
        "expired_sequences": "fail-closed abstention, outside active calibration validity"})
    untrained = root / "UNTRAINED_MODEL.json"
    write(untrained, {"schema": "hepta.continuation.owner-readout.v1", "weights": [0.0] * 11})
    records, features, labels = [], [], []
    rng = np.random.default_rng(protocol["training_seed"])
    faults = rng.permutation(np.tile(np.arange(3), protocol["training_cases"] // 3))
    for index, fault in enumerate(faults):
        directory = root / "training" / f"case-{index:03}"
        directory.mkdir(parents=True)
        native.open(directory / "owner", f"training.{index}", 64, untrained, calibration)
        first = prefix(native, index % 4)
        if any(row["native_abstain"] for row in first):
            raise ValueError("Training first delivery denied by actual owner")
        paths = emit(directory / "initial", index % 4, int(fault))
        observed = readback(paths)
        delivered_at = time.monotonic_ns()
        feedback = protocol["numeric_feedback_by_fault"][observed["fault_class"]]
        write(directory / "DELIVERED.json", {"paths": paths, "observed": observed, "delivered_monotonic_ns": delivered_at})
        ticks = continuation(native, feedback, observed)
        if any(row["native_abstain"] for row in ticks):
            raise ValueError("Training continuation denied")
        x = [1.0] + [v / Q for v in ticks[-1]["eligibility_before_q24"]]
        y = int(observed["fault_class"] != 0)
        features.append(x)
        labels.append(y)
        native.close()
        write(directory / "TRANSCRIPT.json", native.transcript)
        record = {"index": index, "observed_fault": observed["fault_class"], "features": x,
            "label_is_public_repair_need": y, "ticks": ticks, "paths": paths,
            "readback_sha256": digest(observed), "scalar_not_in_readout_features": True}
        write(directory / "TRAINING_RECORD.json", record)
        records.append(record)
    x, y = np.asarray(features), np.asarray(labels)
    w = np.zeros(11)
    for _ in range(protocol["training_updates"]):
        p = 1 / (1 + np.exp(-(x @ w)))
        w -= protocol["learning_rate"] * x.T @ (p - y) / len(y)
    model = root / "MODEL.json"
    write(model, {"schema": "hepta.continuation.owner-readout.v1", "weights": w.tolist()})
    write(root / "TRAINING.json", {"examples": len(y), "trainable_coefficients": 11,
        "gradient_updates": protocol["training_updates"], "initial_weights_sha256": digest([0.0] * 11),
        "final_weights_sha256": digest(w.tolist()), "features_sha256": digest(features),
        "label_sha256": digest(labels), "training_accuracy": float(((x @ w >= 0) == y).mean()),
        "cross_entropy": float(np.mean(np.logaddexp(0, x @ w) - y * (x @ w))),
        "kernel_parameters_trained": False, "natural_codec_trained": False,
        "training_source_population_claim": False,
        "records_sha256": digest(records)})
    return model, calibration


def verify_domain(native, root, model, calibration):
    directory = root / "domain-verification"
    directory.mkdir()
    native.open(directory / "owner", "domain-verification", 6, model, calibration)
    first = prefix(native, 0)
    before = native.call({"command": "Status"})
    rejection = native.call({"command": "Tick", "event_id": "invalid-domain-input", "phase": 1, "feedback_q24": 12345,
                             "receipt_digest": digest({"invalid_public_input": True})}, expect_error=True)
    after = native.call({"command": "Status"})
    branches = [native.call({"command": "Forecast", "feedback_q24": round(f * Q),
        "branch": f"valid-{index}"}) for index, f in enumerate([1, -0.5, -1, 0])]
    native.close()
    passed = before == after and all(b["committed_parent_unchanged"] for b in branches)
    passed &= all(not b["ticks"][0]["native_abstain"] and not b["ticks"][1]["native_abstain"]
                  and b["ticks"][2]["native_abstain"] for b in branches)
    passed &= all(t["confidence_ppm"] == 1_000_000 for b in branches for t in b["ticks"][:2])
    write(directory / "TRANSCRIPT.json", native.transcript)
    result = {"passed": bool(passed), "invalid_input_rejection": rejection,
        "invalid_input_did_not_advance_journal": before == after,
        "forks_preserved_parent": all(b["committed_parent_unchanged"] for b in branches),
        "actual_expired_tick_abstentions": sum(b["ticks"][2]["native_abstain"] for b in branches),
        "finite_domain_active_confidence_ppm": [t["confidence_ppm"] for t in first],
        "semantic_quality_qualification": False, "native_owner_authority": "DENY_ALL"}
    write(root / "DOMAIN_VERIFICATION.json", result)
    if not passed:
        raise ValueError("Finite-domain or real expiry check failed")
