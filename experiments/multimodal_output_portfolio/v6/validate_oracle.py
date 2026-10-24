"""Independent Decimal/path-enumeration oracle for a frozen finite controller.

Only deterministic synthetic transition trees and their known terminal forecast
laws are checked. This is not a neural/FBSDE/global real-world optimality proof.
"""

import argparse
from decimal import Decimal, localcontext
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import random
import subprocess
import sys
import tempfile
import time


SOURCE_DIR = Path("experiments/multimodal_output_portfolio/v6")


def frozen_sources(repo, expected_commit):
    """Verify local custody; this does not authenticate the host or Git remote."""
    def git(*arguments):
        return subprocess.check_output(["git", *arguments], cwd=repo)

    if (len(expected_commit) != 40 or any(c not in "0123456789abcdef" for c in expected_commit)
            or git("rev-parse", "HEAD").decode().strip() != expected_commit
            or Path(git("rev-parse", "--show-toplevel").decode().strip()).resolve() != repo):
        raise ValueError("Frozen controller commit identity differs")
    if git("status", "--porcelain=v1", "--untracked-files=normal"):
        raise ValueError("Frozen repository must be clean")
    if Path(__file__).resolve() != repo / SOURCE_DIR / "validate_oracle.py":
        raise ValueError("Running oracle script is outside the frozen source path")
    sources = {}
    for name in ("control.py", "validate_oracle.py"):
        relative = SOURCE_DIR / name
        source = (repo / relative).read_bytes()
        if source != git("show", f"{expected_commit}:{relative.as_posix()}"):
            raise ValueError(f"Frozen source bytes differ: {name}")
        sources[name] = source
    return sources


def publish_report(output, report):
    """Publish complete JSON once; a competing or stale destination is preserved."""
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=output.parent,
                                         prefix=f".{output.name}.", delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(report, stream, indent=2, sort_keys=True, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, output)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


class Tree:
    def __init__(self, seed, depth, tied):
        rng = random.Random(seed)
        self.nodes, self.counts = {}, {"transition": 0, "prediction": 0}
        self.transition_work = 0.0

        def build(name, level):
            weights = [rng.randint(1, 9) for _ in range(3)]
            probabilities = [w / sum(weights) for w in weights]
            values = [0.25] * 3 if tied else [rng.randint(-16, 16) / 16 for _ in range(3)]
            edges = {f"a{i}": (name + str(i), rng.choice((.25, .5, 1., 1.5)))
                     for i in range(2 + (seed % 2))} if level else {}
            self.nodes[name] = (values, probabilities, edges)
            for child, _ in edges.values():
                build(child, level - 1)
        build("s", depth)

    def actions(self, state, content_control):
        return tuple(self.nodes[state][2])

    def action_cost(self, state, action):
        return self.nodes[state][2][action][1]

    def transition(self, state, action):
        self.counts["transition"] += 1
        self.transition_work += self.action_cost(state, action)
        return self.nodes[state][2][action][0]

    def prediction_cost(self, state):
        return .25

    def predict(self, state):
        self.counts["prediction"] += 1
        return self.nodes[state][:2]

    def state_key(self, state):
        return state

    def identity(self, state):
        return "frozen-known-finite-tree"


