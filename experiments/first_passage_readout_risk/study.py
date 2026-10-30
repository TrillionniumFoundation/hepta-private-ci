"""Freeze without simulation; execute once after publication; reproduce cached risks."""

import argparse
import os
from pathlib import Path
import platform
import time
import traceback

from .artifacts import (HERE, ROOT, canonical, entry, freeze, manifest, read_json,
                        sha, verify_artifacts, verify_execution_commit, verify_freeze,
                        write_bytes, write_json)


def check_environment(config):
    if platform.python_version() != config["runtime"]["python"]:
        raise ValueError("The registered Python version is required")
    for name in config["runtime"]["thread_environment"]:
        if os.environ.get(name) != "1":
            raise ValueError(name + " must equal 1 before numerical imports")


def execute(commit, directory):
    config, publication = verify_execution_commit(commit)
    check_environment(config)
    from . import features, risk
    import numpy as np

    runtime = features.runtime_identity(config, encoder=True)
    directory = directory.resolve()
    if directory.is_relative_to(ROOT / "experiments/first_passage_operator") or directory.is_relative_to(ROOT / "experiments/first_passage_cell"):
        raise ValueError("The original frozen packages cannot be output destinations")
    directory.mkdir(parents=True, exist_ok=False)
    write_json(directory / "RUN_STARTED.json", {"publication": publication, "runtime": runtime,
                                               "status": "started", "resume_supported": False})
    write_bytes(directory / "SOURCE_FREEZE.json", (HERE / "FREEZE.json").read_bytes())
    write_bytes(directory / "PROTOCOL.json", (HERE / "PROTOCOL.json").read_bytes())
    heads, receipts, attempted_fits, fit_seconds = [], [], 0, 0.0
    try:
        # Complete all six fixed fits before opening any confirmation stream.
        for encoder in config["encoders"]:
            seed = encoder["seed"]
            checkpoint = read_json(ROOT / encoder["path"])["checkpoint"]
            net = features.restore_encoder(checkpoint, seed)
            train, receipt = features.generate_cache(net, seed, "train", config, directory)
            receipts.append(receipt)
            mean = train["features"].mean(axis=(0, 1))
            scale = np.maximum(train["features"].std(axis=(0, 1), ddof=0), 1e-8)
            standardized = (train["features"] - mean) / scale
            pair = {}
            for arm in risk.ARMS:
                attempted_fits += 1
                begin = time.perf_counter()
                try:
                    head = risk.fit_head(standardized, train["labels"], arm, config)
                except Exception as error:
                    head = {"arm": arm, "parameters": None, "numerically_accepted": False,
                            "error_type": type(error).__name__, "message": str(error),
                            "traceback": traceback.format_exc()}
                elapsed = time.perf_counter() - begin
                fit_seconds += elapsed
                head.update(seed=seed, train_mean=mean.tolist(), train_scale=scale.tolist(),
                            wall_seconds=elapsed, parameters_per_head=4,
                            train_cache_manifest_sha256=sha(canonical(receipt)))
                write_json(directory / f"heads/{seed}/{arm}.json", head)
                pair[arm] = head
            heads.append(pair)
            development, receipt = features.generate_cache(net, seed, "development", config, directory)
            receipts.append(receipt)
            write_json(directory / f"development/{seed}.json", risk.evaluate(development, pair))
            print(f"Frozen diagnostic heads and descriptive development complete: {seed}", flush=True)
        if attempted_fits != 6:
            raise ArithmeticError("The registered fit budget was not respected")
        write_json(directory / "HEADS_FROZEN.json", {
            "files": [entry(path, directory) for path in sorted((directory / "heads").rglob("*.json"))],
            "attempted_fits": attempted_fits, "confirmation_opened": False,
            "development_used_for_selection": False})
        confirmations = []
        for encoder, pair in zip(config["encoders"], heads, strict=True):
            seed = encoder["seed"]
            net = features.restore_encoder(read_json(ROOT / encoder["path"])["checkpoint"], seed)
            cache, receipt = features.generate_cache(net, seed, "confirmation", config, directory)
            receipts.append(receipt)
            result = risk.evaluate(cache, pair)
            write_json(directory / f"confirmation/{seed}.json", result)
            confirmations.append(result)
            print(f"Confirmation cache complete: {seed}", flush=True)
        trajectories = sum(row["trajectories"] for row in receipts)
        if trajectories != 43008:
            raise ArithmeticError("The registered trajectory budget was not respected")
        bootstrap_identity = features.bootstrap_stream(config)
        write_json(directory / "BOOTSTRAP_STREAM.json", bootstrap_identity)
        rng = np.random.Generator(np.random.PCG64(int(bootstrap_identity["seed_decimal"])))
        comparison, replicates = risk.comparison(confirmations, heads, rng, config)
        write_json(directory / "COMPARISON.json", comparison)
        if replicates is not None:
            features.save_arrays(directory / "bootstrap_replicates.npz", {"improvement_nats": replicates})
        write_json(directory / "COST.json", {
            "encoder_trajectories": trajectories, "deterministic_head_fit_attempts": attempted_fits,
            "generation_wall_seconds": sum(row["wall_seconds"] for row in receipts),
            "actual_events": sum(row["actual_events"] for row in receipts),
            "head_fit_wall_seconds": fit_seconds,
            "max_affine_error": max(row["max_affine_error"] for row in receipts),
            "cache_shared_by_arms": True, "deployed_trajectories_per_prediction": 1,
            "compute_fairness_claim": "Same cached features and optimizer settings; no equal wall-time or baseline-compute superiority claim."})
        verify_freeze()
        write_json(directory / "RUN_FINISHED.json", {"status": "completed", "scientific_status": comparison["status"],
                                                     "original_confirmation": "unchanged: 0/6", "publication": publication})
    except Exception as error:
        write_json(directory / "FAILURE.json", {"status": "incomplete", "error_type": type(error).__name__,
                                               "message": str(error), "traceback": traceback.format_exc(),
                                               "attempted_head_fits": attempted_fits,
                                               "action": "Retain this failure; no automatic retry, cap increase or replacement confirmation."})
        raise
    finally:
        manifest(directory)


