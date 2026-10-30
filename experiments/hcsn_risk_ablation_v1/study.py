"""Independent post-baseline registration and complete-worker CPU ledger."""

import argparse
import datetime
import json
import os
from pathlib import Path
import random
import subprocess
import sys
import time

from experiments.hcsn_free_boundary_v1 import training
from experiments.hcsn_distributional_v2.content_study import evaluate
from .model import MODEL_NAMES, build_model


ROOT = Path(__file__).resolve().parents[2]
PACKAGE = Path(__file__).resolve().parent
CONTRASTS = (("risk_margin_j_risk", "risk_margin_j"),
             ("risk_margin_j_risk", "risk_ordinary_two_gates"),
             ("risk_margin_j", "risk_margin"),
             ("risk_margin_j_risk", "risk_conditional_full"))
SECONDARY = (("risk_margin", "risk_ordinary_two_gates"),
             ("risk_margin_j_risk", "risk_fixed_full"),
             ("risk_margin_j_risk", "risk_direct_full"))


def verify(path):
    protocol = json.loads(Path(path).read_bytes())
    for relative, digest in protocol["source_files_sha256"].items():
        if training._sha256(ROOT / relative) != digest:
            raise RuntimeError("Frozen source changed: " + relative)
    for record in protocol["data"].values():
        if training._sha256(ROOT / record["path"]) != record["sha256"]:
            raise RuntimeError("Frozen dataset changed")
    return protocol


