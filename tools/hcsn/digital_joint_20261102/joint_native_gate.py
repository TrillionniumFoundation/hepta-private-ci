"""Measure the unchanged repository nextest gate before/after a real tool install."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--work", type=Path, required=True)
    p.add_argument("--nextest", type=Path, required=True)
    p.add_argument("--rust-bin", type=Path, required=True)
    p.add_argument("--just-bin", type=Path, required=True)
    p.add_argument("--cargo-home", type=Path, required=True)
    p.add_argument("--source-digest", required=True)
    p.add_argument("--out", type=Path, required=True)
    a = p.parse_args(); a.out.mkdir(parents=True, exist_ok=False)
    expected = "7e43165f5360b31ac559113848e56e1cf0dc97014d34fbbdfa62741754740435"
    if sha(a.nextest) != expected:
        raise ValueError("official CI cargo-nextest byte identity mismatch")
    env = dict(os.environ, CARGO_HOME=str(a.cargo_home), CARGO_NET_OFFLINE="true",
               HEPTA_TASK_NATIVE_SOURCE_DIGEST=a.source_digest, RUST_MIN_STACK="8388608")
    if a.rust_bin.parent.parent.name == "toolchains":
        env.update(RUSTUP_HOME=str(a.rust_bin.parents[2]), RUSTUP_TOOLCHAIN=a.rust_bin.parent.name)
    env["PATH"] = os.pathsep.join([str(a.rust_bin), str(a.just_bin), "/usr/local/bin", "/usr/bin", "/bin"])
    command = ["just", "test", "--offline", "--locked"]
    for name in ("hepta-digital-read-before-native", "codex-hepta-neuron", "codex-hepta-infer-core", "codex-hepta-types"):
        command += ["-p", name]
    rows = []
    for stage in ("before", "after"):
        if stage == "after":
            env["PATH"] = str(a.nextest.parent)+os.pathsep+env["PATH"]
        started = time.perf_counter()
        result = subprocess.run(command, cwd=a.work, env=env, capture_output=True, text=True)
        log = a.out/(stage+".log"); log.write_text(result.stdout+result.stderr)
        row = dict(stage=stage, command=command, cwd=str(a.work), returncode=result.returncode,
                   wall_seconds=time.perf_counter()-started, log_sha256=sha(log), log=log.name)
        rows.append(row); print(json.dumps(row), flush=True)
    version = subprocess.check_output([str(a.nextest), "nextest", "--version"], text=True)
    report = dict(schema="joint-native-real-nextest-gate-v1", results=rows,
                  nextest_sha256=expected, nextest_version=version,
                  original_gate_before_failed=rows[0]["returncode"] != 0,
                  original_gate_after_passed=rows[1]["returncode"] == 0,
                  repository_helpers_modified=False, direct_test_fallback=False)
    (a.out/"SUMMARY.json").write_text(json.dumps(report, indent=2)+"\n")
    if not report["original_gate_after_passed"]:
        raise RuntimeError("real unchanged nextest gate remains failing")


if __name__ == "__main__":
    main()
