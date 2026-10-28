"""Execute the registered finite-MDP study through the original native owner."""

import argparse
import json
import math
from pathlib import Path
import time

import numpy as np

from experiments.free_boundary_neuron.provenance import verify
from .common import (
    Native,
    charge,
    digest,
    encoder_proof,
    open_request,
    permit,
    registered_starts,
    sha,
    uniform,
    write,
)


def threshold_reference(model, starts):
    """Exact known-model tuning, with all candidates fixed before sampled trials."""
    started, cpu = time.monotonic_ns(), time.process_time_ns()
    states = np.asarray(model["states"])
    stop = np.asarray(model["stop_value"])
    transition = np.asarray(model["transition"])
    discount = math.exp(-model["rho"] * model["dt"])
    cost = model["running_cost"] * model["dt"]
    horizon = len(model["value"]) - 1
    grid = list(states[::5]) + [model["payoff_cost"]]
    lowers = sorted(
        set(
            [float(states[0] - 1)]
            + [float(x) for x in grid if x <= model["payoff_cost"]]
        )
    )
    uppers = sorted(
        set(
            [float(states[-1] + 1)]
            + [float(x) for x in grid if x >= model["payoff_cost"]]
        )
    )
    rows = []
    for lower in lowers:
        for upper in uppers:
            value = np.maximum(stop, 0)
            for _ in range(horizon):
                continuation = -cost + discount * (transition @ value)
                value = np.where(
                    states <= lower,
                    0,
                    np.where(states >= upper, np.maximum(stop, 0), continuation),
                )
            rows.append(
                {
                    "lower": lower,
                    "upper": upper,
                    "model_expected_return": float(np.mean(value[starts])),
                }
            )
    selected = max(
        rows,
        key=lambda row: (row["model_expected_return"], row["lower"], -row["upper"]),
    )
    return {
        "selected": selected,
        "candidates": rows,
        "lower_grid": lowers,
        "upper_grid": uppers,
        "bellman_terms": len(rows) * horizon * len(states) ** 2,
        "wall_ns": time.monotonic_ns() - started,
        "cpu_ns": time.process_time_ns() - cpu,
        "selection_information": "Complete registered MDP only; no sampled outcomes or future noise",
    }


def episode(binary, root, model_path, calibration, model, policy, seed, start):
    arm = policy["kind"]
    case = f"{arm}.s{start}.n{seed}"
    request = open_request(case, model_path, calibration, policy)
    native = Native(binary, root)
    native.call({"command": "Open", "request": request})
    processes, calls, steps = [], [], []
    state, remaining = start, len(model["value"]) - 1
    value, discount, fee = 0.0, 1.0, model["running_cost"] * model["dt"]
    recovered = False
    while True:
        event = {
            "event_id": f"observation.{len(steps)}",
            "state": state,
            "remaining": remaining,
            "evidence_digest": digest(
                ["observed-grid-state", case, len(steps), state, remaining]
            ),
        }
        output = native.call({"command": "Observe", "observation": event})
        duplicate = native.call({"command": "Observe", "observation": event})
        if (
            duplicate["native_transition_executed"]
            or duplicate["checkpoint_after"] != output["checkpoint_after"]
        ):
            raise ValueError("Duplicate event changed owner state")
        action = "abstain" if output["native_abstain"] else output["readout"]["action"]
        row = {
            "step": len(steps),
            "state": state,
            "remaining": remaining,
            "observation": event,
            "action": action,
            "native_abstain": output["native_abstain"],
            "discount": discount,
            "checkpoint": output["checkpoint_after"],
        }
        steps.append(row)
        if action != "continue":
            if action == "stop":
                value += discount * model["stop_value"][state]
            final = native.call({"command": "Status"})
            native.call(
                {
                    "command": "Observe",
                    "observation": dict(
                        event,
                        event_id="forbidden-after-stop",
                        remaining=max(0, remaining - 1),
                    ),
                },
                expect_error=True,
            )
            after = native.call({"command": "Status"})
            if final != after:
                raise ValueError("Post-stop request changed native state")
            reason = action
            break
        value -= discount * fee
        u = uniform(seed, start, len(steps) - 1)
        row["transition_uniform"] = u
        cdf = np.cumsum(model["transition"][state])
        next_state = int(np.searchsorted(cdf, u, side="right"))
        discount *= math.exp(-model["rho"] * model["dt"])
        if next_state == len(model["states"]):
            row["transition_outcome"] = "killed"
            evidence = digest(["observed-kill", case, len(steps), u])
            native.call({"command": "Killed", "evidence_digest": evidence})
            reason = "killed"
            break
        row["transition_outcome"] = next_state
        state, remaining = next_state, remaining - 1
        if remaining < 0:
            raise ValueError("Continuation beyond registered horizon")
        if not recovered:
            status = native.call({"command": "Close"})
            calls.extend(native.rows)
            processes.append(native.close())
            native = Native(binary, root)
            restored = native.call({"command": "Resume", "request": request})["status"]
            if restored != status:
                raise ValueError("Cold process recovery changed native checkpoint")
            duplicate = native.call({"command": "Observe", "observation": event})
            if (
                duplicate["native_transition_executed"]
                or duplicate["checkpoint_after"] != output["checkpoint_after"]
            ):
                raise ValueError("Cold retry changed original owner")
            recovered = True
    native.call({"command": "Close"})
    calls.extend(native.rows)
    processes.append(native.close())
    directory = root / case
    files = {
        p.name: {"bytes": p.stat().st_size, "sha256": sha(p)}
        for p in directory.iterdir()
        if p.is_file()
    }
    record = {
        "schema": "hepta.free-boundary.owner-episode.v1",
        "case": case,
        "arm": arm,
        "policy": policy,
        "seed": seed,
        "initial_state": start,
        "initial_remaining": len(model["value"]) - 1,
        "terminal_reason": reason,
        "realized_discounted_task_return": value,
        "steps": steps,
        "rpc": calls,
        "physical_processes": processes,
        "work": charge(calls),
        "native_files": files,
        "avoided_future_tick_opportunities": remaining
        if reason in {"stop", "abstain"}
        else 0,
        "profile_sha256": sha(model_path),
        "owner_authority": "DENY_ALL",
        "independent_population_sample": False,
    }
    write(directory / "EPISODE.json", record)
    return {
        k: record[k]
        for k in (
            "case",
            "arm",
            "seed",
            "initial_state",
            "terminal_reason",
            "realized_discounted_task_return",
            "work",
            "avoided_future_tick_opportunities",
        )
    }


