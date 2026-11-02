"""Preserve the closed first cross attempt without changing any evidence bytes.

The coordinator first reviews ``plan`` and then supplies its SHA256 to
``preserve``. Only the two closed groups/receipts directories are renamed.
This helper never imports scientific modules or starts a retry.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import stat
import tempfile


SOURCE = Path(__file__).resolve()
REPO = SOURCE.parents[3]
STUDY = Path("experiments/hcsn_distribution_content_r15_20261101")
ATTEMPT = "train_execution_cross_01_serialization"
SCHEMA = "hcsn.r15.cross-serialization-failure-preservation.v1"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def encoded(value):
    return (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()


def signature(info):
    return info.st_dev, info.st_ino, info.st_mode, info.st_size, info.st_mtime_ns, info.st_ctime_ns


def raw(path):
    path = Path(path)
    before = path.lstat()
    require(stat.S_ISREG(before.st_mode), "Not a regular file: " + str(path))
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW), "rb") as stream:
        require(signature(os.fstat(stream.fileno())) == signature(before), "Source changed before read")
        value = stream.read()
        require(signature(os.fstat(stream.fileno())) == signature(before), "Source changed during read")
    require(signature(path.lstat()) == signature(before), "Source changed after read")
    return value


def relative(value):
    path = PurePosixPath(value)
    require(isinstance(value, str) and value and not path.is_absolute()
            and path.as_posix() == value and all(part not in (".", "..") for part in path.parts)
            and "\\" not in value, "Unsafe relative path")
    return value


def descriptor(root, path, scope):
    relative(path)
    current = root
    for part in PurePosixPath(path).parts:
        current = current / part
        require(not current.is_symlink(), "Source symlink refused")
    value = raw(current)
    return dict(scope=scope, path=path, bytes=len(value), sha256=hashlib.sha256(value).hexdigest())


def inventory(directory):
    require(directory.is_dir() and not directory.is_symlink(), "Missing/non-directory source")
    files, directories = {}, set()
    for parent, names, filenames in os.walk(directory, followlinks=False):
        for name in names:
            path = Path(parent) / name
            require(stat.S_ISDIR(path.lstat().st_mode), "Special directory entry refused")
            directories.add(path.relative_to(directory).as_posix())
        for name in filenames:
            path = Path(parent) / name
            value = raw(path)
            files[path.relative_to(directory).as_posix()] = (len(value), hashlib.sha256(value).hexdigest())
    return files, directories


def make_plan(output, repo=REPO):
    output, repo = Path(output).resolve(), Path(repo).resolve()
    require(output == repo / STUDY / "results/formal_03", "Only formal_03 is supported")
    prefix = "attempts/" + ATTEMPT
    require(not os.path.lexists(output / prefix), "Preservation attempt already exists")
    protocol = json.loads(raw(output / "PROTOCOL.json"))
    cross = json.loads(raw(output / "train_execution_cross/SELF_REGISTRATION.json"))
    online = json.loads(raw(output / "full_online_confirmation/SELF_REGISTRATION.json"))
    freeze = json.loads(raw(output / "SOURCE_FREEZE.json"))
    require(set(protocol["tasks"]) == {"recall", "binding"}
            and protocol["seeds"] == list(range(15131, 15139)), "Unexpected task/seed matrix")
    names = sorted(f"{task}_s{seed}_light" for task in protocol["tasks"] for seed in protocol["seeds"])
    registration_paths = ["SOURCE_FREEZE.json", "PROTOCOL.json", "train_execution_cross/SELF_REGISTRATION.json",
                          "train_execution_cross/" + relative(cross["source_snapshot"]),
                          "full_online_confirmation/SELF_REGISTRATION.json",
                          "full_online_confirmation/" + relative(online["source_snapshot"])]
    registration = [descriptor(output, path, "run") for path in registration_paths]
    registration_hashes = {row["path"]: row["sha256"] for row in registration}
    require(registration_hashes["SOURCE_FREEZE.json"] == cross["parent_source_freeze_sha256"]
            and registration_hashes["PROTOCOL.json"] == cross["parent_protocol_sha256"]
            and registration_hashes["full_online_confirmation/SELF_REGISTRATION.json"] == cross["parent_online_registration_sha256"]
            and registration_hashes[registration_paths[3]] == cross["source_sha256"]
            and registration_hashes[registration_paths[5]] == online["source_sha256"]
            and online["source_sha256"] == cross["inherited_actual_executor_sha256"], "Registration chain differs")
    expected_sources = dict(freeze["files"])
    expected_sources[str(STUDY / "train_execution_cross.py")] = cross["source_sha256"]
    expected_sources[str(STUDY / "online_confirm.py")] = online["source_sha256"]
    scientific = [descriptor(repo, relative(path), "repository") for path in sorted(expected_sources)]
    require(all(row["sha256"] == expected_sources[row["path"]] for row in scientific), "Scientific source changed")
    groups, group_dirs = inventory(output / "train_execution_cross/groups")
    receipts, receipt_dirs = inventory(output / "receipts/train_execution_cross")
    group_files = {f"{name}/ordinary_distribution_iid_LV.{extension}" for name in names for extension in ("json", "npz")}
    receipt_files = {f"{name}.{suffix}" for name in names for suffix in ("json", "stdout.log", "stderr.log")} | {"TOTAL.json"}
    require(set(groups) == group_files and group_dirs == set(names), "Unexpected failed group inventory")
    require(set(receipts) == receipt_files and not receipt_dirs, "Unexpected failed receipt inventory")
    files = []
    for original, preserved, entries in (("train_execution_cross/groups", prefix + "/groups", groups),
                                          ("receipts/train_execution_cross", prefix + "/receipts", receipts)):
        files.extend(dict(original_path=original + "/" + path, archive_path=preserved + "/" + path,
                          bytes=size, sha256=digest) for path, (size, digest) in sorted(entries.items()))
    processes, stderr_hashes = [], set()
    for name in names:
        receipt_original = "receipts/train_execution_cross/" + name + ".json"
        worker = json.loads(raw(output / receipt_original))
        task, seed = name.split("_s"); seed = int(seed.removesuffix("_light"))
        require((worker["name"], worker["task"], worker["seed"], worker["train_mode"], worker["exit_code"])
                == (name, task, seed, "light", 1), "Unexpected failed process identity")
        for key in ("cpu_user_seconds", "cpu_system_seconds"):
            require(type(worker[key]) in (int, float) and math.isfinite(worker[key]) and worker[key] >= 0, "Invalid CPU receipt")
        error = raw(output / "receipts/train_execution_cross" / (name + ".stderr.log"))
        require(error.decode().splitlines()[-1] == "TypeError: Object of type float32 is not JSON serializable", "Different failure root cause")
        stderr_hashes.add(hashlib.sha256(error).hexdigest())
        malformed = raw(output / "train_execution_cross/groups" / name / "ordinary_distribution_iid_LV.json")
        try:
            json.loads(malformed)
        except json.JSONDecodeError:
            pass
        else:
            raise ValueError("Expected the original incomplete JSON")
        processes.append(dict(process_attempt_id=ATTEMPT + "/" + name, name=name, task=task, seed=seed,
            train_mode="light", exit_code=worker["exit_code"], command=worker["command"],
            receipt_original_path=receipt_original, receipt_archive_path=prefix + "/receipts/" + name + ".json",
            receipt_sha256=receipts[name + ".json"][1], cpu_user_seconds=worker["cpu_user_seconds"],
            cpu_system_seconds=worker["cpu_system_seconds"], cpu_seconds=worker["cpu_user_seconds"] + worker["cpu_system_seconds"],
            measurement_status="complete_process_lifetime_wait4"))
    require(len(stderr_hashes) == 1, "Failed stderr files differ")
    total = json.loads(raw(output / "receipts/train_execution_cross/TOTAL.json"))
    require((total["stage"], total["jobs"], total["failed"]) == ("train_execution_cross", 16, 16), "Unexpected launcher total")
    require(math.isclose(math.fsum(row["cpu_seconds"] for row in processes), total["process_cpu_seconds"], rel_tol=1e-12, abs_tol=1e-10), "CPU total differs")
    guard_dir = output / "operational_addendum_guarded_01"
    require((guard_dir / "FAILURE.json").is_file() and not (guard_dir / "COMPLETE.json").exists(), "Original failed guard is not closed")
    guard_files, _ = inventory(guard_dir)
    evidence = [descriptor(output, "operational_addendum_guarded_01/" + path, "run") for path in sorted(guard_files)]
    return dict(schema=SCHEMA, attempt_id=ATTEMPT, stage="train_execution_cross", complete=False,
        output=str(output), files=files, process_attempts=processes,
        launcher_total=dict(original_path="receipts/train_execution_cross/TOTAL.json", archive_path=prefix + "/receipts/TOTAL.json",
            bytes=receipts["TOTAL.json"][0], sha256=receipts["TOTAL.json"][1], jobs=16, failed=16,
            process_cpu_seconds=total["process_cpu_seconds"], counted_separately=False),
        source_fix=descriptor(repo, str(STUDY / "publication/cross_serialization_adapter.py"), "repository"),
        preservation_helper=descriptor(repo, str(STUDY / "publication/preserve_cross_serialization_failure.py"), "repository"),
        scientific_sources=scientific, registration_files=registration, operational_evidence=evidence,
        file_counts=dict(all=81, group_artifacts=32, npz=16, incomplete_json=16, worker_receipts=16, stdout=16, stderr=16, total=1),
        file_bytes=sum(row["bytes"] for row in files), unchanged_registration_location=True,
        npz_arrays_loaded=False, scientific_functions_executed=False, retry_started=False,
        note="Preserve all failed bytes and original command identities. Failed worker CPU is additional; launcher totals are only cross-checks.")


def atomic_json(path, value):
    fd, temporary = tempfile.mkstemp(prefix="pending_", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(encoded(value)); stream.flush(); os.fsync(stream.fileno())
        os.link(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def preserve(output, expected_plan_sha256, repo=REPO):
    output, repo = Path(output).resolve(), Path(repo).resolve()
    plan = make_plan(output, repo)
    plan_sha = hashlib.sha256(encoded(plan)).hexdigest()
    require(plan_sha == expected_plan_sha256, "Current plan differs from the reviewed pin")
    attempt = output / "attempts" / ATTEMPT
    require(attempt.parent.is_dir() and not attempt.parent.is_symlink(), "Safe attempts parent required")
    attempt.mkdir(exist_ok=False)
    moved = []
    try:
        atomic_json(attempt / "INTENT.json", dict(plan_sha256=plan_sha, plan=plan))
        for source, target in ((output / "train_execution_cross/groups", attempt / "groups"),
                               (output / "receipts/train_execution_cross", attempt / "receipts")):
            require(not os.path.lexists(target) and source.stat().st_dev == attempt.stat().st_dev, "Rename must stay on one filesystem")
            os.rename(source, target)
            moved.append(dict(original_path=str(source.relative_to(output)), archive_path=str(target.relative_to(output))))
        for name, original in (("groups", "train_execution_cross/groups/"), ("receipts", "receipts/train_execution_cross/")):
            observed, _ = inventory(attempt / name)
            expected = {row["original_path"][len(original):]: (row["bytes"], row["sha256"])
                        for row in plan["files"] if row["original_path"].startswith(original)}
            require(observed == expected, "Preserved file bytes or inventory differ")
        for row in plan["scientific_sources"] + plan["registration_files"] + plan["operational_evidence"] + [plan["source_fix"], plan["preservation_helper"]]:
            root = output if row["scope"] == "run" else repo
            require(descriptor(root, row["path"], row["scope"]) == row, "Unmoved evidence changed")
        result = dict(plan, complete=True, plan_sha256=plan_sha, completed_at_utc=datetime.now(timezone.utc).isoformat(),
                      moved_directories=moved, all_81_files_byte_hash_verified_after_move=True,
                      scientific_source_and_registration_bytes_unchanged=True)
        atomic_json(attempt / "PRESERVATION.json", result)
        return dict(path=str(attempt / "PRESERVATION.json"), sha256=hashlib.sha256(raw(attempt / "PRESERVATION.json")).hexdigest(),
                    files=81, bytes=plan["file_bytes"], complete=True)
    except BaseException as error:
        try:
            atomic_json(attempt / "PRESERVATION_FAILURE.json", dict(error=repr(error), moved_directories=moved, complete=False))
        except OSError:
            pass
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("plan", "preserve"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expected-plan-sha256")
    args = parser.parse_args()
    if args.action == "plan":
        plan = make_plan(args.output)
        print(json.dumps(dict(plan_sha256=hashlib.sha256(encoded(plan)).hexdigest(), plan=plan), indent=2, sort_keys=True))
    else:
        parser.error("preserve requires the reviewed plan SHA256") if not args.expected_plan_sha256 else None
        print(json.dumps(preserve(args.output, args.expected_plan_sha256), sort_keys=True))


if __name__ == "__main__":
    main()
