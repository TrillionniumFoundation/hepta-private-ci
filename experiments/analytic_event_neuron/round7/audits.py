"""Frozen conditional-value, artifact-broker, and policy-resumption audits.

No audit outcome selects a model. Conditional Qpi is measured after the current
neural transition, so the current event charge is already sunk.
"""

import argparse
import copy
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import time

import numpy as np
import torch

from . import oracle
from .broker import BrokerClient
from .data import task_configuration
from .joint_control import build_graph, evaluate_graph
from .model import load_model
from .policy import Policy, run_episode
from .task import ACTIONS, State, conditional_episode, generate_episode, initial_state, legal_actions, step


CONDITIONAL_BASE = 50_000_000
BROKER_BASE = 70_000_000
FUTURE_POLICY_OFFSET = 1_500_000_000
COMPUTE_PRICE = 0.0005
EVENT_PRICE = 0.0002
CONTINUATIONS = 64
AUDIT_CONFIGURATIONS = (0, 3, 5, 6)


def _write(path, record):
    path.write_text(json.dumps(record, sort_keys=True, indent=2, allow_nan=False) + "\n")


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def future_policy(model, after_snapshot, future_seed):
    """Keep conditioned internal state/call count; replace only future randomness."""
    snapshot = copy.deepcopy(after_snapshot)
    snapshot["seed"] = int(future_seed)
    result = Policy(model, head=snapshot["head"], deployment=snapshot["deployment"], seed=future_seed)
    result.restore(snapshot)
    return result


def conditional_returns(model, state, prefix_episode, after_snapshot, *, base_seed, count=CONTINUATIONS):
    """Paired Qpi samples at (public state, z_after), before the task action.

    Each replicate draws new posterior truth, unread sources, and future neural
    innovations. All candidate actions share those innovations within a replicate.
    """
    returns = {action: [] for action in legal_actions(state)}
    future_seeds = []
    for replicate in range(count):
        seed = base_seed + replicate
        episode = conditional_episode(state, seed, prefix_episode)
        neural_seed = FUTURE_POLICY_OFFSET + seed
        future_seeds.append(neural_seed)
        for action in returns:
            first = step(state, action, episode)
            # Exactly the q_targets phase: current compute is charged, current
            # neural event is already realized and is excluded from every action.
            value = first.reward - COMPUTE_PRICE
            if not first.done:
                policy = future_policy(model, after_snapshot, neural_seed)
                tail = run_episode(policy, episode, start_state=first.state)
                value += tail["registered_return"]
            returns[action].append(float(value))
    return returns, future_seeds


def _standard_error(values):
    values = np.asarray(values, dtype=float)
    return float(values.std(ddof=1) / np.sqrt(len(values))) if len(values) > 1 else None


def _public_key(state):
    return replace(state, total_cost=0.0, answer=0)


