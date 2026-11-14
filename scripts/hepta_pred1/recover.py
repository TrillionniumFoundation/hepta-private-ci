"""Rebuild only the exact bytes of a previously frozen PRED-1 checkpoint.

An original failed attempt is immutable. A newly trained checkpoint is accepted
only if its complete SHA-256 equals the original pre-confirmation commitment.
Recovery adds costs, never independent seeds, model selection or tuning.
"""

import argparse
import ast
from datetime import datetime
from hashlib import sha256
import json
from pathlib import Path
import time

import numpy as np

from .evaluation import evaluate
from .models import Model
from .run import (
    VARIANTS,
    canonical,
    paired_statistics,
    source_identity,
    train_one,
    write_json,
)
from .simulator import generate_dataset


def file_sha(path):
    return sha256(Path(path).read_bytes()).hexdigest()


def verify_manifest(root):
    manifest = json.loads((root / "manifest.json").read_text())
    for name, metadata in manifest.items():
        path = root / name
        if not path.resolve().is_relative_to(root.resolve()) or path.is_symlink():
            raise ValueError("manifest path escapes original attempt")
        if (
            file_sha(path) != metadata["sha256"]
            or path.stat().st_size != metadata["bytes"]
        ):
            raise ValueError(f"original manifest no longer matches: {name}")
    return manifest


def _model_semantics(path):
    tree = ast.parse(path.read_text())
    model = next(
        n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "Model"
    )
    return {
        n.name: ast.dump(n, include_attributes=False)
        for n in model.body
        if isinstance(n, ast.FunctionDef) and n.name != "save"
    }


def _without_timers(value):
    if isinstance(value, dict):
        return {
            k: _without_timers(v)
            for k, v in value.items()
            if not k.endswith("_seconds")
        }
    if isinstance(value, list):
        return [_without_timers(v) for v in value]
    return value


def accept_checkpoint(source, expected_sha, destination):
    """Publish immutable content-addressed bytes, refusing a replacement model."""
    data = Path(source).read_bytes()
    if sha256(data).hexdigest() != expected_sha:
        raise ValueError("rebuilt checkpoint differs from original frozen SHA")
    target = destination / (expected_sha + ".npz")
    if target.exists():
        if file_sha(target) != expected_sha:
            raise ValueError("immutable checkpoint path has changed")
    else:
        with target.open("xb") as stream:
            stream.write(data)
            stream.flush()
            __import__("os").fsync(stream.fileno())
    if file_sha(target) != expected_sha:
        raise ValueError("immutable checkpoint readback failed")
    return target


