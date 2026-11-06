#!/usr/bin/env python3
"""External, preregistered owner for two existing C4 synthetic census children.

This does not change C4, run Mode-A, generate model materials or execute tests.
Native argv[1:], 300-second deadlines, pipe caps and group cleanup are original.
All other limits below are NEW external coordination limits, not old CI credit.
The frozen proc collector is reused unchanged on a same-directory hash-named
copy of the built example. Missing actual capture is a failure, never inferred.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import resource
import shutil
import stat
import sys
import time

COMMIT = "8df4b21d893906570d48f5beafabb3b31e0aefbc"
TREE = "6f5aaa2af0432e27e24b6bd2ad18013ab4423d14"
SEED = "d74433233739073f8237d5efa7d7fe9f2bf7b686a4634c425c2dabc6bed68944"
EXAMPLE = "pon_work_expensive_v1"
SELECTOR = "--work-expensive-v1"
NATIVE_SCHEMA = "pon-work-expensive-native-v2"
READER_SCHEMA = "pon-work-expensive-reader-v2"
CAPTURE_SHA256 = "64489779d88a399040e20f939fe878f8d20fa86a60b435a2d7896186dc64d87a"
BOOTSTRAP_PINS = {
    "formal/pon-nakamoto-v1/bounded_process.py": "16fa98206e75db5e925a31508e889df9d1968c32f518554f52c2a0711047b356",
    "scripts/ci/verify_ci_source.py": "0ddfd07719eae98913348c82b06d3e4522d721c353d9b01d6deac0dfda619946",
    "scripts/pon_work_expensive_reader_v1.py": "946d5e18b9feaff58a5c6817ee26fb831548ce253791f668b184834f36ffa8f3",
    "trillionnium/crates/trnm-crypto-primitives/examples/pon_work_expensive_v1.rs": "86cce1ac568a4542f37922ac88887f1e9a0c8071d233cd4be1fc0da19cf4364e",
}
CLASSES = (
    "periodic-dense-fixture", "full-rank-field", "zero", "identity", "rank-one",
    "sparse-diagonal", "continuity-maintenance-v1", "left-zero-right-rank-one",
    "right-zero-left-rank-one",
)
ARMS = (
    "lazy-full-limb", "prepared-generic", "prepared-structured", "tiled-classical",
    "tiled-strassen-one-level", "paired-product", "blocked-zero",
    "blocked-zero-integer-paired", "blocked-one-zero-rank-one", "maintenance-periodic",
    "maintenance-integer-paired", "maintenance-prefix", "maintenance-limb",
    "scalar-original", "lazy-full-limb-sparse",
)
ORIGINAL_NATIVE = dict(timeout_seconds=300, stdout_limit_bytes=256*1024*1024,
                       stderr_limit_bytes=1024*1024)
NEW_LIMITS = dict(outer_seconds=3600, preflight_seconds=120,
                  source_guard_seconds=600, identity_seconds=30,
                  metadata_seconds=120, build_seconds=900, reader_seconds=180,
                  collector_finish_seconds=60)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def file_record(path):
    """Read a bounded regular file through a no-follow descriptor, with stability."""
    before = path.lstat()
    require(stat.S_ISREG(before.st_mode), "regular file required: " + str(path))
    require(before.st_size <= 512*1024*1024, "file observation bound")
    fingerprint = lambda value: (value.st_dev, value.st_ino, value.st_mode,
                                  value.st_size, value.st_mtime_ns, value.st_ctime_ns)
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as stream:
        require(fingerprint(os.fstat(stream.fileno())) == fingerprint(before), "file changed before read")
        digest = hashlib.sha256()
        size = 0
        for chunk in iter(lambda: stream.read(1024*1024), b""):
            size += len(chunk)
            require(size <= before.st_size, "file grew during read")
            digest.update(chunk)
        require(size == before.st_size and
                fingerprint(os.fstat(stream.fileno())) == fingerprint(before), "file changed during read")
    require(fingerprint(path.lstat()) == fingerprint(before), "file path changed during read")
    return dict(path=str(path), sha256=digest.hexdigest(), bytes=size,
                device=before.st_dev, inode=before.st_ino, mode=stat.S_IMODE(before.st_mode))


def native_argv(executable, target_index):
    require(type(target_index) is int and target_index in (0, 1), "fixed target required")
    return [str(executable), SELECTOR, "--attempts", "64", "--samples", "8",
            "--reuse", "16", "--target-index", str(target_index), "--seed", SEED]


def build_argv():
    # Same documented package/profile/features/jobs/examples; only the output
    # format is added to retain Cargo's exact executable artifact identity.
    return ["cargo", "build", "--offline", "--locked", "--release", "--manifest-path",
            "trillionnium/Cargo.toml", "-p", "trnm-crypto-primitives", "--jobs", "2",
            "--example", EXAMPLE, "--example", "pon_shared_material_v1",
            "--message-format=json-render-diagnostics"]


def reader_argv(raw_path, report_path):
    return ["python3", "-B", "scripts/pon_work_expensive_reader_v1.py", str(raw_path),
            "--out", str(report_path), "--calibration-samples", "2", "--budgets-ns",
            "1000000", "5000000", "20000000"]


def bind_reader_report(value, target_index, raw_record):
    """Caller identity binding after the unchanged reader has parsed the raw."""
    expected = dict(schema=READER_SCHEMA, native_record_schema=NATIVE_SCHEMA,
                    status="complete", seed=SEED,
                    target=("7f" if target_index == 0 else "07") + "ff"*31,
                    attempts_per_arm=64, samples=8, reuse_attempts=16,
                    observed_arms=list(ARMS), raw_sha256=raw_record["sha256"],
                    raw_bytes=raw_record["bytes"])
    for key, item in expected.items():
        require(type(value.get(key)) is type(item) and value[key] == item,
                "request/report binding: " + key)
    materials = value.get("material_identity")
    require(type(materials) is list and [item.get("class") for item in materials] == list(CLASSES),
            "nine exact ordered material classes required")
    counts = value.get("counts", {})
    for key in ("completed_cells", "unsupported_cells", "failed_cells"):
        require(type(counts.get(key)) is int and counts[key] >= 0, "integer cell count required")
    require(sum(counts[key] for key in ("completed_cells", "unsupported_cells", "failed_cells")) == 1080
            and counts["failed_cells"] == 0, "1080 requested cells with zero failures required")
    cells = value.get("cells")
    require(type(cells) is list and len(cells) == 1080, "complete 1080-cell report required")
    expected_cells = {(name, sample, arm) for name in CLASSES for sample in range(8) for arm in ARMS}
    observed = []
    for cell in cells:
        require(type(cell.get("sample")) is int, "sample type")
        key = (cell.get("class"), cell["sample"], cell.get("arm"))
        observed.append(key)
        if cell.get("arm") in (ARMS[0], ARMS[-1]):
            require(cell.get("status") == "complete" and type(cell.get("attempts")) is int
                    and cell["attempts"] == 64 and type(cell.get("setup_count")) is int
                    and cell["setup_count"] == 4, "Dense/Sparse actual 64 attempts/four setups required")
    require(len(set(observed)) == 1080 and set(observed) == expected_cells,
            "exact class/sample/arm cell coverage required")
    require(value.get("budgets", {}).get("cpu_ns") == [1000000, 5000000, 20000000],
            "original postprocessed CPU budgets required")
    selections = value.get("calibration_selection")
    require(type(selections) is list and [item.get("class") for item in selections] == list(CLASSES),
            "complete original per-class calibration required")
    for selection in selections:
        require(selection.get("calibration_samples") == [0, 1] and
                selection.get("evaluation_samples") == [2, 3, 4, 5, 6, 7],
                "original two/six sample split required")
    return dict(parameter_binding_verified=True, requested_cells=1080,
                observed_complete_cells=counts["completed_cells"],
                observed_unsupported_cells=counts["unsupported_cells"],
                source_and_native_execution_authenticated_by_this_function=False)


def bind_cross_target(left, right):
    materials = lambda value: [(row["class"], row["task"], row["a_sha256"], row["b_sha256"])
                               for row in value["material_identity"]]
    require(materials(left) == materials(right), "cross-target material identity changed")
    streams = lambda value: {(row["class"], row["sample"], row["arm"]):
                             (row["status"], row["attempts"], row["setup_count"],
                              row["trace_sequence_sha256"]) for row in value["cells"]}
    require(streams(left) == streams(right), "cross-target mathematical stream changed")
    return dict(material_identity_equal=True, full_cell_stream_identity_equal=True,
                targets_are_additive_chain_work=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--target", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--capture-helper", type=Path, required=True)
    args = parser.parse_args()
    require(sys.dont_write_bytecode and os.environ.get("PYTHONDONTWRITEBYTECODE") == "1",
            "-B and PYTHONDONTWRITEBYTECODE=1 required")
    require(platform.system() == "Linux" and platform.machine() == "x86_64", "native Linux x64 required")
    for path in (args.root, args.target, args.out, args.capture_helper):
        require(path.is_absolute() and path.resolve() == path, "canonical absolute paths required")
    require(args.root.is_dir() and args.capture_helper.is_file(), "existing source/helper required")
    require(not args.out.is_relative_to(args.root) and not args.target.is_relative_to(args.root),
            "receipt and target must be outside source")
    require(not args.root.is_relative_to(args.target) and
            not Path(__file__).resolve().is_relative_to(args.root),
            "source must not overlap target or contain the external coordinator")
    require(not args.out.is_relative_to(args.target) and not args.target.is_relative_to(args.out),
            "receipt and Cargo target must be separate")
    require(not args.capture_helper.is_relative_to(args.root), "external frozen capture helper required")
    args.out.mkdir(parents=True, mode=0o700, exist_ok=False)
    root, output, target = args.root, args.out, args.target
    started, started_cpu = time.monotonic(), time.process_time_ns()
    deadline = started + NEW_LIMITS["outer_seconds"]
    env = dict(os.environ)
    env.update(CARGO_BUILD_JOBS="2", CARGO_TARGET_DIR=str(target), CARGO_TERM_COLOR="never",
               PYTHONDONTWRITEBYTECODE="1", RUST_TEST_THREADS="1", TRNM_EXPECTED_SOURCE_SHA=COMMIT)
    env.pop("CARGO_INCREMENTAL", None)
    report = dict(schema="trnm-c4-synthetic-census-external-owner-v1", commit=COMMIT, tree=TREE,
                  coordinator_sha256=sha(Path(__file__).read_bytes()), root=str(root), output=str(output),
                  target=str(target), original_native_limits=ORIGINAL_NATIVE, new_external_limits=NEW_LIMITS,
                  started_utc=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                  runtime_process=dict(pid=os.getpid(), parent_pid=os.getppid(),
                    start_ticks=Path("/proc/self/stat").read_text().rpartition(")")[2].split()[19],
                    cgroup=Path("/proc/self/cgroup").read_text()),
                  execution_context="local-synthetic-component-observation", planned_targets=[0, 1],
                  synthetic_seed=SEED, observations=[], components=[], failures=[], passed=False,
                  source_before=None, source_after=None, cargo_configuration_before=None,
                  cargo_configuration_after=None, rust_tests_executed=0,
                  full_owner_campaign_executed=False, mode_a_executed=False, model_material_generated=False,
                  work_hardness_qualified=False, public_service_measured=False, production_activation=False,
                  observer_scope="unchanged frozen proc collector; active during each native child; observer CPU/I/O may affect wall time",
                  collector_legacy_field_scope="observed_selected_tests contains a CLI mode selector here, not executed Rust tests")
    bounded = ProcessFailure = config_snapshot = config_require = Capture = None
    launch = build_image = retained_build = None
    reader_reports = {}

    def save():
        temporary = output / "manifest.tmp"
        temporary.write_text(json.dumps(report, sort_keys=True, indent=2) + "\n")
        temporary.replace(output / "manifest.json")

    def remaining(cap, *, original_native=False):
        available = deadline - time.monotonic()
        require(available > 0, "new external 3600-second coordination window exhausted")
        if original_native:
            require(available >= cap + NEW_LIMITS["collector_finish_seconds"],
                    "insufficient outer window for unshortened original native deadline")
            return float(cap)
        return min(float(cap), available)

    def execute(name, command, cap, *, directory=None, native=False, required=True,
                stdout_limit=16*1024*1024, stderr_limit=8*1024*1024):
        directory = output if directory is None else directory
        timeout = remaining(cap, original_native=native)
        row = dict(name=name, command=command, cwd=str(root), requested_cap_seconds=cap,
                   effective_timeout_seconds=timeout, original_native_child=native, stdin_bytes=0,
                   stdout_limit_bytes=stdout_limit, stderr_limit_bytes=stderr_limit,
                   returncode=None, failure=None, passed=False)
        before = resource.getrusage(resource.RUSAGE_CHILDREN)
        tick = time.monotonic_ns()
        stdout = stderr = b""
        try:
            result = bounded(command, b"", timeout=timeout, stdout_limit=stdout_limit,
                             stderr_limit=stderr_limit, cwd=root, env=env)
            stdout, stderr = result.stdout, result.stderr
            row.update(returncode=result.returncode, passed=result.returncode == 0)
        except ProcessFailure as error:
            stdout, stderr = error.stdout, error.stderr
            row.update(returncode=error.returncode, failure=str(error),
                       stdout_truncated=error.stdout_truncated, stderr_truncated=error.stderr_truncated)
        except (OSError, ValueError) as error:
            row["failure"] = str(error)
        row["wall_ns"] = time.monotonic_ns() - tick
        after = resource.getrusage(resource.RUSAGE_CHILDREN)
        row["child_rusage"] = dict(user_cpu_ns=round((after.ru_utime-before.ru_utime)*1e9),
            system_cpu_ns=round((after.ru_stime-before.ru_stime)*1e9),
            cumulative_maxrss_kib=after.ru_maxrss,
            rss_scope="waited-children cumulative peak; not an enforced or isolated quota")
        for channel, raw in (("stdout", stdout), ("stderr", stderr)):
            filename = "native.jsonl" if native and channel == "stdout" else name + "." + channel
            path = directory / filename
            with path.open("xb") as stream:
                stream.write(raw)
            row[channel] = dict(path=str(path), bytes=len(raw), sha256=sha(raw))
        report["observations"].append(row)
        if not row["passed"]:
            report["failures"].append(name + ": process failure")
        save()
        print(json.dumps({key: row[key] for key in ("name", "returncode", "failure", "passed", "wall_ns")}), flush=True)
        if required:
            require(row["passed"], name + ": process failed; raw retained")
        return row

    def source_guard(name):
        execute(name, ["python3", "-B", "scripts/ci/verify_ci_source.py", "--kind", "head",
                       "--expected-head", COMMIT, "--output", str(output / (name + ".json"))],
                NEW_LIMITS["source_guard_seconds"])
        value = json.loads((output / (name + ".json")).read_text())
        require(value.get("tested_commit") == COMMIT and value.get("tested_tree") == TREE
                and value.get("tracked_worktree_verified") is True, "complete exact C4 source required")
        return value

    def assert_images():
        current_build, current_launch = file_record(build_image), file_record(launch)
        current_retained = file_record(retained_build)
        require(current_build["sha256"] == current_launch["sha256"] ==
                current_retained["sha256"] == report["build_artifact"]["sha256"],
                "build/launch image changed")
        require(current_launch["device"] == report["launch_copy"]["device"] and
                current_launch["inode"] == report["launch_copy"]["inode"], "launch path inode replaced")
        return dict(build=current_build, launch=current_launch, retained_build=current_retained)

    save()
    try:
        for path, expected in BOOTSTRAP_PINS.items():
            require(file_record(root / path)["sha256"] == expected, "bootstrap source pin: " + path)
        helper = file_record(args.capture_helper)
        require(helper["sha256"] == CAPTURE_SHA256, "reviewed capture helper required")
        helper_copy = output / "test_elf_capture.py"
        with helper_copy.open("xb") as stream:
            stream.write(args.capture_helper.read_bytes())
        require(file_record(helper_copy)["sha256"] == CAPTURE_SHA256, "capture helper copy mismatch")
        helper_copy.chmod(0o400)
        report["capture_helper"] = dict(input=helper, frozen=file_record(helper_copy))
        sys.path.insert(0, str(root / "formal/pon-nakamoto-v1"))
        from bounded_process import ProcessFailure, run_bounded
        bounded = run_bounded
        execute("preflight", ["bash", "scripts/project-preflight.sh", "--audit"], NEW_LIMITS["preflight_seconds"])
        report["source_before"] = source_guard("source-before")
        report["lock_before"] = file_record(root / "trillionnium/Cargo.lock")
        sys.path.insert(0, str(root / "scripts/ci"))
        from run_cross_arch_cost import build_environment_overrides, cargo_configuration_snapshot, require_cargo_configuration
        from check_cross_arch_cost import elf_machine
        config_snapshot, config_require = cargo_configuration_snapshot, require_cargo_configuration
        report["build_environment_overrides"] = build_environment_overrides(env)
        require(not report["build_environment_overrides"], "release build overrides refused")
        report["cargo_configuration_before"] = config_snapshot(root, env)
        config_require(report["cargo_configuration_before"])
        execute("uname", ["uname", "-a"], NEW_LIMITS["identity_seconds"])
        with Path("/proc/cpuinfo").open("rb") as stream:
            cpuinfo = stream.read(1024*1024 + 1)
        require(len(cpuinfo) <= 1024*1024, "CPU information observation bound")
        with (output / "cpuinfo.txt").open("xb") as stream:
            stream.write(cpuinfo)
        report["resource_observation"] = dict(cpuinfo=file_record(output / "cpuinfo.txt"),
            logical_cpu_count=os.cpu_count(), cpu_affinity=sorted(os.sched_getaffinity(0)),
            process_limits={name: list(resource.getrlimit(getattr(resource, name)))
                            for name in ("RLIMIT_AS", "RLIMIT_CPU", "RLIMIT_NPROC")},
            resource_limits_modified=False, exclusive_host_isolation_attested=False)
        compiler = execute("rustc", ["rustc", "-vV"], NEW_LIMITS["identity_seconds"])
        text = Path(compiler["stdout"]["path"]).read_text()
        require("\nrelease: 1.95.0\n" in text and "\nhost: x86_64-unknown-linux-gnu\n" in text,
                "original native Rust 1.95.0 x64 required")
        execute("cargo-version", ["cargo", "--version"], NEW_LIMITS["identity_seconds"])
        execute("locked-metadata", ["cargo", "metadata", "--offline", "--locked", "--format-version", "1",
                    "--manifest-path", "trillionnium/Cargo.toml"], NEW_LIMITS["metadata_seconds"])
        built = execute("build", build_argv(), NEW_LIMITS["build_seconds"])
        rows = [json.loads(line) for line in Path(built["stdout"]["path"]).read_text().splitlines() if line]
        require([row.get("success") for row in rows if row.get("reason") == "build-finished"] == [True],
                "successful complete Cargo build record required")
        artifacts = [row for row in rows if row.get("reason") == "compiler-artifact"
                     and row.get("target", {}).get("name") == EXAMPLE
                     and row["target"].get("kind") == ["example"] and row.get("executable")]
        require(len(artifacts) == 1, "one exact census build artifact required")
        artifact = artifacts[0]
        require(artifact["target"].get("src_path") == str(root / "trillionnium/crates/trnm-crypto-primitives/examples/pon_work_expensive_v1.rs"),
                "Cargo example source binding")
        require(artifact.get("features") == ["default"] and artifact.get("profile", {}).get("opt_level") == "3"
                and artifact["profile"].get("test") is False
                and artifact["profile"].get("debug_assertions") is False, "default release profile/features required")
        build_image = Path(artifact["executable"])
        require(build_image == target / "release/examples" / EXAMPLE and build_image.resolve() == build_image,
                "exact private release executable path required")
        require(elf_machine(build_image) == 62, "actual x64 ELF required")
        report["cargo_build_artifact_record"] = artifact
        report["build_artifact"] = file_record(build_image)
        retained_build = output / ("built-" + EXAMPLE + ".elf")
        with build_image.open("rb") as source, retained_build.open("xb") as dest:
            shutil.copyfileobj(source, dest, 1024*1024)
            dest.flush()
            os.fsync(dest.fileno())
        retained_build.chmod(0o400)
        report["retained_build_elf"] = file_record(retained_build)
        require(report["retained_build_elf"]["sha256"] == report["build_artifact"]["sha256"],
                "built ELF archive mismatch")
        launch = build_image.with_name(EXAMPLE + "-" + report["build_artifact"]["sha256"])
        report["launch_copy_preexisted"] = launch.exists()
        if not launch.exists():
            with build_image.open("rb") as source, launch.open("xb") as dest:
                shutil.copyfileobj(source, dest, 1024*1024)
                dest.flush()
                os.fsync(dest.fileno())
            launch.chmod(0o500)
        report["launch_copy"] = file_record(launch)
        require(report["launch_copy"]["mode"] & 0o100, "launch copy must be owner-executable")
        report["same_origin_directory"] = launch.parent == build_image.parent
        assert_images()
        report["argv0_mapping"] = dict(original_build_path=str(build_image), actual_launch_path=str(launch),
            argv_after_zero_unchanged=True, same_elf_bytes=True,
            reason="unchanged proc collector matches crate-hex names; same directory preserves ORIGIN lookup")
        module_spec = importlib.util.spec_from_file_location("c4_frozen_proc_capture", helper_copy)
        module = importlib.util.module_from_spec(module_spec)
        module_spec.loader.exec_module(module)
        Capture = module.ExecutedBinaryCapture
        save()
        for index in (0, 1):
            name = "synthetic-target-" + str(index)
            directory = output / name
            directory.mkdir()
            component = dict(name=name, target_index=index, passed=False, failures=[])
            report["components"].append(component)
            component["image_before"] = assert_images()
            capture = Capture(name, EXAMPLE, lambda arg: arg == SELECTOR,
                              report["source_before"], target=launch.parent, evidence=output)
            capture.bind(os.getpid())
            capture.start()
            observation_started = time.monotonic_ns()
            try:
                process = execute(name, native_argv(launch, index), ORIGINAL_NATIVE["timeout_seconds"],
                    directory=directory, native=True, required=False,
                    stdout_limit=ORIGINAL_NATIVE["stdout_limit_bytes"],
                    stderr_limit=ORIGINAL_NATIVE["stderr_limit_bytes"])
                component["process"] = process
            finally:
                component["actual_elf_capture"] = capture.finish()
                component["observer_active_wall_ns"] = time.monotonic_ns() - observation_started
                save()
            capture_result = component["actual_elf_capture"]
            records = capture_result.get("records", [])
            expected_sha = report["build_artifact"]["sha256"]
            capture_ok = (not capture_result.get("errors") and len(records) == 1
                          and capture_result.get("unique_actual_elf_sha256") == [expected_sha])
            if capture_ok:
                record = records[0]
                retained = file_record(Path(record["retained_copy"]))
                capture_ok = (record.get("actual_executable") == str(launch)
                    and record.get("wrapper_pid") == os.getpid()
                    and record.get("wrapper_start_ticks") == report["runtime_process"]["start_ticks"]
                    and record.get("wrapper_descendant_verified") is True
                    and record.get("post_open_task_and_exe_verified") is True
                    and record.get("observed_selected_tests") == [SELECTOR]
                    and record.get("device") == report["launch_copy"]["device"]
                    and record.get("inode") == report["launch_copy"]["inode"]
                    and retained["sha256"] == expected_sha)
                component["captured_elf_readback"] = retained
            if not capture_ok:
                component["failures"].append("actual executing ELF capture missing or mismatched")
            component["image_after"] = assert_images()
            reader_path = directory / "reader.json"
            reader = execute(name + "-reader", reader_argv(Path(process["stdout"]["path"]), reader_path),
                             NEW_LIMITS["reader_seconds"], directory=directory, required=False)
            component["reader_process"] = reader
            if process["passed"] and reader["passed"]:
                try:
                    reader_raw = file_record(reader_path)
                    require(reader_raw["bytes"] <= 64*1024*1024, "reader report size bound")
                    value = json.loads(reader_path.read_text())
                    component["reader_binding"] = bind_reader_report(value, index, process["stdout"])
                    component["reader_report"] = reader_raw
                    reader_reports[index] = value
                except (OSError, ValueError, KeyError, TypeError, AttributeError, IndexError, OverflowError) as error:
                    component["failures"].append("reader binding: " + str(error))
            else:
                component["failures"].append("native or original reader failed")
            component["passed"] = not component["failures"]
            report["failures"].extend(name + ": " + item for item in component["failures"])
            save()
        require(set(reader_reports) == {0, 1}, "both exact native/reader components required")
        report["cross_target_binding"] = bind_cross_target(reader_reports[0], reader_reports[1])
    except (OSError, ValueError, KeyError, TypeError, ImportError, RuntimeError,
            AttributeError, IndexError, OverflowError) as error:
        report["failures"].append(type(error).__name__ + ": " + str(error))
    finally:
        if bounded is not None and report["source_before"] is not None:
            try:
                report["source_after"] = source_guard("source-after")
                require(report["source_after"] == report["source_before"], "source identity changed")
                report["lock_after"] = file_record(root / "trillionnium/Cargo.lock")
                require(report["lock_after"]["sha256"] == report["lock_before"]["sha256"], "lockfile changed")
                report["cargo_configuration_after"] = config_snapshot(root, env)
                config_require(report["cargo_configuration_after"])
                require(report["cargo_configuration_after"] == report["cargo_configuration_before"],
                        "Cargo configuration changed")
                require(file_record(helper_copy)["sha256"] == CAPTURE_SHA256, "capture helper changed")
                require(sha(Path(__file__).read_bytes()) == report["coordinator_sha256"], "coordinator file changed")
                if launch is not None:
                    report["final_images"] = assert_images()
            except (OSError, ValueError, KeyError, TypeError, AttributeError, IndexError, OverflowError) as error:
                report["failures"].append("final guard: " + str(error))
        report["elapsed_seconds"] = time.monotonic() - started
        if report["elapsed_seconds"] > NEW_LIMITS["outer_seconds"]:
            report["failures"].append("new external coordination deadline exceeded")
        report["coordinator_process_cpu_ns"] = time.process_time_ns() - started_cpu
        report["completed_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        report["passed"] = (not report["failures"] and len(report["components"]) == 2
            and all(item["passed"] for item in report["components"])
            and report.get("cross_target_binding", {}).get("full_cell_stream_identity_equal") is True
            and report["source_before"] is not None and report["source_before"] == report["source_after"])
        save()
        print(json.dumps(dict(passed=report["passed"], failures=report["failures"],
                              manifest=str(output / "manifest.json"))), flush=True)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
