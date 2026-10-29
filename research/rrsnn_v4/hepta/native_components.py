"""Run actual unchanged Hepta owner components; never relabel them production Cells."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import resource
import select
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent
WORKSPACE = ROOT.parents[1]
UPSTREAM = WORKSPACE / "rrsnn_v2/hepta/upstream_snapshot/codex-rs"
UPSTREAM_MANIFEST = WORKSPACE / "rrsnn_v2/hepta/upstream_source_manifest.json"
UPSTREAM_SHA = "f8c9419df6ddeb36ff8b522a50219981fb8d9345"
RUST = Path("/tmp/chain-pon-rustup/toolchains/1.95.0-x86_64-unknown-linux-gnu/bin")
JUST = Path("/tmp/hepta-finish3-rescue/tools/just")
BUILD = ROOT / "native_build"
RESULTS = ROOT / "native_results"


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n")


def upstream_identity():
    manifest = json.loads(UPSTREAM_MANIFEST.read_text())
    for row in manifest["files"]:
        path = UPSTREAM.parent / row["path"]
        data = path.read_bytes()
        assert len(data) == row["bytes"], row["path"]
        assert hashlib.sha256(data).hexdigest() == row["sha256"], row["path"]
        assert hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest() == row["git_blob_sha"]
    return {"commit": UPSTREAM_SHA, "manifest_sha256": sha(UPSTREAM_MANIFEST),
            "unchanged_source_files": len(manifest["files"])}


def cgroup():
    values = {}
    for name in ["cpu.max", "cpu.stat", "memory.max", "memory.current", "memory.events", "memory.stat"]:
        path = Path("/sys/fs/cgroup") / name
        values[name] = path.read_text() if path.exists() else None
    return values


def environment():
    return {"schema": "rrsnn.native-component-host.v1", "platform": platform.platform(),
            "machine": platform.machine(), "python": sys.version,
            "affinity": sorted(os.sched_getaffinity(0)), "pid": os.getpid(),
            "cpu_identity_sha256": sha("/proc/cpuinfo"),
            "memory_limits": cgroup(), "disk_free_bytes": shutil.disk_usage(ROOT).free,
            "dot_identity_verified": False, "production_target_attested": False,
            "rlimit_nofile": list(resource.getrlimit(resource.RLIMIT_NOFILE)),
            "scope": "local scratch executor; no remote identity or private credentials inferred"}


def build():
    identity = upstream_identity()
    BUILD.mkdir(parents=True, exist_ok=True)
    config = BUILD / ".cargo/config.toml"
    config.parent.mkdir(exist_ok=True)
    config.write_text('[source.crates-io]\nreplace-with="vendored"\n[source.vendored]\n'
                      + 'directory=' + json.dumps(str(UPSTREAM / "vendor")) + '\n[net]\noffline=true\n')
    manifest = ('[package]\nname="codex-rrsnn-native-owner-components"\nversion="0.1.0"\nedition="2024"\n'
                '[workspace]\n[dependencies]\nserde_json="=1.0.149"\n')
    for name in ["hepta-types", "hepta-infer-core", "hepta-neuron"]:
        manifest += 'codex-' + name + '={path=' + json.dumps(str(UPSTREAM / name)) + '}\n'
    manifest += ('[[bin]]\nname="rrsnn-native-owner"\npath=' + json.dumps(str(ROOT / "native_owner/src/main.rs"))
                 + '\n[profile.release]\ndebug=false\ncodegen-units=1\n')
    (BUILD / "Cargo.toml").write_text(manifest)
    env = dict(os.environ)
    env["PATH"] = str(RUST) + os.pathsep + env["PATH"]
    env["RUSTC"] = str(RUST / "rustc")
    env["RUSTDOC"] = str(RUST / "rustdoc")
    env["CARGO_HOME"] = str(BUILD / "cargo_home")
    env["CARGO_TARGET_DIR"] = str(BUILD / "target")
    env["CARGO_BUILD_JOBS"] = "1"
    justfile = ('fmt:\n    cargo fmt --manifest-path Cargo.toml\n\n'
                'build:\n    cargo build --release --locked --offline --manifest-path Cargo.toml\n\n'
                'test:\n    ' + json.dumps(sys.executable) + ' ' + json.dumps(str(Path(__file__).resolve()))
                + ' --validate-only --binary ' + json.dumps(str(BUILD / "target/release/rrsnn-native-owner")) + '\n')
    (BUILD / "justfile").write_text(justfile)
    logs = []
    commands = [[str(RUST / "rustc"), "--version"], ["cargo", "generate-lockfile", "--offline"],
                [str(JUST), "fmt"], [str(JUST), "build"], [str(JUST), "test"]]
    for command in commands:
        start = time.perf_counter()
        result = subprocess.run(command, cwd=BUILD, env=env, capture_output=True, text=True)
        logs.append({"command": command, "returncode": result.returncode,
                     "wall_seconds": time.perf_counter() - start, "output": result.stdout + result.stderr})
        print(json.dumps({"step": command, "returncode": result.returncode,
                          "tail": (result.stdout + result.stderr)[-2500:]}), flush=True)
        write_json(RESULTS / "build.json", {"upstream": identity, "steps": logs, "all_passed": all(x["returncode"] == 0 for x in logs)})
        if result.returncode:
            raise RuntimeError("native component build/validation failed")
    assert upstream_identity() == identity
    binary = BUILD / "target/release/rrsnn-native-owner"
    write_json(RESULTS / "build.json", {"upstream": identity, "steps": logs, "all_passed": True,
               "binary_sha256": sha(binary), "manifest_sha256": sha(BUILD / "Cargo.toml"),
               "lock_sha256": sha(BUILD / "Cargo.lock"),
               "scope": "reduced native dependency build; not full upstream workspace CI"})
    return binary


def invoke(binary, mode, run_root, metadata, *arguments):
    command = [str(binary), mode, str(run_root), str(metadata), *map(str, arguments)]
    result = subprocess.run(command, capture_output=True, text=True, timeout=600)
    if result.returncode:
        raise RuntimeError(json.dumps({"command": command, "code": result.returncode, "stderr": result.stderr}))
    return json.loads(result.stdout)


def validation(binary):
    directory = RESULTS / ("validation-" + str(time.time_ns()))
    directory.mkdir(parents=True)
    metadata = directory / "host.json"
    write_json(metadata, environment())
    functional = invoke(binary, "validate", directory / "clean", metadata)
    crashes = []
    for sequence in [1, 2]:
        for phase in ["before_witness", "after_witness"]:
            run_root = directory / f"{phase}-{sequence}"
            process = subprocess.Popen([str(binary), "crash", str(run_root), str(metadata), phase, str(sequence)],
                                       stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            ready, _, _ = select.select([process.stdout], [], [], 30)
            if not ready:
                process.kill()
                raise RuntimeError("native fault process did not reach checkpoint barrier")
            barrier = json.loads(process.stdout.readline())
            assert barrier == {"ready": phase, "sequence": sequence}, barrier
            process.kill()
            code = process.wait(timeout=10)
            assert code == -9, code
            recovered = invoke(binary, "recover", run_root, metadata)
            expected = not (sequence == 1 and phase == "before_witness")
            assert recovered["result"]["recovered"] == expected, recovered
            if expected:
                assert recovered["result"]["recovered_sequence"] == sequence
                assert recovered["result"]["model_calls_during_recovery"] == 0
                assert recovered["result"]["next_model_calls"] == 1
            crashes.append({"phase": phase, "committing_sequence": sequence,
                            "actual_sigkill_returncode": code, "recovery": recovered})
    report = {"schema": "rrsnn.native-owner-crash-validation.v1", "functional": functional,
              "crashes": crashes, "all_expected_behaviors_reproduced": True,
              "all_recovery_cases_passed": False, "production_qualified": False,
              "blocker": "first journal commit before initial witness publication has no public anchored recovery route",
              "binary_sha256": sha(binary), "host": json.loads(metadata.read_text()),
              "upstream": upstream_identity()}
    write_json(directory / "validation.json", report)
    write_json(RESULTS / "validation_latest.json", report)
    print(json.dumps({"functional_checks": functional["result"]["passed"],
                      "actual_sigkill_cases": len(crashes), "recoverable": sum(x["recovery"]["result"]["recovered"] for x in crashes),
                      "first_commit_recovery_blocker": True}), flush=True)
    return report


def percentile(values, p):
    ordered = sorted(values)
    pos = (len(ordered) - 1) * p
    lo = int(pos)
    hi = min(lo + 1, len(ordered) - 1)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (pos - lo)


def measure(binary, counts=None, report_name="component_benchmark.json"):
    protocol = {"schema": "rrsnn.native-owner-component-protocol.v1", "counts": [64, 256, 1024, 4096],
                "warmup_rounds": 4, "measured_rounds": 32, "affinity": [8],
                "unit": "one real upstream NeuronRuntime, SparseJournal and FileAnchorWitnessStore",
                "queue": "one bounded FIFO with capacity equal to owner count; no worker concurrency",
                "model": "fixed executed signed-Q24 8x22 matrix projection; not a trained RR candidate",
                "output": "no external effect destination; DENY_ALL authority",
                "primary_latency": "wall time for entire owner tick including witness fsync",
                "secondary_latency": "full batch including FIFO construction; queue age separately",
                "p99_scope": "descriptive quantile of this run; 32 full-batch samples only",
                "resource_state": "cgroup before and after each fresh process; unexplained/OOM/limit events retain invalid flag",
                "production_cells": False, "dot_attested": False}
    protocol_path = RESULTS / "benchmark_protocol.json"
    if protocol_path.exists():
        assert json.loads(protocol_path.read_text()) == protocol
    else:
        write_json(protocol_path, protocol)
    rows = []
    selected = protocol["counts"] if counts is None else counts
    if not selected or any(count not in protocol["counts"] for count in selected):
        raise ValueError("unsupported frozen confirmation count")
    for count in selected:
        directory = RESULTS / (f"owners-{count}-" + str(time.time_ns()))
        directory.mkdir(parents=True)
        metadata = directory / "host.json"
        write_json(metadata, environment())
        before = cgroup()
        usage_before = resource.getrusage(resource.RUSAGE_CHILDREN)
        output = invoke(binary, "measure", directory / "stores", metadata, count,
                        protocol["warmup_rounds"], protocol["measured_rounds"])
        usage_after = resource.getrusage(resource.RUSAGE_CHILDREN)
        after = cgroup()
        result = output["result"]
        raw = {key: result.pop(key) for key in ["owner_wall_ns", "batch_wall_ns", "runtime_receipt_execution_us", "queue_age_us"]}
        for round_index in range(protocol["measured_rounds"]):
            row = {"round": round_index, "batch_wall_ns": raw["batch_wall_ns"][round_index]}
            for key in ["owner_wall_ns", "runtime_receipt_execution_us", "queue_age_us"]:
                row[key] = raw[key][round_index * count:(round_index + 1) * count]
            (directory / f"timing_{round_index:02}.json").write_text(json.dumps(row, separators=(",", ":")) + "\n")
        row = {"instances": count, "actual_owner_ticks_measured": count * protocol["measured_rounds"],
               "owner_p50_us": percentile(raw["owner_wall_ns"], .5) / 1000,
               "owner_p95_us": percentile(raw["owner_wall_ns"], .95) / 1000,
               "owner_p99_us": percentile(raw["owner_wall_ns"], .99) / 1000,
               "batch_p95_ms": percentile(raw["batch_wall_ns"], .95) / 1e6,
               "batch_p99_ms": percentile(raw["batch_wall_ns"], .99) / 1e6,
               "owner_ticks_per_second": count * len(raw["batch_wall_ns"]) * 1e9 / sum(raw["batch_wall_ns"]),
               "queue_p95_us": percentile(raw["queue_age_us"], .95),
               "cpu_seconds_whole_child_including_initialization_and_recovery":
                   (usage_after.ru_utime + usage_after.ru_stime) - (usage_before.ru_utime + usage_before.ru_stime),
               "native": result, "cgroup_before": before, "cgroup_after": after,
               "protocol_sha256": sha(protocol_path), "binary_sha256": sha(binary),
               "raw_directory": str(directory.relative_to(ROOT)), "timing_file_count": 32,
               "production_cell_measurement": False, "dot_measurement": False}
        def events(value):
            if value is None:
                return None
            return {k: int(v) for k, v in (line.split() for line in value.splitlines())}
        first, last = events(before["memory.events"]), events(after["memory.events"])
        row["memory_limit_events_delta"] = None if first is None or last is None else {key: last[key]-first.get(key, 0) for key in last}
        row["memory_window_valid"] = row["memory_limit_events_delta"] is not None and not any(row["memory_limit_events_delta"].get(k, 0) for k in ["max", "oom", "oom_kill"])
        write_json(directory / "summary.json", row)
        # Ephemeral native stores are reproducible from source/input. Keep metrics and raw timing,
        # then release these exact newly-created stores before the next size to bound disk use.
        shutil.rmtree(directory / "stores")
        rows.append(row)
        write_json(RESULTS / report_name, {"protocol": protocol, "rows": rows,
                   "upstream": upstream_identity(), "full_count_matrix_complete": len(rows) == 4,
                   "confirmation_reason": None if counts is None else "prior 4096 window had shared cgroup memory.max events; retain both runs",
                   "real_production_cell_qualification": False})
        print(json.dumps({k: row[k] for k in ["instances", "owner_p95_us", "owner_p99_us", "batch_p99_ms",
                                             "owner_ticks_per_second", "memory_window_valid"]}), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--binary", type=Path)
    parser.add_argument("--measure", action="store_true")
    parser.add_argument("--confirm-4096", action="store_true")
    args = parser.parse_args()
    ROOT.mkdir(parents=True, exist_ok=True)
    RESULTS.mkdir(exist_ok=True)
    if 8 in os.sched_getaffinity(0):
        os.sched_setaffinity(0, {8})
    if args.validate_only:
        if args.binary is None:
            raise ValueError("validation requires exact compiled binary")
        validation(args.binary)
        return
    binary = args.binary or build()
    if args.measure:
        measure(binary)
    if args.confirm_4096:
        measure(binary, [4096], "component_benchmark_confirmation_4096.json")


if __name__ == "__main__":
    main()
