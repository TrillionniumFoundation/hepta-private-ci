"""Prospective small-step check; original whole-array failure stays unchanged."""

import argparse
import copy
import hashlib
import json
import platform
from pathlib import Path
import resource
import time

import numpy as np
import scipy

from tools.hcsn.continuous_task_r18_20261101.jump_solver import solve as reference
from tools.hcsn.continuous_task_r18_20261101.task import DEFAULT
from .audit import EXPECTED, changed
from . import tangent_solver as candidate


def run():
    root = Path(__file__).resolve().parent
    start, wall = time.process_time(), time.monotonic()
    protocol = json.loads((root / "FOLLOWUP_PROTOCOL.json").read_text())
    freeze = json.loads((root / "FOLLOWUP_SOURCE_FREEZE.json").read_text())
    for item in freeze["files"]:
        raw = (root / item["path"]).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == item["sha256"], item["path"]
    for item in json.loads((root / "INPUT_IDENTITIES.json").read_text())["files"]:
        raw = (root.parents[2] / item["path"]).read_bytes()
        assert len(raw) == item["size"]
        assert hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest() == item["git_blob"]
    assert tuple(candidate.PARAMETERS) == EXPECTED
    original_result = json.loads((root / "CONFIRMATION.json").read_text())
    assert original_result["passed"] is False
    records, cases = [], []
    for profile, law in enumerate(protocol["profiles"]):
        config = copy.deepcopy(DEFAULT)
        config.update(sigma=law["sigma"], reset_x=law["reset_x"])
        for dx, dt in protocol["meshes"]:
            base = candidate.solve(config, dx, dt)
            original = reference(config, dx, dt)
            parity = float(abs(base["values"] - original["values"]).max())
            cases.append(dict(profile=profile, dx=dx, dt=dt, config=config,
                              primal_maximum_absolute_error=parity, jump_records=base["jump_records"]))
            for coordinate, name in enumerate(EXPECTED):
                tangent = base["derivatives"][..., coordinate]
                for step in protocol["fd_steps"]:
                    altered = [changed(config, name, step), changed(config, name, -step)]
                    plus, minus = [reference(c, dx, dt)["values"] for c in altered]
                    fd = (plus - minus) / (2 * step)
                    scaled = abs(tangent - fd) / np.maximum(1., np.maximum(abs(tangent), abs(fd)))
                    location = np.unravel_index(np.argmax(scaled), scaled.shape)
                    signatures = []
                    for law in altered:
                        other = candidate.solve(law, dx, dt)
                        signatures.append(dict(left=int(np.sum(other["left_branches"] != base["left_branches"])),
                                               right=int(np.sum(other["branches"] != base["branches"]))))
                    witnesses = dict(location=list(map(int, location)),
                        plus=float(plus[location]), minus=float(minus[location]),
                        tangent=float(tangent[location]), central_difference=float(fd[location]),
                        maximum_scaled_error=float(scaled[location]))
                    hashes = {label: hashlib.sha256(np.ascontiguousarray(array, dtype="<f8").tobytes()).hexdigest()
                              for label, array in (("plus", plus), ("minus", minus), ("tangent", tangent))}
                    records.append(dict(profile=profile, dx=dx, dt=dt, parameter=name, step=step,
                        scalar_checks=int(fd.size), branch_changes_plus_minus=signatures,
                        stable=all(s["left"] == s["right"] == 0 for s in signatures),
                        witness=witnesses, full_array_sha256=hashes, shape=list(fd.shape),
                        passed=bool(scaled.max() <= protocol["whole_array_scaled_fd_tolerance"])))
    coverage = {name: any(r["parameter"] == name and r["stable"] and r["passed"] for r in records) for name in EXPECTED}
    gates = dict(all_whole_array_bounds=all(r["passed"] for r in records),
                 primal_parity=all(c["primal_maximum_absolute_error"] <= protocol["primal_absolute_tolerance"] for c in cases),
                 stable_coordinate_coverage=all(coverage.values()))
    return dict(schema="hcsn-r19-prospective-small-step-results-v1", protocol=protocol,
                source_freeze=freeze, records=records, cases=cases, gates=gates,
                stable_coordinate_coverage=coverage, passed=all(gates.values()),
                original_registered_gate=original_result["passed"], original_result="CONFIRMATION.json",
                process=dict(cpu_seconds=time.process_time() - start, wall_seconds=time.monotonic() - wall,
                             maximum_rss_linux_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                             python=platform.python_version(), numpy=np.__version__, scipy=scipy.__version__),
                limitations=["Full perturbation arrays represented by hashes and maximum-error witnesses, not archived arrays",
                             "Smaller steps only test local fixed-grid activity; no action-switch/global/continuum derivative qualification",
                             "Original failed gate remains failed; no full financial/neural gradient claim"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    result = run()
    with args.out.open("x") as stream:
        json.dump(result, stream, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps(dict(passed=result["passed"], gates=result["gates"], records=len(result["records"]),
                          maximum_scaled_error=max(r["witness"]["maximum_scaled_error"] for r in result["records"]),
                          process=result["process"]), indent=2))
    raise SystemExit(0 if result["passed"] else 1)
