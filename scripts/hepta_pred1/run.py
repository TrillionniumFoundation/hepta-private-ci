"""Reproducible CPU PRED-1 experiment; execute with python -m hepta_pred1.run.

Confirmation data are generated only after every checkpoint and the family
selection have been frozen using training/development data. A campaign output
directory is create-only; interrupted/failed attempts are never overwritten.
"""

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import itertools
import json
from pathlib import Path
import platform
import time

import numpy as np

from .evaluation import evaluate
from .models import Model, matched_hidden_dim
from .simulator import ACTION_DIM, INPUT_DIM, generate_dataset


VARIANTS = {
    "single_step": ("single_step", False, False),
    "gru": ("gru", False, False),
    "diag_ssm": ("diag_ssm", False, False),
    "dual_timescale": ("dual_timescale", False, False),
    "gru_reset": ("gru", True, False),
    "gru_no_action": ("gru", False, True),
}


def canonical(value):
    return json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n"


def write_json(path, value):
    Path(path).write_text(canonical(value), encoding="utf-8")


def source_identity():
    files = {
        p.name: sha256(p.read_bytes()).hexdigest()
        for p in sorted(Path(__file__).parent.glob("*.py"))
    }
    return {"files": files, "sha256": sha256(canonical(files).encode()).hexdigest()}


def inputs(dataset, no_action):
    if not no_action:
        return dataset.x, dataset.query
    x, query = dataset.x.copy(), dataset.query.copy()
    x[:, :, :3] = 0
    query[:, :4] = 0  # Preserve horizon identity in the action ablation.
    return x, query


def train_one(config, variant, seed, train, dev, out):
    kind, reset, no_action = VARIANTS[variant]
    hidden = matched_hidden_dim(
        kind, INPUT_DIM, ACTION_DIM, 32, config["target_parameters"]
    )
    model = Model(kind, INPUT_DIM, ACTION_DIM, 32, hidden, seed)
    x, query = inputs(train, no_action)
    dx, dq = inputs(dev, no_action)
    rng = np.random.default_rng(seed + 911)
    best, best_epoch, curve = np.inf, None, []
    checkpoint = None
    wall, cpu = time.perf_counter(), time.process_time()
    for epoch in range(config["epochs"]):
        order = rng.permutation(len(x))
        losses = []
        for start in range(0, len(order), config["batch_size"]):
            batch = order[start : start + config["batch_size"]]
            loss = model.fit_step(
                x[batch],
                query[batch],
                train.allowed[batch],
                lr=config["learning_rate"],
                reset=reset,
            )
            losses.append((loss, len(batch)))
        logits = model.forward(dx, dq, reset=reset)
        dev_loss = float(
            (
                np.logaddexp.reduce(logits, axis=1)
                - np.logaddexp.reduce(np.where(dev.allowed, logits, -np.inf), axis=1)
            ).mean()
        )
        curve.append(
            {
                "epoch": epoch + 1,
                "train_nll": sum(a * b for a, b in losses) / len(x),
                "dev_observed_nll": dev_loss,
            }
        )
        if dev_loss < best:
            best, best_epoch = dev_loss, epoch + 1
            checkpoint = out / f"{variant}-{seed}-epoch-{epoch + 1}.npz"
            model.save(checkpoint)
    elapsed, consumed = time.perf_counter() - wall, time.process_time() - cpu
    fitted = Model.load(checkpoint)
    dev_metrics, _ = evaluate(fitted, dev, reset=reset, mask_candidate_action=no_action)
    record = {
        "variant": variant,
        "seed": seed,
        "parameters": model.parameter_count,
        "hidden_dim": hidden,
        "best_epoch": best_epoch,
        "epochs_consumed": config["epochs"],
        "optimizer_steps_consumed": model.steps,
        "selected_checkpoint_steps": fitted.steps,
        "training_examples_consumed": config["epochs"] * len(x),
        "train_wall_seconds": elapsed,
        "train_process_cpu_seconds": consumed,
        "checkpoint": checkpoint.name,
        "checkpoint_sha256": sha256(checkpoint.read_bytes()).hexdigest(),
        "curve": curve,
        "dev": dev_metrics,
        "metering": {
            "energy_joules": None,
            "financial_cost": None,
            "physical_cost_complete": False,
        },
    }
    write_json(out / f"{variant}-{seed}-training.json", record)
    return record


