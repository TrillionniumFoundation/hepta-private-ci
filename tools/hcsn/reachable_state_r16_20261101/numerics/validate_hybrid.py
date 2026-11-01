"""Run, independently audit, restart and archive the fixed hybrid profile."""

import argparse
import gzip
import hashlib
import io
import json
from pathlib import Path
import sys
import tarfile
import tempfile
import time

import numpy as np

from .hybrid_driver import FIELDS, MAXIMUM_ERROR
from .interval_replay import canonical
from .validate_q24 import Law, SCALE, causal_tape, child_run, model_text


HERE = Path(__file__).resolve().parent
MODULE = "tools.hcsn.reachable_state_r16_20261101.numerics.hybrid_driver"
FROZEN_NATIVE_COMMIT = "4c51e9a068a887fcf80573628e7692a1f84f9c18"


def digest(data):
    return hashlib.sha256(data).hexdigest()


def archive(output):
    paths = sorted(path for path in output.rglob("*") if path.is_file())
    manifest, stream = [], io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w") as tar:
        for path in paths:
            data = path.read_bytes()
            relative = str(path.relative_to(output))
            info = tarfile.TarInfo(relative)
            info.size, info.mode, info.mtime = len(data), 0o644, 0
            tar.addfile(info, io.BytesIO(data))
            manifest.append(dict(path=relative, bytes=len(data), sha256=digest(data)))
    compressed = gzip.compress(stream.getvalue(), mtime=0)
    parts = []
    for start in range(0, len(compressed), 480000):
        data = compressed[start:start + 480000]
        name = f"EVIDENCE.tar.gz.part{len(parts):03d}"
        (output / name).write_bytes(data)
        parts.append(dict(path=name, bytes=len(data), sha256=digest(data)))
    index = dict(schema="hcsn-r16-hybrid-evidence-index-v1", files=manifest,
        raw_file_bytes=sum(row["bytes"] for row in manifest),
        archive_sha256=digest(compressed), archive_bytes=len(compressed), parts=parts,
        reconstruction="Concatenate listed parts in order, gunzip, extract tar; every original file byte is indexed.")
    (output / "EVIDENCE_INDEX.json").write_text(json.dumps(index, indent=2, sort_keys=True) + "\n")
    return index


