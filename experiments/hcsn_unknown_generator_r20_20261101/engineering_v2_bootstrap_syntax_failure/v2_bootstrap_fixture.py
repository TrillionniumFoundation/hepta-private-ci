"""Small full-array reference for the bounded-memory resampling implementation."""

import json
import time

import numpy as np

from .confirm_v2 import bootstrap


def verify():
    start = time.process_time()
    rng = np.random.default_rng(98972)
    spec = dict(models=["context_orbit", "orbit_first_order", "first_order"], bootstrap_seed=2006513,
                bootstrap_draws=4096, bootstrap_batch=64)
    stats = {name:rng.random((23, 9)) * 4 for name in spec["models"]}
    for value in stats.values():
        value[:, :4] = np.floor(value[:, :4])
        value[:, 0] = np.maximum(value[:, 0], value[:, 1])
        value[:, 2] = np.maximum(value[:, 2], value[:, 3])
    actual, paired = bootstrap(stats, spec, 92)
    indices = np.random.default_rng(2006513).integers(23, size=(4096, 23))
    maximum = 0.
    for name, value in stats.items():
        total = value[indices].sum(1)
        expected = np.column_stack([np.divide(total[:, 3], total[:, 2], out=np.ones(4096), where=total[:, 2] > 0),
            np.divide(total[:, 1], total[:, 0], out=np.ones(4096), where=total[:, 0] > 0), total[:, 4:6] / 92])
        maximum = max(maximum, float(np.abs(actual[name] - expected).max()))
    delta = (stats["context_orbit"] - stats["orbit_first_order"])[indices].sum(1)
    maximum = max(maximum, float(np.abs(paired - np.column_stack([delta[:, 4] / 92, -delta[:, 5] / 92])).max()))
    assert maximum < 1e-12
    empty, difference = bootstrap({name:np.zeros((1, 9)) for name in spec["models"]}, spec, 4)
    assert all(np.all(value[:, :2] == 1) and np.all(value[:, 2:] == 0) for value in empty.values())
    assert np.all(difference == 0)
    extended_spec = dict(spec, confirmation_arms=spec["models"] + ["feasible_orbit_first_order", "feasible_first_order"],
        feasible_controls={"feasible_orbit_first_order":"orbit_first_order", "feasible_first_order":"first_order"})
    extended = dict(stats, feasible_orbit_first_order=rng.random((23, 9)), feasible_first_order=rng.random((23, 9)))
    actual, paired = bootstrap(extended, extended_spec, 92)
    for name, value in extended.items():
        total = value[indices].sum(1)
        expected = np.column_stack([np.divide(total[:, 3], total[:, 2], out=np.ones(4096), where=total[:, 2] > 0),
            np.divide(total[:, 1], total[:, 0], out=np.ones(4096), where=total[:, 0] > 0), total[:, 4:6] / 92])
        maximum = max(maximum, float(np.abs(actual[name] - expected).max()))
    for column, control in enumerate(["orbit_first_order"] + list(extended_spec["feasible_controls"])):
        delta = (extended["context_orbit"] - extended[control])[indices].sum(1)
        expected = np.column_stack([delta[:, 4] / 92, -delta[:, 5] / 92])
        maximum = max(maximum, float(np.abs(paired[:, 2 * column:2 * column + 2] - expected).max()))
    assert maximum < 1e-12
    return dict(passed=True, synthetic_clusters=23, draws=4096, models=3,
        augmented_arms=5, paired_control_comparisons=3, maximum_batched_vs_full_difference=maximum,
        zero_denominator_risk_one_passed=True,
        process_cpu_seconds=time.process_time() - start, world_generator_called=False)


if __name__ == "__main__":
    print(json.dumps(verify(), sort_keys=True))
