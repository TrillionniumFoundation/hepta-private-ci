"""Supplemental independent action/identity/Q32 audit and fixed native replay.

This is an evidence helper, not part of the frozen model or policy runtime.
It never generates a new scenario or chooses a policy parameter.
"""

import argparse
from collections import defaultdict
from fractions import Fraction
import gzip
import hashlib
import json
import math
from pathlib import Path
import time

from experiments.first_passage_cell.audit import ARMS, SEEDS, audit_run
from experiments.first_passage_cell.ndu import NativeNduPort
from experiments.first_passage_cell.study import replay_episode
from experiments.first_passage_cell.study_io import verify_freeze

PACKAGE = Path(__file__).resolve().parents[2]
Q32 = 2 ** 32
LIMIT = 1_000_000 * Q32
POLICIES = dict(zip(ARMS, ("ordinary", "endogenous", "learned_threshold",
                         "fixed_shared6", "fixed7", "always_wait", "always_repair", "always_stop")))
PRIMARY = {"ordinary_first_event", "endogenous_renewal", "learned_threshold7"}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def exact_round(value):
    return round(Fraction.from_float(float(value)) * Q32)


def independent_path(instants):
    values, projected = [0], 0
    for instant in reversed(instants):
        raw = exact_round(instant) + values[0]
        clipped = max(-LIMIT, min(LIMIT, raw))
        projected += clipped != raw
        values.insert(0, clipped)
    return values, projected


def check_compact(receipt, paths, episode, frozen):
    if (receipt["binary_sha256"] != frozen["native_binary_sha256"]
            or receipt["source_manifest_sha256"] != frozen["native_source_manifest_sha256"]
            or receipt["authority"] != "DENY_ALL" or receipt["safety_certificate"] is not False
            or receipt["rejected"]):
        raise ValueError("Native identity, authority or rejection mismatch")
    context = receipt["context"]
    for field in ("phase", "seed", "arm"):
        if context[field] != episode[field]:
            raise ValueError("Native context mismatch: " + field)
    if (context["scenario_id"] != episode["scenario"]["identity"]
            or context["model_checkpoint_digest"] != episode["model_checkpoint_digest"]):
        raise ValueError("Native scenario/model context mismatch")
    mapping = receipt["native_candidate_to_action"]
    if set(mapping) != {r["id"] for r in receipt["recursive_paths"]}:
        raise ValueError("Candidate mapping is not complete")
    expected_names = set(paths)
    if "STOP" not in expected_names:
        expected_names.add("ABSTAIN")
    if set(mapping.values()) != expected_names or set(receipt["action_values"]) != expected_names:
        raise ValueError("Native action set mismatch")
    for path in receipt["recursive_paths"]:
        name = mapping[path["id"]]
        instants = [0.0] if name == "ABSTAIN" else paths[name]
        expected, projected = independent_path(instants)
        if path["values_q32"] != expected or path["projection_count"] != projected:
            raise ValueError("Independent exact-rational Q32 path disagreement")
        if receipt["action_values"][name] != expected[0] / Q32:
            raise ValueError("Published action value differs from native path")
    return len(receipt["recursive_paths"])


def expected_action(episode, row, model, selected):
    arm, decision = episode["arm"], row["decision"]
    legal = {a.upper() for a in row["observation"]["legal_actions"]}
    if decision["policy"] != POLICIES[arm]:
        raise ValueError("Wrong policy class for registered arm")
    if arm in {"always_wait", "always_repair", "stop"}:
        target = {"always_wait": "WAIT", "always_repair": "REPAIR", "stop": "STOP"}[arm]
        if decision["values"] is not None or decision["native_receipt"] is not None:
            raise ValueError("Fixed-action control unexpectedly uses a forecast")
        return target if target in legal else "WAIT"
    values = decision["values"]
    raw = decision["native_receipt"]["action_values"]
    distance = max(0.0, row["observation"]["level"] - model["selected_parameters"]["barrier"])
    if values["distance"] != distance or set(raw) != legal:
        raise ValueError("Wrong model distance or legal score set")
    if (values["mode"] != ("single" if arm == "ordinary_first_event" else "renewal")
            or values["method"] != "analytic"):
        raise ValueError("Wrong registered forecast mechanism")
    if arm.startswith("fixed") or arm == "learned_threshold7":
        threshold = selected[arm]["selected_parameter"] if arm == "learned_threshold7" else 0.35
        target = "REPAIR" if distance <= threshold and "REPAIR" in legal else "WAIT"
        return target if raw[target] > 0 else "STOP"
    adjusted = dict(raw)
    if "REPAIR" in adjusted:
        adjusted["REPAIR"] -= selected[arm]["selected_parameter"]
    order = {"STOP": 0, "WAIT": 1, "REPAIR": 2}
    return min(adjusted, key=lambda action: (-adjusted[action], order[action]))


