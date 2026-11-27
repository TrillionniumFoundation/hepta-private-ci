"""Fixed synthetic killed-generator development probe; no training or adoption."""

import argparse
import hashlib
import json
from pathlib import Path
import platform
import time

import numpy as np
import scipy

from qualification.hcsn_boundary_audit.spatial_generator import (
    KilledSpatialGenerator,
    continuum_lower_hit,
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("preserve prior attempts; output must be new")
    wall, cpu = time.perf_counter(), time.process_time()
    paths = [Path(__file__), Path(__file__).with_name("spatial_generator.py")]
    before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    rows, composition = [], []
    for drift in (-0.4, 0.0, 0.4):
        for discount in (0.01, 0.3, 2.0):
            for n in (16, 32, 64, 128):
                model = KilledSpatialGenerator(n, 2.0, drift, 0.6)
                exact = continuum_lower_hit(
                    np.linspace(0, 2, n + 1), 2, drift, 0.6, discount
                )
                actual = model.discounted_lower_hit(discount)
                residual = (model.matrix() @ actual - discount * actual)[1:-1]
                rows.append(
                    dict(
                        intervals=n,
                        mu=drift,
                        sigma=0.6,
                        discount=discount,
                        endpoint=2.0,
                        reference=exact.tolist(),
                        discrete=actual.tolist(),
                        maximum_absolute_error=float(np.max(np.abs(actual - exact))),
                        maximum_interior_residual=float(np.max(np.abs(residual))),
                    )
                )
        model = KilledSpatialGenerator(24, 2.0, drift, 0.6)
        schedule = [0.001, 0.003, 0.02, 0.04, 0.08, 0.16]
        product = np.eye(25)
        for dt in schedule:
            product = product @ model.transition(dt)
        direct = model.transition(sum(schedule))
        composition.append(
            dict(
                mu=drift,
                schedule=schedule,
                maximum_row_tv=float(
                    np.max(np.sum(np.abs(product - direct), axis=1)) / 2
                ),
                maximum_mass_error=float(np.max(np.abs(direct.sum(axis=1) - 1))),
                minimum_transition_entry=float(np.min(direct)),
            )
        )
    if before != {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}:
        raise RuntimeError("executing source changed")
    result = dict(
        schema="hcsn-killed-spatial-generator-development-v1",
        source_sha256=before,
        runtime=dict(
            python=platform.python_version(),
            numpy=np.__version__,
            scipy=scipy.__version__,
        ),
        reference_scope="finite interval killed first hit; two absorbing endpoints; no returning tail or reset",
        rows=rows,
        irregular_composition=composition,
        wall_seconds=time.perf_counter() - wall,
        cpu_seconds=time.process_time() - cpu,
        cost_scope="probe process after imports; shared host; no training/model/energy measurement",
        original_14336_visits_requalified=False,
        full_hcsn_repaired=False,
        production_admission="HOLD_NO_GO",
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as stream:
        json.dump(result, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")
    print(
        json.dumps(
            dict(
                rows=len(rows),
                irregular_composition=composition,
                maximum_n128_error=max(
                    r["maximum_absolute_error"] for r in rows if r["intervals"] == 128
                ),
                wall_seconds=result["wall_seconds"],
                cpu_seconds=result["cpu_seconds"],
            )
        )
    )


if __name__ == "__main__":
    main()
