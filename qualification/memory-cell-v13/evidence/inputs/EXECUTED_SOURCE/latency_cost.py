"""Warm CPU request profiling with real per-query encoding and skill execution.

This measures one local resident process, not all-system cost or a hardware
generalization result. The full authored holdout is used only after the model
is fixed. Three repeated timings of a request are not independent task samples.
"""

import argparse
import csv
import hashlib
import json
from pathlib import Path
import platform
import time

import numpy as np

from adapter import Adapter
from backend import FrozenEncoder
from baselines import BM25, Centroid, ExactStore, NearestExample, ProfileExactStore
from experiment import RidgeClassifier
import tasks


ENCODED_METHODS = ("nearest", "centroid", "ridge", "single_adapter")


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def tree_bytes(path):
    path = Path(path)
    if not path.exists():
        return None
    return sum(file.stat().st_size for file in path.rglob("*") if file.is_file() and not file.is_symlink())


def serialize_index(model):
    """Explicit logical array/metadata size; this is not a Python RSS estimate."""
    metadata, numeric = {}, 0
    for name, value in vars(model).items():
        if isinstance(value, np.ndarray):
            numeric += value.nbytes
            metadata[name] = dict(shape=list(value.shape), dtype=str(value.dtype))
        else:
            metadata[name] = value
    return dict(numeric_array_bytes=numeric, canonical_metadata_bytes=len(tasks.canonical(metadata)))


def timed_request(name, model, encoder, row):
    beginning_wall, beginning_cpu = time.perf_counter_ns(), time.process_time_ns()
    public = tasks.public_input(row)
    encode_wall = encode_cpu = input_tokens = encoded_tokens = truncated = 0
    if name in ENCODED_METHODS:
        before_stats = dict(encoder.stats)
        wall, cpu = time.perf_counter_ns(), time.process_time_ns()
        feature = encoder.encode([public["text"]])
        encode_wall, encode_cpu = time.perf_counter_ns() - wall, time.process_time_ns() - cpu
        input_tokens = encoder.stats["input_tokens"] - before_stats["input_tokens"]
        encoded_tokens = encoder.stats["encoded_tokens"] - before_stats["encoded_tokens"]
        truncated = encoder.stats["truncated_examples"] - before_stats["truncated_examples"]
    wall, cpu = time.perf_counter_ns(), time.process_time_ns()
    if name == "single_adapter":
        probabilities = model.predict_proba(feature)[0]
        label = int(probabilities.argmax())
        score = float(probabilities[label])
    elif name == "ridge":
        label, score = int(model.predict(feature)[0]), None
    elif name in ("nearest", "centroid"):
        label, score = model.predict(feature[0])
    else:
        label, score = model.predict(public["text"])
    select_wall, select_cpu = time.perf_counter_ns() - wall, time.process_time_ns() - cpu
    wall, cpu = time.perf_counter_ns(), time.process_time_ns()
    output, error = None, None
    if label is None:
        error = "unsupported_exact_address"
    else:
        try:
            output = tasks.execute(int(label), public["payload"])
            tasks.canonical(output)
        except (ValueError, TypeError, ArithmeticError, csv.Error, OverflowError) as exception:
            error = type(exception).__name__
    execute_wall, execute_cpu = time.perf_counter_ns() - wall, time.process_time_ns() - cpu
    total_wall, total_cpu = time.perf_counter_ns() - beginning_wall, time.process_time_ns() - beginning_cpu
    correct = error is None and tasks.canonical(output) == tasks.canonical(row["expected"])
    return dict(id=row["id"], method=name, prediction=label, score=score,
                error=error, correct=correct, label_correct=label == row["label"],
                encoder_calls=int(name in ENCODED_METHODS),
                input_tokens=input_tokens, encoded_tokens=encoded_tokens,
                truncated_examples=truncated,
                encode_wall_ns=encode_wall, encode_cpu_ns=encode_cpu,
                select_wall_ns=select_wall, select_cpu_ns=select_cpu,
                execute_wall_ns=execute_wall, execute_cpu_ns=execute_cpu,
                total_wall_ns=total_wall, total_cpu_ns=total_cpu)


