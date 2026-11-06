#!/usr/bin/env python3
"""Independent, local-only accounting of the frozen C4 synthetic raw records.

Does not import the original reader, run a native binary, or infer clock honesty.
Aggregates records by cell, verifies phase arithmetic and paired identities,
then compares the separately saved original reader's derived values.
"""
from __future__ import annotations

import hashlib
import json
import statistics
import struct
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RAW = ROOT / "extracted/synthetic-census-two-child"
ARMS = [
    "lazy-full-limb", "prepared-generic", "prepared-structured",
    "tiled-classical", "tiled-strassen-one-level", "paired-product",
    "blocked-zero", "blocked-zero-integer-paired", "blocked-one-zero-rank-one",
    "maintenance-periodic", "maintenance-integer-paired", "maintenance-prefix",
    "maintenance-limb", "scalar-original", "lazy-full-limb-sparse",
]
CLASSES = [
    "periodic-dense-fixture", "full-rank-field", "zero", "identity", "rank-one",
    "sparse-diagonal", "continuity-maintenance-v1", "left-zero-right-rank-one",
    "right-zero-left-rank-one",
]
CLOCKS = ("cpu_ns", "wall_ns")
PHASES = ("setup", "attempt", "cleanup", "teardown", "verification")
PRODUCER_PHASES = PHASES[:4]
BUDGETS = (1_000_000, 5_000_000, 20_000_000)
SEED = "d74433233739073f8237d5efa7d7fe9f2bf7b686a4634c425c2dabc6bed68944"


def unique(items):
    d = {}
    for k, v in items:
        assert k not in d, ("duplicate JSON key", k)
        d[k] = v
    return d


def reject_number(s):
    raise ValueError(("noninteger native JSON number", s))


def timing(value):
    assert set(value) == set(CLOCKS)
    assert all(type(value[k]) is int and 0 <= value[k] < 2**64 for k in CLOCKS)
    return value


def zero():
    return dict.fromkeys(CLOCKS, 0)


def add(dst, src):
    timing(src)
    for clock in CLOCKS:
        dst[clock] += src[clock]
        assert dst[clock] < 2**64


def h(tag, *parts):
    # Exact public wire hash framing, independently implemented here.
    t = tag.encode("ascii")
    m = hashlib.sha256(b"TRNM-PON1\0" + struct.pack("<H", len(t)) + t)
    for p in parts:
        m.update(struct.pack("<I", len(p)))
        m.update(p)
    return m.digest()


def hx(value, size=32):
    assert isinstance(value, str) and len(value) == size * 2
    assert all(c in "0123456789abcdef" for c in value)
    return bytes.fromhex(value)


def paid(cell):
    return {clock: sum(cell["phases"][p][clock] for p in PRODUCER_PHASES) for clock in CLOCKS}


def new_cell(key):
    return {
        "class": key[0], "sample": key[1], "arm": key[2],
        "phases": {p: zero() for p in PHASES}, "native_verifier": zero(),
        "scalar_verifier": zero(), "verification_cleanup": zero(),
        "winner_attempts": zero(), "loser_attempts": zero(),
        "setups": [], "epochs": [], "attempts": 0, "hits": 0,
        "materialized": 0, "epoch_hits": Counter(), "stream_hasher": hashlib.sha256(),
        "summary": None, "last_observed": zero(),
    }