def execute(binary, model_path, destination, source_seal, build_receipt):
    began, cpu = time.monotonic_ns(), time.process_time_ns()
    source = verify(source_seal)
    build = json.loads(Path(build_receipt).read_text())
    if sha(binary) != build["binary_sha256"]:
        raise ValueError("Binary differs from recorded build")
    repository = Path(__file__).resolve().parents[3]
    for path, expected in build["source_sha256"].items():
        if sha(repository / path) != expected:
            raise ValueError(f"Compiled source drift: {path}")
    protocol_path = Path(__file__).with_name("PROTOCOL.json")
    protocol = json.loads(protocol_path.read_text())
    model = json.loads(Path(model_path).read_text())
    starts = registered_starts(model, protocol)
    destination.mkdir(parents=True, exist_ok=False)
    permit(destination)
    calibration = destination / "ENCODER_DOMAIN.json"
    encoder_proof(model_path, calibration)
    write(
        destination / "START.json",
        {
            "source": source,
            "protocol_sha256": sha(protocol_path),
            "model_sha256": sha(model_path),
            "binary_sha256": sha(binary),
            "build_receipt_sha256": sha(build_receipt),
            "authority": "DENY_ALL",
        },
    )
    tuning = threshold_reference(model, starts)
    write(destination / "THRESHOLD_TUNING.json", tuning)
    policies = [
        {"kind": "free_boundary"},
        {"kind": "exact_dp"},
        {
            "kind": "constant_threshold",
            "lower": tuning["selected"]["lower"],
            "upper": tuning["selected"]["upper"],
        },
    ]
    rows = []
    for start in starts:
        for seed in protocol["noise_seeds"]:
            for policy in policies:
                rows.append(
                    episode(
                        binary,
                        destination,
                        model_path,
                        calibration,
                        model,
                        policy,
                        seed,
                        start,
                    )
                )
    write(
        destination / "INDEX.json",
        {
            "schema": "hepta.free-boundary.owner-index.v1",
            "episodes": rows,
            "profile_sha256": sha(model_path),
            "source": verify(source_seal),
            "threshold_tuning_sha256": sha(destination / "THRESHOLD_TUNING.json"),
            "complete": len(rows) == protocol["episodes"],
            "selection": tuning["selected"],
            "orchestrator_cpu_ns": time.process_time_ns() - cpu,
            "run_wall_ns": time.monotonic_ns() - began,
            "claims": "Finite engineered MDP and original-owner composition only; no native authority or efficacy promotion",
        },
    )
    return {
        "episodes": len(rows),
        "directory": str(destination),
        "index_sha256": sha(destination / "INDEX.json"),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("binary", "model", "destination", "source-seal", "build-receipt"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    print(
        json.dumps(
            execute(
                args.binary.resolve(),
                args.model.resolve(),
                args.destination.resolve(),
                args.source_seal.resolve(),
                args.build_receipt.resolve(),
            ),
            indent=2,
        )
    )