@torch.no_grad()
def conditional_value_audit(models, output):
    started = time.perf_counter()
    graph = build_graph()
    lookup = {}
    for index, state in enumerate(graph.states):
        lookup.setdefault(_public_key(state), []).append(index)
    records = []
    for fit_index, (fit_seed, model, checkpoint) in enumerate(models):
        _, exact = evaluate_graph(model, graph, policy="greedy", head=1)
        for configuration_index, configuration in enumerate(AUDIT_CONFIGURATIONS):
            for phase in (0, 2):
                prefix_index = 2 * configuration_index + int(phase == 2)
                base = CONDITIONAL_BASE + fit_index * 1_000_000 + prefix_index * 10_000
                episode = generate_episode(base + 9000, task_configuration(configuration))
                state = initial_state(episode)
                policy = Policy(model, head=1, deployment="hard", seed=800_000_000 + base)
                history = []
                for _ in range(phase):
                    _, prediction = policy.act(state)
                    result = step(state, "WAIT", episode)
                    history.append({"state": state.to_dict(), "forced_action": "WAIT",
                                    "internal_state_after": policy.snapshot(),
                                    "event_count": prediction["event_count"]})
                    state = result.state
                if state.terminated:
                    raise ValueError("registered audit prefix unexpectedly terminated")
                before_snapshot = policy.snapshot()
                selected, prediction = policy.act(state)
                after_snapshot = policy.snapshot()
                latent = int(policy.mass.argmax(dim=-1))
                indices = lookup[_public_key(state)]
                exact_rows = exact["q_targets"][indices, latent, :]
                if float((exact_rows - exact_rows[0]).abs().max()) > 1e-10:
                    raise AssertionError("sunk prefix costs changed the conditional joint value")
                exact_values = exact_rows[0].tolist()
                samples, future_seeds = conditional_returns(model, state, episode, after_snapshot,
                                                             base_seed=base, count=CONTINUATIONS)
                stop = np.asarray(samples["STOP"])
                teacher = oracle.action_values(state)
                actions = {}
                for action, values in samples.items():
                    index = ACTIONS.index(action)
                    advantage = np.asarray(values) - stop
                    mean, se = float(np.mean(values)), _standard_error(values)
                    actions[action] = {
                        "returns": values, "mean": mean, "standard_error": se,
                        "descriptive_95_interval": [mean - 1.96 * se, mean + 1.96 * se],
                        "paired_advantages_over_STOP": advantage.tolist(),
                        "mean_advantage_over_STOP": float(advantage.mean()),
                        "advantage_standard_error": _standard_error(advantage),
                        "learned_full_return_head": prediction["q"][index],
                        "exact_joint_greedy_Qpi": exact_values[index],
                        "original_task_Qstar": teacher[action],
                        "mc_minus_exact_joint": mean - exact_values[index],
                        "learned_minus_exact_joint": prediction["q"][index] - exact_values[index],
                    }
                records.append({
                    "fit_seed": fit_seed, "checkpoint": str(checkpoint),
                    "checkpoint_sha256": _sha(checkpoint), "configuration_index": configuration,
                    "prefix_index": prefix_index, "forced_prefix_waits": phase,
                    "prefix_fixture_seed": episode.seed, "public_state": state.to_dict(),
                    "public_state_digest": state.digest(), "history": history,
                    "policy_before_current_transition": before_snapshot,
                    "policy_after_current_transition": after_snapshot,
                    "conditioned_latent_index": latent, "model_selected_action": selected,
                    "already_incurred_current_event_cost_excluded": EVENT_PRICE * prediction["event_count"],
                    "continuations_per_action": CONTINUATIONS, "conditional_seed_base": base,
                    "future_internal_seeds_shared_across_actions": future_seeds,
                    "actions": actions,
                })
    record = {
        "schema": "hepta.round7.conditional-qpi.v1", "records": records,
        "phase": "after current neural transition, before first task action; current event cost sunk",
        "truth_sampling": "H drawn from public posterior for every replicate; observed evidence preserved",
        "future_neural_sampling": "new future seed for each replicate, paired across first-action branches",
        "exact_reference": "finite joint task/internal-state greedy policy Qpi, not continuous QVI",
        "teacher_scope": "original finite-task Qstar omits neural compute/event proxies and is different",
        "learned_scope": "Qstar-pretrained then soft-policy joint-Qpi-refined head, audited under greedy deployment",
        "uncertainty": "within-prefix conditional Monte Carlo SE; 95% intervals are descriptive",
        "wall_seconds": time.perf_counter() - started,
    }
    _write(output / "conditional_qpi.json", record)
    return {"prefixes": len(records), "continuations_per_action": CONTINUATIONS,
            "action_branches": sum(len(r["actions"]) for r in records),
            "wall_seconds": record["wall_seconds"]}


