"""Refine a diagnosed full-trajectory CDF error without rewriting registration."""

import argparse
import hashlib
import json
from pathlib import Path
import time

import numpy as np

from brownian_reference import Case
from finite_volume_reference import solve


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    parser.add_argument("--case", default="turning_boundary")
    parser.add_argument("--cells", type=int, default=384)
    parser.add_argument("--phases", type=int, default=96)
    parser.add_argument("--steps", type=int, default=512)
    args = parser.parse_args()
    registration = json.loads((args.directory/"registration.json").read_text())
    case = Case(**next(c for c in registration["cases"] if c["name"] == args.case))
    path = args.directory/(args.case+f"_followup_{args.cells}_{args.phases}_{args.steps}.json")
    if path.exists():
        raise FileExistsError(path)
    started = time.perf_counter()
    result = solve(case, args.cells, args.phases, args.steps)
    raw = np.load(args.directory/(args.case+"_samples.npz"))
    times = np.array([r["time"] for r in result["history"]])
    hit = np.array([r["ever"] for r in result["history"]])
    empirical_hit = np.searchsorted(np.sort(raw["first_event_time"]), times, side="right")/len(raw["counts"])
    centers = np.asarray(result["final_centers"])
    width = centers[1]-centers[0]
    edges = np.r_[centers[0]-width/2, centers+width/2]
    unhit = np.sort(raw["final_position"][raw["counts"] == 0])
    empirical = np.searchsorted(unhit, edges, side="right")/len(raw["counts"])
    result.update(first_hit_cdf_max_difference=float(max(abs(hit-empirical_hit))),
        unhit_position_cdf_max_difference=float(max(abs(np.r_[0.,np.cumsum(result["final_killed"][:args.cells])]-empirical))),
        scope="Post-run targeted refinement of diagnosed CDF residual; original registration and outcomes retained",
        followup_source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        wall_seconds=time.perf_counter()-started)
    path.write_text(json.dumps(result, indent=2, allow_nan=False)+"\n")
    print(json.dumps({k: result[k] for k in ("first_hit_cdf_max_difference", "unhit_position_cdf_max_difference", "metrics", "wall_seconds")}))


if __name__ == "__main__":
    main()
