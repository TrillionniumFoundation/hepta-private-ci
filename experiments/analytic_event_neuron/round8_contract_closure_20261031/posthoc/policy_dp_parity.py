"""Match every heldout hard-policy trace to the finite DP's stage convention."""

import argparse
import gzip
import hashlib
import json
from pathlib import Path
import time

import numpy as np
import torch

from ...round7.posthoc.independent_joint_optimal import build_public_graph, prepare_kernel
from ...round7.task import ACTIONS, features
from ..calibration import load_calibrated
from ..protocol import configurations
from .independent_confirmation_audit import MODES, SEEDS, STAGES, verify_frozen


@torch.no_grad()
def run(root, output):
    root, output = Path(root), Path(output)
    if output.exists():
        raise FileExistsError(output)
    torch.set_num_threads(1)
    freeze = verify_frozen(root)
    started = time.perf_counter()
    graph = build_public_graph(configurations("heldout"))
    ids = {state.digest(): index for index, state in enumerate(graph.states)}
    x = torch.tensor(np.stack([features(state) for state in graph.states]), dtype=torch.float64)
    target = json.loads((root / "evidence/heldout_exact.json").read_text())
    expected = {(r["mode"], r["stage"], r["fit_seed"]): r["registered_return"] for r in target["records"]}
    kernels, q_tables, actions, values = {}, {}, {}, {}
    for mode in MODES:
        for seed in SEEDS:
            for stage in STAGES:
                model = load_calibrated(root / f"evidence/calibration_models/{mode}_none_{seed}_{stage}.json")[0]
                if (mode, seed) not in kernels:
                    kernels[mode, seed] = prepare_kernel(model, graph)
                kernel = kernels[mode, seed]
                content, _ = model.encode(x)
                q = model.state_action_values(x, content)[:, :, 1, :].numpy()
                chosen = np.where(graph.legal[:, None, :], q, -np.inf).argmax(-1)
                key = mode, stage, seed
                q_tables[key], actions[key] = q, chosen
                # Independent explicit recursion: first obtain the incoming
                # latent successor; choose its greedy action; incur one
                # decision fee; only then advance the public environment.
                before = np.zeros(kernel.transition.shape[:2], dtype=np.float64)
                for i in reversed(graph.forward_order):
                    after = np.zeros(model.core.n_states, dtype=np.float64)
                    for a in np.flatnonzero(graph.legal[i]):
                        candidate = np.full(model.core.n_states, graph.reward[i, a] - 0.0005)
                        for probability, successor, _ in graph.edges[i, a]:
                            if successor >= 0:
                                candidate += probability * before[successor]
                        after = np.where(chosen[i] == a, candidate, after)
                    before[i] = kernel.transition[i] @ after - 0.0002 * kernel.events[i]
                values[key] = float((before[graph.starts] @ kernel.initial).mean())
                if abs(values[key] - expected[key]) > 1e-12:
                    raise AssertionError("independent deployed-policy recursion differs")
    records, steps, q_error, event_error, boundary_proximity = 0, 0, 0.0, 0.0, 1.0
    with gzip.open(root / "evidence/confirmation_v1/trajectories.jsonl.gz", "rt", encoding="utf8") as stream:
        for line in stream:
            row = json.loads(line)
            parts = row["arm"].split("/")
            if row["regime"] != "heldout" or len(parts) != 3 or parts[0] not in MODES or parts[2] != "hard":
                continue
            mode, stage = parts[:2]
            key = mode, stage, row["fit_seed"]
            kernel = kernels[mode, row["fit_seed"]]
            previous = int(kernel.initial.argmax())
            for call, trace in enumerate(row["steps"]):
                public_digest = hashlib.sha256(json.dumps(trace["before"], sort_keys=True,
                    separators=(",", ":"), allow_nan=False).encode()).hexdigest()
                i = ids[public_digest]
                probabilities = np.clip(kernel.transition[i, previous], 0, None)
                probabilities /= probabilities.sum()
                payload = f"round7/policy/v1/{row['latent_seed']}/{call}/latent".encode()
                uniform = int.from_bytes(hashlib.sha256(payload).digest()[:8], "big") / 2**64
                cumulative = probabilities.cumsum()
                latent = min(len(probabilities) - 1, int(np.searchsorted(cumulative, uniform, side="right")))
                boundary_proximity = min(boundary_proximity, float(np.abs(cumulative - uniform).min()))
                prediction = trace["prediction"]
                mass = np.asarray(prediction["mass"])
                expected_mass = np.eye(1, len(mass), latent)[0]
                if not np.array_equal(mass, expected_mass):
                    raise AssertionError("DP incoming successor differs from deployed sampled state")
                if ACTIONS[actions[key][i, latent]] != trace["requested_action"]:
                    raise AssertionError("DP observes a different latent stage before action selection")
                discrepancy = float(np.abs(q_tables[key][i, latent] - prediction["q"]).max())
                q_error = max(q_error, discrepancy)
                event_error = max(event_error, abs(float(kernel.events[i, previous]) - prediction["expected_event_count"]))
                if discrepancy > 1e-12 or event_error > 1e-12:
                    raise AssertionError("batched DP readout or event probability differs")
                actual_event = int(previous < kernel.n_grid and latent >= kernel.n_grid)
                if prediction["event_count"] != actual_event:
                    raise AssertionError("sampled event charged at wrong stage")
                action = ACTIONS.index(trace["requested_action"])
                successor = trace["result"]["state"]
                if successor["terminated"]:
                    target_id = -1
                else:
                    digest = hashlib.sha256(json.dumps(successor, sort_keys=True,
                        separators=(",", ":"), allow_nan=False).encode()).hexdigest()
                    target_id = ids[digest]
                if not any(p > 0 and destination == target_id for p, destination, _ in graph.edges[i, action]):
                    raise AssertionError("deployed public successor is absent from the DP law")
                previous = latent
                steps += 1
            records += 1
    if records != 5 * 128 * 12 or verify_frozen(root) != freeze:
        raise AssertionError("incomplete hard matrix or changed frozen sources")
    result = {"schema": "round8-posthoc-policy-dp-parity-v1", "passed": True,
              "freeze_sha256": freeze, "models": len(q_tables), "heldout_trajectories": records,
              "incoming_latent_transitions_checked": steps,
              "maximum_Q_discrepancy": q_error, "maximum_expected_event_discrepancy": event_error,
              "minimum_uniform_to_cumulative_boundary_distance": boundary_proximity,
              "maximum_independent_recursion_return_error": max(abs(v - expected[k]) for k, v in values.items()),
              "checks": ["incoming transition before greedy action", "normalized categorical inverse CDF and shared RNG key",
                         "realized latent state carried to next decision", "current event fee counted exactly once",
                         "Q_after excludes sunk current event fee", "legal public successors", "complete future reset/recovery"],
              "limits": "This verifies the finite R7 kernel and hard policy. It does not establish continuous diffusion accuracy or evaluate the distinct mean policy.",
              "wall_seconds": time.perf_counter() - started,
              "source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    with output.open("x", encoding="utf8") as stream:
        json.dump(result, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
    print(json.dumps(result))
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    run(args.root, args.output or args.root / "evidence/final_policy_dp_parity.json")