def _restore_windows(model, policy_seed, states, predictions, folder, case):
    """Replay actual public inputs through serialized policy checkpoints."""
    reference = Policy(model, head=1, deployment="hard", seed=policy_seed)
    windows = []
    for index, state in enumerate(states):
        if index:
            snapshot = reference.snapshot()
            started = time.perf_counter_ns()
            payload = (json.dumps(snapshot, sort_keys=True, separators=(",", ":")) + "\n").encode()
            path = folder / f"{case}_before_{index}.json"
            path.write_bytes(payload)
            serialize_write_ns = time.perf_counter_ns() - started
            restored = Policy(model, head=1, deployment="hard", seed=policy_seed)
            started = time.perf_counter_ns()
            restored.restore(json.loads(path.read_bytes()))
            restore_ns = time.perf_counter_ns() - started
            matches = []
            for future in range(index, len(states)):
                action, prediction = restored.act(states[future])
                expected = predictions[future]
                matches.append(action == expected["action"] and prediction["mass"] == expected["mass"]
                               and prediction["q"] == expected["q"]
                               and prediction["state_sha256"] == expected["state_sha256"])
            windows.append({"before_decision": index, "snapshot_file": str(path),
                            "snapshot_sha256": hashlib.sha256(payload).hexdigest(),
                            "snapshot_bytes": len(payload), "serialize_write_ns": serialize_write_ns,
                            "restore_read_ns": restore_ns, "continuation_decisions": len(matches),
                            "exact_actions_mass_q_and_state_hash": all(matches)})
        action, predicted = reference.act(state)
        expected = predictions[index]
        if action != expected["action"] or predicted["mass"] != expected["mass"]:
            raise AssertionError("reference policy differs from the actual broker trace")
    return windows


@torch.no_grad()
def broker_and_resume_audit(model, checkpoint, output, artifact_root):
    started = time.perf_counter()
    snapshots = output / "snapshots"
    snapshots.mkdir()
    records, manifest, resume_records = [], [], []
    action_counts = {action: 0 for action in ACTIONS}
    transport = {"request_utf8": 0, "response_utf8": 0}
    with BrokerClient(artifact_root) as broker:
        for case_index in range(16):
            case = f"round7_broker_{case_index:02d}"
            seed = BROKER_BASE + case_index
            policy_seed = 1_700_000_000 + case_index
            parameters = task_configuration(case_index)
            first = broker.start(seed, parameters)
            if not first["ok"]:
                raise RuntimeError("broker start failed: " + json.dumps(first))
            for key in transport:
                transport[key] += first.get("transport_bytes", {}).get(key, 0)
            state = State.from_dict(first["state"])
            policy = Policy(model, head=1, deployment="hard", seed=policy_seed)
            trace, states, predictions = [], [], []
            while not state.terminated:
                states.append(state)
                action, prediction = policy.act(state)
                predictions.append({"action": action, **prediction})
                response = broker.step(action)
                for key in transport:
                    transport[key] += response.get("transport_bytes", {}).get(key, 0)
                trace.append({"public_state": state.to_dict(), "action": action,
                              "prediction": prediction, "response": response})
                if not response["ok"]:
                    _write(output / f"{case}_FAILURE.json", {"setup": first, "trace": trace})
                    raise RuntimeError("broker task failed; failure and incurred costs retained")
                action_counts[response["info"]["executed_action"]] += 1
                state = State.from_dict(response["state"])
            artifact = response["artifact"]
            posterior = artifact["output"]["posterior_at_commit"]
            manifest.append({
                "case": case, "artifact_path": artifact["path"], "expected_sha256": artifact["sha256"],
                "native_parameters": {"mean": 2 * posterior - 1,
                                      "variance": 4 * posterior * (1 - posterior) + 0.01,
                                      "lower": -0.25, "upper": 0.25},
                "parameter_mapping": "Gaussian proxy from the public binary-fact posterior at STOP: mean=2p-1, variance=4p(1-p)+0.01, fixed cuts ±0.25. Not the learned neuron distribution; native feedback verifies artifact integrity only.",
            })
            records.append({"case": case, "fixture_seed": seed, "policy_seed": policy_seed,
                            "setup": first, "trace": trace, "artifact": artifact})
            windows = _restore_windows(model, policy_seed, states, predictions, snapshots, case)
            resume_records.append({"case": case, "windows": windows})
    all_windows = [window for record in resume_records for window in record["windows"]]
    summary = {"episodes": len(records), "action_counts": action_counts,
               "all_client_readbacks_verified": all(r["artifact"]["client_readback_verified"] for r in records),
               "actual_jsonl_transport_bytes": transport,
               "snapshot_windows": len(all_windows),
               "all_resume_windows_exact": all(w["exact_actions_mass_q_and_state_hash"] for w in all_windows),
               "snapshot_bytes": sum(w["snapshot_bytes"] for w in all_windows),
               "restore_read_ns": sum(w["restore_read_ns"] for w in all_windows),
               "wall_seconds": time.perf_counter() - started}
    _write(output / "broker_trace.json", {"checkpoint": str(checkpoint), "checkpoint_sha256": _sha(checkpoint),
                                          "records": records, "summary": summary})
    _write(output / "native_manifest.json", {"records": manifest})
    _write(output / "snapshot_audit.json", {
        "scope": "Policy/internal-state and public-input continuation only; not restoration of an entire worker or production process",
        "records": resume_records, "summary": summary,
    })
    return summary


