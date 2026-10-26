"""PROSPECTIVE ONLY: root-reviewed single validation, never a qualification issuer.

No default GO, timeout, retry, cleanup, installation, cancellation or model warmup.
This file has not been executed. The admission template deliberately cannot run.
"""

import argparse
import errno
import hashlib
import json
import os
from pathlib import Path
import re
import resource
import runpy
import stat
import subprocess
import sys
import time
import traceback


HERE = Path(__file__).resolve().parent
NOFOLLOW = os.O_NOFOLLOW | os.O_NONBLOCK


def require(value, reason):
    if not value:
        raise ValueError(reason)


def fields(info):
    return {"dev": info.st_dev, "inode": info.st_ino, "uid": info.st_uid,
            "gid": info.st_gid, "mode": oct(stat.S_IMODE(info.st_mode)),
            "nlink": info.st_nlink, "bytes": info.st_size,
            "mtime_ns": info.st_mtime_ns, "ctime_ns": info.st_ctime_ns}


def no_links(path):
    require(path.is_absolute(), "ABSOLUTE_PATH_REQUIRED")
    for item in [path, *path.parents]:
        require(not item.is_symlink(), f"SYMLINK_PATH:{item}")


def digest(path):
    no_links(path)
    before = path.lstat()
    require(stat.S_ISREG(before.st_mode), f"REGULAR_FILE_REQUIRED:{path}")
    value = hashlib.sha256()
    with os.fdopen(os.open(path, os.O_RDONLY | NOFOLLOW | os.O_NOATIME), "rb") as stream:
        require(fields(os.fstat(stream.fileno())) == fields(before), "OPEN_IDENTITY_DRIFT")
        size = 0
        while block := stream.read(4 * 1024 * 1024):
            size += len(block)
            require(size <= before.st_size, "FILE_GREW")
            value.update(block)
    require(size == before.st_size and fields(path.lstat()) == fields(before), "FILE_DRIFT")
    return value.hexdigest()


def read_json(path, expected):
    no_links(path)
    with os.fdopen(os.open(path, os.O_RDONLY | NOFOLLOW | os.O_NOATIME), "rb") as stream:
        before = os.fstat(stream.fileno())
        require(stat.S_ISREG(before.st_mode) and before.st_size <= 2 * 1024 * 1024, "BOUNDED_REGULAR_METADATA_REQUIRED")
        raw = stream.read(before.st_size + 1)
        require(len(raw) == before.st_size and fields(before) == fields(os.fstat(stream.fileno())) == fields(path.lstat()), "METADATA_DRIFT")
    require(hashlib.sha256(raw).hexdigest() == expected, f"SHA256_MISMATCH:{path}")
    return json.loads(raw)


