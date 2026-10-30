"""Audit and disclose all108 cost jobs, including both risk implementations."""

import argparse
from collections import defaultdict
import itertools
from pathlib import Path

from experiments.hcsn_risk_cost_v1 import analyze as frozen
from experiments.hcsn_cost_scaling_v1.analyze import aggregate
from .study import PACKAGE, MATRIX_PROTOCOL, MODEL, PROFILE, factory, base


def backend_gates(matrix_study, vector_study, matrix, vector):
    lookup = {}
    for profile, study, protocol in (("matrix", matrix_study, matrix), ("vector", vector_study, vector)):
        for job in protocol["jobs"]:
            key = (job["task"], job["width"], job["depth"], job["seed"])
            name = f"{job['task']}__{job['model']}__w{job['width']}d{job['depth']}__{job['seed']}"
            path = Path(study) / "runs" / name / "COST.json"
            lookup[(profile, *key)] = base.read(path) if path.exists() else None
    gates = []
    for task, (width, depth), target in itertools.product(base.TASKS, base.SCALES, vector["quality"]["targets"]):
        pairs = []
        for seed in base.SEEDS:
            sides = {}
            for profile in ("matrix", "vector"):
                cost = lookup[(profile, task, width, depth, seed)]
                point = None if cost is None else next(row for row in cost["quality_selection"] if row["target"] == target)["checkpoint"]
                if point is None:
                    sides[profile] = None
                    continue
                evaluation = cost["evaluations"][point["sha256"]]
                sides[profile] = dict(checkpoint_sha256=point["sha256"],
                    test_accuracy=evaluation["test"]["accuracy"], training_cpu_seconds=point["training_cpu_seconds"],
                    timing=evaluation["timing"])
            a, b = sides["matrix"], sides["vector"]
            qualified = (a is not None and b is not None and a["test_accuracy"] >= target and
                         b["test_accuracy"] >= target and abs(a["test_accuracy"]-b["test_accuracy"]) <= .02)
            ratios = None
            if qualified:
                ratios = dict(matrix_over_vector_training_cpu=a["training_cpu_seconds"]/b["training_cpu_seconds"],
                    inference=[dict(batch=left["batch"],
                        cpu_matrix_over_vector=left["median_cpu_seconds"]/right["median_cpu_seconds"],
                        wall_matrix_over_vector=left["median_wall_seconds"]/right["median_wall_seconds"])
                        for left, right in zip(a["timing"], b["timing"], strict=True)])
            pairs.append(dict(seed=seed, qualified=bool(qualified), sides=sides, ratios=ratios))
        gates.append(dict(task=task, width=width, depth=depth, target=target,
                          all_seeds_qualify=all(row["qualified"] for row in pairs), pairs=pairs))
    return gates


