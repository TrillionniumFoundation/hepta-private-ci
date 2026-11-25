"""Causal delayed-information LQ study, within the existing E1–E6 prerequisites.

Known linear state = [editable theta, target belief]. A zero-mean Gaussian
innovation is revealed only after the third transition. All policies pay the
same physical trajectory objective. This synthetic control study executes no
HCSN, LLM, user trajectory, or adoption. No independent learning claim follows.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import sys
import time

import numpy as np

from . import pft_linear as pft


METHODS = (
    "full_riccati",
    "pft_compressed",
    "single_action_ridge",
    "full_horizon_gd",
    "blind_belief_ablation",
)
SPEC = dict(
    widths=[8, 32, 64],
    seeds=[113, 271, 419],
    initial_states=3,
    innovation_paths=4,
    horizon=6,
    reveal_transition=3,
    innovation_sigma=0.5,
    gd_iterations=32,
    stage_task=0.04,
    terminal_task=1.0,
    stage_retention=0.08,
    terminal_retention=0.4,
    initial_theta_sigma=0.4,
)


def source_identity():
    paths = [
        Path(__file__),
        Path(pft.__file__),
        Path(__file__).with_name("pft_horizon_tests.py"),
    ]
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}


def freeze(path):
    protocol = dict(
        schema="hepta.e1e6.pft-horizon-protocol.v1",
        specification=SPEC,
        source_sha256=source_identity(),
        methods=list(METHODS),
        frozen_at=datetime.now(timezone.utc).isoformat(),
        target_law="belief martingale; one independent N(0,sigma^2 I) increment after transition 3",
        information="action k observes x_k only; increment k is applied after action k",
        rls_scope="independent arithmetic check of the same single-action remaining-horizon ridge problem",
        gd_rule="32 zero-start gradient steps; step=1/lambda_max of complete remaining-horizon Hessian",
        acceptance="all registered episodes retained; numerical parity and causality only; no win threshold",
        cost="same stage/terminal task readout, old-output retention and action effort for every method",
        data_scope="fresh synthetic mechanism arrays, no inherited final panels or model calls",
    )
    with Path(path).open("x", encoding="utf-8") as out:
        json.dump(protocol, out, ensure_ascii=False, indent=2)
        out.write("\n")
    return protocol


def load_protocol(path):
    raw = Path(path).read_bytes()
    protocol = json.loads(raw)
    if (
        protocol.get("schema") != "hepta.e1e6.pft-horizon-protocol.v1"
        or protocol.get("specification") != SPEC
        or protocol.get("methods") != list(METHODS)
        or protocol.get("source_sha256") != source_identity()
    ):
        raise ValueError(
            "frozen protocol/source identity differs; do not silently change or retune"
        )
    return protocol, hashlib.sha256(raw).hexdigest()


def timed(ledger, phase, call):
    began = time.perf_counter_ns()
    try:
        return call()
    finally:
        ledger[phase] += time.perf_counter_ns() - began


def make_system(width, seed, theta, spec):
    rng = np.random.default_rng(seed + 1000 * width)
    orthogonal = np.linalg.qr(rng.normal(size=(width, width)))[0].T
    q, r, h = width // 2, width // 4, spec["horizon"]
    readout = orthogonal[:q]
    retention = 0.6 * orthogonal[:r] + 0.8 * orthogonal[q : q + r]
    direction = rng.normal(size=width)
    action_cost = (
        np.diag(np.linspace(0.15, 0.35, width))
        + 0.03 * np.outer(direction, direction) / width
    )
    A = [np.eye(2 * width) for _ in range(h)]
    E = [np.vstack((np.eye(width), np.zeros((width, width)))) for _ in range(h)]
    L, targets = [], []
    for k in range(h + 1):
        task = spec["terminal_task"] if k == h else spec["stage_task"]
        keep = spec["terminal_retention"] if k == h else spec["stage_retention"]
        L.append(
            np.vstack(
                (
                    np.sqrt(task) * np.c_[readout, -readout],
                    np.sqrt(keep) * np.c_[retention, np.zeros((r, width))],
                )
            )
        )
        targets.append(np.r_[np.zeros(q), np.sqrt(keep) * retention @ theta])
    return (A, E, L, targets, [action_cost] * h), readout, retention


def response(system, start):
    """Forward maps from current state and remaining actions; no future samples."""
    A, E, L, targets, costs = system
    h, width, dim = len(A), E[0].shape[1], len(A[0])
    total = (h - start) * width
    origin, action_map = np.eye(dim), np.zeros((dim, total))
    rows, origins, labels, penalty = [], [], [], np.zeros((total, total))
    for k in range(start, h + 1):
        rows.append(L[k] @ action_map)
        origins.append(L[k] @ origin)
        labels.append(targets[k])
        if k < h:
            selected = slice((k - start) * width, (k - start + 1) * width)
            penalty[selected, selected] = costs[k]
            action_map = A[k] @ action_map
            action_map[:, selected] += E[k]
            origin = A[k] @ origin
    G, O, target = np.vstack(rows), np.vstack(origins), np.concatenate(labels)
    H = G.T @ G + penalty
    whiten = np.linalg.solve(np.linalg.cholesky(costs[start]).T, np.eye(width))
    single = G[:, :width] @ whiten
    return dict(
        G=G,
        O=O,
        target=target,
        H=H,
        whiten=whiten,
        single=single,
        block_rows=len(L[0]),
        width=width,
    )


def prepare(system, ledger):
    A, E, L, targets, costs = system
    full = timed(ledger, "solve", lambda: pft.solve_lq(*system))
    bases, ranks = timed(
        ledger, "feature_response", lambda: pft.effective_action_bases(A, E, L, costs)
    )
    small, _ = timed(ledger, "solve", lambda: pft.reduce_actions(*system, bases=bases))
    maps = [
        timed(ledger, "feature_response", lambda k=k: response(system, k))
        for k in range(len(A))
    ]
    for mapping in maps:
        mapping["step"] = timed(
            ledger, "solve", lambda: 1.0 / np.linalg.eigvalsh(mapping["H"])[-1]
        )
    return dict(full=full, small=small, bases=bases, ranks=ranks, maps=maps)


def choose(method, state, k, prepared, iterations):
    """Only the current filtration enters; no innovation path is accepted here."""
    if method in ("full_riccati", "blind_belief_ablation"):
        policy = prepared["full"]
        observed = state.copy()
        if method == "blind_belief_ablation":
            observed[len(state) // 2 :] = 0.0
        return -policy["gains"][k] @ observed + policy["offsets"][k]
    if method == "pft_compressed":
        policy = prepared["small"]
        return prepared["bases"][k] @ (
            -policy["gains"][k] @ state + policy["offsets"][k]
        )
    mapping = prepared["maps"][k]
    residual = mapping["O"] @ state - mapping["target"]
    if method == "single_action_ridge":
        matrix = mapping["single"]
        reduced = pft.solve_normal(
            matrix.T @ matrix, -matrix.T @ residual, regularizer=1.0
        )
        return mapping["whiten"] @ reduced
    if method != "full_horizon_gd":
        raise ValueError("unregistered method")
    gradient_offset = mapping["G"].T @ residual
    controls = np.zeros(len(gradient_offset))
    for _ in range(iterations):
        controls -= mapping["step"] * (mapping["H"] @ controls + gradient_offset)
    return controls[: mapping["width"]]


def simulate(method, initial, innovations, prepared, spec, ledger):
    state, states, actions, rls_errors = initial.copy(), [initial.copy()], [], []
    policy = prepared["full"]
    for k in range(spec["horizon"]):
        action = timed(
            ledger,
            "solve",
            lambda: choose(method, state, k, prepared, spec["gd_iterations"]),
        )
        if method == "single_action_ridge":

            def check_rls():
                mapping = prepared["maps"][k]
                residual = mapping["O"] @ state - mapping["target"]
                M, block = mapping["single"], mapping["block_rows"]
                batches = [
                    (M[j : j + block], -residual[j : j + block])
                    for j in range(0, len(M), block)
                ]
                direct = mapping["whiten"] @ pft.recursive_ridge(
                    batches, regularizer=1.0
                )
                return float(np.max(np.abs(direct - action)))

            rls_errors.append(timed(ledger, "validation", check_rls))
        # The arriving innovation is read only after the current action is fixed.
        state = policy["A"][k] @ state + policy["E"][k] @ action + innovations[k]
        actions.append(action)
        states.append(state.copy())
    return dict(
        states=np.asarray(states), actions=np.asarray(actions), rls_errors=rls_errors
    )


def score(run, initial_theta, readout, retention, cost, spec):
    """Reconstruct common task, retention and effort directly from physical states."""
    width, h = len(initial_theta), spec["horizon"]
    task = keep = effort = 0.0
    for k, state in enumerate(run["states"]):
        weight = spec["terminal_task"] if k == h else spec["stage_task"]
        retain = spec["terminal_retention"] if k == h else spec["stage_retention"]
        task += (
            0.5 * weight * np.square(readout @ (state[:width] - state[width:])).sum()
        )
        keep += (
            0.5 * retain * np.square(retention @ (state[:width] - initial_theta)).sum()
        )
        if k < h:
            effort += 0.5 * run["actions"][k] @ cost @ run["actions"][k]
    return dict(
        task=float(task),
        retention=float(keep),
        effort=float(effort),
        total=float(task + keep + effort),
    )


def study(protocol):
    spec = protocol["specification"]
    ledger = dict(feature_response=0, solve=0, validation=0, communication=0)
    began, cpu = time.perf_counter_ns(), time.process_time_ns()
    groups, checks = [], []
    for width in spec["widths"]:
        for seed in spec["seeds"]:
            rng = np.random.default_rng(seed + 10000 * width)
            group = dict(width=width, seed=seed, episodes=[], shared_setups=[])
            groups.append(group)
            for origin in range(spec["initial_states"]):
                theta = rng.normal(0, spec["initial_theta_sigma"], width)
                initial = np.r_[theta, np.zeros(width)]
                before = ledger.copy()
                system, C, R = timed(
                    ledger,
                    "feature_response",
                    lambda: make_system(width, seed, theta, spec),
                )
                prepared = prepare(system, ledger)
                group["shared_setups"].append(
                    dict(
                        origin=origin,
                        initial=initial.tolist(),
                        ranks=[r["rank"] for r in prepared["ranks"]],
                        timing_ns={key: ledger[key] - before[key] for key in ledger},
                    )
                )
                for path in range(spec["innovation_paths"]):
                    noise = np.zeros((spec["horizon"], 2 * width))
                    reveal = spec["reveal_transition"] - 1
                    noise[reveal, width:] = rng.normal(
                        0, spec["innovation_sigma"], width
                    )
                    episode = dict(
                        origin=origin,
                        path=path,
                        innovation=noise[reveal, width:].tolist(),
                        methods={},
                    )
                    group["episodes"].append(episode)
                    executed = {}
                    for method in METHODS:
                        before = ledger.copy()
                        run = simulate(method, initial, noise, prepared, spec, ledger)
                        values = timed(
                            ledger,
                            "validation",
                            lambda: score(run, theta, C, R, system[-1][0], spec),
                        )
                        executed[method] = run
                        episode["methods"][method] = dict(
                            objective=values,
                            actions=run["actions"].tolist(),
                            endpoint=run["states"][-1].tolist(),
                            rls_max_error=max(run["rls_errors"], default=0.0),
                            timing_ns={
                                key: ledger[key] - before[key] for key in ledger
                            },
                        )
                    error = float(
                        np.max(
                            np.abs(
                                executed["full_riccati"]["actions"]
                                - executed["pft_compressed"]["actions"]
                            )
                        )
                    )
                    checks.append(
                        dict(
                            width=width,
                            seed=seed,
                            origin=origin,
                            path=path,
                            parity_error=error,
                            passed=error < 1e-9
                            and episode["methods"]["single_action_ridge"][
                                "rls_max_error"
                            ]
                            < 1e-9,
                        )
                    )
                    if path == 0:
                        changed = noise.copy()
                        changed[reveal, width:] += np.linspace(-0.9, 0.7, width)
                        for method in METHODS:
                            # Validation uses its own ledger; no nested timing intervals.
                            scratch = dict.fromkeys(ledger, 0)
                            rerun = timed(
                                ledger,
                                "validation",
                                lambda: simulate(
                                    method, initial, changed, prepared, spec, scratch
                                ),
                            )
                            prefix = executed[method]["actions"][
                                : spec["reveal_transition"]
                            ]
                            same = np.array_equal(
                                prefix, rerun["actions"][: spec["reveal_transition"]]
                            )
                            checks.append(
                                dict(
                                    width=width,
                                    seed=seed,
                                    origin=origin,
                                    method=method,
                                    future_suffix_prefix_equal=bool(same),
                                    passed=bool(same),
                                )
                            )
    elapsed = time.perf_counter_ns() - began
    ledger["unattributed_overhead"] = elapsed - sum(ledger.values())
    if ledger["unattributed_overhead"] < 0:
        raise RuntimeError("overlapping timing intervals")
    return dict(
        groups=groups,
        checks=checks,
        passed=all(c["passed"] for c in checks),
        episode_count=sum(len(g["episodes"]) for g in groups),
        timing_ns={
            **ledger,
            "total_elapsed": elapsed,
            "total_cpu": time.process_time_ns() - cpu,
        },
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--freeze-protocol", type=Path)
    parser.add_argument("--protocol", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.freeze_protocol:
        if args.protocol or args.output:
            parser.error("freeze and execution must be separate invocations")
        freeze(args.freeze_protocol)
        print(json.dumps({"frozen_protocol": str(args.freeze_protocol)}))
        return
    if args.protocol is None or args.output is None:
        parser.error("execution requires --protocol and --output")
    protocol, digest = load_protocol(args.protocol)
    result = study(protocol)
    result.update(
        schema="hepta.e1e6.pft-horizon-result.v1",
        protocol_sha256=digest,
        source_sha256=source_identity(),
        scope=__doc__,
        model_calls=0,
        communication_performed=False,
        independent_learning_acceptance=False,
        method_scopes={
            "single_action_ridge": "all remaining charges; only first action free in each replanning solve",
            "full_horizon_gd": "same complete conditional-mean horizon; 32 zero-start iterations",
            "blind_belief_ablation": "information-removal diagnostic, not an equal-information competitor",
        },
        runtime=dict(
            python=sys.version,
            numpy=np.__version__,
            platform=platform.platform(),
            ended_at=datetime.now(timezone.utc).isoformat(),
        ),
    )
    with args.output.open("x", encoding="utf-8") as out:
        json.dump(
            result, out, ensure_ascii=False, allow_nan=False, separators=(",", ":")
        )
        out.write("\n")
    print(
        json.dumps(
            {
                "passed": result["passed"],
                "groups": len(result["groups"]),
                "episodes": result["episode_count"],
                "timing_ns": result["timing_ns"],
            }
        )
    )
    if not result["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
