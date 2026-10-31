"""Fresh fixed-fixture qualification of the inherited local native owner.

This executable is separate from the scientific fit/freeze/confirmation lifecycle.
It uses actual recovered Rust execution, never datasets or calibration bridges.
"""

import argparse
import base64
import gzip
import json
import math
import os
from pathlib import Path
import resource
import subprocess
import sys
import time
import zlib
import struct

from ..native_adapter import Native
from ..runtime import digest
from ..round4.runtime_codec import Decoder, Encoder, HEADER, MODES
from ..round4.runtime_evidence import EvidenceZip, write_json
from ..round4.runtime_law import Q24, make_law
from ..round4.runtime_owner import Owner, ZERO, file_sha, read_document


SCHEMA = "hepta.actual-native-qualification.v6"
BINARY_SHA256 = "b519cae26325f818d9596aab34504490a0b5355b9eb633369878e6f07a50e179"
SOURCE_COMMIT = "0acfd9b27db910c180b0d8911f39aea469b7f864"
PUBLIC = {"initial": .25, "residuals": [.6], "variances": [.36],
          "repair_cost": .12, "wait_cost": .04, "wait_variance": .16}
WAITED = {**PUBLIC, "residuals": [.6, .45], "variances": [.36, .16]}
LAWS = [make_law([1], [.3], [.2]), make_law([.4, .6], [-.4, .8], [.15, .5])]
TAILS = [make_law([1], [7.5], [.0001]), make_law([1], [-7.5], [.0001]),
         make_law([.5, .5], [-7.5, 7.5], [.0001, .0001]),
         make_law([.01, .99], [0, 7.5], [.0001, .01])]
EDGE = make_law([1 / Q24, 1 - 1 / Q24], [-7.999, 7.999], [4 / Q24, 7.9])
FIXTURES = {"public": PUBLIC, "waited": WAITED, "laws": LAWS, "tails": TAILS, "edge": EDGE}
MODEL_SHA256 = digest(FIXTURES)
SOURCE_FILES = ("round6/qualifier.py", "round6/test_qualifier.py", "native_adapter.py",
                "native.rs", "native_head.rs", "analytic.py", "runtime.py",
                "round4/runtime_codec.py", "round4/runtime_owner.py", "round4/runtime_law.py",
                "round4/runtime_evidence.py", "round4/evidence/execute.py")


