"""POSTHOC query-binding diagnostic; run only when the owner releases CPU time.

The diagnostic was proposed after the original IID scores were observed. It
does not train, choose checkpoints or modify any frozen model implementation.
"""

import argparse
import csv
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from comparison_models import load_model
from content import Model
from content_audit import file_hash, write_json
from content_tasks import array_hash, sample_batch


FAMILIES = ("ordinary", "analytic", "lif_surrogate", "transformer")
WIDTHS, SEEDS = (16, 32, 64), (11, 23, 37)
SUBGROUPS = ("all_distinct", "two_same", "all_same")
TRIGGER = (
    "POSTHOC: after observing the registered IID results, the owner noticed that "
    "many associative-recall scores were near the query-ignorant majority-value "
    "expectation 17/27. Full-history improvement over last-observation-only "
    "therefore does not by itself establish key-value binding."
)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def frozen_models(base):
    records = []
    for family in FAMILIES:
        namespace = "content" if family in ("ordinary", "analytic") else "comparison"
        for width in WIDTHS:
            for seed in SEEDS:
                run = base / "evidence" / namespace / "runs" / "associative_recall" / f"{family}_w{width}_s{seed}"
                config = json.loads((run / "run_config.json").read_text())
                receipt = json.loads((run / "FINAL_CHECKPOINT_RECEIPT.json").read_text())
                metrics = json.loads((run / "evaluation_test/metrics.json").read_text())
                identity = ("associative_recall", family, width, seed)
                for source in (config, metrics):
                    require(tuple(source[k] for k in ("task", "family", "width", "seed")) == identity,
                            "model identity differs from registered directory")
                require(metrics["data_partition"] == "test", "expected existing frozen test results")
                for name, sha in config["source_sha256"].items():
                    require(file_hash(base / name) == sha, f"frozen source changed: {name}")
                checkpoint = file_hash(run / "final.npz")
                require(checkpoint == receipt["checkpoint_sha256"] == metrics["checkpoint_sha256"],
                        f"checkpoint changed: {run}")
                records.append({"family": family, "width": width, "seed": seed, "run": run,
                                "checkpoint_sha256": checkpoint, "iid_metrics": metrics["splits"]["iid"]})
    return records


def shared_inputs():
    """Replay exactly the first eight 64-example IID batches from seed 1700000."""
    rng = np.random.default_rng(1700000)
    batches, batch_hashes, queries, labels_by_query = [], [], [], []
    for _ in range(8):
        item = sample_batch("associative_recall", rng, 64, split="test")
        token = item["x"].argmax(axis=2)
        require(np.array_equal(item["x"], np.eye(9)[token]), "recall inputs are not raw one-hot tokens")
        keys, values = token[:6:2], token[1:6:2] - 3
        require(np.array_equal(np.sort(keys, axis=0), np.broadcast_to(np.arange(3)[:, None], keys.shape)),
                "history does not contain each key exactly once")
        require(np.all((0 <= values) & (values < 3)), "invalid value token")
        require(np.all(token[-2] == 6) and np.all((0 <= token[-1]) & (token[-1] < 3)),
                "query suffix does not match the registered task")
        by_query = np.empty((64, 3), dtype=np.int64)
        for position in range(3):
            by_query[np.arange(64), keys[position]] = values[position]
        require(np.array_equal(by_query[np.arange(64), token[-1]], item["y"]),
                "original label does not match independently decoded key-value history")
        queries.append(token[-1].copy())
        labels_by_query.append(by_query)
        batches.append(item)
        batch_hashes.append(array_hash(item["x"], item["y"], item["dt"], item["ids"]))
    labels_by_query = np.concatenate(labels_by_query)
    counts = np.sum(labels_by_query[:, :, None] == np.arange(3)[None, None, :], axis=1)
    maximum = counts.max(axis=1)
    masks = {name: maximum == size for name, size in zip(SUBGROUPS, (1, 2, 3))}
    return batches, batch_hashes, np.concatenate(queries), labels_by_query, counts.argmax(axis=1), masks


def measured_accuracy(prediction, label, mask=None):
    if mask is not None:
        prediction, label = prediction[mask], label[mask]
    return float(np.mean(prediction == label)) if len(label) else None


