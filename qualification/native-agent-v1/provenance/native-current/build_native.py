"""Build the qualification runner against the current owner native library.

The caller supplies an isolated source worktree and one exact runtime revision.
This script never changes a lockfile, downloads a toolchain, or runs a model.
Failed command evidence is preserved in the original fresh output directory.
"""

import argparse
from contextlib import ExitStack
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time
import tomllib

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "production-qualification"))
from native_build_evidence import (POLICY_VERSION, PROJECTION_VERSION, RUNNER,
    digest, object_digest, source_snapshot, patch_configuration)


def save(path, value):
    with Path(path).open("x") as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write("\n")


class BuildCancelled(RuntimeError):
    pass


def cancel_build(signum, _frame):
    raise BuildCancelled(f"build interrupted by signal {signum}")


def bounded_command(argv, cwd, env, log, timeout, stderr_path=None):
    result = {"argv": argv, "cwd": str(cwd), "started_ns": time.time_ns()}
    cancellation = {"signal": None}
    previous = {}
    child = None
    def requested(signum, _frame):
        cancellation["signal"] = signum
    with ExitStack() as stack:
        stream = stack.enter_context(log.open("xb"))
        errors = stack.enter_context(stderr_path.open("xb")) if stderr_path else subprocess.STDOUT
        try:
            for signum in (signal.SIGINT, signal.SIGTERM):
                previous[signum] = signal.signal(signum, requested)
            child = subprocess.Popen(argv, cwd=cwd, env=env, stdout=stream,
                stderr=errors, start_new_session=True)
            result["pid"] = child.pid
            deadline = time.monotonic() + timeout
            while True:
                if cancellation["signal"]:
                    result["cancelled_signal"] = cancellation["signal"]
                    raise BuildCancelled("original Cargo command was cancelled")
                # WNOWAIT keeps the original leader PID allocated until all
                # group signals are complete; no reaped PGID is later reused.
                observed = os.waitid(os.P_PID, child.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT)
                if observed is not None:
                    result["exit_code"] = child.wait()
                    break
                if time.monotonic() >= deadline:
                    result["timed_out"] = True
                    raise subprocess.TimeoutExpired(argv, timeout)
                time.sleep(0.05)
        except BaseException as error:
            result["error"] = str(error)
            result["exit_code"] = None
            if child is not None:
                cleanup = {"scope": "original process group", "leader_pid": child.pid,
                    "leader_reaped": False, "descendant_reap": "not observable by this parent"}
                result["cleanup"] = cleanup
                try:
                    for signum in (signal.SIGTERM, signal.SIGKILL):
                        try:
                            os.killpg(child.pid, signum)
                            cleanup[signal.Signals(signum).name] = "sent"
                        except ProcessLookupError:
                            cleanup[signal.Signals(signum).name] = "group_absent"
                        if signum == signal.SIGTERM:
                            time.sleep(0.5)
                    result["exit_code"] = child.wait(timeout=10)
                    cleanup["leader_reaped"] = True
                except BaseException as cleanup_error:
                    cleanup["error"] = str(cleanup_error)
                    cleanup["state"] = "unknown; preserve this original PID evidence, do not restart automatically"
        finally:
            for signum, handler in previous.items():
                signal.signal(signum, handler)
            result["finished_ns"] = time.time_ns()
    result["log_sha256"] = digest(log)
    return result


