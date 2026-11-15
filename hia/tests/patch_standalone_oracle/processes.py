"""Observe complete real programs with exact bytes and fresh owned fixtures."""
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import resource
import shutil
import stat
import subprocess
import time

from .abi_admission import require
from .process_corpus import categories
from .process_corpus import CASE_COUNT
from .process_corpus import materialize
from .process_corpus import matrix


def digest(data):
    return hashlib.sha256(data).hexdigest()


def save(path, value):
    with path.open("x") as stream:
        json.dump(value, stream, indent=2)
        stream.write("\n")


def tree(root):
    raw_root = os.fsencode(root)
    records, inode_paths = [], {}

    def visit(path, relative):
        metadata = os.lstat(path)
        row = {"path_hex": relative.hex(), "mode": stat.S_IMODE(metadata.st_mode)}
        if stat.S_ISLNK(metadata.st_mode):
            row.update(kind="symlink", target_hex=os.readlink(path).hex())
        elif stat.S_ISDIR(metadata.st_mode):
            row["kind"] = "directory"
        elif stat.S_ISREG(metadata.st_mode):
            with open(path, "rb") as stream:
                data = stream.read()
            row.update(kind="file", bytes=len(data), contents_hex=data.hex())
            inode_paths.setdefault((metadata.st_dev, metadata.st_ino), []).append(relative.hex())
        else:
            row.update(kind="other", file_type=stat.S_IFMT(metadata.st_mode))
        records.append(row)
        if row["kind"] == "directory":
            for name in sorted(os.listdir(path)):
                visit(path + b"/" + name, relative + (b"/" if relative else b"") + name)

    visit(raw_root, b"")
    groups = sorted(sorted(paths) for paths in inode_paths.values() if len(paths) > 1)
    return {"entries": records, "hardlink_groups": groups}


def run_one(binary, case, fixture, record_dir, side, counts):
    require(not fixture.exists() and not fixture.is_symlink(), "fixture must be a fresh owned path")
    request = materialize(case, fixture)
    before = tree(fixture)
    fd_close_after_spawn, fd_hold = [], []
    process = None
    observation = {"side": side, "binary": str(binary), "case": case, "timed_out": False,
                   "before_tree": before, "fixture_hex": os.fsencode(fixture).hex(),
                   "argv_hex": [value.hex() for value in request["argv"]],
                   "cwd_hex": request["cwd"].hex(), "stdin_hex": request["stdin"].hex(),
                   "environment_hex": {key.hex(): value.hex() for key, value in sorted(request["environment"].items())},
                   "patch_hex": request["patch"].hex(), "process_started": False}
    out, err = b"", b""
    start = time.monotonic_ns()
    try:
        if case["stdin_mode"] == "bytes":
            stdin = subprocess.PIPE
            input_bytes = request["stdin"]
        elif case["stdin_mode"] == "directory":
            stdin = os.open(os.fsencode(fixture) + b"/stdin-directory", os.O_RDONLY | os.O_DIRECTORY)
            fd_close_after_spawn.append(stdin)
            input_bytes = None
        else:
            require(case["stdin_mode"] == "open-pipe" and len(request["argv"]) >= 2,
                    "a held-open stdin requires an actual supplied argument")
            stdin, writer = os.pipe()
            fd_close_after_spawn.append(stdin)
            fd_hold.append(writer)
            input_bytes = None

        def output_fd(mode):
            if mode == "pipe":
                return subprocess.PIPE
            require(mode == "closed-pipe", "unknown fixed output mode")
            reader, writer = os.pipe()
            os.close(reader)
            fd_close_after_spawn.append(writer)
            return writer

        stdout = output_fd(case["stdout_mode"])
        stderr = output_fd(case["stderr_mode"])

        def before_exec():
            os.umask(0o022)
            resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
            if case["cwd_mode"] == "removed-after-chdir":
                # This is an empty directory newly made for this one process.
                # No filesystem result returned by the product is substituted.
                os.rmdir(request["cwd"])

        counts["launch_attempts"] += 1
        process = subprocess.Popen(request["argv"], executable=os.fsencode(binary),
            stdin=stdin, stdout=stdout, stderr=stderr, cwd=request["cwd"],
            env=request["environment"], preexec_fn=before_exec, close_fds=True)
        observation["process_started"] = True
        counts["actual_processes"] += 1
        for descriptor in fd_close_after_spawn:
            os.close(descriptor)
        fd_close_after_spawn.clear()
        try:
            out, err = process.communicate(input=input_bytes, timeout=10)
        except subprocess.TimeoutExpired:
            observation["timed_out"] = True
            process.kill()
            out, err = process.communicate()
        out, err = out or b"", err or b""
    finally:
        if process is not None and process.poll() is None:
            process.kill()
            process.wait()
        if process is not None:
            observation["returncode"] = process.returncode
            if process.returncode is not None:
                counts["observed_terminal_processes"] += 1
        for descriptor in fd_close_after_spawn + fd_hold:
            os.close(descriptor)
        observation.update(elapsed_ns=time.monotonic_ns() - start,
                           stdout_hex=out.hex(), stderr_hex=err.hex(),
                           after_tree=tree(fixture), actual_stdout_bytes=len(out), actual_stderr_bytes=len(err))
        (record_dir / (side + ".stdout")).write_bytes(out)
        (record_dir / (side + ".stderr")).write_bytes(err)
        save(record_dir / (side + ".json"), observation)
    require(observation["process_started"] and not observation["timed_out"],
            "the complete process did not reach an observed terminal state")
    return observation


