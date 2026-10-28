"""Registered six-arm learning runs and checkpoint-only independent rescoring."""

import argparse
import hashlib
import itertools
import json
from pathlib import Path
import time

import numpy as np
from scipy.special import logit
from scipy.stats import t as student_t

from ..provenance import verify
from .network import Adam, boundaries, forward, initialize, loss_and_gradient
from .task import BellmanReference, evaluate, make_episodes, myopic_boundaries


PROTOCOL_PATH = Path(__file__).with_name("PROTOCOL.json")
METHODS = ("fixed", "direct", "free")
GRADIENTS = ("standard", "first_passage")


def parameter_digest(parameters):
    digest = hashlib.sha256()
    for key, value in sorted(parameters.items()):
        digest.update(key.encode())
        digest.update(np.ascontiguousarray(value).tobytes())
    return digest.hexdigest()


def select_fixed(parameters, validation, gradient, protocol):
    """Validation-only grid choice; exact ties retain the first declared pair."""
    voltage, _, _ = forward(parameters, validation, gradient, cache_gradients=False)
    best, evaluations = (-float("inf"), None), 0
    for upper in protocol["fixed_selection"]["choice_threshold_grid"]:
        for lower in protocol["fixed_selection"]["abstain_threshold_grid"]:
            pair = (np.full_like(voltage, upper), np.full_like(voltage, lower))
            score = evaluate(voltage, *pair, validation)["mean_utility"]
            evaluations += 1
            if score > best[0]:
                best = (score, (upper, lower))
    return best[1], evaluations


def train(
    seed,
    method,
    gradient,
    training,
    validation,
    oracle,
    protocol,
    *,
    steps=None,
    progress=None,
):
    started = time.perf_counter()
    config = protocol["training"]
    steps = config["steps"] if steps is None else steps
    parameters = initialize(seed, method)
    initial = {key: value.copy() for key, value in parameters.items()}
    optimizer = Adam(parameters, config["learning_rate"])
    schedule = np.random.default_rng(np.random.SeedSequence([seed, 703]))
    free = oracle.boundaries(training) if method == "free" else None
    fixed = (
        protocol["fixed_selection"]["training_choice_threshold"],
        protocol["fixed_selection"]["training_abstain_threshold"],
    )
    check = np.arange(min(128, len(training.truth)))
    check_free = tuple(array[check] for array in free) if free is not None else None
    initial_loss = loss_and_gradient(
        parameters, training.take(check), method, gradient, fixed=fixed, free=check_free
    )[0]
    norms = []
    for _ in range(steps):
        indices = schedule.integers(len(training.truth), size=config["batch_size"])
        batch = training.take(indices)
        batch_free = (
            tuple(array[indices] for array in free) if free is not None else None
        )
        _, derivatives, _ = loss_and_gradient(
            parameters, batch, method, gradient, fixed=fixed, free=batch_free
        )
        norms.append(optimizer.step(parameters, derivatives))
        if progress is not None:
            progress["last_completed_optimizer_step"] = optimizer.step_count
    final_loss = loss_and_gradient(
        parameters, training.take(check), method, gradient, fixed=fixed, free=check_free
    )[0]
    training_seconds = time.perf_counter() - started
    selection_started = time.perf_counter()
    validation_evaluations = 0
    if method == "fixed":
        fixed, validation_evaluations = select_fixed(
            parameters, validation, gradient, protocol
        )
    change = float(
        np.sqrt(sum(np.sum((parameters[k] - initial[k]) ** 2) for k in parameters))
    )
    return (
        parameters,
        fixed,
        {
            "training_seconds": training_seconds,
            "selection_seconds": time.perf_counter() - selection_started,
            "training_steps": steps,
            "minibatch_size": config["batch_size"],
            "actual_training_cell_updates": (
                steps * config["batch_size"] + 2 * len(check)
            )
            * 16
            * 8,
            "optimizer_forward_cell_updates": steps * config["batch_size"] * 16 * 8,
            "diagnostic_forward_cell_updates": 2 * len(check) * 16 * 8,
            "selection_forward_cell_updates": len(validation.truth) * 16 * 8
            if method == "fixed"
            else 0,
            "parameter_count": sum(value.size for value in parameters.values()),
            "parameter_change_l2": change,
            "initial_training_loss": initial_loss,
            "final_training_loss": final_loss,
            "max_gradient_norm": float(max(norms, default=0)),
            "clipped_gradient_steps": optimizer.clipped_steps,
            "projected_parameter_scalars": optimizer.projected_scalars,
            "validation_threshold_evaluations": validation_evaluations,
            "checkpoint_sha256": parameter_digest(parameters),
        },
    )


