"""Independent plan/worker census and cost audit without candidate imports.

This reads existing receipts only. It does not launch workers, regenerate data,
select models, import the study supervisor, or infer experimental quality.
"""

import argparse
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path


def read(path):
    return json.loads(Path(path).read_text())


def sha(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        while block := stream.read(1024 * 1024):
            value.update(block)
    return value.hexdigest()


def resolved(path, root):
    value = Path(path)
    return value.resolve() if value.is_absolute() else (root / value).resolve()


def content_binding(argv, root):
    """Reproduce the declared dependency substitution using only saved JSON."""
    template = resolved(argv[argv.index("--template") + 1], root)
    output = resolved(argv[argv.index("--output") + 1], root)
    expected = read(template)
    expected["template_sha256"] = sha(template)
    errors, identity = [], dict(template=str(template), sha256=sha(template))
    dependency = expected.pop("pretrained_from", None)
    if dependency:
        directory = resolved(dependency, root)
        selected, source_job = read(directory / "selection.json"), read(directory / "job.json")
        checkpoint = directory / "selected.pt"
        if selected["selected_checkpoint_sha256"] != sha(checkpoint):
            errors.append("Donor selection/checkpoint digest differs")
        if (source_job["family"] != "shared" or source_job["task"] != expected["task"]
                or source_job["seed"] != expected["seed"]):
            errors.append("Donor is not the predeclared shared task/seed")
        # The worker preserves the template's relative path spelling.
        expected.update(pretrained=str(Path(dependency) / "selected.pt"),
            pretrained_sha256=sha(checkpoint),
            pretrained_selection_sha256=sha(directory / "selection.json"),
            pretrained_job_sha256=sha(directory / "job.json"),
            pretrained_binding_rule="selected.pt hash equals completed dependency selection")
        identity.update(donor=str(directory), donor_checkpoint_sha256=sha(checkpoint),
                        donor_selected_step=selected["selected_step"])
    if read(output / "job.json") != expected:
        errors.append("Executed content configuration is not the mechanical frozen-template resolution")
    return dict(identity=identity, errors=errors, audit_ok=not errors)


def audit(plan_path, meter):
    plan_path, meter = Path(plan_path).resolve(), Path(meter).resolve()
    plan = read(plan_path)
    root, plan_sha = Path(plan["repository_root"]).resolve(), sha(plan_path)
    errors, checks = [], []
    if not (meter / "summary.json").is_file():
        raise ValueError("The supervisor has not completed; do not audit a partial study as final")
    summary, start = read(meter / "summary.json"), read(meter / "start.json")
    if sha(meter / "plan.json") != plan_sha:
        errors.append("Supervisor did not preserve the exact predeclared plan bytes")
    if summary["plan_sha256"] != plan_sha or start["plan_sha256"] != plan_sha:
        errors.append("Supervisor plan digest differs from registration")
    frozen_paths = [entry["path"] for entry in plan["frozen_files"]]
    if len(frozen_paths) != len(set(frozen_paths)):
        errors.append("Duplicate frozen source/input path")
    for entry in plan["frozen_files"]:
        path = resolved(entry["path"], root)
        if not path.is_file() or sha(path) != entry["sha256"]:
            errors.append("Frozen source/input changed: " + entry["path"])
    declared = {entry["id"]: entry for entry in plan["jobs"]}
    if len(declared) != len(plan["jobs"]):
        errors.append("Duplicate planned job identifier")
    receipts, receipt_paths = {}, {}
    for path in sorted((meter / "receipts").glob("*/whole_process.json")):
        record = read(path)
        identifier = record["job_id"]
        if identifier in receipts or identifier != path.parent.name:
            errors.append("Repeated receipt or receipt directory/identifier differs")
        receipts[identifier], receipt_paths[identifier] = record, path
    if set(receipts) != set(declared):
        errors.append("Receipt cohort differs from complete declared job matrix")
    failures, intervals, cost_by_job = [], [], {}
    template_count, output_count = 0, 0
    for identifier, record in receipts.items():
        job = declared.get(identifier)
        local = []
        if record.get("exit_code") != 0:
            failures.append(identifier)
        if job is None:
            continue
        if not record.get("executed"):
            checks.append(dict(job_id=identifier, executed=False,
                               exit_code=record.get("exit_code"), audit_ok=False,
                               errors=["Worker was skipped or failed to launch"]))
            continue
        directory = receipt_paths[identifier].parent
        begun = read(directory / "start.json")
        if (record.get("argv") != job["argv"] or begun.get("argv") != job["argv"]
                or record.get("depends") != job.get("depends", [])
                or Path(record.get("cwd", "")).resolve() != root
                or record.get("plan_sha256") != plan_sha or begun.get("plan_sha256") != plan_sha):
            local.append("Worker command, dependency, working directory or plan differs")
        if record.get("thread_environment") != start["thread_environment"]:
            local.append("Worker thread environment differs from supervisor contract")
        for key in ("wall_sec", "cpu_user_sec", "cpu_system_sec", "cpu_total_sec", "peak_rss_kib"):
            value = record.get(key)
            if not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
                local.append("Invalid complete worker cost: " + key)
        if not math.isclose(record["cpu_user_sec"] + record["cpu_system_sec"],
                record["cpu_total_sec"], rel_tol=1e-12, abs_tol=1e-9):
            local.append("Complete worker CPU is not user plus system time")
        if record.get("missing_outputs") or record.get("frozen_source_error"):
            local.append("Supervisor reports missing evidence or changed frozen source")
        if record.get("exit_code") != 0 or record.get("process_exit_code") != 0:
            local.append("Worker did not complete successfully")
        for stream in ("stdout", "stderr"):
            path = directory / (stream + ".log")
            if not path.is_file() or sha(path) != record.get(stream + "_sha256"):
                local.append("Worker log digest differs: " + stream)
        expected_outputs = job.get("outputs", [])
        recorded_outputs = record.get("outputs", [])
        if [row["path"] for row in recorded_outputs] != expected_outputs:
            local.append("Worker evidence inventory differs from required outputs")
        for row in recorded_outputs:
            path = resolved(row["path"], root)
            if (not path.is_file() or sha(path) != row["sha256"]
                    or path.stat().st_size != row["bytes"]):
                local.append("Worker output bytes/digest differs: " + row["path"])
            output_count += 1
        beginning, ending = datetime.fromisoformat(record["started_utc"]), datetime.fromisoformat(record["ended_utc"])
        if ending < beginning or abs((ending - beginning).total_seconds() - record["wall_sec"]) > .5:
            local.append("Worker wall-time chronology differs from its receipt")
        if beginning < datetime.fromisoformat(plan.get("frozen_at_utc", start["started_utc"])):
            local.append("Worker began before the declared plan freeze")
        for dependency in job.get("depends", []):
            donor = receipts.get(dependency, {})
            if (donor.get("exit_code") != 0 or "ended_utc" not in donor
                    or datetime.fromisoformat(donor["ended_utc"]) > beginning):
                local.append("Worker began before a successful declared dependency finished")
        intervals.extend([(beginning, 1), (ending, -1)])
        cost_by_job[identifier] = {key: record[key] for key in
                                  ("cpu_total_sec", "wall_sec", "peak_rss_kib")}
        binding = None
        if "--template" in job["argv"] and record.get("exit_code") == 0:
            binding = content_binding(job["argv"], root)
            local.extend(binding["errors"])
            template_count += 1
        checks.append(dict(job_id=identifier, executed=True, errors=local, audit_ok=not local,
                           receipt_sha256=sha(receipt_paths[identifier]), template_binding=binding))
    if sorted(summary["failures"]) != sorted(failures) or summary["jobs"] != len(receipts):
        errors.append("Supervisor cohort/failures summary differs from individual receipts")
    # Include measured failed attempts too. Skipped jobs have no child CPU.
    total_cpu = sum(row.get("cpu_total_sec", 0) for row in receipts.values())
    maximum_rss = max((row.get("peak_rss_kib", 0) for row in receipts.values()), default=0)
    if not math.isclose(total_cpu, summary["child_cpu_sec"], rel_tol=1e-12, abs_tol=1e-8):
        errors.append("Supervisor total omits or double counts complete worker CPU")
    if maximum_rss != summary["max_worker_rss_kib"]:
        errors.append("Supervisor maximum single-worker RSS differs from receipts")
    active, peak = 0, 0
    for _, delta in sorted(intervals, key=lambda pair: (pair[0], pair[1])):
        active += delta
        peak = max(peak, active)
    if active != 0 or peak > start["max_parallel_workers"]:
        errors.append("Worker timeline violates the declared concurrency bound")
    if intervals:
        span = (max(t for t, _ in intervals) - min(t for t, _ in intervals)).total_seconds()
        if span > summary["wall_sec"] + .5:
            errors.append("Supervisor makespan is shorter than its worker timeline")
    return dict(schema="hcsn-independent-study-audit.v1", plan=str(plan_path),
        plan_sha256=plan_sha, meter=str(meter), errors=errors,
        audit_ok=not errors and not failures and all(row["audit_ok"] for row in checks),
        planned_jobs=len(declared), observed_receipts=len(receipts), failures=failures,
        frozen_files_checked=len(frozen_paths), required_outputs_checked=output_count,
        content_templates_reconstructed=template_count, observed_peak_workers=peak,
        complete_worker_cpu_seconds=total_cpu, max_single_worker_rss_kib=maximum_rss,
        study_makespan_seconds=summary["wall_sec"], supervisor_cpu_seconds=summary["supervisor_cpu_sec"],
        cost_by_job=cost_by_job, checks=checks,
        scope="Complete interpreter receipts including failed measured attempts; no energy, raw decoding or quality inference")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--meter", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    value = audit(args.plan, args.meter)
    value["audit_source_sha256"] = sha(__file__)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as stream:
        json.dump(value, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps({key: value[key] for key in
        ("audit_ok", "planned_jobs", "observed_receipts", "failures", "complete_worker_cpu_seconds")}))


if __name__ == "__main__":
    main()
