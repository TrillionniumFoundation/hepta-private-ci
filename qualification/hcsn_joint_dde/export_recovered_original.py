"""New, source-bound export from the recovered original training journal.

No model step or optimizer runs. Old lost JSON bytes are not reconstructed.
"""

import argparse
import hashlib
import inspect
import json
import math
from pathlib import Path

import numpy as np

from qualification.hcsn_graded.spatial import GradedSpatialGenerator
from qualification.hcsn_initial_law.migration import MigrationBasis, migrate


def sha(data):
    return hashlib.sha256(data).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--journal", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    raw = args.journal.read_bytes()
    expected = "2a9fc79e38311147451511c5b6ecc17449faa544cc38bcaab567e4f9cbe08517"
    if sha(raw) != expected:
        raise ValueError("original journal hash differs")
    lines = raw.splitlines()
    if (
        sha(lines[24])
        != "fed0107753b35d114c0cb8c3c668fb7f205b78697bb23db98c6e5fafd8a4054b"
    ):
        raise ValueError("original row hash differs")
    row = json.loads(lines[24])
    prefix = sum(
        sum(sum(r) for r in json.loads(line)["valid_mask"]) for line in lines[:24]
    )
    if row["step"] != 24 or prefix != 896 or not row["valid_mask"][0][1]:
        raise ValueError("selected original visit differs")
    state = row["states"][1]
    probability, content = (
        np.asarray(state["probability"])[0],
        np.asarray(state["content_mass"])[0],
    )
    if probability.shape != (25,) or content.shape != (25, 4):
        raise ValueError("original fixed-state shape differs")
    physics = row["physical_parameters"]
    previous_npz = {
        128: "fda047c1a8fce3cc042246b5249859cd0a0ba449647460ba9e0a39592386ff7d",
        512: "b72377db558eaba0fff7b52f54617af4d6eb350adab19065986ee65a8e9dcdc0",
    }
    for n in (128, 512):
        spatial = GradedSpatialGenerator(n, 8.0, physics["mu"], physics["sigma"], 6.0)
        basis = MigrationBasis(
            4.8, 16, 1.0, 0.2, 8, 8.0, n, actual_nodes=tuple(spatial.nodes)
        )
        migrated = migrate(
            basis, probability, content, identity=f"seed37-c0_b1-step24-pos1-n{n}"
        )
        active, marked, phase = migrated.solve_inputs()
        path = args.output / f"seed37-c0_b1-step24-pos1-n{n}.npz"
        np.savez_compressed(path, active=active, content=marked, nodes=spatial.nodes)
        digest = sha(path.read_bytes())
        metadata = dict(
            case="original_recovered_fixed_posterior",
            scope="A new JSON export from the recovered hash-bound original journal row. The original selected posterior and four signed contents are migrated once and then held fixed. No historical step or optimizer replay, no derivative through migration. Lost original JSON bytes are not restored.",
            candidate_source_commit="4bb30c1687b320fb37709732e8001b31baef07ec",
            intervals=n,
            source_visit=dict(
                index=897,
                update_index=24,
                position=1,
                model_sha256=row["model_sha256"],
                parameters=physics,
                posterior=state["probability"],
                content_mass=state["content_mass"],
                episode_id=row["episode_id"],
            ),
            recovered_artifact=dict(
                id=13904346161,
                sha256="8c94ecc88540079506e1702634049057bca5fb464b9c97f06fc923e013db81f8",
                size=19217333,
            ),
            source_trace_sha256=None,
            source_journal_sha256=expected,
            source_journal=str(args.journal),
            original_line_index=24,
            original_line_sha256=sha(lines[24]),
            valid_prefix_positions=prefix,
            current_recorded_gap=row["dt"][0][1],
            historical_next_gap=row["dt"][0][2],
            reset_distance=math.log(physics["absolute_reset"])
            - physics["log_boundary"],
            physics=physics,
            npz_sha256=digest,
            previous_lost_npz_sha256=previous_npz[n],
            reproduces_previous_npz_bytes=digest == previous_npz[n],
            exporter_sha256=sha(Path(__file__).read_bytes()),
            migration_source_sha256=sha(
                Path(inspect.getfile(MigrationBasis)).read_bytes()
            ),
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
            sha(path.with_suffix(".json").read_bytes()),
            digest,
            metadata["reproduces_previous_npz_bytes"],
        )
    if sha(args.journal.read_bytes()) != expected:
        raise ValueError("original changed during export")


if __name__ == "__main__":
    main()
