"""Independent finite differences of the untouched R18 jump solver.

No candidate perturbation helper or candidate finite-difference reference is
used. Every grid value, including every admission date, enters the error gate;
branch changes are disclosed and never excluded from the statistic.
"""

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import resource
import sys
import time

import numpy as np

from tools.hcsn.continuous_task_r18_20261101.jump_solver import solve as reference
from tools.hcsn.continuous_task_r18_20261101.task import DEFAULT
from tools.hcsn.continuous_task_r19_20261101 import tangent_solver as candidate


EXPECTED = ("sigma", "wait_cost", "recovery_cost", "reset_x", "reset_fee_0",
            "reset_fee_1", "retention_0", "retention_1", "reward_base_0",
            "reward_base_1", "reward_amplitude_0", "reward_amplitude_1", "reward_slope")


def changed(config, name, delta):
    result = copy.deepcopy(config)
    if name in ("sigma", "wait_cost", "recovery_cost", "reset_x", "reward_slope"):
        result[name] += delta
    elif name in ("retention_0", "retention_1"):
        j = int(name[-1])
        result["content_transition"][j][j] += delta
        result["content_transition"][j][1 - j] -= delta
    else:
        key, index = name.rsplit("_", 1)
        result[key][int(index)] += delta
    return result


def run(mode):
    start_wall, start_cpu = time.monotonic(), time.process_time()
    records, cases = [], []
    profiles = [(1., .63), (.7, .67), (1.3, .63)]
    meshes = [(.2, .02), (.1, .01)]
    names = EXPECTED if mode == "confirmation" else ("sigma", "reset_x", "retention_1")
    if mode != "confirmation":
        profiles, meshes = profiles[:1], meshes[:1]
    assert tuple(candidate.PARAMETERS) == EXPECTED
    for profile, (sigma, reset_x) in enumerate(profiles):
        config = copy.deepcopy(DEFAULT)
        config.update(sigma=sigma, reset_x=reset_x)
        for dx, dt in meshes:
            original = reference(config, dx, dt)
            solved = candidate.solve(config, dx, dt)
            primal_error = float(np.max(abs(original["values"] - solved["values"])))
            finite = bool(np.isfinite(solved["derivatives"]).all())
            case = dict(profile=profile, config=config, dx=dx, dt=dt,
                        primal_maximum_absolute_error=primal_error, derivatives_finite=finite,
                        branch_counts={str(j): int(np.sum(solved["branches"] == j)) for j in range(3)},
                        jump_records=solved["jump_records"])
            cases.append(case)
            assert primal_error <= 1e-12 and finite
            jump_indices = np.arange(original["lag"], len(original["times"]), original["lag"])
            for name in names:
                coordinate = EXPECTED.index(name)
                derivative = solved["derivatives"][..., coordinate]
                differences, signatures = [], []
                for step in (2e-5, 1e-5):
                    plus_config, minus_config = changed(config, name, step), changed(config, name, -step)
                    plus = reference(plus_config, dx, dt)["values"]
                    minus = reference(minus_config, dx, dt)["values"]
                    fd = (plus - minus) / (2 * step)
                    error = abs(derivative - fd) / np.maximum(1., np.maximum(abs(derivative), abs(fd)))
                    differences.append(fd)
                    if step == 1e-5:
                        for altered in (plus_config, minus_config):
                            result = candidate.solve(altered, dx, dt)
                            signatures.append(dict(
                                right=int(np.sum(result["branches"] != solved["branches"])),
                                left=int(np.sum(result["left_branches"] != solved["left_branches"]))))
                    records.append(dict(profile=profile, dx=dx, dt=dt, parameter=name,
                                        step=step, scalar_checks=int(error.size),
                                        maximum_scaled_error=float(error.max()),
                                        admission_maximum_scaled_error=float(error[jump_indices].max()),
                                        derivative_maximum_absolute=float(abs(derivative).max()),
                                        passed=bool(error.max() <= 5e-5)))
                records[-1]["branch_changes_plus_minus"] = signatures
                records[-1]["fd_step_maximum_difference"] = float(abs(differences[0] - differences[1]).max())
    rejected = []
    for name in ("recovery", "horizon", "lower", "upper", "dx", "dt", "unknown"):
        try:
            candidate.perturb(DEFAULT, name, .001)
        except ValueError:
            rejected.append(name)
        else:
            raise AssertionError("unsupported coordinate accepted: " + name)
    for reset_x in (.6, -4., 4.):
        config = copy.deepcopy(DEFAULT)
        config["reset_x"] = reset_x
        try:
            candidate.solve(config, .2, .02)
        except ValueError:
            rejected.append("reset_x=" + str(reset_x))
        else:
            raise AssertionError("reset interpolation knot accepted")
    usage = resource.getrusage(resource.RUSAGE_SELF)
    paths = [Path(__file__), Path(candidate.__file__)]
    return dict(schema="hcsn-r19-independent-task-gradient-audit-v1", mode=mode,
                candidate_parameters=list(EXPECTED), cases=cases, records=records,
                rejections=rejected, passed=all(r["passed"] for r in records),
                source_sha256={str(p.name): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths},
                process=dict(pid=os.getpid(), python=sys.version, numpy=np.__version__,
                             cpu_seconds=time.process_time() - start_cpu,
                             wall_seconds=time.monotonic() - start_wall,
                             maximum_rss_linux_kib=usage.ru_maxrss),
                limitations=["fixed-grid active-branch task derivatives only",
                             "no moving recovery/horizon/domain or continuum derivative",
                             "no full financial/neural gradient or quality adoption claim"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("development", "confirmation"), required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    result = run(args.mode)
    args.out.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    print(json.dumps(dict(passed=result["passed"], records=len(result["records"]),
                          maximum_scaled_error=max(r["maximum_scaled_error"] for r in result["records"]),
                          process=result["process"]), indent=2))
    raise SystemExit(0 if result["passed"] else 1)
