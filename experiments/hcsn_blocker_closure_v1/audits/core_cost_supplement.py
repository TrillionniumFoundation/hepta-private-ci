"""Read exact-run cost receipts without opening scientific quality outcomes."""

import argparse
import datetime
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import time
import traceback


RUN = 41156755829
SEAL = "c9063043d088b6b469e740b9b6f341f3faea3928"
PREFIX = "experiments/hcsn_blocker_closure_v1"
PUBLICATION_SHA = "83856bb2ba45fe799a539769ea64b236bd151cf1d9b1a1fe0639419b7ec17bc6"
EXPECTED_CHILDREN = {
    "prepare": ["finite_qvi", "torch_bridge", "content_preflight", "registration"],
    "train": ["development", "selection_lock", "fixed", "equal_cpu"],
    "finalize": ["content_analysis", "native_restore", "native_task"],
}
WORKERS = {"development": 76, "fixed": 304, "equal_cpu": 64}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def seconds(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        raise ValueError("A nonnegative finite measured duration is required")
    return value


def close(actual, expected):
    if not math.isclose(actual, expected, rel_tol=1e-12, abs_tol=1e-8):
        raise ValueError(f"Cost identity differs: {actual} versus {expected}")


def safe_name(name):
    path = PurePosixPath(name)
    if path.is_absolute() or not path.parts or ".." in path.parts or "\\" in name or path.as_posix() != name:
        raise ValueError("Unexpected evidence member path")
    return path


def timestamp(value):
    return datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-receipt", type=Path, required=True)
    parser.add_argument("--jobs-receipt", type=Path, required=True)
    parser.add_argument("--publication", type=Path, required=True)
    parser.add_argument("--restored", type=Path, required=True)
    parser.add_argument("--require-full-run", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError("Preserve every cost accounting attempt")
    started = time.process_time()
    inputs, checks, result = {}, [], {}

    def read(path, expected=None):
        path = Path(path)
        if path.is_symlink() or path.stat().st_size > 2000000:
            raise ValueError("Expected bounded regular cost metadata")
        digest = sha(path)
        if expected is not None and digest != expected:
            raise ValueError("Pinned cost evidence hash changed: " + str(path))
        inputs[str(path.resolve())] = dict(sha256=digest, bytes=path.stat().st_size)
        return json.loads(path.read_bytes())

    try:
        run, jobs_api = read(args.run_receipt), read(args.jobs_receipt)
        if (run["id"] != RUN or run["head_sha"] != SEAL
                or run["repository"]["full_name"] != "TrillionniumFoundation/hepta-private-ci"):
            raise ValueError("Wrong public run identity")
        jobs = jobs_api["jobs"]
        if len(jobs) != jobs_api["total_count"] or {j["id"] for j in jobs} != {124405134658, 124428879276}:
            raise ValueError("Incomplete or unexpected exact-run job inventory")
        experiment = next(j for j in jobs if j["id"] == 124405134658)
        if experiment["status"] != "completed" or experiment["conclusion"] != "success":
            raise PermissionError("The experimental job must complete before this cost-only read")
        full_run = run["status"] == "completed" and all(j["status"] == "completed" for j in jobs)
        if args.require_full_run and not full_run:
            raise PermissionError("Full run completion requested but publisher is not complete")
        checks.append("Exact public run and completed experimental job")

        publication = read(args.publication, PUBLICATION_SHA)
        if publication["execution_seal"] != SEAL or str(publication["github_run_id"]) != str(RUN):
            raise ValueError("Packaging receipt belongs to another execution")
        published = {row["path"]: row for row in publication["files"]}
        if len(published) != len(publication["files"]):
            raise ValueError("Duplicate publication member")
        publication_root = args.publication.parents[4]

        def public_file(name):
            safe_name(name)
            row = published[name]
            path = publication_root / name
            if path.stat().st_size != row["bytes"]:
                raise ValueError("Published metadata size changed")
            return read(path, row["sha256"])

        index = public_file(PREFIX + "/artifacts/closure001/INDEX.json")
        if index["schema"] != "hcsn-bounded-member-index.v1":
            raise ValueError("Unexpected member index schema")
        rows = []
        for row in index["member_shards"]:
            name = PREFIX + "/artifacts/closure001/" + row["path"]
            if published[name]["sha256"] != row["sha256"] or published[name]["bytes"] != row["bytes"]:
                raise ValueError("Index and publication disagree about a member shard")
            shard = public_file(name)
            if len(shard) != row["members"]:
                raise ValueError("Member shard count differs")
            rows.extend(shard)
        if len(rows) != index["original_member_count"]:
            raise ValueError("Incomplete original member inventory")
        manifest = {key: value for key, value in index.items()
                    if key not in ("member_shards", "original_manifest_sha256", "original_member_count")}
        manifest.update(schema="hcsn-evidence-bundle.v1", members=rows)
        encoded = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode()
        if hashlib.sha256(encoded).hexdigest() != index["original_manifest_sha256"]:
            raise ValueError("Canonical member manifest changed")
        members = {row["path"]: row for row in rows}
        if len(members) != len(rows):
            raise ValueError("Duplicate raw evidence member")
        for name in members:
            safe_name(name)
        checks.append("Externally pinned publication, all member shards and canonical manifest")

        def restored(name):
            safe_name(name)
            row = members[name]
            path = args.restored / name
            if path.stat().st_size != row["bytes"]:
                raise ValueError("Restored cost receipt size changed")
            return read(path, row["sha256"])

        identity = restored("results/hosted001/EXECUTION_IDENTITY.json")
        if identity["seal"] != SEAL or str(identity["run_id"]) != str(RUN) or identity["concurrent_workers"] != 4:
            raise ValueError("Cost receipts and execution identity differ")
        stages, children = [], {}
        for stage, names in EXPECTED_CHILDREN.items():
            prefix = "results/hosted001/" + stage + "/"
            report = restored(prefix + "RUNNER_" + stage.upper() + "_RESULT.json")
            if (report["mode"] != stage or not report["all_child_costs_known"]
                    or [row["name"] for row in report["subprocesses"]] != names):
                raise ValueError("Incomplete or reordered stage cost inventory")
            child_total = 0.
            for child in report["subprocesses"]:
                if restored(prefix + child["name"] + "_EXECUTION.json") != child:
                    raise ValueError("Child receipt and aggregate stage disagree")
                value = seconds(child["complete_child_cpu_seconds"])
                close(value, seconds(child["user_cpu_seconds"]) + seconds(child["system_cpu_seconds"]))
                child_total += value
                children[child["name"]] = child
            close(child_total, report["direct_child_cpu_seconds"])
            self_cpu = seconds(report["coordinator_self_cpu_seconds"])
            stages.append(dict(stage=stage, child_count=len(names), direct_children_cpu_seconds=child_total,
                coordinator_body_cpu_seconds=self_cpu, nonoverlap_cpu_seconds=child_total + self_cpu,
                stage_wall_seconds=seconds(report["stage_wall_seconds"])))
        checks.append("Every outer wait4 receipt, user/system identity and disjoint stage sum")

        nested = []
        for stage, count in WORKERS.items():
            ledger = public_file(PREFIX + "/content/results/hosted001/RUN_" + stage + ".json")
            jobs = ledger["jobs"]
            if (ledger["stage"] != stage or ledger["complete"] is not True or len(jobs) != count
                    or len({row["id"] for row in jobs}) != count
                    or any(row["job"]["stage"] != stage for row in jobs)):
                raise ValueError("Complete worker cost inventory required")
            cpu = sum(seconds(row["child_cpu_seconds"]) for row in jobs)
            close(cpu, ledger["child_cpu_seconds"])
            if cpu > children[stage]["complete_child_cpu_seconds"] + 1e-8:
                raise ValueError("Nested worker CPU exceeds enclosing process CPU")
            nested.append(dict(stage=stage, workers=count, failed_workers=sum(row["exit_code"] != 0 for row in jobs),
                worker_cpu_seconds=cpu, summed_worker_wall_seconds=sum(seconds(row["wall_seconds"]) for row in jobs),
                concurrent_stage_wall_seconds=seconds(ledger["wall_seconds"]),
                maximum_individual_worker_rss_bytes=max(row["maxrss_bytes"] for row in jobs),
                enclosing_child_cpu_seconds=children[stage]["complete_child_cpu_seconds"],
                includes_python_imports_serialization_exit=True, added_to_outer_total_again=False))
        native = restored("runtime/results/hosted001/WHOLE_WORKER_COST.json")
        native_total = seconds(native["worker_and_reaped_descendant_cpu_seconds"]) + seconds(native["launcher_cpu_seconds_from_before_spawn"])
        if native_total > children["native_task"]["complete_child_cpu_seconds"] + 1e-8:
            raise ValueError("Nested native worker CPU exceeds enclosing child")
        checks.append("444 nested worker costs and native replay costs remain nested")

        wall_rows = []
        for job in jobs_api["jobs"]:
            duration = None
            if job["status"] == "completed":
                duration = seconds((timestamp(job["completed_at"]) - timestamp(job["started_at"])).total_seconds())
            wall_rows.append(dict(id=job["id"], name=job["name"], status=job["status"], conclusion=job["conclusion"],
                started_at=job["started_at"], completed_at=job["completed_at"], occupied_runner_seconds=duration))
        outer_cpu = sum(row["nonoverlap_cpu_seconds"] for row in stages)
        package_cpu = seconds(publication["packaging_cpu_seconds"])
        result = dict(passed=True, full_run_completed=full_run, execution_seal=SEAL, run_id=RUN,
            outer_stages=stages, outer_driver_cpu_lower_bound=outer_cpu,
            packaging_cpu_seconds=package_cpu, packaging_wall_seconds=publication["packaging_wall_seconds"],
            measured_nonoverlap_cpu_lower_bound=outer_cpu + package_cpu,
            nested_worker_cpu_seconds=sum(row["worker_cpu_seconds"] for row in nested), nested_worker_stages=nested,
            nested_native_worker_cpu_seconds=native["worker_and_reaped_descendant_cpu_seconds"],
            nested_native_launcher_cpu_seconds=native["launcher_cpu_seconds_from_before_spawn"],
            nested_costs_added_again=False, platform_jobs=wall_rows,
            completed_jobs_occupied_wall_lower_bound=sum(row["occupied_runner_seconds"] or 0 for row in wall_rows),
            complete_training_publication_job_wall_seconds=(sum(row["occupied_runner_seconds"] for row in wall_rows) if full_run else None),
            complete_platform_cpu_seconds=None, complete_platform_energy_joules=None,
            quality_outcomes_opened=False, scientific_gate_changed=False,
            expected_evidence_branch="research/hcsn-blocker-evidence-41156755829",
            expected_publication_prefix=PREFIX, expected_archive_prefix=PREFIX + "/artifacts/closure001",
            archive_members_are_relative_to=PREFIX,
            unmetered_cpu=["Checkout, container setup and pinned dependency installation", "Launcher imports before RunBook construction and final serialization after sampling", "The prepare-stage git identity subprocess, outside explicit RunBook child receipts", "Artifact upload/download and publisher verification/git push", "Provider and operating-system overhead outside retained process receipts"],
            scope="Cost-only accounting. Outer stages include registration/data generation, oracle checks, preflight, all training workers, lock, analysis, native restore and analytic native replay. Packaging is a separate workflow step and added once. Training optimizer/inference/body CPU and worker costs are nested. No held-out quality files or scientific decisions are read.",
            runtime_limitations="Native replay is an analytic task policy engineering replication, not a learned content neural kernel. Peak individual worker RSS is not aggregate concurrent memory; summed worker wall is not elapsed job wall. CPU is not Joules. Container quota is4CPU/8GiB, not proof of dedicated physical cores.")
    except Exception as error:
        result = dict(passed=False, error=repr(error), traceback=traceback.format_exc(), quality_outcomes_opened=False)
    result.update(schema="hcsn-core-independent-cost-supplement.v1", source_sha256=sha(__file__),
        recorded_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(), input_files=inputs, checks=checks,
        audit_body_cpu_seconds=time.process_time() - started)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as stream:
        json.dump(result, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
    print(json.dumps({key: result.get(key) for key in ("passed", "full_run_completed", "measured_nonoverlap_cpu_lower_bound", "error")}))
    if not result["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
