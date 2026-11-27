"""Same-weight Lambert-W versus bracketed-root closed-loop control.

This file does not alter a trained parameter, the task, the random seed rule,
or the frozen evaluator. RRPolicy already exposes the two boundary methods.
The control replays both methods with the same scenarios and initial RNG.
"""

from pathlib import Path
import argparse
import copy
import gzip
import hashlib
import json
import os
import time

import numpy as np
import torch

from .evaluate import (LATENT_BASE, QUERY_DRAWS, REPLAYS, canonical_digest,
                       evaluate, load_policy, numpy, validate_selection)
from .prepare_data import load_data, sha
from .run_evaluation import DATASETS, validated_selection
from .train import atomic_json, check_disk


ROOT = Path(__file__).resolve().parent
EVENT_TIME_TOLERANCE = 1e-7


def weights_digest(model):
    digest = hashlib.sha256()
    for name, value in sorted(model.state_dict().items()):
        array = value.detach().cpu().contiguous().numpy()
        digest.update(name.encode()+b"\0"+str(array.dtype).encode()+b"\0")
        digest.update(json.dumps(array.shape).encode()+b"\0"+array.tobytes())
    return digest.hexdigest()


class BoundaryProbe(torch.nn.Module):
    is_stochastic = True

    def __init__(self, model):
        super().__init__()
        self.core = model
        self.records = []
        self.batch_serial = -1

    def initial_state(self, batch_size, rng):
        self.batch_serial += 1
        self.observation_step = 0
        return self.core.initial_state(batch_size, rng)

    def step(self, state, observation, dt_elapsed, rng, event_mask=True, record_spikes=False):
        state, output = self.core.step(state, observation, dt_elapsed, rng,
                                      event_mask=event_mask, record_spikes=record_spikes)
        self.records.append({"batch_serial": self.batch_serial, "step": self.observation_step,
            "time": state.time.copy(), "observation": numpy(observation).copy(),
            "dt": numpy(dt_elapsed).copy(), "mask": numpy(event_mask).copy(),
            "indices": state.indices.copy(), "trace": state.trace.copy(),
            "boundary": numpy(output["boundary"]).copy(), "drift": numpy(output["drift"]).copy(),
            "logits": numpy(output["logits"]).copy(), "actual_counts": numpy(output["actual_counts"]).copy(),
            "rng_sha256": canonical_digest(rng.bit_generator.state)})
        self.observation_step += 1
        return state, output


def compare_event_logs(left, right):
    types_left = [(event["component"], event["cause"]) for event in left]
    types_right = [(event["component"], event["cause"]) for event in right]
    same_types = types_left == types_right
    time_error = (max((abs(a["time"]-b["time"]) for a, b in zip(left, right)), default=0.)
                  if same_types else None)
    first = next((index for index, (a, b) in enumerate(zip(left, right))
                  if (a["component"], a["cause"]) != (b["component"], b["cause"])
                  or abs(a["time"]-b["time"]) > EVENT_TIME_TOLERANCE), None)
    if first is None and len(left) != len(right):
        first = min(len(left), len(right))
    return {"counts_equal": len(left) == len(right), "event_type_sequence_equal": same_types,
            "exact_event_log_equal": left == right,
            "event_log_equal_with_time_tolerance": same_types and time_error <= EVENT_TIME_TOLERANCE,
            "maximum_time_difference_if_type_aligned": time_error,
            "first_event_divergence_beyond_tolerance": first,
            "count_root_minus_lambert": len(right)-len(left)}


def compare_step_records(left, right):
    if len(left) != len(right):
        raise AssertionError("Numerical methods received different numbers of observation calls")
    records = []
    for index, (a, b) in enumerate(zip(left, right)):
        if (a["batch_serial"], a["step"]) != (b["batch_serial"], b["step"]):
            raise AssertionError("Numerical methods used different batching or event order")
        if not np.array_equal(a["dt"], b["dt"]) or not np.array_equal(a["mask"], b["mask"]):
            raise AssertionError("Numerical methods used different time intervals or masks")
        row = {"call": index, "batch_serial": a["batch_serial"], "observation_step": a["step"],
               "batch_size": len(a["time"]), "time": a["time"].tolist(),
               "same_observation": bool(np.array_equal(a["observation"], b["observation"])),
               "same_indices_after_observation": bool(np.array_equal(a["indices"], b["indices"])),
               "same_count_matrix": bool(np.array_equal(a["actual_counts"], b["actual_counts"])),
               "same_rng_after_observation": a["rng_sha256"] == b["rng_sha256"]}
        for field in ("boundary", "drift", "logits", "trace"):
            row[field+"_maximum_absolute_difference"] = float(np.abs(a[field]-b[field]).max(initial=0.))
        records.append(row)
    return records