def recover(original, output):
    old, out = Path(original).resolve(), Path(output).resolve()
    if out.is_relative_to(old):
        raise ValueError("recovery output must be outside the immutable failed attempt")
    original_manifest = verify_manifest(old)
    original_attempt = json.loads((old / "attempt.json").read_text())
    if (
        original_attempt["status"] != "failed"
        or original_attempt.get("error")
        != "AssertionError: checkpoint changed after selection"
    ):
        raise ValueError(
            "only the retained checkpoint-integrity failure can be recovered"
        )
    config = original_attempt["config"]
    if (
        sha256(canonical(config).encode()).hexdigest()
        != original_attempt["config_sha256"]
    ):
        raise ValueError("original configuration changed")
    for name, digest in original_attempt["source"]["files"].items():
        if file_sha(old / "source" / name) != digest:
            raise ValueError("original source snapshot changed")
    current = Path(__file__).parent
    for name in ("contracts.py", "simulator.py", "evaluation.py"):
        if file_sha(current / name) != file_sha(old / "source" / name):
            raise ValueError("data, observation or evaluation semantics changed")
    if _model_semantics(current / "models.py") != _model_semantics(
        old / "source/models.py"
    ):
        raise ValueError("model or optimizer semantics changed")
    selection = json.loads((old / "selection.json").read_text())
    family = json.loads((old / "family-selection.json").read_text())
    if (
        not family["frozen_before_evaluation_training"]
        or not selection["selected_before_confirmation_generation"]
        or family["selected_family"] != selection["selected_family"]
        or set(config["seeds"]) & set(config["selection_seeds"])
    ):
        raise ValueError("invalid original selection barrier")
    records = [json.loads(p.read_text()) for p in sorted(old.glob("*-training.json"))]
    index = {(r["variant"], r["seed"]): r for r in records}
    expected_pairs = {
        (v, s) for v in VARIANTS for s in config["selection_seeds"] + config["seeds"]
    }
    if set(index) != expected_pairs or len(records) != len(index):
        raise ValueError("original training denominator is incomplete")
    commitments = selection["checkpoint_sha256"]
    if len(commitments) != len(records):
        raise ValueError("checkpoint commitment denominator is incomplete")
    for record in records:
        if commitments.get(record["checkpoint"]) != record["checkpoint_sha256"]:
            raise ValueError("training record does not match the original freeze")
    out.mkdir(parents=True, exist_ok=False)
    (out / "checkpoints").mkdir()
    (out / "source").mkdir()
    identity = source_identity()
    for path in current.glob("*.py"):
        (out / "source" / path.name).write_bytes(path.read_bytes())
    attempt = {
        "schema": "pred1-recovery-v1",
        "status": "running",
        "original_attempt_sha256": file_sha(old / "attempt.json"),
        "original_manifest_sha256": file_sha(old / "manifest.json"),
        "original_source_sha256": original_attempt["source"]["sha256"],
        "source": identity,
        "config": config,
        "config_sha256": original_attempt["config_sha256"],
        "original_status": "failed",
        "acceptance": "exact_original_checkpoint_SHA_only",
    }
    write_json(out / "attempt.json", attempt)
    wall, cpu = time.perf_counter(), time.process_time()
    repairs, adopted, replayed, confirmation, datasets = [], {}, [], [], {}
    try:
        for record in records:
            name, expected = record["checkpoint"], record["checkpoint_sha256"]
            if Path(name).name != name:
                raise ValueError("checkpoint name is not a basename")
            source = old / name
            if file_sha(source) != expected:
                seed, variant = record["seed"], record["variant"]
                repair_dir = out / f"repair-{variant}-{seed}"
                repair_dir.mkdir()
                print(
                    json.dumps(
                        {
                            "phase": "rebuild_exact_bytes",
                            "variant": variant,
                            "seed": seed,
                        }
                    ),
                    flush=True,
                )
                train = generate_dataset(
                    config["train_episodes"], seed, "train", config["history_length"]
                )
                dev = generate_dataset(
                    config["dev_episodes"], seed, "dev", config["history_length"]
                )
                repaired = train_one(config, variant, seed, train, dev, repair_dir)
                source = repair_dir / repaired["checkpoint"]
                if repaired["checkpoint_sha256"] != expected:
                    raise ValueError(
                        "deterministic reconstruction did not recover the frozen bytes"
                    )
                repairs.append(
                    {
                        "variant": variant,
                        "seed": seed,
                        "frozen_sha256": expected,
                        "original_file_sha256": file_sha(old / name),
                        "repair_record": repaired,
                        "original_logical_checkpoint": name,
                    }
                )
            target = accept_checkpoint(source, expected, out / "checkpoints")
            adopted[record["variant"], record["seed"]] = target
        write_json(
            out / "recovery-freeze.json",
            {
                "original_selection": selection,
                "original_family_selection": family,
                "repaired_checkpoints": [
                    {k: v for k, v in r.items() if k != "repair_record"}
                    for r in repairs
                ],
                "adopted": {f"{v}:{s}": p.name for (v, s), p in adopted.items()},
            },
        )
        for seed in config["seeds"]:
            test = generate_dataset(
                config["confirm_episodes"], seed, "confirm", config["history_length"]
            )
            datasets[str(seed)] = {
                "confirm_sha256": test.fingerprint(),
                "episodes": len(test.x),
            }
            for variant, (_, reset, no_action) in VARIANTS.items():
                model_path = adopted[variant, seed]
                if file_sha(model_path) != model_path.stem:
                    raise ValueError("adopted checkpoint changed before evaluation")
                metrics, episodes = evaluate(
                    Model.load(model_path),
                    test,
                    reset=reset,
                    mask_candidate_action=no_action,
                )
                result = {"seed": seed, "variant": variant, **metrics}
                name = f"{variant}-{seed}"
                prior = old / (name + "-confirm.json")
                if prior.exists():
                    if _without_timers(
                        json.loads(prior.read_text())
                    ) != _without_timers(result):
                        raise ValueError(
                            "original confirmation metrics did not replay exactly"
                        )
                    with np.load(
                        old / (name + "-episodes.npz"), allow_pickle=False
                    ) as archived:
                        if set(archived.files) != set(episodes) or any(
                            not np.array_equal(archived[key], value)
                            for key, value in episodes.items()
                        ):
                            raise ValueError(
                                "original confirmation episodes did not replay exactly"
                            )
                    replayed.append(name)
                write_json(out / (name + "-confirm.json"), result)
                with (out / (name + "-episodes.npz")).open("xb") as stream:
                    np.savez_compressed(stream, **episodes)
                confirmation.append(result)
        prior_confirm = [json.loads(p.read_text()) for p in old.glob("*-confirm.json")]
        if len(prior_confirm) != len(replayed):
            raise ValueError("not all prior confirmations were reconciled")
        selected = selection["selected_family"]
        lookup = {(r["variant"], r["seed"]): r for r in confirmation}
        comparisons = {
            baseline: paired_statistics(
                [
                    lookup[selected, seed]["net_utility"]
                    - lookup[baseline, seed]["net_utility"]
                    for seed in config["seeds"]
                ]
            )
            for baseline in ("single_step", "gru_reset", "gru_no_action")
        }
        causal = {
            baseline: paired_statistics(
                [
                    lookup["gru", seed]["net_utility"]
                    - lookup[baseline, seed]["net_utility"]
                    for seed in config["seeds"]
                ]
            )
            for baseline in ("gru_reset", "gru_no_action")
        }
        primary = comparisons["single_step"]
        signal = (
            primary["mean_difference"] >= config["practical_utility_gain"]
            and primary["one_sided_signflip_p"] <= 0.05
        )
        repair_records = [r["repair_record"] for r in repairs]
        all_training = records + repair_records
        duration = (
            datetime.fromisoformat(original_attempt["finished_at"])
            - datetime.fromisoformat(original_attempt["started_at"])
        ).total_seconds()
        summary = {
            "schema": "pred1-recovered-results-v1",
            "recovery_status": "exact_frozen_bytes_recovered",
            "status": "simulation_gain_observed"
            if signal
            else "simulation_gain_not_established",
            "selected_family": selected,
            "primary_comparison": primary,
            "selected_family_auxiliary_comparisons": comparisons,
            "same_architecture_causal_checks": causal,
            "confirm_by_seed": confirmation,
            "datasets": datasets,
            "selection": selection,
            "recovered_from_failed_attempt": True,
            "original_attempt_status": "failed",
            "original_training_instances": len(records),
            "repair_training_instances": len(repairs),
            "replayed_confirmation_instances": len(replayed),
            "independent_evaluation_training_seeds": config["seeds"],
            "independent_family_selection_training_seeds": config["selection_seeds"],
            "all_training_wall_seconds": sum(
                r["train_wall_seconds"] for r in all_training
            ),
            "all_training_process_cpu_seconds": sum(
                r["train_process_cpu_seconds"] for r in all_training
            ),
            "all_training_examples_consumed": sum(
                r["training_examples_consumed"] for r in all_training
            ),
            "original_attempt_elapsed_wall_seconds": duration,
            "recovery_wall_seconds": time.perf_counter() - wall,
            "recovery_process_cpu_seconds": time.process_time() - cpu,
            "prior_confirmation_inference_cpu_seconds": sum(
                r["inference_process_cpu_seconds"] for r in prior_confirm
            ),
            "new_confirmation_inference_cpu_seconds": sum(
                r["inference_process_cpu_seconds"] for r in confirmation
            ),
            "original_total_process_cpu_seconds": None,
            "physical_cost_complete": False,
            "real_tool_qualification": "not_run",
            "hcsn_comparison": "not_run",
            "autoregressive_rollout_qualification": "not_run",
            "original_source_sha256": original_attempt["source"]["sha256"],
            "source_sha256": identity["sha256"],
            "config_sha256": attempt["config_sha256"],
            "scope": "fixed preparation-option simulator; exploratory seed inference; no RSI conclusion",
        }
        if source_identity() != identity or verify_manifest(old) != original_manifest:
            raise ValueError("source or original attempt changed during recovery")
        write_json(out / "summary.json", summary)
        attempt["status"] = "completed"
    except BaseException as error:
        attempt["status"] = "failed"
        attempt["error"] = f"{type(error).__name__}: {error}"
        raise
    finally:
        attempt["elapsed_wall_seconds"] = time.perf_counter() - wall
        attempt["process_cpu_seconds"] = time.process_time() - cpu
        write_json(out / "attempt.json", attempt)
        manifest = {
            str(p.relative_to(out)): {"sha256": file_sha(p), "bytes": p.stat().st_size}
            for p in sorted(out.rglob("*"))
            if p.is_file() and p.name != "manifest.json"
        }
        write_json(out / "manifest.json", manifest)
    print(
        json.dumps(
            {"status": summary["status"], "primary": primary, "repairs": len(repairs)}
        ),
        flush=True,
    )
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--original", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    recover(args.original, args.output)