def read_target(target_index):
    path = RAW / f"synthetic-target-{target_index}/native.jsonl"
    digest = hashlib.sha256()
    byte_count = 0
    counts = Counter()
    materials, cells, streams, proofs, accepted = {}, {}, {}, {}, set()
    schedule = []
    header = end = None
    with path.open("rb") as source:
        for lineno, raw in enumerate(source, 1):
            assert raw.endswith(b"\n") and 0 < len(raw) <= 256 * 1024
            digest.update(raw)
            byte_count += len(raw)
            row = json.loads(raw, object_pairs_hook=unique,
                             parse_float=reject_number, parse_constant=reject_number)
            assert row["schema"] == "pon-work-expensive-native-v2"
            kind = row["kind"]
            counts[kind] += 1
            if kind == "run":
                assert lineno == 1 and header is None
                header = row
                assert row["arms"] == ARMS and row["samples"] == 8
                assert row["attempts_per_arm"] == 64 and row["reuse_attempts"] == 16
                assert row["class_count"] == 9 and row["target_index"] == target_index
                assert row["seed"] == SEED and row["work_identity_revision"] == 2
                assert row["work_identity_fields"] == ["challenge", "task", "target"]
                assert row["target_shared_challenge_stream"] is True
                assert row["challenge_is_native_header"] is False
                assert row["production_activation"] is False
                assert row["target"] == ("7f" if target_index == 0 else "07") + "ff" * 31
                target = hx(row["target"])
                continue
            assert header is not None and end is None
            if kind == "material":
                name = row["class"]
                assert name in CLASSES and name not in materials
                a, b = hx(row["a_hex"], 16384), hx(row["b_hex"], 16384)
                av, bv = struct.unpack("<4096I", a), struct.unpack("<4096I", b)
                assert max(av + bv) < 4294967291
                assert h("task", a, b).hex() == row["task"]
                assert hashlib.sha256(a).hexdigest() == row["a_sha256"]
                assert hashlib.sha256(b).hexdigest() == row["b_sha256"]
                assert row["nonzero_a"] == sum(v != 0 for v in av)
                assert row["nonzero_b"] == sum(v != 0 for v in bv)
                materials[name] = {k: v for k, v in row.items() if k not in ("a_hex", "b_hex")}
                continue
            if kind == "run_summary":
                end = row
                continue
            key = (row["class"], row["sample"], row["arm"])
            assert key[0] in materials and type(key[1]) is int and 0 <= key[1] < 8 and key[2] in ARMS
            cell = cells.setdefault(key, new_cell(key))
            assert cell["summary"] is None
            phase = cell["phases"]
            if kind == "setup":
                epoch = len(cell["setups"])
                assert row["epoch"] == row["setup_generation"] == epoch
                assert row["start_attempt"] == cell["attempts"] == epoch * 16
                assert len(cell["epochs"]) == epoch
                assert row["cache_key"] == materials[key[0]]["task"]
                assert row["intended_reuse_attempts"] == 16 and row["error"] is None
                assert row["status"] in ("prepared", "unsupported")
                add(phase["setup"], row["timing"])
                cell["setups"].append(row["status"])
            elif kind == "attempt":
                i = cell["attempts"]
                epoch = i // 16
                assert row["index"] == i and row["epoch"] == epoch
                assert len(cell["setups"]) == epoch + 1 and cell["setups"][-1] == "prepared"
                assert len(cell["epochs"]) == epoch
                task = hx(materials[key[0]]["task"])
                challenge = h("pon-work-expensive-challenge-v1", task, hx(SEED),
                              struct.pack("<Q", key[1]), struct.pack("<Q", i))
                assert hx(row["challenge"]) == challenge
                trace, ticket = hx(row["trace"]), hx(row["ticket"])
                assert h("ticket", challenge, trace) == ticket
                hit = ticket <= target
                assert row["target_hit"] is hit and row["stream_equal"] is True
                assert row["outcome"] == "complete" and row["error"] is None
                work = h("pon-work-expensive-work-v2", challenge, task, target).hex()
                assert row["work_id"] == work
                stream_key = (key[0], key[1], i)
                value = (row["challenge"], row["trace"], row["ticket"])
                assert streams.setdefault(stream_key, value) == value
                cell["stream_hasher"].update(trace)
                materialized = hit if key[2] in (ARMS[0], ARMS[-1]) else True
                assert row["proof_materialized"] is materialized
                if materialized:
                    hx(row["proof_sha256"])
                    assert proofs.setdefault(stream_key, row["proof_sha256"]) == row["proof_sha256"]
                else:
                    assert row["proof_sha256"] is None
                cell["materialized"] += int(materialized)
                cell["attempts"] += 1
                cell["hits"] += int(hit)
                cell["epoch_hits"][epoch] += int(hit)
                add(phase["attempt"], row["timing"])
                add(phase["cleanup"], row["cleanup_timing"])
                add(cell["winner_attempts" if hit else "loser_attempts"], row["timing"])
                assert all(row["producer_cumulative_" + c] == paid(cell)[c] for c in CLOCKS)
                if hit:
                    v = row["verification"]
                    assert v["products_equal"] is True
                    for backend in ("native", "scalar"):
                        assert v[backend]["outcome"] == "Accepted"
                        add(phase["verification"], v[backend]["timing"])
                        add(cell[backend + "_verifier"], v[backend]["timing"])
                    add(phase["verification"], v["cleanup_timing"])
                    add(cell["verification_cleanup"], v["cleanup_timing"])
                    accepted.add(work)
                else:
                    assert row["verification"] is None
                observed = {c: row["observed_cell_cumulative_" + c] for c in CLOCKS}
                assert all(observed[c] >= max(cell["last_observed"][c], paid(cell)[c]) for c in CLOCKS)
                cell["last_observed"] = observed
            elif kind == "teardown":
                epoch = len(cell["epochs"])
                assert row["epoch"] == epoch and cell["attempts"] == (epoch + 1) * 16
                assert row["actual_attempts"] == 16 and row["actual_hits"] == cell["epoch_hits"][epoch]
                assert row["lifetime_includes_audit_and_output"] is True
                add(phase["teardown"], row["timing"])
                observed = {c: row["observed_cell_cumulative_" + c] for c in CLOCKS}
                assert all(observed[c] >= max(cell["last_observed"][c], paid(cell)[c]) for c in CLOCKS)
                cell["last_observed"] = observed
                cell["epochs"].append({"producer_cpu_ns": paid(cell)["cpu_ns"],
                                       "observed_cpu_ns": observed["cpu_ns"],
                                       "completed_attempts": cell["attempts"],
                                       "verified_unique_hits": cell["hits"],
                                       "cached_lifetime": timing(row["cached_lifetime"])})
            elif kind == "cell_summary":
                complete = cell["attempts"] == 64
                assert row["status"] == ("complete" if complete else "unsupported")
                assert row["sequence_complete"] is complete and row["error_count"] == 0
                assert row["unsupported_count"] == int(not complete)
                assert cell["setups"] == (["prepared"] * 4 if complete else ["unsupported"])
                assert len(cell["epochs"]) == (4 if complete else 0)
                assert row["attempts"] == cell["attempts"]
                assert row["hits"] == row["verified_hits"] == cell["hits"]
                assert row["setup_count"] == len(cell["setups"])
                assert row["distinct_application_results"] == int(cell["hits"] > 0)
                assert row["native_branch_accepted_work"] is None
                for p in PHASES:
                    assert row[p + "_timing"] == phase[p], (key, p)
                assert row["producer_timing"] == paid(cell), key
                assert all(row["observed_cell_timing"][c] >= cell["last_observed"][c] for c in CLOCKS)
                cell["summary"] = row
                cell["trace_sequence_sha256"] = cell.pop("stream_hasher").hexdigest()
                schedule.append(key)
            else:
                raise AssertionError(("unexpected kind", kind))
    expected_schedule = [(name, sample, ARMS[(offset + sample) % 15])
                         for name in CLASSES for sample in range(8) for offset in range(15)]
    assert schedule == expected_schedule
    assert set(materials) == set(CLASSES) and len(cells) == 1080 and len(streams) == 4608
    assert counts == {"run": 1, "material": 9, "setup": 2928, "attempt": 39424,
                      "teardown": 2464, "cell_summary": 1080, "run_summary": 1}
    totals = {"completed_cells": sum(c["summary"]["status"] == "complete" for c in cells.values()),
              "unsupported_cells": sum(c["summary"]["status"] == "unsupported" for c in cells.values()),
              "failed_cells": 0, "attempts": sum(c["attempts"] for c in cells.values()),
              "hits": sum(c["hits"] for c in cells.values()),
              "verified_hits": sum(c["hits"] for c in cells.values())}
    assert totals["completed_cells"] == 616 and totals["unsupported_cells"] == 464
    assert end["requested_cells"] == 1080 and end["status"] == "complete"
    assert end["all_attempts_retained"] is True and end["qualification"] is False
    assert end["native_branch_accepted_work"] is None
    for k, v in totals.items():
        assert end[k] == v
    # Compare to the original saved reader only after independent aggregation.
    original = json.loads((RAW / f"synthetic-target-{target_index}/reader.json").read_text())
    assert original["counts"] == totals and original["raw_sha256"] == digest.hexdigest()
    assert original["raw_bytes"] == byte_count
    assert original["unique_relation_winners_across_repeated_arms"] == len(accepted)
    oldcells = {(r["class"], r["sample"], r["arm"]): r for r in original["cells"]}
    assert set(oldcells) == set(cells)
    for key, cell in cells.items():
        previous = oldcells[key]
        assert previous["phase_timing"] == cell["phases"]
        assert previous["producer_timing"] == paid(cell)
        assert previous["trace_sequence_sha256"] == cell["trace_sequence_sha256"]
        boundaries = [{k: v for k, v in e.items() if k != "cached_lifetime"} for e in cell["epochs"]]
        assert previous["settled_epoch_boundaries"] == boundaries
        prefixes = []
        for budget in BUDGETS:
            r = {"budget_cpu_ns": budget}
            for scope in ("producer", "observed"):
                available = [e for e in boundaries if e[scope + "_cpu_ns"] <= budget]
                selected = available[-1] if available else {"verified_unique_hits": 0, "completed_attempts": 0}
                r[scope + "_verified_unique_hits"] = selected["verified_unique_hits"]
                r[scope + "_settled_attempts"] = selected["completed_attempts"]
            prefixes.append(r)
        assert previous["prefixes"] == prefixes
        cell["prefixes"] = prefixes
    return {
        "target_index": target_index, "raw_sha256": digest.hexdigest(), "raw_bytes": byte_count,
        "records": dict(counts), "totals": totals, "unique_indexed_streams": len(streams),
        "unique_relation_winners": len(accepted), "materials": materials, "cells": cells,
        "header": header, "end": end, "streams": streams, "proofs": proofs,
        "original_reader": original,
    }