def compact_path(row):
    return {"actions": [{"time": item["time"], "action": item["action"]} for item in row["task_trace"]],
            "delivered": row["delivered"], "expected_utility": row["expected_utility"],
            "normalized_utility": row["normalized_utility"],
            "realized_query_utility": row["realized_query_utility"],
            "budget_final": row["budget_final"], "budget_spent": row["budget_spent"],
            "renewals": row["renewals"], "internal_spikes": row["internal_spikes"],
            "internal_spikes_per_neuron": row["internal_spikes_per_neuron"],
            "actual_internal_events": row["internal_spike_times"]}


def evaluate_pair(model, scenarios, *, oracle_values, episode_metadata, dataset,
                  training_seed, latent_replay, latent_seed=None, query_seed_base=None):
    original_weights = weights_digest(model)
    probes, results = {}, {}
    order = ("closed_form", "root") if (training_seed+latent_replay) % 2 == 0 else ("root", "closed_form")
    for method in order:
        core = copy.deepcopy(model)
        core.boundary_method = method
        if weights_digest(core) != original_weights:
            raise AssertionError("Boundary method control changed weights")
        probe = BoundaryProbe(core).eval()
        results[method] = evaluate(probe, scenarios, oracle_values=oracle_values,
            episode_metadata=episode_metadata, dataset=dataset, training_seed=training_seed,
            latent_replay=latent_replay, latent_seed=latent_seed, keep_trace=True,
            query_draws=QUERY_DRAWS, query_seed_base=query_seed_base)
        if weights_digest(core) != original_weights:
            raise AssertionError("Evaluation mutated a frozen parameter or buffer")
        probes[method] = probe
    a, b = results["closed_form"], results["root"]
    if a["latent_seed"] != b["latent_seed"]:
        raise AssertionError("Boundary methods did not use identical initial actor RNG seeds")
    rows = []
    for left, right in zip(a["rows"], b["rows"]):
        keys = ("scenario_index", "scenario_digest", "group", "condition", "initial_state_sha256",
                "query_seeds", "query_bits", "oracle_expected_utility")
        if any(left[key] != right[key] for key in keys):
            raise AssertionError("Methods do not share scenario, initial state, and observer queries")
        if len(left["task_trace"]) != len(right["task_trace"]):
            raise AssertionError("Task event schedule changed under a numerical method")
        disagreement = [x["time"] for x, y in zip(left["task_trace"], right["task_trace"])
                        if x["action"] != y["action"]]
        row = {key: left[key] for key in keys}
        row.update(compare_event_logs(left["internal_spike_times"], right["internal_spike_times"]))
        row.update(action_disagreement_count=len(disagreement), action_disagreement_times=disagreement,
                   delivered_pulses_equal=left["delivered"] == right["delivered"],
                   expected_utility_root_minus_lambert=right["expected_utility"]-left["expected_utility"],
                   realized_utility_root_minus_lambert=(np.asarray(right["realized_query_utility"])
                                                      -np.asarray(left["realized_query_utility"])).tolist(),
                   lambert=compact_path(left), brent=compact_path(right))
        rows.append(row)
    steps = compare_step_records(probes["closed_form"].records, probes["root"].records)
    summary = {"episodes": len(rows), "same_weights_and_initial_state": True,
               "all_task_resource_invariants_passed": a["all_resource_invariants_passed"] and b["all_resource_invariants_passed"],
               "rows_with_any_action_divergence": sum(row["action_disagreement_count"] > 0 for row in rows),
               "total_action_disagreements": sum(row["action_disagreement_count"] for row in rows),
               "rows_with_event_divergence_beyond_tolerance": sum(not row["event_log_equal_with_time_tolerance"] for row in rows),
               "rows_with_different_event_counts": sum(not row["counts_equal"] for row in rows),
               "rows_with_different_delivered_pulses": sum(not row["delivered_pulses_equal"] for row in rows),
               "maximum_absolute_expected_utility_difference": max(abs(row["expected_utility_root_minus_lambert"]) for row in rows),
               "mean_expected_utility_root_minus_lambert": float(np.mean([row["expected_utility_root_minus_lambert"] for row in rows])),
               "maximum_type_aligned_event_time_difference": max((row["maximum_time_difference_if_type_aligned"]
                    for row in rows if row["event_type_sequence_equal"]), default=None),
               "observation_calls_with_different_rng_states": sum(not item["same_rng_after_observation"] for item in steps)}
    for field in ("boundary", "drift", "logits", "trace"):
        summary[field+"_maximum_absolute_difference"] = max(item[field+"_maximum_absolute_difference"] for item in steps)
    if weights_digest(model) != original_weights:
        raise AssertionError("Original frozen model changed")
    return {"schema": "rrsnn-v4-frozen-boundary-comparison-1", "summary": summary,
            "dataset": dataset, "training_seed": training_seed, "latent_replay": latent_replay,
            "latent_seed": a["latent_seed"], "same_weight_state_sha256": original_weights,
            "execution_order": list(order), "event_time_tolerance": EVENT_TIME_TOLERANCE,
            "methods": {"lambert": "Frozen RRPolicy boundary_method=closed_form",
                        "brent": "Frozen RRPolicy boundary_method=root, independent scalar brentq bracket"},
            "timing": {method: {"model_step_cpu_seconds": result["model_step_cpu_seconds"],
                                "elapsed_seconds_including_task": result["elapsed_seconds_including_task"]}
                       for method, result in results.items()},
            "timing_scope": "Same instrumented model.step path, including diagnostic copies and RNG digests. Alternating method order. These are full diagnostic replay costs, not an optimized boundary-kernel microbenchmark.",
            "coupling_scope": "Identical scenario, frozen weights, initialization and actor seed per replay. After a numerical branch changes random consumption, trajectories evolve naturally; divergence is recorded rather than forcing path equality.",
            "control_difference_scope": "Recorded drift/logit/threshold differences follow each closed-loop history. After action or state divergence they include downstream effects, not only local root roundoff.",
            "real_future_window": False, "new_training_performed": False,
            "step_comparisons": steps, "rows": rows}


