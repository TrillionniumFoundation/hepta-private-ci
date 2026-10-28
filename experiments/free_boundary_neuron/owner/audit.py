"""Reconstruct outcomes from observed paths and reopen every original-owner journal.

This auditor does not invoke the experiment runner, generate new environment
draws, alter the candidate, or substitute numerical parity for task efficacy.
"""

import argparse
from collections import Counter, defaultdict
import hashlib
import json
import math
from pathlib import Path
import statistics
import time

from experiments.free_boundary_neuron.provenance import verify
from .common import Native, charge, open_request, registered_starts, sha, write


def validate_roster(index, protocol, model):
    starts = registered_starts(model, protocol)
    expected = {
        (arm, seed, state)
        for arm in protocol["arms"]
        for seed in protocol["noise_seeds"]
        for state in starts
    }
    rows = index["episodes"]
    actual = [(row["arm"], row["seed"], row["initial_state"]) for row in rows]
    if (
        not index["complete"]
        or len(expected) != protocol["episodes"]
        or len(rows) != len(expected)
        or set(actual) != expected
    ):
        raise ValueError("Incomplete or duplicated registered episode roster")
    if len({(seed, state) for _, seed, state in actual}) != protocol["paired_contexts"]:
        raise ValueError("Registered paired context count mismatch")
    for row in rows:
        if row["case"] != f"{row['arm']}.s{row['initial_state']}.n{row['seed']}":
            raise ValueError("Case path is not bound to registered arm/start/seed")


def execution_gates(arms, exact_paths, contexts):
    return {
        "all_registered_paths_match_exact_dp": exact_paths == contexts,
        "every_arm_applied_readout": all(
            row["applied_readout_count"] > 0 for row in arms.values()
        ),
        "candidate_stop_and_continue_exercised": all(
            arms["free_boundary"]["applied_actions"].get(action, 0) > 0
            for action in ("stop", "continue")
        ),
        "no_arm_all_native_fallback": all(
            not row["all_native_fallback"] for row in arms.values()
        ),
    }


def expected_action(model, state, remaining, policy):
    stop = model["states"][state] - model["payoff_cost"]
    if policy["kind"] == "constant_threshold":
        if remaining == 0:
            return "stop" if stop > 0 else "abstain"
        if model["states"][state] <= policy["lower"]:
            return "abstain"
        if model["states"][state] >= policy["upper"]:
            return "stop" if stop > 0 else "abstain"
        return "continue"
    continuation = (
        0.0
        if remaining == 0
        else -model["running_cost"] * model["dt"]
        + math.exp(-model["rho"] * model["dt"])
        * math.fsum(
            p * v
            for p, v in zip(model["transition"][state], model["value"][remaining - 1])
        )
    )
    if max(stop, continuation) <= 0:
        return "abstain"
    return "stop" if remaining == 0 or stop >= continuation else "continue"


