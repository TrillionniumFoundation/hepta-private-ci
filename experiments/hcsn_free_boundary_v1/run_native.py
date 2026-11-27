"""Run original-owner channel interventions and optional trained-model traces.

All reported actions and durable transitions come from the pinned native host.
The intervention cohort is engineering validation, not a neural utility trial.
"""

import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import shutil
import time

from .native_bridge import (
    MANIFEST, OBJECTIVE, POLICIES, NativeSession, Signals, UPSTREAM,
    file_hashes, profile, restored_binary,
)


PREFIX = Signals(0.8, 0.1, 0.1, 0.1)
TAIL_STOP = Signals(-1, -1, 1, 0)
INTERVENTIONS = {
    "continuation": [Signals(-0.3, -0.3, 0.1, 0.1), Signals(0.3, -0.3, 0.1, 0.1)],
    "margin": [Signals(0, -0.2, 0.1, 0.1), Signals(0, 0.3, 0.1, 0.1)],
    "risk": [Signals(0.2, -0.2, 0.1, 0.1), Signals(0.2, -0.2, 0.9, 0.1)],
    "activity": [Signals(0, -0.2, 0.1, 0.1), Signals(0, -0.2, 0.1, 0.9)],
}


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")


def protocol():
    model = UPSTREAM.digest("fixed-engineering-channel-witness-v1")
    return {
        "schema": "hcsn-causal-native-protocol.v1", "model_sha256": model,
        "objective": OBJECTIVE, "source_state": "identical durable prefix bytes",
        "prefix": asdict(PREFIX), "tail_stop": asdict(TAIL_STOP),
        "interventions": {k: [asdict(x) for x in v] for k, v in INTERVENTIONS.items()},
        "policies": {p: profile(p, model) for p in POLICIES},
        "read_cost": 0.02,
        "acceptance": "each channel changes actual native action and downstream reads; exact cold replay",
        "heldout_selection": "all supplied episodes, no outcome-based removal",
        "interpretation": "engineering causality, not learned native-head or neural efficacy",
    }


def interventions(output, binary, plan):
    model, case, seed = plan["model_sha256"], "matched", 17
    original = output / "common_prefix"
    first = NativeSession(original, binary=binary, policy="causal_maxout",
                          model_digest=model, case=case, seed=seed)
    prefix = first.tick(PREFIX, context={"phase": "common-prefix"})
    if prefix["native"]["effective_action"] != "keep":
        raise RuntimeError("Common prefix must permit a legal successor")
    prefix_status = first.bridge.rpc({"command": "Status"})
    prefix_cost = first.close()
    frozen = file_hashes(original / case)
    write(output / "prefix.json", {"status": prefix_status, "event": prefix,
                                   "file_sha256": frozen, "cost": prefix_cost})
    comparisons = []
    for channel, variants in INTERVENTIONS.items():
        rows = []
        changed = [key for key in asdict(variants[0])
                   if asdict(variants[0])[key] != asdict(variants[1])[key]]
        if changed != [channel]:
            raise RuntimeError("Intervention must change exactly its named channel")
        for variant, signals in enumerate(variants):
            root = output / channel / str(variant)
            root.mkdir(parents=True)
            shutil.copytree(original / case, root / case)
            if file_hashes(root / case) != frozen:
                raise RuntimeError("Matched branch state is not byte-identical")
            session = NativeSession(root, binary=binary, policy="causal_maxout",
                                    model_digest=model, case=case, seed=seed, resume=True)
            if session.open_receipt["status"] != prefix_status:
                raise RuntimeError("Cold restored branch frontier differs")
            result = session.tick(signals, context={"channel": channel, "variant": variant})
            if result["native"]["checkpoint_before"] != prefix_status["checkpoint"]:
                raise RuntimeError("Intervention did not start from the common checkpoint")
            retry = session.verify_retry()
            continued_reads = 0
            if not session.terminal:
                session.tick(TAIL_STOP, context={"phase": "executed-next-read"})
                continued_reads = 1
            terminal = session.verify_terminal()
            cost = session.close()
            row = {"variant": variant, "signal": asdict(signals),
                   "common_prefix_state_sha256": UPSTREAM.digest(frozen),
                   "first_divergence_tick": 2, "action": result["native"]["effective_action"],
                   "executed_reads_including_prefix": 2 + continued_reads,
                   "paid_read_cost": plan["read_cost"] * (2 + continued_reads),
                   "native_events": session.events, "resume": session.open_receipt,
                   "exact_retry": retry, "terminal_probe": terminal, "process_cost": cost}
            write(root / "RESULT.json", row)
            rows.append(row)
        passed = (rows[0]["action"] != rows[1]["action"] and
                  rows[0]["executed_reads_including_prefix"] != rows[1]["executed_reads_including_prefix"])
        if not passed:
            raise RuntimeError(f"No actual causal action effect for {channel}")
        comparisons.append({"channel": channel, "passed": passed,
                            "actions": [x["action"] for x in rows],
                            "reads": [x["executed_reads_including_prefix"] for x in rows],
                            "paid_costs": [x["paid_read_cost"] for x in rows]})
    return {"passed": True, "matched_branch_count": 8, "channels": comparisons,
            "prefix_file_sha256": frozen,
            "scope": "declared feature interventions; not naturally occurring task performance"}