def evaluate_checkpoint(checkpoint, freeze_path, selection_path, publication_receipt,
                        datasets=DATASETS, replays=range(REPLAYS)):
    _, selected, manifest, publication_identity = validated_selection(freeze_path, selection_path, publication_receipt)
    selection = validate_selection(checkpoint, selection_path, freeze_path)
    model, blob = load_policy(checkpoint, selection["training_protocol_sha256"])
    if blob.get("run_name", blob["variant"]) != "rr_full" or blob["variant"] != "rr_full":
        raise ValueError("Frozen numerical boundary control is declared only for rr_full")
    if Path(checkpoint).resolve() != selected["rr_full"][int(blob["seed"])].resolve():
        raise ValueError("Numerical control checkpoint differs from the complete published selection")
    if any(name not in DATASETS for name in datasets) or any(replay not in range(REPLAYS) for replay in replays):
        raise ValueError("Numerical control requested an undeclared dataset or replay")
    torch.set_num_threads(1)
    destination = Path(checkpoint).parent/"numerical_control"
    destination.mkdir(exist_ok=True)
    output_files = []
    for dataset in datasets:
        scenarios, arrays, metadata, _ = load_data(dataset, freeze_path)
        for replay in replays:
            check_disk()
            path = destination/f"evaluation_{dataset}_rep{replay}.json.gz"
            identity = {**publication_identity, "controller_sha256": sha(__file__),
                        "checkpoint_sha256": sha(checkpoint), "same_weight_state_sha256": weights_digest(model),
                        "variant": "rr_full", "training_seed": int(blob["seed"]),
                        "dataset": dataset, "latent_replay": replay,
                        "source_files": next(item["files"] for item in manifest["splits"] if item["name"] == dataset),
                        "event_time_tolerance": EVENT_TIME_TOLERANCE, "new_training_performed": False}
            if path.exists():
                with gzip.open(path, "rt", encoding="utf-8") as handle:
                    existing = json.load(handle)
                if (existing["identity"] != identity or len(existing["comparison"]["rows"]) != len(scenarios)
                        or existing["comparison"]["summary"]["same_weights_and_initial_state"] is not True):
                    raise ValueError("Existing numerical-control result has different or incomplete identity")
                summary = existing["comparison"]["summary"]
            else:
                comparison = evaluate_pair(model, scenarios, oracle_values=arrays["oracle_utility"],
                    episode_metadata=metadata, dataset=dataset, training_seed=int(blob["seed"]), latent_replay=replay)
                temporary = path.with_suffix(path.suffix+".tmp")
                with gzip.open(temporary, "wt", encoding="utf-8") as handle:
                    json.dump({"identity": identity, "comparison": comparison}, handle, allow_nan=False)
                temporary.replace(path)
                summary = comparison["summary"]
            check_disk()
            output_files.append({"path": str(path.relative_to(ROOT)), "sha256": sha(path), "summary": summary})
            print(json.dumps({"numerical_control": str(path), "summary": summary}), flush=True)
    validated_selection(freeze_path, selection_path, publication_receipt)
    return output_files


