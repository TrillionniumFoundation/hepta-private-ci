"""Post-seal read-only audit of paid reads, stopping values, native evidence.

This analysis never trains or selects a policy. Every completed planned actor
seed and every recorded policy episode are checked. Optional actor replay is
performed only after training ends, outside inference latency measurements.
"""

import argparse
import json
from pathlib import Path
import sys
import time
import traceback

import numpy as np
from scipy.special import expit

from online_audit_common import (
    canonical,
    check,
    close,
    read_arrays,
    read_traces,
    regenerate_episodes,
    sha,
)
from online_episode_audit import MODES, audit_record, recompute_metrics
from online_state_audit import audit_python_replay, checkpoint_model_digest


def audit_seed(directory, protocol, base_results, replay_neural, tables):
    result = json.loads((directory / "RESULT.json").read_text())
    start = json.loads((directory / "START.json").read_text())
    policy = json.loads((directory / "POLICY.json").read_text())
    seed = result["seed"]
    check(
        start["seed"] == seed and start["protocol"] == protocol,
        "frozen online protocol",
    )
    check(start["source_seals"] == result["source_seals"], "source seal identity")
    check(
        result["policy_fit"] == policy
        and sha(directory / "POLICY.json") == result["policy_sha256"],
        "policy fit identity",
    )
    check(
        0.25 <= policy["temperature"] <= 4 and policy["temperature_updates"] == 100,
        "shared train-only temperature contract",
    )
    check(
        policy["direct"]["updates"] == protocol["direct_updates"],
        "direct update contract",
    )
    check(
        sha(directory / "episodes/manifest.json") == result["episode_manifest_sha256"],
        "episode evidence identity",
    )
    expected_objective = canonical(
        {
            "correct_reward": 1.0,
            "cost": "all purchased observations",
            "force_first_observation": True,
            "protocol": protocol,
        }
    )
    check(
        result["objective_sha256"] == expected_objective,
        "shared task objective identity",
    )
    actor = Path(base_results) / "boundary" / f"seed{seed}" / "actor_checkpoint"
    historical = json.loads((actor.parent / "RESULT.json").read_text())
    check(
        sha(actor.parent / "RESULT.json") == start["historical_actor_result_sha256"],
        "historical actor result identity",
    )
    check(
        historical["actor"]["training_cpu_seconds"]
        == start["historical_actor_training_cpu_seconds"],
        "historical actor training cost is retained",
    )
    check(
        checkpoint_model_digest(actor)
        == result["actor_model_sha256"]
        == start["actor_model_sha256"],
        "independent actor byte/config binding",
    )
    check(
        sha(actor / "manifest.json")
        == result["actor_manifest_sha256"]
        == start["actor_manifest_sha256"],
        "shared historical actor identity",
    )
    model, torch, StreamingClassifier = None, None, None
    if replay_neural:
        import torch
        from experiments.continuous_spiking_network.models import SequenceClassifier
        from experiments.continuous_spiking_network.records import checkpoint_load
        from experiments.continuous_spiking_followup.streaming import (
            StreamingClassifier,
            model_digest,
        )

        torch.set_num_threads(1)
        model = SequenceClassifier(
            **json.loads((actor / "manifest.json").read_text())["config"]
        )
        checkpoint_load(model, actor)
        model.eval()
        check(
            model_digest(model) == result["actor_model_sha256"],
            "actor tensor/config digest",
        )
    arrays, summary, value_errors = read_arrays(directory / "episodes"), {}, []
    counts = {
        "python_policy_episodes": 0,
        "native_policy_episodes": 0,
        "replayed_full_actor_episodes": 0,
        "replayed_full_actor_steps": 0,
    }
    for split, prefix, offset in (("id", "train", 303), ("ood", "ood", 404)):
        horizon = protocol[prefix + "_horizon"]
        count = protocol["test_" + split + "_size"]
        generated = regenerate_episodes(
            count,
            horizon,
            protocol[prefix + "_snr"],
            protocol[prefix + "_cost"],
            seed + protocol["new_episode_seed_offset"] + offset,
            split,
        )
        data = {
            key.removeprefix(split + "_"): value
            for key, value in arrays.items()
            if key.startswith(split + "_")
        }
        check(set(data) == set(generated), "complete episode array inventory")
        for key in generated:
            check(
                np.array_equal(data[key], generated[key]),
                f"independently regenerated {split}/{key}",
            )
        rows = {
            mode: read_traces(directory, result["trace_files"][split][mode])
            for mode in MODES
        }
        check(
            all(len(values) == count for values in rows.values()),
            "all policy episodes present",
        )
        summary[split] = {"policies": {}, "native": {}}
        for mode, values in rows.items():
            for index, record in enumerate(values):
                value_errors += audit_record(
                    record,
                    mode,
                    str(data["episode_id"][index]),
                    float(data["snr"][index]),
                    float(data["cost"][index]),
                    horizon,
                    policy,
                    tables,
                )
                full_trace = rows["full"][index]["trace"]
                for tick in record["trace"]:
                    counterpart = full_trace[tick["step"] - 1]
                    check(
                        tick["logits"] == counterpart["logits"],
                        "same actor causal prefix across policy arms",
                    )
                    check(
                        tick["natural_margin_mean"]
                        == counterpart["natural_margin_mean"]
                        and tick["event_activity_mean"]
                        == counterpart["event_activity_mean"],
                        "same neural dynamics across policy arms",
                    )
            calculated = recompute_metrics(values, data["label"])
            for key, value in calculated.items():
                close(
                    result["metrics"][split][mode][key],
                    value,
                    f"recomputed {split}/{mode}/{key}",
                )
            summary[split]["policies"][mode] = calculated
            counts["python_policy_episodes"] += len(values)
        for index, record in enumerate(rows["full"]):
            check(
                record["observations"] == horizon
                and record["avoided_model_steps"] == 0,
                "full-horizon reference",
            )
            if replay_neural:
                stream = StreamingClassifier(model).reset(1)
                for t, tick in enumerate(record["trace"]):
                    logits, aux = stream.step(
                        torch.from_numpy(data["x"][index : index + 1, t]),
                        torch.from_numpy(data["dt"][index : index + 1, t]),
                    )
                    check(
                        logits[0].tolist() == tick["logits"],
                        "exact actor replay on complete heldout trajectory",
                    )
                    check(
                        float(aux["margin"].mean()) == tick["natural_margin_mean"]
                        and float(aux["event_probability"].mean())
                        == tick["event_activity_mean"],
                        "exact natural margin/activity replay",
                    )
                    counts["replayed_full_actor_steps"] += 1
                counts["replayed_full_actor_episodes"] += 1
        for mode in ("fixed", "direct", "value"):
            receipt = result["replays"][split][mode]
            if rows[mode][0]["observations"] == 1:
                check(
                    receipt["status"] == "already_stopped_after_first_read"
                    and receipt["steps_replayed"] == 0,
                    "legitimate empty Python continuation",
                )
            else:
                check(
                    receipt["status"] == "exact_in_process_serialized_replay"
                    and receipt["max_logit_error"] == 0,
                    "in-process serialized task replay",
                )
                check(
                    receipt["steps_replayed"] == rows[mode][0]["observations"] - 1,
                    "replayed remainder length",
                )
                audit_python_replay(
                    directory / "replay" / split / mode,
                    receipt,
                    rows[mode][0],
                    data["x"][0],
                    data["dt"][0],
                    policy,
                    result,
                )
        full_odds = np.array(
            [[tick["raw_log_odds"] for tick in row["trace"]] for row in rows["full"]]
        )
        calibration = {}
        for name, odds in (
            ("raw", full_odds),
            ("shared_temperature", full_odds / policy["temperature"]),
        ):
            target = data["label"][:, None]
            calibration[name] = {
                "prefix_ce": float(np.mean(np.logaddexp(0, odds) - target * odds)),
                "prefix_brier": float(np.mean((expit(odds) - target) ** 2)),
            }
            for key, value in calibration[name].items():
                close(
                    result["metrics"][split]["calibration"][name][key],
                    value,
                    "heldout calibration arithmetic",
                    atol=2e-6,
                )
        summary[split]["calibration"] = calibration
        if seed == protocol["native"]["actor_seed"]:
            from audit_native_online import audit_native_record

            n = protocol["native"]["episodes_per_split_policy"]
            for mode in ("fixed", "direct", "value"):
                receipt = result["native"][split][mode]
                native_rows = read_traces(directory, receipt["records"])
                check(len(native_rows) == n, "native subset inventory")
                native_checks = []
                for index, record in enumerate(native_rows):
                    episode_id = f"study002.{seed}.{split}.{mode}.{index:03d}"
                    value_errors += audit_record(
                        record,
                        mode,
                        episode_id,
                        float(data["snr"][index]),
                        float(data["cost"][index]),
                        horizon,
                        policy,
                        tables,
                        native=True,
                    )
                    for tick in record["trace"]:
                        check(
                            tick["logits"]
                            == rows["full"][index]["trace"][tick["step"] - 1]["logits"],
                            "native task uses the same causal neural actor",
                        )
                    check(
                        record["reference_python_observations"]
                        == rows[mode][index]["observations"],
                        "native matched Python reference",
                    )
                    check(
                        record["same_stop_as_python"]
                        == (
                            record["observations"] == rows[mode][index]["observations"]
                        ),
                        "native discrepancy retained",
                    )
                    native_checks.append(
                        audit_native_record(
                            directory,
                            record,
                            data["x"][index],
                            data["dt"][index],
                            result,
                        )
                    )
                calculated = recompute_metrics(native_rows, data["label"][:n])
                for key, value in calculated.items():
                    close(
                        receipt["metrics"][key],
                        value,
                        "native subset metric arithmetic",
                    )
                recovered = sum(
                    row["native_recovery"] is not None for row in native_rows
                )
                check(
                    recovered
                    == receipt["cold_resume_count"]
                    == int(any(row["observations"] > 1 for row in native_rows)),
                    "first continuing native case recovery selection",
                )
                check(
                    receipt["same_stop_count"]
                    == sum(row["same_stop_as_python"] for row in native_rows),
                    "native stop agreement count",
                )
                summary[split]["native"][mode] = {
                    "metrics": calculated,
                    "checks": native_checks,
                    "same_stop_count": receipt["same_stop_count"],
                    "cold_resume_count": recovered,
                }
                counts["native_policy_episodes"] += n
    return {
        "seed": seed,
        "counts": counts,
        "splits": summary,
        "value_prefixes_independently_checked": len(value_errors),
        "maximum_independent_continuation_value_error": max(value_errors, default=0),
        "actor_manifest_sha256": result["actor_manifest_sha256"],
        "policy_sha256": result["policy_sha256"],
        "result_sha256": sha(directory / "RESULT.json"),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--study", required=True)
    parser.add_argument("--base-results", required=True)
    parser.add_argument("--output")
    parser.add_argument("--replay-neural", action="store_true")
    parser.add_argument("--skip-performance", action="store_true")
    parser.add_argument("--cache-dir")
    args = parser.parse_args()
    study = Path(args.study).resolve()
    package = study.parent.parent
    sys.path.insert(0, str(package.parent.parent))
    protocol = json.loads((package / "PROTOCOL.json").read_text())
    began = time.process_time(), time.perf_counter()
    report = {
        "schema": "hcsn-study002-online-audit-v1",
        "issues": [],
        "missing": [],
        "boundary": {},
        "performance": {},
    }
    seal = json.loads((package / "SOURCE_SEAL.json").read_text())
    check(canonical(seal["files"]) == seal["sha256"], "source seal mapping identity")
    for name, digest in seal["files"].items():
        check(sha(package / name) == digest, "sealed scientific source bytes")
    tables = {}
    for seed in protocol["boundary"]["actor_seeds"]:
        directory = study / "boundary" / f"seed{seed}"
        if not (directory / "RESULT.json").exists():
            report["missing"].append(str(directory.relative_to(study)))
            continue
        try:
            report["boundary"][str(seed)] = audit_seed(
                directory,
                protocol["boundary"],
                args.base_results,
                args.replay_neural,
                tables,
            )
            source = json.loads((directory / "RESULT.json").read_text())["source_seals"]
            check(
                source
                == {"base": protocol["base_source_seal"], "followup": seal["sha256"]},
                "formal boundary source identity",
            )
        except Exception:
            report["issues"].append(
                {"case": f"boundary/seed{seed}", "traceback": traceback.format_exc()}
            )
    if not args.skip_performance:
        from audit_stream_performance import audit_performance
        from audit_remaining_execution import audit_remaining_execution

        report["performance"] = audit_performance(
            study,
            package,
            protocol,
            report["issues"],
            report["missing"],
            args.cache_dir,
        )
        try:
            report["external_execution"] = audit_remaining_execution(
                study,
                package,
                protocol,
                {"base": protocol["base_source_seal"], "followup": seal["sha256"]},
            )
        except Exception:
            report["issues"].append(
                {"case": "remaining_execution", "traceback": traceback.format_exc()}
            )
    report.update(
        {
            "status": "passed"
            if not report["issues"] and not report["missing"]
            else "incomplete_or_failed",
            "actor_replay_requested": args.replay_neural,
            "source_seal": json.loads((package / "SOURCE_SEAL.json").read_text())[
                "sha256"
            ],
            "analysis_sources": {
                p.name: sha(p) for p in Path(__file__).parent.glob("*audit*.py")
            },
            "cpu_seconds": time.process_time() - began[0],
            "wall_seconds": time.perf_counter() - began[1],
            "limits": [
                "Value check independently reproduces the finite 257-point Gaussian model, not continuum optimality or Bayesian correctness of neural transitions.",
                "Actor replay, when requested, uses the frozen trained implementation; it is not a second neural architecture implementation.",
                "Native Q24 disagreements are preserved; equality with Python is not an audit pass criterion.",
                "Tensor state bytes are not RSS; CPU and task observation costs are not energy.",
            ],
        }
    )
    destination = (
        Path(args.output) if args.output else study / "analysis/ONLINE_AUDIT.json"
    )
    destination.write_text(
        json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n"
    )
    print(
        json.dumps(
            {
                "status": report["status"],
                "boundary_seeds": len(report["boundary"]),
                "issues": len(report["issues"]),
                "missing": len(report["missing"]),
            }
        )
    )
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
