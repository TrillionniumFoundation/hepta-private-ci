"""Bounded worker orchestration and immutable per-policy arithmetic."""

from pathlib import Path

import numpy as np

from experiments.hcsn_unknown_generator_r20_20261101.process_guard import persist, workers
from .study import ROOT


STAT_COLUMNS = ["accepted", "accepted_errors", "fractional", "fractional_errors", "payoff",
                "before_brier", "support_losses", "reads", "fees", "read_net_effect"]


def budget(spec, reserve=0):
    size = sum(path.stat().st_size for path in ROOT.rglob("*") if path.is_file() and "__pycache__" not in path.parts)
    if size + reserve > spec["raw_output_budget_bytes"]:
        raise OSError("Predeclared component output budget exhausted; no population estimate")


def run_batches(module, names, output, spec):
    receipts, errors = {}, []
    try:
        output.mkdir(exist_ok=False)
        names = list(names)
        for begin in range(0, len(names), spec["maximum_workers"]):
            completed, failures = workers(module, names[begin:begin + spec["maximum_workers"]],
                                          output / ("batch_%02d" % (begin // spec["maximum_workers"])))
            receipts.update(completed)
            errors.extend(failures)
            if failures or any(value["exit_code"] for value in completed.values()):
                break
    except Exception as error:
        errors.append(repr(error))
    if not persist(output / "WORKER_RECEIPTS.json", receipts):
        errors.append("Global worker receipt write failed")
    complete = set(receipts) == set(names) and not errors and all(value["exit_code"] == 0 for value in receipts.values())
    if not complete:
        persist(output / "FAILED.json", dict(errors=errors, complete_population=False, population_quality=None))
    return complete


def stat_vector(value):
    if value["invalid"]:
        # Quality is null if any invalidity. The issued request and its actual
        # fee are still retained instead of silently becoming free abstention.
        return np.asarray([0., 0., 0., 0., 0., 0., 0., value["read_index"] is not None, value["fee"], 0.])
    accepted = value["accepted"]
    fractional = accepted and value["fractional"]
    wrong = not value["correct"]
    return np.asarray([accepted, accepted and wrong, fractional, fractional and wrong,
        value["payoff"], value["before_brier"], value["true_probability"] <= 0,
        value["read_index"] is not None, value["fee"], value["payoff"] - value["no_read_payoff"]], dtype=float)


def pair_controls(spec, primary):
    return [name for name in spec["arms"] if name != primary] + list(spec["feasible_controls"])


def resample(stats, primary, spec, worlds):
    generators = next(iter(stats.values())).shape[0]
    rng = np.random.default_rng(spec["bootstrap_seed"])
    draws = {name:np.zeros((spec["bootstrap_draws"], 6)) for name in stats}
    controls = pair_controls(spec, primary)
    paired = np.zeros((spec["bootstrap_draws"], len(controls) * 2))
    for start in range(0, spec["bootstrap_draws"], spec["bootstrap_batch"]):
        count = min(spec["bootstrap_batch"], spec["bootstrap_draws"] - start)
        indices = rng.integers(generators, size=(count, generators))
        for name, values in stats.items():
            totals = np.column_stack([values[:, column][indices].sum(1) for column in range(6)])
            draws[name][start:start + count, :2] = np.column_stack([
                np.divide(totals[:, 3], totals[:, 2], out=np.ones(count), where=totals[:, 2] > 0),
                np.divide(totals[:, 1], totals[:, 0], out=np.ones(count), where=totals[:, 0] > 0)])
            draws[name][start:start + count, 2:] = np.column_stack([totals[:, 4:6] / worlds,
                totals[:, 2] / worlds, totals[:, 0] / worlds])
        for column, control in enumerate(controls):
            difference = stats[primary] - stats[control]
            paired[start:start + count, 2 * column] = difference[:, 4][indices].sum(1) / worlds
            paired[start:start + count, 2 * column + 1] = -difference[:, 5][indices].sum(1) / worlds
    return draws, paired, controls