def score_model(parameters, fixed, method, gradient, episodes, oracle):
    started = time.perf_counter()
    voltage, spikes, _ = forward(parameters, episodes, gradient, cache_gradients=False)
    free = oracle.boundaries(episodes) if method == "free" else None
    (choice, abstain), _ = boundaries(
        parameters, episodes, method, fixed=fixed, free=free
    )
    result = evaluate(voltage, choice, abstain, episodes, spikes=spikes, cells=8)
    result["inference_seconds"] = time.perf_counter() - started
    result["dataset_sha256"] = episodes.digest
    result["source_of_probability"] = (
        "learned_log_odds_readout_not_terminal_or_FPT_probability"
    )
    return result


def score_references(episodes, oracle):
    result = {}
    for name, getter in (
        ("raw_belief_dp", oracle.boundaries),
        ("raw_belief_myopic_voc", myopic_boundaries),
    ):
        started = time.perf_counter()
        voltage = np.cumsum(
            episodes.observations * logit(episodes.reliability[:, None]), axis=1
        )
        upper, lower = getter(episodes)
        result[name] = evaluate(voltage, upper, lower, episodes)
        result[name]["inference_seconds"] = time.perf_counter() - started
        result[name]["dataset_sha256"] = episodes.digest
    return result


def paired_analysis(records, phase, minimum_effect=0.005):
    results = []
    for gradient in GRADIENTS:
        differences = []
        for row in records:
            arms = row["arms"]
            differences.append(
                arms[f"free:{gradient}"]["ood_test"]["mean_utility"]
                - arms[f"direct:{gradient}"]["ood_test"]["mean_utility"]
            )
        values = np.asarray(differences)
        mean = float(np.mean(values))
        se = (
            float(np.std(values, ddof=1) / np.sqrt(len(values)))
            if len(values) > 1
            else None
        )
        ordinary = (
            float(student_t.ppf(0.975, len(values) - 1) * se)
            if se is not None
            else None
        )
        adjusted = (
            float(student_t.ppf(0.9875, len(values) - 1) * se)
            if se is not None
            else None
        )
        interval = [mean - adjusted, mean + adjusted] if adjusted is not None else None
        results.append(
            {
                "gradient": gradient,
                "n_independent_seeds": len(values),
                "paired_differences": differences,
                "mean_difference": mean,
                "descriptive_95_ci": [mean - ordinary, mean + ordinary]
                if ordinary is not None
                else None,
                "family_adjusted_97_5_ci": interval,
                "minimum_practical_effect": minimum_effect,
                "confirmatory_superiority": bool(
                    phase == "confirmation"
                    and interval is not None
                    and interval[0] > minimum_effect
                ),
            }
        )
    return {
        "primary_comparisons": results,
        "joint_superiority": all(row["confirmatory_superiority"] for row in results),
        "scope": "Synthetic task only. Model-informed stopping benefit is not uniquely a neural/SNN contribution.",
    }


def write_receipt(path, payload):
    """Exclusive bounded writes; a failed final write cannot erase checkpoints."""
    encoded = json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n"
    if len(encoded.encode()) >= 512_000:
        raise ValueError("logical result exceeds reviewable artifact budget")
    with Path(path).open("x") as handle:
        handle.write(encoded)


