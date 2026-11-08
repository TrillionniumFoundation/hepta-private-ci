"""Check MEM-1 reference evidence, supplied binary bytes and partial accounting."""

import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path

from audit_evidence import ARMS, audit_run, binary_identity


def verify(root, *, native):
    root = Path(root)
    manifest = json.loads((root / "manifest.json").read_text())
    if (
        manifest["schema"] != "hepta-mem1-reference-v1"
        or type(manifest["owner_change"]) is not bool
    ):
        raise ValueError("unsupported reference manifest")
    if (
        not isinstance(manifest["arms"], list)
        or not manifest["arms"]
        or any(arm not in ARMS for arm in manifest["arms"])
        or len(set(manifest["arms"])) != len(manifest["arms"])
    ):
        raise ValueError("empty, duplicate or unsupported arm roster")
    if (
        not isinstance(manifest["seeds"], list)
        or not manifest["seeds"]
        or any(type(seed) is not int for seed in manifest["seeds"])
        or len(set(manifest["seeds"])) != len(manifest["seeds"])
    ):
        raise ValueError("empty, duplicate or invalid seed roster")
    binary = binary_identity(native, manifest["native_binary_sha256"])
    if (
        hashlib.sha256((root / "inputs.json").read_bytes()).hexdigest()
        != manifest["inputs_sha256"]
    ):
        raise ValueError("input artifact differs from frozen manifest")
    inputs = json.loads((root / "inputs.json").read_text())
    results = json.loads((root / "results.json").read_text())
    expected = {(arm, seed) for arm in manifest["arms"] for seed in manifest["seeds"]}
    actual = [(row["arm"], row["seed"]) for row in results]
    if (
        len(actual) != len(set(actual))
        or set(actual) != expected
        or manifest["planned_runs"] != len(expected)
    ):
        raise ValueError("missing/duplicate arm-seed attempt")
    counts, audits = Counter(), []
    for result in results:
        if result["status"] != "completed":
            raise ValueError("failed attempt retained: " + repr(result))
        folder = root / f"{result['arm']}-seed-{result['seed']}"
        events = [
            json.loads(line)
            for line in (folder / "events.jsonl").read_text().splitlines()
        ]
        audits.append(
            audit_run(folder, manifest, result, events, inputs[str(result["seed"])])
        )
        grouped, updates = defaultdict(list), Counter()
        trial_counts = Counter()
        b_stream = []
        for event in events:
            if (event["arm"], event["seed"]) != (result["arm"], result["seed"]):
                raise ValueError("cross-run event contamination")
            counts[event["event"]] += 1
            trial_counts[event["event"]] += 1
            if event["event"] == "update":
                updates[event["kind"]] += 1
            if event["event"] == "probe":
                # Recompute truth from answers; do not trust the recorded correct flag.
                correct = event["output"] == event["expected"]
                if correct != event["correct"]:
                    raise ValueError(
                        "probe correctness was not derived from its raw answer"
                    )
                grouped[event["phase"], event["panel"]].append(event)
            if event["event"] == "recovery" and not event["matched"]:
                raise ValueError("recovery mismatch")
            if (
                event["event"] == "prequential"
                and event["phase"] == "B"
                and event["sources"][0].startswith("B:")
            ):
                b_stream.append(event["output"] == event["expected"])
        expected_panels = {
            (phase, panel)
            for phase in ("A1", "B", "A2")
            for panel in ("stable", "superseded", "revoked", "scope", "composition")
        }
        if set(grouped) != expected_panels or trial_counts["probe"] != 60:
            raise ValueError("missing probe panel or query")
        boundary = "owner_change" if manifest["owner_change"] else "owner_stationary"
        if (
            trial_counts["prequential"] != 240
            or trial_counts["recovery"] != 3
            or trial_counts[boundary] != 1
        ):
            raise ValueError("incomplete stream/recovery/owner-boundary coverage")
        for (phase, panel), rows in grouped.items():
            score = result["panels"][phase][panel]
            derived = {
                "n": len(rows),
                "accuracy": sum(row["correct"] for row in rows) / len(rows),
                "coverage": sum(row["output"] is not None for row in rows) / len(rows),
                "wrong_assertions": sum(
                    row["output"] is not None and row["output"] != row["expected"]
                    for row in rows
                ),
                "stale_assertions": sum(row["stale_assertion"] for row in rows),
                "invalid_assertions": sum(
                    row["output"] is not None and not row["eligible"] for row in rows
                ),
            }
            if score != derived:
                raise ValueError("summary differs from raw probe outcomes")
        retention = (
            result["panels"]["B"]["stable"]["accuracy"]
            - result["panels"]["A1"]["stable"]["accuracy"]
        )
        if result["retention_delta"] != retention or result[
            "b_prequential_accuracy"
        ] != sum(b_stream) / len(b_stream):
            raise ValueError("retention/plasticity summary drift")
        for kind in ("online", "sleep", "rebuild"):
            if result["counts"][kind + "_updates"] != updates[kind]:
                raise ValueError("update ledger differs from event log")
        sleep_expected = (
            128
            if result["arm"]
            in {"rag_replay", "fast_uniform", "fast_structured", "fast_stabilized"}
            else 0
        )
        if updates["sleep"] != sleep_expected:
            raise ValueError("offline training opportunity mismatch")
        for key, limit in manifest["budget"].items():
            if result["capacity_and_compute"][key] > limit:
                raise ValueError("budget exceeded")
        coverage_passed = result["panels"]["A2"]["stable"]["coverage"] >= 0.5
        if (
            result["coverage_floor_passed"] is not coverage_passed
            or not coverage_passed
        ):
            raise ValueError("coverage gate failed")
    return {
        "verified_runs": len(results),
        "raw_events": dict(counts),
        "native_binary": binary,
        "cost_audit": {
            "status": "PARTIAL",
            "complete_cost_verified": False,
            "profile": "MEM-1 v1 call roster and serialized state accounting",
            "limitations": [
                "owner calls have no complete event-level ledger",
                "retained pool snapshots establish a lower bound, not the full peak",
                "kernel counts exclude hashing/IPC; physical cost is not reconstructed",
            ],
            "runs": audits,
        },
        "scientific_qualification": "HOLD",
        "production_adoption": "NoUpdate",
        "scope": "reference output consistency; not an independent real-task evaluator",
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output")
    parser.add_argument(
        "--native",
        required=True,
        help="retained native binary whose actual bytes must match the run manifest",
    )
    args = parser.parse_args()
    print(json.dumps(verify(args.output, native=args.native), indent=2, sort_keys=True))
