"""Exact finite-R14 policy expectations and a full-episode oracle ceiling.

This diagnostic reads already published training checkpoints, never confirmation
tapes. It does not train, select candidates, change R14 acceptance, or establish
new confirmatory efficacy. "Exact" means complete finite enumeration using the
supplied floating-point matrices, not an interval-certified continuum theorem.
"""

import argparse
import copy
import hashlib
import itertools
import json
from pathlib import Path
import time

import numpy as np

from ..task_aligned_r14_20261101.qpi import encode, policy_alpha
from ..unified_cell_r12_20261031.task_value import ExactBeliefDP


R14_SOURCE = "1ce8b88f483d9fed5d96145300b1a81cc7f98ffa"
R14_FREEZE = "0af6d81c45e485efac0bb27b8bdbc907947996b4b36f4db2b90d0b273dfe229a"
NUMERICAL_TOLERANCE = 2e-9
FIELDS = ("utility", "reward", "fee", "elapsed", "reads", "resets", "terminal_mass")


def schedule_support(durations, horizon=3):
    """The Cartesian product represents independent uniform duration draws."""
    durations = tuple(float(value) for value in durations)
    if (isinstance(horizon, bool) or not isinstance(horizon, (int, np.integer))
            or not 0 <= horizon <= 3 or not durations or len(durations) > 8
            or len(set(durations)) != len(durations)
            or not np.isfinite(durations).all() or min(durations) <= 0):
        raise ValueError("Require distinct positive durations and horizon zero to three")
    return tuple(itertools.product(durations, repeat=int(horizon)))


def exact_episode(world, actor, planner, schedule, budget=2, first_action=None):
    """Forward unnormalized world mass through the ACTUAL recurrent policy.

    Unlike the inherited backward alpha-vector evaluator, this independently
    transports joint state/history mass, charging fees at each actual action.
    The actor sees only encode(token, duration, reset), never this world mass.
    ``first_action`` is for forced-action numerical validation only.
    """
    model = copy.deepcopy(actor)
    model.start()
    prior, times, reads = planner._inputs(world.prior, schedule, budget)
    if len(times) > 3 or world.E.shape != (planner.states, 8):
        raise ValueError("This diagnostic requires R14's eight symbols and short horizon")
    planner._inputs(model.current, times, reads)
    transitions = {dt: np.asarray(world.transition(dt), dtype=float) for dt in set(times)}
    for matrix in transitions.values():
        if (matrix.shape != (planner.states, planner.states) or not np.isfinite(matrix).all()
                or matrix.min() < -2e-12 or not np.allclose(matrix.sum(1), 1., atol=2e-10, rtol=0)):
            raise ValueError("Invalid world transition")
    if (not np.isfinite([world.reset_cost, world.latency_price]).all()
            or min(world.reset_cost, world.latency_price) < 0):
        raise ValueError("Invalid actual task prices")
    nodes, leaves = 0, 0
    root_action = planner.choose(model.current, times, reads) if first_action is None else first_action

    def visit(mass, estimator, remaining, remaining_reads, forced=None):
        nonlocal nodes, leaves
        nodes += 1
        action = planner.choose(estimator.current, remaining, remaining_reads) if forced is None else forced
        if action not in planner.legal_actions(remaining, remaining_reads):
            raise ValueError("Actual policy selected an illegal action")
        probability = float(mass.sum())
        if action in ("STOP0", "STOP1"):
            leaves += 1
            reward = float(mass @ world.reward[:, int(action[-1])])
            return np.array([reward, reward, 0., 0., 0., 0., probability])
        dt, rest = remaining[0], remaining[1:]
        successor = (mass @ world.R if action == "RESET" else mass) @ transitions[dt]
        fee = probability * world.latency_price * dt
        result = np.zeros(len(FIELDS))
        result[3] = probability * dt
        if action == "READ":
            fee += float(successor @ world.read_cost)
            result[4] = probability
            for token in range(8):
                branch_mass = successor * world.E[:, token]
                if branch_mass.sum() <= 0:
                    continue
                branch = copy.deepcopy(estimator)
                branch.step(encode(token, dt))
                result += visit(branch_mass, branch, rest, remaining_reads - 1)
        else:
            branch = copy.deepcopy(estimator)
            branch.step(encode(None, dt, action == "RESET"))
            result += visit(successor, branch, rest, remaining_reads)
            if action == "RESET":
                fee += probability * world.reset_cost
                result[5] += probability
        result[0] -= fee
        result[2] += fee
        return result

    values = visit(prior, model, times, reads, root_action)
    if (not np.isfinite(values).all() or abs(values[-1] - 1.) > NUMERICAL_TOLERANCE
            or abs(values[0] - values[1] + values[2]) > NUMERICAL_TOLERANCE):
        raise ArithmeticError("Enumeration lost mass or the reward-minus-fee identity")
    return dict(zip(FIELDS, map(float, values)), first_action=root_action, nodes=nodes, leaves=leaves)


