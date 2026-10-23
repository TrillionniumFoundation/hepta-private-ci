"""Development-only independent arithmetic audit of the real native process.

This script does not import the planner, the model, or heldout data. It supplies
finite action tables, independently calculates budget-constrained decisions,
and verifies every response from one persistent HEPTA owner process. Neural
feedback/model execution is covered separately by the experiment rollout.
"""

import argparse
import gzip
import hashlib
import json
from pathlib import Path
import random
import subprocess
import time


ROOT = Path(__file__).resolve().parents[3]


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def run_audit(binary, *, sessions=256, seed=7301):
    """Return the independently checked receipt and complete protocol trace."""
    start = time.perf_counter()
    process_start = time.process_time()
    binary = Path(binary).resolve(strict=True)
    rng = random.Random(seed)
    requests, expected = [], []
    choices = {"emit": 0, "refine": 0}
    errors = {}

    def request(fields, result):
        requests.append("\t".join(map(str, fields)))
        expected.append(list(map(str, result)))
        if result[0] == "ERR":
            errors[result[1]] = errors.get(result[1], 0) + 1

    def error(fields, name):
        request(fields, ["ERR", name])

    latent = sha256(b"development initial latent")
    error(["CHOOSE", 1, 0, 0, 0, latent, "emit", 0, 10], "InvalidProtocol")
    for sid, budget, depth, q, digest in [
        (1, 0, 3, 0, latent), (0, 10, 3, 0, latent),
        (1, 10, 65, 0, latent), (1, 10, 3, 65_536, latent),
        (1, 10, 3, 0, "0" * 64),
    ]:
        error(["INIT", sid, budget, 10, 6, depth, q, digest], "InvalidConfiguration")

    settings = []
    for _ in range(sessions):
        emit_cost, refine_cost = rng.randint(1, 1000), rng.randint(1, 1000)
        budget = emit_cost + rng.randint(0, 3) * refine_cost + rng.randrange(refine_cost)
        settings.append((budget, emit_cost, refine_cost, rng.randint(0, 3)))
    # The independent Python integer oracle must agree when u64 addition would
    # overflow in a native feasibility calculation.
    settings.append(((1 << 64) - 1, 10, (1 << 64) - 1, 3))

    for sid, (budget, emit_cost, refine_cost, max_depth) in enumerate(settings, 1):
        q = rng.randrange(8)
        digest = sha256(f"initial:{seed}:{sid}".encode())
        remaining, version, depth = budget, 0, 0
        init = ["INIT", sid, budget, emit_cost, refine_cost, max_depth, q, digest]
        request(init, ["OK", "INIT", sid, version, remaining, depth, "ready"])
        error(init, "PendingExecution")
        while True:
            base = ["CHOOSE", sid, version, depth, q, digest]
            error(base + ["emit", "nan", emit_cost], "NonFiniteValue")
            error(base + ["emit", 0, emit_cost, "refine", "inf", refine_cost], "NonFiniteValue")
            error(base + ["emit", 0, emit_cost, "refine", "-inf", refine_cost], "NonFiniteValue")
            error(base + ["emit", 0, 0], "CostMismatch")
            error(base + ["emit", 0, emit_cost, "emit", 1, emit_cost], "InvalidTable")
            error(base + ["refine", 0, refine_cost], "InvalidTable")
            error(base[:2] + [version + 1] + base[3:] + ["emit", 0, emit_cost], "SnapshotMismatch")
            error(base[:5] + [sha256(b"wrong latent")] + ["emit", 0, emit_cost], "SnapshotMismatch")

            stop = rng.uniform(-3, 1)
            continuation = rng.choice([
                stop, stop + 0.5e-12, stop + 1e-12, stop + 2e-12,
                stop - 1.0, stop + 1.0, -1e300, 1e300,
            ])
            # Independent arithmetic: unlimited Python integers, immutable local
            # variables, and no call to the native/Python planner implementation.
            feasible = depth < max_depth and remaining >= emit_cost + refine_cost
            action = "refine" if feasible and continuation > stop + 1e-12 else "emit"
            value = continuation if action == "refine" else stop
            table = ["emit", repr(stop), emit_cost, "refine", repr(continuation), refine_cost]
            if sid % 2:
                table = table[3:] + table[:3]
            remaining -= refine_cost if action == "refine" else emit_cost
            version += 1
            depth += int(action == "refine")
            choices[action] += 1
            request(base + table, ["OK", "CHOOSE", sid, version, remaining, depth, action, repr(value)])
            error(base + table, "PendingExecution")
            if action == "refine":
                digest = sha256(f"observed:{seed}:{sid}:{depth}".encode())
                refined = ["REFINED", sid, version, depth, q, digest]
                error(refined[:2] + [version - 1] + refined[3:], "SnapshotMismatch")
                request(refined, ["OK", "REFINED", sid, version, remaining, depth, "ready"])
                continue
            outputs = [sha256(f"actual-fixture:{sid}:{m}".encode()) for m in range(4)]
            error(["EMITTED", sid, version + 1] + outputs, "SnapshotMismatch")
            error(["EMITTED", sid, version] + ["0" * 64] * 4, "InvalidOutputs")
            request(["EMITTED", sid, version] + outputs,
                    ["OK", "EMITTED", sid, version, remaining, depth, "sealed"])
            error(base + table, "Sealed")
            error(["EMITTED", sid, version] + outputs, "Sealed")
            error(init, "SessionSequence")
            break

    stdin = "\n".join(requests) + "\n"
    result = subprocess.run([str(binary)], input=stdin, text=True,
                            capture_output=True, timeout=30, check=False)
    if result.returncode != 0:
        raise AssertionError(f"native exit {result.returncode}: {result.stderr}")
    responses = result.stdout.splitlines()
    if len(responses) != len(expected):
        raise AssertionError(("response count", len(responses), len(expected)))
    for index, (response, wanted) in enumerate(zip(responses, expected)):
        fields = response.split("\t")
        if wanted[:2] == ["OK", "CHOOSE"]:
            valid = len(fields) == 8 and fields[:7] == wanted[:7]
            valid = valid and float(fields[7]) == float(wanted[7])
        else:
            valid = fields == wanted
        if not valid:
            raise AssertionError({"index": index, "request": requests[index],
                                  "actual": fields, "expected": wanted})
    if not all(choices.values()):
        raise AssertionError("audit must exercise both real process action branches")
    source_paths = [
        "codex-rs/hepta-ndu/Cargo.toml", "codex-rs/Cargo.lock",
        "codex-rs/hepta-ndu/BUILD.bazel", "codex-rs/hepta-ndu/src/lib.rs",
        "codex-rs/hepta-ndu/src/feedback_generation.rs",
        "codex-rs/hepta-ndu/src/feedback_generation_protocol.rs",
        "codex-rs/hepta-ndu/src/feedback_generation_tests.rs",
        "codex-rs/hepta-ndu/src/bin/ndu-feedback-generation.rs",
        str(Path(__file__).resolve().relative_to(ROOT)),
    ]
    receipt = {
        "schema": "hepta.feedback-native-parity.v1",
        "scope": "development finite action-table and persistent-process parity; no neural, production runtime, or heldout claim",
        "seed": seed, "randomized_sessions": sessions,
        "additional_u64_overflow_session": 1,
        "persistent_processes": 1, "returncode": result.returncode,
        "requests_checked": len(requests), "choices": choices,
        "expected_errors_checked": errors,
        "mismatches": 0, "binary": str(binary),
        "binary_sha256": sha256(binary.read_bytes()),
        "source_sha256": {p: sha256((ROOT / p).read_bytes()) for p in source_paths},
        "stdin_sha256": sha256(stdin.encode()),
        "stdout_sha256": sha256(result.stdout.encode()),
        "stderr": result.stderr,
        "audit_wall_seconds": time.perf_counter() - start,
        "audit_python_cpu_seconds": time.process_time() - process_start,
        "native_child_cpu_seconds": "not separately measured by this portable subprocess audit",
    }
    transcript = "".join(json.dumps({"request": request, "response": response},
                                   sort_keys=True) + "\n"
                         for request, response in zip(requests, responses))
    return receipt, transcript


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()
    receipt, transcript = run_audit(args.binary)
    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    trace_path = args.receipt.with_suffix(".transcript.jsonl.gz")
    trace_bytes = gzip.compress(transcript.encode(), mtime=0)
    trace_path.write_bytes(trace_bytes)
    receipt["transcript_artifact"] = trace_path.name
    receipt["transcript_gzip_sha256"] = sha256(trace_bytes)
    args.receipt.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    print(json.dumps({k: receipt[k] for k in
                     ("requests_checked", "choices", "mismatches", "audit_wall_seconds")}))


if __name__ == "__main__":
    main()