def append(path, item):
    with Path(path).open("a") as stream:
        stream.write(json.dumps(item, sort_keys=True, allow_nan=False) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def inventory(root):
    return {str(p.relative_to(root)): file_sha(p) for p in sorted(Path(root).rglob("*")) if p.is_file()}


class MeteredNative(Native):
    """Observe actual inherited requests, including rejected request time."""
    def __init__(self, binary, receipt, trace):
        super().__init__(binary, receipt)
        self.trace, self.attempts, self.attempt_wall_ns = Path(trace), 0, 0

    def _request(self, request):
        started = time.perf_counter_ns()
        item = {"request": request, "attempt": self.attempts + 1,
                "python_pid": os.getpid(), "native_pid": self._process.pid}
        try:
            result = super()._request(request)
            item.update(accepted=True, response=result)
            return result
        except Exception as error:
            item.update(accepted=False, error=type(error).__name__ + ": " + str(error))
            raise
        finally:
            elapsed = time.perf_counter_ns() - started
            self.attempts += 1
            self.attempt_wall_ns += elapsed
            append(self.trace, {**item, "attempt_wall_ns": elapsed})

    def meter(self):
        return {"successful_requests": self.calls, "original_sparse_ticks": self.original_sparse_ticks,
                "successful_roundtrip_ns": self.wall_ns, "attempted_requests": self.attempts,
                "attempted_roundtrip_ns": self.attempt_wall_ns, "native_pid": self._process.pid}


def worker(binary, receipt, job_path, output):
    """A genuinely fresh Python and native process reopens an existing owner."""
    job = json.loads(Path(job_path).read_text())
    with MeteredNative(binary, receipt, Path(output).with_suffix(".attempts.jsonl")) as native:
        owner = Owner(job["root"], job["identity"], MODEL_SHA256, native, job["mode"])
        cached = owner.step(WAITED, job["law"], 2)
        before = native.meter()
        continued = owner.step(WAITED, job["law"], 3, expected_checkpoint=job["checkpoint"])
        after = native.meter()
    result = {"pid": os.getpid(), "job_sha256": file_sha(job_path), "cached": cached,
              "before_continuation": before, "continued": continued, "native": after}
    write_json(output, result)


def qualify(binary, receipt, output):
    root = Path(output).resolve()
    root.mkdir(parents=True, exist_ok=False)
    source_root = Path(__file__).resolve().parents[1]
    sources = {name: file_sha(source_root / name) for name in SOURCE_FILES}
    build = json.loads(Path(receipt).read_text())
    if file_sha(binary) != BINARY_SHA256 or build["source_commit"] != SOURCE_COMMIT:
        raise ValueError("Exact registered original native artifact required")
    started, cpu = time.perf_counter_ns(), time.process_time_ns()
    start = {"schema": SCHEMA, "pid": os.getpid(), "started_ns": time.time_ns(),
             "sources_sha256": sources, "binary_sha256": file_sha(binary),
             "build_receipt_sha256": file_sha(receipt), "original_source_commit": SOURCE_COMMIT,
             "new_build": False, "new_execution": True, "fixtures": FIXTURES,
             "model_sha256": MODEL_SHA256, "scientific_confirmation_used": False}
    write_json(root / "STARTED.json", start)
    records, checks, failures, recovery_jobs = [], [], [], []

    def require(name, condition, **details):
        item = {"name": name, "passed": bool(condition), **details}
        append(root / "CHECKS.jsonl", item)
        checks.append(item)
        if not condition:
            raise AssertionError(name)

    def rejected(name, operation, owner, native, exception=(ValueError, RuntimeError)):
        before, attempts = inventory(owner.root), native.attempts
        try:
            operation()
        except exception as error:
            require(name, inventory(owner.root) == before and native.attempts == attempts,
                    error=str(error), owner=owner.subject, state_sha256=digest(before),
                    new_native_attempts=native.attempts - attempts)
        else:
            raise AssertionError("Expected rejection: " + name)

    def release_checks(row, label):
        law, components = row["law"], len(row["source_law"]["weights"])
        require(label + ": native receiver", row["receiver_reopened_before_native"]
                and not row["policy_receives_encoder_residual"]
                and len(row["native"]) == components
                and all(r["original_neuron_runtime"] and r["abstain"]
                        and r["legacy_runtime_confidence_ppm"] == 0 for r in row["native"]))
        require(label + ": positive Q24", min(law["probabilities_q24"]) >= 1
                and sum(law["probabilities_q24"]) == Q24
                and max(abs(a - b) for a, b in zip(law["probabilities"], law["native_mixture_probabilities"])) <= 3 / Q24)
        require(label + ": actual native CDF", row["native_max_cdf_error"] < 2e-15
                and law["native_vs_reference_max_absolute_error"] < 2e-15)
        require(label + ": limited authority", row["authority"] == "DENY_ALL" and not row["cross_owner_atomicity"])

    try:
        with MeteredNative(binary, receipt, root / "NATIVE_ATTEMPTS.jsonl") as native:
            for mode in MODES:
                for k, law in enumerate(LAWS, 1):
                    label = f"{mode}/K{k}"
                    identity = [SCHEMA, "ordinary", mode, k]
                    owner = Owner(root / "owners", identity, MODEL_SHA256, native, mode)
                    first = owner.step(PUBLIC, law, 1)
                    second = owner.step(WAITED, law, 2, expected_checkpoint=first["checkpoint_after"])
                    records.extend([first, second])
                    for row in (first, second):
                        release_checks(row, label + f"/stage{row['sequence']}")
                    rejected(label + ": stale checkpoint", lambda: owner.step(WAITED, law, 3), owner, native)
                    rejected(label + ": changed duplicate", lambda: owner.step({**PUBLIC, "initial": .26}, law, 1), owner, native)
                    rejected(label + ": component-count change", lambda: owner.step(WAITED, LAWS[2-k], 3,
                             expected_checkpoint=second["checkpoint_after"]), owner, native)
                    recovery_jobs.append({"root": str(root / "owners"), "identity": identity,
                        "mode": mode, "k": k, "law": law, "checkpoint": second["checkpoint_after"], "cached": second})

                    bounded = Owner(root / "owners", [SCHEMA, "bounded", mode, k], MODEL_SHA256, native, mode)
                    checkpoint = ZERO
                    for sequence in range(1, 17):
                        row = bounded.step(PUBLIC, law, sequence, expected_checkpoint=checkpoint)
                        checkpoint = row["checkpoint_after"]
                        records.append(row)
                    require(label + ": all sixteen actual requests", row["sequence"] == 16
                            and all(r["sequence"] == 16 for r in row["native"]))
                    rejected(label + ": seventeenth request", lambda: bounded.step(PUBLIC, law, 17,
                             expected_checkpoint=checkpoint), bounded, native)

                    for stage in ("after_packet", "after_first_native", "after_native", "after_commit"):
                        interrupted = Owner(root / "owners", [SCHEMA, stage, mode, k], MODEL_SHA256, native, mode)
                        before = native.calls
                        try:
                            interrupted.step(PUBLIC, law, 1, fail_stage=stage)
                        except RuntimeError as error:
                            failure = {"mode": mode, "components": k, "stage": stage, "owner": interrupted.subject,
                                       "error": str(error), "actual_native_calls": native.calls - before,
                                       "files_sha256": inventory(interrupted.root)}
                            failures.append(failure)
                            append(root / "INTERRUPTIONS.jsonl", failure)
                        else:
                            raise AssertionError("Interruption was not injected")
                        expected = {"after_packet": 0, "after_first_native": 1, "after_native": k, "after_commit": k}[stage]
                        require(label + ": " + stage + " actual native count", native.calls - before == expected)
                        if stage == "after_commit":
                            saved = read_document(interrupted.root / "state.json")["receipts"][0]
                            attempts = native.attempts
                            cached = interrupted.step(PUBLIC, law, 1)
                            require(label + ": lost acknowledgement exact cached receipt", cached == saved and native.attempts == attempts)
                            records.append(cached)
                        else:
                            require(label + ": partial transaction retained", (interrupted.root / "pending.json").exists()
                                    and not (interrupted.root / "state.json").exists())
                            rejected(label + ": " + stage + " retry fails closed",
                                     lambda: interrupted.step(PUBLIC, law, 1), interrupted, native, RuntimeError)

                    encoder, decoder = Encoder(mode), Decoder(mode)
                    packet = encoder.encode(law, 1, 1.0)
                    decoder.apply(packet)
                    for name, bad in (("CRC", packet[:-5] + bytes([packet[-5] ^ 1]) + packet[-4:]),
                                      ("duplicate", packet)):
                        state = decoder.snapshot()
                        try:
                            decoder.apply(bad)
                        except ValueError as error:
                            require(label + ": decoder " + name, decoder.snapshot() == state,
                                    error=str(error), rejected_packet_base64=base64.b64encode(bad).decode())
                        else:
                            raise AssertionError("Decoder accepted invalid " + name)
                    other = Encoder(mode)
                    other.encode(LAWS[2-k], 1, 1.0)
                    changed = other.encode(LAWS[2-k], 2, 1.0, "propagation")
                    state = decoder.snapshot()
                    try:
                        decoder.apply(changed)
                    except ValueError:
                        require(label + ": decoder component-count change", decoder.snapshot() == state)
                    else:
                        raise AssertionError("Decoder accepted changed component count")
                    for sequence in range(2, 17):
                        packet = encoder.encode(law, sequence, 1.0, "propagation")
                        decoder.apply(packet)
                    header = list(HEADER.unpack(packet[:HEADER.size]))
                    header[5] = 17
                    body = HEADER.pack(*header) + packet[HEADER.size:-4]
                    seventeenth = body + struct.pack("<I", zlib.crc32(body))
                    state = decoder.snapshot()
                    try:
                        decoder.apply(seventeenth)
                    except ValueError:
                        require(label + ": decoder seventeenth request", decoder.snapshot() == state)
                    else:
                        raise AssertionError("Decoder accepted seventeenth request")

                for i, law in enumerate([*TAILS, EDGE]):
                    owner = Owner(root / "owners", [SCHEMA, "tail", mode, i], MODEL_SHA256, native, mode)
                    row = owner.step(PUBLIC, law, 1)
                    records.append(row)
                    release_checks(row, f"{mode}/tail{i}")
                    require(f"{mode}/tail{i}: finite physical log probabilities",
                            all(math.isfinite(v) for v in row["law"]["physical_log_probabilities"]))
                    if i < len(TAILS):
                        require(f"{mode}/tail{i}: raw zero retained", min(row["law"]["raw_probabilities_q24"]) == 0)

            native_edges = []
            for i, (mean, variance) in enumerate(((-8., 8.), (8., 1 / Q24))):
                directory = root / "native_edges" / str(i)
                row = native.typed(f"{SCHEMA}/native-edge/{i}", directory, mean, variance, -.5, .5,
                                   expected_checkpoint=ZERO)
                native_edges.append(row)
                require(f"native exact edge {i}", row["head"]["parameters_q24_decoded"][:2] == [mean, variance])
                before, calls = inventory(directory), native.calls
                try:
                    native.typed(f"{SCHEMA}/native-edge/{i}", directory, mean, variance, -.5, .5,
                                 expected_checkpoint=ZERO)
                except ValueError as error:
                    require(f"native stale edge {i}", inventory(directory) == before and native.calls == calls,
                            error=str(error))
                else:
                    raise AssertionError("Actual native accepted stale checkpoint")
            in_process = native.meter()

        recoveries = []
        for job in recovery_jobs:
            tag = f"{job['mode']}_K{job['k']}"
            job_path, result_path = root / f"RESTART_{tag}_JOB.json", root / f"RESTART_{tag}.json"
            write_json(job_path, job)
            child_start, child_cpu = time.perf_counter_ns(), resource.getrusage(resource.RUSAGE_CHILDREN)
            completed = subprocess.run([sys.executable, "-m", "experiments.analytic_event_neuron.round6.qualifier",
                "worker", "--binary", str(binary), "--receipt", str(receipt), "--job", str(job_path),
                "--output", str(result_path)], capture_output=True, text=True)
            (root / f"RESTART_{tag}.log").write_text(completed.stdout + completed.stderr)
            usage = resource.getrusage(resource.RUSAGE_CHILDREN)
            execution = {"returncode": completed.returncode, "wall_ns": time.perf_counter_ns() - child_start,
                         "child_cpu_seconds": usage.ru_utime + usage.ru_stime - child_cpu.ru_utime - child_cpu.ru_stime}
            write_json(root / f"RESTART_{tag}_EXECUTION.json", execution)
            require(tag + ": subprocess succeeded", completed.returncode == 0)
            result = json.loads(result_path.read_text())
            require(tag + ": fresh Python and native", result["pid"] != os.getpid()
                    and result["native"]["native_pid"] != in_process["native_pid"])
            require(tag + ": exact duplicate after restart", result["cached"] == job["cached"]
                    and result["before_continuation"]["attempted_requests"] == 0)
            require(tag + ": continuation after restart", result["native"]["successful_requests"] == job["k"]
                    and result["continued"]["checkpoint_before"] == job["checkpoint"]
                    and result["continued"]["sequence"] == 3
                    and result["continued"]["law"] == job["cached"]["law"]
                    and all(r["sequence"] == 3 for r in result["continued"]["native"]))
            records.append(result["continued"])
            recoveries.append({"mode": job["mode"], "components": job["k"], "native": result["native"], **execution})

        archive = EvidenceZip(root / "OWNERS.zip")
        archive.append(root / "owners", "owners")
        archive.append(root / "native_edges", "native_edges")
        archived = archive.finish()
        with gzip.open(root / "FORECASTS.json.gz", "xt") as stream:
            json.dump({"owners": records, "native_edges": native_edges}, stream, sort_keys=True, allow_nan=False)
        require("source binding stable throughout execution", sources == {name: file_sha(source_root / name) for name in SOURCE_FILES})
        report = {"schema": SCHEMA, "passed": True, "started_sha256": file_sha(root / "STARTED.json"),
                  "checks": len(checks), "owner_receipts": len(records), "modes": list(MODES),
                  "component_counts": [1, 2], "interruption_cases": len(failures), "fresh_processes": len(recoveries),
                  "maximum_owner_sequence": 16, "in_process_native": in_process, "recoveries": recoveries,
                  "archive": archived, "sources_sha256": sources, "binary_sha256": BINARY_SHA256,
                  "cross_owner_atomicity": False, "production_activation": False, "new_build": False,
                  "qualification_used_confirmation": False, "latency_and_memory_digests_exact_replay_claimed": False,
                  "body_wall_ns": time.perf_counter_ns() - started, "parent_cpu_ns": time.process_time_ns() - cpu,
                  "full_process_tree_cost": "external execute wrapper; body CPU excludes subprocess CPU",
                  "evidence_sha256": inventory(root)}
        write_json(root / "RESULT.json", report)
        return report
    except Exception as error:
        write_json(root / "FAILED.json", {"passed": False, "error": type(error).__name__ + ": " + str(error),
                   "completed_checks": len(checks), "sources_sha256": sources})
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("qualify", "worker"))
    for name in ("binary", "receipt", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--job", type=Path)
    args = parser.parse_args()
    if args.operation == "worker":
        worker(args.binary.resolve(), args.receipt.resolve(), args.job.resolve(), args.output.resolve())
    else:
        result = qualify(args.binary.resolve(), args.receipt.resolve(), args.output.resolve())
        print(json.dumps({key: result[key] for key in ("passed", "checks", "owner_receipts", "fresh_processes")}))


if __name__ == "__main__":
    main()
