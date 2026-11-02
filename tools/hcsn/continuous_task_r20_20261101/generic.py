"""Separate nonconstant-law probe; all attempted signed directions are retained."""

import argparse
import copy
import gzip
import hashlib
import json
from pathlib import Path
import time

import numpy as np

from tools.hcsn.continuous_task_r18_20261101.task import DEFAULT
from tools.hcsn.continuous_task_r18_20261101.jump_solver import solve as reference
from .task_directional import PARAMETERS, perturb, solve


def run(output):
    output.mkdir(exist_ok=False)
    root = Path(__file__).resolve().parent
    protocol = json.loads((root / "GENERIC_PROTOCOL.json").read_text())
    freeze = json.loads((root / "SOURCE_FREEZE.json").read_text())
    for item in freeze["files"]:
        assert hashlib.sha256((root / item["path"]).read_bytes()).hexdigest() == item["sha256"]
    for item in json.loads((root / "INPUT_IDENTITIES.json").read_text())["files"]:
        raw = (root.parents[2] / item["path"]).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == item["sha256"]
    cpu, wall = time.process_time(), time.monotonic()
    records, raw_files = [], []
    dx, dt = protocol["mesh"]
    for profile, changes in enumerate(protocol["profiles"]):
        config = copy.deepcopy(DEFAULT)
        config.update(changes)
        original = reference(config, dx, dt)["values"]
        for coordinate, name in enumerate(PARAMETERS):
            for sign in (-1., 1.):
                d = np.zeros(13)
                d[coordinate] = sign
                row = dict(profile=profile, parameter=name, sign=sign, config=config, dx=dx, dt=dt)
                try:
                    base = solve(config, d, dx, dt)
                    shifted, checks = [], []
                    for step in protocol["steps"]:
                        actual = reference(perturb(config, d, step), dx, dt)["values"]
                        shifted.append(actual.tolist())
                        error = float(abs((actual - base["values"]) / step - base["tangent"]).max())
                        checks.append(dict(step=step, derivative_error=error,
                            passed=error <= protocol["one_sided_tolerance"]))
                    row.update(status="completed", checks=checks,
                        primal_parity=float(abs(base["values"] - original).max()),
                        unresolved_rows=sum(r["unresolved_numerical_rows"] for r in base["records"]),
                        maximum_derivative=float(abs(base["tangent"]).max()))
                    row["passed"] = all(r["passed"] for r in checks) and row["primal_parity"] <= protocol["primal_tolerance"]
                    raw_row = dict(record=row, original_values=original.tolist(), values=base["values"].tolist(),
                                   tangent=base["tangent"].tolist(), shifted_values=shifted)
                except (ValueError, RuntimeError, AssertionError) as error:
                    row.update(status="failed", passed=False, error=type(error).__name__ + ": " + str(error))
                    raw_row = dict(record=row)
                data = json.dumps(raw_row, separators=(",", ":"), allow_nan=False).encode()
                packed = gzip.compress(data, mtime=0)
                assert len(packed) <= 512000
                path = output / f"raw_{len(records):03d}.json.gz"
                path.write_bytes(packed)
                raw_files.append(dict(path=path.name, bytes=len(packed), sha256=hashlib.sha256(packed).hexdigest(),
                                      raw_sha256=hashlib.sha256(data).hexdigest()))
                records.append(row)
    result = dict(schema="hcsn-r20-generic-directional-probe-v1", protocol=protocol, records=records,
        raw_files=raw_files, numerical_finite_step_gate=all(r["passed"] for r in records),
        nonzero_coordinate_coverage={name: any(r["parameter"] == name and r.get("maximum_derivative", 0) > 1e-10 for r in records) for name in PARAMETERS},
        generic_math_qualification=False, original_r19_whole_array_gate=False, full_gradient_gate=False,
        process=dict(cpu_seconds=time.process_time() - cpu, wall_seconds=time.monotonic() - wall),
        qualification="Generic floating tie classification is diagnostic, not an outward-rounded exact classification certificate.")
    (output / "RESULTS.json").write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    print(json.dumps(dict(gate=result["numerical_finite_step_gate"], attempts=len(records),
                         completed=sum(r["status"] == "completed" for r in records), process=result["process"]), indent=2))
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    result = run(parser.parse_args().output)
    raise SystemExit(0 if result["numerical_finite_step_gate"] else 1)
