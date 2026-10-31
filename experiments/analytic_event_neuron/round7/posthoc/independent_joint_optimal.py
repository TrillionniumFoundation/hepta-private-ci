"""Post-freeze optimal action reference for each fixed finite Round7 cell.

No trained head enters the reference Bellman recursion. This module independently
enumerates oracle.transition_distribution and solves the public/latent product
DAG. It does not optimize the cell, certify a continuous QVI, or alter registered
comparisons. All costs are the existing utility proxies, not physical energy.
"""

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import gzip
import hashlib
import io
import json
from pathlib import Path
import platform
import time
import unittest

import numpy as np
import torch

from .. import oracle
from ..data import task_configuration
from ..model import load_model
from ..study import checkpoint_path, verify_freeze
from ..task import ACTIONS, State, features, legal_actions


COMPUTE_PRICE = 0.0005
EVENT_PRICE = 0.0002
TIE_TOLERANCE = 1e-10
FROZEN_SHA256 = "3cda25b5fc17774e624d590679267066b51a9246072801c53453ee964b2202f0"
MODES = ("clocked", "first_passage", "continuous", "direct", "first_passage_temperature")


@dataclass
class PublicGraph:
    states: list
    configurations: list
    starts: list
    state_configuration: np.ndarray
    legal: np.ndarray
    reward: np.ndarray
    edges: dict
    forward_order: list


@dataclass
class Kernel:
    transition: np.ndarray
    events: np.ndarray
    initial: np.ndarray
    drive: np.ndarray
    n_grid: int
    maximum_mass_error: float
    maximum_deployment_normalization_change: float


@dataclass
class Solution:
    q_after: np.ndarray
    value_before: np.ndarray
    actions: np.ndarray
    initial_values: np.ndarray


def build_public_graph(configurations):
    """Enumerate legal public transitions without joint_control's graph code."""
    states, ids, starts, edges = [], {}, [], {}

    def register(state):
        if state not in ids:
            ids[state] = len(states)
            states.append(state)
        return ids[state]

    for configuration in configurations:
        starts.append(register(State(configuration, remaining_budget=configuration.budget)))
    cursor = 0
    while cursor < len(states):
        state = states[cursor]
        for a, action in enumerate(ACTIONS):
            if action not in legal_actions(state):
                continue
            outcomes = []
            total = 0.0
            for probability, successor, reward in oracle.transition_distribution(state, action):
                if probability < 0 or not np.isfinite([probability, reward]).all():
                    raise ValueError("invalid external transition")
                if probability == 0:
                    continue
                if successor.tick != state.tick + 1:
                    raise ValueError("external transition must advance one decision tick")
                target = -1 if successor.terminated else register(successor)
                outcomes.append((probability, target, reward))
                total += probability
            if abs(total - 1.0) > 1e-12:
                raise ValueError("external transition mass does not sum to one")
            edges[cursor, a] = tuple(outcomes)
        cursor += 1
    legal = np.zeros((len(states), len(ACTIONS)), dtype=bool)
    reward = np.zeros((len(states), len(ACTIONS)), dtype=np.float64)
    for (i, a), outcomes in edges.items():
        legal[i, a] = True
        reward[i, a] = sum(p * r for p, _, r in outcomes)
    if not legal[:, ACTIONS.index("STOP")].all():
        raise ValueError("every public state must permit STOP")
    configuration_ids = {p: i for i, p in enumerate(configurations)}
    return PublicGraph(states, list(configurations), starts,
                       np.array([configuration_ids[s.parameters] for s in states]),
                       legal, reward, edges, sorted(range(len(states)), key=lambda i: states[i].tick))