def register(protocol_path, output, math_audit):
    protocol_path, output, math_audit = Path(protocol_path), Path(output), Path(math_audit)
    if protocol_path.exists() or output.exists():
        raise FileExistsError("Use new protocol and output paths")
    source = json.loads((ROOT / "experiments/hcsn_distributional_v2/CONTENT002_PROTOCOL.json").read_bytes())
    preflight_path = PACKAGE / "results/train_preflight002/RESULTS.json"
    preflight = json.loads(preflight_path.read_bytes())
    mathematical = json.loads(math_audit.read_bytes())
    if not preflight["passed"] or not preflight["train_only"] or not mathematical["passed"]:
        raise RuntimeError("Training-only and independent mathematical gates must pass")
    sources = dict(source["source_files_sha256"])
    for absolute, expected in mathematical["source_sha256"].items():
        path = Path(absolute)
        if training._sha256(path) != expected:
            raise RuntimeError("Independent mathematical audit source changed: " + str(path))
        sources[str(path.relative_to(ROOT))] = expected
    for relative, digest in preflight["source_files_sha256"].items():
        if training._sha256(ROOT / relative) != digest:
            raise RuntimeError("Preflight source changed: " + relative)
        sources[relative] = digest
    for path in sorted(PACKAGE.glob("*.py")):
        sources[str(path.relative_to(ROOT))] = training._sha256(path)
    for relative, digest in sources.items():
        if training._sha256(ROOT / relative) != digest:
            raise RuntimeError("Frozen dependency changed: " + relative)
    jobs = [dict(task=task, model=arm, seed=seed) for task in ("selective_copy", "mqar")
            for arm in MODEL_NAMES for seed in range(9401, 9409)]
    random.Random(202610301).shuffle(jobs)
    protocol = dict(schema="hcsn-first-event-risk-study.v1", study_id="risk001",
        registered_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        source_commit=subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        status_at_registration="train_only_preflight_complete_no_risk001_heldout_access",
        train_only_design_changes=[
            "Added input-conditioned direct threshold before any risk001 heldout access",
            "Seven candidate contrasts exceed eight-seed Holm resolution; fixed four primary and three descriptive comparisons before training"],
        outcome_scope="post-baseline exploratory feature-engineering study; previously observed datasets; not pristine confirmation",
        source_files_sha256=sources, data={task: source["data"][task] for task in ("selective_copy", "mqar")},
        preflight=dict(path=str(preflight_path.relative_to(ROOT)), sha256=training._sha256(preflight_path)),
        independent_math=dict(path=str(math_audit.resolve().relative_to(ROOT)), sha256=training._sha256(math_audit)),
        jobs=jobs, seeds=list(range(9401, 9409)), models=list(MODEL_NAMES),
        optimization=dict(learning_rates=[.001], training_cpu_seconds_per_lr=20.0,
            primary_cpu_checkpoints=[5.0, 10.0, 20.0], width=32, depth=1,
            batch_size=32, max_updates=65536, threads=1, gradient_clip_l2=2.0,
            optimizer="torch.optim.Adam defaults", loss="cross_entropy_only",
            selection="validation CE at common CPU gates; ties earlier CPU/step; heldout after durable lock",
            fixed128="optional descriptive snapshot; not an additional selection opportunity"),
        mechanism=dict(contrasts=[dict(treatment=a, control=b) for a, b in CONTRASTS],
            secondary_contrasts=[dict(treatment=a, control=b) for a, b in SECONDARY],
            unit="paired initialization seed; mean of selective_copy and mqar test accuracy differences",
            exact_test="two-sided sign flip over eight paired seed differences; Holm across four primary contrasts",
            sign_flip_resolution="minimum p=2/256=0.0078125; seven Holm primary tests could never reject at .05; three other contrasts are descriptive",
            practical_mean_gain=.01, holm_alpha=.05, nominal_t95_lower_must_exceed=0.0,
            heldout_selection=False, task_specific_tests="descriptive only"),
        features=dict(common="full probability state and all seven physical coefficients in every arm",
            ordinary=["active_mean", "variance", "active_mass"],
            margin=["margin", "active_mean", "variance"],
            margin_j=["margin", "continuation_J", "variance"],
            full=["margin", "continuation_J", "first_event_probability_in_current_interval"],
            interpretation="equal-capacity feature replacement, not pure information removal",
            no_default_put_claim=True, fixed_boundary=1.2,
            direct_boundary="0.35 + 3.99 sigmoid(theta); initialize 1.2; input-independent learned threshold",
            conditional_boundary="0.35 + 3.99 sigmoid(theta + slope * mu); initialize theta to 1.2 and slope to zero; same domain as direct threshold",
            boundary_scope="free boundary solves Brownian/Erlang surrogate, not finite-grid or task optimum"),
        numerics=dict(regenerative_projection="roundoff_unit_mass_v1; record corrections; no negative clipping",
            killed_kernel="float64 unnormalized fixed Poisson series; no survival normalization",
            risk_semantics="p dot (1 - R_nohit exp(Q_nohit.T dt) 1); boundary jump included; self-events killed",
            unit_mass_identity="risk + surviving_mass = incoming_mass; final cast roundoff is reported",
            smoothness="first derivatives away from remap/upwind/reset interpolation knots"),
        execution=dict(workers=2, expected_searches=112, expected_lr_candidates=112,
            nominal_training_cpu_seconds=2240.0, failure_policy="stop launches and drain active workers",
            cost="complete wait4 worker CPU includes imports/setup/train/validation/checkpoint/heldout; training is nested",
            energy_measured=False, main_content002_unchanged=True))
    output.mkdir(parents=True, exist_ok=False)
    protocol_path.parent.mkdir(parents=True, exist_ok=True)
    training._write_json(protocol_path, protocol)
    training._write_json(output / "REGISTRATION.json", dict(protocol_sha256=training._sha256(protocol_path),
        jobs=len(jobs), registered_utc=protocol["registered_utc"], status="before_main_training"))
    return protocol


def worker(protocol_path, output, job):
    protocol = verify(protocol_path)
    if job not in protocol["jobs"]:
        raise ValueError("Unregistered job")
    optimization = protocol["optimization"]
    original = training.build_model, training.evaluate
    training.build_model, training.evaluate = build_model, evaluate
    try:
        summary = training.run_search(ROOT / protocol["data"][job["task"]]["path"],
            job["model"], job["seed"], output,
            cpu_seconds=optimization["training_cpu_seconds_per_lr"],
            width=optimization["width"], depth=optimization["depth"],
            batch_size=optimization["batch_size"], max_updates=optimization["max_updates"],
            learning_rates=optimization["learning_rates"])
    finally:
        training.build_model, training.evaluate = original
    verify(protocol_path)
    training._write_json(Path(output) / "IDENTITY.json", dict(job=job, status="completed",
        protocol_sha256=training._sha256(protocol_path), source_files_sha256=protocol["source_files_sha256"],
        dataset_sha256=protocol["data"][job["task"]]["sha256"]))
    return summary


