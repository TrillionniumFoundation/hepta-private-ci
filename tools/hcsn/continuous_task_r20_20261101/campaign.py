"""Frozen prospective directional checks with complete compressed numerical arrays."""

import argparse
import copy
import gzip
import hashlib
import json
from pathlib import Path
import platform
import time

import numpy as np
import scipy

from tools.hcsn.continuous_task_r18_20261101.task import DEFAULT
from tools.hcsn.continuous_task_r18_20261101.jump_solver import solve as reference
from tools.hcsn.continuous_task_r19_20261101.tangent_solver import solve as old_gradient
from . import directional, task_directional
from .audit_ties import run as independent_ties


def analytic_callback(matrix, value, obstacle, rhs, dmatrix, dobstacle, drhs):
    states = np.where(value - obstacle > 0, 0, np.where(matrix @ value - rhs > 0, 1, 2))
    return directional.derivative(np.diag(matrix), np.diag(matrix, -1), np.diag(matrix, 1),
        value, rhs, obstacle, drhs, dobstacle, dmatrix @ value, states)[0]


def run(output):
    output.mkdir(exist_ok=False)
    root = Path(__file__).resolve().parent
    protocol = json.loads((root / "PROTOCOL.json").read_text())
    freeze = json.loads((root / "SOURCE_FREEZE.json").read_text())
    for item in freeze["files"]:
        raw = (root / item["path"]).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == item["sha256"], item["path"]
    prior_failures = []
    for item in json.loads((root / "INPUT_IDENTITIES.json").read_text())["files"]:
        raw = (root.parents[2] / item["path"]).read_bytes()
        assert len(raw) == item["bytes"] and hashlib.sha256(raw).hexdigest() == item["sha256"]
        assert hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest() == item["git_blob"]
        if item["path"].endswith(("CONFIRMATION.json", "FOLLOWUP_RESULTS.json")):
            assert json.loads(raw)["passed"] is False
            prior_failures.append(item["path"])
    started, wall = time.process_time(), time.monotonic()
    controls = independent_ties(analytic_callback, directional.max_direction, tuple(protocol["steps"]))
    config = copy.deepcopy(DEFAULT)
    config.update(protocol["config_changes"])
    rejected = []
    invalid = []
    for coordinate in (1, 2, 4, 5, 10, 11):
        d = np.zeros(13)
        d[coordinate] = -.1
        invalid.append((config, d, str(coordinate)))
    invalid += [(config, np.zeros(12), "shape"), (config, np.full(13, np.nan), "nonfinite")]
    upper_config, row_config = copy.deepcopy(config), copy.deepcopy(config)
    upper_config["reward_base"][0] = 1.
    row_config["content_transition"][0] = [1., 0.]
    d = np.zeros(13)
    d[8] = .1
    invalid.append((upper_config, d, "reward_upper"))
    d = np.zeros(13)
    d[6] = .1
    invalid.append((row_config, d, "row_upper"))
    for law, direction, name in invalid:
        try:
            task_directional.solve(law, direction, *protocol["meshes"][0])
        except ValueError:
            rejected.append(name)
        else:
            raise AssertionError("Infeasible direction accepted: " + name)
    rng = np.random.default_rng(protocol["direction_seed"])
    directions = []
    for family in ("affine_tie", "joint_smooth"):
        for index in range(protocol["directions_per_family"]):
            d = rng.uniform(-1., 1., 13) * np.asarray(protocol["coordinate_scales"])
            d[[1, 2, 4, 5, 10, 11]] = abs(d[[1, 2, 4, 5, 10, 11]])
            if family == "affine_tie":
                d[[0, 3, 6, 7, 12]] = 0.
            directions.append((family, index, d))
    records, raw_rows, raw_files, nonlinear = [], [], [], []

    def flush():
        if not raw_rows:
            return
        data = ("\n".join(json.dumps(r, separators=(",", ":"), allow_nan=False) for r in raw_rows) + "\n").encode()
        packed = gzip.compress(data, mtime=0)
        assert len(packed) <= 512000
        path = output / f"raw_{len(raw_files):03d}.jsonl.gz"
        path.write_bytes(packed)
        raw_files.append(dict(path=path.name, bytes=len(packed), rows=len(raw_rows),
            sha256=hashlib.sha256(packed).hexdigest(), raw_sha256=hashlib.sha256(data).hexdigest()))
        raw_rows.clear()

    for dx, dt in protocol["meshes"]:
        old = old_gradient(config, dx, dt)
        for family, index, d in directions:
            base = task_directional.solve(config, d, dx, dt)
            doubled = task_directional.solve(config, 2 * d, dx, dt)
            assert base["exact_tie_profile"]
            homogeneity = float(abs(doubled["tangent"] - 2 * base["tangent"]).max())
            shifted, checks = [], []
            for step in protocol["steps"]:
                actual = reference(task_directional.perturb(config, d, step), dx, dt)["values"]
                shifted.append(actual.tolist())
                error = float(abs((actual - base["values"]) / step - base["tangent"]).max())
                remainder = float(abs(actual - base["values"] - step * base["tangent"]).max() / step ** 2)
                checks.append(dict(step=step, derivative_error=error, remainder_over_step_squared=remainder,
                    passed=error <= protocol["affine_derivative_tolerance"] if family == "affine_tie"
                    else remainder <= protocol["joint_remainder_bound"]))
            residual = max(r["residual"] for r in base["records"])
            row = dict(family=family, index=index, dx=dx, dt=dt, direction=d.tolist(), checks=checks,
                homogeneity_error=homogeneity, directional_lcp_residual=residual,
                exact_primal_error=float(abs(base["values"] - .5).max()),
                maximum_admission_tie_count=max(j["exact_max_ties"] for j in base["jumps"]),
                derivative_jump=max(j["derivative_jump"] for j in base["jumps"]),
                old_selected_branch_difference=float(abs(old["derivatives"] @ d - base["tangent"]).max()))
            row["passed"] = all(c["passed"] for c in checks) and homogeneity <= protocol["algebra_tolerance"] and residual <= protocol["algebra_tolerance"] and row["exact_primal_error"] == 0.
            records.append(row)
            raw_rows.append(dict(record=row, values=base["values"].tolist(), tangent=base["tangent"].tolist(),
                doubled_tangent=doubled["tangent"].tolist(), shifted_values=shifted))
            if len(raw_rows) == 8:
                flush()
        d = np.zeros(13)
        d[8], d[9] = .1, -.1
        positive, negative = [task_directional.solve(config, sign * d, dx, dt) for sign in (1, -1)]
        lag = int(round(config["recovery"] / dt))
        total = positive["tangent"][lag] + negative["tangent"][lag]
        nonlinear.append(dict(dx=dx, dt=dt, first_admission_sum=total.tolist(),
            positive_first_admission=positive["tangent"][lag].tolist(),
            negative_first_admission=negative["tangent"][lag].tolist(),
            expected=.05, error=float(abs(total - .05).max()), passed=bool(abs(total - .05).max() <= protocol["algebra_tolerance"])))
    flush()
    result = dict(schema="hcsn-r20-directional-campaign-v1", protocol=protocol, source_freeze=freeze,
        analytic_controls=controls, records=records, actual_admission_nonadditivity=nonlinear, raw_files=raw_files,
        infeasible_direction_rejections=rejected,
        passed=controls["passed"] and all(r["passed"] for r in records + nonlinear),
        verified_prior_failures=prior_failures,
        original_r19_whole_array_gate=False, full_gradient_gate=False, production_activation=False,
        process=dict(cpu_seconds=time.process_time() - started, wall_seconds=time.monotonic() - wall,
                     python=platform.python_version(), numpy=np.__version__, scipy=scipy.__version__))
    (output / "RESULTS.json").write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    print(json.dumps(dict(passed=result["passed"], cases=len(records), process=result["process"]), indent=2))
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    raise SystemExit(0 if run(parser.parse_args().output)["passed"] else 1)