@torch.no_grad()
def prepare_kernel(model, graph):
    """Use only frozen content, drive, transition and initialization; no Q head."""
    inputs = torch.tensor(np.stack([features(s) for s in graph.states]), dtype=torch.float64)
    _, drive = model.encode(inputs)
    count, latent = len(graph.states), model.core.n_states
    if model.mode == "direct":
        transition = torch.eye(latent, dtype=torch.float64).expand(count, -1, -1)
        events = torch.zeros(count, latent, 2, dtype=torch.float64)
    else:
        transition, events = model.core.transition_matrix(drive)
    matrix, event_count = transition.numpy().copy(), events.sum(-1).numpy().copy()
    row_mass = matrix.sum(-1)
    maximum_mass_error = float(np.max(np.abs(row_mass - 1.0)))
    if (not np.isfinite(matrix).all() or not np.isfinite(event_count).all()
            or matrix.min() < -1e-12 or maximum_mass_error > 1e-10):
        raise ValueError("frozen transition failed the finite Markov validity gate")
    expected_events = np.zeros_like(event_count)
    expected_events[:, :model.n_grid] = matrix[:, :model.n_grid, model.n_grid:].sum(-1)
    if np.max(np.abs(expected_events - event_count)) > 1e-11:
        raise ValueError("event reward disagrees with active-to-refractory transition mass")
    # policy.py clips/normalizes only roundoff before a sampled hard-state draw.
    deployed = np.clip(matrix, 0.0, None)
    deployed /= deployed.sum(-1, keepdims=True)
    return Kernel(matrix, event_count, model.initial(1)[0].numpy().copy(), drive.numpy().copy(),
                  model.n_grid, maximum_mass_error, float(np.max(np.abs(deployed - matrix))))


@torch.no_grad()
def network_greedy_actions(model, graph):
    """The trained head is used only for the comparison policy, never Q*."""
    inputs = torch.tensor(np.stack([features(s) for s in graph.states]), dtype=torch.float64)
    content, _ = model.encode(inputs)
    q = model.state_action_values(inputs, content)[:, :, 1, :].numpy()
    return np.where(graph.legal[:, None, :], q, -np.inf).argmax(-1)


def solve(graph, kernel, *, policy=None, compute_price=COMPUTE_PRICE, event_price=EVENT_PRICE):
    """Backward finite Bellman recursion; policy=None computes the optimum.

    Q_after excludes the already incurred current event fee. V_before includes
    that fee and the transition before observing z_after and choosing an action.
    All later event, reset, recovery and compute effects enter through V_next.
    """
    count, latent = kernel.transition.shape[:2]
    q_after = np.full((count, latent, len(ACTIONS)), -np.inf, dtype=np.float64)
    before = np.zeros((count, latent), dtype=np.float64)
    actions = np.zeros((count, latent), dtype=np.int64)
    if policy is not None and (policy.shape != actions.shape or
                              not graph.legal[np.arange(count)[:, None], policy].all()):
        raise ValueError("comparison policy must choose one legal action at every state")
    for i in reversed(graph.forward_order):
        for a in np.flatnonzero(graph.legal[i]):
            q_after[i, :, a] = graph.reward[i, a] - compute_price
            for probability, successor, _ in graph.edges[i, a]:
                if successor >= 0:
                    q_after[i, :, a] += probability * before[successor]
        actions[i] = q_after[i].argmax(-1) if policy is None else policy[i]
        after = q_after[i, np.arange(latent), actions[i]]
        before[i] = kernel.transition[i] @ after - event_price * kernel.events[i]
    return Solution(q_after, before, actions, before[graph.starts] @ kernel.initial)


def advantage_act(graph, optimum):
    """REPAIR/STOP versus READ/WAIT; forced act states have undefined margin."""
    margin = np.full(optimum.actions.shape, np.nan, dtype=np.float64)
    comparable = graph.legal[:, :2].any(-1)
    margin[comparable] = (optimum.q_after[comparable, :, 2:].max(-1) -
                          optimum.q_after[comparable, :, :2].max(-1))
    return margin


