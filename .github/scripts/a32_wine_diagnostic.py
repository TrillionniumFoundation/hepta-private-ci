#!/usr/bin/env python3
"""Add-only a32 Wine diagnostic: evidence, not a product fix or full-CI substitute."""
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import time
import traceback
import urllib.request
import uuid

BASE = "a32d73f00cfc292ff1ed4ac5cef958ca9f238020"
BASE_TREE = "603a3e5b69258e37653a828dda625efe45365d7e"
BRANCH = "diagnostic/a32-wine-repro-20261022"
LABEL = "//bazel/rules/testing/wine:wine-test-support-unit-tests"
ALLOW = (
    ".github/scripts/a32_wine_diagnostic.py",
    ".github/scripts/test_a32_wine_diagnostic.py",
    ".github/workflows/a32-wine-diagnostic.yml",
)
CASES = (
    "tests::pinned_powershell_runs_under_wine_with_a_pty",
    "tests::take_stdout_panics_when_called_twice",
    "tests::shutdown_reports_nonzero_process_exit",
    "tests::shutdown_returns_teardown_error",
)
PLAN = ("full-original-parallelism", *CASES)
ASSET = "dotslash-ubuntu-22.04.x86_64.v0.5.9.tar.gz"
ASSET_SIZE = 777657
ASSET_SHA256 = "ba6b6908c69db8264efdb8ee32f4906284ea3b77247c611339b5f60160cc5691"


def require(ok, message):
    if not ok:
        raise RuntimeError(message)


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    temporary.replace(path)


def git(root, *args):
    return subprocess.check_output(["git", "-C", str(root), *args])


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def git_blob(data):
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()


def tree_entries(root, ref):
    result = {}
    for entry in git(root, "ls-tree", "-rz", ref).split(b"\0"):
        if entry:
            header, path = entry.split(b"\t", 1)
            mode, kind, oid = header.decode().split()
            require(kind == "blob", "unsupported tree entry: " + os.fsdecode(path))
            result[os.fsdecode(path)] = (mode, oid)
    return result


def guard(root, expected, base=BASE, base_tree=BASE_TREE, allow=ALLOW):
    """Check HEAD ancestry, complete index and real bytes, not stat-cache cleanliness."""
    head = git(root, "rev-parse", "HEAD").decode().strip()
    require(head == expected, "HEAD differs from dispatched SOURCE_SHA")
    parents = git(root, "rev-list", "--parents", "-n", "1", "HEAD").decode().split()
    require(parents == [head, base], "input must have exactly one parent: a32")
    require(git(root, "rev-parse", base + "^{tree}").decode().strip() == base_tree,
            "base tree mismatch")
    old, current = tree_entries(root, base), tree_entries(root, "HEAD")
    require(set(current) - set(old) == set(allow), "new-file allowlist mismatch")
    require(all(current.get(p) == entry for p, entry in old.items()), "product tree changed")
    require(all(current[p][0] == "100644" for p in allow), "harness must be regular files")
    flags = git(root, "ls-files", "-v", "-f", "-z")
    require(all(p.startswith(b"H ") for p in flags.split(b"\0") if p),
            "hidden index flags (assume-unchanged/skip-worktree/fsmonitor-valid)")
    index = {}
    for entry in git(root, "ls-files", "--stage", "-z").split(b"\0"):
        if entry:
            header, path = entry.split(b"\t", 1)
            mode, oid, stage = header.decode().split()
            require(stage == "0", "unmerged index")
            index[os.fsdecode(path)] = (mode, oid)
    require(index == current, "index differs from input commit")
    checked = 0
    for path, (mode, oid) in current.items():
        file = root / path
        actual = file.lstat()
        if mode == "120000":
            require(stat.S_ISLNK(actual.st_mode), "symlink type changed: " + path)
            data = os.fsencode(os.readlink(file))
        else:
            require(stat.S_ISREG(actual.st_mode), "file type changed: " + path)
            require(bool(actual.st_mode & 0o111) == (mode == "100755"), "mode changed: " + path)
            data = file.read_bytes()
        require(git_blob(data) == oid, "source bytes changed: " + path)
        checked += len(data)
    require(not git(root, "status", "--porcelain", "--untracked-files=all"), "dirty worktree")
    for path in ("user.bazelrc", ".bazeliskrc", "tools/bazel"):
        require(not os.path.lexists(root / path), "undeclared Bazel configuration: " + path)
    return {"head": head, "tree": git(root, "rev-parse", "HEAD^{tree}").decode().strip(),
            "parent": base, "product_tree": base_tree, "allowed_additions": list(allow),
            "tracked_files": len(current), "checked_bytes": checked,
            "index_flags_sha256": sha256(flags), "all_source_bytes_match": True}