def run(protocol_path, output):
    protocol_path, output = Path(protocol_path).resolve(), Path(output).resolve()
    protocol = verify(protocol_path)
    digest = training._sha256(protocol_path)
    registration = json.loads((output / "REGISTRATION.json").read_bytes())
    if registration["protocol_sha256"] != digest or (output / "runs").exists():
        raise ValueError("Registration mismatch or existing execution; never overwrite")
    (output / "runs").mkdir()
    (output / "process_logs").mkdir()
    environment = os.environ.copy()
    environment.update({key: "1" for key in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS")})
    pending, active, records, stopped = list(protocol["jobs"]), {}, [], False
    start_wall, start_cpu = time.perf_counter(), time.process_time()
    while pending or active:
        stopped = stopped or (output / "STOP_REQUESTED.json").exists()
        while pending and not stopped and len(active) < protocol["execution"]["workers"]:
            job = pending.pop(0)
            name = f"{job['task']}__{job['model']}__{job['seed']}"
            folder, log = output / "runs" / name, output / "process_logs" / (name + ".log")
            stream = log.open("w")
            command = [sys.executable, "-m", "experiments.hcsn_risk_ablation_v1.study", "worker",
                "--protocol", str(protocol_path), "--output", str(folder),
                "--task", job["task"], "--model", job["model"], "--seed", str(job["seed"])]
            process = subprocess.Popen(command, cwd=ROOT, env=environment, stdout=stream, stderr=subprocess.STDOUT)
            active[process.pid] = (process, stream, job, folder, log, command, time.perf_counter())
        for pid, item in list(active.items()):
            got, status, usage = os.wait4(pid, os.WNOHANG)
            if not got:
                continue
            process, stream, job, folder, log, command, launched = item
            code = os.waitstatus_to_exitcode(status)
            process.returncode = code
            stream.close()
            folder.mkdir(exist_ok=True)
            record = dict(job=job, command=command, returncode=code, protocol_sha256=digest,
                stdout_sha256=training._sha256(log), child_user_cpu_seconds=usage.ru_utime,
                child_system_cpu_seconds=usage.ru_stime, child_total_cpu_seconds=usage.ru_utime+usage.ru_stime,
                child_peak_rss_kib_linux=usage.ru_maxrss, wall_seconds=time.perf_counter()-launched)
            training._write_json(folder / "EXECUTION.json", record)
            records.append(record)
            del active[pid]
            stopped = stopped or code != 0
            training._write_json(output / "PROGRESS.json", dict(records=records, expected=len(protocol["jobs"])))
            print(json.dumps(dict(completed=len(records), expected=len(protocol["jobs"]), job=job, returncode=code)), flush=True)
        if stopped and not active:
            break
        if active:
            time.sleep(.05)
    verify(protocol_path)
    complete = not stopped and len(records) == len(protocol["jobs"])
    final = dict(status="completed" if complete else "aborted", protocol_sha256=digest,
        records=records, expected=len(protocol["jobs"]), completed=len(records), unstarted=pending,
        failures=sum(row["returncode"] != 0 for row in records),
        complete_child_cpu_seconds=sum(row["child_total_cpu_seconds"] for row in records),
        coordinator_cpu_seconds=time.process_time()-start_cpu, wall_seconds=time.perf_counter()-start_wall)
    training._write_json(output / ("COMPLETE.json" if complete else "ABORTED.json"), final)
    return final


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("register", "worker", "run"))
    parser.add_argument("--protocol", type=Path, default=PACKAGE / "PROTOCOL.json")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--math-audit", type=Path)
    parser.add_argument("--task")
    parser.add_argument("--model", choices=MODEL_NAMES)
    parser.add_argument("--seed", type=int)
    arguments = parser.parse_args()
    if arguments.action == "register":
        register(arguments.protocol, arguments.output, arguments.math_audit)
    elif arguments.action == "worker":
        worker(arguments.protocol, arguments.output,
               dict(task=arguments.task, model=arguments.model, seed=arguments.seed))
    else:
        run(arguments.protocol, arguments.output)