def oracle_table(world, durations, horizon=3, budget=2):
    """Best public-history policy with known world, NOT a latent-state oracle."""
    oracle = ExactBeliefDP(world, reset_cost=world.reset_cost, latency_price=world.latency_price)
    table = []
    for schedule in schedule_support(durations, horizon):
        values = oracle.action_values(world.prior, schedule, budget)
        table.append(dict(schedule=list(schedule), upper_value=max(values.values()),
                          oracle_first_action=oracle.choose(world.prior, schedule, budget)))
    return table


def audit_pair(world, ordinary, hx, planner, durations, horizon=3, budget=2, oracle_rows=None):
    """Evaluate the frozen B/D actors; the independently computed DP bounds both."""
    support = schedule_support(durations, horizon)
    oracle_rows = oracle_table(world, durations, horizon, budget) if oracle_rows is None else oracle_rows
    if [tuple(row["schedule"]) for row in oracle_rows] != list(support):
        raise ValueError("Oracle schedule support differs from the evaluation law")
    records = []
    for schedule, reference in zip(support, oracle_rows):
        row = dict(schedule=list(schedule), probability=1. / len(support), oracle=reference["upper_value"])
        for name, actor in (("B", ordinary), ("D", hx)):
            forward = exact_episode(world, actor, planner, schedule, budget)
            positioned = copy.deepcopy(actor)
            positioned.start()
            alpha = policy_alpha(world, positioned, planner, schedule, budget)
            backward = float(world.prior @ alpha[forward["first_action"]])
            error = abs(backward - forward["utility"])
            if error > NUMERICAL_TOLERANCE:
                raise ArithmeticError("Independent forward and backward policy evaluations differ")
            headroom = row["oracle"] - forward["utility"]
            if headroom < -NUMERICAL_TOLERANCE:
                raise ArithmeticError("Deployed policy exceeds the true-world public-information DP")
            row[name] = dict(forward, backward_alpha_utility=backward, forward_backward_error=error,
                             oracle_headroom=headroom)
        row["D_minus_B"] = row["D"]["utility"] - row["B"]["utility"]
        records.append(row)
    means = {name: {key: float(np.mean([row[name][key] for row in records]))
                    for key in FIELDS + ("oracle_headroom",)} for name in ("B", "D")}
    return dict(schedule_count=len(support), schedule_probability=1. / len(support),
                distribution="independent uniform draws with replacement at each public slot",
                horizon=horizon, read_budget=budget, durations=list(map(float, durations)),
                oracle_mean=float(np.mean([row["oracle"] for row in records])), arms=means,
                D_minus_B=float(np.mean([row["D_minus_B"] for row in records])),
                max_forward_backward_error=max(row[a]["forward_backward_error"] for row in records for a in ("B", "D")),
                schedules=records)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def analyze_r14(run, protocol_path=None, seeds=None):
    """Load only fixed training artifacts, preserving their published selection."""
    from ..task_aligned_r14_20261101.models import GenericHMM, restore
    from ..task_aligned_r14_20261101.task import TaskModel

    started, wall = time.process_time(), time.perf_counter()
    root = Path(__file__).resolve().parents[3]
    protocol_path = (Path(protocol_path) if protocol_path is not None else
                     root / "tools/hcsn/task_aligned_r14_20261101/PROTOCOL.json")
    run = Path(run)
    freeze_path = run / "FREEZE.json"
    if digest(freeze_path) != R14_FREEZE:
        raise ValueError("Expected the exact already published R14 candidate freeze")
    freeze = json.loads(freeze_path.read_text())
    protocol = json.loads(protocol_path.read_text())
    if freeze["source_commit"] != R14_SOURCE or digest(protocol_path) != freeze["protocol_sha256"]:
        raise ValueError("R14 protocol/source identity mismatch")
    for name, expected in freeze["sources"].items():
        if digest(root / name) != expected:
            raise ValueError("Frozen scientific source differs: " + name)
    selected_seeds = list(protocol["fit_seeds"] if seeds is None else seeds)
    if (not selected_seeds or len(set(selected_seeds)) != len(selected_seeds)
            or any(seed not in protocol["fit_seeds"] for seed in selected_seeds)):
        raise ValueError("Only distinct registered fits are allowed")
    inputs = {str(freeze_path): digest(freeze_path), str(protocol_path): digest(protocol_path)}

    def training_file(seed, name):
        relative = str(Path(str(seed)) / name)
        path = run / relative
        if relative not in freeze["artifacts"] or digest(path) != freeze["artifacts"][relative]:
            raise ValueError("Training artifact is not the published frozen bytes: " + relative)
        inputs[str(path)] = digest(path)
        return json.loads(path.read_text())

    world = TaskModel()
    domains = {domain: dict(oracle=oracle_table(world, protocol[domain + "_durations"],
                protocol["horizon"], protocol["read_budget"]), fits=[])
               for domain in ("iid", "ood")}
    for seed in selected_seeds:
        training = training_file(seed, "TRAINING.json")
        selected = training["selected_ordinary"]
        if (training["status"] != "completed" or training["seed"] != seed
                or selected != freeze["selected_ordinary"][str(seed)]):
            raise ValueError("Registered candidate selection changed")
        common = restore(training_file(seed, "common_model.json")["model"]).build_cell()
        ordinary = (GenericHMM(common) if selected == "generic_hmm" else
                    restore(training_file(seed, selected + ".json")["final_model"]))
        hx = restore(training_file(seed, "hx_distribution.json")["final_model"])
        planner = ExactBeliefDP(common, reset_cost=common.reset_cost, latency_price=common.latency_price)
        for domain, data in domains.items():
            result = audit_pair(world, ordinary, hx, planner, protocol[domain + "_durations"],
                                protocol["horizon"], protocol["read_budget"], data["oracle"])
            data["fits"].append(dict(seed=seed, selected_ordinary=selected, **result))
    for data in domains.values():
        rows = data["fits"]
        headroom = float(np.mean([row["arms"]["B"]["oracle_headroom"] for row in rows]))
        data["summary"] = dict(oracle_mean=float(np.mean([row["upper_value"] for row in data["oracle"]])),
            B_mean=float(np.mean([row["arms"]["B"]["utility"] for row in rows])),
            D_mean=float(np.mean([row["arms"]["D"]["utility"] for row in rows])),
            D_minus_B=float(np.mean([row["D_minus_B"] for row in rows])),
            oracle_minus_B=headroom, registered_mean_floor=.01,
            numerical_headroom_below_mean_floor=headroom < .01 - NUMERICAL_TOLERANCE,
            max_forward_backward_error=max(row["max_forward_backward_error"] for row in rows))
    if any(digest(Path(path)) != expected for path, expected in inputs.items()):
        raise ValueError("Training evidence changed during the diagnostic")
    for name, expected in freeze["sources"].items():
        if digest(root / name) != expected:
            raise ValueError("Frozen scientific source changed during evaluation: " + name)
    return dict(schema="hcsn.r15.exact-attainability.v1", source_commit=R14_SOURCE,
        frozen_candidate_sha256=R14_FREEZE, world_identity=world.identity,
        inputs=inputs, diagnostic_source_sha256=digest(__file__), domains=domains,
        fit_seeds=selected_seeds, complete_registered_fit_set=set(selected_seeds) == set(protocol["fit_seeds"]),
        new_confirmation_opened=False, scientific_acceptance_changed=False,
        independent_unit="already published training fit; schedules are integrated, not independent fits",
        numerical_tolerance=NUMERICAL_TOLERANCE,
        scope="Full-episode finite-world expected reward minus actual fees; no Monte Carlo outcomes reused",
        oracle_scope="Optimal public-history policy with known true finite world, never a hidden-state clairvoyant policy",
        interpretation="Oracle minus fixed B bounds any replacement policy's expected D-minus-B in this unchanged task. A small ceiling is not a successful quality or CPU gate. A ceiling above the floor does not prove attainability.",
        limitations=["Floating-point matrix exponentials/enumeration, not rigorous interval certification",
                     "Conditional on these fixed trained candidates and fixed task; not new independent efficacy confirmation",
                     "No deployment timing or energy inference; all reported CPU is diagnostic computation"],
        cpu_seconds=time.process_time() - started, wall_seconds=time.perf_counter() - wall)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", type=int, action="append", help="Optional registered subset; output marks incomplete sets")
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError("Diagnostic output already exists; retain prior results")
    report = analyze_r14(args.run, seeds=args.seed)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as stream:
        json.dump(report, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
    print(json.dumps({domain: data["summary"] for domain, data in report["domains"].items()}, sort_keys=True))


if __name__ == "__main__":
    main()