def run(phase, source_seal=None, *, progress_directory=None, progress=None):
    protocol = json.loads(PROTOCOL_PATH.read_text())
    development = phase == "development"
    source = {"development_only": True} if development else verify(source_seal)
    if not development and progress_directory is None:
        raise ValueError("scientific execution requires incremental evidence storage")
    progress = {} if progress is None else progress
    seeds = (
        protocol["development_seed_namespace"][:1]
        if development
        else protocol[f"{phase}_seeds"]
    )
    dataset = protocol["datasets"]
    oracle = BellmanReference(protocol["bellman_reference"]["belief_grid_points"])
    for domain in ("id", "ood"):
        for context in itertools.product(
            *(
                dataset[f"{domain}_{field}"]
                for field in ("reliability", "cost", "deadline")
            )
        ):
            oracle.profile(*context)
    if progress_directory is not None:
        write_receipt(
            progress_directory / "DP_CACHE.json",
            {
                "context_count": len(oracle.profiles),
                "build_seconds": oracle.build_seconds,
                "timing_policy": "All registered model contexts built before any arm; all later queries warm.",
            },
        )
    records = []
    for seed in seeds:
        batches = {
            split: make_episodes(
                seed,
                split,
                32 if development else dataset[f"{split}_episodes"],
                ood=split == "ood_test",
            )
            for split in ("train", "validation", "id_test", "ood_test")
        }
        row = {
            "seed": seed,
            "data_hashes": {name: value.digest for name, value in batches.items()},
            "arms": {},
            "references": {},
        }
        for method in METHODS:
            for gradient in GRADIENTS:
                key = f"seed_{seed}_{method}_{gradient}"
                progress.update(
                    active_arm=key, stage="training", last_completed_optimizer_step=0
                )
                parameters, fixed, stats = train(
                    seed,
                    method,
                    gradient,
                    batches["train"],
                    batches["validation"],
                    oracle,
                    protocol,
                    steps=2 if development else None,
                    progress=progress,
                )
                arm = {
                    "training": stats,
                    "selected_fixed_thresholds": list(fixed),
                    "checkpoint": {
                        name: value.tolist() for name, value in parameters.items()
                    },
                }
                if progress_directory is not None:
                    write_receipt(
                        progress_directory / f"{key}_checkpoint.json",
                        {
                            "phase": phase,
                            "source": source,
                            "seed": seed,
                            "arm": f"{method}:{gradient}",
                            "data_hashes": row["data_hashes"],
                            **arm,
                        },
                    )
                progress["stage"] = "scoring"
                for split in ("id_test", "ood_test"):
                    arm[split] = score_model(
                        parameters, fixed, method, gradient, batches[split], oracle
                    )
                row["arms"][f"{method}:{gradient}"] = arm
                if progress_directory is not None:
                    write_receipt(
                        progress_directory / f"{key}_scores.json",
                        {split: arm[split] for split in ("id_test", "ood_test")},
                    )
                progress.setdefault("completed_arms", []).append(key)
        for split in ("id_test", "ood_test"):
            row["references"][split] = score_references(batches[split], oracle)
        records.append(row)
        if progress_directory is not None:
            write_receipt(progress_directory / f"seed_{seed}_complete.json", row)
        print(
            json.dumps({"phase": phase, "completed_seed": seed, "arms": 6}), flush=True
        )
    if not development:
        verify(source_seal)
    return {
        "schema": "free-boundary-learning-results-v1",
        "phase": phase,
        "source": source,
        "protocol_sha256": hashlib.sha256(PROTOCOL_PATH.read_bytes()).hexdigest(),
        "protocol": protocol,
        "records": records,
        "DP_build_seconds": oracle.build_seconds,
        "DP_context_count": len(oracle.profiles),
        "DP_timing_policy": "Separately charged upfront build; all arms and references use warm profiles.",
        "DP_resident_numeric_bytes": oracle.grid.nbytes
        + sum(
            value.nbytes
            for profile in oracle.profiles.values()
            for value in profile.values()
            if isinstance(value, np.ndarray)
        ),
        "DP_belief_transition_evaluations": sum(
            2 * (key[2] - 1) * len(oracle.grid) for key in oracle.profiles
        ),
        "DP_work_definition": "Two next-belief interpolation queries per grid state and backward time step; numeric cache bytes exclude Python object overhead.",
        "statistics": paired_analysis(
            records, phase, protocol["minimum_practical_effect"]
        ),
        "claim": "development_smoke_not_scientific_evidence"
        if development
        else "registered_run_not_automatic_superiority",
    }


