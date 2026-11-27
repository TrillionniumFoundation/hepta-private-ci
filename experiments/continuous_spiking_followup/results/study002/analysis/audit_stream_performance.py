"""Post-seal independent arithmetic and identity checks for all selected streams."""

import json
from pathlib import Path
import traceback

import numpy as np

from online_audit_common import canonical, check, close, read_arrays, sha
from online_state_audit import checkpoint_model_digest
from audit_stream_replay import audit_replay


def tensor_sha(array):
    import hashlib

    header = json.dumps(
        {"shape": list(array.shape), "dtype": array.dtype.str}, sort_keys=True
    ).encode()
    return hashlib.sha256(header + np.ascontiguousarray(array).tobytes()).hexdigest()


def statistics(values):
    values = np.asarray(values, dtype=float)
    return {
        "median": float(np.median(values)),
        "p95": float(np.quantile(values, 0.95)),
        "p05": float(np.quantile(values, 0.05)),
        "min": float(values.min()),
        "max": float(values.max()),
        "sum": float(values.sum()),
    }


def expected_state_bytes(config, tensors, batch, length):
    check(
        config.get("match_cell_budget") is False,
        "state-byte formulas require the 55 prespecified unmatched model widths",
    )
    width, depth, name = config["width"], config["depth"], config["architecture"]
    base = batch * 8  # Serialized v2 elapsed accumulator is float64.
    if name == "transformer":
        return [base + 2 * batch * width * depth * t * 4 for t in range(length + 1)]
    if name in {"hcsn", "single", "no_adaptation", "ordinary"}:
        fixed = 4 * batch * width * depth * 4
    elif name == "lif_snn":
        fixed = 2 * batch * width * depth * 4
    elif name in {"continuous_rnn", "two_gates", "cfc"}:
        fixed = batch * width * depth * 4
    elif name == "mamba1":
        shapes = {row["name"]: row["shape"] for row in tensors}
        fixed = 0
        for layer in range(depth):
            conv = shapes[f"backbone.blocks.{layer}.mixer.conv1d.weight"]
            state = shapes[f"backbone.blocks.{layer}.mixer.A_log"]
            fixed += batch * (conv[0] * (conv[2] - 1) + state[0] * state[1]) * 4
    else:
        raise ValueError("unrecognized architecture in state-byte audit")
    return [base + fixed] * (length + 1)


