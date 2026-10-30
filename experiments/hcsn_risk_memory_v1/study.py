"""Register a fresh fixed128 cohort and call the unchanged frozen worker.

Only the model factory is replaced in an isolated child process. Update count,
minibatch draws, loss, optimizer, CPU cap, selection lock and heldout ordering
are the original equal_updates.worker implementation.
"""

import argparse
import copy
import datetime
import json
from pathlib import Path
import subprocess

from .train_equivalence import ROOT, PACKAGE, UPSTREAM, sha, verify, write


def register(protocol_path, output):
    if protocol_path.exists() or output.exists():
        raise FileExistsError("Preserve earlier protocols and cohorts")
    upstream = json.loads(UPSTREAM.read_bytes())
    if sha(UPSTREAM) != "86bd8bc59c08b96cf76de482cfde007b251ae7fcb2295ff44a4ad0616f1d9a56":
        raise RuntimeError("Frozen fixed128 registration identity changed")
    verify(upstream)
    preflight_path = PACKAGE / "results/train_preflight001/RESULTS.json"
    preflight = json.loads(preflight_path.read_bytes())
    if sha(preflight_path) != "b7e4e9be02eb1fad601005fef8ff72e6bc8a79aa8c598b97d611a58e91722e02":
        raise RuntimeError("Reviewed preflight result identity changed")
    if not preflight["passed"] or not preflight["significant_memory_goal_passed"]:
        raise RuntimeError("Numerical and memory preflight gates must pass")
    verify(dict(source_files_sha256=preflight["source_files_sha256"], data=upstream["data"]))
    expected_pairs = {(task, arm) for task in upstream["data"] for arm in upstream["models"]}
    if {(row["task"], row["model"]) for row in preflight["pairs"]} != expected_pairs:
        raise RuntimeError("Incomplete all-arm train-only preflight")
    if not all(item["bitwise_equal"] for row in preflight["pairs"] for item in row["comparisons"]):
        raise RuntimeError("Reviewed three-update bitwise equivalence is missing")
    previous_path = ROOT / "experiments/hcsn_risk_ablation_v1/results/risk128_4w/ABORTED.json"
    previous = json.loads(previous_path.read_bytes())
    if previous["status"] != "aborted" or previous["completed"] != 3 or previous["failures"] != 1:
        raise RuntimeError("Previous aborted cohort identity differs")
    kernel_path = PACKAGE / "results/kernel_preflight001/RESULTS.json"
    if not json.loads(kernel_path.read_bytes())["passed"]:
        raise RuntimeError("Kernel preflight failed")
    evaluation_path = PACKAGE / "results/evaluation_shape_preflight001/RESULTS.json"
    namespace_path = PACKAGE / "results/namespace_preflight001/RESULTS.json"
    evaluation = json.loads(evaluation_path.read_bytes())
    namespace = json.loads(namespace_path.read_bytes())
    if not evaluation["passed"] or not namespace["passed"]:
        raise RuntimeError("Evaluation-shape memory and real-child namespace probes must pass")
    verify(dict(source_files_sha256=evaluation["source_files_sha256"], data=upstream["data"]))
    if namespace["source_sha256"] != sha(PACKAGE / "resource_accounting.py"):
        raise RuntimeError("Resource accounting changed after the real-child probe")
    sources = dict(upstream["source_files_sha256"])
    if len(sources) != 59:
        raise RuntimeError("All 59 original fixed128 sources must be preserved")
    sources[str(UPSTREAM.relative_to(ROOT))] = sha(UPSTREAM)
    for name in ("vector_kernel.py", "model.py", "kernel_validation.py", "train_equivalence.py",
                 "study.py", "analyze.py", "evaluation_memory.py", "resource_queue.py",
                 "resource_accounting.py", "MEMORY_PROFILE.md",
                 "COPY_MANIFEST.json", "INDEPENDENT_REVIEW.json"):
        path = PACKAGE / name
        sources[str(path.relative_to(ROOT))] = sha(path)
    protocol = copy.deepcopy(upstream)
    protocol.update(schema="hcsn-risk-memory-profile-fixed128.v1", study_id="memory_profile002",
        registered_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        source_commit=subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        status_at_registration="fresh_cohort_not_started; previous aborted cohort preserved; train-only numerical/resource revision",
        source_files_sha256=sources,
        outcome_scope="post-baseline exploratory fresh fixed128 cohort using equivalent backward-risk-vector numerical profile; previously observed datasets and earlier aborted cohort exist; three-update equivalence does not prove identical 128-update trajectories; fixed128 does not establish convergence")
    protocol["model_identity"].update(
        original_fixed128_protocol=str(UPSTREAM.relative_to(ROOT)),
        original_fixed128_protocol_sha256=sha(UPSTREAM), frozen_fixed128_source_count=59,
        all_59_source_hashes_identical=True,
        numerical_profile="backward_poisson_risk_vector_v1",
        equal_cpu_implementation="frozen original float64 killed-matrix time transition",
        equal_updates_implementation="new backward Poisson risk vector; original matrix fallback above 16 chunks",
        three_update_train_equivalence="all 7516 recorded arrays bitwise equal, one seed, seven arms, both train datasets",
        long_trajectory_equivalence_claim=False)
    protocol["upstream_execution_revision"] = protocol.pop("execution_revision", None)
    protocol["execution"]["historical_original_train_only_timing_forecast_cpu_seconds"] = \
        protocol["execution"].pop("train_only_timing_forecast_cpu_seconds")
    protocol["execution"]["historical_forecast_is_measurement"] = \
        protocol["execution"].pop("forecast_is_measurement")
    protocol["execution"].update(workers=4, workers_is_upper_limit=True, initial_desired_workers=2,
        per_worker_peak_budget_bytes=int(1.25 * 1024 ** 3), required_shared_reserve_bytes=2 * 1024 ** 3,
        scheduler="experiments.hcsn_risk_memory_v1.resource_queue; namespace-verified own worker memory; no changes to job order",
        authorization="public seal required before first dispatch; later worker increases require recorded root authorization",
        fresh_cohort=True, reuse_any_previous_completed_job=False)
    protocol["joint_inference"].update(
        equal_updates_family="memory_profile002: original fixed128 four primary contrasts, separately Holm-adjusted",
        numerical_implementation_disclosure="equal-CPU matrix implementation versus fresh equal-update backward-vector implementation; validated kernel and three-update equivalence, not proof of identical long trajectories",
        aborted_cohort="report separately with all costs; never pool its two completed jobs into this family")
    protocol["numerical_revision"] = dict(
        rationale="OOM resource failure; optimize unnecessary dense risk time propagation using the same finite polynomial",
        selection_basis="mathematical equivalence and train-only memory/CPU; no predictive score used",
        kernel_preflight=dict(path=str(kernel_path.relative_to(ROOT)), sha256=sha(kernel_path)),
        train_preflight=dict(path=str(preflight_path.relative_to(ROOT)), sha256=sha(preflight_path)),
        label_free_evaluation_shape_preflight=dict(path=str(evaluation_path.relative_to(ROOT)), sha256=sha(evaluation_path)),
        real_child_namespace_probe=dict(path=str(namespace_path.relative_to(ROOT)), sha256=sha(namespace_path)),
        unchanged=["112 jobs", "job order", "seven model arms", "eight seeds", "datasets", "minibatch draws",
                   "128 updates", "Adam/lr/clipping/loss", "900 training CPU cap", "heldout lock order", "statistical gates"],
        previous_attempt=dict(path=str(previous_path.relative_to(ROOT)), sha256=sha(previous_path),
            successful_jobs=2, failed_jobs=1, unstarted_jobs=109,
            complete_child_cpu_seconds=previous["complete_child_cpu_seconds"], reused_rows=0))
    for key in ("data", "jobs", "models", "seeds", "mechanism", "optimization"):
        if protocol[key] != upstream[key]:
            raise RuntimeError("Prohibited design change: " + key)
    verify(protocol)
    output.mkdir(parents=True, exist_ok=False)
    protocol_path.parent.mkdir(parents=True, exist_ok=True)
    write(protocol_path, protocol)
    write(output / "REGISTRATION.json", dict(protocol_sha256=sha(protocol_path), jobs=112,
        registered_utc=protocol["registered_utc"], status="fresh_cohort_before_main_training",
        original_protocol_sha256=sha(UPSTREAM), numerical_profile=protocol["model_identity"]["numerical_profile"]))
    print(json.dumps(dict(protocol=str(protocol_path), protocol_sha256=sha(protocol_path),
                         output=str(output), jobs=112, source_count=len(sources))), flush=True)


def worker(protocol_path, output, job):
    from experiments.hcsn_risk_ablation_v1 import equal_updates
    from .model import build_model

    protocol = json.loads(protocol_path.read_bytes())
    verify(protocol)
    if protocol["schema"] != "hcsn-risk-memory-profile-fixed128.v1":
        raise ValueError("Memory-profile registration required")
    original_factory = equal_updates.build_model
    equal_updates.build_model = build_model
    try:
        return equal_updates.worker(protocol_path, output, job)
    finally:
        equal_updates.build_model = original_factory


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("register", "worker"))
    parser.add_argument("--protocol", type=Path, default=PACKAGE / "PROTOCOL.json")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--task")
    parser.add_argument("--model")
    parser.add_argument("--seed", type=int)
    args = parser.parse_args()
    if args.action == "register":
        register(args.protocol.resolve(), args.output.resolve())
    else:
        worker(args.protocol.resolve(), args.output.resolve(),
               dict(task=args.task, model=args.model, seed=args.seed))