def summarize(records):
    summaries = {}
    for name in sorted({record["method"] for record in records}):
        group = [record for record in records if record["method"] == name]
        measurements = {}
        for stage in ("encode", "select", "execute", "total"):
            for clock in ("wall", "cpu"):
                values = np.asarray([row[f"{stage}_{clock}_ns"] for row in group]) / 1e6
                measurements[f"{stage}_{clock}_ms"] = dict(p50=float(np.quantile(values, 0.5)), p95=float(np.quantile(values, 0.95)), mean=float(values.mean()), minimum=float(values.min()), maximum=float(values.max()))
        first = {row["id"]: row for row in reversed(group)}
        prediction_sets = {identity: {row["prediction"] for row in group if row["id"] == identity} for identity in first}
        summaries[name] = dict(timing_trials=len(group), distinct_requests=len(first),
                               unique_correct=sum(row["correct"] for row in first.values()),
                               unique_accepted=sum(row["prediction"] is not None for row in first.values()),
                               inconsistent_request_predictions=sum(len(values) != 1 for values in prediction_sets.values()),
                               encoder_calls=sum(row["encoder_calls"] for row in group),
                               input_tokens=sum(row["input_tokens"] for row in group),
                               measurements=measurements)
    return summaries


def storage_ledger(model_dir, inputs, results, adapter, baselines):
    state = adapter.state_dict()
    params = sum(value.nbytes for value in state.pop("params").values())
    adam = sum(value.nbytes for group in ("m", "v") for value in state.pop(group).values())
    order = state["sampler"].pop("order")
    own_profile = len(tasks.canonical(state))
    source_files = {file.name: file.stat().st_size for file in sorted(inputs.glob("*_rows.json"))}
    profile_files = {name: size for name, size in source_files.items() if name.startswith("profile-")}
    weights = model_dir / "onnx/model.onnx"
    runtime = model_dir.parent / "site-packages"
    checkpoints = {str(file.relative_to(results)): file.stat().st_size for file in sorted(results.rglob("*.npz"))}
    return dict(
        units="bytes; physical files and logical arrays are separate, non-additive views",
        shared_encoder=dict(weights_file=weights.stat().st_size, assets_and_manifest=tree_bytes(model_dir) - weights.stat().st_size,
                            weights_sha256=sha(weights), amortization="one resident shared encoder; never duplicate-counted as independent per-cell models"),
        dedicated_runtime=dict(directory=str(runtime), bytes=tree_bytes(runtime), attribution="whole dedicated pinned dependency directory including dependencies; not peak RSS"),
        single_adapter=dict(parameter_array_bytes=params, optimizer_m_v_array_bytes=adam,
                            sampler_order_array_bytes=order.nbytes, causal_profile_json_bytes=own_profile,
                            compressed_checkpoint_file_bytes=(results / "seed-713/single.npz").stat().st_size),
        baseline_indexes={name: {**serialize_index(model), "requires_shared_encoder": name in ENCODED_METHODS} for name, model in baselines.items()},
        sources=dict(train_rows_physical_bytes=source_files["train_rows.json"], all_exported_row_files=source_files,
                     profile_snapshot_files=profile_files, note="Authored dataset artifacts contain evaluator goldens too; these are provenance files, not an asserted minimal production store."),
        archived_checkpoint_files=checkpoints,
        all_checkpoint_physical_bytes=sum(checkpoints.values()),
        excluded_or_separate=["OS/page cache", "allocator and Python object overhead", "model migration network bytes and latency", "external service or queueing cost"],
    )