def assert_close_tree(actual, expected):
    import math

    if isinstance(expected, dict):
        if actual.keys() != expected.keys():
            raise ArithmeticError("Reproduction keys differ")
        for key in expected:
            assert_close_tree(actual[key], expected[key])
    elif isinstance(expected, list):
        if len(actual) != len(expected):
            raise ArithmeticError("Reproduction dimensions differ")
        for a, b in zip(actual, expected, strict=True):
            assert_close_tree(a, b)
    elif isinstance(expected, float):
        if not math.isclose(actual, expected, rel_tol=1e-12, abs_tol=1e-12):
            raise ArithmeticError("Reproduced numeric summary differs")
    elif actual != expected:
        raise ArithmeticError("Reproduced decision or metadata differs")


def reproduce(directory, destination):
    config, _ = verify_freeze()
    check_environment(config)
    verify_artifacts(directory)
    from . import features, risk
    import numpy as np

    runtime = features.runtime_identity(config, encoder=False)
    if read_json(directory / "PROTOCOL.json") != config:
        raise ValueError("The retained experiment used a different protocol")
    if (directory / "SOURCE_FREEZE.json").read_bytes() != (HERE / "FREEZE.json").read_bytes():
        raise ValueError("The retained experiment used different frozen source or checkpoints")
    frozen_heads = read_json(directory / "HEADS_FROZEN.json")
    expected_heads = [entry(path, directory) for path in sorted((directory / "heads").rglob("*.json"))]
    if frozen_heads != {"files": expected_heads, "attempted_fits": 6,
                        "confirmation_opened": False, "development_used_for_selection": False}:
        raise ValueError("The retained heads differ from the pre-confirmation head freeze")
    heads, confirmations = [], []
    for encoder in config["encoders"]:
        seed = encoder["seed"]
        pair = {arm: read_json(directory / f"heads/{seed}/{arm}.json") for arm in risk.ARMS}
        heads.append(pair)
        for split in ("development", "confirmation"):
            row = risk.evaluate(features.load_cache(directory, seed, split), pair)
            assert_close_tree(row, read_json(directory / f"{split}/{seed}.json"))
            if split == "confirmation":
                confirmations.append(row)
    identity = features.bootstrap_stream(config)
    if identity != read_json(directory / "BOOTSTRAP_STREAM.json"):
        raise ValueError("The retained bootstrap stream differs")
    rng = np.random.Generator(np.random.PCG64(int(identity["seed_decimal"])))
    result, replicates = risk.comparison(confirmations, heads, rng, config)
    assert_close_tree(result, read_json(directory / "COMPARISON.json"))
    if replicates is not None:
        with np.load(directory / "bootstrap_replicates.npz", allow_pickle=False) as archive:
            if not np.allclose(replicates, archive["improvement_nats"], rtol=1e-12, atol=1e-12):
                raise ArithmeticError("The original bootstrap replicas differ")
    write_json(destination, {"status": "reproduced_from_retained_caches", "runtime": runtime,
                             "comparison": result, "encoder_executions": 0, "head_fits": 0,
                             "new_data": False, "new_statistical_test": False,
                             "input_manifest_sha256": sha((directory / "ARTIFACT_MANIFEST.json").read_bytes())})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("freeze")
    run = commands.add_parser("execute")
    run.add_argument("--freeze-commit", required=True)
    run.add_argument("--output", type=Path, required=True)
    replay = commands.add_parser("reproduce")
    replay.add_argument("--run-dir", type=Path, required=True)
    replay.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "freeze":
        print(freeze())
    elif args.command == "execute":
        execute(args.freeze_commit, args.output)
    else:
        reproduce(args.run_dir, args.output)


if __name__ == "__main__":
    main()