def audit_measurement(directory, study, protocol, data_cache, cache_dir):
    from experiments.continuous_spiking_network.data import load_data

    result = json.loads((directory / "MEASUREMENT.json").read_text())
    spec, identity = result["identity"]["spec"], result["identity"]
    run = study / spec["id"]
    training = json.loads((run / "RESULT.json").read_text())
    check(
        sha(run / "RESULT.json") == identity["run_result_sha256"],
        "measurement training result identity",
    )
    check(
        training["spec"] == spec
        and training["source_seals"] == identity["source_seals"],
        "measurement specification/source identity",
    )
    checkpoint = run / training["selected_checkpoint"]
    check(
        training["selected_checkpoint"] == identity["selected_checkpoint"],
        "actual selected checkpoint",
    )
    check(
        sha(checkpoint / "manifest.json") == identity["checkpoint_manifest_sha256"],
        "measurement checkpoint identity",
    )
    manifest = json.loads((checkpoint / "manifest.json").read_text())
    check(
        checkpoint_model_digest(checkpoint) == result["model_sha256"],
        "independent measurement model byte/config binding",
    )
    check(
        result["strict_reload"] and result["environment"]["threads"] == 1,
        "strict single-thread CPU contract",
    )
    check(not result["environment"]["cuda"], "recorded CPU-only environment")
    recorded_data = json.loads((run / "DATA.json").read_text())
    check(
        canonical(recorded_data, compact=True) == identity["data_manifest_sha256"],
        "saved data manifest identity",
    )
    for folder, field in (
        ("sources", "sources_manifest_sha256"),
        ("predictions", "predictions_manifest_sha256"),
    ):
        check(
            sha(run / folder / "manifest.json") == training[field] == identity[field],
            "training data/prediction identity",
        )
    batch, length = result["fixed_batch"]["batch_size"], spec["length"]
    check(
        batch == min(protocol["batch_size"], spec["test_size"]),
        "preselected batch size",
    )
    check(result["fixed_batch"]["sequence_length"] == length, "sequence length")
    key = tuple(
        spec[k]
        for k in ("task", "data_seed", "train_size", "val_size", "test_size", "length")
    )
    if key not in data_cache:
        bundle = load_data(
            spec["task"],
            train_size=spec["train_size"],
            val_size=spec["val_size"],
            test_size=spec["test_size"],
            context_length=length,
            seed=spec["data_seed"],
            cache_dir=cache_dir,
        )
        data_cache[key] = {
            "manifest": canonical(bundle.manifest, compact=True),
            "x": bundle.test.x[:batch].copy(),
            "dt": bundle.test.dt[:batch].copy(),
            "ids": bundle.test.sample_ids[:batch].copy(),
            "labels": bundle.test.y[:batch].copy(),
        }
    rebuilt = data_cache[key]
    check(
        rebuilt["manifest"] == identity["data_manifest_sha256"],
        "independent measurement data rebuild",
    )
    check(
        tensor_sha(rebuilt["x"]) == result["fixed_batch"]["x_sha256"]
        and tensor_sha(rebuilt["dt"]) == result["fixed_batch"]["dt_sha256"],
        "actual fixed measurement input tensors",
    )
    check(
        rebuilt["ids"].tolist() == result["fixed_batch"]["sample_ids"],
        "first heldout episode selection",
    )
    check(
        result["warmup_repetitions_per_mode"] == protocol["warmups"]
        and result["measurement_repetitions_per_mode"] == protocol["repeats"],
        "fixed repeat counts",
    )
    expected_order = [
        (phase, repeat, mode)
        for phase, count in (
            ("warmup", protocol["warmups"]),
            ("measurement", protocol["repeats"]),
        )
        for repeat in range(count)
        for mode in (("batch", "stream") if repeat % 2 == 0 else ("stream", "batch"))
    ]
    check(
        [(r["phase"], r["repeat"], r["mode"]) for r in result["raw_samples"]]
        == expected_order,
        "alternating timing order",
    )
    for row in result["raw_samples"]:
        check(
            all(np.isfinite(x) and x > 0 for x in row["forward"].values()),
            "positive raw forward clocks",
        )
        check(
            row["reset_plus_forward_interval"]["wall_seconds"]
            >= row["forward"]["wall_seconds"],
            "enclosing timing scope",
        )
        if row["mode"] == "stream":
            check(
                row["reset_with_identity_check"]["wall_seconds"] > 0,
                "separately measured reset/hash",
            )
        else:
            check(row["reset_with_identity_check"] is None, "batch reset scope")
    for mode in ("batch", "stream"):
        raw = [
            r
            for r in result["raw_samples"]
            if r["phase"] == "measurement" and r["mode"] == mode
        ]
        metrics = result["measurement"][mode]
        walls = [r["forward"]["wall_seconds"] for r in raw]
        cpus = [r["forward"]["cpu_seconds"] for r in raw]
        check(
            walls == metrics["wall_seconds"] and cpus == metrics["process_cpu_seconds"],
            "raw timed samples retained",
        )
        for field, values in (
            ("wall_latency_seconds", walls),
            ("process_cpu_seconds_stats", cpus),
            ("examples_per_second", [batch / wall for wall in walls]),
        ):
            for name, value in statistics(values).items():
                close(
                    metrics[field][name],
                    value,
                    "latency/throughput arithmetic",
                    atol=1e-12,
                )
        check(
            metrics["reset_plus_forward_wall_seconds"]
            == [r["reset_plus_forward_interval"]["wall_seconds"] for r in raw],
            "combined reset/forward raw samples",
        )
        check(
            metrics["repeat_output_max_abs_difference"] >= 0, "repeat error is retained"
        )
    parity = result["parity"]
    check(
        sha(directory / "parity_arrays/manifest.json")
        == parity["arrays_manifest_sha256"],
        "prefix logits archive identity",
    )
    arrays = read_arrays(directory / "parity_arrays")
    full, streamed = (
        arrays["full_sequence_prefix_logits"],
        arrays["incremental_prefix_logits"],
    )
    check(
        full.shape == streamed.shape == (batch, length, manifest["config"]["classes"]),
        "prefix output shapes",
    )
    check(
        full.dtype == streamed.dtype == np.float32
        and np.isfinite(full).all()
        and np.isfinite(streamed).all(),
        "finite float32 outputs",
    )
    check(
        np.array_equal(arrays["sample_ids"], rebuilt["ids"])
        and np.array_equal(arrays["labels"], rebuilt["labels"]),
        "parity episode/label identity",
    )
    rtol, atol = protocol["sequence_parity_rtol"], protocol["sequence_parity_atol"]
    check(parity["rtol"] == rtol and parity["atol"] == atol, "fixed parity tolerance")
    within = np.isclose(streamed, full, rtol=rtol, atol=atol)
    changed = streamed.argmax(-1) != full.argmax(-1)
    check(
        bool(within.all()) == parity["all_prefixes_within_tolerance"]
        and int((~within).sum()) == parity["tensor_entries_outside_tolerance"],
        "numerical parity arithmetic",
    )
    close(
        parity["max_abs_logit_error"],
        float(np.max(np.abs(streamed - full))),
        "maximum prefix error",
        atol=0,
        rtol=0,
    )
    close(
        parity["final_max_abs_logit_error"],
        float(np.max(np.abs(streamed[:, -1] - full[:, -1]))),
        "maximum final error",
        atol=0,
        rtol=0,
    )
    check(
        int(changed.sum()) == parity["prefix_predicted_class_changes"]
        and int(changed[:, -1].sum()) == parity["final_predicted_class_changes"],
        "predicted class disagreements",
    )
    predicted = read_arrays(run / "predictions")["logits"][:batch]
    saved_agreement = bool(np.allclose(full[:, -1], predicted, rtol=rtol, atol=atol))
    check(
        saved_agreement == parity["saved_training_predictions_within_tolerance"],
        "selected training prediction agreement",
    )
    check(
        parity["passed"]
        == (bool(within.all()) and not bool(changed.any()) and saved_agreement),
        "parity failure must not be hidden",
    )
    check(
        parity["state_payload_bytes_initial_and_after_each_step"]
        == expected_state_bytes(manifest["config"], manifest["tensors"], batch, length),
        "independent persistent state-byte formula",
    )
    check(
        parity["final_state_payload_bytes"]
        == parity["state_payload_bytes_initial_and_after_each_step"][-1],
        "final persistent bytes",
    )
    check(
        parity["steps"] == length and parity["processed_rows"] == batch * length,
        "actual processed stream work",
    )
    selected_replay = (
        spec["stage"] == "representation"
        and spec["task"] == "mnist"
        and spec["seed"] == 6201
    )
    replay = audit_replay(
        directory,
        result["cross_process_replay"],
        selected_replay,
        rebuilt,
        streamed,
        result["model_sha256"],
        identity["checkpoint_manifest_sha256"],
        parity["final_state_payload_bytes"],
    )
    return {
        "id": spec["id"],
        "measurement_sha256": sha(directory / "MEASUREMENT.json"),
        "parity_passed": parity["passed"],
        "prefix_class_changes": parity["prefix_predicted_class_changes"],
        "max_abs_logit_error": parity["max_abs_logit_error"],
        "cold_replay": replay,
        "state_bytes": parity["final_state_payload_bytes"],
        "raw_samples_checked": len(result["raw_samples"]),
    }