def model_metrics(original, swapped, original_label, query_labels, query, majority, masks):
    alt = np.arange(3)[None, :] != query[:, None]
    changes = swapped != original[:, None]
    pair_changes = np.stack([swapped[:, a] != swapped[:, b] for a, b in ((0, 1), (0, 2), (1, 2))], axis=1)
    target_changes = np.stack([query_labels[:, a] != query_labels[:, b] for a, b in ((0, 1), (0, 2), (1, 2))], axis=1)
    result = {
        "examples": len(original_label), "original_accuracy": measured_accuracy(original, original_label),
        "majority_original_accuracy": measured_accuracy(majority, original_label),
        "three_query_mean_accuracy": measured_accuracy(swapped, query_labels),
        "all_three_queries_correct_history_rate": float(np.mean(np.all(swapped == query_labels, axis=1))),
        "query_0_accuracy": measured_accuracy(swapped[:, 0], query_labels[:, 0]),
        "query_1_accuracy": measured_accuracy(swapped[:, 1], query_labels[:, 1]),
        "query_2_accuracy": measured_accuracy(swapped[:, 2], query_labels[:, 2]),
        "alternative_query_prediction_change_rate": float(np.mean(changes[alt])),
        "any_query_prediction_change_history_rate": float(np.mean(np.any(swapped != swapped[:, :1], axis=1))),
        "pairwise_query_prediction_change_rate": float(np.mean(pair_changes)),
        "pairwise_target_label_change_rate": float(np.mean(target_changes)),
        "prediction_change_when_target_changes": float(np.mean(pair_changes[target_changes])),
        "subgroups": {},
    }
    for name, mask in masks.items():
        result["subgroups"][name] = {
            "histories": int(mask.sum()),
            "original_accuracy": measured_accuracy(original, original_label, mask),
            "majority_original_accuracy": measured_accuracy(majority, original_label, mask),
            "three_query_mean_accuracy": measured_accuracy(swapped, query_labels, mask),
            "majority_three_query_accuracy": measured_accuracy(np.broadcast_to(majority[:, None], swapped.shape), query_labels, mask),
            "all_three_queries_correct_history_rate": float(np.mean(np.all(swapped[mask] == query_labels[mask], axis=1))) if np.any(mask) else None,
            "pairwise_prediction_change_rate": float(np.mean(pair_changes[mask])) if np.any(mask) else None,
        }
    return result


def summarize(records):
    groups = defaultdict(list)
    for record in records:
        groups[(record["family"], record["width"])].append(record)
    summaries = []
    keys = ("original_accuracy", "majority_original_accuracy", "three_query_mean_accuracy",
            "all_three_queries_correct_history_rate", "alternative_query_prediction_change_rate",
            "pairwise_query_prediction_change_rate", "distinct_original_accuracy",
            "distinct_three_query_accuracy", "distinct_all_three_correct_rate")
    for (family, width), items in groups.items():
        require(sorted(i["seed"] for i in items) == list(SEEDS), "missing seed in diagnostic summary")
        row = {"family": family, "width": width, "seeds": list(SEEDS)}
        for key in keys:
            values = np.array([i[key] for i in items], dtype=float)
            row[key] = {"mean": float(values.mean()), "min": float(values.min()), "max": float(values.max())}
        summaries.append(row)
    return summaries