def describe(target):
    cells = target["cells"]
    class_reports = []
    for name in CLASSES:
        byarm = {arm: [cells[name, s, arm] for s in range(8)] for arm in ARMS}
        supported = [arm for arm in ARMS if all(c["summary"]["status"] == "complete" for c in byarm[arm])]
        assert all(all(c["summary"]["status"] == "unsupported" for c in byarm[a]) for a in ARMS if a not in supported)
        arm_totals = {}
        for arm in ARMS:
            cs = byarm[arm]
            arm_totals[arm] = {
                "status": cs[0]["summary"]["status"], "samples": 8,
                "attempts": sum(c["attempts"] for c in cs), "hits": sum(c["hits"] for c in cs),
                "setup_calls": sum(len(c["setups"]) for c in cs),
                "materialized_proofs": sum(c["materialized"] for c in cs),
                "producer_timing": {k: sum(paid(c)[k] for c in cs) for k in CLOCKS},
                "phase_timing": {p: {k: sum(c["phases"][p][k] for c in cs) for k in CLOCKS} for p in PHASES},
                "native_verifier_timing": {k: sum(c["native_verifier"][k] for c in cs) for k in CLOCKS},
                "scalar_verifier_timing": {k: sum(c["scalar_verifier"][k] for c in cs) for k in CLOCKS},
                "winner_attempt_timing": {k: sum(c["winner_attempts"][k] for c in cs) for k in CLOCKS},
                "loser_attempt_timing": {k: sum(c["loser_attempts"][k] for c in cs) for k in CLOCKS},
                "per_sample_producer_cpu_ns": [paid(c)["cpu_ns"] for c in cs],
            }
        dense, sparse = arm_totals[ARMS[0]], arm_totals[ARMS[-1]]
        paired = [paid(byarm[ARMS[0]][s])["cpu_ns"] / paid(byarm[ARMS[-1]][s])["cpu_ns"] for s in range(8)]
        best = min(supported, key=lambda a: arm_totals[a]["producer_timing"]["cpu_ns"])
        calibration = min(supported, key=lambda a: sum(paid(c)["cpu_ns"] for c in byarm[a][:2]))
        eval_ns = sum(paid(c)["cpu_ns"] for c in byarm[calibration][2:])
        dense_eval = sum(paid(c)["cpu_ns"] for c in byarm[ARMS[0]][2:])
        old = next(x for x in target["original_reader"]["calibration_selection"] if x["class"] == name)
        assert old["selected_arm"] == calibration and old["evaluation_producer_cpu_ns"] == eval_ns
        assert old["generic_evaluation_producer_cpu_ns"] == dense_eval
        cr = {
            "class": name, "material": target["materials"][name],
            "supported_arms": supported, "unsupported_arms": [a for a in ARMS if a not in supported],
            "dense_over_sparse_ratio_of_cpu_sums": dense["producer_timing"]["cpu_ns"] / sparse["producer_timing"]["cpu_ns"],
            "paired_dense_over_sparse_cpu_ratios": paired,
            "paired_ratio_median": statistics.median(paired),
            "retrospective_minimum_all_8_samples": best,
            "dense_over_retrospective_best": dense["producer_timing"]["cpu_ns"] / arm_totals[best]["producer_timing"]["cpu_ns"],
            "calibration_selected_arm_samples_0_1": calibration,
            "evaluation_samples_2_7_dense_over_selected": dense_eval / eval_ns,
            "arm_totals": arm_totals,
        }
        class_reports.append(cr)
    return {
        "target_index": target["target_index"], "target": target["header"]["target"],
        "raw_sha256": target["raw_sha256"], "raw_bytes": target["raw_bytes"],
        "record_counts": target["records"], "counts": target["totals"],
        "unique_indexed_streams": target["unique_indexed_streams"],
        "unique_relation_winners_across_repeated_arms": target["unique_relation_winners"],
        "material_creation_timing": target["header"]["material_creation_timing"],
        "run_timing": target["end"]["run_timing"],
        "original_reader_counts_phase_sums_prefixes_calibration_match": True,
        "all_supported_arm_streams_and_materialized_proof_hashes_match": True,
        "classes": class_reports,
    }


