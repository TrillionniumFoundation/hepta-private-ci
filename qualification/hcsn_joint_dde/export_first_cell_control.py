"""Create a disclosed control law, never reconstruct a lost original posterior."""

import hashlib
import inspect
import json
import math
from pathlib import Path

import numpy as np

from qualification.hcsn_graded.spatial import GradedSpatialGenerator
from qualification.hcsn_initial_law.migration import MigrationBasis, migrate


def main():
    output = Path(
        "qualification/hcsn_joint_dde/evidence/large-physical-20261112/control-mixture-inputs"
    )
    output.mkdir(parents=True, exist_ok=False)
    physics = dict(
        mu=-0.11999999999999998,
        sigma=0.35,
        discount=0.15,
        log_boundary=0.006853103411896752,
        absolute_reset=1.3771277643359572,
    )
    probability = np.zeros(25)
    probability[0] = 0.6
    probability[17] = 0.4
    content = np.column_stack(
        [2 * probability, -3 * probability, 0.7 * probability, -0.2 * probability]
    )
    for n in (128, 512):
        spatial = GradedSpatialGenerator(n, 8.0, physics["mu"], physics["sigma"], 6.0)
        basis = MigrationBasis(
            4.8, 16, 1.0, 0.2, 8, 8.0, n, actual_nodes=tuple(spatial.nodes)
        )
        migrated = migrate(
            basis, probability, content, identity=f"first-cell-control-n{n}"
        )
        active, marked, phase = migrated.solve_inputs()
        path = output / f"uniform-phase-control-n{n}.npz"
        np.savez_compressed(path, active=active, content=marked, nodes=spatial.nodes)
        metadata = dict(
            case="first_uniform_plus_first_phase_control",
            scope="Constructed .6 first Uniform[0,.3] plus .4 first remaining Uniform[0,.025] law with four declared signed marks, evaluated at an original-parameter snapshot. This is not the lost original posterior, training replay, or an independent future task.",
            candidate_source_commit="4bb30c1687b320fb37709732e8001b31baef07ec",
            intervals=n,
            source_visit=dict(
                index=None,
                update_index=None,
                position=None,
                model_sha256=None,
                parameters=physics,
            ),
            source_trace_sha256=None,
            source_journal_sha256=None,
            current_recorded_gap=0.02,
            historical_next_gap=None,
            reset_distance=math.log(physics["absolute_reset"])
            - physics["log_boundary"],
            physics=physics,
            npz_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
            exporter_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            migration_source_sha256=hashlib.sha256(
                Path(inspect.getfile(MigrationBasis)).read_bytes()
            ).hexdigest(),
            source_probability=probability.tolist(),
            source_content=content.tolist(),
            migration_report=migrated.report,
            phase=[
                dict(
                    identity=p.identity,
                    start=str(p.start),
                    end=str(p.end),
                    mass=str(p.mass),
                    content=list(map(str, p.content)),
                )
                for p in phase
            ],
        )
        path.with_suffix(".json").write_text(
            json.dumps(metadata, indent=2, sort_keys=True) + "\n"
        )
        print(
            n,
            hashlib.sha256(path.with_suffix(".json").read_bytes()).hexdigest(),
            metadata["npz_sha256"],
        )


if __name__ == "__main__":
    main()