def enumerate_stopping_paths(tree, state, depth, remaining, gamma, penalty, path=(), spent=Decimal(0)):
    values, probabilities, edges = tree.nodes[state]
    values, weights = [Decimal(str(v)) for v in values], [Decimal(str(p)) for p in probabilities]
    total = sum(weights)
    probabilities = [p / total for p in weights]
    g = Decimal(str(gamma))
    value = (sum(p * v for p, v in zip(probabilities, values)) if not g else
             -sum(p * (-g * v).exp() for p, v in zip(probabilities, values)).ln() / g)
    outcomes = [(value - Decimal(str(penalty)) * spent, path)]
    if depth:
        for action, (child, cost) in edges.items():
            if cost <= remaining:
                outcomes.extend(enumerate_stopping_paths(tree, child, depth - 1, remaining - cost,
                                gamma, penalty, path + (action,), spent + Decimal(str(cost))))
    return outcomes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expected-commit", required=True)
    args = parser.parse_args()
    repo = args.repo.resolve()
    output = args.output.parent.resolve() / args.output.name
    if output.exists() or output.is_symlink():
        raise FileExistsError(f"Oracle report already exists: {output}")
    if output.is_relative_to(repo):
        raise ValueError("Oracle report must be outside the frozen repository")
    sources = frozen_sources(repo, args.expected_commit)
    control_path = repo / SOURCE_DIR / "control.py"
    # Compile exactly the verified source, never a possibly stale .pyc or an
    # earlier module imported through another checkout's package path.
    spec = importlib.util.spec_from_file_location("ndu_oracle_frozen_control", control_path)
    control = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = control
    exec(compile(sources["control.py"], str(control_path), "exec"), control.__dict__)
    if Path(control.__file__).resolve() != control_path or frozen_sources(repo, args.expected_commit) != sources:
        raise ValueError("Imported controller source identity differs")

    started, records, failures = time.perf_counter_ns(), [], []
    tolerance = Decimal("1e-11")
    for index in range(128):
        horizon, tied = index % 5, index % 16 == 0
        gamma = (0., 1e-12, 1e-6, .1, 1., 2., 10.)[index % 7]
        penalty = 0.0 if tied else (0., .002, .03, .2)[index % 4]
        generation = (0., .25, .75, 1.5, 2.25, 4.)[index % 6]
        tree = Tree(19037 + index, horizon, tied)
        budget = control.WorkBudget(263 + generation, stop_reserve=5, initial_work=2)
        decision = control.choose(tree, "s", budget, control.ControllerConfig(horizon=horizon, gamma=gamma,
                          cost_penalty=penalty, search_work_limit=256, search_fraction=1))
        with localcontext() as context:
            context.prec = 80
            paths = enumerate_stopping_paths(tree, "s", horizon, generation, gamma, penalty)
            best = max(value for value, _ in paths)
            selected = [value for value, path in paths if (path[0] if path else None) == decision.action]
            policy_gap = best - max(selected)
            value_gap = abs(best - Decimal(str(decision.value)))
            tie_class = {path[0] if path else None for value, path in paths if best - value <= tolerance}
        counts = {k: v for k, v in tree.counts.items() if v}
        actual_search = tree.transition_work + .25 * tree.counts["prediction"]
        accounting = decision.search_calls == counts and decision.search_work == actual_search
        execution_cost = 0 if decision.action is None else tree.action_cost("s", decision.action)
        if decision.action is not None:
            budget.charge_execution(tree.action_cost("s", decision.action))
            tree.transition("s", decision.action)
        budget.finish_stop(5)
        passed = (decision.complete and accounting and value_gap <= tolerance and policy_gap <= tolerance
                  and decision.action in tie_class and budget.used <= budget.limit
                  and budget.used == 7 + actual_search + execution_cost and decision.generation_envelope == generation)
        if not passed:
            failures.append(index)
        records.append({"case": index, "seed": 19037 + index, "horizon": horizon, "gamma": gamma,
                        "cost_penalty": penalty, "generation_envelope": generation, "node_count": len(tree.nodes),
                        "enumerated_stopping_paths": len(paths), "optimal_value_decimal": str(best),
                        "controller_value": decision.value, "value_gap": float(value_gap), "first_action_policy_gap": float(policy_gap),
                        "chosen_first_action": decision.action, "optimal_first_action_tolerance_class": sorted("stop" if x is None else x for x in tie_class),
                        "complete": decision.complete, "search_work": decision.search_work, "search_calls": decision.search_calls,
                        "search_accounting_verified": accounting, "generation_envelope_verified": decision.generation_envelope == generation,
                        "total_work_including_initial_execution_stop": budget.used, "modeled_limit": budget.limit, "passed": passed})
    elapsed = time.perf_counter_ns() - started
    if Path(control.__file__).resolve() != control_path or frozen_sources(repo, args.expected_commit) != sources:
        raise ValueError("Controller/oracle source changed during validation")
    report = {"schema": "hepta.ndu-v6.independent-finite-oracle.v1", "git_commit": args.expected_commit,
              "status": "failed" if failures else "passed", "clean_source_verified_pre_post": True,
              "control_sha256": hashlib.sha256(sources["control.py"]).hexdigest(),
              "script_sha256": hashlib.sha256(sources["validate_oracle.py"]).hexdigest(), "cases": len(records),
              "decimal_precision": 80, "absolute_tie_and_gap_tolerance": float(tolerance), "failures": failures,
              "max_value_gap": max(r["value_gap"] for r in records), "max_first_action_policy_gap": max(r["first_action_policy_gap"] for r in records),
              "complete_searches": sum(r["complete"] for r in records), "multi_action_tie_cases": sum(len(r["optimal_first_action_tolerance_class"]) > 1 for r in records),
              "nontrivial_stopping_choice_cases": sum(r["enumerated_stopping_paths"] > 1 for r in records),
              "total_enumerated_stopping_paths": sum(r["enumerated_stopping_paths"] for r in records),
              "wall_ns": elapsed, "scope": "known finite deterministic transition trees, terminal empirical entropic forecast, explicit stopping and budget; no general FBSDE or neural optimality claim", "records": records}
    output.parent.mkdir(parents=True, exist_ok=True)
    publish_report(output, report)
    print(json.dumps({k: v for k, v in report.items() if k != "records"}, sort_keys=True))
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