def main():
    left, right = read_target(0), read_target(1)
    assert left["streams"] == right["streams"] and left["proofs"] == right["proofs"]
    for name in CLASSES:
        for k in ("task", "a_sha256", "b_sha256", "nonzero_a", "nonzero_b", "rank_a", "rank_b"):
            assert left["materials"][name][k] == right["materials"][name][k]
    report = {
        "schema": "independent-c4-synthetic-raw-recomputation-v1",
        "source_commit": "8df4b21d893906570d48f5beafabb3b31e0aefbc",
        "source_tree": "6f5aaa2af0432e27e24b6bd2ad18013ab4423d14",
        "method": "independent record grouping and arithmetic; original reader imported/executed: false",
        "native_or_reader_reexecuted": False,
        "clock_scope": "cpu_ns is native same-thread ThreadCPUTime; wall_ns is Instant; observer CPU separate",
        "producer_scope": "setup + all winning and losing attempts + proof cleanup + completed epoch teardown",
        "excluded_from_producer_sum": ["material creation", "material identity/rank", "native/reference verification", "audit", "JSON emission"],
        "shared_targets_same_challenge_trace_ticket_stream": True,
        "targets_are_independent_new_tasks": False,
        "global_cheapest_proved": False, "native_admission_or_public_service_claim": False,
        "relation_proof_bytes_not_in_raw": "proof hashes and real native/reference outcomes retained; no independent verifier rerun",
        "targets": [describe(left), describe(right)],
    }
    out = ROOT / "independent-sparse-recomputation.json"
    b = (json.dumps(report, indent=2) + "\n").encode()
    with out.open("xb") as f:
        f.write(b)
    print(json.dumps({"path": str(out), "bytes": len(b), "sha256": hashlib.sha256(b).hexdigest(),
                      "counts": [r["counts"] for r in report["targets"]],
                      "unique_winners": [r["unique_relation_winners_across_repeated_arms"] for r in report["targets"]]}))


if __name__ == "__main__":
    main()