def forward_audit(graph, kernel, optimum, comparison, *, compute_price=COMPUTE_PRICE,
                  event_price=EVENT_PRICE):
    """Forward deployed-policy occupancy, costs and performance-difference identity."""
    count, latent = comparison.actions.shape
    n_config = len(graph.configurations)
    before = np.zeros((count, latent), dtype=np.float64)
    for start in graph.starts:
        before[start] += kernel.initial / n_config
    after_all = np.zeros_like(before)
    margin = advantage_act(graph, optimum)
    rows = [dict(configuration_index=c, registered_return=0.0, task_return=0.0,
                 expected_decisions=0.0, expected_events=0.0, terminal_mass=0.0,
                 comparable_decision_mass=0.0, tie_decision_mass=0.0, forced_act_decision_mass=0.0,
                 wrong_group_decision_mass=0.0, optimal_action_regret_sum=0.0,
                 wrong_group_action_regret_sum=0.0, wrong_group_boundary_margin_sum=0.0)
            for c in range(n_config)]
    for i in graph.forward_order:
        after = before[i] @ kernel.transition[i]
        after_all[i] = after
        c = int(graph.state_configuration[i])
        row = rows[c]
        scaled = after * n_config
        events = float(before[i] @ kernel.events[i]) * n_config
        decisions = float(scaled.sum())
        selected = comparison.actions[i]
        task_reward = float(scaled @ graph.reward[i, selected])
        row["task_return"] += task_reward
        row["registered_return"] += task_reward - compute_price * decisions - event_price * events
        row["expected_decisions"] += decisions
        row["expected_events"] += events
        regret = optimum.q_after[i].max(-1) - optimum.q_after[i, np.arange(latent), selected]
        row["optimal_action_regret_sum"] += float(scaled @ regret)
        strict = np.isfinite(margin[i]) & (np.abs(margin[i]) > TIE_TOLERANCE)
        wrong = strict & ((selected >= 2) != (margin[i] > 0))
        row["comparable_decision_mass"] += float(scaled[strict].sum())
        row["wrong_group_decision_mass"] += float(scaled[wrong].sum())
        row["tie_decision_mass"] += float(scaled[np.isfinite(margin[i]) & ~strict].sum())
        row["forced_act_decision_mass"] += float(scaled[~np.isfinite(margin[i])].sum())
        row["wrong_group_action_regret_sum"] += float(scaled[wrong] @ regret[wrong])
        row["wrong_group_boundary_margin_sum"] += float(scaled[wrong] @ np.abs(margin[i, wrong]))
        for a in np.flatnonzero(graph.legal[i]):
            chosen_mass = after * (selected == a)
            for probability, successor, _ in graph.edges[i, a]:
                if successor >= 0:
                    before[successor] += probability * chosen_mass
                else:
                    row["terminal_mass"] += n_config * probability * float(chosen_mass.sum())
    for c, row in enumerate(rows):
        row["optimal_registered_return"] = float(optimum.initial_values[c])
        row["greedy_bellman_registered_return"] = float(comparison.initial_values[c])
        row["optimal_minus_greedy"] = float(optimum.initial_values[c] - comparison.initial_values[c])
        row["performance_difference_identity_error"] = abs(row["optimal_minus_greedy"] - row["optimal_action_regret_sum"])
        row["forward_backward_return_error"] = abs(row["registered_return"] - comparison.initial_values[c])
        row["wrong_group_rate_among_strict_comparable_decisions"] = (
            row["wrong_group_decision_mass"] / row["comparable_decision_mass"]
            if row["comparable_decision_mass"] else None)
        row["wrong_group_rate_among_all_decisions"] = row["wrong_group_decision_mass"] / row["expected_decisions"]
        row["compute_proxy_fee"] = compute_price * row["expected_decisions"]
        row["event_proxy_fee"] = event_price * row["expected_events"]
        if (row["optimal_minus_greedy"] < -1e-10 or row["performance_difference_identity_error"] > 1e-10
                or row["forward_backward_return_error"] > 1e-10 or abs(row["terminal_mass"] - 1) > 1e-10):
            raise AssertionError("optimality, mass, fee or regret identity failed")
    return rows, after_all, margin