def run(model_dir, inputs, results, repeats=3):
    if repeats < 3:
        raise ValueError("At least three repetitions are required")
    started_wall, started_cpu = time.perf_counter(), time.process_time()
    inventory = json.loads((inputs / "INVENTORY.json").read_text())
    for name in ("encoder_manifest.json", "train_rows.json", "train_features.npz", "test_rows.json", "hybrid_rows.json"):
        if sha(inputs / name) != inventory[name]["sha256"]:
            raise ValueError(f"Frozen input identity mismatch: {name}")
    manifest = json.loads((inputs / "encoder_manifest.json").read_text())
    train_rows = json.loads((inputs / "train_rows.json").read_text())
    held_rows = json.loads((inputs / "test_rows.json").read_text())
    if len(held_rows) < 72 or any(row["split"] != "test" for row in held_rows):
        raise ValueError("Expected the complete holdout of at least 72 requests")
    if any(row["split"] != "train" for row in train_rows):
        raise ValueError("Baseline fitting requires the training split")
    if hashlib.sha256(tasks.canonical(train_rows)).hexdigest() != manifest["source_version"]:
        raise ValueError("Training rows differ from the model source version")
    with np.load(inputs / "train_features.npz", allow_pickle=False) as saved:
        features = saved["X"].copy()
        if not np.array_equal(saved["y"], [row["label"] for row in train_rows]):
            raise ValueError("Training row/feature label mismatch")
    encoder = FrozenEncoder(model_dir, threads=1)
    if encoder.manifest_hash != manifest["encoder_hash"]:
        raise ValueError("Profiler encoder differs from the trained encoder")
    stage_wall, stage_cpu = time.perf_counter(), time.process_time()
    stats_before_train = dict(encoder.stats)
    recomputed = encoder.encode([row["text"] for row in train_rows])
    train_feature_cost = dict(wall_seconds=time.perf_counter() - stage_wall, cpu_seconds=time.process_time() - stage_cpu,
                              input_tokens=encoder.stats["input_tokens"] - stats_before_train["input_tokens"],
                              encoded_tokens=encoder.stats["encoded_tokens"] - stats_before_train["encoded_tokens"],
                              examples=len(train_rows), max_abs_delta_from_frozen=float(np.max(np.abs(recomputed - features))),
                              attribution="One common train-feature encoding, reported separately; methods use the identical frozen training matrix.")
    if not np.allclose(recomputed, features, rtol=1e-6, atol=1e-7):
        raise ValueError("Frozen training features fail direct encoder reproduction")
    checkpoint = results / "seed-713/single.npz"
    stage_wall, stage_cpu = time.perf_counter(), time.process_time()
    adapter = Adapter.load(checkpoint, expected_encoder_hash=encoder.manifest_hash, expected_source_version=manifest["source_version"], expected_data_id="skills-train")
    adapter_load = dict(wall_seconds=time.perf_counter() - stage_wall, cpu_seconds=time.process_time() - stage_cpu)
    initial_model_hash = adapter.state_hash()
    constructors = dict(exact_store=lambda: ExactStore(train_rows), bm25=lambda: BM25(train_rows),
                        nearest=lambda: NearestExample(train_rows, features), centroid=lambda: Centroid(train_rows, features),
                        ridge=lambda: RidgeClassifier(features, np.asarray([row["label"] for row in train_rows]), len(tasks.SKILLS)))
    baselines, index_build = {}, {}
    for name, construct in constructors.items():
        stage_wall, stage_cpu = time.perf_counter(), time.process_time()
        baselines[name] = construct()
        index_build[name] = dict(wall_seconds=time.perf_counter() - stage_wall, cpu_seconds=time.process_time() - stage_cpu)
    saved_ridge = np.load(results / "seed-713/ridge.npy", allow_pickle=False)
    if not np.array_equal(baselines["ridge"].weights, saved_ridge):
        raise ValueError("Rebuilt ridge differs from the fixed experiment model")
    methods = {**baselines, "single_adapter": adapter}
    setup = dict(wall_seconds=time.perf_counter() - started_wall, cpu_seconds=time.process_time() - started_cpu,
                 encoder_stats=dict(encoder.stats), train_feature_encoding=train_feature_cost,
                 index_build_or_ridge_fit=index_build, adapter_checkpoint_load=adapter_load)
    warmup = [timed_request(name, model, encoder, train_rows[0]) for name, model in methods.items()]
    initial_encoder_stats = dict(encoder.stats)
    records = []
    rng = np.random.default_rng(271828)
    for repeat in range(repeats):
        for row_number in rng.permutation(len(held_rows)):
            row = held_rows[int(row_number)]
            for within_query, name in enumerate(rng.permutation(list(methods))):
                record = timed_request(str(name), methods[name], encoder, row)
                record.update(repeat=repeat, trial=len(records), within_query_order=within_query)
                records.append(record)
    summaries = summarize(records)
    expected_calls = repeats * len(held_rows) * len(ENCODED_METHODS)
    actual_calls = encoder.stats["calls"] - initial_encoder_stats["calls"]
    if actual_calls != expected_calls:
        raise AssertionError("Each embedding method must perform its own per-query encoder call")
    for name in ("exact_store", "bm25"):
        if summaries[name]["encoder_calls"]:
            raise AssertionError("Text-only control invoked the encoder")
    profile_rows = json.loads((inputs / "hybrid_rows.json").read_text())
    profile_models, profile_build, profile_records = {}, {}, []
    for frontier in sorted({row["as_of"] for row in profile_rows}):
        stage_wall, stage_cpu = time.perf_counter(), time.process_time()
        profile_models[frontier] = ProfileExactStore(tasks.profile_journal(), frontier)
        profile_build[frontier] = dict(wall_seconds=time.perf_counter() - stage_wall, cpu_seconds=time.process_time() - stage_cpu,
                                      index_storage=serialize_index(profile_models[frontier]))
    for case in profile_rows:
        row = {**case, "text": case["original_text"], "label": tasks.SKILLS.index(case["skill"])}
        record = timed_request("profile_exact", profile_models[case["as_of"]], encoder, row)
        record.update(frontier=case["as_of"], project=case["project"], repeat=0)
        profile_records.append(record)
    if encoder.stats["calls"] - initial_encoder_stats["calls"] != expected_calls:
        raise AssertionError("Profile exact store unexpectedly invoked the encoder")
    if adapter.state_hash() != initial_model_hash:
        raise AssertionError("Profiling changed the learned model")
    training_receipts = json.loads((results / "seed-713/SELECTION.json").read_text())["training"]
    result = dict(
        schema="hepta-memory-v13-local-warm-latency-cost-v1", model_id=encoder.manifest["model_id"],
        encoder_hash=encoder.manifest_hash, checkpoint_sha256=sha(checkpoint),
        checkpoint_state_hash=adapter.state_hash(), setup=setup, training_request_warmup=warmup,
        repeats=repeats, authored_holdout_requests=len(held_rows), independent_timing_samples_claim=False,
        query_results_shared_between_methods=False, encoder_result_cache_used=False,
        method_order="seeded independent permutations per request; request order permuted each repetition",
        encoder_calls_observed=actual_calls, encoder_calls_expected=expected_calls,
        encoder_stats_before_measurement=initial_encoder_stats, encoder_stats_after_measurement=encoder.stats,
        summaries=summaries, records=records,
        profile_exact=dict(records=profile_records, summaries=summarize(profile_records), setup=profile_build,
                           repeats=1, scope="Three constructed projects across four version frontiers; linked repeated snapshots, not twelve independent tasks. Source resolution runs inside timed prediction; no encoder and only the original public project-name request."),
        training_evidence=dict(source="seed-713/SELECTION.json", receipts=training_receipts,
                               interpretation="Previously incurred adapter/candidate training wall time and presentations; per-method CPU training and source-ingestion totals are not inferred. Common train-feature encoding is separately measured in setup."),
        storage=storage_ledger(model_dir, inputs, results, adapter, baselines),
        environment=dict(python=platform.python_version(), platform=platform.platform(), packages=encoder.manifest["packages"], threads=1),
        measured_scope="Warm resident single CPU process: public input copy, actual query encoding when required, prediction, registered skill execution, output canonicalization. Golden scoring is excluded from per-request latency.",
        excluded_scope=["cold process/startup per request", "request transport", "queueing and concurrency", "remote node discovery", "source ingestion and training amortization", "failure recovery", "energy"],
        network_measurement=dict(included=False, reason="Cross-node transport is a separate measurement; local timing cannot establish a network benefit."),
        hardware_generalization_claim=False, complete_system_cost_claim=False,
        quality_constraint="Timing differences alone do not establish a cost victory when accepted coverage or task quality differs. Compare equal-quality operating points before amortized economic claims.",
        memory_measurement="Weights/index/source/profile/optimizer file and array sizes are reported. Process RAM, allocator overhead, page-cache residency, and peak activation memory were not isolated per method.",
        profiling_process_wall_seconds=time.perf_counter() - started_wall,
        profiling_process_cpu_seconds=time.process_time() - started_cpu,
        source_sha256={name: sha(Path(__file__).with_name(name)) for name in ("latency_cost.py", "backend.py", "adapter.py", "baselines.py", "experiment.py", "tasks.py")},
    )
    destination = results / "LATENCY_COST.json"
    destination.write_text(json.dumps(result, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False) + "\n")
    print(json.dumps(dict(output=str(destination), encoder_calls=actual_calls, summaries=summaries), sort_keys=True, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--inputs", type=Path, required=True)
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args()
    run(args.model_dir, args.inputs, args.results, args.repeats)