def environment_guard():
    forbidden = ("BUILDBUDDY_API_KEY", "CODEX_BAZEL_BIN", "BAZEL_OPTS", "BAZEL_ARGS",
                 "BAZELISK_BAZELRC", "BAZELISK_SKIP_WRAPPER", "RUST_TEST_THREADS",
                 "RUST_TEST_NOCAPTURE", "TESTBRIDGE_TEST_ONLY", "CODEX_BAZEL_TEST_SKIP_FILTERS",
                 "RUSTFLAGS", "CARGO_ENCODED_RUSTFLAGS")
    require(not [key for key in forbidden if os.environ.get(key)],
            "undeclared credential/flag/test-filter environment present")
    require(os.environ.get("USE_BAZEL_VERSION", "9.3.0") == "9.3.0", "wrong Bazel selection")
    require(os.environ.get("GITHUB_REF") == "refs/heads/" + BRANCH, "wrong branch")
    require(os.environ.get("RUNNER_OS") == "Linux" and os.environ.get("RUNNER_ARCH") == "X64",
            "requires standard Ubuntu24.04 x64 runner")


def dotslash_binary(data):
    require(len(data) == ASSET_SIZE and sha256(data) == ASSET_SHA256,
            "DotSlash asset length/checksum mismatch")
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
        members = [m for m in archive.getmembers() if m.isfile() and Path(m.name).name == "dotslash"]
        require(len(members) == 1 and 0 < members[0].size <= 10_000_000, "bad DotSlash archive")
        binary = archive.extractfile(members[0]).read(10_000_001)
        require(len(binary) == members[0].size, "truncated DotSlash binary")
        return binary


def bootstrap(out):
    url = "https://github.com/facebook/dotslash/releases/download/v0.5.9/" + ASSET
    with urllib.request.urlopen(url, timeout=120) as response:
        data = response.read(ASSET_SIZE + 1)
    binary = dotslash_binary(data)
    tools = out / "tools"
    tools.mkdir(parents=True, exist_ok=True)
    (tools / ASSET).write_bytes(data)
    executable = tools / "dotslash"
    executable.write_bytes(binary)
    executable.chmod(0o755)
    # a32 .bazelrc gives tests a fixed PATH including /usr/local/bin, not GITHUB_PATH.
    subprocess.run(["sudo", "cp", str(executable), "/usr/local/bin/dotslash"], check=True)
    version = subprocess.check_output(["/usr/local/bin/dotslash", "--version"], text=True).strip()
    require(version == "DotSlash 0.5.9", "wrong DotSlash version")
    with open(os.environ["GITHUB_PATH"], "a") as path:
        path.write(str(tools) + "\n")
    save(out / "dotslash.json", {"url": url, "size": len(data), "sha256": sha256(data),
                                 "binary_sha256": sha256(binary), "version": version})


def expected_tests(root):
    source = (root / "bazel/rules/testing/wine/src/lib_tests.rs").read_text()
    names = {"tests::" + n for n in re.findall(r"#\[(?:tokio::)?test\]\s+(?:async )?fn (\w+)", source)}
    require(len(names) == 13 and set(CASES) <= names, "a32 test inventory mismatch")
    return names


def parse_test_log(text, names, total=13):
    starts = [int(n) for n in re.findall(r"(?m)^running (\d+) tests?\s*$", text)]
    seen = re.findall(r"(?m)^test (tests::\w+) \.\.\.", text)
    summaries = re.findall(r"test result: (ok|FAILED)\. (\d+) passed; (\d+) failed; (\d+) ignored; "
                           r"(\d+) measured; (\d+) filtered out;", text)
    outcomes = re.findall(r"(?m)^test (tests::\w+) \.\.\. (ok|FAILED|ignored)(?:[ \t].*)?$", text)
    # In serial --nocapture mode, a panic/backtrace can split libtest's prefix and status.
    if len(names) == 1 and not outcomes and seen == list(names):
        standalone = re.findall(r"(?m)^(ok|FAILED|ignored)[ \t]*$", text)
        if len(standalone) == 1:
            outcomes = [(seen[0], standalone[0])]
    counts = None
    if len(summaries) == 1:
        status, *numbers = summaries[0]
        counts = dict(zip(("passed", "failed", "ignored", "measured", "filtered"), map(int, numbers)))
        counts["result"] = status
    passed = (starts == [len(names)] and len(seen) == len(names) and set(seen) == set(names)
              and len(outcomes) == len(names) and {n for n, _ in outcomes} == set(names)
              and all(status == "ok" for _, status in outcomes)
              and counts is not None and counts == {"passed": len(names), "failed": 0,
                  "ignored": 0, "measured": 0, "filtered": total - len(names), "result": "ok"})
    return {"running_counts": starts, "observed_test_names": seen, "per_case_outcomes": outcomes, "counts": counts,
            "count_and_name_guard_passed": passed}