def validate_development():
    from .models import make_policy
    from .prepare_data import make_arrays, paired_scenarios
    from .task import Scenario
    torch.set_num_threads(1)
    torch.manual_seed(901901)
    model = make_policy("rr_full")
    scenes = [Scenario((1.2, .8, .4, .2), (1., 1., 3., 3.), 3, 2, 1),
              Scenario((.3, 1.3, .6, 1.1), (.75, 1.25, 2.75, 3.25), 4, 1, 1,
                       shock_time=1.25, refill_time=2.75)]
    arrays = make_arrays(scenes)
    batch = evaluate_pair(model, scenes, oracle_values=arrays["oracle_utility"], episode_metadata=None,
        dataset="development", training_seed=0, latent_replay=0, latent_seed=901904, query_seed_base=901940)
    paired, metadata = paired_scenarios(901910, groups=1)
    arrays = make_arrays(paired)
    strict = evaluate_pair(model, paired, oracle_values=arrays["oracle_utility"], episode_metadata=metadata,
        dataset="paired", training_seed=0, latent_replay=1, latent_seed=901914, query_seed_base=901950)
    assert strict["execution_order"] != batch["execution_order"]
    assert len({row["initial_state_sha256"] for row in strict["rows"]}) == 1
    for output in (batch, strict):
        assert output["summary"]["same_weights_and_initial_state"]
        assert output["summary"]["all_task_resource_invariants_passed"]
        assert output["summary"]["boundary_maximum_absolute_difference"] < 2e-5
    original = [{"time": .25, "component": 0, "cause": "ctmc_threshold"}]
    altered = [{"time": .2501, "component": 0, "cause": "ctmc_threshold"}]
    assert compare_event_logs(original, altered)["first_event_divergence_beyond_tolerance"] == 0
    assert compare_event_logs([], original)["count_root_minus_lambert"] == 1
    before_data = json.loads((ROOT/"pre_data_freeze.json").read_text())
    assert all(sha(ROOT/name) == expected for name, expected in before_data["source_sha256"].items())
    result = {"schema": "rrsnn-v4-numerical-control-development-1", "all_passed": True,
              "normal_batch": batch["summary"], "strict_paired": strict["summary"],
              "numerical_methods_have_identical_initial_state_and_weights": True,
              "both_execution_orders_checked": True, "event_divergence_detector_checked": True,
              "frozen_source_files_unchanged": True, "production_data_opened": False,
              "source_sha256": sha(__file__)}
    atomic_json(ROOT/"numerical_control_validation.json", result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkpoint", type=Path)
    parser.add_argument("--freeze", type=Path)
    parser.add_argument("--selection", type=Path)
    parser.add_argument("--publication-receipt", type=Path)
    parser.add_argument("--datasets", nargs="+", default=list(DATASETS))
    parser.add_argument("--replays", nargs="+", type=int, default=list(range(REPLAYS)))
    parser.add_argument("--validate-development", action="store_true")
    args = parser.parse_args()
    if args.validate_development:
        print(json.dumps(validate_development()))
    elif args.checkpoint and args.freeze and args.selection and args.publication_receipt:
        files = evaluate_checkpoint(args.checkpoint, args.freeze, args.selection, args.publication_receipt,
                                    tuple(args.datasets), tuple(args.replays))
        print(json.dumps({"completed_files": len(files)}))
    else:
        parser.error("Provide --checkpoint, --freeze, --selection and --publication-receipt, or --validate-development")