def audit_performance(study, package, protocol, issues, missing, cache_dir=None):
    inventory = json.loads((package / "RUNS.json").read_text())
    expected = {
        row["id"]
        for row in inventory
        if (row["stage"] == "representation" and row["seed"] == 6201)
        or (row["stage"] == "scaling" and row["seed"] == 7301)
    }
    check(
        len(expected) == protocol["stream_measurement"]["cases"],
        "measurement preselection inventory",
    )
    discovered = {}
    for path in study.rglob("MEASUREMENT.json"):
        if "failed_attempts" in path.relative_to(study).parts:
            continue
        item = json.loads(path.read_text())
        case = item["identity"]["spec"]["id"]
        if case in discovered:
            issues.append({"case": case, "problem": "duplicate measurement"})
        discovered[case] = path.parent
    for case in sorted(expected - set(discovered)):
        missing.append("measurement/" + case)
    for case in sorted(set(discovered) - expected):
        issues.append({"case": case, "problem": "unexpected measurement"})
    data_cache, reports = {}, {}
    cache_dir = (
        Path(cache_dir) if cache_dir else package.parent.parent.parent / "hcsn-data"
    )
    for case in sorted(expected & set(discovered)):
        try:
            reports[case] = audit_measurement(
                discovered[case],
                study,
                protocol["stream_measurement"],
                data_cache,
                cache_dir,
            )
        except Exception:
            issues.append(
                {"case": "measurement/" + case, "traceback": traceback.format_exc()}
            )
    return {
        "planned_cases": len(expected),
        "audited_cases": len(reports),
        "cases": reports,
        "parity_failures_retained": [
            case for case, row in reports.items() if not row["parity_passed"]
        ],
        "exact_cross_process_cases": sum(
            row["cold_replay"].get("selected", False) for row in reports.values()
        ),
        "distinct_test_input_configs_reconstructed": len(data_cache),
    }
