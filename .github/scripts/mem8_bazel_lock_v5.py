"""One exact-source Bazel module-lock check; no native project test or model call."""
import argparse
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tarfile
import traceback

HEAD = "9bd2f589debdba4a93baa363817c3669cb103721"
TREE = "c77785ecb368c44ea699769001a47402c9f50591"
BASE = "2ae5215beaf8d7b7df111a090b82134beae2683d"
BASE_TREE = "12159640adcf073b51f3837e75575e11f5c20233"
EXEC_BLOB = "c9434b3a4afb31f80e323d543936386a2fa738de"
LOCKS = {
    "codex-rs/Cargo.lock": "98b3767c6e74bf6eeb5894db760259dbc400cbfd0685af8ad915c92d25408d69",
    "MODULE.bazel.lock": "783b3ad329fa53bd4a0e48be6907d38259fa2880d61bd1994b863d7f78bbca57",
}


def now():
    return datetime.now(timezone.utc).isoformat()


def info(data):
    return {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
            "git_blob": hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()}


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def main():
    parser = argparse.ArgumentParser()
    for key in ("source", "output", "cache-root", "expected-head", "expected-tree", "base"):
        parser.add_argument("--" + key, required=True)
    parser.add_argument("--timeout-seconds", type=int, required=True)
    args = parser.parse_args()
    if (args.expected_head, args.expected_tree, args.base, args.timeout_seconds) != (HEAD, TREE, BASE, 1200):
        raise RuntimeError("unexpected exact source or lock-command budget")
    workspace = Path(os.environ["GITHUB_WORKSPACE"]).resolve()
    temporary = Path(os.environ["RUNNER_TEMP"]).resolve()
    source, output, cache = (Path(value).resolve() for value in (args.source, args.output, args.cache_root))
    if (source, output, cache) != (workspace / "source", temporary / "mem8-bazel-lock-v5", temporary / "mem8-bazel-lock-v5-caches"):
        raise RuntimeError("unexpected isolated source, evidence or cache root")
    output.mkdir(mode=0o700)
    records = output / "records"
    records.mkdir(mode=0o700)
    tools_dir = output / "bin"
    tools_dir.mkdir(mode=0o700)
    environment = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", GIT_TERMINAL_PROMPT="0", GIT_OPTIONAL_LOCKS="0",
                       RUSTUP_TOOLCHAIN="1.96.0", CODEX_REPO_ROOT=str(source),
                       BAZELISK_HOME=str(cache / "bazelisk"), USE_BAZEL_VERSION="9.3.0",
                       SOURCE_SHA=HEAD, TESTED_SHA=HEAD, BASE_SHA=BASE, HEPTA_CI_LANE="source-head")
    for key in list(environment):
        if key.startswith(("GIT_TRACE", "HEPTA_LOCAL_PROVIDER_", "HEPTA_MEM_CONTEXT_", "HEPTA_MEM_NATIVE_")) or key in {"GIT_CURL_VERBOSE", "CARGO_BIN_EXE_codex"}:
            environment.pop(key)
    started = now()
    result = {"schema": "hepta.mem8.bazel-lock-ci.v5", "status": "failed", "started_at": started,
              "source_head": HEAD, "source_tree": TREE, "base": BASE, "source_refs_modified": False,
              "lock_command_budget_seconds": 1200, "maximum_lock_command_phases": 1,
              "lock_command_phases_started": 0, "native_project_tests_executed": 0,
              "model_requests_executed": 0, "automatic_retries": 0, "donor_used": False,
              "execution_host": "github-hosted ubuntu-24.04", "failure": None}

    def save(name, value):
        write(records / name, (json.dumps(value, indent=2, sort_keys=True) + "\n").encode())

    def git(*argv):
        return subprocess.check_output(["git", "--no-replace-objects", *argv], cwd=source, env=environment, timeout=30)

    def identity():
        return {"head": git("rev-parse", "HEAD").decode().strip(),
                "tree": git("rev-parse", "HEAD^{tree}").decode().strip(),
                "status": git("status", "--porcelain=v1", "--untracked-files=all").decode()}

    def observe_files(label, paths):
        rows = []
        for name in paths:
            path = source / name
            if path.is_symlink() or not path.is_file() or path.stat().st_nlink != 1:
                raise RuntimeError("unexpected source file kind: " + name)
            data = path.read_bytes()
            write(records / label / name, data)
            rows.append({"path": name, **info(data)})
        save(label + ".json", rows)
        return rows

    def bounded_read(label, argv):
        raw = records / (label + ".raw.log")
        begin, timed_out, cleanup = now(), False, None
        with raw.open("xb") as stream:
            child = subprocess.Popen(argv, cwd=source, env=environment, stdout=stream,
                                     stderr=subprocess.STDOUT, start_new_session=True)
            try:
                code = child.wait(timeout=30)
            except subprocess.TimeoutExpired:
                timed_out = True
                try:
                    os.killpg(child.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                code = child.wait(timeout=5)
                cleanup = {"owned_pgid": child.pid, "signal": "SIGKILL", "reaped_exit": code}
            stream.flush()
            os.fsync(stream.fileno())
        data = raw.read_bytes()
        save(label + ".json", {"argv": argv, "started_at": begin, "finished_at": now(),
             "exit_code": code, "timed_out": timed_out, "cleanup": cleanup, **info(data)})
        if timed_out or code:
            raise RuntimeError("bounded tool observation failed: " + label)
        return data

    try:
        write(records / "DRIVER.py", Path(__file__).read_bytes())
        before = identity()
        result["source_before"] = before
        if before != {"head": HEAD, "tree": TREE, "status": ""}:
            raise RuntimeError("source is not the exact clean formatted candidate")
        if git("rev-parse", BASE + "^{tree}").decode().strip() != BASE_TREE:
            raise RuntimeError("comparison base tree differs")
        write(records / "SOURCE_TREE.ls-tree", git("ls-tree", "-r", "-z", HEAD))
        write(records / "BASE_TREE.ls-tree", git("ls-tree", "-r", "-z", BASE))
        executable = source / "scripts/hepta_ci_exec.py"
        if info(executable.read_bytes())["git_blob"] != EXEC_BLOB:
            raise RuntimeError("strict source receipt wrapper changed")
        write(records / "hepta_ci_exec.py", executable.read_bytes())
        if (source / ".bazelversion").read_bytes() != b"9.3.0\n":
            raise RuntimeError("unexpected repository Bazel version")
        locks_before = observe_files("locks-before", LOCKS)
        for lock in locks_before:
            if lock["sha256"] != LOCKS[lock["path"]]:
                raise RuntimeError("initial lock bytes differ")
        for name in ("justfile", ".bazelrc", ".bazelversion", "MODULE.bazel"):
            write(records / "source-config" / name, (source / name).read_bytes())
        tool_pins = {}
        for name in ("just", "bazel", "rustc", "cargo", "python3"):
            resolved = shutil.which(name, path=environment["PATH"])
            if not resolved:
                raise RuntimeError("required tool absent: " + name)
            path = Path(resolved).resolve()
            if name in {"rustc", "cargo"}:
                resolved_tool = bounded_read(name + "-physical-path", ["rustup", "which", "--toolchain", "1.96.0", name])
                path = Path(resolved_tool.decode().strip()).resolve()
            tool_pins[name] = {"invoked_path": resolved, "physical_path": str(path), **info(path.read_bytes())}
        save("TOOLS_BEFORE.json", tool_pins)
        if bounded_read("just-version", [tool_pins["just"]["physical_path"], "--version"]).strip() != b"just 1.51.0":
            raise RuntimeError("just version differs")
        for name in ("rustc", "cargo"):
            version = bounded_read(name + "-version", [tool_pins[name]["physical_path"], "--version"]).strip()
            if not version.startswith((name + " 1.96.0 ").encode()):
                raise RuntimeError("Rust toolchain version differs: " + name)
        bounded_read("python-version", [tool_pins["python3"]["physical_path"], "--version"])
        real_bazel = tool_pins["bazel"]["physical_path"]
        if bounded_read("bazel-version", [real_bazel, "--version"]).strip() != b"bazel 9.3.0":
            raise RuntimeError("Bazel version differs")
        downloaded = []
        for path in sorted((cache / "bazelisk").rglob("bazel")):
            if path.is_file() and not path.is_symlink():
                downloaded.append({"path": str(path), **info(path.read_bytes())})
        if not downloaded:
            raise RuntimeError("actual Bazel binary was not observed in the owned cache")
        save("OWNED_BAZELISK_BINARY_INVENTORY.json", {"scope": "only this run cache", "files": downloaded,
             "label": "Observed cache files, distinct from PATH Bazelisk launcher; no inherited desktop binary identity"})
        wrapper = "#!/usr/bin/env python3\nimport os,sys\nreal=" + repr(real_bazel) + "\n" + \
            "os.execv(real,[real,'--batch','--noexperimental_remote_repo_contents_cache'," + \
            repr("--output_base=" + str(cache / "output-base")) + ",*sys.argv[1:]," + \
            repr("--repo_contents_cache=" + str(cache / "repo-contents")) + "," + \
            repr("--repository_cache=" + str(cache / "repository")) + "])\n"
        launcher = tools_dir / "bazel"
        write(launcher, wrapper.encode())
        launcher.chmod(0o700)
        environment["PATH"] = str(tools_dir) + os.pathsep + environment["PATH"]
        write(records / "bazel-wrapper.py", wrapper.encode())
        save("CACHE_ISOLATION.json", {"cache_root": str(cache), "output_base": str(cache / "output-base"),
             "repository_cache": str(cache / "repository"), "repo_contents_cache": str(cache / "repo-contents"),
             "bazelisk_home": str(cache / "bazelisk"), "remote_repo_contents_cache": False,
             "shared_cache_restore_or_mutation": False, "wrapper": info(wrapper.encode())})
        if identity() != before:
            raise RuntimeError("preflight changed source")
        phase_record = records / "lock-generate.json"
        argv = [sys.executable, "-B", str(executable), "--output", str(phase_record),
                "--minimum-tests", "0", "--timeout-seconds", "1200", "--",
                tool_pins["just"]["physical_path"], "bazel-lock-update"]
        result["lock_command_phases_started"] = 1
        save("LOCK_COMMAND_START.json", {"argv": argv, "started_at": now(), "source_before": before,
             "source_sha": HEAD, "tree": TREE, "lane": "source-head", "budget_seconds": 1200,
             "workflow_commit": os.environ["GITHUB_SHA"], "workflow_run": os.environ["GITHUB_RUN_ID"],
             "workflow_attempt": os.environ["GITHUB_RUN_ATTEMPT"]})
        # The existing wrapper owns the original 1200s process-group timer.
        # A second subprocess timeout would risk orphaning that owned group.
        with (records / "lock-generate.wrapper.stdout").open("xb") as stdout, (records / "lock-generate.wrapper.stderr").open("xb") as stderr:
            process = subprocess.run(argv, cwd=source, env=environment, stdout=stdout, stderr=stderr)
        result["wrapper_exit_code"] = process.returncode
        receipt = json.loads(phase_record.read_bytes())
        result["phase_receipt"] = receipt
        result["source_after"] = identity()
        locks_after = observe_files("locks-after", LOCKS)
        write(records / "source-after.patch", git("diff", "--binary", "HEAD"))
        write(records / "source-after-status.txt", result["source_after"]["status"].encode())
        changed = git("diff", "--name-only", "HEAD").decode().splitlines()
        result["changed_paths"] = changed
        result["lock_changed"] = locks_after != locks_before
        if receipt.get("log_file"):
            raw_path = records / receipt["log_file"]
            if raw_path.parent != records or not raw_path.is_file():
                raise RuntimeError("strict receipt raw log missing")
            raw = raw_path.read_bytes()
            if (len(raw), hashlib.sha256(raw).hexdigest()) != (receipt.get("log_bytes"), receipt.get("log_sha256")):
                raise RuntimeError("strict receipt raw bytes differ")
        after_tools = {name: {**row, **info(Path(row["physical_path"]).read_bytes())} for name, row in tool_pins.items()}
        save("TOOLS_AFTER.json", after_tools)
        if after_tools != tool_pins:
            raise RuntimeError("tool bytes changed")
        downloaded_after = []
        for row in downloaded:
            path = Path(row["path"])
            if path.is_symlink() or not path.is_file():
                raise RuntimeError("actual Bazel binary no longer a regular file")
            downloaded_after.append({"path": str(path), **info(path.read_bytes())})
        save("OWNED_BAZELISK_BINARY_INVENTORY_AFTER.json", {"files": downloaded_after})
        if downloaded_after != downloaded:
            raise RuntimeError("actual Bazel binary bytes changed")
        if (receipt.get("source_sha"), receipt.get("tested_sha"), receipt.get("lane")) != (HEAD, HEAD, "source-head"):
            raise RuntimeError("strict receipt source binding differs")
        if any(receipt.get(key) for key in ("timed_out", "output_limit_exceeded")) or receipt.get("command_exit_code") != 0:
            raise RuntimeError("actual original lock command failed")
        if result["source_after"] != before or locks_after != locks_before:
            result["review_required"] = True
            result["review_reason"] = "Original command may have generated a new lock; strict dirty failure is preserved. No automatic commit, reset or second phase."
            raise RuntimeError("source or lock rewrite requires a distinct reviewed candidate")
        if process.returncode != 0 or receipt.get("status") != "passed" or receipt.get("exit_code") != 0:
            raise RuntimeError("original strict exact-source gate did not pass")
        result["status"] = "passed_exact_source_bazel_lock_only"
    except Exception:
        result["failure"] = traceback.format_exc()
        write(records / "DRIVER_FAILURE.txt", result["failure"].encode())
    finally:
        result["finished_at"] = now()
        save("RESULT.json", result)
        print(json.dumps(result), flush=True)
        inventory = []
        for path in sorted(records.rglob("*")):
            if path.is_symlink():
                raise RuntimeError("unsafe evidence member")
            if path.is_file():
                inventory.append({"path": path.relative_to(records).as_posix(), **info(path.read_bytes())})
        save("FILE_MANIFEST.json", {"members": inventory})
        archive = output / "mem8-bazel-lock-v5-records.tar.xz"
        with archive.open("xb") as stream:
            with tarfile.open(fileobj=stream, mode="w:xz", preset=6) as tar:
                for path in sorted(records.rglob("*")):
                    if path.is_file():
                        data = path.read_bytes()
                        member = tarfile.TarInfo(path.relative_to(records).as_posix())
                        member.size, member.mode, member.mtime = len(data), 0o600, 0
                        tar.addfile(member, io.BytesIO(data))
            stream.flush()
            os.fsync(stream.fileno())
        write(output / "ARCHIVE_INFO.json", (json.dumps({"path": archive.name, "members": len(inventory) + 1, **info(archive.read_bytes())}, indent=2) + "\n").encode())
    return 0 if result["status"] == "passed_exact_source_bazel_lock_only" else 1


if __name__ == "__main__":
    sys.exit(main())