def run(root, output, artifact_root, checkpoints=None):
    from .study import checkpoint_path
    root, output = Path(root), Path(output)
    protocol = json.loads((root / "PROTOCOL.json").read_text())
    frozen = root / "FROZEN_MANIFEST.json"
    manifest = json.loads(frozen.read_text())
    if not protocol["frozen"]:
        raise ValueError("freeze source/config/models before generating audit fixtures")
    for name, expected in manifest["files"].items():
        if _sha(root / name) != expected:
            raise ValueError("frozen bytes changed: " + name)
    if output.exists():
        raise FileExistsError("audit output must be new; prior attempts are retained")
    paths = checkpoints or [checkpoint_path(root / "evidence", "first_passage", "none", seed)
                            for seed in range(11, 16)]
    models = []
    for path in paths:
        model, metadata = load_model(path)
        if model.mode != "first_passage":
            raise ValueError("this registered audit requires first_passage checkpoints")
        models.append((metadata["seed"], model, Path(path)))
    models.sort(key=lambda item: item[0])
    if len({seed for seed, _, _ in models}) != len(models):
        raise ValueError("duplicate fitted seed")
    selected = next((entry for entry in models if entry[0] == 11), None)
    if selected is None:
        raise ValueError("the registered 16 broker tasks require fitted seed 11")
    output.mkdir(parents=True)
    started = time.perf_counter()
    try:
        conditional = conditional_value_audit(models, output)
        broker = broker_and_resume_audit(selected[1], selected[2], output, artifact_root)
        summary = {"status": "complete", "frozen_manifest_sha256": _sha(frozen),
                   "fit_seeds": [seed for seed, _, _ in models],
                   "full_five_fit_audit": [seed for seed, _, _ in models] == list(range(11, 16)),
                   "conditional": conditional, "broker": broker,
                   "wall_seconds": time.perf_counter() - started}
    except Exception as error:
        _write(output / "AUDIT_FAILURE.json", {"status": "incomplete", "type": type(error).__name__,
                                               "message": str(error), "wall_seconds": time.perf_counter() - started})
        raise
    _write(output / "AUDIT_SUMMARY.json", summary)
    return summary


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=str(Path(__file__).parent))
    parser.add_argument("--output", required=True)
    parser.add_argument("--artifact-root", required=True)
    parser.add_argument("--checkpoint", action="append")
    args = parser.parse_args()
    torch.set_num_threads(1)
    result = run(args.root, args.output, args.artifact_root, args.checkpoint)
    print(json.dumps(result, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