def supplemental(phase, native, frozen):
    folder = PACKAGE / "runs" / phase
    count = 256 if phase == "confirmation" else 128
    metrics = defaultdict(lambda: defaultdict(float))
    initial_observations, cohort, replay_targets = {}, set(), []
    q32_maximum, float_sum_maximum, paths_checked, decisions_checked = 0.0, 0.0, 0, 0
    for seed in SEEDS:
        model_root = PACKAGE / "prepared" / str(seed)
        models = {n: read(model_root / f"model{n}.json") for n in (6, 7)}
        model_hashes = {n: sha(model_root / f"model{n}.json") for n in (6, 7)}
        selected = read(model_root / "policy_selection.json")["selected"]
        ledger = folder / f"{seed}.jsonl.gz"
        with gzip.open(ledger, "rt") as stream:
            for line_index, line in enumerate(stream):
                episode = json.loads(line)
                if episode["phase"] != phase or episode["seed"] != seed or episode["arm"] not in ARMS:
                    raise ValueError("Unregistered phase, seed or arm")
                arm = episode["arm"]
                scenario_index = int(episode["scenario"]["identity"].split(":")[-1])
                if episode["scenario"]["identity"] != f"{phase}:{seed}:{scenario_index}" or not 0 <= scenario_index < count:
                    raise ValueError("Wrong registered scenario identity")
                key = (seed, scenario_index, arm)
                if key in cohort:
                    raise ValueError("Duplicate cohort entry")
                cohort.add(key)
                observed = canonical(episode["records"][0]["observation"])
                pair = (seed, scenario_index)
                if pair in initial_observations and initial_observations[pair] != observed:
                    raise ValueError("Arms received different initial public observations")
                initial_observations[pair] = observed
                width = 7 if arm == "fixed_cross7" else 6
                model = models[width]
                if (episode["model_digest"] != model["model_digest"]
                        or episode["model_checkpoint_digest"] != model_hashes[width]
                        or episode["active_physical_parameters"] != width
                        or episode["active_policy_parameters"] != int(arm in PRIMARY)):
                    raise ValueError("Frozen model identity or parameter budget mismatch")
                bias = selected[arm]["selected_parameter"] if arm in {"ordinary_first_event", "endogenous_renewal"} else 0.0
                threshold = selected[arm]["selected_parameter"] if arm == "learned_threshold7" else None
                if episode["policy_bias"] != bias or episode["policy_threshold"] != threshold:
                    raise ValueError("Policy parameter changed after development")
                forecast_calls = 0
                for row in episode["records"]:
                    decisions_checked += 1
                    decision = row["decision"]
                    if decision["bias"] != bias or expected_action(episode, row, model, selected) != row["action"].upper():
                        raise ValueError("Actual action differs from independently reconstructed policy")
                    compact = decision["native_receipt"]
                    if compact is not None:
                        forecast_calls += 1
                        paths = {}
                        for action, value in decision["values"]["actions"].items():
                            if value["terminal"] != 0 or any(event["discount"] != 1 for event in value["events"]):
                                raise ValueError("Unsupported forecast recursive profile")
                            paths[action] = [event["instant"] for event in value["events"]]
                        paths_checked += check_compact(compact, paths, episode, frozen)
                realized = episode["realized_native_receipt"]
                instants = [row["reward"] for row in episode["records"]]
                paths_checked += check_compact(realized, {"REALIZED": instants}, episode, frozen)
                native_score = realized["action_values"]["REALIZED"]
                # Python 3.12 sum uses improved float summation, whereas the
                # task accumulator uses repeated +=. Keep this separate from
                # exact Q32 checks and from the much larger Q32 roundoff bound.
                accumulation_error = abs(realized["realized_return"] - episode["total_reward"])
                accumulation_budget = 8 * math.ulp(max(1.0, sum(abs(x) for x in instants)))
                float_sum_maximum = max(float_sum_maximum, accumulation_error)
                if episode["realized_native_return"] != native_score or accumulation_error > accumulation_budget:
                    raise ValueError("Actual return and recorded native score mismatch")
                difference = abs(native_score - episode["total_reward"])
                q32_maximum = max(q32_maximum, difference)
                bound = (len(instants) + 1) / Q32
                if realized["roundoff_bound"] != bound or difference > len(instants) / (2 * Q32) + 1e-12:
                    raise ValueError("Native actual-return roundoff exceeded the exact conversion budget")
                runtime = episode["runtime"]
                if (runtime["native_calls"] != forecast_calls + 1
                        or runtime["forecast_requests"] != forecast_calls
                        or runtime["decisions"] != len(episode["records"]) or runtime["forecast_cache_hits"] != 0):
                    raise ValueError("Compute counters or fresh-cache contract mismatch")
                for name, value in runtime.items():
                    if value < 0:
                        raise ValueError("Negative measured compute cost")
                    metrics[arm][name] += value
                metrics[arm]["episodes"] += 1
                if scenario_index in {0, count - 1}:
                    replay_targets.append((ledger, line_index, seed, scenario_index, arm))
    if len(cohort) != len(SEEDS) * count * len(ARMS):
        raise ValueError("Registered paired cohort is incomplete")
    if len(replay_targets) != 128:
        raise ValueError("Fixed replay sample is incomplete")
    replayed = []
    for ledger, line_index, seed, index, arm in replay_targets:
        receipt = replay_episode(ledger, line_index, native)
        replayed.append({"seed": seed, "scenario_index": index, "arm": arm,
                         "line_index": line_index, "forecast_receipts_replayed": receipt["forecast_receipts_replayed"],
                         "realized_receipt_replayed": receipt["realized_receipt_replayed"]})
    for arm, row in metrics.items():
        denominator = row["episodes"]
        for name, value in list(row.items()):
            if name != "episodes":
                row["mean_" + name] = value / denominator
        row["mean_observed_pipeline_wall_seconds"] = sum(row[name] for name in
            ("decision_wall_seconds", "simulation_wall_seconds", "realized_native_wall_seconds")) / denominator
    return {"pass": True, "episodes": len(cohort), "paired_initial_observations": len(initial_observations),
            "decisions_checked": decisions_checked, "independent_native_paths_checked": paths_checked,
            "maximum_actual_return_q32_error": q32_maximum,
            "maximum_float_accumulation_difference": float_sum_maximum,
            "float_accumulation_budget": "8 ULP of max(1, sum absolute instantaneous rewards), separate from exact Q32 verification",
            "q32_reference": "exact Fraction.from_float, ties-even integer rounding, registered additive recursion",
            "fixed_replay_sample_rule": "first and last scenario per seed, all eight arms; selected before observing outcomes",
            "native_replay_episodes": len(replayed), "native_replay_calls": native.calls,
            "replay_records": replayed, "compute_by_arm": dict(metrics),
            "compute_scope": "observed inference/simulation/native wall times; Python process CPU excludes native subprocess CPU; no cross-arm cache reuse"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("confirmation", "stress_drift", "stress_diffusion"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run_path = PACKAGE / "runs" / f"{args.phase}_run.json"
    if not run_path.exists():
        raise ValueError("Refusing to audit an incomplete run")
    if args.output.exists():
        raise FileExistsError(args.output)
    native = NativeNduPort(PACKAGE / "NATIVE_BUILD.json")
    frozen = verify_freeze(PACKAGE / "FREEZE.json", PACKAGE / "prepared", native)
    run = read(run_path)
    if (run["freeze_sha256"] != sha(PACKAGE / "FREEZE.json")
            or run["source_commit"] != frozen["source_commit"]):
        raise ValueError("Run receipt is not bound to the frozen source")
    started = time.perf_counter()
    result = audit_run(PACKAGE / "runs" / args.phase, args.phase)
    result["supplemental_checks"] = supplemental(args.phase, native, frozen)
    result.update({"freeze_sha256": sha(PACKAGE / "FREEZE.json"), "source_commit": frozen["source_commit"],
                   "run_receipt_sha256": sha(run_path), "audit_helper_sha256": sha(__file__),
                   "input_root": str((PACKAGE / "runs" / args.phase).relative_to(PACKAGE.parent.parent)),
                   "audit_wall_seconds": time.perf_counter() - started})
    verify_freeze(PACKAGE / "FREEZE.json", PACKAGE / "prepared", native)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as stream:
        json.dump(result, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
    print(json.dumps({"phase": args.phase, "ledger_pass": result["ledger_pass"],
                      "episodes": result["episodes"], "primary_comparisons": result["primary_comparisons"],
                      "native_replay_episodes": result["supplemental_checks"]["native_replay_episodes"]}), flush=True)


if __name__ == "__main__":
    main()