def noise(seed, start, step):
    raw = json.dumps(
        ["free-boundary.noise.v1", seed, start, step],
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    value = int.from_bytes(hashlib.sha256(raw).digest()[:8], "big") >> 11
    return (value + 0.5) / (1 << 53)


def reconstruct(record, model):
    state, remaining = record["initial_state"], record["initial_remaining"]
    total, discount = 0.0, 1.0
    actions = Counter()
    for number, step in enumerate(record["steps"]):
        if (step["step"], step["state"], step["remaining"]) != (
            number,
            state,
            remaining,
        ):
            raise ValueError("Observed transition chain mismatch")
        expected = (
            "abstain"
            if step["native_abstain"]
            else expected_action(model, state, remaining, record["policy"])
        )
        if step["action"] != expected or abs(step["discount"] - discount) > 1e-12:
            raise ValueError("Admitted action or elapsed discount mismatch")
        actions[expected] += 1
        if expected != "continue":
            if (
                number != len(record["steps"]) - 1
                or record["terminal_reason"] != expected
            ):
                raise ValueError("Recorded work continues after stopping")
            if expected == "stop":
                total += discount * (model["states"][state] - model["payoff_cost"])
            break
        total -= discount * model["running_cost"] * model["dt"]
        draw = noise(record["seed"], record["initial_state"], number)
        if draw != step["transition_uniform"]:
            raise ValueError("Paired counter stream drift")
        cumulative, successor = 0.0, None
        for index, probability in enumerate(model["transition"][state]):
            cumulative += probability
            if draw < cumulative:
                successor = index
                break
        discount *= math.exp(-model["rho"] * model["dt"])
        if successor is None:
            if (
                step["transition_outcome"] != "killed"
                or record["terminal_reason"] != "killed"
                or number != len(record["steps"]) - 1
            ):
                raise ValueError("Absorbing killing event mismatch")
            break
        if successor != step["transition_outcome"]:
            raise ValueError("Exported transition row was not used")
        state, remaining = successor, remaining - 1
    if abs(total - record["realized_discounted_task_return"]) > 1e-12:
        raise ValueError("Terminal utility reconstruction mismatch")
    native_calls = [
        row["response"]["result"]
        for row in record["rpc"]
        if row["response"]["ok"]
        and row["response"]["result"].get("native_transition_executed")
    ]
    if len(native_calls) != len(record["steps"]) or any(
        row["owner_authority"] != "DENY_ALL" for row in native_calls
    ):
        raise ValueError("Native receipt count or authority mismatch")
    for row, step in zip(native_calls, record["steps"]):
        if (
            row["checkpoint_after"] != step["checkpoint"]
            or row["native_abstain"] != step["native_abstain"]
        ):
            raise ValueError("Native receipt is not bound to reported trajectory")
        if not row["native_abstain"] and row["readout"]["action"] != step["action"]:
            raise ValueError("Executed readout differs from declared action")
    if record["work"] != charge(record["rpc"]):
        raise ValueError("Complete work accounting mismatch")
    return total, actions


def audit(root, model_path, binary, source_seal, output):
    began, cpu = time.monotonic_ns(), time.process_time_ns()
    source = verify(source_seal)
    index = json.loads((root / "INDEX.json").read_text())
    start = json.loads((root / "START.json").read_text())
    protocol_path = Path(__file__).with_name("PROTOCOL.json")
    protocol = json.loads(protocol_path.read_text())
    if (
        sha(protocol_path) != start["protocol_sha256"]
        or sha(model_path) != start["model_sha256"]
        or index["profile_sha256"] != start["model_sha256"]
        or sha(binary) != start["binary_sha256"]
    ):
        raise ValueError("Run/model/binary completion identity mismatch")
    for key in ("source_commit", "seal_sha256", "verified_inputs"):
        if start["source"][key] != source[key] or index["source"][key] != source[key]:
            raise ValueError("Source seal differs between registered run and audit")
    model = json.loads(Path(model_path).read_text())
    validate_roster(index, protocol, model)
    tuning = json.loads((root / "THRESHOLD_TUNING.json").read_text())
    if (
        sha(root / "THRESHOLD_TUNING.json") != index["threshold_tuning_sha256"]
        or tuning["selected"] != index["selection"]
    ):
        raise ValueError("Threshold tuning receipt differs from indexed selection")
    grouped, contexts, counters = (
        defaultdict(list),
        defaultdict(dict),
        defaultdict(Counter),
    )
    native_verification = Counter()
    replay_processes = []
    file_index = {}
    for summary in index["episodes"]:
        directory = root / summary["case"]
        record = json.loads((directory / "EPISODE.json").read_text())
        if any(record.get(key) != value for key, value in summary.items()):
            raise ValueError("Index and episode record disagree")
        if (
            record["profile_sha256"] != start["model_sha256"]
            or record["initial_remaining"] != protocol["horizon"]
            or record["owner_authority"] != "DENY_ALL"
        ):
            raise ValueError("Episode model, horizon or authority binding mismatch")
        expected_policy = {"kind": record["arm"]}
        if record["arm"] == "constant_threshold":
            expected_policy.update(
                {key: index["selection"][key] for key in ("lower", "upper")}
            )
        if record["policy"] != expected_policy:
            raise ValueError(
                "Episode policy differs from registered arm or tuned baseline"
            )
        required = {"IDENTITY.json", "owner.journal", "owner.witness", "events.jsonl"}
        if record["terminal_reason"] == "killed":
            required.add("FINISH.json")
        if set(record["native_files"]) != required:
            raise ValueError("Incomplete native file inventory")
        for name, identity in record["native_files"].items():
            path = directory / name
            if (
                path.stat().st_size != identity["bytes"]
                or sha(path) != identity["sha256"]
            ):
                raise ValueError(
                    "Persisted owner bytes changed before independent replay"
                )
        identity = json.loads((directory / "IDENTITY.json").read_text())
        if (
            identity["case"] != record["case"]
            or identity["policy"] != record["policy"]
            or identity["model_sha256"] != start["model_sha256"]
            or identity["binary_sha256"] != start["binary_sha256"]
            or identity["calibration_sha256"] != sha(root / "ENCODER_DOMAIN.json")
        ):
            raise ValueError("Native runtime identity differs from episode identity")
        value, actions = reconstruct(record, model)
        native = Native(binary, root)
        request = open_request(
            record["case"], model_path, root / "ENCODER_DOMAIN.json", record["policy"]
        )
        status = native.call({"command": "Resume", "request": request})["status"]
        last = record["steps"][-1]
        if (
            status["sequence"] != len(record["steps"])
            or status["checkpoint"] != last["checkpoint"]
            or not status["terminal"]
        ):
            raise ValueError("Original-owner full journal replay mismatch")
        duplicate = native.call(
            {"command": "Observe", "observation": last["observation"]}
        )
        if (
            duplicate["native_transition_executed"]
            or duplicate["checkpoint_after"] != last["checkpoint"]
        ):
            raise ValueError(
                "Independent cold replay re-executed an acknowledged event"
            )
        native.call({"command": "Close"})
        process = native.close()
        replay_processes.append(process)
        work = charge(native.rows)
        native_verification.update(
            {k: v for k, v in work.items() if k != "peak_transient_allocation_bytes"}
        )
        write(
            directory / "AUDIT_REPLAY.json",
            {"rpc": native.rows, "process": process, "work": work},
        )
        for name, identity in record["native_files"].items():
            if sha(directory / name) != identity["sha256"]:
                raise ValueError("Verification changed committed owner files")
        grouped[record["arm"]].append(record)
        context = (record["seed"], record["initial_state"])
        if record["arm"] in contexts[context]:
            raise ValueError("Duplicate evaluation context")
        contexts[context][record["arm"]] = record
        counters[record["arm"]].update(actions)
        file_index[str((directory / "EPISODE.json").relative_to(root))] = sha(
            directory / "EPISODE.json"
        )
    pair_differences = {
        "free_boundary_minus_exact_dp": [],
        "free_boundary_minus_constant_threshold": [],
    }
    exact_paths = 0
    for arms in contexts.values():
        if set(arms) != {"free_boundary", "exact_dp", "constant_threshold"}:
            raise ValueError("Incomplete paired arm set")
        candidate = arms["free_boundary"]
        reference = arms["exact_dp"]

        def semantic(row):
            return [
                (x["state"], x["remaining"], x["action"], x.get("transition_outcome"))
                for x in row["steps"]
            ]

        exact_paths += semantic(candidate) == semantic(reference)
        for arm in ("exact_dp", "constant_threshold"):
            pair_differences[f"free_boundary_minus_{arm}"].append(
                candidate["realized_discounted_task_return"]
                - arms[arm]["realized_discounted_task_return"]
            )
    summary = {}
    for arm, records in grouped.items():
        native_abstentions = sum(
            step["native_abstain"] for row in records for step in row["steps"]
        )
        applied = Counter(
            step["action"]
            for row in records
            for step in row["steps"]
            if not step["native_abstain"]
        )
        persisted = Counter()
        for row in records:
            persisted.update(
                {
                    name: identity["bytes"]
                    for name, identity in row["native_files"].items()
                }
            )
        summary[arm] = {
            "episodes": len(records),
            "mean_task_return": statistics.mean(
                x["realized_discounted_task_return"] for x in records
            ),
            "actions": dict(counters[arm]),
            "terminal_reasons": dict(Counter(x["terminal_reason"] for x in records)),
            "native_abstention_count": native_abstentions,
            "voluntary_abstention_count": applied["abstain"],
            "applied_readout_count": sum(applied.values()),
            "applied_actions": dict(applied),
            "all_native_fallback": sum(applied.values()) == 0,
            "persisted_native_file_bytes": dict(persisted),
            "owner_ticks": sum(x["work"]["owner_ticks"] for x in records),
            "all_original_kernel_executions": sum(
                x["work"]["all_original_kernel_executions"] for x in records
            ),
            "avoided_future_tick_opportunities": sum(
                x["avoided_future_tick_opportunities"] for x in records
            ),
            "child_cpu_seconds": sum(
                p["child_user_cpu_seconds"] + p["child_system_cpu_seconds"]
                for x in records
                for p in x["physical_processes"]
            ),
            "process_wall_seconds": sum(
                p["process_wall_ns"] for x in records for p in x["physical_processes"]
            )
            / 1e9,
            "complete_work": {
                key: sum(x["work"][key] for x in records)
                for key in records[0]["work"]
                if key != "peak_transient_allocation_bytes"
            },
            "peak_transient_allocation_bytes": max(
                x["work"]["peak_transient_allocation_bytes"] for x in records
            ),
        }
    gates = execution_gates(summary, exact_paths, len(contexts))
    result = {
        "schema": "hepta.free-boundary.owner-audit.v1",
        "passed": all(gates.values()),
        "execution_gates": gates,
        "source": source,
        "episodes": len(index["episodes"]),
        "paired_contexts": len(contexts),
        "exact_dp_path_matches": exact_paths,
        "arms": summary,
        "paired_mean_return_differences": {
            key: statistics.mean(values) for key, values in pair_differences.items()
        },
        "paired_return_differences": pair_differences,
        "episode_sha256": file_index,
        "verification_work": dict(native_verification),
        "verification_child_cpu_seconds": sum(
            p["child_user_cpu_seconds"] + p["child_system_cpu_seconds"]
            for p in replay_processes
        ),
        "audit_cpu_ns": time.process_time_ns() - cpu,
        "audit_wall_ns": time.monotonic_ns() - began,
        "claims": {
            "actual_original_owner_executed": True,
            "native_authority": "DENY_ALL",
            "learned_end_to_end_snn": False,
            "production_qualification": False,
            "energy_measured": False,
            "sampled_comparisons_are_descriptive": True,
            "dp_parity_is_not_algorithmic_superiority": True,
        },
    }
    write(output, result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for field in ("root", "model", "binary", "source-seal", "output"):
        parser.add_argument("--" + field, type=Path, required=True)
    args = parser.parse_args()
    result = audit(
        args.root.resolve(),
        args.model.resolve(),
        args.binary.resolve(),
        args.source_seal.resolve(),
        args.output.resolve(),
    )
    print(
        json.dumps(
            {
                "passed": result["passed"],
                "episodes": result["episodes"],
                "exact_dp_path_matches": result["exact_dp_path_matches"],
                "paired_mean_return_differences": result[
                    "paired_mean_return_differences"
                ],
            },
            indent=2,
        )
    )
