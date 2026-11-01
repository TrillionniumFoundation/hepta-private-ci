"""Independent exact-Fraction and saved-evidence audit; never executes formal tapes."""

from decimal import Decimal
from fractions import Fraction
import gzip
import hashlib
import io
import json
from pathlib import Path
import random
import struct
import tarfile
import time

import numpy as np

from .interval_replay import IntervalMemory, IntervalModel


HERE = Path(__file__).resolve().parent
SCALE, BUDGET = 2 ** 24, (2 ** 24) // 100
FIELDS = ("completed", "clock_ticks", "counts", "support", "l1_bound_units")


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def checked_payload(value):
    body = dict(value)
    assert body.pop("sha256") == digest(canonical(body).encode())
    return body


def exact_radius(cache, counts):
    answer = []
    for row, low, high in zip(counts, cache["lower"], cache["upper"]):
        error = sum(max(Fraction(q, SCALE) - Fraction(a), Fraction(b) - Fraction(q, SCALE))
                    for q, a, b in zip(row, low, high))
        units = error * SCALE
        answer.append(min(2 * SCALE, -(-units.numerator // units.denominator)))
    return answer


def fraction_cases():
    coordinates, certificates, restored = 0, 0, 0
    for case in range(24):
        rng = random.Random(918400 + case)
        states, addresses, classes = 6, 2, 3

        def weights(columns):
            row = [rng.randrange(7) if rng.random() > .4 else 0 for _ in range(columns)]
            if not any(row):
                row[rng.randrange(columns)] = 1
            return row

        initial = [weights(states) for _ in range(addresses)]
        transitions = [[weights(states) for _ in range(states)] for _ in range(2)]
        emissions = [[weights(3) for _ in range(states)] for _ in range(2)]
        lines = ["HCSN_Q24_MODEL_V1", "b" * 64, "6 2 3 2 2"]
        lines.extend(" ".join(map(str, row)) for row in initial)
        for ticks, matrix in zip([7, 11], transitions):
            lines.append(str(ticks))
            lines.extend(" ".join(map(str, row)) for row in matrix)
        for matrix in emissions:
            lines.append("3")
            lines.extend(" ".join(map(str, row)) for row in matrix)
        model = IntervalModel(("\n".join(lines) + "\n").encode())
        state = IntervalMemory(model)
        exact = [[Fraction(value, sum(row)) for value in row] for row in initial]
        kernels = [[[Fraction(value, sum(row)) for value in row] for row in matrix]
                   for matrix in transitions]
        likelihoods = [[[Fraction(value, sum(row)) for value in row] for row in matrix]
                       for matrix in emissions]
        for step in range(48):
            key, index = rng.randrange(addresses), rng.randrange(2)
            if step % 3 == 0:
                operation = f"T {index}"
                exact = [[sum(p[i] * kernels[index][i][j] for i in range(states))
                          for j in range(states)] for p in exact]
            elif step % 3 == 1:
                admissible = [token for token in range(3)
                              if sum(exact[key][i] * likelihoods[index][i][token]
                                     for i in range(states)) > 0]
                token = rng.choice(admissible)
                operation = f"O {key} {index} {token}"
                posterior = [exact[key][i] * likelihoods[index][i][token] for i in range(states)]
                evidence = sum(posterior)
                exact[key] = [value / evidence for value in posterior]
            else:
                content = rng.randrange(classes)
                operation = f"W {key} {content}"
                exact[key] = [sum(exact[key][(i // classes) * classes:(i // classes + 1) * classes])
                              if i % classes == content else Fraction(0) for i in range(states)]
            state.apply(operation)
            if step == 23:
                payload = state.export()
                state = IntervalMemory.restore(model, payload)
                assert state.export() == payload
                restored += 1
            quantized = state.quantized(BUDGET)
            assert exact_radius(state.export(), quantized["counts"]) == quantized["l1_bound_units"]
            for key, row in enumerate(exact):
                assert state.support[key] == [p > 0 for p in row]
                for value, low, high in zip(row, state.lower[key], state.upper[key]):
                    assert Fraction(low) <= value <= Fraction(high)
                    coordinates += 1
                error = sum(abs(value - Fraction(q, SCALE))
                            for value, q in zip(row, quantized["counts"][key]))
                assert error <= Fraction(quantized["l1_bound_units"][key], SCALE)
                certificates += 1
    return dict(fixtures=24, events=1152, coordinate_enclosures=coordinates,
                exact_l1_certificates=certificates, exact_restores=restored,
                namespace="918400..918423, independent tiny fixtures; no formal seed executed")


def decode_native(data, model, addresses=4, states=40):
    assert data[:8] == b"HQ24CK03" and data[8:40].hex() == model
    assert digest(data[:-32]) == data[-32:].hex()
    a, n, completed, clock = struct.unpack_from("<IIQQ", data, 40)
    assert (a, n) == (addresses, states)
    assert len(data) == 96 + addresses * (4 + 4 * states + (states + 7) // 8)
    rows, supports, bounds, position = [], [], [], 64
    for _ in range(addresses):
        bound = struct.unpack_from("<I", data, position)[0]
        position += 4
        row = list(struct.unpack_from(f"<{states}I", data, position))
        position += 4 * states
        packed = data[position:position + (states + 7) // 8]
        position += (states + 7) // 8
        support = [bool(packed[i // 8] & (1 << (i % 8))) for i in range(states)]
        assert sum(row) == SCALE and bound <= BUDGET
        assert all(not value or possible for value, possible in zip(row, support))
        rows.append(row)
        supports.append(support)
        bounds.append(bound)
    return dict(completed=completed, clock_ticks=clock, counts=rows,
                support=supports, l1_bound_units=bounds)


def bundle_check(path, model_hash, tape_hash):
    body = checked_payload(json.loads(path.read_text()))
    cache = checked_payload(body["interval_cache"])
    assert body["model"] == cache["model"] == model_hash
    assert body["tape"] == tape_hash and body["maximum_error"] == BUDGET
    assert cache["precision"] == 80
    state = decode_native(bytes.fromhex(body["native_checkpoint_hex"]), model_hash)
    assert state == body["native_state"]
    assert state["completed"] == cache["completed"] and state["clock_ticks"] == cache["clock_ticks"]
    assert state["support"] == cache["support"]
    assert max(exact_radius(cache, state["counts"])) <= BUDGET
    return body


def raw_audit(seed):
    root = HERE / "results" / f"hybrid_qualification_{seed}"
    result = json.loads((root / "HYBRID_VALIDATION.json").read_text())
    model_hash, tape_hash = digest((root / "MODEL.txt").read_bytes()), digest((root / "OPS.txt").read_bytes())
    operations = (root / "OPS.txt").read_text().splitlines()
    traces, bundles, total_frames, refusal_count = {}, {}, 0, 0
    for name in ("full", "prefix", "resumed"):
        path = root / name
        run = json.loads((path / "RUN.json").read_text())
        trace = [json.loads(line) for line in (path / "TRACE.jsonl").read_text().splitlines()]
        enclosures = [json.loads(line) for line in (path / "ENCLOSURES.jsonl").read_text().splitlines()]
        assert len(trace) == len(enclosures) == run["events_committed"] + 1
        assert [row["completed"] for row in trace] == list(range(run["start"], run["completed"] + 1))
        assert [row["completed"] for row in enclosures] == [row["completed"] for row in trace]
        assert max(max(row["interval_radius_units"]) for row in enclosures) == run["maximum_interval_radius_units"]
        assert max(max(row["native_radius_units"]) for row in enclosures) == run["maximum_native_radius_units"]
        assert run["maximum_interval_radius_units"] <= BUDGET and run["maximum_native_radius_units"] <= BUDGET
        reconstructed, last_replayed, native_cpu = [], run["start"], 0.
        for call_index, receipt in enumerate(run["native_calls"]):
            prefix = path / "native_calls" / f"{call_index:04d}"
            raw = prefix.with_suffix(".stdout.jsonl").read_bytes()
            assert digest(raw) == receipt["stdout_sha256"]
            stderr = prefix.with_suffix(".stderr.txt").read_text().strip()
            assert stderr == receipt["stderr"]
            assert prefix.with_suffix(".ops").read_text().splitlines() == operations[receipt["start"]:run["requested_stop"]]
            frames = [row for row in map(json.loads, raw.splitlines()) if row["event"] != "checkpoint"]
            assert frames[0]["completed"] == receipt["start"]
            if call_index:
                restored = decode_native(prefix.with_suffix(".restore.ckpt").read_bytes(), model_hash)
                assert {field: frames[0][field] for field in FIELDS} == restored
                assert {field: reconstructed[-1][field] for field in FIELDS} == restored
            else:
                reconstructed.append(dict(frames[0], execution="initial"))
            reconstructed.extend(dict(frame, execution="native") for frame in frames[1:])
            native_cpu += receipt["cpu_seconds"]
            if receipt["returncode"]:
                assert receipt["returncode"] == 2
                assert stderr.startswith(f"operation line {len(frames)}:") and "precision required:" in stderr
                fallback = run["fallbacks"][call_index]
                next_event = frames[-1]["completed"] + 1
                assert fallback["refused_event"] == next_event == fallback["replay_to"]
                assert fallback["replay_from"] == last_replayed
                assert fallback["replayed_events"] == next_event - last_replayed
                last_replayed = next_event
                cache_raw = prefix.with_suffix(".interval_cache.json").read_bytes()
                assert digest(cache_raw) == fallback["interval_cache_sha256"]
                cache = checked_payload(json.loads(cache_raw))
                frame = trace[next_event - run["start"]]
                assert cache["completed"] == frame["completed"]
                assert cache["clock_ticks"] == frame["clock_ticks"]
                assert cache["support"] == frame["support"]
                assert exact_radius(cache, frame["counts"]) == frame["l1_bound_units"] == fallback["q24_radius_units"]
                assert frame["execution"] == "interval_fallback"
                assert frame["event"] == operations[next_event - 1].split()[0]
                reconstructed.append(frame)
                refusal_count += 1
            else:
                assert call_index == len(run["native_calls"]) - 1 and not stderr
                assert decode_native(prefix.with_suffix(".ckpt").read_bytes(), model_hash) == {field: trace[-1][field] for field in FIELDS}
        assert reconstructed == trace
        assert abs(native_cpu - run["native_cpu_seconds"]) < 1e-12
        assert sum(row["replayed_events"] for row in run["fallbacks"]) + run["completed"] - last_replayed == run["replayed_events"]
        bundles[name] = bundle_check(path / "HYBRID_CHECKPOINT.json", model_hash, tape_hash)
        traces[name] = trace
        total_frames += len(trace)
    assert traces["prefix"] + traces["resumed"][1:] == traces["full"]
    for field in ("native_state", "native_checkpoint_hex", "interval_cache"):
        assert bundles["full"][field] == bundles["resumed"][field]
    assert bundles["resumed"]["cumulative_cost"]["replayed_events"] == len(operations)
    reference = np.load(io.BytesIO(gzip.decompress((root / "FLOAT_REFERENCE.npy.gz").read_bytes())), allow_pickle=False)
    counts = np.array([row["counts"] for row in traces["full"]]) / SCALE
    assert counts.shape == reference.shape == (550, 4, 40)
    l1 = float(np.abs(counts - reference).sum(axis=2).max())
    assert l1 == result["float_reference_l1_max"]
    argmax_changes = int(np.count_nonzero(counts.reshape(550, 4, 10, 4).sum(2).argmax(2)
                                        != reference.reshape(550, 4, 10, 4).sum(2).argmax(2)))
    assert argmax_changes == result["content_argmax_disagreements"] == 0
    receipts = json.loads((root / "PROCESS_RECEIPTS.json").read_text())
    assert receipts == result["receipts"]
    assert sum(row["child_cpu_seconds"] for row in receipts) == result["outer_child_cpu_seconds"]
    for label, text in [("reject_corrupt_hybrid_cache", "Hybrid recovery checksum mismatch"),
                        ("reject_changed_tape", "Hybrid model/tape/profile mismatch"),
                        ("reject_reused_output_namespace", "FileExistsError")]:
        assert text in (root / "owner_receipts" / (label + ".stderr.log")).read_text()
        assert next(row for row in receipts if row["name"] == label)["returncode"] != 0
    index = json.loads((root / "EVIDENCE_INDEX.json").read_text())
    archive = b"".join((root / part["path"]).read_bytes() for part in index["parts"])
    assert digest(archive) == index["archive_sha256"] and len(archive) == index["archive_bytes"]
    for part in index["parts"]:
        data = (root / part["path"]).read_bytes()
        assert len(data) == part["bytes"] <= 480000 and digest(data) == part["sha256"]
    with tarfile.open(fileobj=io.BytesIO(gzip.decompress(archive)), mode="r:") as tar:
        assert sorted(tar.getnames()) == sorted(item["path"] for item in index["files"])
        for item in index["files"]:
            data = tar.extractfile(item["path"]).read()
            assert data == (root / item["path"]).read_bytes()
            assert len(data) == item["bytes"] and digest(data) == item["sha256"]
    assert result["events"] == len(operations) == 549 and result["passed"]
    return dict(seed=seed, source_commit=result["source_commit"], saved_frames_checked=total_frames,
                precision_refusals_checked=refusal_count, full_fallbacks=len(result["full_execution"]["fallbacks"]),
                raw_files_checked=len(index["files"]), archive_sha256=index["archive_sha256"],
                max_float_l1=l1, max_interval_units=result["full_execution"]["maximum_interval_radius_units"],
                max_native_units=result["full_execution"]["maximum_native_radius_units"],
                unchanged_budget_units=BUDGET, outer_child_cpu_seconds=result["outer_child_cpu_seconds"],
                raw_recovery_exact=True, corruption_and_identity_refusals=True)


def main():
    started = time.process_time()
    manifest = json.loads((HERE / "HYBRID_PUBLISH_MANIFEST.json").read_text())
    hashes = {}
    for row in manifest["files"]:
        data = (HERE / Path(row["path"]).name).read_bytes()
        assert digest(data) == row["sha256"] and len(data) == row["bytes"]
        hashes[Path(row["path"]).name] = row["sha256"]
    result = dict(schema="hcsn-r16-hybrid-independent-audit-v1", source_hashes=hashes,
        exact_fraction_checks=fraction_cases(), formal_saved_evidence=[raw_audit(seed) for seed in (163211, 163213)],
        frozen_source_changed=False, formal_tapes_executed_by_this_audit=False,
        reviewed_claims=["80-digit directed interval arithmetic encloses exact normalized integer-weight fixture",
            "Bayes lower numerator / upper denominator and upper numerator / strictly positive lower denominator",
            "Simplex complement intersection and exact endpoint-derived Q24 L1 rebase certificate",
            "Committed native events and interval-cache events are each traversed once in their own state streams",
            "Complete trusted native/cache snapshot plus model/full public tape identity; exact restart"],
        limits=["Small independent Fraction fixtures test implementation; static interval reasoning supports enclosure induction",
            "Formal evidence audit uses saved traces/caches and exact Fraction endpoint certificates; it does not regenerate formal seeds",
            "No claim that interval radii are dominated by every native declared radius; both are independently checked against the fixed budget",
            "Float-reference comparison is descriptive and is not an expm or continuous-PDE error certificate",
            "Checksums bind trusted snapshots only; no authentication, antirollback, production owner, energy or network claim",
            "Original pure-Q24 refusal and compression cost failures remain valid"],
        blocking_findings=[], passed=True, audit_cpu_seconds=time.process_time() - started)
    path = HERE / "results" / "HYBRID_INDEPENDENT_AUDIT.json"
    path.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n")
    print(canonical(result))


if __name__ == "__main__":
    main()