def audit_results(path, source_seal):
    """Reopen actual checkpoints and regenerate test streams without training."""
    source = verify(source_seal)
    result = json.loads(Path(path).read_text())
    protocol = json.loads(PROTOCOL_PATH.read_text())
    if (
        result["protocol_sha256"]
        != hashlib.sha256(PROTOCOL_PATH.read_bytes()).hexdigest()
    ):
        raise ValueError("protocol differs from the result")
    if result["protocol"] != protocol:
        raise ValueError("embedded protocol differs")
    if (
        result["phase"] != "development"
        and result["source"]["seal_sha256"] != source["seal_sha256"]
    ):
        raise ValueError("result belongs to another source seal")
    expected_seeds = (
        protocol["development_seed_namespace"][:1]
        if result["phase"] == "development"
        else protocol[f"{result['phase']}_seeds"]
    )
    if [row["seed"] for row in result["records"]] != expected_seeds:
        raise ValueError("registered seed roster is incomplete or changed")
    oracle = BellmanReference(protocol["bellman_reference"]["belief_grid_points"])
    checked = 0
    for row in result["records"]:
        if set(row["arms"]) != {
            f"{method}:{gradient}" for method in METHODS for gradient in GRADIENTS
        }:
            raise ValueError("registered arm roster is incomplete or changed")
        validation_count = (
            32
            if result["phase"] == "development"
            else protocol["datasets"]["validation_episodes"]
        )
        validation = make_episodes(row["seed"], "validation", validation_count)
        if validation.digest != row["data_hashes"]["validation"]:
            raise AssertionError("validation dataset differs")
        for key, arm in row["arms"].items():
            method, gradient = key.split(":")
            parameters = {
                name: np.asarray(values, float)
                for name, values in arm["checkpoint"].items()
            }
            initial = initialize(row["seed"], method)
            if set(parameters) != set(initial) or any(
                parameters[k].shape != initial[k].shape for k in initial
            ):
                raise AssertionError("checkpoint architecture differs")
            change = float(
                np.sqrt(sum(np.sum((parameters[k] - initial[k]) ** 2) for k in initial))
            )
            np.testing.assert_allclose(
                change, arm["training"]["parameter_change_l2"], rtol=1e-12, atol=1e-12
            )
            steps = (
                2 if result["phase"] == "development" else protocol["training"]["steps"]
            )
            check_count = 32 if result["phase"] == "development" else 128
            expected_counts = {
                "training_steps": steps,
                "minibatch_size": protocol["training"]["batch_size"],
                "parameter_count": sum(v.size for v in parameters.values()),
                "actual_training_cell_updates": (
                    steps * protocol["training"]["batch_size"] + 2 * check_count
                )
                * 128,
                "optimizer_forward_cell_updates": steps
                * protocol["training"]["batch_size"]
                * 128,
                "diagnostic_forward_cell_updates": 2 * check_count * 128,
                "selection_forward_cell_updates": validation_count * 128
                if method == "fixed"
                else 0,
            }
            if any(
                arm["training"][name] != value
                for name, value in expected_counts.items()
            ):
                raise AssertionError("checkpoint budget/work metadata differs")
            if method == "fixed":
                selected, evaluations = select_fixed(
                    parameters, validation, gradient, protocol
                )
                if list(selected) != arm["selected_fixed_thresholds"]:
                    raise AssertionError(
                        "saved fixed thresholds are not the registered validation selection"
                    )
                if evaluations != arm["training"]["validation_threshold_evaluations"]:
                    raise AssertionError("validation selection work differs")
        for split in ("id_test", "ood_test"):
            count = (
                32
                if result["phase"] == "development"
                else protocol["datasets"][f"{split}_episodes"]
            )
            episodes = make_episodes(row["seed"], split, count, ood=split == "ood_test")
            if episodes.digest != row["data_hashes"][split]:
                raise AssertionError("regenerated dataset differs")
            for key, arm in row["arms"].items():
                method, gradient = key.split(":")
                parameters = {
                    name: np.asarray(values, float)
                    for name, values in arm["checkpoint"].items()
                }
                if parameter_digest(parameters) != arm["training"]["checkpoint_sha256"]:
                    raise AssertionError("checkpoint bytes differ")
                actual = score_model(
                    parameters,
                    arm["selected_fixed_thresholds"],
                    method,
                    gradient,
                    episodes,
                    oracle,
                )
                for metric, expected in arm[split].items():
                    if metric.endswith("_seconds"):
                        continue
                    if isinstance(expected, float):
                        np.testing.assert_allclose(
                            actual[metric], expected, rtol=1e-11, atol=1e-11
                        )
                    elif actual[metric] != expected:
                        raise AssertionError(
                            f"rescoring mismatch: {key}/{split}/{metric}"
                        )
                checked += 1
            references = score_references(episodes, oracle)
            for name, metrics in row["references"][split].items():
                for metric, expected in metrics.items():
                    if (
                        not metric.endswith("_seconds")
                        and references[name][metric] != expected
                    ):
                        raise AssertionError(
                            f"reference rescoring mismatch: {name}/{split}/{metric}"
                        )
    if (
        paired_analysis(
            result["records"], result["phase"], protocol["minimum_practical_effect"]
        )
        != result["statistics"]
    ):
        raise AssertionError("paired statistics differ")
    return {
        "checkpoint_dataset_scores_verified": checked,
        "training_repeated": False,
        "validation_grid_selection_reproduced": True,
        "timing_scope": "wall-clock durations are retained measurements, not numerically reproducible claims",
    }