def validate(output, rustc, seed, source_commit):
    started = time.process_time()
    if seed in (163211, 163213) and (len(source_commit) != 40
                                   or any(c not in "0123456789abcdef" for c in source_commit)):
        raise ValueError("Formal seeds require the published, read-back hybrid source commit")
    output.mkdir(parents=True, exist_ok=False)
    frozen = json.loads((HERE / "PUBLISH_MANIFEST.json").read_text())
    for item in frozen["files"]:
        path = HERE / Path(item["path"]).name
        if digest(path.read_bytes()) != item["sha256"]:
            raise ValueError("Frozen pure-Q24 dependency changed: " + path.name)
    law = Law()
    model, _, conversion = model_text(law)
    operations, reference, world = causal_tape(law, seed=seed)
    model_path, operations_path = output / "MODEL.txt", output / "OPS.txt"
    model_path.write_bytes(model)
    operations_path.write_text("\n".join(operations) + "\n")
    (output / "WORLD.json.gz").write_bytes(gzip.compress(canonical(world).encode(), mtime=0))
    array = io.BytesIO()
    np.save(array, reference, allow_pickle=False)
    (output / "FLOAT_REFERENCE.npy.gz").write_bytes(gzip.compress(array.getvalue(), mtime=0))
    receipts = []

    def recorded_run(command, name):
        launched = output / "owner_receipts" / name
        launched.parent.mkdir(exist_ok=True)
        launched.with_suffix(".launch.json").write_text(canonical(dict(
            name=name, command=list(map(str, command)), state="launched")) + "\n")
        result = child_run(command, receipts, name)
        launched.with_suffix(".stdout.log").write_text(result.stdout)
        launched.with_suffix(".stderr.log").write_text(result.stderr)
        (output / "PROCESS_RECEIPTS.json").write_text(json.dumps(receipts, indent=2, sort_keys=True) + "\n")
        return result

    with tempfile.TemporaryDirectory(prefix="hcsn-r16-hybrid-") as temporary:
        temporary = Path(temporary)
        binary = temporary / "q24"
        compile_result = recorded_run([rustc, "--edition=2024", "-O", "-D", "warnings",
                                   HERE / "q24_main.rs", "-o", binary], "compile_frozen_native")
        if compile_result.returncode:
            raise RuntimeError(compile_result.stderr)
        tests = recorded_run([sys.executable, "-m",
            "tools.hcsn.reachable_state_r16_20261101.numerics.test_interval_replay"], "exact_fraction_unit_tests")
        (output / "INTERVAL_TESTS.log").write_text(tests.stdout + tests.stderr)
        if tests.returncode:
            raise RuntimeError(tests.stderr)
        command = [sys.executable, "-m", MODULE, "--model", model_path,
                   "--ops", operations_path, "--native", binary]
        full = recorded_run(command + ["--output", output / "full"], "full_hybrid_execution")
        if full.returncode:
            raise RuntimeError(full.stderr)
        split = len(operations) // 2
        prefix = recorded_run(command + ["--output", output / "prefix", "--stop-after", split],
                           "prefix_hybrid_execution")
        resumed = recorded_run(command + ["--output", output / "resumed", "--restore",
                                      output / "prefix/HYBRID_CHECKPOINT.json"], "fresh_process_hybrid_restore")
        if prefix.returncode or resumed.returncode:
            raise RuntimeError(prefix.stderr + resumed.stderr)
        traces = {name: [json.loads(line) for line in (output / name / "TRACE.jsonl").read_text().splitlines()]
                  for name in ("full", "prefix", "resumed")}
        combined = traces["prefix"] + traces["resumed"][1:]
        compare_fields = FIELDS + ("event", "execution")
        resume_equal = (len(combined) == len(traces["full"])
                        and all(all(a[field] == b[field] for field in compare_fields)
                                for a, b in zip(combined, traces["full"])))
        bundles = {name: json.loads((output / name / "HYBRID_CHECKPOINT.json").read_text())
                   for name in ("full", "prefix", "resumed")}
        interval_restore_exact = bundles["full"]["interval_cache"] == bundles["resumed"]["interval_cache"]
        native_restore_exact = bundles["full"]["native_checkpoint_hex"] == bundles["resumed"]["native_checkpoint_hex"]
        cumulative_replay_exact = bundles["resumed"]["cumulative_cost"]["replayed_events"] == len(operations)
        float_l1, content_changes = [], 0
        for index, (frame, expected) in enumerate(zip(traces["full"], reference)):
            if frame["completed"] != index:
                raise AssertionError("Tapes do not align event by event")
            actual = np.asarray(frame["counts"]) / SCALE
            float_l1.extend(np.sum(np.abs(actual - expected), axis=1).tolist())
            content_changes += int(np.count_nonzero(np.argmax(actual.reshape(4, 10, 4).sum(1), axis=1)
                                                    != np.argmax(expected.reshape(4, 10, 4).sum(1), axis=1)))
        # Restore rejection uses a new namespace and cannot overwrite old evidence.
        invalid = json.loads((output / "prefix/HYBRID_CHECKPOINT.json").read_text())
        invalid["native_state"]["completed"] += 1
        corrupt = output / "CORRUPT_CHECKPOINT.json"
        corrupt.write_text(canonical(invalid))
        rejected_cache = recorded_run(command + ["--output", output / "rejected_cache", "--restore", corrupt],
                                   "reject_corrupt_hybrid_cache")
        changed_tape = output / "CHANGED_OPS.txt"
        changed_tape.write_bytes(operations_path.read_bytes().replace(b"\n", b" \n", 1))
        tape_command = [sys.executable, "-m", MODULE, "--model", model_path, "--ops", changed_tape,
                        "--native", binary, "--output", output / "rejected_tape", "--restore",
                        output / "prefix/HYBRID_CHECKPOINT.json"]
        rejected_tape = recorded_run(tape_command, "reject_changed_tape")
        old_hash = digest((output / "full/TRACE.jsonl").read_bytes())
        reused = recorded_run(command + ["--output", output / "full"], "reject_reused_output_namespace")
        namespace_intact = old_hash == digest((output / "full/TRACE.jsonl").read_bytes())
    full_result = json.loads((output / "full/RUN.json").read_text())
    independent_units = "Numerical deterministic trajectories; no statistical quality inference from visited states."
    result = dict(schema="hcsn-r16-hybrid-validation-v1", source_commit=source_commit,
        frozen_native_commit=FROZEN_NATIVE_COMMIT, seed=seed,
        events=len(operations), independent_units=independent_units,
        full_execution=full_result, float_reference_l1_max=max(float_l1),
        content_argmax_disagreements=content_changes,
        source_fixture_conversion_l1_max=conversion,
        resume_trace_exact=resume_equal, resume_interval_cache_exact=interval_restore_exact,
        resume_native_checkpoint_exact=native_restore_exact,
        resumed_cumulative_replayed_events_exact=cumulative_replay_exact,
        cache_corruption_rejected=rejected_cache.returncode != 0,
        changed_tape_rejected=rejected_tape.returncode != 0 and "Hybrid model/tape/profile mismatch" in rejected_tape.stderr,
        prior_namespace_rejected_intact=reused.returncode != 0 and namespace_intact,
        receipts=receipts, orchestration_cpu_seconds=time.process_time() - started,
        outer_child_cpu_seconds=sum(row["child_cpu_seconds"] for row in receipts),
        cost_rule="Outer child CPU includes the driver and its waited-for native descendants. Do not add driver replay/native breakdowns again. Full execution cost is separate from compile, unit checks and recovery verification.",
        scope="80-digit interval replay of the exact integer fixture, four-address finite tape, trusted snapshot recovery. No pure-Q24 admission, expm/PDE certificate, native planner, production owner, anti-rollback, network or energy claim.",
        source_hashes={name: digest((HERE / name).read_bytes()) for name in
            ("interval_replay.py", "hybrid_driver.py", "test_interval_replay.py", "validate_hybrid.py", "HYBRID_PROTOCOL.json")})
    result["gates"] = dict(all_events_once=full_result["events_committed"] == len(operations),
        original_one_percent_budget=full_result["maximum_native_radius_units"] <= MAXIMUM_ERROR
            and full_result["maximum_interval_radius_units"] <= MAXIMUM_ERROR,
        float_l1_below_1e_minus_4=max(float_l1) < 1e-4,
        interval_replay_covers_every_consumed_event=full_result["replayed_events"] == len(operations),
        complete_recovery=resume_equal and interval_restore_exact and native_restore_exact and cumulative_replay_exact,
        refusal_integrity=result["cache_corruption_rejected"] and result["changed_tape_rejected"]
            and result["prior_namespace_rejected_intact"])
    result["passed"] = all(result["gates"].values())
    (output / "PROCESS_RECEIPTS.json").write_text(json.dumps(receipts, indent=2, sort_keys=True) + "\n")
    index = archive(output)
    result["orchestration_cpu_seconds"] = time.process_time() - started
    result["orchestration_cpu_scope"] = "Through evidence packaging, excluding final summary serialization; a recorded lower bound."
    result["evidence"] = dict(index="EVIDENCE_INDEX.json", archive_sha256=index["archive_sha256"],
                               raw_bytes=index["raw_file_bytes"], archive_bytes=index["archive_bytes"],
                               parts=index["parts"])
    (output / "HYBRID_VALIDATION.json").write_text(json.dumps(result, indent=2, sort_keys=True,
                                                            allow_nan=False) + "\n")
    (output / "PUBLICATION_FILES.json").write_text(json.dumps(
        ["HYBRID_VALIDATION.json", "EVIDENCE_INDEX.json", "PUBLICATION_FILES.json"]
        + [part["path"] for part in index["parts"]], indent=2) + "\n")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--source-commit", default="development")
    parser.add_argument("--rustc", type=Path, default=Path(
        "/tmp/trnm-original-budget-rustup/toolchains/1.95.0-x86_64-unknown-linux-gnu/bin/rustc"))
    args = parser.parse_args()
    result = validate(args.output.resolve(), args.rustc, args.seed, args.source_commit)
    print(canonical({key: result[key] for key in ("passed", "seed", "events", "float_reference_l1_max", "gates")}))
    raise SystemExit(0 if result["passed"] else 1)
