"""Independent acceptance accounting for a completed frozen retention study.

Run only after the original confirmation SUMMARY exists. This does not train,
select checkpoints, evaluate a model, or change the frozen scientific source.
It regenerates the registered inputs to check their hashes and query identity.
Quality and numerical subdivision are separate gates. The full-time error is
an original-evaluation measurement; only query-time logits were archived and
can be independently recomputed here without another model evaluation.
"""

import argparse
import hashlib
import json
from pathlib import Path
import time

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
TASKS = ("mqar", "selective", "binding")
CORES = ("flow", "diagonal")
SEEDS = (17, 29, 43)
CONDITIONS = ("base", "irregular", "missing", "long_delay", "resample",
              "long_tokens_64", "long_tokens_128", "matched_silence_64",
              "matched_silence_128", "query_swap")


def require(value, message):
    if not value:
        raise ValueError(message)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


def array_hash(value):
    return hashlib.sha256(np.ascontiguousarray(value).tobytes()).hexdigest()


def review(run, protocol_sha256, candidate_sha256, source_commit):
    started, cpu = time.perf_counter(), time.process_time()
    run = Path(run).resolve()
    confirmation = run / "confirmation"
    require((confirmation / "SUMMARY.json").is_file(), "Completed confirmation required; no inputs opened")
    inputs = {}

    def bind(path, expected=None):
        path = Path(path).resolve()
        actual = digest(path)
        if expected is not None:
            require(actual == expected, "Hash mismatch: " + str(path))
        inputs[str(path)] = actual
        return actual

    bind(run / "PROTOCOL.json", protocol_sha256)
    bind(run / "ALL_CHECKPOINTS.json", candidate_sha256)
    bind(run / "TRAINING_SOURCE.json")
    bind(confirmation / "SUMMARY.json")
    protocol, candidate = read(run / "PROTOCOL.json"), read(run / "ALL_CHECKPOINTS.json")
    training, summary = read(run / "TRAINING_SOURCE.json"), read(confirmation / "SUMMARY.json")
    require(protocol["tasks"] == list(TASKS) and protocol["cores"] == list(CORES)
            and protocol["seeds"] == list(SEEDS) and protocol["conditions"] == list(CONDITIONS),
            "Registered task/core/seed/condition set changed")
    require(protocol["gates"]["required_conditions"] == [c for c in CONDITIONS if c != "missing"]
            and protocol["gates"]["all4"] == .95 and protocol["gates"]["resampling"] == 1e-4,
            "Registered independent gates changed")
    require(protocol["confirmation_seed"] == 73117 and protocol["confirmation_episodes"] == 1024
            and protocol["steps"] == 600, "Confirmation or training budget changed")
    for path, expected in protocol["source_hashes"].items():
        bind(ROOT / path, expected)
        bind(run / "sources" / path, expected)
    require(training == {"source_commit": source_commit, "protocol_sha256": protocol_sha256},
            "Training source identity differs from externally supplied freeze")
    require(candidate["source_commit"] == source_commit and candidate["protocol_sha256"] == protocol_sha256
            and candidate["failed"] == 0 and candidate["source_unchanged"] is True
            and candidate["protocol_unchanged"] is True, "Training candidate did not complete unchanged")
    require(summary["candidate_freeze_sha256"] == candidate_sha256 and summary["source_commit"] == source_commit
            and summary["source_hashes"] == protocol["source_hashes"] and summary["source_unchanged"] is True,
            "Confirmation source or candidate mismatch")
    expected_fits = {(task, core, seed) for task in TASKS for core in CORES for seed in SEEDS}
    fit_key = lambda row: (row["task"], row["core"], row["seed"])
    require(len(candidate["fits"]) == 18 and {fit_key(r) for r in candidate["fits"]} == expected_fits,
            "Missing or duplicate training fits")
    fits = {fit_key(row): row for row in candidate["fits"]}
    for key, row in fits.items():
        require(row["status"] == "completed" and row["steps"] == protocol["steps"], "Incomplete fit: " + str(key))
        bind(run / row["checkpoint"], row["checkpoint_sha256"])
        fit_record = (run / row["checkpoint"]).with_name("FIT.json")
        bind(fit_record)
        require(read(fit_record) == row, "Candidate and on-disk fit record differ: " + str(key))
    for task in TASKS:
        for seed in SEEDS:
            require(len({fits[task, core, seed]["input_stream_sha256"] for core in CORES}) == 1,
                    "Unmatched training inputs: " + str((task, seed)))

    expected_rows = {(*key, condition) for key in expected_fits for condition in CONDITIONS}
    row_key = lambda row: (*fit_key(row), row["condition"])
    require(len(summary["records"]) == 180 and {row_key(r) for r in summary["records"]} == expected_rows,
            "Missing or duplicate confirmation records")
    rows = {row_key(row): row for row in summary["records"]}

    # Import only after exact frozen source identity and completed-run checks.
    from . import data

    raw, recomputed, generated = {}, [], {}
    n = protocol["confirmation_episodes"]
    for task in TASKS:
        for condition in CONDITIONS:
            arrays = data.batch(task, n, protocol["confirmation_seed"], "confirm", condition)
            hashes = {key: array_hash(value) for key, value in arrays.items()}
            generated[task + "/" + condition] = hashes
            mask = arrays["y"] >= 0
            require(np.all(mask.sum(-1) == 4), "Exactly four queries required")
            require(np.array_equal(arrays["sample_weight"], mask.astype(np.float32)),
                    "Registered score weights differ from four equally weighted queries")
            episode_id, position = np.where(mask)
            available = arrays["target_available"][mask].reshape(n, 4)
            for core in CORES:
                for seed in SEEDS:
                    key = (task, core, seed, condition)
                    row = rows[key]
                    require(row["data_sha256"] == hashes, "Input identity mismatch: " + str(key))
                    require(row["checkpoint_sha256"] == fits[key[:3]]["checkpoint_sha256"],
                            "Result uses different model weights: " + str(key))
                    path = confirmation / row["raw_file"]
                    bind(path, row["raw_sha256"])
                    bind(path.with_suffix(".json"))
                    require(read(path.with_suffix(".json")) == row, "Summary/raw-sidecar mismatch: " + str(key))
                    with np.load(path, allow_pickle=False) as archive:
                        result = {name: archive[name] for name in archive.files}
                    require(result["logits"].shape == (n * 4, 8) and np.isfinite(result["logits"]).all(),
                            "Invalid raw logits: " + str(key))
                    for name, value in (("target", arrays["y"][mask]), ("episode_id", episode_id),
                                        ("query_position", position), ("available", available),
                                        ("prediction", result["logits"].argmax(-1))):
                        require(np.array_equal(result[name], value), "Raw " + name + " mismatch: " + str(key))
                    correct = (result["prediction"] == result["target"]).reshape(n, 4)
                    measured = dict(accuracy=float(correct.mean()), all4=float(correct.all(-1).mean()),
                        available_accuracy=float(correct[available].mean()) if available.any() else None,
                        unavailable_accuracy=float(correct[~available].mean()) if (~available).any() else None)
                    for name, value in measured.items():
                        require(row[name] == value, "Raw metric mismatch " + name + ": " + str(key))
                    recomputed.append(dict(task=task, core=core, seed=seed, condition=condition, **measured))
                    if condition in ("base", "resample"):
                        raw[key] = result

    quality, resampling, resampling_rows = {}, {}, []
    for core in CORES:
        selected = [row for row in recomputed if row["core"] == core and row["condition"] != "missing"]
        require(len(selected) == 81, "Incomplete nine-condition gate")
        quality[core] = dict(passed=all(row["all4"] >= .95 for row in selected), records=len(selected),
            minimum_all4=min(row["all4"] for row in selected),
            failures=[row for row in selected if row["all4"] < .95])
        checks = []
        for task in TASKS:
            for seed in SEEDS:
                base, refined = raw[task, core, seed, "base"], raw[task, core, seed, "resample"]
                require(np.array_equal(base["target"], refined["target"])
                        and np.array_equal(base["episode_id"], refined["episode_id"])
                        and np.array_equal(2 * base["query_position"] + 1, refined["query_position"]),
                        "Subdivision altered query identities")
                measured = float(np.max(np.abs(base["logits"] - refined["logits"])))
                recorded = rows[task, core, seed, "resample"]["resampling_error"]
                require(np.isfinite(recorded) and recorded >= 0 and measured <= recorded + 1e-7,
                        "Query error exceeds recorded full-time error")
                entry = dict(task=task, core=core, seed=seed, query_max_abs_error=measured,
                    recorded_full_time_max_abs_error=recorded, passed=recorded <= 1e-4 and measured <= 1e-4)
                checks.append(entry)
                resampling_rows.append(entry)
        resampling[core] = dict(passed=all(row["passed"] for row in checks), records=len(checks),
            maximum_recorded_full_time_error=max(row["recorded_full_time_max_abs_error"] for row in checks),
            maximum_recomputed_query_error=max(row["query_max_abs_error"] for row in checks))
        require(summary["retention_gates"][core] == quality[core]["passed"],
                "Original quality gate differs from independent all-rows calculation")
    for path, expected in inputs.items():
        require(digest(path) == expected, "Evidence changed during review: " + path)
    return dict(schema="hcsn.retention.independent_acceptance.v1", integrity_passed=True,
        protocol_sha256=protocol_sha256, candidate_freeze_sha256=candidate_sha256, source_commit=source_commit,
        reviewer_source_sha256=digest(__file__), inputs=inputs, regenerated_input_hashes=generated,
        fits_verified=18, records_verified=180, equal_query_weights_verified=True,
        quality_gates_by_core=quality, resampling_gates_by_core=resampling,
        combined_gate_by_core={core: quality[core]["passed"] and resampling[core]["passed"] for core in CORES},
        raw_recomputed_records=recomputed, resampling_records=resampling_rows,
        scope="Frozen-source and raw-result audit; no model evaluation or training; no CI recomputation",
        limitations=["Full-time subdivision errors are measured by the original frozen evaluator; query-only archives independently verify the query component",
                     "The 95% quality gate is an empirical all-four fraction, not a lower confidence bound",
                     "Passing task and numerical gates does not establish an analytical increment, energy efficiency or adoption",
                     "Only three training seeds; all-success bootstrap intervals do not establish population certainty"],
        cpu_seconds=time.process_time()-cpu, wall_seconds=time.perf_counter()-started)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--protocol-sha256", required=True)
    parser.add_argument("--candidate-freeze-sha256", required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    require(not args.out.exists(), "Review output already exists")
    result = review(args.run, args.protocol_sha256, args.candidate_freeze_sha256, args.source_commit)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("x") as stream:
        json.dump(result, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
    print(json.dumps({key: result[key] for key in ("integrity_passed", "fits_verified", "records_verified",
        "quality_gates_by_core", "resampling_gates_by_core", "combined_gate_by_core")}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