def markdown(report):
    lines = ["# POSTHOC associative-recall query-binding audit", "", "**Posthoc diagnostic; no retraining or checkpoint selection.**", "",
             TRIGGER, "", "## Data and counterfactual contract", "",
             "This reuses the first 512 original IID test histories, generated with seed 1700000 in eight batches of 64. Each frozen model is checked against its saved original logits. The history, distractors, query marker and clock remain fixed; only the final query-key token is replaced by each of 0, 1 and 2. Labels are independently decoded from the unchanged history and are passed only to the evaluator.", "",
             "The three counterfactual queries are dependent observations sharing one history. This is not a new independent held-out dataset. Results are descriptive, with no p-value or confidence interval.", "",
             "## Query-ignorant majority reference", "",
             "With three IID values drawn uniformly from three classes, the 27 value triples contain 3 all-same, 18 two-same and 6 all-distinct cases. A fixed majority prediction is correct on 3, 2 and 1 of the three possible queries respectively. Therefore its population accuracy is (3×3 + 18×2 + 6×1)/(27×3) = 17/27 ≈ 62.963%. Ties are broken toward the smallest value. This reference uses history contents but ignores the query key.", "",
             f"Observed subgroup sizes in these fixed histories: {report['subgroup_counts']}.", "",
             "A query-invariant prediction has exactly 1/3 accuracy across the three queries of an all-distinct history, and cannot answer all three correctly. Prediction changes alone do not establish binding: correctness after the query change is necessary.", "",
             "## All frozen model results", "",
             "Numbers are percentages, shown as mean [seed minimum, seed maximum] over seeds 11/23/37. Three-query accuracy averages the three queries; all-three measures the fraction of histories on which every query is answered correctly. Change rate compares each of the two alternative queries with the original-query prediction.", "",
             "| Family | Width | Original accuracy | Three-query accuracy | All three correct | Alternative-query change | Distinct three-query accuracy | Distinct all three correct |",
             "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"]
    def show(x):
        return f"{100*x['mean']:.2f} [{100*x['min']:.2f}, {100*x['max']:.2f}]"
    for row in report["groups"]:
        metrics = ("original_accuracy", "three_query_mean_accuracy", "all_three_queries_correct_history_rate",
                   "alternative_query_prediction_change_rate", "distinct_three_query_accuracy", "distinct_all_three_correct_rate")
        lines.append("| " + row["family"] + " | " + str(row["width"]) + " | " + " | ".join(show(row[k]) for k in metrics) + " |")
    lines += ["", "## Reading this evidence", "",
              "A full-history advantage over last-observation-only can reflect retention of the bag of values. It does not by itself establish that the model associates each value with its key and responds to the requested key. This audit adds query-conditioned counterfactual correctness and the all-distinct subgroup to distinguish those possibilities.", "",
              "The diagnostic was motivated by already-observed model results and must remain labeled posthoc. It does not replace the original registered scores or retrospectively convert this task into a successful binding benchmark. Frozen sources and checkpoint files are unchanged; input hashes, original-score consistency, in-memory parameter hashes, predictions and logits are saved alongside the report.", ""]
    return "\n".join(lines)