def execute_attempt(phase, destination, source_seal=None, results=None):
    destination = Path(destination)
    if destination.exists():
        raise FileExistsError(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    directory = destination.with_name(destination.stem + "_checkpoints")
    directory.mkdir(exist_ok=False)
    started, cpu = time.perf_counter(), time.process_time()
    state = {"phase": phase, "completed_arms": [], "stage": "initial_verification"}
    write_receipt(
        directory / "ATTEMPT_START.json",
        {
            "phase": phase,
            "source_seal": str(source_seal),
            "protocol_sha256": hashlib.sha256(PROTOCOL_PATH.read_bytes()).hexdigest(),
        },
    )
    try:
        output = (
            audit_results(results, source_seal)
            if phase == "audit"
            else run(phase, source_seal, progress_directory=directory, progress=state)
        )
        state["stage"] = "writing_final_result"
        write_receipt(destination, output)
        write_receipt(
            directory / "ATTEMPT_COMPLETE.json",
            {
                "result_sha256": hashlib.sha256(destination.read_bytes()).hexdigest(),
                "wall_seconds": time.perf_counter() - started,
                "cpu_seconds": time.process_time() - cpu,
            },
        )
        return output
    except BaseException as error:
        write_receipt(
            directory / "INVALID_ATTEMPT.json",
            {
                **state,
                "error_type": type(error).__name__,
                "error": str(error),
                "wall_seconds": time.perf_counter() - started,
                "cpu_seconds": time.process_time() - cpu,
                "completed_evidence_retained": True,
            },
        )
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--phase",
        choices=("development", "screening", "confirmation", "audit"),
        required=True,
    )
    parser.add_argument("--source-seal", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--results", type=Path)
    args = parser.parse_args()
    if args.phase != "development" and args.source_seal is None:
        parser.error("scientific runs and audit require a committed source seal")
    execute_attempt(args.phase, args.output, args.source_seal, args.results)
    print(json.dumps({"output": str(args.output), "bytes": args.output.stat().st_size}))


if __name__ == "__main__":
    main()