def save(path, value):
    raw = (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode()
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def git(repo, *args):
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(GIT_NO_LAZY_FETCH="1", GIT_NO_REPLACE_OBJECTS="1", GIT_OPTIONAL_LOCKS="0",
               GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull,
               GIT_TERMINAL_PROMPT="0", GIT_GRAFT_FILE=os.devnull)
    return subprocess.check_output(["git", "-c", "core.fsmonitor=false", "-C", str(repo), *args], env=env)


def visible_processes(old=None):
    builds, matches, observations = [], [], []
    build_names = {"cargo", "rustc", "clippy-driver", "cargo-clippy", "cargo-nextest", "rustfmt"}
    for proc in Path("/proc").iterdir():
        if not proc.name.isdecimal():
            continue
        row = {"pid": int(proc.name), "uid": None, "permission_denied": {}, "raced": {}}

        def observed(operation, read):
            try:
                return read()
            except OSError as error:
                if error.errno in {errno.EACCES, errno.EPERM}:
                    counts = row["permission_denied"]
                elif error.errno in {errno.ENOENT, errno.ESRCH}:
                    counts = row["raced"]
                else:
                    raise
                counts[operation] = counts.get(operation, 0) + 1
                return None

        row["uid"] = observed("uid", lambda: proc.stat().st_uid)
        comm = observed("comm", lambda: (proc / "comm").read_text().strip())
        def first_argument():
            with (proc / "cmdline").open("rb") as stream:
                return os.fsdecode(stream.read(4096).split(b"\0", 1)[0])
        arg0 = observed("cmdline", first_argument)
        if comm in build_names or (arg0 is not None and Path(arg0).name in build_names):
            builds.append({"pid": row["pid"], "uid": row["uid"], "comm": comm, "arg0": arg0})
        if old is not None:
            exe = observed("exe", lambda: (proc / "exe").stat())
            if exe is not None and (exe.st_dev, exe.st_ino) == (old["dev"], old["inode"]):
                matches.append({"pid": row["pid"], "reference": "exe"})
            fds = observed("fd-list", lambda: list((proc / "fd").iterdir()))
            for path in fds or []:
                info = observed("fd-stat", path.stat)
                if info is not None and (info.st_dev, info.st_ino) == (old["dev"], old["inode"]):
                    matches.append({"pid": row["pid"], "reference": str(path)})
        observations.append(row)
    return {"visible_active_rust": builds, "visible_old_cli_references": matches,
            "process_observations": observations,
            "permission_denied_count": sum(sum(x["permission_denied"].values()) for x in observations),
            "raced_count": sum(sum(x["raced"].values()) for x in observations),
            "scope": "PARTIAL_VISIBLE_PROC_ONLY_ROOT_EXCLUSIVE_UID1000_TARGET_LEASE_REQUIRED",
            "global_absence_reap_or_WholeU_proof": False}


def no_active_rust():
    report = visible_processes()
    require(not report["visible_active_rust"], f"VISIBLE_BUILD_REQUIRES_ROOT_COORDINATION:{report}")
    return report


def no_cli_references(old):
    report = visible_processes(old)
    require(not report["visible_active_rust"] and not report["visible_old_cli_references"],
            f"VISIBLE_BUILD_OR_OLD_CLI_REFERENCE_REQUIRES_ROOT_COORDINATION:{report}")
    report["old_cli_identity"] = old
    return report


def protecting_existing_cli(a):
    state = a["old_artifact_state"]
    require(state in {"PRESENT_BOUND_EXISTING_CLI", "ABSENT_AFTER_UNKNOWN_DELETION"},
            "EXPLICIT_OLD_ARTIFACT_STATE_REQUIRED")
    return state == "PRESENT_BOUND_EXISTING_CLI"


def absent_old_cli(a):
    require(not protecting_existing_cli(a), "ABSENT_STATE_REQUIRED")
    path = Path(a["old_cli"]["path"])
    no_links(path)
    try:
        path.lstat()
    except FileNotFoundError:
        return {"state": "ABSENT_AFTER_UNKNOWN_DELETION", "path": str(path),
                "historical_identity_not_observed_current": a["old_cli"],
                "preserved_or_backed_up": False, "cause_or_actor": "UNKNOWN"}
    raise ValueError("OLD_ARTIFACT_APPEARED_REQUIRES_NEW_ROOT_REVIEW")


def original_budget_unstarted(a):
    prior = a["prior_preflight_failure"]
    failed = read_json(Path(prior["path"]), prior["sha256"])
    require(failed["runroot_exists"] is False and failed["900_second_deadline_created"] is False
            and failed["builds_started"] == failed["tests_started"] == failed["model_forwards"] == 0,
            "ORIGINAL_ALLOCATION_ALREADY_STARTED_OR_UNKNOWN")
    require(not Path(prior["original_run_root"]).exists(), "PRIOR_RUNROOT_NOW_EXISTS")
    require(a["same_unstarted_budget"] == {"wall_seconds": 900, "prior_deadline_created": False,
            "prior_builds_started": 0, "prior_tests_started": 0, "restarts_or_extra_allocation": 0,
            "only_original_allocation_not_SDK1200_or_supervisor900": True},
            "EXACT_SAME_UNSTARTED_ALLOCATION_REQUIRED")


def uid_scoped_target_owner(a):
    require(a["process_visibility_policy"] == {
        "effective_uid": 1000, "target_owner_uid": 1000,
        "inaccessible_processes": "RECORD_PARTIAL_VISIBILITY_NOT_GLOBAL_ABSENCE",
        "visible_positive_cli_refs_or_builds": "REFUSE_BEFORE_BUILD",
        "reliance": "ROOT_EXCLUSIVE_AFTER_CACHE_TERMINAL_UNTIL_VALIDATION_TERMINAL",
        "no_global_absence_reap_or_WholeU_claim": True}, "EXACT_PARTIAL_VISIBILITY_SCOPE_REQUIRED")
    require(os.getuid() == os.geteuid() == a["old_cli"]["uid"] == 1000, "UID1000_SCOPE_REQUIRED")
    original_budget_unstarted(a)
    target = Path(a["target"])
    no_links(target)
    require(a["target_state"] == "FRESH_CREATE_ONLY_ROOT_EXCLUSIVE" and not target.exists(),
            "FRESH_TARGET_MUST_BE_ABSENT_BEFORE_BUILD")
    require(target.parent.stat().st_uid == 1000, "FRESH_TARGET_PARENT_UID1000_REQUIRED")
    require(Path(a["environment"]["CARGO_TARGET_DIR"]) == target and
            Path(a["environment"]["CARGO_BIN_EXE_codex"]) == target / "debug" / "codex" and
            target != Path(a["old_cli"]["path"]).parent.parent,
            "DISTINCT_EXACT_FRESH_TARGET_AND_CLI_REQUIRED")
    if protecting_existing_cli(a):
        path = Path(a["old_cli"]["path"])
        no_links(path)
        require(path.stat().st_uid == 1000, "ORIGINAL_UID1000_TARGET_OWNER_REQUIRED")
    else:
        absent_old_cli(a)


def mount_check(a, minimum):
    m = a["external"]
    path = Path(m["mount"])
    no_links(path)
    current = fields(path.stat())
    require(all(current[k] == v for k, v in m["identity"].items()), "MOUNT_IDENTITY_DRIFT")
    matches = []
    for line in Path("/proc/self/mountinfo").read_text().splitlines():
        parts = line.split()
        split = parts.index("-")
        if parts[4] == str(path):
            matches.append(parts)
            require(parts[0] == m["mount_id"] and parts[2] == m["major_minor"], "MOUNT_CHANGED")
            require(parts[split + 1] == m["filesystem"] and parts[split + 2] == m["source"], "MOUNT_SOURCE")
            require(set(m["required_options"]) <= set(parts[5].split(",")), "MOUNT_NOT_NOEXEC")
    require(len(matches) == 1, "EXACT_EXTERNAL_MOUNT_REQUIRED")
    fs = os.statvfs(path)
    require(fs.f_bavail * fs.f_frsize >= minimum, "EXTERNAL_SPACE_PREREQUISITE")


def backup_cli(a, run, minimum):
    mount_check(a, minimum)
    src = Path(a["old_cli"]["path"])
    require(fields(src.lstat()) == {k: v for k, v in a["old_cli"].items() if k not in {"path", "sha256"}},
            "PROTECTED_OLD_CLI_IDENTITY_DRIFT")
    require(digest(src) == a["old_cli"]["sha256"], "PROTECTED_OLD_CLI_HASH_DRIFT")
    root = Path(a["external"]["backup_root"])
    no_links(root)
    root.mkdir(mode=0o700)
    dest = Path(a["external"]["backup_file"])
    require(dest.parent == root, "BACKUP_MUST_BE_PRIVATE_CHILD")
    with os.fdopen(os.open(src, os.O_RDONLY | NOFOLLOW | os.O_NOATIME), "rb") as incoming:
        require(fields(os.fstat(incoming.fileno())) == fields(src.lstat()), "BACKUP_SOURCE_OPEN_DRIFT")
        with os.fdopen(os.open(dest, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600), "wb") as outgoing:
            copied = 0
            while block := incoming.read(4 * 1024 * 1024):
                copied += len(block)
                require(copied <= a["old_cli"]["bytes"], "CLI_SOURCE_GREW")
                outgoing.write(block)
            outgoing.flush()
            os.fsync(outgoing.fileno())
    require(copied == a["old_cli"]["bytes"], "CLI_BACKUP_TRUNCATED")
    require(digest(dest) == digest(src) == a["old_cli"]["sha256"], "CLI_INDEPENDENT_READBACK_FAILED")
    require(fields(src.lstat()) == {k: v for k, v in a["old_cli"].items() if k not in {"path", "sha256"}},
            "OLD_CLI_CHANGED_BEFORE_BUILD")
    require(dest.stat().st_dev != src.stat().st_dev and dest.stat().st_nlink == 1, "NOT_INDEPENDENT_BACKUP")
    require(stat.S_IMODE(dest.stat().st_mode) == 0o600, "BACKUP_EXECUTION_NOT_PERMITTED")
    for directory in [root, root.parent]:
        fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    receipt = {"source": a["old_cli"], "backup": str(dest), "backup_identity": fields(dest.stat()),
               "sha256": digest(dest), "use": "NOEXEC_RETAINED_BYTES_ONLY_NOT_NEW_CLI"}
    save(root / "retained-artifact.json", receipt)
    save(run / "old-cli-preserved.json", receipt)


def export_chain(a, run):
    c = a["C"]
    repo = Path(c["repo"])
    require(git(repo, "rev-parse", c["head"] + "^{tree}").decode().strip() == c["tree"], "CHAIN_TREE")
    rows = git(repo, "ls-tree", "-rz", c["head"], "--", *c["export_prefixes"])
    require(hashlib.sha256(rows).hexdigest() == c["git_ls_tree_sha256"], "CHAIN_EXPORT_SET")
    root = Path(a["config"]["chain"])
    require(root.parent == run, "EXPORT_ROOT")
    root.mkdir(mode=0o700)
    expected = {}
    for row in rows.split(b"\0"):
        if not row:
            continue
        meta, raw_name = row.split(b"\t", 1)
        mode, kind, blob = meta.decode().split()
        name = raw_name.decode()
        require(kind == "blob" and mode in {"100644", "100755"}, "UNSUPPORTED_EXPORT_TYPE")
        require(not Path(name).is_absolute() and ".." not in Path(name).parts, "EXPORT_PATH")
        content = git(repo, "cat-file", "blob", blob)
        dest = root / name
        dest.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with dest.open("xb") as stream:
            stream.write(content)
        dest.chmod(0o755 if mode == "100755" else 0o644)
        expected[name] = {"path": name, "mode": mode, "git_blob": blob,
                          "bytes": len(content), "sha256": digest(dest)}
    require(sorted(expected.values(), key=lambda x: x["path"]) ==
            sorted(a["chain_objects"], key=lambda x: x["path"]), "EXPORT_READBACK_MISMATCH")
    require(len(expected) == 358, "EXACT_358_REQUIRED")
    actual = {str(x.relative_to(root)) for x in root.rglob("*") if x.is_file()}
    require(actual == set(expected), "EXPORT_EXTRA_OR_IGNORED_PYCACHE")
    save(run / "chain-export-readback.json", {"head": c["head"], "tree": c["tree"],
         "entries": list(expected.values()), "old_evidence_not_requalified": True})


def command(step, number, a, run, env, identity, count_reader):
    remaining = (int(env["HEPTA_INITIAL_QUERY_OUTER_DEADLINE_NS"]) - time.monotonic_ns()) / 1e9
    require(remaining > 0, "SAME_OUTER_DEADLINE_EXPIRED")
    require(identity(repository=Path(a["H"]["repo"]))["commit"] == a["H"]["head"], "HEAD_CHANGED")
    log = run / f"stage-{number:02d}.log"
    before = identity(repository=Path(a["H"]["repo"]))
    if number in (0, 1) or "expected_case" in step:
        require(before["tree"] == a["H"]["tree"] and not before["dirty"], "TEST_SOURCE_CHANGED")
    if number == 0:
        require(not Path(a["target"]).exists(), "FRESH_TARGET_PREBIRTH_COLLISION")
        if protecting_existing_cli(a):
            save(run / "old-cli-references-immediately-before-build.json", no_cli_references(a["old_cli"]))
        else:
            save(run / "old-cli-absent-immediately-before-build.json", absent_old_cli(a))
    elif number == 1 or "expected_case" in step:
        built = json.loads((run / "actual-source-cli.json").read_bytes())
        require(fields(Path(env["CARGO_BIN_EXE_codex"]).stat()) == built["identity"] and
                digest(Path(env["CARGO_BIN_EXE_codex"])) == built["sha256"], "ACTUAL_SOURCE_CLI_CHANGED")
    started = time.monotonic()
    save(run / f"stage-{number:02d}-started.json", {"argv": step["argv"], "cwd": step["cwd"],
         "before": before, "started_wall_ns": time.time_ns(), "no_wrapper_timeout": True})
    # Relay raw output to the single original outer owner's cumulative output cap.
    with log.open("xb") as output:
        # Final scheduling check follows all long hashing/fsync/open work.
        remaining = (int(env["HEPTA_INITIAL_QUERY_OUTER_DEADLINE_NS"]) - time.monotonic_ns()) / 1e9
        require(remaining > 0, "SAME_OUTER_DEADLINE_EXPIRED_BEFORE_BIRTH")
        stage_env = dict(env)
        stage_env.pop("HEPTA_PN3_NEURAL_NATIVE_CONFIG", None)
        if "config_path" in step:
            stage_env["HEPTA_PN3_NEURAL_NATIVE_CONFIG"] = step["config_path"]
            config = next(x for x in a["case_configs"] if x["path"] == step["config_path"])
            require(digest(Path(step["config_path"])) == config["sha256"], "CASE_CONFIG_CHANGED")
            require(not Path(config["projection"]["output"]).exists(), "CASE_OUTPUT_ALREADY_EXISTS")
        remaining = (int(env["HEPTA_INITIAL_QUERY_OUTER_DEADLINE_NS"]) - time.monotonic_ns()) / 1e9
        require(remaining > 0, "SAME_OUTER_DEADLINE_EXPIRED_AT_BIRTH")
        process = subprocess.Popen(step["argv"], cwd=step["cwd"], env=stage_env,
                                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        assert process.stdout is not None
        with process.stdout:
            while block := process.stdout.read(65536):
                output.write(block)
                sys.stdout.buffer.write(block)
                sys.stdout.buffer.flush()
        code = process.wait()
    after = identity(repository=Path(a["H"]["repo"]))
    text = log.read_text(errors="replace")
    plain = re.sub(r"\x1b\[[0-9;]*m", "", text)
    summaries = re.findall(r"Summary[^\n]*", plain)
    passed, failed = count_reader(text)
    receipt = {"argv": step["argv"], "cwd": step["cwd"], "before": before, "after": after,
               "exit_code": code, "elapsed_seconds": time.monotonic() - started,
               "log_sha256": digest(log), "terminal_summaries": summaries,
               "observed_passed": passed, "observed_failed_or_timeout": failed,
               "same_outer_remaining_at_birth_seconds": remaining,
               "case_config": step.get("config_path"),
               "retry_lines": [line for line in plain.splitlines() if re.search(r"\b(?:RETRY|TRY [12]|FLAKY)\b", line)]}
    selected_ok = True
    if "expected_case" in step:
        name = step["expected_case"]
        passes = [line for line in plain.splitlines() if re.search(r"\b(?:PASS|FLAKY)\b", line) and line.rstrip().endswith(name)]
        selected_skips = [line for line in plain.splitlines() if re.search(r"\bSKIP\b", line) and line.rstrip().endswith(name)]
        single_summary = len(summaries) == 1 and re.search(r"\b1 test run: 1 passed\b", summaries[0]) is not None
        selected_ok = bool(passes) and not selected_skips and single_summary and passed == 1 and failed == 0
        receipt.update(expected_case=name, selected_pass_lines=passes, selected_skip_lines=selected_skips,
                       selected_case_count=1 if selected_ok else None,
                       filtered_other_inventory_is_not_selected_case_skip=True)
    elif number == 1:
        selected_ok = bool(summaries) and passed > 0 and failed == 0
    save(run / f"stage-{number:02d}-result.json", receipt)
    require(code == 0 and selected_ok, f"STAGE_FAILED:{number}")
    return receipt


def collect_outputs(a, run, limit):
    root = Path(a["output_inventory_root"])
    rows = []
    if root.exists():
        for path in root.rglob("*"):
            require(len(rows) < limit, "ROOT_ADMITTED_READBACK_FILE_CAP_REACHED")
            no_links(path)
            item = {"path": str(path.relative_to(root)), **fields(path.lstat())}
            if path.is_file():
                item["sha256"] = digest(path)
            else:
                require(path.is_dir(), "UNSUPPORTED_OUTPUT_TYPE")
            rows.append(item)
    save(run / "output-inventory.json", {"rows": rows,
         "raw_supervisor_and_ready_receipts_retained_in_place": True,
         "no_missing_RSS_converted_to_zero": True, "no_terminal_or_authority_inferred": True})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--go", type=Path, required=True)
    parser.add_argument("--go-sha256", required=True)
    parser.add_argument("--pipeline", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    admission_path = HERE / "02-admission-proposal.json"
    go = read_json(args.go, args.go_sha256)
    a = read_json(admission_path, go.get("admission_sha256"))
    keys = {"schema", "decision", "helper_sha256", "admission_sha256", "cache_result", "cache_readback",
            "native_protocol", "sole_target_lease", "minimum_free_bytes", "PATH", "readback_file_cap", "cpu_affinity"}
    require(set(go) == keys and go["schema"] == "initial-query-root-go-v1" and
            go["decision"] == "GO_ONCE", "EXACT_ROOT_GO_REQUIRED_TEMPLATE_IS_NOT_GO")
    require(go["helper_sha256"] == digest(Path(__file__).resolve()) and
            go["admission_sha256"] == digest(admission_path), "GO_SOURCE_BINDING")
    require(go["sole_target_lease"] == "ROOT_EXCLUSIVE_AFTER_CACHE_TERMINAL_UNTIL_VALIDATION_TERMINAL",
            "TARGET_LEASE_REQUIRED")
    uid_scoped_target_owner(a)
    minima = go["minimum_free_bytes"]
    require(set(minima) == {"target", "external"} and
            all(type(x) is int and x > 0 for x in minima.values()), "ROOT_FRESH_DISK_GATE_REQUIRED")
    require(minima["target"] >= 8 * 1024**3, "ROOT_MINIMUM_TARGET_8GIB_REQUIRED")
    require(type(go["readback_file_cap"]) is int and go["readback_file_cap"] > 0, "ROOT_READBACK_CAP_REQUIRED")
    cache = read_json(Path(go["cache_result"]["path"]), go["cache_result"]["sha256"])
    require(cache.get("result") == "PASS_CACHE_IO_ONLY" and cache.get("io_only") is True and
            cache.get("retained_cache_hardlinks") == 150 and
            cache.get("no_model_test_budget_or_compatibility_retry") is True, "CACHE_NOT_COMPLETE")
    read_json(Path(go["cache_readback"]["path"]), go["cache_readback"]["sha256"])
    protocol = read_json(Path(go["native_protocol"]["path"]), go["native_protocol"]["sha256"])
    require(protocol == {"schema": "initial-query-root-native-protocol-v1", "decision": "ADMITTED_BY_ROOT",
            "original_limits": a["original_limits"], "manual_retries": 0,
            "new_feature_envelope": {"wall_seconds": 900, "cpu_count": 4, "nice": 10,
                                     "address_space_bytes": 16 * 1024**3},
            "no_prior_budget_reset": True,
            "scope": "CLI_BUILD_HOSTLIB_FIVE_INITIAL_OLD_NEURAL_THREE_NEW_FIX_STRICT_FMT_ONLY"}, "ROOT_PROTOCOL_REQUIRED")
    require(isinstance(go["PATH"], str) and go["PATH"] and all(Path(x).is_absolute() for x in go["PATH"].split(os.pathsep)),
            "EXPLICIT_ROOT_TOOL_PATH_REQUIRED")
    require(digest(Path(a["source_evidence"]["path"])) == a["source_evidence"]["sha256"], "EVIDENCE_CHANGED")
    reader = a["H"]["identity_reader"]
    require(digest(Path(reader["path"])) == reader["sha256"], "IDENTITY_READER_CHANGED")
    owners = runpy.run_path(reader["path"], run_name="initial_query_read_only_identity")
    identity = owners["identity"]
    original = identity(repository=Path(a["H"]["repo"]))
    require(original["commit"] == a["H"]["head"] and original["tree"] == a["H"]["tree"] and not original["dirty"],
            "EXACT_CLEAN_SOURCE_REQUIRED")
    cpus = go["cpu_affinity"]
    require(isinstance(cpus, list) and len(cpus) == len(set(cpus)) == 4 and
            all(type(x) is int and x >= 0 for x in cpus) and set(cpus) <= os.sched_getaffinity(0), "EXACT_FOUR_AVAILABLE_CPUS_REQUIRED")
    run = Path(a["run_root"])
    if args.pipeline:
        marker = json.loads((run / "go-consumed.json").read_bytes())
        require(marker["go_sha256"] == args.go_sha256 and marker["owner_pid"] == os.getppid(), "ROOT_OWNED_PIPELINE_REQUIRED")
        require(os.sched_getaffinity(0) == set(cpus) and os.getpriority(os.PRIO_PROCESS, 0) == 10 and
                resource.getrlimit(resource.RLIMIT_AS) == (16 * 1024**3, 16 * 1024**3), "INHERITED_RESOURCE_ENVELOPE_REQUIRED")
        save(run / "pipeline-started-once.json", {"pid": os.getpid(), "same_outer_deadline_ns":
             int(os.environ["HEPTA_INITIAL_QUERY_OUTER_DEADLINE_NS"])})
        return pipeline(a, go, run, identity, owners)
    proc = no_active_rust()
    if protecting_existing_cli(a):
        proc["old_cli_references"] = no_cli_references(a["old_cli"])
    else:
        proc["old_artifact_absence"] = absent_old_cli(a)
    fs = os.statvfs(Path(a["target"]).parent)
    require(fs.f_bavail * fs.f_frsize >= minima["target"], "FRESH_POST_CACHE_TARGET_SPACE_PREREQUISITE")
    if protecting_existing_cli(a):
        mount_check(a, minima["external"])
        require(not Path(a["external"]["backup_root"]).exists(), "BACKUP_PATH_EXISTS")
    no_links(run)
    require(not run.exists(), "CREATE_ONLY_PATH_EXISTS")
    run.mkdir(mode=0o700)
    save(run / "go-consumed.json", {"go_sha256": args.go_sha256, "owner_pid": os.getpid(),
         "started_wall_ns": time.time_ns(), "single_launch": True, "process_snapshot": proc})
    os.sched_setaffinity(0, set(cpus))
    os.setpriority(os.PRIO_PROCESS, 0, 10)
    resource.setrlimit(resource.RLIMIT_AS, (16 * 1024**3, 16 * 1024**3))
    deadline = time.monotonic_ns() + 900 * 10**9
    os.environ["HEPTA_INITIAL_QUERY_OUTER_DEADLINE_NS"] = str(deadline)
    save(run / "outer-resource-envelope.json", {"absolute_deadline_ns": deadline, "new_total_seconds": 900,
         "cpu_affinity": sorted(os.sched_getaffinity(0)), "nice": os.getpriority(os.PRIO_PROCESS, 0),
         "RLIMIT_AS": resource.getrlimit(resource.RLIMIT_AS), "no_prior_budget_reset": True,
         "budget_allocation": a["same_unstarted_budget"]})
    argv = [os.fsdecode(Path(os.sys.executable).resolve()), str(Path(__file__).resolve()),
            "--go", str(args.go), "--go-sha256", args.go_sha256, "--pipeline"]
    outer = owners["execute_logged"](argv, run / "whole-pipeline.log",
              timeout_seconds=max(0, (deadline - time.monotonic_ns()) / 1e9))
    outer.update(schema="initial-query-single-outer-envelope-v1", no_retry=True,
                 requested_absolute_deadline_ns=deadline, escaped_sessions_reclaimed="UNKNOWN_NOT_CLAIMED",
                 WholeU_retirement_or_refund_authority=False, overall_I10="NOT_QUALIFIED")
    save(run / "outer-terminal.json", outer)
    return 0 if outer["returncode"] == 0 and not outer["timed_out"] and not outer["output_limit_exceeded"] else 1


def pipeline(a, go, run, identity, owners):
    result = {"schema": "initial-query-validation-result-v1", "result": "FAIL",
              "tested_head": a["H"]["head"], "authority": "NONE", "overall_I10": "NOT_QUALIFIED",
              "retained_failure_material": True, "manual_retries": 0}
    try:
        if protecting_existing_cli(a):
            backup_cli(a, run, go["minimum_free_bytes"]["external"])
        else:
            save(run / "old-cli-absent-not-backed-up.json", absent_old_cli(a))
        export_chain(a, run)
        (run / "inputs").mkdir(mode=0o700)
        (run / "outputs").mkdir(mode=0o700)
        require(digest(Path(a["original_config"]["path"])) == a["original_config"]["sha256"], "OLD_CONFIG_CHANGED")
        require(digest(Path(a["parent"]["path"])) == a["parent"]["sha256"], "PARENT_CHANGED")
        for config in a["case_configs"]:
            save(Path(config["path"]), config["projection"])
            require(digest(Path(config["path"])) == config["sha256"], "EXACT_CASE_CONFIG_REQUIRED")
        env = dict(os.environ)
        env.update(a["environment"], PATH=go["PATH"])
        require(not any(k in env for k in ["NEXTEST_RETRIES", "NEXTEST_SLOW_TIMEOUT", "RUSTFLAGS", "CARGO_ENCODED_RUSTFLAGS"]),
                "AMBIENT_COMPILER_OR_TEST_OVERRIDE_REQUIRES_REVIEW")
        receipts = []
        for number, step in enumerate(a["steps"]):
            receipts.append(command(step, number, a, run, env, identity, owners["observed_test_counts"]))
            if number == 0:
                binary = Path(env["CARGO_BIN_EXE_codex"])
                actual = fields(binary.stat())
                require((actual["dev"], actual["inode"]) !=
                        (a["old_cli"]["dev"], a["old_cli"]["inode"]),
                        "FRESH_CLI_MUST_NOT_ADOPT_HISTORICAL_INODE")
                save(run / "actual-source-cli.json", {"source": a["H"], "path": str(binary),
                     "bytes": binary.stat().st_size, "identity": fields(binary.stat()),
                     "old_artifact_state": a["old_artifact_state"],
                     "historical_old_cli_identity_not_adopted": a["old_cli"],
                     "sha256": digest(binary), "build_stage": 0,
                     "not_old_cli_or_backup": str(binary) != a["external"]["backup_file"]})
        collect_outputs(a, run, go["readback_file_cap"])
        final = identity(repository=Path(a["H"]["repo"]))
        patch = git(Path(a["H"]["repo"]), "diff", "--binary", "--no-ext-diff", "--no-textconv", "HEAD", "--")
        (run / "post-fix-format.patch").open("xb").write(patch)
        result.update(result="STAGES_COMPLETED_REQUIRES_ROOT_READBACK", after=final,
                      tested_source_equals_postprocessed_source=not final["dirty"],
                      distinct_selected_cases=9, selected_case_skip_count=0,
                      historical_callback_not_retractable=True)
    except Exception as error:
        result.update(error=repr(error), traceback=traceback.format_exc(), no_cleanup_or_redispatch=True)
    finally:
        result["finished_wall_ns"] = time.time_ns()
        save(run / "result.json", result)
    return 0 if result["result"] == "STAGES_COMPLETED_REQUIRES_ROOT_READBACK" else 1


if __name__ == "__main__":
    raise SystemExit(main())