def parse_bep(path):
    records, errors = [], []
    if path.exists():
        for line_number, line in enumerate(path.read_text(errors="replace").splitlines(), 1):
            try:
                records.append(json.loads(line))
            except ValueError:
                errors.append(line_number)
    results = [r for r in records if r.get("id", {}).get("testResult", {}).get("label") == LABEL]
    summaries = [r for r in records if r.get("id", {}).get("testSummary", {}).get("label") == LABEL]
    summary = summaries[0].get("testSummary", {}) if len(summaries) == 1 else {}
    status = summary.get("overallStatus")
    result = results[0].get("testResult", {}) if len(results) == 1 else {}
    passed = (not errors and len(results) == 1 and len(summaries) == 1 and status == "PASSED"
              and result.get("status") == "PASSED" and not result.get("cachedLocally", False)
              and not result.get("executionInfo", {}).get("cachedRemotely", False)
              and summary.get("totalRunCount") == 1 and summary.get("runCount") == 1
              and summary.get("attemptCount") == 1 and not summary.get("totalNumCached", 0))
    return {"test_results": results, "test_summaries": summaries, "malformed_lines": errors,
            "one_uncached_pass": passed, "overall_status": status}


def command(root, out, case, owner=None):
    argv = [sys.executable, str(root / ".github/scripts/run_bazel_with_buildbuddy.py"),
            "--nosystem_rc", "--nohome_rc", "--output_base=" + os.environ["BAZEL_OUTPUT_BASE"],
            "test", "--config=ci-linux", "--host_platform=//:local_linux", "--platforms=//:local_linux",
            "--announce_rc", "--lockfile_mode=error", "--nocache_test_results", "--runs_per_test=1",
            "--flaky_test_attempts=1", "--test_output=all", "--test_env=RUST_BACKTRACE=1",
            "--test_arg=--nocapture", "--build_event_json_file=" + str(out / "bep.json")]
    if owner:
        argv.append("--test_env=A32_WINE_DIAGNOSTIC_OWNER=" + owner)
    if case in CASES:
        argv += ["--test_arg=--exact", "--test_arg=" + case, "--test_arg=--test-threads=1"]
    return [*argv, "--", LABEL]


def system_snapshot(out):
    for name, argv in (("processes", ["ps", "-eo", "pid,ppid,stat,etime,comm"]),
                       ("disk", ["df", "-h"]), ("memory", ["free", "-m"])):
        with (out / (name + ".log")).open("wb") as log:
            subprocess.run(argv, stdout=log, stderr=subprocess.STDOUT, check=False)


def preserve_logs(root, out, started):
    directory = root / "bazel-testlogs/bazel/rules/testing/wine/wine-test-support-unit-tests"
    logfile = directory / "test.log"
    require(logfile.is_file(), "no test.log: test did not run or log unavailable")
    require(logfile.stat().st_mtime_ns >= started, "stale test.log from earlier invocation")
    location = directory.resolve()
    require(location.is_relative_to(Path(os.environ["BAZEL_OUTPUT_BASE"]).resolve()),
            "test.log outside declared output base")
    shutil.copytree(location, out / "testlogs", dirs_exist_ok=True)
    return (out / "testlogs/test.log").read_text(errors="replace")


def process_identity(pid):
    text = Path(f"/proc/{pid}/stat").read_text()
    fields = text.rsplit(")", 1)[1].split()
    return {"pid": int(pid), "state": fields[0], "ppid": int(fields[1]),
            "process_group": int(fields[2]), "session": int(fields[3]), "start_ticks": fields[19]}


