"""Independent NumPy/stdlib arithmetic audit; never imports an author evaluator."""
import argparse
from collections import Counter, defaultdict
import hashlib
import itertools
import json
import os
from pathlib import Path
import subprocess

import numpy as np

ROOT = Path(__file__).resolve().parents[4]
BASE = Path("experiments/hcsn_v13_followup_20261102")
EVAL = BASE / "joint_core/results/content_evaluation002"
TRAIN = BASE / "joint_core/results/run001"
METRICS = ("all_prefix_accuracy", "final_prefix_accuracy", "all_prefix_nll", "final_prefix_nll")
SEEDS = (13301, 13303, 13307)
TASKS = ("async_av", "av_binding")
FAMILIES = ("hx_full", "hx_margin", "ordinary_gate", "gru", "ssm", "history")
CELLS = {"A": ("hx_full", "hx_full"), "B": ("hx_full", "hx_margin"),
         "C": ("hx_margin", "hx_full"), "D": ("hx_margin", "hx_margin")}


def read(path):
    return json.loads(path.read_text())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git(*args):
    return subprocess.check_output(["git", *args], text=True).strip()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    os.chdir(ROOT)
    args.out.mkdir(exist_ok=False)
    failures, checks, errors = [], Counter(), defaultdict(float)

    def check(ok, category, detail):
        checks[category] += 1
        if not bool(ok):
            failures.append({"category": category, "detail": detail})

    def close(actual, expected, category, detail, tolerance=5e-12):
        actual, expected = np.asarray(actual), np.asarray(expected)
        delta = float(np.max(np.abs(actual - expected))) if actual.size else 0.0
        errors[category] = max(errors[category], delta)
        check(actual.shape == expected.shape and np.all(np.isfinite(actual)) and delta <= tolerance,
              category, dict(location=detail, max_abs_error=delta, tolerance=tolerance))

    result, start, author_agg = [read(EVAL / name) for name in ("RESULT.json", "START.json", "AGGREGATES.json")]
    candidates, plan = read(TRAIN / "CANDIDATES.json"), read(TRAIN / "PLAN.json")
    gate = start["publication_gate"]
    dependency_path = BASE / "publication/DEPENDENCY_PUBLICATION.json"
    dependency = read(dependency_path)
    check(sha(dependency_path) == gate["publication_receipt_sha256"], "publication", "receipt SHA256")
    check(start["candidate_remote_head"] == gate["remote_head"] == dependency["remote_head"] ==
          "f810ee199755d139f5b8c08187efc41cbd7839c9", "publication", "candidate remote identity")
    check(start["source_remote_head"] == gate["source_remote_head"] == dependency["source_remote_head"] ==
          "4c2fa0d86b9b09d5b26849b4738458fabc7b2945", "publication", "source remote identity")
    check(gate["local_head"] == dependency["local_head"], "publication", "recorded local mapping")
    check(git("rev-parse", gate["local_head"] + "^{tree}") == dependency["new_dependency_stage"]["tree"],
          "publication", "mapped candidate local root tree")
    check(sha(TRAIN / "CANDIDATES.json") == start["candidate_manifest_sha256"] == gate["candidate_manifest_sha256"],
          "publication", "candidate manifest linkage")
    check(start["protocol"] == read(BASE / "joint_core/operations/EVALUATION_PROTOCOL.json"),
          "publication", "protocol exact semantic identity")
    for path, key in ((BASE / "joint_core/operations/evaluate_content.py", "evaluation_source_sha256"),
                      (BASE / "joint_core/operations/EVALUATION_PROTOCOL.json", "evaluation_protocol_sha256")):
        check(sha(path) == start[key], "publication", str(path))
    provenance = []
    gate_paths = {item["path"] for item in gate["checked_files"]}
    for item in gate["checked_files"]:
        path = Path(item["path"])
        actual_sha = sha(path)
        blob = git("hash-object", "--no-filters", str(path))
        frozen_blob = git("rev-parse", gate["local_head"] + ":" + str(path))
        check(actual_sha == item["sha256"] and blob == item["git_blob"] == frozen_blob,
              "publication_blobs", str(path))
        provenance.append(dict(path=str(path), sha256=actual_sha, git_blob=blob, frozen_git_blob=frozen_blob))
    source_mapping = next(item for item in dependency["initial_source_commit_mapping"]
                          if item["remote_commit"] == start["source_remote_head"])
    check(git("rev-parse", source_mapping["local_commit"] + "^{tree}") == source_mapping["tree"],
          "publication", "mapped original source local tree")
    original_source_present, original_source_absent = [], []
    for path, expected_sha in plan["source_sha256"].items():
        check(path in gate_paths and sha(Path(path)) == expected_sha, "plan_source", path)
        original = subprocess.run(["git", "show", source_mapping["local_commit"] + ":" + path], capture_output=True)
        if original.returncode == 0:
            original_source_present.append(path)
            check(hashlib.sha256(original.stdout).hexdigest() == expected_sha, "plan_source", "original source blob " + path)
        else:
            original_source_absent.append(dict(path=path, original_git_error=original.stderr.decode().strip(),
                                              candidate_dependency_blob=git("rev-parse", gate["local_head"] + ":" + path)))
            check(path == "recovered/v3/experiments/hcsn_free_boundary_v1/datasets.py", "known_dependency_repair", path)
    candidate_index = {(x["task"], x["family"], x["seed"]): x for x in candidates["models"]}
    expected_candidates = set(itertools.product(TASKS, FAMILIES, SEEDS))
    check(len(candidate_index) == len(candidates["models"]) == 36 and set(candidate_index) == expected_candidates,
          "candidate_coverage", "all 36 fixed final checkpoints")
    for key, item in candidate_index.items():
        directory = TRAIN / item["directory"]
        for filename, digest_key in (("weights.pt", "weights_sha256"), ("TRAIN.json", "train_metadata_sha256")):
            check(str(directory / filename) in gate_paths and sha(directory / filename) == item[digest_key],
                  "candidate_bytes", dict(candidate=key, filename=filename))

    expected_keys = set()
    for task, split, family, seed in itertools.product(TASKS, ("val", "test"), FAMILIES, SEEDS):
        modes = ("hx_full", "hx_margin") if family.startswith("hx_") else (family,)
        expected_keys.update((task, split, family, seed, mode) for mode in modes)
    rows = result["rows"]
    keys = [(r["task"], r["split"], r["training_family"], r["seed"], r["execution_mode"]) for r in rows]
    check(len(rows) == result["condition_records"] == 96 and len(set(keys)) == 96 and set(keys) == expected_keys,
          "condition_coverage", "96 exact unique conditions")
    check({p.name for p in EVAL.glob("*.npz")} == {r["raw_file"] for r in rows},
          "condition_coverage", "96 raw files, none omitted or additional")
    objects, dependency_counts, object_rows, independent_rows, raw_inventory = {}, [], [], [], []
    input_reference = {}
    for task, split in itertools.product(TASKS, ("val", "test")):
        metadata = read(EVAL / f"{task}-{split}-OBJECTS.json")
        entries = metadata["objects"]
        identity = result["input_identities"][task + "/" + split]
        nobjects = 12 if task == "async_av" else 24
        check([x["index"] for x in entries] == list(range(nobjects)) and
              [x["source_id"] for x in entries] == identity["ids"] and
              identity["objects"] == nobjects and identity["sequences"] == 10 * nobjects and
              metadata["dependent_orders_per_object"] == 10,
              "object_provenance", task + "/" + split)
        sources = Counter()
        for entry in entries:
            ids = [part.split(":", 1)[-1] for part in entry["source_id"].split("|")]
            sources.update(set(ids))
            check(sorted({x.split("_", 1)[0] for x in ids}) == sorted(entry["actor_ids"]),
                  "object_provenance", entry["source_id"])
        check(len(sources) == 12 and bool(max(sources.values()) > 1) == (task == "av_binding"),
              "dependent_units", task + "/" + split)
        objects[(task, split)] = entries
        dependency_counts.append(dict(task=task, split=split, objects=nobjects, dependent_orders=10,
                                      unique_underlying_recordings=len(sources),
                                      max_objects_sharing_a_recording=max(sources.values()),
                                      actors=sorted({a for x in entries for a in x["actor_ids"]})))
    required_arrays = {"logits", "probabilities", "labels", "predictions", "object_index", "accepted_order", "reset", "restored"}
    valid_orders = {tuple("audio" if i in (0, *positions) else "video" for i in range(6))
                    for positions in itertools.combinations(range(1, 6), 2)}
    for row, key in zip(rows, keys):
        task, split, family, seed, mode = key
        path = EVAL / row["raw_file"]
        check(sha(path) == row["raw_sha256"], "raw_sha256", path.name)
        candidate = candidate_index[(task, family, seed)]
        check(row["weights_sha256"] == candidate["weights_sha256"], "row_weights", path.name)
        with np.load(path, allow_pickle=False) as archive:
            check(set(archive.files) == required_arrays, "raw_schema", path.name)
            raw = {name: archive[name] for name in required_arrays}
        logits, labels, indices = raw["logits"], raw["labels"], raw["object_index"]
        nobjects = len(objects[(task, split)])
        classes = 6 if task == "async_av" else 2
        check(logits.shape == (nobjects * 10, 6, classes) and labels.shape == (nobjects * 10, 6) and
              indices.shape == (nobjects * 10,) and raw["reset"].shape == raw["restored"].shape == (nobjects * 10, 6, 8) and
              raw["accepted_order"].shape == (nobjects * 10, 6) and raw["reset"].dtype == raw["restored"].dtype == bool and
              np.all(np.isfinite(logits)) and labels.dtype.kind in "iu" and np.all((labels >= 0) & (labels < classes)),
              "raw_schema", path.name)
        signature = {name: hashlib.sha256(np.ascontiguousarray(raw[name]).tobytes()).hexdigest()
                     for name in ("labels", "object_index", "accepted_order")}
        if (task, split) in input_reference:
            check(signature == input_reference[(task, split)], "paired_inputs", path.name)
        else:
            input_reference[(task, split)] = signature
        check(set(indices.tolist()) == set(range(nobjects)), "object_orders", path.name)
        shifted = logits - logits.max(axis=-1, keepdims=True)
        exponentials = np.exp(shifted)
        normalizer = exponentials.sum(axis=-1, keepdims=True)
        probabilities = exponentials / normalizer
        nll = np.log(normalizer[..., 0]) - np.take_along_axis(shifted, labels[..., None], axis=-1)[..., 0]
        predictions = logits.argmax(axis=-1)
        correct = predictions == labels
        close(probabilities, raw["probabilities"], "probability_error", path.name, 2e-14)
        check(np.array_equal(predictions, raw["predictions"]), "predictions", path.name)
        metrics = dict(zip(METRICS, map(float, (correct.mean(), correct[:, -1].mean(), nll.mean(), nll[:, -1].mean()))))
        for metric in METRICS:
            close(metrics[metric], row[metric], "row_metric_error", path.name + "/" + metric)
        close(correct.mean(axis=0), row["prefix_accuracy"], "prefix_metric_error", path.name)
        close(nll.mean(axis=0), row["prefix_nll"], "prefix_metric_error", path.name)
        check(int(raw["reset"].sum()) == row["reset_cell_events"] and
              int(raw["restored"].sum()) == row["restoration_cell_events"] and
              row["recording_or_pair_objects"] == nobjects and row["dependent_sequences"] == nobjects * 10,
              "row_counts", path.name)
        author_objects = read(path.with_name(path.stem + "-OBJECT_METRICS.json"))
        check([x["object_index"] for x in author_objects] == list(range(nobjects)), "object_metrics", path.name)
        current_objects = []
        for index in range(nobjects):
            selected = indices == index
            check(int(selected.sum()) == 10 and set(map(tuple, raw["accepted_order"][selected].tolist())) == valid_orders and
                  len(set(labels[selected].reshape(-1).tolist())) == 1, "object_orders", dict(raw=path.name, object=index))
            values = dict(zip(METRICS, map(float, (correct[selected].mean(), correct[selected, -1].mean(),
                                                 nll[selected].mean(), nll[selected, -1].mean()))))
            for metric in METRICS:
                close(values[metric], author_objects[index][metric], "object_metric_error", f"{path.name}/{index}/{metric}")
            current_objects.append(values)
            object_rows.append(dict(task=task, split=split, training_family=family, seed=seed, execution_mode=mode,
                                    object_index=index, source_id=objects[(task, split)][index]["source_id"], **values))
        for metric in METRICS:
            close(np.mean([x[metric] for x in current_objects]), metrics[metric], "object_mean_error", path.name)
        independent_rows.append(dict(task=task, split=split, training_family=family, seed=seed, execution_mode=mode,
                                     **metrics, reset_cell_events=int(raw["reset"].sum()), restoration_cell_events=int(raw["restored"].sum())))
        raw_inventory.append(dict(raw_file=path.name, raw_sha256=sha(path), weights_sha256=candidate["weights_sha256"],
                                  shape=list(logits.shape), paired_input_array_sha256=signature,
                                  min_probability=float(probabilities.min())))
    by_key = {k: value for k, value in zip(keys, independent_rows)}
    contrasts = []
    coefficients = {"A-B": {"A": 1, "B": -1}, "C-D": {"C": 1, "D": -1},
                    "A-C": {"A": 1, "C": -1}, "B-D": {"B": 1, "D": -1},
                    "(A-B)-(C-D)": {"A": 1, "B": -1, "C": -1, "D": 1}}
    for task, split, seed in itertools.product(TASKS, ("val", "test"), SEEDS):
        cells = {name: by_key[(task, split, family, seed, mode)] for name, (family, mode) in CELLS.items()}
        values = {name: {metric: sum(weight * cells[cell][metric] for cell, weight in weights.items()) for metric in METRICS}
                  for name, weights in coefficients.items()}
        for ordinary in ("hx_margin", "ordinary_gate", "gru", "ssm", "history"):
            other = by_key[(task, split, ordinary, seed, ordinary)]
            values["A-versus-" + ordinary] = {metric: cells["A"][metric] - other[metric] for metric in METRICS}
        previous = next(x for x in result["contrasts"] if (x["task"], x["split"], x["seed"]) == (task, split, seed))
        check(set(previous["descriptive_only"]) == set(values), "contrast_coverage", [task, split, seed])
        for name, vals in values.items():
            for metric in METRICS:
                close(vals[metric], previous["descriptive_only"][name][metric], "contrast_error", [task, split, seed, name, metric])
        contrasts.append(dict(task=task, split=split, seed=seed, descriptive_only=values))
    aggregates = []
    for task, split, family, mode in sorted({(k[0], k[1], k[2], k[4]) for k in keys}):
        vals = {metric: float(np.mean([by_key[(task, split, family, seed, mode)][metric] for seed in SEEDS])) for metric in METRICS}
        previous = next(x for x in author_agg["aggregates"] if (x["task"], x["split"], x["training_family"], x["execution_mode"]) ==
                        (task, split, family, mode))
        check(previous["fixed_seeds"] == list(SEEDS), "aggregate_seeds", [task, split, family, mode])
        for metric in METRICS:
            close(vals[metric], previous[metric], "aggregate_error", [task, split, family, mode, metric])
        aggregates.append(dict(task=task, split=split, training_family=family, execution_mode=mode, fixed_seeds=list(SEEDS), **vals))
    contrast_means = []
    for task, split in itertools.product(TASKS, ("val", "test")):
        selected = [x["descriptive_only"] for x in contrasts if (x["task"], x["split"]) == (task, split)]
        values = {name: {metric: float(np.mean([x[name][metric] for x in selected])) for metric in METRICS} for name in selected[0]}
        previous = next(x for x in author_agg["contrasts"] if (x["task"], x["split"]) == (task, split))
        check(set(previous["fixed_seed_mean_contrasts"]) == set(values), "contrast_coverage", [task, split])
        for name, vals in values.items():
            for metric in METRICS:
                close(vals[metric], previous["fixed_seed_mean_contrasts"][name][metric], "aggregate_contrast_error", [task, split, name, metric])
        contrast_means.append(dict(task=task, split=split, fixed_seed_mean_contrasts=values))
    check(len(aggregates) == len(author_agg["aggregates"]) == 32 and len(contrast_means) == len(author_agg["contrasts"]) == 4 and
          len(contrasts) == len(result["contrasts"]) == 12, "aggregate_coverage", "32 aggregate cells, 12 seed contrast sets, 4 mean sets")
    for name, value in (("protocol_quality_acceptance", start["protocol"]["quality_acceptance"]),
                        ("result_quality_admission_passed", result["quality_admission_passed"]),
                        ("result_all_blockers_closed", result["all_blockers_closed"]),
                        ("result_production_activation", result["production_activation"]),
                        ("aggregate_all_blockers_closed", author_agg["all_blockers_closed"])):
        check(value is False, "scientific_gates", name)
    report = dict(schema="hcsn-v13-independent-content96-review.v1", audit_pass=not failures,
                  checks=dict(checks), failures=failures, maximum_absolute_errors=dict(errors),
                  metric_formula="NLL=log(sum(exp(z-max(z))))-(z_label-max(z)); accuracy=argmax(logits)==label; final=prefix 6; all=equal sequence-prefix mean",
                  numeric_absolute_tolerance=5e-12, probability_absolute_tolerance=2e-14,
                  no_author_evaluator_imported=True, no_model_selection=True, no_confidence_intervals=True,
                  no_additional_source_data_opened=True, condition_records=len(independent_rows),
                  candidate_count=len(candidate_index), object_metric_records=len(object_rows),
                  source_remote_head=start["source_remote_head"], candidate_remote_head=start["candidate_remote_head"],
                  publication_local_head=gate["local_head"], external_remote_verification="Performed by root; this audit checks recorded local Git blobs and published mapping only, without network",
                  original_source_present=original_source_present, original_source_absent_then_dependency_published=original_source_absent,
                  metadata_sha256={str(path): sha(path) for path in (EVAL / "START.json", EVAL / "RESULT.json", EVAL / "AGGREGATES.json", TRAIN / "CANDIDATES.json", TRAIN / "PLAN.json", dependency_path)},
                  dependency_counts=dependency_counts, raw_inventory=raw_inventory, provenance=provenance,
                  quality_acceptance=False, all_blockers_closed=False, production_activation=False)
    for filename, value in (("AUDIT.json", report), ("ROWS.json", independent_rows), ("OBJECT_METRICS.json", object_rows),
                            ("AGGREGATES.json", aggregates), ("CONTRASTS.json", contrasts), ("MEAN_CONTRASTS.json", contrast_means)):
        (args.out / filename).write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")
    print(json.dumps({k: report[k] for k in ("audit_pass", "condition_records", "candidate_count", "object_metric_records", "maximum_absolute_errors", "failures")}))
    return int(bool(failures))


if __name__ == "__main__":
    raise SystemExit(main())
