"""Unseal the new V4 final labels once, after every action and audit is frozen."""

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time

import numpy as np

from cell_field_closure_audit import verify_run
from cell_field_closure_data import claim_final_access, registered_source_directory, write
from cell_field_closure_run import seal, source_hashes
from cell_field_features import file_hash


def source_scores(predictions, labels, floor=1e-15):
    p, y = np.asarray(predictions), np.asarray(labels)
    if (p.shape != (len(y), 4) or y.dtype.kind not in "iu" or np.any(y < 0) or np.any(y >= 4)
            or not np.isfinite(p).all() or np.any(p < 0) or np.any(p > 1)
            or not np.allclose(p.sum(axis=1), 1.0, atol=1e-13, rtol=0)):
        raise ValueError("invalid frozen probabilities or final classes")
    return -np.log(np.clip(p[np.arange(len(y)), y], floor, 1)), (p.argmax(axis=1) == y).astype(float)


def paired_interval(difference, labels, *, replicates=10000, seed=431026, family_size=6, alpha=0.05):
    """Resample whole paired sources within class, after fixed-seed averaging."""
    difference, labels = np.asarray(difference), np.asarray(labels)
    if (difference.ndim != 1 or labels.shape != difference.shape or not np.isfinite(difference).all()
            or set(labels.tolist()) != set(range(4))):
        raise ValueError("four-class finite paired source differences required")
    rng = np.random.default_rng(seed)
    draws = np.concatenate([rng.choice(np.flatnonzero(labels == c),
                            size=(replicates, np.count_nonzero(labels == c)), replace=True)
                            for c in range(4)], axis=1)
    means = difference[draws].mean(axis=1)
    tail = alpha / (2 * family_size)
    interval = np.quantile(means, [tail, 1 - tail], method="linear")
    return {"mean_difference": float(difference.mean()), "interval": interval.tolist(),
            "quantiles": [tail, 1 - tail], "replicates": replicates, "bootstrap_seed": seed,
            "source_count": len(labels), "family_size": family_size,
            "passes": bool(interval[1] < 0), "method": "paired class-stratified source percentile bootstrap",
            "scope": "conditional on three fixed fitted seeds and source sampling; no task/seed population or finite-sample guarantee"}


def preflight(runs, data, audit_path):
    """Every check here is label-free and must pass before the access ledger exists."""
    root, data = Path(runs), Path(data)
    plan, run = verify_run(root)
    data = registered_source_directory(plan, data)
    frozen = json.loads((root / "source-freeze.json").read_bytes())
    if source_hashes() != frozen["files"]:
        raise ValueError("evaluation source differs from the published executed source")
    inputs = json.loads((root / "inputs.json").read_bytes())
    receipt = json.loads((data / "data_receipt.json").read_bytes())
    sources = json.loads((data / "sources.json").read_bytes())["rows"]
    report = json.loads(Path(audit_path).read_bytes())
    if (file_hash(data / "data_receipt.json") != inputs["new_data_receipt_sha256"]
            or file_hash(data / "sources.json") != inputs["new_sources_sha256"]
            or receipt["files"]["final_labels.json"]["sha256"] != inputs["final_labels_sha256"]
            or receipt["protocol_sha256"] != frozen["protocol_sha256"]
            or receipt["source_owner_directory"] != plan["source_owner_directory"]
            or receipt["prepared_source_directory"] != str(data)
            or report["status"] != "passed" or report["final_labels_opened"] is not False
            or report["run_seal_sha256"] != file_hash(root / "run-seal.json")
            or len(report["ranking_rows"]) != 90 or report["registered_branches"] != 306
            or report["replayed_optimizer_steps"] != 2448 or report["replayed_anchor_training_steps"] != 480):
        raise ValueError("new source or pre-unseal audit binding differs")
    total = sum(x["rows"] for x in plan["new_source_plan"])
    expected_roles = [x["role"] for x in plan["new_source_plan"] for _ in range(x["rows"])]
    if (len(sources) != total or [x["index"] for x in sources] != list(range(total))
            or [x["role"] for x in sources] != expected_roles
            or len({x["source_id"] for x in sources}) != total
            or len({x["component_id"] for x in sources}) != total):
        raise ValueError("new source census is not uniquely registered")
    # Check every registered heldout prediction before any final class is read.
    for row in run["records"] + run["warmups"]:
        with np.load(root / row["path"], allow_pickle=False) as archive:
            predictions = archive["predictions"]
        source_scores(predictions, np.zeros(total, dtype=np.int64), plan["external_nll_probability_floor"])
    return plan, run, inputs, receipt, sources