def paired_statistics(differences):
    """Seed-level exploratory inference; episodes are not independent trainings."""
    values = np.asarray(differences, dtype=float)
    if (
        values.ndim != 1
        or len(values) < 2
        or len(values) > 16
        or not np.isfinite(values).all()
    ):
        raise ValueError("need 2..16 finite independent training-seed differences")
    observed = values.mean()
    flipped = [
        np.mean(values * signs)
        for signs in itertools.product((-1, 1), repeat=len(values))
    ]
    # Exact only under the paired sign-exchangeability null. No normality claim.
    p = float(np.mean(np.array(flipped) >= observed - 1e-14))
    rng = np.random.default_rng(61257)
    means = values[rng.integers(len(values), size=(10_000, len(values)))].mean(axis=1)
    return {
        "independent_seed_count": len(values),
        "mean_difference": float(observed),
        "seed_differences": values.tolist(),
        "one_sided_signflip_p": p,
        "descriptive_seed_bootstrap_95": np.quantile(means, [0.025, 0.975]).tolist(),
        "inference_scope": "exploratory; sign-exchangeability assumed; small-seed CI is descriptive",
    }


def run(config, output):
    seeds = config["seeds"]
    selection_seeds = config["selection_seeds"]
    if len(set(seeds)) != len(seeds) or not 2 <= len(seeds) <= 16:
        raise ValueError("need 2..16 unique independent seeds")
    if not all(isinstance(s, int) and s >= 0 for s in seeds):
        raise ValueError("nonnegative integer seeds required")
    if (
        not 1 <= len(selection_seeds) <= 16
        or len(set(selection_seeds)) != len(selection_seeds)
        or set(selection_seeds) & set(seeds)
        or not all(isinstance(s, int) and s >= 0 for s in selection_seeds)
    ):
        raise ValueError(
            "family-selection seeds must be unique and disjoint from evaluation training seeds"
        )
    if not 1 <= config["epochs"] <= 500 or not 1 <= config["batch_size"] <= 4096:
        raise ValueError("invalid training budget")
    if not 128 <= config["target_parameters"] <= 100_000:
        raise ValueError("invalid model budget")
    out = Path(output)
    out.mkdir(parents=True, exist_ok=False)
    started = datetime.now(timezone.utc).isoformat()
    identity = source_identity()
    attempt = {
        "schema": "pred1-campaign-v1",
        "started_at": started,
        "status": "running",
        "base_commit": config["base_commit"],
        "source": identity,
        "config_sha256": sha256(canonical(config).encode()).hexdigest(),
        "environment": {
            "python": platform.python_version(),
            "numpy": np.__version__,
            "platform": platform.platform(),
        },
        "config": config,
        "scope": "finite simulator; fixed preparation-option forecast; no real external effects",
    }
    write_json(out / "attempt.json", attempt)
    snapshot = out / "source"
    snapshot.mkdir()
    for path in Path(__file__).parent.glob("*.py"):
        (snapshot / path.name).write_bytes(path.read_bytes())
    start_wall, start_cpu = time.perf_counter(), time.process_time()
    records, datasets, selection_records = [], {}, []
    selected, family_selection = None, None
    try:
        for seed in selection_seeds + seeds:
            data_wall, data_cpu = time.perf_counter(), time.process_time()
            train = generate_dataset(
                config["train_episodes"], seed, "train", config["history_length"]
            )
            dev = generate_dataset(
                config["dev_episodes"], seed, "dev", config["history_length"]
            )
            if set(train.groups) & set(dev.groups):
                raise AssertionError("train/dev source group overlap")
            datasets[str(seed)] = {
                "train": {
                    "sha256": train.fingerprint(),
                    "episodes": len(train.x),
                    "observation_counts": train.observation_counts,
                },
                "dev": {"sha256": dev.fingerprint(), "episodes": len(dev.x)},
                "generation_wall_seconds": time.perf_counter() - data_wall,
                "generation_process_cpu_seconds": time.process_time() - data_cpu,
            }
            for variant in VARIANTS:
                print(
                    json.dumps({"phase": "training", "seed": seed, "variant": variant}),
                    flush=True,
                )
                record = train_one(config, variant, seed, train, dev, out)
                records.append(record)
                if seed in selection_seeds:
                    selection_records.append(record)
                print(
                    json.dumps(
                        {
                            "phase": "trained",
                            "seed": seed,
                            "variant": variant,
                            "dev": record["dev"],
                        }
                    ),
                    flush=True,
                )
            if seed == selection_seeds[-1]:
                families = ("gru", "diag_ssm", "dual_timescale")
                dev_values = {
                    v: float(
                        np.mean(
                            [
                                r["dev"]["net_utility"]
                                for r in selection_records
                                if r["variant"] == v
                            ]
                        )
                    )
                    for v in families
                }
                selected = max(families, key=lambda name: (dev_values[name], name))
                family_selection = {
                    "selected_family": selected,
                    "selection_seeds": selection_seeds,
                    "evaluation_training_seeds": seeds,
                    "dev_net_utility": dev_values,
                    "frozen_at": datetime.now(timezone.utc).isoformat(),
                    "frozen_before_evaluation_training": True,
                }
                write_json(out / "family-selection.json", family_selection)
        selection = {
            "selected_family": selected,
            "dev_net_utility": dev_values,
            "independent_family_selection": family_selection,
            "selected_before_confirmation_generation": True,
            "checkpoint_sha256": {
                r["checkpoint"]: r["checkpoint_sha256"] for r in records
            },
            "frozen_at": datetime.now(timezone.utc).isoformat(),
        }
        write_json(out / "selection.json", selection)
        confirmation = []
        for seed in seeds:
            test = generate_dataset(
                config["confirm_episodes"], seed, "confirm", config["history_length"]
            )
            datasets[str(seed)]["confirm"] = {
                "sha256": test.fingerprint(),
                "episodes": len(test.x),
            }
            for variant, (_, reset, no_action) in VARIANTS.items():
                trained = next(
                    r for r in records if r["variant"] == variant and r["seed"] == seed
                )
                checkpoint = out / trained["checkpoint"]
                if (
                    sha256(checkpoint.read_bytes()).hexdigest()
                    != selection["checkpoint_sha256"][checkpoint.name]
                ):
                    raise AssertionError("checkpoint changed after selection")
                model = Model.load(checkpoint)
                metrics, per_episode = evaluate(
                    model, test, reset=reset, mask_candidate_action=no_action
                )
                record = {"seed": seed, "variant": variant, **metrics}
                confirmation.append(record)
                write_json(out / f"{variant}-{seed}-confirm.json", record)
                with (out / f"{variant}-{seed}-episodes.npz").open("wb") as stream:
                    np.savez_compressed(stream, **per_episode)
        lookup = {(r["variant"], r["seed"]): r for r in confirmation}
        comparisons = {}
        for baseline in ("single_step", "gru_reset", "gru_no_action"):
            comparisons[baseline] = paired_statistics(
                [
                    lookup[selected, seed]["net_utility"]
                    - lookup[baseline, seed]["net_utility"]
                    for seed in seeds
                ]
            )
        # Matched-architecture ablations are always GRU vs GRU, even if a different
        # family wins development. Cross-family contrasts cannot isolate memory.
        causal_checks = {
            baseline: paired_statistics(
                [
                    lookup["gru", seed]["net_utility"]
                    - lookup[baseline, seed]["net_utility"]
                    for seed in seeds
                ]
            )
            for baseline in ("gru_reset", "gru_no_action")
        }
        primary = comparisons["single_step"]
        gain = (
            primary["mean_difference"] >= config["practical_utility_gain"]
            and primary["one_sided_signflip_p"] <= 0.05
        )
        summary = {
            "schema": "pred1-results-v1",
            "status": "simulation_gain_observed"
            if gain
            else "simulation_gain_not_established",
            "selected_family": selected,
            "selection": selection,
            "primary_comparison": comparisons["single_step"],
            "selected_family_auxiliary_comparisons": comparisons,
            "same_architecture_causal_checks": causal_checks,
            "confirm_by_seed": confirmation,
            "datasets": datasets,
            "source_sha256": identity["sha256"],
            "config_sha256": attempt["config_sha256"],
            "measured_campaign_wall_seconds": time.perf_counter() - start_wall,
            "measured_campaign_process_cpu_seconds": time.process_time() - start_cpu,
            "all_training_wall_seconds": sum(r["train_wall_seconds"] for r in records),
            "all_training_process_cpu_seconds": sum(
                r["train_process_cpu_seconds"] for r in records
            ),
            "selection_training_wall_seconds": sum(
                r["train_wall_seconds"] for r in selection_records
            ),
            "independent_family_selection_training_seeds": selection_seeds,
            "independent_evaluation_training_seeds": seeds,
            "physical_cost_complete": False,
            "real_tool_qualification": "not_run",
            "hcsn_comparison": "not_run",
            "autoregressive_rollout_qualification": "not_run",
            "scientific_scope": "controlled simulation only; exploratory seed inference; no RSI conclusion",
        }
        if source_identity() != identity:
            raise RuntimeError("source changed while campaign was running")
        write_json(out / "summary.json", summary)
        attempt["status"] = "completed"
    except BaseException as error:
        attempt["status"] = "failed"
        attempt["error"] = f"{type(error).__name__}: {error}"
        raise
    finally:
        attempt["finished_at"] = datetime.now(timezone.utc).isoformat()
        write_json(out / "attempt.json", attempt)
        manifest = {
            str(p.relative_to(out)): {
                "sha256": sha256(p.read_bytes()).hexdigest(),
                "bytes": p.stat().st_size,
            }
            for p in sorted(out.rglob("*"))
            if p.is_file() and p.name != "manifest.json"
        }
        write_json(out / "manifest.json", manifest)
    print(
        json.dumps(
            {
                "status": summary["status"],
                "selected_family": selected,
                "primary": summary["primary_comparison"],
            }
        ),
        flush=True,
    )
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run(json.loads(args.config.read_text(encoding="utf-8")), args.output)