def recovery(output, binary, plan):
    model, case, seed = plan["model_sha256"], "recovery", 29
    signals = [PREFIX, Signals(0.4, -0.2, 0.1, 0.2), TAIL_STOP]
    runs, costs = [], []
    for label in ("uninterrupted", "cold"):
        root = output / label
        session = NativeSession(root, binary=binary, policy="causal_maxout",
                                model_digest=model, case=case, seed=seed)
        rows = []
        for index, signal in enumerate(signals):
            if index == 1 and label == "cold":
                costs.append(session.close())
                session = NativeSession(root, binary=binary, policy="causal_maxout",
                                        model_digest=model, case=case, seed=seed, resume=True)
            row = session.tick(signal, context={"sequence": "recovery", "index": index})
            rows.append({k: row["native"][k] for k in
                         ("checkpoint_before", "checkpoint_after", "activation_q24", "readout", "effective_action")})
        session.verify_terminal()
        costs.append(session.close())
        runs.append(rows)
    if runs[0] != runs[1]:
        raise RuntimeError("Cold native recovery changed actions or numerical states")
    result = {"passed": True, "bitwise_numerical_action_records": runs,
              "process_costs": costs, "new_native_process": True,
              "python_process_restarted": False}
    write(output / "RESULT.json", result)
    return result


def run_traces(path, output, binary):
    raw = Path(path).read_bytes()
    dataset = json.loads(raw)
    if dataset["schema"] != "hcsn-native-prefix-traces.v1" or dataset["split"] != "heldout":
        raise ValueError("Explicit heldout causal-prefix trace schema required")
    model = dataset["source_model_sha256"]
    episodes = dataset["episodes"]
    if not episodes:
        raise ValueError("Empty native trace evaluation")
    write(output / "TRACE_IDENTITY.json", {
        "sha256": hashlib.sha256(raw).hexdigest(), "model_sha256": model,
        "provenance": dataset.get("provenance"), "episodes": len(episodes)})
    summary = {}
    for policy in POLICIES:
        records = []
        for number, episode in enumerate(episodes):
            steps = episode["steps"]
            if not 1 <= len(steps) <= 512:
                raise ValueError("Native episode length outside bounded contract")
            cost = float(episode["read_cost"])
            if cost < 0:
                raise ValueError("Read cost must be nonnegative")
            case = f"episode{number:05d}"
            root = output / policy / case
            session = NativeSession(root, binary=binary, policy=policy, model_digest=model,
                                    case=case, seed=int(episode.get("seed", number)))
            count = 0
            for index, step in enumerate(steps):
                signals = Signals(**{k: step[k] for k in ("continuation", "margin", "risk", "activity")})
                session.tick(signals, context={"dataset_sha256": hashlib.sha256(raw).hexdigest(),
                                               "episode": episode["id"], "prefix": index + 1})
                count += 1
                if session.terminal:
                    break
            guard = session.verify_terminal() if session.terminal else None
            correct = int(steps[count - 1]["prediction"] == episode["label"])
            record = {"id": episode["id"], "policy": policy, "reads": count,
                      "avoided_reads": len(steps) - count, "correct": correct,
                      "read_cost": cost * count, "utility": correct - cost * count,
                      "stop_reason": "native_stop" if session.terminal else "finite_horizon",
                      "events": session.events, "terminal_probe": guard,
                      "native_cost": session.close()}
            write(root / "RESULT.json", record)
            records.append(record)
        summary[policy] = {"episodes": len(records),
                           "mean_accuracy": sum(x["correct"] for x in records) / len(records),
                           "mean_utility": sum(x["utility"] for x in records) / len(records),
                           "total_reads": sum(x["reads"] for x in records),
                           "native_stops": sum(x["stop_reason"] == "native_stop" for x in records),
                           "native_cpu_seconds": sum(x["native_cost"]["child_cpu_seconds"] for x in records)}
    write(output / "SUMMARY.json", summary)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--binary", type=Path)
    parser.add_argument("--traces", type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    plan = protocol()
    write(args.output / "PROTOCOL.json", plan)
    inputs = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
              for p in Path(__file__).parent.glob("*.py")}
    write(args.output / "SOURCE_IDENTITY.json", {"inputs": inputs, "native": MANIFEST})
    binary = args.binary or restored_binary()
    started = time.process_time(), time.perf_counter()
    results = {"interventions": interventions(args.output / "interventions", binary, plan),
               "cold_recovery": recovery(args.output / "recovery", binary, plan)}
    if args.traces:
        results["heldout_traces"] = run_traces(args.traces, args.output / "traces", binary)
    results.update({"parent_cpu_seconds": time.process_time() - started[0],
                    "elapsed_wall_seconds": time.perf_counter() - started[1],
                    "energy_measured": False, "production_authority": False,
                    "trained_native_head": False})
    write(args.output / "SUMMARY.json", results)
    print(json.dumps({"output": str(args.output), "causal_channels": 4,
                      "cold_recovery": True, "heldout_traces": bool(args.traces)}))


if __name__ == "__main__":
    main()