def evaluate(runs, data, audit, output):
    root, data, output = Path(runs), Path(data), Path(output)
    plan, run, inputs, receipt, sources = preflight(root, data, audit)
    output.mkdir(parents=True, exist_ok=False)
    began, cpu, opened = time.perf_counter_ns(), time.process_time_ns(), False
    try:
        access = {"schema": "hepta.cell-closure-final-access.v4",
                  "at_utc": datetime.now(timezone.utc).isoformat(),
                  "run_seal_sha256": file_hash(root / "run-seal.json"),
                  "pre_unseal_audit_sha256": file_hash(audit),
                  "expected_final_sha256": inputs["final_labels_sha256"],
                  "source_owner_directory": plan["source_owner_directory"],
                  "prepared_source_directory": str(registered_source_directory(plan, data)),
                  "attempt": 1, "outputs": str(output.absolute()),
                  "policy": "single final exposure; preserve failures, do not select a new protocol on these sources",
                  "authority": "DENY_ALL"}
        # Both preparation and final access use this one published source owner.
        claim_final_access(plan, data, access)
        opened = True
        write(output / "final-access.json", access)
        payload = (data / "final_labels.json").read_bytes()
        if (hashlib.sha256(payload).hexdigest() != inputs["final_labels_sha256"]
                or len(payload) != receipt["files"]["final_labels.json"]["bytes"]):
            raise ValueError("new final label payload differs from its pre-run commitment")
        final = json.loads(payload)
        roles = {row["role"]: row for row in plan["new_source_plan"]}
        if final["classes"] != 4 or set(final["roles"]) != set(roles):
            raise ValueError("unregistered final role")
        all_labels, indices = np.full(len(sources), -1, dtype=np.int64), {}
        for role, values in final["roles"].items():
            expected = [row["index"] for row in sources if row["role"] == role]
            y = np.asarray(values["labels"])
            if (set(values) != {"indices", "labels", "source_ids"} or values["indices"] != expected
                    or y.shape != (roles[role]["rows"],) or y.dtype.kind not in "iu"
                    or Counter(y.tolist()) != {c: len(y) // 4 for c in range(4)}
                    or values["source_ids"] != [sources[i]["source_id"] for i in expected]):
                raise ValueError("final classes, balance or source identities differ")
            indices[role] = np.asarray(expected)
            all_labels[expected] = y
        predictions = {}
        for row in run["records"]:
            with np.load(root / row["path"], allow_pickle=False) as archive:
                predictions[(row["anchor"], row["action"])] = source_scores(
                    archive["predictions"], all_labels, plan["external_nll_probability_floor"])
        warm = {}
        for row in run["warmups"]:
            with np.load(root / row["path"], allow_pickle=False) as archive:
                warm[(row["head"], row["seed"])] = source_scores(
                    archive["predictions"], all_labels, plan["external_nll_probability_floor"])
        chosen, per_seed = {}, []
        for anchor in run["anchors"]:
            for arm in plan["arms"] + ["zero", "warmup"]:
                scores = (warm[(anchor["head"], anchor["seed"])] if arm == "warmup" else
                          predictions[(anchor["id"], 0 if arm == "zero" else anchor["selected"][arm])])
                chosen[(anchor["head"], anchor["anchor_offset"], anchor["seed"], arm)] = scores
                for role, marks in indices.items():
                    per_seed.append({"anchor": anchor["id"], "arm": arm, "role": role,
                        "nll": float(scores[0][marks].mean()), "accuracy": float(scores[1][marks].mean())})

        primary, differences, secondary = [], [], []
        config = plan["external_primary"]
        marks = indices[config["role"]]
        for head in plan["head_modes"]:
            for arm, baseline in config["comparisons"]:
                delta = np.mean([chosen[(head, config["anchor_offset"], seed, arm)][0][marks]
                                 - chosen[(head, config["anchor_offset"], seed, baseline)][0][marks]
                                 for seed in plan["seeds"]], axis=0)
                interval = paired_interval(delta, all_labels[marks], replicates=config["bootstrap_replicates"],
                    seed=config["bootstrap_seed"], family_size=config["family_size"], alpha=config["alpha"])
                primary.append({"head": head, "arm": arm, "baseline": baseline, "role": config["role"],
                                "anchor_offset": config["anchor_offset"], **interval})
                differences.append({"head": head, "arm": arm, "baseline": baseline,
                    "source_ids": [sources[i]["source_id"] for i in marks],
                    "labels": all_labels[marks].tolist(), "fixed_seed_mean_nll_difference": delta.tolist()})
            for offset in plan["anchor_offsets"]:
                for arm in plan["arms"] + ["zero", "warmup"]:
                    for role, subset in indices.items():
                        metrics = np.mean([chosen[(head, offset, seed, arm)] for seed in plan["seeds"]], axis=0)
                        warmed = np.mean([warm[(head, seed)] for seed in plan["seeds"]], axis=0)
                        secondary.append({"head": head, "anchor_offset": offset, "arm": arm, "role": role,
                            "nll": float(metrics[0, subset].mean()), "accuracy": float(metrics[1, subset].mean()),
                            "nll_change_from_warmup": float((metrics[0, subset] - warmed[0, subset]).mean()),
                            "accuracy_change_from_warmup": float((metrics[1, subset] - warmed[1, subset]).mean())})
        if len(primary) != config["family_size"]:
            raise ValueError("registered comparison family incomplete")
        write(output / "source-differences.json", {"rows": differences, "seeds": plan["seeds"]})
        result = {"schema": "hepta.cell-closure-evaluation.v4", "primary": primary,
                  "primary_passed": sum(row["passes"] for row in primary), "primary_registered": 6,
                  "secondary_point_estimates": secondary, "per_seed_point_estimates": per_seed,
                  "sources": len(sources), "reserved_components": receipt["reserved_components"],
                  "source_commit": run["source_commit"], "run_seal_sha256": access["run_seal_sha256"],
                  "final_labels_sha256": inputs["final_labels_sha256"], "final_labels_opened": True,
                  "wall_ns": time.perf_counter_ns() - began, "cpu_ns": time.process_time_ns() - cpu,
                  "interpretation": "historical source-disjoint external evaluation of six reused fitted trajectories; finite pool only; no independent training-task, topology-growth, AGI or production claim",
                  "retention_scope": "new old-source terminal risk relative to warmup; not pathwise retention guarantee",
                  "authority": "DENY_ALL", "production_authority": False}
        write(output / "evaluation.json", result)
        identity = seal(output, "evaluation-seal.json")
        return {"primary_passed": result["primary_passed"], "primary_registered": 6,
                "final_labels_opened": True, "evaluation_seal_sha256": identity}
    except Exception as error:
        write(output / "failure.json", {"error_type": type(error).__name__, "message": str(error),
              "final_access_attempt_started": opened, "post_access_sources_consumed": opened,
              "partial_outputs_preserved": True, "at_utc": datetime.now(timezone.utc).isoformat()})
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("runs", "data", "audit", "output"):
        parser.add_argument("--" + name, required=True)
    print(json.dumps(evaluate(**vars(parser.parse_args())), sort_keys=True))