def comparable(observation):
    # Side, executable filename and wall time are the only removed fields.
    # The exact argv, cwd, environment, output, status and file bytes remain.
    return {key: value for key, value in observation.items()
            if key not in ("side", "binary", "elapsed_ns")}


def validate_mode_case(case, observation):
    if case["category"] != "full-main-patch-environment" or case["kind"] != "update-crlf":
        return
    require(observation["returncode"] == 0, "the mode-observation fixture did not succeed")
    expected = b"ONE\r\nTWO\r\n" if case["environment_hex"] == b"1".hex() else b"ONE\nTWO\n"
    rows = [r for r in observation["after_tree"]["entries"] if r["path_hex"] == b"cwd/target.txt".hex()]
    require(len(rows) == 1 and rows[0].get("contents_hex") == expected.hex(),
            "the complete original environment-selection fixture did not distinguish exact Unicode 1")


def run(binaries, output):
    require(not output.exists(), "process observations require a new external directory")
    output.mkdir(parents=True)
    cases = matrix()
    save(output / "cases.json", cases)
    report = {"schema": "codex.hia.patch-standalone-process-observations.v1", "passed": False,
              "case_count": len(cases), "categories": categories(cases), "compared_pairs": 0,
              "actual_processes": 0, "launch_attempts": 0, "observed_terminal_processes": 0,
              "mismatches": 0, "skipped": 0, "cases": [],
              "filesystem_results_substituted": False, "paths_or_errors_normalized": False,
              "native_transition_counts_instrumented": False,
              "launcher_umask": "022", "launcher_core_dump_limit_bytes": 0,
              "stdout_write_syscall_trace_qualified": False,
              "runtime_initialization_failure_qualified": False,
              "stdout_flush_failure_qualified": False,
              "runtime_shutdown_and_cancellation_qualified": False}
    codes = Counter()
    try:
        for case in cases:
            folder = output / ("case-" + str(case["id"]).zfill(4))
            folder.mkdir()
            fixture = folder / "fixture"
            original = run_one(binaries["original"], case, fixture, folder, "original", report)
            validate_mode_case(case, original)
            # The same absolute fixture path and exact initial content are used
            # for both binaries. Its complete original after-state was saved.
            require(fixture.parent == folder and fixture.name == "fixture" and not fixture.is_symlink(),
                    "refuse cleanup outside this exact newly owned fixture")
            shutil.rmtree(fixture)
            native = run_one(binaries["native"], case, fixture, folder, "native", report)
            validate_mode_case(case, native)
            left, right = comparable(original), comparable(native)
            if left != right:
                report["mismatches"] += 1
                raise RuntimeError("complete standalone process differs at case " + str(case["id"]))
            report["compared_pairs"] += 1
            codes[str(original["returncode"])] += 1
            report["cases"].append({"id": case["id"], "returncode": original["returncode"],
                "original_record": str(folder / "original.json"), "native_record": str(folder / "native.json"),
                "original_record_sha256": digest((folder / "original.json").read_bytes()),
                "native_record_sha256": digest((folder / "native.json").read_bytes()),
                "exact_comparable_sha256": digest(json.dumps(left, sort_keys=True).encode())})
        require(report["compared_pairs"] == CASE_COUNT and report["actual_processes"] == 2 * CASE_COUNT,
                "the fixed whole-process corpus is incomplete")
        require(report["launch_attempts"] == report["observed_terminal_processes"] == 2 * CASE_COUNT,
                "the fixed whole-process launches or terminal statuses are incomplete")
        require(all(str(code) in codes for code in (0, 1, 2)), "required success and error exits were not exercised")
        report["passed"] = True
    except Exception as error:
        report["error"] = type(error).__name__ + ": " + str(error)
        raise
    finally:
        report["observed_returncodes"] = dict(codes)
        save(output / "report.json", report)
    return report