def main():
    parser = argparse.ArgumentParser()
    for name in ("source", "output", "target-dir"):
        parser.add_argument("--" + name, type=lambda value: Path(value).resolve(), required=True)
    parser.add_argument("--runtime-rev", required=True)
    parser.add_argument("--runtime-source", type=lambda value: Path(value).resolve())
    parser.add_argument("--cargo-config", type=lambda value: Path(value).resolve())
    parser.add_argument("--profile", choices=("dev", "release"), default="dev")
    parser.add_argument("--jobs", type=int, default=3)
    parser.add_argument("--build-timeout", type=int, default=3600)
    parser.add_argument("--offline", action="store_true")
    args = parser.parse_args()
    if not 1 <= args.jobs <= 8 or not 1 <= args.build_timeout <= 7200:
        raise ValueError("bounded build jobs and timeout required")
    for tree in (args.source, args.runtime_source):
        if tree and (args.output.is_relative_to(tree) or args.target_dir.is_relative_to(tree)):
            raise ValueError("build evidence and generated target files must be outside both source worktrees")
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output / "bin").mkdir()
    toolchain = tomllib.loads((args.source / "codex-rs/rust-toolchain.toml").read_text())["toolchain"]["channel"]
    manifest = args.source / RUNNER / "Cargo.toml"
    environment = dict(os.environ, CARGO_TARGET_DIR=str(args.target_dir),
        CARGO_INCREMENTAL="0", CARGO_PROFILE_DEV_DEBUG="0")
    record = {"schema": "hepta.native-build.v1", "source": str(args.source),
        "runtime_revision": args.runtime_rev, "runtime_source": str(args.runtime_source) if args.runtime_source else None,
        "cargo_config": str(args.cargo_config) if args.cargo_config else None,
        "profile": args.profile, "toolchain": toolchain,
        "context_policy_version": POLICY_VERSION, "request_projection_version": PROJECTION_VERSION,
        "runtime_variant": "explicit local path patch; base commit plus complete dirty/source inventory" if args.runtime_source else "pinned original git checkout",
        "started_ns": time.time_ns(), "build_succeeded": False,
        "scope": "Current owner native-agent path library in the isolated qualification SessionOwner; this build alone does not establish production owner parity."}
    save(args.output / "BUILD_STARTED.json", record)
    cargo = ["cargo", "+" + toolchain]
    if args.cargo_config: cargo += ["--config", str(args.cargo_config)]
    locked = ["--locked"] + (["--offline"] if args.offline else [])
    try:
        record["rustc"] = subprocess.check_output(["rustup", "run", toolchain, "rustc", "-vV"], timeout=30, text=True)
        record["cargo"] = subprocess.check_output(cargo + ["--version"], timeout=30, text=True)
        patch = patch_configuration(args.cargo_config, args.runtime_source)
        if patch:
            shutil.copyfile(args.cargo_config, args.output / "runtime-patch.toml")
        graphs = {}
        record["metadata_commands"] = {}
        for label, graph_manifest in (("runner", manifest), ("owner", args.source / "codex-rs/Cargo.toml")):
            argv = cargo + ["metadata", "--format-version", "1", "--manifest-path", str(graph_manifest)] + locked
            output = args.output / (label + "-cargo-metadata.json")
            command = bounded_command(argv, graph_manifest.parent, environment, output, 180,
                stderr_path=args.output / (label + "-metadata.log"))
            record["metadata_commands"][label] = command
            if command["exit_code"] != 0 or command.get("timed_out") or command.get("cancelled_signal") or command.get("error"):
                raise RuntimeError(label + " locked metadata failed; inspect its original metadata.log")
            graphs[label] = json.loads(output.read_bytes())
        metadata = {"schema": "hepta.native-resolved-graphs.v1", "graphs": graphs}
        shutil.copyfile(Path(__file__), args.output / "build_native.py")
        shutil.copyfile(Path(sys.modules["native_build_evidence"].__file__), args.output / "native_build_evidence.py")
        save(args.output / "cargo-metadata.json", metadata)
        before = source_snapshot(args.source, metadata, args.runtime_rev, args.runtime_source, args.cargo_config)
        save(args.output / "source-before.json", before)
        record["source_commit"] = before["source_commit"]
        record["source_tree_sha256"] = object_digest(before)
        environment.update(HEPTA_QUALIFICATION_SOURCE_SHA256=record["source_tree_sha256"],
            HEPTA_QUALIFICATION_RUNTIME_REV=args.runtime_rev)
        record["environment_overrides"] = {key: environment[key] for key in (
            "CARGO_TARGET_DIR", "CARGO_INCREMENTAL", "CARGO_PROFILE_DEV_DEBUG",
            "HEPTA_QUALIFICATION_SOURCE_SHA256", "HEPTA_QUALIFICATION_RUNTIME_REV")}
        record["inherited_build_flags"] = {key: os.environ.get(key) for key in (
            "RUSTFLAGS", "CARGO_ENCODED_RUSTFLAGS", "RUSTC_WRAPPER", "CARGO_BUILD_TARGET")}
        argv = cargo + ["build", "--manifest-path", str(manifest), "--profile", args.profile,
            "--jobs", str(args.jobs), "--bin", "hepta-native-qualification", "--message-format=json-render-diagnostics"] + locked
        record["command"] = bounded_command(argv, manifest.parent, environment,
            args.output / "native-build.log", args.build_timeout)
        if record["command"]["exit_code"] != 0 or record["command"].get("timed_out") or record["command"].get("cancelled_signal") or record["command"].get("error"):
            raise RuntimeError("current native build failed; inspect the original native-build.log")
        after = source_snapshot(args.source, metadata, args.runtime_rev, args.runtime_source, args.cargo_config)
        save(args.output / "source-after.json", after)
        if before != after:
            raise ValueError("local source or runtime checkout changed during compilation")
        artifacts = set()
        with (args.output / "native-build.log").open() as stream:
            for line in stream:
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if (row.get("reason") == "compiler-artifact" and row.get("target", {}).get("name") == "hepta-native-qualification"
                        and "bin" in row.get("target", {}).get("kind", []) and row.get("executable")):
                    artifacts.add(row["executable"])
        if len(artifacts) != 1:
            raise ValueError("Cargo did not identify exactly one actual qualification binary")
        built = Path(artifacts.pop()).resolve()
        if not built.is_relative_to(args.target_dir):
            raise ValueError("Cargo artifact escaped the recorded target directory")
        executable = args.output / "bin/hepta-native-qualification"
        shutil.copy2(built, executable)
        identity = json.loads(subprocess.check_output([str(executable), "--build-identity"], timeout=15))
        expected = {"schema": "hepta.native-qualification-build-identity.v1",
            "context_policy_version": POLICY_VERSION, "request_projection_version": PROJECTION_VERSION,
            "source_tree_sha256": record["source_tree_sha256"], "runtime_revision": args.runtime_rev}
        if identity != expected:
            raise ValueError("actual binary did not report its compiled current native source identity")
        record["binary_identity"] = identity
        record["binary"] = {"sha256": digest(executable), "bytes": executable.stat().st_size,
            "cargo_artifact": str(built), "path": str(executable)}
        record["evidence_files"] = {name: digest(args.output / name) for name in (
            "build_native.py", "native_build_evidence.py", "cargo-metadata.json", "runner-cargo-metadata.json", "runner-metadata.log",
            "owner-cargo-metadata.json", "owner-metadata.log", "source-before.json", "source-after.json", "native-build.log")}
        if patch: record["evidence_files"]["runtime-patch.toml"] = digest(args.output / "runtime-patch.toml")
        record["build_succeeded"] = True
        record["finished_ns"] = time.time_ns()
        save(args.output / "NATIVE_BUILD.json", record)
        print(json.dumps({"build_succeeded": True, "source_commit": record["source_commit"],
            "runtime_revision": args.runtime_rev, "native_binary": str(executable)}), flush=True)
    except BaseException as error:
        record["finished_ns"] = time.time_ns()
        record["error"] = str(error)
        save(args.output / "BUILD_FAILED.json", record)
        raise


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, cancel_build)
    main()