def observe_processes(out, ownership):
    """Observe only; never signal processes, restore sources, or kill by PID/name."""
    live, uncertain = [], []
    owners = {b"A32_WINE_DIAGNOSTIC_OWNER=" + owner.encode() for owner in ownership["markers"]}
    server_pid_file = Path(os.environ["BAZEL_OUTPUT_BASE"]) / "server/server.pid.txt"
    try:
        server_pid = int(server_pid_file.read_text().strip()) if server_pid_file.exists() else None
    except (OSError, ValueError):
        server_pid = None
        uncertain.append("unreadable Bazel server PID identity")
    controller = ownership.get("controller", {})
    clients = ownership.get("clients", [])
    roots = ownership.get("execution_roots", [])
    server_identity = None
    if server_pid is not None:
        try:
            argument = ("--output_base=" + os.environ["BAZEL_OUTPUT_BASE"]).encode()
            if argument in Path(f"/proc/{server_pid}/cmdline").read_bytes().split(b"\0"):
                server_identity = process_identity(server_pid)
            else:
                uncertain.append("server PID does not identify the declared output base")
        except FileNotFoundError:
            pass
        except OSError as error:
            uncertain.append("cannot verify server identity: " + str(error))
    for proc in Path("/proc").iterdir():
        if not proc.name.isdecimal() or int(proc.name) == os.getpid():
            continue
        try:
            if proc.stat().st_uid != os.getuid():
                continue
            identity = process_identity(proc.name)
            if identity["state"] == "Z":
                continue
            tagged = bool(owners.intersection((proc / "environ").read_bytes().split(b"\0")))
            controller_live = (identity["pid"] == controller.get("pid")
                               and identity["start_ticks"] == controller.get("start_ticks"))
            executable = os.readlink(proc / "exe").removesuffix(" (deleted)")
            owned_executable = any(executable.startswith(root + "/") for root in roots)
            owned_session = any(identity["session"] == client["session"]
                                and int(identity["start_ticks"]) >= int(client["start_ticks"])
                                for client in clients)
            owned_ancestry = False
            ancestor = identity
            for _ in range(64):
                parent = ancestor["ppid"]
                if parent <= 1:
                    break
                try:
                    ancestor = process_identity(parent)
                except FileNotFoundError:
                    if proc.exists():
                        uncertain.append({"pid": proc.name, "error": "ancestor disappeared while process remained"})
                    break
                if (server_identity and ancestor["pid"] == server_identity["pid"]
                        and ancestor["start_ticks"] == server_identity["start_ticks"]):
                    owned_ancestry = True
                    break
                if any(ancestor["pid"] == client["pid"] and ancestor["start_ticks"] == client["start_ticks"]
                       for client in clients):
                    owned_ancestry = True
                    break
            writers = []
            for fd in (proc / "fd").iterdir():
                try:
                    target = os.readlink(fd).removesuffix(" (deleted)")
                    if target.startswith(str(out) + "/"):
                        info = (proc / "fdinfo" / fd.name).read_text()
                        flags = int(re.search(r"(?m)^flags:\s+(\d+)$", info).group(1), 8)
                        if flags & os.O_ACCMODE:
                            writers.append(target)
                except FileNotFoundError:
                    pass
            # A settled Bazel server is permitted only with the exact output-base argument
            # and PID-file identity, and no still-open evidence writer.
            server = (server_identity is not None and identity["pid"] == server_identity["pid"]
                      and identity["start_ticks"] == server_identity["start_ticks"])
            if writers or controller_live or ((tagged or owned_executable or owned_session or owned_ancestry) and not server):
                live.append({**identity, "owned_marker": tagged, "controller": controller_live,
                             "owned_executable": owned_executable, "owned_session": owned_session,
                             "owned_ancestry": owned_ancestry, "executable": executable,
                             "evidence_writers": writers})
        except FileNotFoundError:
            try:
                if process_identity(proc.name)["state"] != "Z":
                    uncertain.append({"pid": proc.name, "error": "incomplete observation of still-live process"})
            except FileNotFoundError:
                pass  # The observed process exited, rather than an attribution read failing.
        except (OSError, ValueError, AttributeError) as error:
            uncertain.append({"pid": proc.name, "error": str(error)})
    return {"live_owned_processes_or_writers": live, "uncertain": uncertain,
            "bazel_server_pid_from_output_base": server_pid, "verified_server_identity": server_identity,
            "execution_roots": roots, "settled": not live and not uncertain}


