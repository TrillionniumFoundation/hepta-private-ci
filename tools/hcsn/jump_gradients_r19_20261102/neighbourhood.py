"""Explicit post-outcome local-neighbourhood FD qualification; old failure kept."""

import argparse
import hashlib
import json
from pathlib import Path
import platform
import time

import numpy as np
import scipy

from . import capture, coordinates as co, tangent
from .checks import error, left_error
from ..continuous_task_r18_20261101.task import DEFAULT


ROOT = Path(__file__).parent


def branch_changes(base, other):
    count, samples = 0, []
    for index in range(1, len(base["values"])):
        left, _, choice, _, _ = tangent.left_info(base, index)
        other_left, _, other_choice, _, _ = tangent.left_info(other, index)
        for stage, changed in (("left_LCP", choice != other_choice),):
            positions = np.argwhere(changed)
            count += len(positions)
            for mode, cell in positions[:max(0, 8 - len(samples))]:
                samples.append(dict(time=float(base["times"][index]), stage=stage, mode=int(mode), state=float(base["x"][cell])))
        if index % base["lag"] == 0:
            select = base["reset_values"][index, :, None] > left
            other_select = other["reset_values"][index, :, None] > other_left
            positions = np.argwhere(select != other_select)
            count += len(positions)
            for mode, cell in positions[:max(0, 8 - len(samples))]:
                samples.append(dict(time=float(base["times"][index]), stage="right_admission_max", mode=int(mode), state=float(base["x"][cell])))
    return dict(count=count, first_locations=samples)


def run(output):
    output.mkdir(exist_ok=False)
    freeze = json.loads((ROOT / "SOURCE_FREEZE_NEIGHBOURHOOD.json").read_text())
    inherited = json.loads((ROOT / "SOURCE_FREEZE.json").read_text())
    for manifest in (freeze, inherited):
        for name, digest in manifest["files"].items():
            if hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != digest:
                raise RuntimeError(f"Changed frozen source: {name}")
    protocol = json.loads((ROOT / "NEIGHBOURHOOD_PROTOCOL.json").read_text())
    started, wall = time.process_time(), time.perf_counter()
    records, crossings = [], []
    for sigma in protocol["sigma_profiles"]:
        raw = co.encode(DEFAULT); raw[0] = np.log(sigma)
        for dx, dt in protocol["meshes"]:
            s, p = capture.solve(co.decode(raw), dx, dt), capture.reference(co.decode(raw), dx, dt)
            j, r = tangent.jump(s, raw), tangent.positive(p, raw)
            for coordinate, name in enumerate(co.NAMES):
                row = dict(sigma=sigma, dx=dx, dt=dt, coordinate=name, finite_difference=[])
                for step in protocol["fd_steps"]:
                    offset = np.eye(co.P)[coordinate] * step
                    plus, minus = capture.solve(co.decode(raw + offset), dx, dt), capture.solve(co.decode(raw - offset), dx, dt)
                    pp, pm = capture.reference(co.decode(raw + offset), dx, dt), capture.reference(co.decode(raw - offset), dx, dt)
                    fd = (plus["values"] - minus["values"]) / (2 * step)
                    fl = {key: (plus["left_limits"][key] - minus["left_limits"][key]) / (2 * step) for key in plus["left_limits"]}
                    fref = (pp["values"] - pm["values"]) / (2 * step)
                    js, jm = tangent.signature(plus), tangent.signature(minus)
                    ps, pmask = tangent.signature(pp, True), tangent.signature(pm, True)
                    row["finite_difference"].append(dict(step=step,
                        jump_right_error=error(j["jacobian"][..., coordinate], fd),
                        jump_left_error=left_error({key: value[..., coordinate] for key, value in j["left_jacobians"].items()}, fl),
                        positive_error=error(r["jacobian"][..., coordinate], fref),
                        smooth_jump=js["branch_sha256"] == jm["branch_sha256"] == j["branch_sha256"] and js["critical_count"] == jm["critical_count"] == 0,
                        smooth_positive=ps["branch_sha256"] == pmask["branch_sha256"] == r["branch_sha256"] and ps["critical_count"] == pmask["critical_count"] == 0))
                records.append(row)
            if sigma == 1.3 and dx == .0625:
                for coordinate in (0, 5):
                    for sign in (-1., 1.):
                        perturbation = np.eye(co.P)[coordinate] * 1e-5 * sign
                        other = capture.solve(co.decode(raw + perturbation), dx, dt)
                        crossings.append(dict(coordinate=co.NAMES[coordinate], step=sign * 1e-5, **branch_changes(s, other)))
    all_items = [item for row in records for item in row["finite_difference"]]
    gates = dict(all90_coordinates_attempted=len(records) == 90 and all(sum(row["coordinate"] == name for row in records) == 6 for name in co.NAMES),
        every_registered_pair_stays_on_regular_branch=all(item["smooth_jump"] and item["smooth_positive"] for item in all_items),
        same_original_fd_tolerance=all(max(item["jump_right_error"], item["jump_left_error"], item["positive_error"]) < protocol["unchanged_fd_tolerance"] for item in all_items),
        original_large_step_crossing_identified=all(sum(row["count"] for row in crossings if row["coordinate"] == name) > 0 for name in ("log_sigma", "reset_x")))
    result = dict(schema="hcsn-r19-local-neighbourhood-followup-v1", classification=protocol["classification"],
        source_freeze=freeze, gates=gates, parameter_names=co.NAMES, records=records,
        preserved_large_step_diagnostics=crossings, original_result="run_01/RESULTS.json",
        maximum_errors={key: max(item[key] for item in all_items) for key in ("jump_right_error", "jump_left_error", "positive_error")},
        cpu_seconds=time.process_time() - started, wall_seconds=time.perf_counter() - wall,
        runtime=dict(python=platform.python_version(), numpy=np.__version__, scipy=scipy.__version__), production_activation=False)
    with (output / "RESULTS.json").open("x") as stream:
        json.dump(result, stream, indent=2, allow_nan=False); stream.write("\n")
    print(json.dumps(dict(gates=gates, maximum_errors=result["maximum_errors"], cpu_seconds=result["cpu_seconds"]), indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(); parser.add_argument("--output", type=Path, required=True)
    run(parser.parse_args().output)