def run_audit(base, out):
    records = frozen_models(base)
    batches, hashes, query, query_labels, majority, masks = shared_inputs()
    original_labels = np.concatenate([b["y"] for b in batches])
    for record in records:
        require(hashes == record["iid_metrics"]["batch_sha256"][:8], "original IID raw batch hashes differ")
    out.mkdir(parents=True, exist_ok=False)
    inputs = out / "shared_inputs.npz"
    np.savez_compressed(inputs, sequence=np.concatenate([b["x"] for b in batches], axis=1),
                        dt=np.concatenate([b["dt"] for b in batches], axis=1), original_labels=original_labels,
                        original_query=query, labels_by_query=query_labels, majority_predictions=majority,
                        **{name + "_mask": mask for name, mask in masks.items()})
    replacement_hashes = {str(q): [] for q in range(3)}
    for index, batch in enumerate(batches):
        for q in range(3):
            changed = batch["x"].copy()
            changed[-1] = 0
            changed[-1, :, q] = 1
            replacement_hashes[str(q)].append({"input_sha256": array_hash(changed, batch["dt"]),
                "labeled_batch_sha256": array_hash(changed, query_labels[index*64:(index+1)*64, q], batch["dt"], batch["ids"])})
    rows, raw_reports = [], []
    predictions_dir = out / "predictions"
    predictions_dir.mkdir()
    for record in records:
        run, family = record["run"], record["family"]
        model = Model.load(run / "final.npz") if family in ("ordinary", "analytic") else load_model(run / "final.npz")
        before = array_hash(*[model.params[key] for key in sorted(model.params)])
        originals, swaps = [], []
        for batch in batches:
            # The model API receives only raw observations and elapsed time.
            h, _ = model.forward(batch["x"], batch["dt"])
            originals.append(model.logits(h))
            answers = []
            for q in range(3):
                changed = batch["x"].copy()
                changed[-1] = 0
                changed[-1, :, q] = 1
                h, _ = model.forward(changed, batch["dt"])
                answers.append(model.logits(h))
            swaps.append(np.stack(answers, axis=1))
        original_logits, swap_logits = np.concatenate(originals), np.concatenate(swaps)
        with np.load(run / "evaluation_test/iid_predictions.npz", allow_pickle=False) as saved:
            require(np.array_equal(saved["labels"][:512], original_labels), "saved test labels differ")
            require(np.allclose(saved["logits"][:512], original_logits, rtol=1e-10, atol=1e-10),
                    "replayed original logits differ from frozen IID evidence")
            saved_error = float(np.max(np.abs(saved["logits"][:512] - original_logits)))
        require(np.allclose(swap_logits[np.arange(512), query], original_logits, rtol=1e-10, atol=1e-10),
                "unchanged-query counterfactual failed to reproduce original")
        after = array_hash(*[model.params[key] for key in sorted(model.params)])
        require(before == after and file_hash(run / "final.npz") == record["checkpoint_sha256"],
                "model parameters changed during diagnostic")
        original_prediction, swap_prediction = original_logits.argmax(axis=1), swap_logits.argmax(axis=2)
        result = model_metrics(original_prediction, swap_prediction, original_labels, query_labels, query, majority, masks)
        name = f"{family}_w{record['width']}_s{record['seed']}"
        payload = predictions_dir / (name + ".npz")
        np.savez_compressed(payload, original_logits=original_logits, original_predictions=original_prediction,
                            query_logits=swap_logits, query_predictions=swap_prediction, original_labels=original_labels,
                            labels_by_query=query_labels, original_query=query, majority_predictions=majority)
        result.update({"family": family, "width": record["width"], "seed": record["seed"],
                       "checkpoint_sha256": record["checkpoint_sha256"], "in_memory_parameter_sha256": before,
                       "parameters_unchanged": True, "saved_original_max_logit_error": saved_error,
                       "payload": str(payload.relative_to(out)), "payload_sha256": file_hash(payload)})
        raw_reports.append(result)
        row = {"family": family, "width": record["width"], "seed": record["seed"]}
        row.update({key: value for key, value in result.items() if key != "subgroups"})
        for subgroup, values in result["subgroups"].items():
            row.update({subgroup + "_" + key: value for key, value in values.items()})
        row.update({"distinct_original_accuracy": result["subgroups"]["all_distinct"]["original_accuracy"],
                    "distinct_three_query_accuracy": result["subgroups"]["all_distinct"]["three_query_mean_accuracy"],
                    "distinct_all_three_correct_rate": result["subgroups"]["all_distinct"]["all_three_queries_correct_history_rate"]})
        rows.append(row)
    report = {"status": "POSTHOC", "trigger": TRIGGER, "created_utc": datetime.now(timezone.utc).isoformat(),
              "source_sha256": file_hash(Path(__file__)), "models": 36, "histories_per_model": 512,
              "query_counterfactuals_per_history": 3, "independent_new_test_set": False,
              "model_training_or_selection": False, "generation_seed": 1700000, "generation_batch_size": 64,
              "original_raw_batch_sha256": hashes, "replacement_hashes": replacement_hashes,
              "shared_inputs_sha256": file_hash(inputs), "majority_population_accuracy": 17/27,
              "majority_original_accuracy": measured_accuracy(majority, original_labels),
              "majority_three_query_accuracy": measured_accuracy(np.broadcast_to(majority[:, None], query_labels.shape), query_labels),
              "subgroup_counts": {key: int(mask.sum()) for key, mask in masks.items()},
              "groups": summarize(rows), "model_reports": raw_reports,
              "remote_freeze_proof": "existing owner orchestration receipts; this script independently checks local file identities"}
    with (out / "per_model.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    write_json(out / "summary.json", report)
    (out / "RECALL_BINDING_POSTHOC.md").write_text(markdown(report))
    return {"output": str(out), "models": 36, "histories": 512, "status": "POSTHOC"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    base = args.base.resolve()
    out = base / "analysis/recall_binding_posthoc" if args.out is None else args.out.resolve()
    require(not out.exists(), "posthoc output already exists; preserve prior evidence and select a new --out")
    print(json.dumps(run_audit(base, out)))


if __name__ == "__main__":
    main()