def quiescence(out):
    ownership_file = out / "ownership.json"
    if not ownership_file.exists():
        return {"settled": False, "reason": "ownership record unavailable"}
    ownership = json.loads(ownership_file.read_text())
    history, consecutive = [], 0
    # At most ~2 seconds of observation after Bazel returns; no test deadline changes.
    for _ in range(8):
        try:
            observation = observe_processes(out, ownership)
        except Exception:
            observation = {"settled": False, "uncertain": traceback.format_exc()}
        history.append(observation)
        consecutive = consecutive + 1 if observation["settled"] else 0
        if consecutive == 2:
            break
        time.sleep(0.25)
    return {"settled": consecutive == 2, "observations": history}


def run_all(root, out):
    environment_guard()
    version = subprocess.check_output(["bazel", "--version"], text=True).strip()
    require(version == "bazel 9.3.0", "wrong Bazel version: " + version)
    save(out / "bazel-version.json", {"version": version, "executable": shutil.which("bazel")})
    names = expected_tests(root)
    roots = [str(Path(os.environ[key]).resolve()) for key in
             ("BAZEL_OUTPUT_BASE", "BAZEL_OUTPUT_USER_ROOT", "BAZEL_REPO_CONTENTS_CACHE", "BAZEL_REPOSITORY_CACHE")
             if os.environ.get(key)]
    require(all(len(Path(root).parts) >= 3 for root in roots), "execution root is not narrowly scoped")
    ownership = {"controller": process_identity(os.getpid()), "markers": [], "clients": [], "execution_roots": roots}
    save(out / "ownership.json", ownership)
    all_passed, blocked = True, None
    for index, case in enumerate(PLAN):
        directory = out / (str(index) + "-" + case.replace("::", "-"))
        directory.mkdir(parents=True, exist_ok=True)
        record = {"case": case, "state": "running", "started_ns": time.time_ns(),
                  "original_internal_parallelism": index == 0, "passed": False}
        if blocked:
            record.update(state="blocked", reason=blocked)
            save(directory / "result.json", record)
            all_passed = False
            continue
        save(directory / "result.json", record)
        try:
            save(directory / "guard-before.json", guard(root, os.environ["SOURCE_SHA"]))
        except Exception:
            blocked = {"source_integrity": traceback.format_exc()}
        if not blocked:
            owner = uuid.uuid4().hex
            ownership["markers"].append(owner)
            save(out / "ownership.json", ownership)
            argv = command(root, directory, case, owner)
            record.update(command=argv, ownership_marker=owner)
            save(directory / "result.json", record)
            try:
                with (directory / "console.log").open("wb") as log:
                    with subprocess.Popen(argv, cwd=root, stdout=log, stderr=subprocess.STDOUT,
                                          start_new_session=True,
                                          env={**os.environ, "A32_WINE_DIAGNOSTIC_OWNER": owner}) as process:
                        record["client"] = process_identity(process.pid)
                        ownership["clients"].append(record["client"])
                        save(out / "ownership.json", ownership)
                        save(directory / "result.json", record)
                        record["exit_code"] = process.wait()
                record["bep"] = parse_bep(directory / "bep.json")
            except Exception:
                record["error"] = traceback.format_exc()
            record["quiescence"] = quiescence(out)
            save(directory / "quiescence.json", record["quiescence"])
            if not record["quiescence"]["settled"]:
                blocked = {"unsettled_processes_or_writers": record["quiescence"]}
            try:
                text = preserve_logs(root, directory, record["started_ns"])
                record["libtest"] = parse_test_log(text, names if index == 0 else {case})
            except Exception:
                # Never overwrite an unpreserved previous attempt's raw log with another run.
                blocked = {"evidence_preservation": traceback.format_exc()}
            record["passed"] = (not blocked and record.get("exit_code") == 0
                                and record.get("bep", {}).get("one_uncached_pass", False)
                                and record.get("libtest", {}).get("count_and_name_guard_passed", False))
        try:
            save(directory / "guard-after.json", guard(root, os.environ["SOURCE_SHA"]))
        except Exception:
            blocked = {"source_integrity": traceback.format_exc()}
            record["passed"] = False
        if blocked:
            record["block_latched"] = blocked
        record["state"] = "completed"
        record["finished_ns"] = time.time_ns()
        if not record["passed"]:
            system_snapshot(directory)
        all_passed &= record["passed"]
        save(directory / "result.json", record)
        print(json.dumps(record), flush=True)
    return 0 if all_passed else 1


