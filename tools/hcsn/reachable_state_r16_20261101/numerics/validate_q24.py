"""Compile the integer executable, replay a causal R15 tape, audit and restart.

This is a numerical qualification of one frozen finite operator. It is not
production-owner integration, policy optimality, a performance comparison,
energy measurement, network recovery, or a statistical quality confirmation.
"""

import argparse
import gzip
import hashlib
import json
from pathlib import Path
import resource
import shutil
import struct
import subprocess
import tempfile
import time

import numpy as np

from ...addressed_decision_r15_20261101.law import Law


SCALE = 1 << 24
SOURCE_SCALE = 1 << 80
DT = [0., 1e-6, .05, .15, .45, .75, 1.05, 2.1]
SEED = 161101703
HERE = Path(__file__).resolve().parent


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def source_weights(row, support=None):
    result = []
    support = np.asarray(row) > 0 if support is None else support
    for value, possible in zip(row, support):
        value = float(value)
        if not np.isfinite(value) or value < 0:
            raise ValueError("Unrepresentable reference probability")
        numerator, denominator = value.as_integer_ratio()
        if value > 0 and not possible:
            raise ValueError("Positive reference outside structural support")
        result.append(max(1, numerator * SOURCE_SCALE // denominator) if possible else 0)
    return result


def quantize_python(weights):
    """Independent integer transcription, also returning an exact L1 radius."""
    total = sum(weights)
    quotients = [divmod(weight * SCALE, total) for weight in weights]
    counts = [value[0] for value in quotients]
    remaining = SCALE - sum(counts)
    ranking = sorted(range(len(weights)), key=lambda index: (-quotients[index][1], index))
    for index in ranking[:remaining]:
        counts[index] += 1
    discrepancy = sum(abs(count * total - weight * SCALE)
                      for count, weight in zip(counts, weights))
    return counts, (discrepancy + total - 1) // total


def model_text(law):
    priors = [law.initial_prior(content) for content in range(4)]
    kernels = [law.transition(dt) for dt in DT]
    emissions = [law.E_read, law.E_refresh]
    reachable = (law.Q > 0) | np.eye(40, dtype=bool)
    for intermediate in range(40):
        reachable |= reachable[:, intermediate, None] & reachable[None, intermediate, :]
    lines = ["HCSN_Q24_MODEL_V1", law.identity, f"40 4 4 {len(kernels)} 2"]
    weights = dict(priors=[], kernels=[], emissions=[])
    source_conversion_error = 0.
    for name, matrices in (("priors", [priors]), ("kernels", kernels), ("emissions", emissions)):
        for matrix_index, matrix in enumerate(matrices):
            if name == "kernels":
                lines.append(str(round(DT[matrix_index] * 1e6)))
            if name == "emissions":
                lines.append(str(matrix.shape[1]))
            matrix_weights = []
            for row_index, row in enumerate(matrix):
                support = (reachable[row_index] if name == "kernels" and DT[matrix_index] > 0
                           else np.asarray(row) > 0)
                row_weights = source_weights(row, support)
                converted = np.array([weight / sum(row_weights) for weight in row_weights])
                source_conversion_error = max(source_conversion_error,
                                              float(np.sum(np.abs(converted - row))))
                lines.append(" ".join(map(str, row_weights)))
                matrix_weights.append(row_weights)
            weights[name].append(matrix_weights)
    weights["priors"] = weights["priors"][0]
    return ("\n".join(lines) + "\n").encode(), weights, source_conversion_error


def causal_tape(law, cycles=256, seed=SEED):
    rng = np.random.default_rng(seed)
    belief = np.array([law.initial_prior(content) for content in range(4)])
    hidden = [int(rng.choice(40, p=row / row.sum())) for row in belief]
    operations, reference, hidden_records = [], [belief.copy()], []
    for cycle in range(cycles):
        kernel_id = int(rng.integers(len(DT)))
        transition = law.transition(DT[kernel_id])
        belief = belief @ transition
        hidden = [int(rng.choice(40, p=transition[state] / transition[state].sum()))
                  for state in hidden]
        operations.append(f"T {kernel_id}")
        reference.append(belief.copy())
        key, quality = int(rng.integers(4)), int(rng.integers(2))
        emission = law.E_read if quality == 0 else law.E_refresh
        token = int(rng.choice(emission.shape[1], p=emission[hidden[key]]))
        unnormalized = belief[key] * emission[:, token]
        belief[key] = unnormalized / unnormalized.sum()
        operations.append(f"O {key} {quality} {token}")
        reference.append(belief.copy())
        hidden_records.append(dict(cycle=cycle, kernel=kernel_id, key=key,
                                   quality=quality, token=token, hidden=hidden.copy()))
        if cycle % 7 == 3:
            key, content = int(rng.integers(4)), int(rng.integers(4))
            phase = belief[key].reshape(10, 4).sum(axis=1)
            belief[key] = 0.
            belief[key, content::4] = phase
            hidden[key] = hidden[key] // 4 * 4 + content
            operations.append(f"W {key} {content}")
            reference.append(belief.copy())
    return operations, np.array(reference), hidden_records


def integer_reference(weights, operations):
    state_and_bounds = [quantize_python(row) for row in weights["priors"]]
    state = [row for row, _ in state_and_bounds]
    bounds = [radius for _, radius in state_and_bounds]
    support = np.array(weights["priors"], dtype=object) > 0
    kernels = [[quantize_python(row) for row in matrix] for matrix in weights["kernels"]]
    emissions = [[quantize_python(row) for row in matrix] for matrix in weights["emissions"]]
    records = [(np.array(state), bounds.copy(), support.copy())]
    for operation in operations:
        values = operation.split()
        if values[0] == "T":
            kernel = kernels[int(values[1])]
            row_radius = max(radius for _, radius in kernel)
            next_state, next_bounds = [], []
            for key in range(4):
                raw = [sum(state[key][i] * kernel[i][0][j] for i in range(40))
                       for j in range(40)]
                counts, radius = quantize_python(raw)
                next_state.append(counts)
                next_bounds.append(min(2 * SCALE, bounds[key] + row_radius + radius))
            state, bounds = next_state, next_bounds
            mask = np.array(weights["kernels"][int(values[1])], dtype=object) > 0
            support = support.astype(int) @ mask.astype(int) > 0
        elif values[0] == "O":
            key, emission_id, token = map(int, values[1:])
            emission = emissions[emission_id]
            raw = [state[key][i] * emission[i][0][token] for i in range(40)]
            counts, radius = quantize_python(raw)
            numerator = 2 * (bounds[key] + max(r for _, r in emission)) * SCALE ** 2
            amplified = (numerator + sum(raw) - 1) // sum(raw)
            state[key] = counts
            bounds[key] = min(2 * SCALE, amplified + radius)
            support[key] &= np.array(weights["emissions"][emission_id], dtype=object)[:, token] > 0
        elif values[0] == "W":
            key, content = map(int, values[1:])
            phase = [sum(state[key][4 * i:4 * i + 4]) for i in range(10)]
            state[key] = [0] * 40
            state[key][content::4] = phase
            possible_phase = support[key].reshape(10, 4).any(axis=1)
            support[key] = False
            support[key, content::4] = possible_phase
        records.append((np.array(state), bounds.copy(), support.copy()))
    return records


def child_run(command, receipts, name):
    started = time.perf_counter()
    before = resource.getrusage(resource.RUSAGE_CHILDREN)
    result = subprocess.run(list(map(str, command)), capture_output=True, text=True)
    after = resource.getrusage(resource.RUSAGE_CHILDREN)
    receipts.append(dict(name=name, returncode=result.returncode,
        wall_seconds=time.perf_counter() - started,
        child_cpu_seconds=(after.ru_utime + after.ru_stime - before.ru_utime - before.ru_stime),
        stdout_sha256=sha256(result.stdout.encode()), stderr=result.stderr))
    return result


def check_checkpoint(bytes_, model_digest, states, support, completed):
    if bytes_[:8] != b"HQ24CK03" or bytes_[8:40].hex() != model_digest:
        raise AssertionError("Native checkpoint identity mismatch")
    if sha256(bytes_[:-32]) != bytes_[-32:].hex():
        raise AssertionError("Native SHA-256 differs from hashlib")
    addresses, width = struct.unpack_from("<II", bytes_, 40)
    if (addresses, width) != (4, 40) or struct.unpack_from("<Q", bytes_, 48)[0] != completed:
        raise AssertionError("Checkpoint counters/dimensions do not match")
    for key in range(4):
        decoded = list(struct.unpack_from("<40I", bytes_, 68 + key * 169))
        if decoded != states[key]:
            raise AssertionError("Checkpoint state differs from native output")
        packed = bytes_[228 + key * 169:233 + key * 169]
        possible = [bool(packed[index // 8] & (1 << (index % 8))) for index in range(40)]
        if possible != support[key]:
            raise AssertionError("Checkpoint structural support differs")


def validate(output, rustc, seed):
    started = time.process_time()
    receipts = []
    output.mkdir(parents=True, exist_ok=True)
    law = Law()
    model, weights, conversion_error = model_text(law)
    operations, reference, hidden = causal_tape(law, seed=seed)
    integer = integer_reference(weights, operations)
    model_path, ops_path = output / "q24_model.txt", output / "q24_operations.txt"
    model_path.write_bytes(model)
    ops_path.write_text("\n".join(operations) + "\n")
    (output / "q24_world.json.gz").write_bytes(gzip.compress(
        json.dumps(hidden, sort_keys=True, separators=(",", ":")).encode(), mtime=0))
    with tempfile.TemporaryDirectory(prefix="hcsn-r16-q24-") as temporary:
        temporary = Path(temporary)
        binary, test_binary = temporary / "q24", temporary / "q24-tests"
        compiler = [rustc, "--edition=2024", "-D", "warnings"]
        build = child_run(compiler + ["-O", HERE / "q24_main.rs", "-o", binary], receipts, "compile_native")
        test_build = child_run(compiler + ["--test", HERE / "q24_main.rs", "-o", test_binary], receipts, "compile_tests")
        if build.returncode or test_build.returncode:
            raise RuntimeError(build.stderr + test_build.stderr)
        tests = child_run([test_binary, "--nocapture"], receipts, "rust_tests")
        if tests.returncode:
            raise RuntimeError(tests.stdout + tests.stderr)
        (output / "RUST_TESTS.log").write_text(tests.stdout)
        native = child_run([binary, model_path, ops_path, temporary / "full.ckpt", 2 * SCALE],
                           receipts, "full_diagnostic_tape")
        if native.returncode:
            raise RuntimeError(native.stderr)
        (output / "q24_native_trace.jsonl.gz").write_bytes(gzip.compress(native.stdout.encode(), mtime=0))
        raw = [json.loads(line) for line in native.stdout.splitlines()]
        states = raw[:-1]
        if len(states) != len(reference):
            raise AssertionError("Incomplete native tape")
        absolute_errors, radius_violations, answer_changes, retained_zero_counts = [], 0, 0, 0
        for native_state, expected_float, (expected_counts, expected_bounds, expected_support) in zip(states, reference, integer):
            actual = np.array(native_state["counts"], dtype=np.int64)
            support = np.array(native_state["support"], dtype=bool)
            if (not np.array_equal(actual, expected_counts)
                    or native_state["l1_bound_units"] != expected_bounds
                    or not np.array_equal(support, expected_support)):
                raise AssertionError("Rust/Python integer mismatch")
            if not np.all(actual.sum(axis=1) == SCALE):
                raise AssertionError("Integer mass loss")
            if np.any((expected_float > 0) & ~support):
                raise AssertionError("Positive finite-model structural support deleted")
            retained_zero_counts += int(np.count_nonzero(support & (actual == 0)))
            error = np.sum(np.abs(actual / SCALE - expected_float), axis=1)
            absolute_errors.extend(error.tolist())
            radius_violations += int(np.count_nonzero(error > np.array(expected_bounds) / SCALE + 1e-12))
            float_answers = np.argmax(expected_float.reshape(4, 10, 4).sum(axis=1), axis=1)
            integer_answers = np.argmax(actual.reshape(4, 10, 4).sum(axis=1), axis=1)
            answer_changes += int(np.count_nonzero(float_answers != integer_answers))
        checkpoint = (temporary / "full.ckpt").read_bytes()
        check_checkpoint(checkpoint, sha256(model), states[-1]["counts"],
                         states[-1]["support"], len(operations))
        (output / "q24_final_checkpoint.bin").write_bytes(checkpoint)
        split = len(operations) // 2
        prefix, suffix = temporary / "prefix.txt", temporary / "suffix.txt"
        prefix.write_text("\n".join(operations[:split]) + "\n")
        suffix.write_text("\n".join(operations[split:]) + "\n")
        first = child_run([binary, model_path, prefix, temporary / "half.ckpt", 2 * SCALE], receipts, "prefix_process")
        second = child_run([binary, model_path, suffix, temporary / "resumed.ckpt", 2 * SCALE,
                            temporary / "half.ckpt"], receipts, "resumed_process")
        if first.returncode or second.returncode:
            raise RuntimeError(first.stderr + second.stderr)
        resumed = [json.loads(line) for line in second.stdout.splitlines()][:-1]
        resume_equal = (resumed[1:] == states[split + 1:]
                        and (temporary / "resumed.ckpt").read_bytes() == checkpoint)
        strict = child_run([binary, model_path, ops_path, temporary / "strict.ckpt", SCALE // 100],
                           receipts, "strict_one_percent_guard")
        strict_rows = [json.loads(line) for line in strict.stdout.splitlines()]
        strict_checkpoint_written = (temporary / "strict.ckpt").exists()
        empty = temporary / "empty.txt"
        empty.write_text("")
        restart_strict = child_run([binary, model_path, empty, temporary / "restart.ckpt", SCALE // 100,
                                   temporary / "full.ckpt"], receipts, "restart_cannot_reset_error_budget")
        bad_cases = {}
        corrupt = bytearray(checkpoint)
        corrupt[100] ^= 1
        for name, data in (("checksum", corrupt), ("truncated", checkpoint[:-1])):
            source = temporary / f"{name}.ckpt"
            source.write_bytes(data)
            result = child_run([binary, model_path, empty, temporary / "bad.ckpt", 2 * SCALE, source],
                               receipts, "reject_" + name)
            bad_cases[name] = dict(rejected=result.returncode != 0, reason=result.stderr.strip())
        changed_model = temporary / "changed_model.txt"
        changed_model.write_bytes(model + b"\n")
        result = child_run([binary, changed_model, empty, temporary / "bad_model.ckpt", 2 * SCALE,
                            temporary / "full.ckpt"], receipts, "reject_changed_model_bytes")
        bad_cases["model"] = dict(rejected=result.returncode != 0, reason=result.stderr.strip())
    result = dict(schema="hcsn-r16-native-q24-v1", source_law_identity=law.identity,
        source_operator_identity=law.operator_identity, model_bytes_sha256=sha256(model),
        environment=dict(rustc=str(rustc), numpy=np.__version__),
        probability_scale=SCALE, source_fixture_scale=SOURCE_SCALE,
        source_conversion_l1_max=conversion_error,
        causal_tape_seed=seed, events=len(operations), addresses=4,
        checked_address_states=len(states) * 4, checked_probability_counts=len(states) * 160,
        float_reference_l1_max=max(absolute_errors), float_reference_l1_p99=float(np.quantile(absolute_errors, .99)),
        content_argmax_disagreements=answer_changes, certificate_violations=radius_violations,
        structurally_possible_zero_count_coordinates=retained_zero_counts,
        process_restart_bitwise_equal=resume_equal,
        strict_guard=dict(maximum_l1_units=SCALE // 100, maximum_l1=(SCALE // 100) / SCALE,
                          returncode=strict.returncode,
                          completed=last["completed"] if (last := strict_rows[-1]) else 0,
                          reason=strict.stderr.strip(),
                          checkpoint_written=strict_checkpoint_written),
        restart_does_not_reset_error_budget=dict(rejected=restart_strict.returncode != 0,
                                                reason=restart_strict.stderr.strip()),
        invalid_checkpoints=bad_cases, receipts=receipts,
        production_activation=False, continuous_model_convergence_claim=False,
        scope="Q24 replay/filter/write and four-address memory checkpoint for one R15 finite operator; no native planner, owner integration, network, energy or quality claim.",
        python_cpu_seconds=time.process_time() - started,
        child_cpu_seconds=sum(r["child_cpu_seconds"] for r in receipts),
        source_hashes={p.name: sha256(p.read_bytes()) for p in sorted(HERE.glob("q24_*.rs"))})
    result["gates"] = dict(integer_reference_exact=True, mass_and_structural_support=True,
        float_reference_l1_below_1e_minus_4=result["float_reference_l1_max"] < 1e-4,
        certified_radius_valid=radius_violations == 0, restart_exact=resume_equal,
        malformed_checkpoint_rejection=all(r["rejected"] for r in bad_cases.values()),
        strict_guard_refuses_without_reset=strict.returncode != 0 and restart_strict.returncode != 0)
    result["passed"] = all(result["gates"].values())
    (output / "Q24_VALIDATION.json").write_text(json.dumps(result, indent=2, sort_keys=True,
                                                         allow_nan=False) + "\n")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=SEED)
    parser.add_argument("--rustc", type=Path, default=Path(shutil.which("rustc") or
        "/tmp/trnm-original-budget-rustup/toolchains/1.95.0-x86_64-unknown-linux-gnu/bin/rustc"))
    arguments = parser.parse_args()
    result = validate(arguments.output.resolve(), arguments.rustc, arguments.seed)
    print(json.dumps({key: result[key] for key in ("passed", "events", "float_reference_l1_max",
        "certificate_violations", "content_argmax_disagreements", "strict_guard", "gates")}, sort_keys=True))
    raise SystemExit(0 if result["passed"] else 1)
