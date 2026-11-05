#!/usr/bin/env python3
"""Second independent arithmetic check of the C4 from-zero raw cost records.

No native execution or transcript replay. The measured phases exclude public
admission, wire/JSON handling, network and other unmeasured end-to-end costs.
"""
import argparse
from collections import Counter, defaultdict
from fractions import Fraction
import hashlib
import json
from pathlib import Path


def ratio(numerator, denominator):
    value = Fraction(numerator, denominator)
    return {"numerator": numerator, "denominator": denominator,
            "exact_fraction": str(value), "value": float(value)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("raw", type=Path)
    parser.add_argument("findings", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    findings_raw = args.findings.read_bytes()
    findings = json.loads(findings_raw)
    assert findings["source_commit"] == "8df4b21d893906570d48f5beafabb3b31e0aefbc"
    classes = defaultdict(lambda: Counter())
    counts, sha = Counter(), hashlib.sha256()
    candidates = {}
    header = end = None
    with args.raw.open("rb") as stream:
        for line in stream:
            sha.update(line)
            item = json.loads(line)
            kind = item["kind"]
            counts[kind] += 1
            if kind == "campaign":
                assert header is None
                header = item
                continue
            if kind == "end":
                assert end is None
                end = item
                continue
            cell = classes[item["class"]]
            if kind == "cohort":
                assert item["setup_calls"] == 1 and item["searches"] == 4
                cell["setups"] += 1
                for axis in ("cpu_ns", "wall_ns"):
                    cell["setup_" + axis] += item["setup"][axis]
                    cell["total_" + axis] += item["total"][axis]
            elif kind == "search":
                assert item["setup_calls"] == 0
                assert item["status"] == "target-hit-unverified"
                cell["searches"] += 1
                cell["attempts"] += len(item["attempts"])
                cell["misses"] += sum(not row["target_hit"] for row in item["attempts"])
                assert sum(row["target_hit"] for row in item["attempts"]) == 1
                for axis in ("cpu_ns", "wall_ns"):
                    cell["search_" + axis] += item["timing"][axis]
            elif kind == "candidate":
                raw = bytes.fromhex(item["proof_hex"])
                assert len(raw) == 49188
                assert hashlib.sha256(raw).hexdigest() == item["proof_sha256"]
                key = (item["class"], item["sample"], item["search_index"])
                assert key not in candidates
                candidates[key] = item["proof_sha256"]
                cell["candidates"] += 1
            elif kind == "verifier":
                key = (item["class"], item["sample"], item["search_index"])
                assert candidates[key] == item["proof_sha256"]
                assert item["outcome"] == "Transcript"
                if item["path"] == "production":
                    cell["production_verifications"] += 1
                    for axis in ("cpu_ns", "wall_ns"):
                        cell["production_" + axis] += item["timing"][axis]
    assert counts == {"campaign": 1, "material": 9, "cohort": 72,
                      "search": 288, "candidate": 288, "verifier": 1440, "end": 1}
    assert end["complete"] and header["valid_proof_acquisition_used"] is False
    assert header["samples"] == 8 and header["searches_per_setup"] == 4
    assert header["clock"] == "thread-cpu-and-monotonic-wall-ns"
    assert sha.hexdigest() == "8398d8f8473b168e7303b007796ebb8434066b1b4cd85e1ee92e0d89a3cb8390"
    reviewed = []
    for item in findings["from_zero_full_cost_amplification"]:
        cell = classes[item["class_name"]]
        assert cell["setups"] == 8
        assert cell["searches"] == cell["candidates"] == cell["production_verifications"] == 32
        assert cell["attempts"] == item["nonce_attempts"]
        assert cell["misses"] == item["misses"]
        comparisons = {}
        for axis in ("cpu_ns", "wall_ns"):
            assert cell["setup_" + axis] == item["setup"][axis]
            assert cell["search_" + axis] == item["search"][axis]
            assert cell["total_" + axis] == item["inclusive_attacker_total"][axis]
            assert cell["production_" + axis] == item["production_rejection"][axis]
            assert cell["total_" + axis] >= cell["setup_" + axis] + cell["search_" + axis]
            comparisons[axis] = ratio(cell["production_" + axis], cell["total_" + axis])
        reviewed.append({"class": item["class_name"], "totals": dict(cell),
                         "production_over_measured_attacker": comparisons})
    aggregate = {axis: ratio(sum(c["production_" + axis] for c in classes.values()),
                            sum(c["total_" + axis] for c in classes.values()))
                 for axis in ("cpu_ns", "wall_ns")}
    sensitivity = {axis: ratio(aggregate[axis]["numerator"],
                              aggregate[axis]["denominator"] + header["material_setup"][axis])
                   for axis in ("cpu_ns", "wall_ns")}
    result = {"scope": __doc__.strip(), "source_commit": findings["source_commit"],
              "source_tree": findings["source_tree"], "raw_sha256": sha.hexdigest(),
              "findings_sha256": hashlib.sha256(findings_raw).hexdigest(),
              "counts": dict(counts), "nonce_attempts": sum(c["attempts"] for c in classes.values()),
              "misses": sum(c["misses"] for c in classes.values()),
              "classes": reviewed, "material_generation_once": header["material_setup"],
              "aggregate_measured_phase_ratio": aggregate,
              "aggregate_with_entire_once_generated_material_charged_to_attacker": sensitivity,
              "sensitivity_allocation": "Charge the complete single campaign material-generation measurement once across all 288 candidate observations; do not duplicate this shared cost per candidate or assert a measured per-class material cost.",
              "native_runs": 0, "transcript_replays": 0,
              "public_service_pass": False, "global_attacker_lower_bound": False}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"counts": dict(counts), "nonce_attempts": result["nonce_attempts"],
                      "misses": result["misses"], "aggregate": aggregate,
                      "with_material_generation_once": sensitivity}))


if __name__ == "__main__":
    main()
