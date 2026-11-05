#!/usr/bin/env python3
# Copyright 2026 TrillionniumFoundation
# SPDX-License-Identifier: Apache-2.0
"""Create-only bounded Rust qualification; keep all failed attempts and logs."""
import argparse
import datetime
import hashlib
import json
import os
import pathlib
import resource
import shutil
import signal
import subprocess
import tempfile
import time

BASE = "990f85e46bedb8f49c0e6d0029ea6f9afbf6eac7"
CHANGED = ("Cargo.toml", "Cargo.lock", "src/mcp/mod.rs", "src/mcp/server.rs",
           "src/mcp/weight_certificate.rs", "src/mcp/weight_certificate_exact.rs",
           "src/mcp/weight_certificate_tests.rs")


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, obj):
    path.write_text(json.dumps(obj, sort_keys=True, indent=2, allow_nan=False) + "\n")


def source_manifest(root):
    names = {str(p.relative_to(root)) for p in (root / "src").rglob("*") if p.is_file()}
    names.update(str(p.relative_to(root)) for p in (root / "tests").rglob("*") if p.is_file())
    names.update(n for n in ("Cargo.toml", "Cargo.lock", "build.rs", "rustfmt.toml", "rust-toolchain.toml") if (root / n).is_file())
    return {n: {"bytes": (root / n).stat().st_size, "sha256": sha(root / n)} for n in sorted(names)}


def main(args):
    root, target, output = args.root.resolve(), args.target.resolve(), args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    if subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip() != BASE:
        raise ValueError("wrong declared source parent")
    for name in CHANGED:
        p = output / "source_snapshot" / name
        p.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(root / name, p)
    before = source_manifest(root)
    save(output / "SOURCE_MANIFEST.json", before)
    cargo = str(pathlib.Path.home() / ".cargo/bin/cargo")
    env = os.environ.copy()
    tmp = tempfile.mkdtemp(prefix="hwcert-", dir="/tmp")
    os.chmod(tmp, 0o700)
    env.update(CARGO_TARGET_DIR=str(target), CARGO_BUILD_JOBS="2", TMPDIR=tmp, RUST_BACKTRACE="1")
    commands = [
        [cargo, "fmt", "--all", "--", "--check"],
        [cargo, "test", "--locked", "--offline", "--all-features", "--lib", "weight_", "--", "--test-threads=1", "--nocapture"],
        [cargo, "clippy", "--locked", "--offline", "--all-features", "--all-targets", "--", "-D", "warnings"],
        [cargo, "test", "--locked", "--offline", "--no-default-features", "--lib", "weight_", "--", "--test-threads=1", "--nocapture"],
        [cargo, "clippy", "--locked", "--offline", "--no-default-features", "--all-targets", "--", "-D", "warnings"],
        [cargo, "build", "--locked", "--offline", "--all-features", "--bin", "hepta-runtime"],
        [cargo, "fmt", "--all", "--", "--check"],
    ]
    result = {"schema": "hepta-native-certificate-local-qualification-v1", "base_sha": BASE,
              "started_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
              "rustc_version": subprocess.check_output([str(pathlib.Path.home()/".cargo/bin/rustc"), "--version"], text=True).strip(),
              "commands": [], "all_passed": False, "complete_repository_tests_run": False,
              "scope": "Focused complete weight-library tests, both feature configurations, all-target strict Clippy, binary and format; not complete repository tests or efficacy."}
    started, self_cpu = time.monotonic(), time.process_time()
    usage = resource.getrusage(resource.RUSAGE_CHILDREN)
    try:
        for i, cmd in enumerate(commands, 1):
            log = output / f"command-{i}.log"
            start = time.monotonic()
            old = resource.getrusage(resource.RUSAGE_CHILDREN)
            timed_out = False
            with log.open("xb") as stream:
                p = subprocess.Popen(cmd, cwd=root, env=env, stdout=stream, stderr=subprocess.STDOUT, start_new_session=True)
                try:
                    code = p.wait(timeout=1200)
                except subprocess.TimeoutExpired:
                    timed_out = True
                    os.killpg(p.pid, signal.SIGKILL)
                    code = p.wait()
            new = resource.getrusage(resource.RUSAGE_CHILDREN)
            record = {"command": ["cargo"] + cmd[1:], "exit_code": code, "timed_out": timed_out,
                      "wall_seconds": time.monotonic()-start,
                      "child_cpu_seconds": new.ru_utime+new.ru_stime-old.ru_utime-old.ru_stime,
                      "maximum_descendant_rss_kib": new.ru_maxrss,
                      "log_bytes": log.stat().st_size, "log_sha256": sha(log)}
            result["commands"].append(record)
            save(output / "RESULT.json", result)
            print(json.dumps(record), flush=True)
            if code or timed_out:
                break
        result["source_unchanged"] = source_manifest(root) == before
        result["all_passed"] = (len(result["commands"]) == len(commands)
                                and all(x["exit_code"] == 0 and not x["timed_out"] for x in result["commands"])
                                and result["source_unchanged"])
        if result["all_passed"]:
            binary = target / "debug/hepta-runtime"
            result["binary"] = {"sha256": sha(binary), "bytes": binary.stat().st_size}
    finally:
        final = resource.getrusage(resource.RUSAGE_CHILDREN)
        result.update(completed=True, wall_seconds=time.monotonic()-started,
                      self_cpu_seconds=time.process_time()-self_cpu,
                      child_cpu_seconds=final.ru_utime+final.ru_stime-usage.ru_utime-usage.ru_stime)
        save(output / "RESULT.json", result)
    print(json.dumps({"all_passed": result["all_passed"], "commands_completed": len(result["commands"])}), flush=True)
    raise SystemExit(0 if result["all_passed"] else 1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    for name in ("root", "target", "output"):
        parser.add_argument("--"+name, type=pathlib.Path, required=True)
    main(parser.parse_args())
