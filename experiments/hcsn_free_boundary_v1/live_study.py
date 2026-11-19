"""Predeclared trained-checkpoint/native-owner evaluation and cost ledger.

The first 32 test episodes and controller coefficients are fixed in PROTOCOL.
Every controller and fixed-prefix reference executes actual model.step calls.
This driver does not train, fit a controller, or select a checkpoint from test.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import time
import traceback

import numpy as np
import torch

from .model import HCSNClassifier
from .native_bridge import MANIFEST, POLICIES, restored_binary
from .run_native import write
from .run_native_live import model_identity, run_live
from .training import load_weights


PACKAGE = Path(__file__).resolve().parent
REPOSITORY = PACKAGE.parents[1]
REFERENCE_READS = {"read_all": None, "fixed8": 8, "fixed16": 16, "fixed24": 24}


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _json(path):
    return json.loads(Path(path).read_text())


def _mean(records, key):
    return sum(row[key] for row in records) / len(records)


def source_identity():
    paths = [PACKAGE / name for name in (
        "live_study.py", "run_native_live.py", "native_bridge.py", "run_native.py",
        "restore_native.py", "model.py", "oracle_torch.py", "training.py",
        "benchmark_models.py", "native_vendor/adapter.py", "native_vendor/MANIFEST.json")]
    return {str(path.relative_to(REPOSITORY)): sha256(path) for path in paths}


def _freeze_entries(value):
    """Accept common explicit hash-receipt layouts; never infer missing hashes."""
    for field in ("source_sha256", "files", "sources", "inputs"):
        raw = value.get(field)
        if isinstance(raw, dict):
            entries = {}
            for key, item in raw.items():
                digest = item if isinstance(item, str) else item.get("sha256")
                if isinstance(digest, str):
                    entries[key] = digest
            if entries:
                return entries
        if isinstance(raw, list):
            entries = {item["path"]: item["sha256"] for item in raw
                       if isinstance(item, dict) and "path" in item and "sha256" in item}
            if entries:
                return entries
    raise ValueError("Source freeze must contain explicit source SHA-256 entries")


def verify_freeze(path):
    entries = _freeze_entries(_json(path))
    verified = {}
    for source, expected in entries.items():
        source_path = Path(source)
        candidates = [source_path] if source_path.is_absolute() else [
            REPOSITORY / source_path, PACKAGE / source_path]
        actual_path = next((candidate for candidate in candidates if candidate.is_file()), None)
        if actual_path is None or sha256(actual_path) != expected:
            raise ValueError(f"Frozen source is missing or changed: {source}")
        verified[str(actual_path.resolve())] = expected
    # A protocol receipt alone is insufficient to bind the trained model code.
    required = ("model.py", "oracle_torch.py", "training.py", "benchmark_models.py")
    if not all(str((PACKAGE / name).resolve()) in verified for name in required):
        raise ValueError("Source freeze does not bind all required model/training sources")
    return {"receipt_sha256": sha256(path), "verified_file_count": len(verified),
            "model_source_sha256": verified[str((PACKAGE / "model.py").resolve())]}


def training_charge(summary, execution=None, *, development_fallback=False):
    """Charge exact full training-child CPU; retain in-process search details."""
    candidates = summary["candidates"]
    full_search = summary["total_cpu_seconds"] - summary["holdout_cpu_seconds"]
    if full_search < 0 or not candidates:
        raise ValueError("Invalid training/search CPU receipt")
    if execution is None:
        if not development_fallback:
            raise ValueError("Main native evaluation requires training EXECUTION.json")
        charged_cpu = full_search
        charge_scope = "development fallback only: in-process summary total minus heldout CPU"
    else:
        charged_cpu = float(execution["child_cpu_seconds"])
        if not math.isfinite(charged_cpu) or charged_cpu < 0:
            raise ValueError("Invalid exact-child training CPU receipt")
        if execution.get("exit_code", 0) != 0:
            raise ValueError("Training child did not exit successfully")
        charge_scope = "Exact training child PID CPU from wait4: includes Python/Torch startup, both LR candidates, validation, checkpoint/report IO and heldout evaluation; conservatively charged in full"
    return {
        "selected_learning_rate": summary["selection"]["selected_learning_rate"],
        "selected_step": summary["selection"]["selected_step"],
        "completed_candidates": len(candidates),
        "requested_update_cpu_seconds": sum(row["requested_training_cpu_seconds"] for row in candidates),
        "actual_update_cpu_seconds": sum(row["training_cpu_seconds"] for row in candidates),
        "candidate_setup_cpu_seconds": sum(row["setup_cpu_seconds"] for row in candidates),
        "candidate_validation_cpu_seconds": sum(row["validation_cpu_seconds"] for row in candidates),
        "all_candidate_total_cpu_seconds": sum(row["total_cpu_seconds"] for row in candidates),
        "full_training_search_cpu_seconds": full_search,
        "full_training_search_cpu_formula": "training summary total_cpu_seconds minus holdout_cpu_seconds",
        "charged_training_cpu_seconds": charged_cpu,
        "training_cpu_charge_scope": charge_scope,
        "execution_receipt_present": execution is not None,
        "development_fallback_used": execution is None,
        "training_experiment_total_cpu_seconds": summary["total_cpu_seconds"],
        "separate_holdout_cpu_seconds": summary["holdout_cpu_seconds"],
        "candidates": [{key: row[key] for key in (
            "learning_rate", "updates", "stopping_reason", "training_cpu_seconds",
            "total_cpu_seconds", "validation_cpu_seconds", "setup_cpu_seconds",
            "selected_parameter_changes")} for row in candidates],
    }


def load_locked_checkpoint(training_run, data, protocol, freeze):
    training_run, data = Path(training_run), Path(data)
    summary, selection = _json(training_run / "summary.json"), _json(training_run / "selection.json")
    request = _json(training_run / "request.json")
    execution_path = training_run / "EXECUTION.json"
    if not execution_path.is_file():
        raise ValueError("Main native evaluation requires completed training EXECUTION.json")
    execution = _json(execution_path)
    native = protocol["native_evaluation"]
    expected = protocol["optimization"]
    if summary["status"] != "completed" or request != summary["request"]:
        raise ValueError("Require a completed, internally consistent training receipt")
    if summary["selection"] != selection or request["model"] != native["model"] or request["seed"] != native["seed"]:
        raise ValueError("Training selection/model/seed differs from frozen native protocol")
    if (request["learning_rates"] != expected["learning_rates"]
            or request["cpu_seconds"] != expected["training_cpu_seconds_per_lr"]
            or request["width"] != expected["width"] or request["depth"] != expected["depth"]
            or len(summary["candidates"]) != len(expected["learning_rates"])):
        raise ValueError("Checkpoint search differs from predeclared training budget")
    weights = training_run / "selected.npz"
    if sha256(weights) != selection["selected_checkpoint_sha256"] or selection["selected_step"] < 1:
        raise ValueError("Selected trained numeric checkpoint identity changed")
    data_manifest = _json(data.with_suffix(".json"))
    data_hash = sha256(data)
    if (data_manifest["task"] != native["task"] or data_hash != selection["dataset_sha256"]
            or data_hash != data_manifest["sha256"]):
        raise ValueError("Native evaluation dataset differs from the selected training dataset")
    if tuple(native["policies"]) != POLICIES or list(native["references"]) != list(REFERENCE_READS):
        raise ValueError("Native policies/references differ from the frozen implementations")
    if native["cohort"] != "first32testepisodes, fixed before test metrics":
        raise ValueError("This driver is specifically bound to the first-32 cohort")
    freeze_receipt = verify_freeze(freeze)
    model = HCSNClassifier(**summary["selected_model_config"]).cpu().eval()
    load_weights(weights, model)
    with np.load(data, allow_pickle=False) as archive:
        x = torch.from_numpy(np.array(archive["test_x"][:32], copy=True))
        dt = torch.from_numpy(np.array(archive["test_dt"][:32], copy=True))
        y = np.array(archive["test_y"][:32], copy=True)
    if (len(x) != 32 or x.shape[1] < 24 or y.shape != tuple(dt.shape)
            or not np.all(y[:, :-1] == -100) or not np.all(y[:, -1] >= 0)):
        raise ValueError("Require 32 predeclared episodes with a final classification target")
    episode_ids = data_manifest["splits"]["test"]["episode_ids"][:32]
    cohort_hash = hashlib.sha256(x.numpy().tobytes() + dt.numpy().tobytes() + y.tobytes()).hexdigest()
    identity = {
        "training_run": str(training_run), "training_request": request,
        "training_summary_sha256": sha256(training_run / "summary.json"),
        "training_selection_sha256": sha256(training_run / "selection.json"),
        "training_request_sha256": sha256(training_run / "request.json"),
        "training_execution_sha256": sha256(execution_path),
        "training_execution_receipt": execution,
        "selected_checkpoint_sha256": sha256(weights),
        "selected_model_config": summary["selected_model_config"],
        "model_numeric_identity_sha256": model_identity(model)[0],
        "dataset_sha256": data_hash, "dataset_manifest_sha256": sha256(data.with_suffix(".json")),
        "cohort_sha256": cohort_hash, "episode_ids": episode_ids,
        "source_freeze": freeze_receipt, "training_charge": training_charge(summary, execution),
    }
    return model, x, dt, torch.from_numpy(y[:, -1].copy()), episode_ids, identity


def _native_totals(records):
    costs = [cost for row in records for cost in row["native_process_costs"]]
    keys = ("owner_ticks", "total_native_kernel_calls", "total_native_ndu_calls",
            "original_journal_replay_steps", "event_validation_kernel_steps",
            "event_validation_ndu_calls", "rpc_calls", "native_errors")
    return {key: sum(cost["counters"][key] for cost in costs) for key in keys}


def collect_native(directory, summary, price):
    result = {}
    for policy, aggregate in summary["summary"].items():
        paths = sorted((Path(directory) / policy).glob("episode*/RESULT.json"))
        records = [_json(path) for path in paths]
        if len(records) != aggregate["episodes"]:
            raise ValueError("Native aggregate lost episode receipts")
        counters = _native_totals(records)
        for record in records:
            if record["actual_reads"] != record["model_updates_executed"] or record["actual_reads"] != len(record["events"]):
                raise ValueError("Actual native/model/read counts diverged")
            if abs(record["utility"] - record["correct"] + price * record["actual_reads"]) > 1e-10:
                raise ValueError("Native task utility ledger is inconsistent")
        if counters["owner_ticks"] != sum(row["actual_reads"] for row in records):
            raise ValueError("Owner ticks differ from actual paid observations")
        total_cpu = aggregate["parent_cpu_seconds"] + aggregate["native_child_cpu_seconds"]
        result[policy] = {
            **aggregate, "mean_reads": _mean(records, "actual_reads"),
            "read_price": price, "mean_paid_read_cost": price * _mean(records, "actual_reads"),
            "full_execution_cpu_seconds": total_cpu,
            "full_execution_cpu_per_episode": total_cpu / len(records),
            "model_and_child_cpu_per_episode": (aggregate["model_cpu_seconds"] + aggregate["native_child_cpu_seconds"]) / len(records),
            "python_nonmodel_cpu_seconds": aggregate["parent_cpu_seconds"] - aggregate["model_cpu_seconds"],
            "native_counters": counters,
            "episodes_ledger": [{key: row[key] for key in (
                "episode", "actual_reads", "correct", "utility", "stop_reason",
                "model_updates_executed", "model_updates_avoided")} for row in records],
        }
    return result


def verify_recovered_trajectory(uninterrupted_root, recovered_root, recovered):
    """Compare numeric/actions; dataset-context hashes differ by price scenario."""
    for policy in POLICIES:
        suffix = Path(policy) / "episode00000" / "RESULT.json"
        normal = _json(Path(uninterrupted_root) / suffix)
        resumed = _json(Path(recovered_root) / suffix)
        fields = ("prefix", "prediction", "raw_signals", "signals")
        native_fields = ("activation_q24", "effective_action")
        readout_fields = ("action", "scores_q24", "tie", "native_ndu_frontier")

        def numerical_events(record):
            return [{**{key: event[key] for key in fields},
                     "native": {key: event["native"][key] for key in native_fields},
                     "readout": {key: event["native"]["readout"][key] for key in readout_fields}}
                    for event in record["events"]]

        if numerical_events(normal) != numerical_events(resumed):
            raise ValueError(f"Recovery changed numeric feature/action trajectory for {policy}")
        recovered[policy]["first_episode_matches_uninterrupted"] = True
        recovered[policy]["matched_fields"] = (list(fields) + [f"native.{key}" for key in native_fields]
                                                + [f"native.readout.{key}" for key in readout_fields])
        recovered[policy]["checkpoint_hashes_compared"] = False
        recovered[policy]["checkpoint_hash_scope"] = "Paid-price scenario is part of input/context identity, affecting checkpoint and native_ndu_digest; native001 separately tests identical-context digest equality"


def run_references(model, x, dt, labels, episode_ids, price, output):
    """Each reference truly executes its required prefix, without shared traces."""
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    summary = {}
    for name, fixed in REFERENCE_READS.items():
        started = time.process_time(), time.perf_counter()
        reads = x.shape[1] if fixed is None else fixed
        if reads > x.shape[1]:
            raise ValueError("Reference prefix exceeds the actual episode horizon")
        records = []
        for number in range(len(x)):
            state, steps, model_cpu, model_wall = None, [], 0.0, 0.0
            for index in range(reads):
                clock = time.process_time(), time.perf_counter()
                with torch.no_grad():
                    logits, state, _ = model.step(x[number:number + 1, index],
                                                  dt[number:number + 1, index], state)
                model_cpu += time.process_time() - clock[0]
                model_wall += time.perf_counter() - clock[1]
                if not torch.isfinite(logits).all():
                    raise FloatingPointError("Reference produced nonfinite logits")
                prediction = int(logits.argmax(-1).item())
                steps.append({"prefix": index + 1, "prediction": prediction,
                              "logits_sha256": hashlib.sha256(logits.numpy().tobytes()).hexdigest()})
            correct = int(prediction == int(labels[number]))
            record = {"episode": str(episode_ids[number]), "reference": name,
                      "actual_reads": reads, "model_updates_executed": reads,
                      "model_updates_avoided": x.shape[1] - reads,
                      "correct": correct, "prediction": prediction,
                      "paid_read_cost": price * reads, "utility": correct - price * reads,
                      "model_cpu_seconds": model_cpu, "model_wall_seconds": model_wall,
                      "stop_reason": "finite_horizon" if fixed is None else "predeclared_fixed_prefix",
                      "steps": steps, "native_owner_used": False}
            write(output / name / f"episode{number:05d}.json", record)
            records.append(record)
        parent_cpu, elapsed = time.process_time() - started[0], time.perf_counter() - started[1]
        summary[name] = {"episodes": len(records), "accuracy": _mean(records, "correct"),
                         "mean_reads": reads, "actual_reads": reads * len(records),
                         "mean_utility": _mean(records, "utility"), "read_price": price,
                         "mean_paid_read_cost": price * reads,
                         "model_cpu_seconds": sum(row["model_cpu_seconds"] for row in records),
                         "parent_cpu_seconds": parent_cpu, "native_child_cpu_seconds": 0.0,
                         "elapsed_wall_seconds": elapsed, "full_execution_cpu_seconds": parent_cpu,
                         "full_execution_cpu_per_episode": parent_cpu / len(records),
                         "model_and_child_cpu_per_episode": _mean(records, "model_cpu_seconds"),
                         "native_owner_used": False,
                         "episodes_ledger": [{key: row[key] for key in (
                             "episode", "actual_reads", "correct", "utility", "stop_reason",
                             "model_updates_executed", "model_updates_avoided")} for row in records]}
    write(output / "SUMMARY.json", summary)
    return summary


def cost_scenarios(cohorts, recovery, search_cpu, protocol, *, shared_setup_cpu=0.0,
                   summary_search_cpu=None):
    grid = protocol["native_evaluation"]["cpu_cost_scenarios"]
    rows = []
    for cohort in cohorts:
        for policy, record in cohort["results"].items():
            # Charge an entire separate recovery verification run once. Its
            # duplicated prefix/suffix work is not hidden in inference averages.
            recovery_cpu = recovery.get(policy, {}).get("full_execution_cpu_seconds", 0.0)
            for count in grid["amortization_episode_counts"]:
                for cpu_price in grid["utility_units_per_cpu_second"]:
                    infer = record["full_execution_cpu_per_episode"]
                    amortized_cpu = (search_cpu / count + infer + recovery_cpu / count
                                     + shared_setup_cpu / count)
                    rows.append({"policy": policy, "read_price": cohort["read_price"],
                                 "deployment_episodes_scenario": count,
                                 "utility_units_per_cpu_second_scenario": cpu_price,
                                 "accuracy": record["accuracy"], "mean_reads": record["mean_reads"],
                                 "read_only_utility": record["mean_utility"],
                                 "full_training_search_cpu_amortized": (search_cpu if summary_search_cpu is None else summary_search_cpu) / count,
                                 "charged_training_cpu_amortized": search_cpu / count,
                                 "measured_execution_cpu_per_episode": infer,
                                 "recovery_verification_cpu_amortized": recovery_cpu / count,
                                 "shared_setup_charge": shared_setup_cpu / count,
                                 "scenario_utility": record["mean_utility"] - cpu_price * amortized_cpu})
    return rows


def run_study(training_run, data, freeze, output, protocol_path=PACKAGE / "PROTOCOL.json", binary=None):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    clock = time.process_time(), time.perf_counter()
    protocol = _json(protocol_path)
    initial_sources = source_identity()
    write(output / "REQUEST.json", {
        "started_at_utc": datetime.now(timezone.utc).isoformat(),
        "training_run": str(training_run), "data": str(data), "source_freeze": str(freeze),
        "protocol_path": str(protocol_path), "protocol_sha256": sha256(protocol_path),
        "source_sha256": initial_sources, "native_evaluation": protocol["native_evaluation"],
        "selection": "All protocol arms, prices and first32 fixed before reading native outcomes",
        "recovery_accounting": "Main inference excludes deliberate recovery; separate first-episode recovery verification is charged once per scenario population",
    })
    try:
        torch.set_num_threads(1)
        model, x, dt, labels, ids, identity = load_locked_checkpoint(training_run, data, protocol, freeze)
        write(output / "INPUT_IDENTITY.json", {**identity, "native_binary": MANIFEST,
                                               "torch_version": torch.__version__, "torch_threads": torch.get_num_threads()})
        binary = binary or restored_binary()
        cohorts = []
        for price in protocol["native_evaluation"]["read_costs"]:
            directory = output / ("price_" + format(price, ".3f").replace(".", "p"))
            live_root = directory / "native"
            live = run_live(model, x, dt, labels, price, live_root, binary=binary,
                            episode_ids=ids, recover_first=False, provenance=identity)
            records = collect_native(live_root, live, price)
            records.update(run_references(model, x, dt, labels, ids, price, directory / "references"))
            cohort = {"read_price": price, "results": records}
            write(directory / "LEDGER.json", cohort)
            cohorts.append(cohort)
        recovery_root = output / "recovery_verification"
        recovery_live = run_live(model, x[:1], dt[:1], labels[:1], 0.0, recovery_root,
                                 binary=binary, episode_ids=ids[:1], recover_first=True,
                                 provenance={**identity, "scope": "separate recovery verification, not utility cohort"})
        recovered = collect_native(recovery_root, recovery_live, 0.0)
        first_price = protocol["native_evaluation"]["read_costs"][0]
        first_directory = output / ("price_" + format(first_price, ".3f").replace(".", "p")) / "native"
        verify_recovered_trajectory(first_directory, recovery_root, recovered)
        # The controller has no read-price input. Explicitly check the expected
        # identical correctness/read decisions without dropping any scenario.
        actions = [[(row["correct"], row["actual_reads"]) for row in value["episodes_ledger"]]
                   for value in cohorts[0]["results"].values()]
        invariance = all(
            [[(row["correct"], row["actual_reads"]) for row in value["episodes_ledger"]]
             for value in cohort["results"].values()] == actions for cohort in cohorts[1:])
        if not invariance:
            raise ValueError("Frozen price-independent policy/reference changed decisions across prices")
        if source_identity() != initial_sources:
            raise ValueError("Execution source changed during the native evaluation")
        if sha256(protocol_path) != _json(output / "REQUEST.json")["protocol_sha256"]:
            raise ValueError("Protocol changed during native evaluation")
        parent_cpu = time.process_time() - clock[0]
        policy_parent_cpu = (sum(row["parent_cpu_seconds"] for cohort in cohorts
                                 for row in cohort["results"].values())
                             + sum(row["parent_cpu_seconds"] for row in recovered.values()))
        shared_setup_cpu = parent_cpu - policy_parent_cpu
        if shared_setup_cpu < 0:
            raise ValueError("Shared setup CPU attribution became negative")
        scenarios = cost_scenarios(cohorts, recovered,
                                   identity["training_charge"]["charged_training_cpu_seconds"], protocol,
                                   shared_setup_cpu=shared_setup_cpu,
                                   summary_search_cpu=identity["training_charge"]["full_training_search_cpu_seconds"])
        write(output / "COST_SCENARIOS.json", {"schema": "hcsn-native-cpu-scenarios.v1",
              "formula": protocol["native_evaluation"]["cpu_cost_scenarios"]["formula"],
              "execution_scope": "All per-policy Python CPU including model/signals/adapter/receipts plus exact native child PID CPU; no deliberate recovery in main cohort",
              "recovery_scope": "Entire separate first-episode verification replay, including its prefix/suffix model work, charged once; not a pure restart-time estimate",
              "shared_setup_charge_cpu_seconds": shared_setup_cpu,
              "shared_overhead_scope": "Measured shared checkpoint loading, source verification and ledger/report preparation outside policy loops is charged once/N in every standalone-policy deployment scenario. Do not add separate policy scenarios together; this deliberately retains the full shared experimental overhead rather than dividing it among policies",
              "accounting_cutoff": "CPU measured after episode/price ledgers, recovery checks and source verification; final COST_SCENARIOS/SUMMARY serialization is outside this self-measurement cutoff",
              "scenario_only": True, "energy_measured": False, "rows": scenarios})
        result = {"schema": "hcsn-trained-native-study.v1", "status": "completed",
                  "cohort_episodes": len(x), "cohorts": cohorts,
                  "recovery_verification": recovered, "price_independent_decisions_verified": invariance,
                  "training_charge": identity["training_charge"],
                  "separate_causal_fixture": {"path": "../native001/SUMMARY.json",
                      "sha256": sha256(PACKAGE / "results/native001/SUMMARY.json"),
                      "scope": "Four individual channel interventions from identical durable prefix states; not classification utility evidence"},
                  "parent_cpu_seconds": parent_cpu,
                  "attributed_policy_parent_cpu_seconds": policy_parent_cpu,
                  "unallocated_driver_parent_cpu_seconds": parent_cpu - policy_parent_cpu,
                  "shared_setup_charge_cpu_seconds": shared_setup_cpu,
                  "unallocated_cpu_scope": "Legacy detail field for overhead outside policy loops; now explicitly charged once/N as shared_setup_charge in every independent policy scenario",
                  "elapsed_wall_seconds": time.perf_counter() - clock[1],
                  "native_child_cpu_seconds": sum(row["native_child_cpu_seconds"] for cohort in cohorts
                      for name, row in cohort["results"].items() if name in POLICIES)
                      + sum(row["native_child_cpu_seconds"] for row in recovered.values()),
                  "limitations": [
                      "A 32-episode fixed descriptive cohort from one selected checkpoint; no population or significant-advantage claim",
                      "Three hand-specified frozen policies; no heldout fitting and no task-Bellman optimality claim",
                      "Read price is an accounting scenario, not a controller input; the controller does not adapt its actions to price",
                      "Checkpoint training supervises final query targets; early-prefix confidence is not calibrated for stopping",
                      "Deliberate recovery recreates the neural object in the same Python interpreter and restarts the real native child; true Python-process restart evidence is separate in scaling002",
                      "Main latency includes native durability/guards, intentional terminal probes and local receipt overhead; it is an audited research execution cost",
                      "Native authority stays DENY_ALL; neither hardware energy nor production deployment is measured"]}
        write(output / "SUMMARY.json", result)
        return result
    except Exception as error:
        write(output / "FAILURE.json", {"error_type": type(error).__name__, "error": str(error),
              "traceback": traceback.format_exc(), "parent_cpu_seconds": time.process_time() - clock[0],
              "elapsed_wall_seconds": time.perf_counter() - clock[1],
              "partial_results_preserved": True})
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--training-run", type=Path, required=True)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--source-freeze", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--protocol", type=Path, default=PACKAGE / "PROTOCOL.json")
    parser.add_argument("--binary", type=Path)
    args = parser.parse_args()
    result = run_study(args.training_run, args.data, args.source_freeze, args.output, args.protocol, args.binary)
    print(json.dumps({"status": result["status"], "cohort_episodes": result["cohort_episodes"],
                      "read_costs": [row["read_price"] for row in result["cohorts"]],
                      "output": str(args.output)}, sort_keys=True))


if __name__ == "__main__":
    main()