def run_diagnostic(root, output):
    root, output = Path(root), Path(output)
    tables = output.with_name("JOINT_OPTIMAL_TABLES.jsonl.gz")
    if output.exists() or tables.exists():
        raise FileExistsError("preserve prior diagnostics; both output paths must be new")
    freeze = verify_freeze(root)
    if freeze["sha256"] != FROZEN_SHA256:
        raise ValueError("this diagnostic targets the stated Round7 freeze")
    from . import test_independent_joint_optimal as test_module
    stream = io.StringIO()
    result = unittest.TextTestRunner(stream=stream, verbosity=2).run(
        unittest.defaultTestLoader.loadTestsFromModule(test_module))
    if not result.wasSuccessful():
        raise AssertionError(stream.getvalue())
    started, cpu_started = time.perf_counter(), time.process_time()
    configurations = [task_configuration(i) for i in range(8)]
    graph = build_public_graph(configurations)
    records, table_index = [], []
    output.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(tables, "wt", encoding="utf-8", compresslevel=6) as table_stream:
        for mode in MODES:
            for seed in range(11, 16):
                checkpoint = checkpoint_path(root / "evidence", mode, "none", seed)
                original = checkpoint.read_bytes()
                model, metadata = load_model(checkpoint)
                kernel = prepare_kernel(model, graph)
                optimum = solve(graph, kernel)
                actions = network_greedy_actions(model, graph)
                comparison = solve(graph, kernel, policy=actions)
                rows, occupancy, margin = forward_audit(graph, kernel, optimum, comparison)
                optimal_rows, _, _ = forward_audit(graph, kernel, optimum, optimum)
                for row, optimal_row in zip(rows, optimal_rows):
                    row["optimal_policy_metrics"] = {key: optimal_row[key] for key in (
                        "registered_return", "task_return", "expected_decisions", "expected_events",
                        "compute_proxy_fee", "event_proxy_fee", "terminal_mass")}
                if checkpoint.read_bytes() != original:
                    raise AssertionError("checkpoint bytes changed")
                strict = np.isfinite(margin) & (np.abs(margin) > TIE_TOLERANCE)
                wrong = strict & ((actions >= 2) != (margin > 0))
                mean_gap = float(np.mean([r["optimal_minus_greedy"] for r in rows]))
                wrong_mass = sum(r["wrong_group_decision_mass"] for r in rows)
                comparable_mass = sum(r["comparable_decision_mass"] for r in rows)
                entry = {"mode": mode, "seed": seed, "checkpoint": str(checkpoint.relative_to(root)),
                         "checkpoint_sha256": hashlib.sha256(original).hexdigest(),
                         "checkpoint_unchanged": True, "configuration": model.configuration(),
                         "maximum_transition_mass_error": kernel.maximum_mass_error,
                         "maximum_deployment_row_normalization_change": kernel.maximum_deployment_normalization_change,
                         "optimal_registered_return_mean": float(optimum.initial_values.mean()),
                         "greedy_registered_return_mean": float(comparison.initial_values.mean()),
                         "optimal_minus_greedy_mean": mean_gap,
                         "wrong_group_rate_among_strict_comparable_decisions": wrong_mass / comparable_mass if comparable_mass else None,
                         "all_public_latent_cells_strict_comparable": int(strict.sum()),
                         "all_public_latent_cells_wrong_group": int(wrong.sum()),
                         "all_public_latent_cells_counts_include_unvisited_states": True,
                         "per_configuration": rows}
                records.append(entry)
                sparse_occupancy = [[int(i), int(z), float(occupancy[i, z])]
                                    for i, z in zip(*np.nonzero(occupancy))]
                raw = {"mode": mode, "seed": seed, "checkpoint_sha256": entry["checkpoint_sha256"],
                       "state_order": "public_states in JOINT_OPTIMAL_DIAGNOSTIC.json",
                       "latent_order": "active voltage nodes followed by refractory_plus, refractory_minus",
                       "q_star_after": np.where(np.isfinite(optimum.q_after), optimum.q_after, None).tolist(),
                       "advantage_act": np.where(np.isfinite(margin), margin, None).tolist(),
                       "optimal_actions": optimum.actions.tolist(), "head1_greedy_actions": actions.tolist(),
                       "hardgreedy_after_occupancy_uniform_eight_configs_sparse": sparse_occupancy}
                encoded = json.dumps(raw, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n"
                table_stream.write(encoded)
                table_index.append({"mode": mode, "seed": seed, "line_1_based": len(records),
                                    "uncompressed_line_bytes": len(encoded.encode()),
                                    "uncompressed_line_sha256": hashlib.sha256(encoded.encode()).hexdigest()})
                print(json.dumps({"mode": mode, "seed": seed, "gap": mean_gap,
                                  "wrong_group_rate": entry["wrong_group_rate_among_strict_comparable_decisions"]}), flush=True)
    after = verify_freeze(root)
    if after["sha256"] != freeze["sha256"]:
        raise AssertionError("freeze changed during diagnostic")
    mode_summaries = []
    for mode in MODES:
        selected = [row for row in records if row["mode"] == mode]
        cells = [c for row in selected for c in row["per_configuration"]]
        denominator = sum(c["comparable_decision_mass"] for c in cells)
        mode_summaries.append({"mode": mode, "checkpoints": len(selected),
                               "optimal_registered_return_mean": float(np.mean([r["optimal_registered_return_mean"] for r in selected])),
                               "greedy_registered_return_mean": float(np.mean([r["greedy_registered_return_mean"] for r in selected])),
                               "optimal_minus_greedy_mean": float(np.mean([r["optimal_minus_greedy_mean"] for r in selected])),
                               "maximum_checkpoint_configuration_gap": max(c["optimal_minus_greedy"] for c in cells),
                               "wrong_group_rate_among_strict_comparable_decisions": sum(c["wrong_group_decision_mass"] for c in cells) / denominator if denominator else None})
    report = {"status": "complete", "created_utc": datetime.now(timezone.utc).isoformat(),
              "classification": "post-freeze deterministic diagnostic; not a preregistered primary hypothesis",
              "frozen_manifest_sha256": freeze["sha256"], "frozen_inputs_unchanged": True,
              "frozen_input_count": len(freeze["manifest"]["files"]),
              "posthoc_source_sha256": {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                                        for path in (Path(__file__), Path(test_module.__file__))},
              "independent_posthoc_tests": {"status": "PASS", "tests_run": result.testsRun,
                                            "failures": len(result.failures), "errors": len(result.errors),
                                            "not_in_original_45_tests": True, "output": stream.getvalue(),
                                            "records": test_module.AUDIT_RECORDS},
              "cost_contract": {"compute_per_decision_including_STOP": COMPUTE_PRICE,
                                "event_per_active_to_refractory_transition": EVENT_PRICE,
                                "prices_are_utility_proxies_not_physical_measurements": True},
              "reference": {"q_after": "R_task(s,a)-compute+sum_snext P(snext|s,a) V_before(snext,z_after)",
                            "v_before": "sum_zafter T_s(z_before,z_after) max_legal_a Q_after(s,z_after,a)-event_price*expected_new_events(s,z_before)",
                            "A_act": "max_legal(REPAIR,STOP) Q_star_after - max_legal(READ,WAIT) Q_star_after",
                            "current_event_fee_is_sunk_in_Q_after": True, "reference_uses_network_head": False,
                            "numeric_precision": "FP64 finite-DAG expectations and maximization, subject to reported roundoff; not continuous diffusion exactness",
                            "head_comparison": "head1 greedy after a sampled latent-state transition; ideal kernel-law expectation, no trajectory sampling",
                            "tie_tolerance": TIE_TOLERANCE,
                            "forced_act_margin": "null when READ and WAIT are both unavailable",
                            "grouping_caveat": "REPAIR/STOP versus READ/WAIT is the requested action grouping; REPAIR can itself reveal information",
                            "scope": "Each optimum holds that checkpoint's encoder, drive, finite grid, boundary, noise, reset and recovery fixed. Controller observes public sufficient state and its realized internal state; no hidden truth or future innovations.",
                            "limits": "No architecture-wide optimum, learned voltage-threshold optimality, continuum QVI, calibration guarantee, physical energy optimum, or deployed wall-time upper bound is implied."},
              "configuration_indices": list(range(8)), "configurations": [p.to_dict() for p in configurations],
              "action_order": list(ACTIONS), "public_state_count": len(graph.states),
              "public_states": [{"id": i, "configuration_index": int(graph.state_configuration[i]),
                                  "digest": state.digest(), "state": state.to_dict(),
                                  "legal_actions": [ACTIONS[a] for a in np.flatnonzero(graph.legal[i])]}
                                 for i, state in enumerate(graph.states)],
              "initial_public_state_ids": graph.starts, "checkpoints": records, "mode_summaries": mode_summaries,
              "full_tables": {"path": tables.name, "sha256": hashlib.sha256(tables.read_bytes()).hexdigest(),
                              "bytes": tables.stat().st_size, "encoding": "UTF-8 JSON Lines, lossless gzip",
                              "all_25_checkpoints_all_public_latent_cells_retained": True,
                              "illegal_action_Q_entries": "null; excluded from every maximization", "index": table_index},
              "diagnostic_runtime": {"wall_seconds_excluding_tests": time.perf_counter() - started,
                                     "process_cpu_seconds_excluding_tests": time.process_time() - cpu_started,
                                     "python": platform.python_version(), "torch": torch.__version__,
                                     "numpy": np.__version__, "torch_threads": torch.get_num_threads()}}
    output.write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    torch.set_num_threads(1)
    output = args.output or args.root / "evidence" / "JOINT_OPTIMAL_DIAGNOSTIC.json"
    report = run_diagnostic(args.root, output)
    print(json.dumps({"status": report["status"], "checkpoints": len(report["checkpoints"]),
                      "table_bytes": report["full_tables"]["bytes"]}), flush=True)


if __name__ == "__main__":
    main()