def collect(root, out):
    report = {"base": BASE, "base_tree": BASE_TREE, "branch": BRANCH,
              "step_results": json.loads(os.environ.get("STEP_RESULTS", "{}")), "attempts": []}
    report["final_quiescence"] = quiescence(out)
    try:
        report["final_guard"] = guard(root, os.environ["SOURCE_SHA"])
    except Exception:
        report["integrity_error"] = traceback.format_exc()
    for index, case in enumerate(PLAN):
        path = out / (str(index) + "-" + case.replace("::", "-")) / "result.json"
        record = json.loads(path.read_text()) if path.exists() else {"case": case, "state": "not-run", "passed": False}
        if record["state"] == "running":
            record["state"] = "interrupted"
            record["passed"] = False
            record["bep"] = parse_bep(path.parent / "bep.json")
            try:
                preserve_logs(root, path.parent, record["started_ns"])
            except Exception:
                record["log_error"] = traceback.format_exc()
            save(path, record)
        report["attempts"].append(record)
    report["passed"] = ("integrity_error" not in report and report["final_quiescence"]["settled"]
                        and all(r["passed"] for r in report["attempts"]))
    report["interpretation"] = "Diagnostic only; isolated/warm passes do not fix or replace original parallel-suite failure."
    save(out / "summary.json", report)
    # A separate immutable snapshot prevents a surviving orchestration writer from
    # mutating the uploaded bytes after hashing. Unsettled inputs are clearly partial.
    frozen = out.with_name("a32-wine-frozen")
    require(not frozen.exists(), "refuse to overwrite an earlier frozen artifact")
    frozen.mkdir()
    snapshots = {}
    for path in sorted(out.rglob("*")):
        relative = str(path.relative_to(out))
        try:
            if not path.is_file():
                continue
            before = path.stat()
            with path.open("rb") as source:
                data = source.read(before.st_size)  # Fixed prefix, even if the source keeps growing.
            after = path.stat()
            destination = frozen / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(data)
            stable = ((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
                      == (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
                      and len(data) == before.st_size)
            snapshots[relative] = {"snapshot_bytes": len(data), "source_stable_during_copy": stable,
                                   "source_size_before": before.st_size, "source_size_after": after.st_size}
        except OSError:
            # An interrupted controller can rename/unlink a .tmp while we seal evidence.
            # Keep the remaining snapshots and hash manifest; never claim completeness.
            snapshots[relative] = {"source_stable_during_copy": False,
                                   "snapshot_error": traceback.format_exc()}
    report["passed"] &= all(s["source_stable_during_copy"] for s in snapshots.values())
    report["evidence_state"] = ("partial-unsettled" if not report["final_quiescence"]["settled"] else
                                "settled" if all(s["source_stable_during_copy"] for s in snapshots.values()) else
                                "partial-changing-or-unavailable")
    save(frozen / "summary.json", report)
    save(frozen / "snapshot-metadata.json", snapshots)
    hashes = {str(p.relative_to(frozen)): {"sha256": sha256(p.read_bytes()), "bytes": p.stat().st_size}
              for p in sorted(frozen.rglob("*")) if p.is_file()}
    save(frozen / "artifact-hashes.json", hashes)
    print(json.dumps(report, indent=2))
    return 0 if report["passed"] else 1


def main():
    action, destination = sys.argv[1:]
    root = Path(os.environ.get("GITHUB_WORKSPACE", ".")).resolve()
    out = Path(destination).resolve()
    require(not out.is_relative_to(root), "evidence must be outside checkout")
    out.mkdir(parents=True, exist_ok=True)
    if action == "init":
        environment_guard()
        save(out / "input.json", guard(root, os.environ["SOURCE_SHA"]))
        (out / "input.patch").write_bytes(git(root, "diff", "--binary", BASE, "HEAD"))
        save(out / "plan.json", {"order": PLAN, "target": LABEL, "expected_full_count": 13,
             "expected_isolated_count": 1, "per_test_deadlines": "unchanged a32",
             "bazel_target_timeout": "unchanged short", "retries": 0})
        return 0
    if action == "dotslash":
        bootstrap(out)
        return 0
    if action == "run":
        return run_all(root, out)
    if action == "collect":
        return collect(root, out)
    raise ValueError("unknown action: " + action)


if __name__ == "__main__":
    sys.exit(main())
