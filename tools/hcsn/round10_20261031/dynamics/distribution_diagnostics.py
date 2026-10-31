"""Additional retained-distribution diagnostics; not a post-hoc acceptance gate."""

import argparse
import hashlib
import json
import math
from pathlib import Path

import numpy as np


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    summary = json.loads((args.directory/"summary.json").read_text())
    records = []
    for case in summary["cases"]:
        name, fine = case["case"], case["resolutions"][-1]
        raw = np.load(args.directory/(name+"_samples.npz"))
        grid = json.loads((args.directory/(name+f"_grid_{fine['cells']}_{fine['stages']}_{fine['steps']}.json")).read_text())
        size = len(raw["counts"])
        times = np.array([row["time"] for row in grid["history"]])
        numerical_hit = np.array([row["ever"] for row in grid["history"]])
        empirical_hit = np.searchsorted(np.sort(raw["first_event_time"]), times, side="right")/size
        centers = np.asarray(grid["final_centers"])
        width = centers[1]-centers[0]
        edges = np.r_[centers[0]-width/2, centers+width/2]
        killed = np.asarray(grid["final_killed"][:fine["cells"]])
        numerical_joint = np.r_[0., np.cumsum(killed)]
        unhit_positions = np.sort(raw["final_position"][raw["counts"] == 0])
        empirical_joint = np.searchsorted(unhit_positions, edges, side="right")/size
        gap = min(row["events"]-row["ever"] for row in grid["history"])
        if gap < -1e-10:
            raise AssertionError("Repeated-event expectation fell below first-event probability")
        records.append(dict(case=name, samples=size,
            first_hit_cdf_max_difference=float(np.max(abs(numerical_hit-empirical_hit))),
            never_hit_and_final_position_cdf_max_difference=float(np.max(abs(numerical_joint-empirical_joint))),
            minimum_expected_count_minus_first_probability=gap,
            monte_carlo_uniform_cdf_bound_99_percent_familywise=math.sqrt(math.log(1200)/(2*size)),
            time_grid=times.tolist(), numerical_first_hit_cdf=numerical_hit.tolist(),
            empirical_first_hit_cdf=empirical_hit.tolist(), position_edges=edges.tolist(),
            numerical_unhit_position_cdf=numerical_joint.tolist(), empirical_unhit_position_cdf=empirical_joint.tolist()))
    out = dict(schema="hcsn.round10.moving.distribution-diagnostic.v1", records=records,
        interpretation="Post-run diagnostics, not changed acceptance criteria. DKW/Bonferroni bounds cover Monte Carlo noise only, not finite-volume error.",
        diagnostic_source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    (args.directory/"distribution_diagnostics.json").write_text(json.dumps(out, indent=2, allow_nan=False)+"\n")
    print(json.dumps([{key: row[key] for key in ("case", "first_hit_cdf_max_difference", "never_hit_and_final_position_cdf_max_difference")} for row in records]))


if __name__ == "__main__":
    main()
