"""Read-only coverage and provenance audit for the six-stage HCSN study.

This audit does not train models, select new candidates, read heldout tensors,
or replace the registered content analyzer. It checks the scientific scope of
available evidence and independently reconciles the execution ledger.
"""

import argparse
import datetime
import hashlib
import json
import math
from pathlib import Path
import subprocess
import time


ROOT = Path(__file__).resolve().parents[2]
PACKAGE = Path(__file__).resolve().parent


def digest(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def read_json(path):
    return json.loads(Path(path).read_bytes())


def job_key(job):
    return job["task"], job["model"], job["seed"]


def bound_file(relative, expected=None):
    path = ROOT / relative
    result = {"path": str(relative), "available": path.is_file()}
    if path.is_file():
        result.update(bytes=path.stat().st_size, sha256=digest(path))
    if expected is not None:
        result.update(expected_sha256=expected,
                      matches=result.get("sha256") == expected)
    return result


def audit(protocol_path, study, output):
    started = time.process_time()
    protocol_path, study, output = (Path(path).resolve()
                                   for path in (protocol_path, study, output))
    if output.exists():
        raise FileExistsError("Use a new audit output; prior evidence is immutable")
    protocol = read_json(protocol_path)
    protocol_hash = digest(protocol_path)
    failures = []

    def check(condition, message):
        if not condition:
            failures.append(message)

    keys = [job_key(job) for job in protocol["jobs"]]
    core = protocol["core"]
    mechanism = protocol["mechanism"]
    reconstructed = {
        (task, model, seed)
        for task in core["tasks"]
        for model in core["models"]
        for seed in core["seeds"]
    } | {
        (task, model, seed)
        for task in mechanism["tasks"]
        for model in mechanism["models"]
        for seed in mechanism["seeds"]
    }
    check(len(keys) == len(set(keys)), "Duplicate registered search")
    check(set(keys) == reconstructed, "Registered matrix differs from panel union")
    optimization = protocol["optimization"]
    expected_candidates = len(keys) * len(optimization["learning_rates"])
    nominal_cpu = expected_candidates * optimization["training_cpu_seconds_per_lr"]
    check(protocol["execution"]["expected_searches"] == len(keys), "Search count")
    check(protocol["execution"]["expected_lr_candidates"] == expected_candidates,
          "Learning-rate candidate count")
    check(protocol["execution"]["nominal_training_cpu_seconds"] == nominal_cpu,
          "Nominal training CPU calculation")

    sources = [bound_file(path, expected)
               for path, expected in protocol["source_files_sha256"].items()]
    data = [bound_file(row["path"], row["sha256"])
            for row in protocol["data"].values()]
    for row in sources + data:
        check(row["matches"], "Frozen identity: " + row["path"])
    snapshot = []
    for path in sorted((PACKAGE / "results/content002/source").glob("*")):
        if not path.is_file():
            continue
        original = PACKAGE / path.name
        same = original.is_file() and digest(path) == digest(original)
        snapshot.append(dict(file=path.name, sha256=digest(path), matches=same))
        check(same, "Registration snapshot: " + path.name)
    for key in ("domain_preflight", "prior_aborted_study"):
        record = protocol[key]
        relative = record.get("path", record.get("receipt"))
        expected = record.get("sha256", record.get("receipt_sha256"))
        check(bound_file(relative, expected)["matches"], key + " receipt binding")

    registration = study / "REGISTRATION.json"
    check(registration.is_file(), "Execution registration is missing")
    if registration.is_file():
        check(read_json(registration)["protocol_sha256"] == protocol_hash,
              "Execution registration hash")
    expected_names = {"__".join(map(str, key)) for key in keys}
    runs = study / "runs"
    present_names = {path.name for path in runs.iterdir() if path.is_dir()} if runs.exists() else set()
    check(not (present_names - expected_names), "Unregistered run directories")
    executions, finalized = [], []
    for key in keys:
        name = "__".join(map(str, key))
        directory = runs / name
        execution_file = directory / "EXECUTION.json"
        if not execution_file.is_file():
            continue
        execution = read_json(execution_file)
        executions.append(execution)
        check(job_key(execution["job"]) == key, "Execution job: " + name)
        check(execution["protocol_sha256"] == protocol_hash, "Execution protocol: " + name)
        components = [execution[k] for k in ("child_user_cpu_seconds", "child_system_cpu_seconds")]
        check(all(math.isfinite(v) and v >= 0 for v in components), "CPU components: " + name)
        check(abs(sum(components)-execution["child_total_cpu_seconds"]) <= 1e-9,
              "CPU sum: " + name)
        log = study / "process_logs" / (name + ".log")
        check(log.is_file() and digest(log) == execution["stdout_sha256"],
              "Worker log binding: " + name)
        if execution["returncode"] != 0:
            continue
        summary_file = directory / "summary.json"
        identity_file = directory / "IDENTITY.json"
        check(summary_file.is_file() and identity_file.is_file(), "Successful worker files: " + name)
        if not summary_file.is_file() or not identity_file.is_file():
            continue
        summary, identity = read_json(summary_file), read_json(identity_file)
        check(identity["protocol_sha256"] == protocol_hash, "Worker identity protocol: " + name)
        check(identity["source_files_sha256"] == protocol["source_files_sha256"],
              "Worker source map: " + name)
        candidates = summary["candidates"]
        check([candidate["learning_rate"] for candidate in candidates] == optimization["learning_rates"],
              "Learning-rate coverage: " + name)
        check(all(candidate["stopping_reason"] == "cpu_budget" and
                  candidate["training_cpu_seconds"] >= optimization["training_cpu_seconds_per_lr"]
                  for candidate in candidates), "Training budget: " + name)
        selection = read_json(directory / "selection.json")
        check(summary["selection"] == selection, "Selection receipt: " + name)
        winner = min(candidates, key=lambda candidate:
                     (candidate["best"]["validation"]["cross_entropy"], candidate["learning_rate"]))
        check(selection["selected_checkpoint_sha256"] == winner["best"]["sha256"],
              "Validation-only winner: " + name)
        check(digest(directory / "selected.npz") == selection["selected_checkpoint_sha256"],
              "Selected checkpoint: " + name)
        access = summary["access_log"]
        locks = [i for i, row in enumerate(access) if row["event"] == "selection_locked"]
        check(len(locks) == 1, "Selection lock count: " + name)
        if len(locks) == 1:
            check(access[locks[0]]["completed_lr_candidates"] == len(candidates),
                  "Candidates completed before lock: " + name)
            check(all(i > locks[0] for i, row in enumerate(access)
                      if row.get("split") in ("test", "ood")), "Heldout access order: " + name)
        finalized.append(name)

    complete = study / "COMPLETE.json"
    aborted = study / "ABORTED.json"
    if complete.is_file():
        end = read_json(complete)
        ledger = {job_key(row["job"]): row for row in end["records"]}
        check(end["status"] == "completed" and end["failures"] == 0, "Completion status")
        check(len(end["records"]) == len(keys) and set(ledger) == set(keys), "Completion coverage")
        check(len(finalized) == len(keys), "Successful search coverage")
        check(end["protocol_sha256"] == protocol_hash, "Completion protocol")
        check(all(ledger.get(job_key(row["job"])) == row for row in executions),
              "Completion/per-worker ledger agreement")
        check(abs(sum(row["child_total_cpu_seconds"] for row in executions)
                  - end["complete_child_cpu_seconds"]) <= 1e-7, "Complete worker CPU sum")
        state = "completed"
    elif aborted.is_file():
        state = "aborted"
    elif present_names:
        state = "started_without_completion_receipt"
    else:
        state = "registered_without_published_execution"

    scope_files = [
        "experiments/hcsn_free_boundary_v1/CONTRACT.md",
        "experiments/hcsn_free_boundary_v1/RESULTS.md",
        "experiments/hcsn_free_boundary_v1/SCALING.md",
        "experiments/hcsn_distributional_v2/CONTENT.md",
        "experiments/hcsn_distributional_v2/MATH.md",
        "experiments/hcsn_distributional_v2/results/kernel_validation003/RESULTS.json",
        "experiments/hcsn_distributional_v2/results/policy_gap001/RESULTS.json",
        "experiments/hcsn_distributional_v2/results/content001/ABORTED.json",
    ]
    stages = [
        dict(stage=1, evidence="Scalar v1 oracle and v2 finite-volume generator numerical audits",
             remaining="Finite spatial grid/lower wall/Erlang law remain modeling approximations; whole-network or task optimality is not certified"),
        dict(stage=2, evidence="v1 fixed/direct/free comparison; v2 free versus input-conditioned threshold in content002",
             remaining="v2 analytic boundary optimizes the Brownian/Erlang surrogate, not the finite grid or task return; superiority requires complete registered analysis"),
        dict(stage=3, evidence="v1 margin/J/J+G/ordinary features; v2 J/G versus same-information ordinary features",
             remaining="G is intervention value, not default probability; content002 does not contain a full margin/continuation/default-risk channel ladder"),
        dict(stage=4, evidence="v2 retained active and refractory distributions; active-mean-collapse and v1 legacy controls",
             remaining="Finite marginal distributions do not retain all high-dimensional correlations; no-reset/entire reset-law ablation is not in content002"),
        dict(stage=5, evidence="Copy, MQAR, irregular sampling, MNIST, FSDD and queried digit image/audio selection",
             remaining="No natural paired audiovisual retrieval/video-recognition dataset or objective is registered here; previously observed data limit confirmation claims"),
        dict(stage=6, evidence="Full worker CPU ledger; prior v1 synthetic timing/scaling and native-owner cost studies",
             remaining="v2 trained-checkpoint quality-matched timing remains separate; GPU memory, hardware joules and foundation-scale training have not been measured"),
    ]
    result = dict(schema="hcsn-sixstage-evidence-audit.v1",
        created_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        source_commit=subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        auditor_sha256=digest(__file__), protocol_sha256=protocol_hash,
        parent_commit=protocol["parent_commit"],
        study=str(study.relative_to(ROOT)) if study.is_relative_to(ROOT) else str(study),
        execution_state=state, expected_searches=len(keys), expected_lr_candidates=expected_candidates,
        nominal_training_cpu_seconds=nominal_cpu, source_files=sources, data_files=data,
        registration_snapshot=snapshot, scope_files=[bound_file(path) for path in scope_files],
        observed_run_directories=len(present_names), observed_execution_receipts=len(executions),
        successful_searches=len(finalized), failed_worker_receipts=sum(row["returncode"] != 0 for row in executions),
        observed_worker_cpu_seconds=sum(row["child_total_cpu_seconds"] for row in executions),
        prior_aborted_worker_cpu_seconds=protocol["prior_aborted_study"]["cost"]["complete_worker_cpu_seconds"],
        failures=failures, integrity_passed=not failures,
        stages=stages, all_six_scientific_stages_closed=False,
        interpretation="Integrity checks do not establish quality, causal mechanism superiority, energy efficiency or general task optimality. No heldout tensor values were read by this audit.",
        audit_body_cpu_seconds=time.process_time()-started)
    output.mkdir(parents=True, exist_ok=False)
    (output / "AUDIT.json").write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False)+"\n")
    lines = ["# HCSN six-stage evidence audit", "",
             f"Source commit: `{result['source_commit']}`. Protocol: `{protocol_hash}`.", "",
             f"Execution state: **{state}**; successful searches **{len(finalized)}/{len(keys)}**; "
             f"integrity findings **{len(failures)}**.", "",
             f"The frozen matrix contains {expected_candidates} learning-rate candidates and "
             f"{nominal_cpu:g} nominal training CPU seconds. Observed complete-worker CPU is "
             f"{result['observed_worker_cpu_seconds']:.6f} seconds. Training time is nested within worker cost.", "",
             "| Stage | Available evidence | Remaining scope |", "|---|---|---|"]
    lines += [f"| {row['stage']} | {row['evidence']} | {row['remaining']} |" for row in stages]
    lines += ["", "## Integrity findings", ""]
    lines += ["- " + message for message in failures] if failures else ["All checked identities and available ledger records agree."]
    lines += ["", "The registered content analyzer remains required after a complete matrix. "
              "This audit does not recompute prediction metrics or certify scientific superiority. "
              "Old source and result files are read only; a new output directory is required for every audit."]
    (output / "REPORT.md").write_text("\n".join(lines)+"\n")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, default=PACKAGE / "CONTENT002_PROTOCOL.json")
    parser.add_argument("--study", type=Path, default=PACKAGE / "results/content002")
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    result = audit(arguments.protocol, arguments.study, arguments.output)
    print(json.dumps({key: result[key] for key in
                     ("execution_state", "expected_searches", "successful_searches", "integrity_passed", "failures")}))