def analyze(main_study, matrix_study, vector_study, protocol, output):
    if output.exists():
        raise FileExistsError("Preserve earlier analyses")
    p, matrix = base.verify(protocol), base.verify(MATRIX_PROTOCOL)
    assert p["jobs"] == matrix["jobs"]
    assert all(p[key] == matrix[key] for key in ("data", "optimization", "quality", "timing"))
    # Re-run the immutable audit under separate output subdirectories; no
    # earlier audit verdict or result is replaced.
    original = frozen.analyze(main_study, matrix_study, MATRIX_PROTOCOL, output / "matrix_contract")
    previous_factory = frozen.factory
    frozen.factory = factory
    try:
        optimized = frozen.analyze(main_study, vector_study, protocol, output / "vector_contract")
    finally:
        frozen.factory = previous_factory
    old_base = [row for row in original["rows"] if row["study"] == "original72"]
    new_base = [row for row in optimized["rows"] if row["study"] == "original72"]
    assert old_base == new_base
    rows = [dict(row, implementation_profile="original_registered_baseline") for row in old_base]
    rows += [dict(row, implementation_profile="original_float64_killed_matrix")
             for row in original["rows"] if row["study"] == "risk18"]
    rows += [dict(row, implementation_profile=PROFILE)
             for row in optimized["rows"] if row["study"] == "risk18"]
    keys = {(row["protocol_sha256"], row["task"], row["model"], row["width"], row["depth"], row["seed"]) for row in rows}
    assert len(keys) == len(rows)
    groups = defaultdict(list)
    for row in rows:
        groups[(row["task"], row["model"], row["implementation_profile"], row["width"], row["depth"])].append(row)
    summaries = [dict(task=k[0], model=k[1], implementation_profile=k[2], width=k[3], depth=k[4],
        parameters=v[0]["parameters"], **{name:aggregate([r[name] for r in v]) for name in
        ("test_accuracy", "updates", "whole_worker_cpu_seconds", "peak_rss_bytes")}) for k,v in sorted(groups.items())]
    complete = original["all_registered_jobs_completed"] and optimized["all_registered_jobs_completed"] and len(rows) == 108
    integrity = original["integrity_passed"] and optimized["integrity_passed"]
    comparisons = backend_gates(matrix_study, vector_study, matrix, p) if complete and integrity else []
    receipts = [dict(row, implementation_profile="original_registered_baseline" if row["study"] == "original72"
        else "original_float64_killed_matrix") for row in original["study_receipts"]]
    receipts += [dict(row, implementation_profile=PROFILE) for row in optimized["study_receipts"] if row["study"] == "risk18"]
    result = dict(schema="hcsn-all-risk-backends-cpu-cost-analysis.v1", integrity_passed=integrity,
        all_registered_jobs_completed=complete, expected=108, audited=len(rows), rows=rows, aggregates=summaries,
        matrix_external_gates=original["equal_quality_gates"], vector_external_gates=optimized["equal_quality_gates"],
        matrix_vector_quality_gates=comparisons,
        study_receipts=receipts, unique_complete_worker_cpu_seconds=sum(row["worker_cpu_seconds"] for row in receipts),
        contract_analysis_sha256={"matrix":base.digest(output / "matrix_contract/ANALYSIS.json"),
                                  "vector":base.digest(output / "vector_contract/ANALYSIS.json")},
        scope="All108 small CPU cost jobs; profiles always reported together; original72 deduplicated; no GPU, energy, foundation-scale or architectural-equivalence claim",
        original_results_changed=False, no_backend_selection=True)
    base.write(output / "RESULTS.json", result)
    lines = ["# Original encoders and both risk implementations", "",
        f"Audited {len(rows)}/108 unique jobs. Integrity: {integrity}; all registered jobs complete: {complete}.", "",
        "Both risk implementations are disclosed. The original72 are counted once; matrix18 and vector18 retain distinct protocol identities.", "",
        "| Task | Model | Implementation | Width/depth | Mean test accuracy | Mean complete worker CPU s |",
        "| --- | --- | --- | --- | ---: | ---: |"]
    lines += [f"| {r['task']} | {r['model']} | {r['implementation_profile']} | {r['width']}/{r['depth']} | {100*r['test_accuracy']['mean']:.2f}% | {r['whole_worker_cpu_seconds']['mean']:.3f} |" for r in summaries]
    lines += ["", f"All-three-seed matrix/vector quality gates: {sum(g['all_seeds_qualify'] for g in comparisons)}/{len(comparisons)}.", "",
        "Only qualified operating points support a same-quality ratio. These are descriptive gates, not statistical equivalence tests. The optimization changes numerical evaluation order; existing short-run equivalence checks do not prove identical long training trajectories."]
    (output / "REPORT.md").write_text("\n".join(lines) + "\n")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--main-study", type=Path, required=True)
    parser.add_argument("--matrix-study", type=Path, required=True)
    parser.add_argument("--vector-study", type=Path, required=True)
    parser.add_argument("--protocol", type=Path, default=PACKAGE / "PROTOCOL.json")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = analyze(args.main_study, args.matrix_study, args.vector_study, args.protocol, args.output)
    print({key:result[key] for key in ("integrity_passed", "all_registered_jobs_completed", "audited")})
