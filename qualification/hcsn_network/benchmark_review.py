"""Independent NumPy-only arithmetic/cost review; zero model execution."""

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def score(logits, labels):
    shifted = logits-logits.max(axis=1, keepdims=True)
    loss = np.log(np.exp(shifted).sum(axis=1))-shifted[np.arange(len(labels)), labels]
    return {"accuracy": float(np.mean(logits.argmax(axis=1) == labels)),
            "cross_entropy": float(np.mean(loss))}


def main():
    parser = argparse.ArgumentParser()
    for name in ("campaign", "protocol", "data", "output"):
        parser.add_argument("--"+name, required=True)
    args = parser.parse_args()
    root = Path(args.campaign)
    protocol = json.loads(Path(args.protocol).read_text())
    seal = json.loads((root/"EVALUATION_SEAL.json").read_text())
    if seal["protocol_sha256"] != sha(Path(args.protocol)):
        raise ValueError("frozen protocol identity changed")
    for name, expected in protocol["data_sha256"].items():
        if sha(Path(args.data)/name) != expected:
            raise ValueError("original data identity changed")
    train_data = np.loadtxt(Path(args.data)/"pendigits.tra", delimiter=",", dtype=np.int64)
    labels = np.loadtxt(Path(args.data)/"pendigits.tes", delimiter=",", dtype=np.int64)[:, -1]
    rng = np.random.default_rng(271828)
    validation_rows = np.sort(np.concatenate([rng.permutation(np.flatnonzero(train_data[:, -1] == k))[:75]
                                              for k in range(10)]))
    expected_validation_labels = train_data[validation_rows, -1]
    failures, rows, checked_validations, total_updates = [], [], 0, 0
    for item in seal["fits"]:
        name = item["directory"]
        fit, evaluation = root/"fits"/name, root/"evaluation"/name
        if item["result_sha256"] is None or not (evaluation/"RESULT.json").exists():
            failures.append({"fit": name, "reason": "training or evaluation did not complete"})
            continue
        if sha(fit/"RESULT.json") != item["result_sha256"] or sha(fit/"selected.pt") != item["selected_sha256"]:
            raise ValueError("sealed fit identity changed")
        result, measured = json.loads((fit/"RESULT.json").read_text()), json.loads((evaluation/"RESULT.json").read_text())
        journal = [json.loads(line) for line in (fit/"training.jsonl").read_text().splitlines()]
        updates = [row for row in journal if "update" in row]
        if [r["update"] for r in updates] != list(range(1, result["updates"]+1)):
            raise ValueError("optimizer journal has gaps or duplicate completed steps")
        if any(not np.isfinite([r["loss"], r["gradient_norm"], r["completed_seconds"]]).all() for r in updates):
            raise ValueError("nonfinite training record")
        total_updates += len(updates)
        eligible = []
        for index, validation in enumerate(result["validations"]):
            with np.load(fit/f"validation-{index:03}.npz", allow_pickle=False) as raw:
                if raw["logits"].shape != (750, 10) or not np.array_equal(raw["labels"], expected_validation_labels):
                    raise ValueError("training validation denominator or labels changed")
                actual = score(raw["logits"], raw["labels"])
            if any(abs(actual[k]-validation[k]) > 1e-12 for k in actual):
                raise ValueError("recorded validation arithmetic disagrees with saved logits")
            if validation["eligible"] != (validation["completed_seconds"] <= protocol["budget_seconds"]):
                raise ValueError("deadline eligibility mismatch")
            if validation["eligible"]:
                eligible.append(validation)
            checked_validations += 1
        best = max(eligible, key=lambda r: (r["accuracy"], -r["cross_entropy"]))
        if best != result["selected"] or result["selected_updates"] != best["updates"] or result["test_rows_read"] != 0:
            raise ValueError("selection was not the best eligible training-only checkpoint")
        with np.load(evaluation/"predictions.npz", allow_pickle=False) as raw:
            if raw["logits"].shape != (3498, 10) or not np.array_equal(raw["labels"], labels):
                raise ValueError("original independent-writer test denominator changed")
            actual = score(raw["logits"], raw["labels"])
        if any(abs(actual[k]-measured["test"][k]) > 1e-12 for k in actual):
            raise ValueError("test arithmetic disagrees with saved logits")
        if measured["selected_checkpoint_sha256"] != item["selected_sha256"] or measured["optimizer_calls"] != 0:
            raise ValueError("test stage changed selection or trained")
        rows.append({"arm": item["arm"], "seed": item["seed"], **actual,
                     "updates": result["updates"], "selected_updates": result["selected_updates"],
                     "parameters": result["parameter_count"], "first_target_seconds": result["time_to_validation_target_first_observed"],
                     "state_bytes": measured["logical_forward_state_bytes"],
                     "physics_bytes": measured["physics_tensor_payload_bytes"],
                     "autograd_payload_bytes": measured["autograd_saved_tensor_payload_bytes_with_repeats"],
                     "forward_backward_seconds": measured["profile_forward_backward_wall_seconds"],
                     "test_inference_seconds": measured["inference_wall_seconds"],
                     "training_wall_seconds": result["training_wall_seconds"],
                     "training_cpu_seconds": result["training_cpu_seconds"]})
    aggregate = {}
    for arm in protocol["arms"]:
        arm_rows = [r for r in rows if r["arm"] == arm]
        aggregate[arm] = {"completed_seeds": len(arm_rows), "seeds": [r["seed"] for r in arm_rows]}
        for name in ("accuracy", "cross_entropy", "updates", "state_bytes", "autograd_payload_bytes",
                     "forward_backward_seconds", "test_inference_seconds"):
            values = [r[name] for r in arm_rows if r[name] is not None]
            aggregate[arm][name] = {"mean": float(np.mean(values)) if values else None,
                                    "sample_sd": float(np.std(values, ddof=1)) if len(values) > 1 else None,
                                    "values": values}
        aggregate[arm]["target_observed"] = sum(r["first_target_seconds"] is not None for r in arm_rows)
    costs = json.loads((root/"FIT_COSTS.json").read_text())+json.loads((root/"EVALUATION_COSTS.json").read_text())
    review = {"status": "COMPLETE_ARITHMETIC_REVIEW" if not failures else "REVIEW_WITH_FAILED_FITS",
              "failures": failures, "fits_reviewed": len(rows), "validation_records_recomputed": checked_validations,
              "completed_optimizer_updates": total_updates,
              "all_child_cpu_seconds": sum(c["cpu_seconds"] for c in costs),
              "sum_child_wall_seconds_not_campaign_elapsed": sum(c["wall_seconds"] for c in costs),
              "max_child_rss_kib": max(c["maxrss_kib"] for c in costs),
              "all_child_failures": sum(c["exit_code"] != 0 for c in costs),
              "new_model_calls": 0, "new_optimizer_calls": 0, "aggregate": aggregate, "rows": rows,
              "seed_sd_is_not_independent_dataset_uncertainty": True,
              "global_advantage_or_training_adequacy_proven": False}
    output = Path(args.output)
    if output.exists():
        raise FileExistsError("independent review output already exists")
    output.write_text(json.dumps(review, indent=2)+"\n")
    print(json.dumps({"status": review["status"], "fits": len(rows), "completed_updates": total_updates}), flush=True)


if __name__ == "__main__":
    main()
