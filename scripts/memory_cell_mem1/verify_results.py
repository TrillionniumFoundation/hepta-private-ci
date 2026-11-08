"""Recompute reported scores and budgets from retained event-level evidence."""

import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path


def verify(root):
    root = Path(root)
    manifest = json.loads((root / "manifest.json").read_text())
    if hashlib.sha256((root / "inputs.json").read_bytes()).hexdigest() != manifest["inputs_sha256"]:
        raise ValueError("input artifact differs from frozen manifest")
    results = json.loads((root / "results.json").read_text())
    expected = {(arm, seed) for arm in manifest["arms"] for seed in manifest["seeds"]}
    actual = [(row["arm"], row["seed"]) for row in results]
    if len(actual) != len(set(actual)) or set(actual) != expected:
        raise ValueError("missing/duplicate arm-seed attempt")
    counts = Counter()
    for result in results:
        if result["status"] != "completed":
            raise ValueError("failed attempt retained: " + repr(result))
        folder = root / f"{result['arm']}-seed-{result['seed']}"
        events = [json.loads(line) for line in (folder / "events.jsonl").read_text().splitlines()]
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
                    raise ValueError("probe correctness was not derived from its raw answer")
                grouped[event["phase"], event["panel"]].append(event)
            if event["event"] == "recovery" and not event["matched"]:
                raise ValueError("recovery mismatch")
            if event["event"] == "prequential" and event["phase"] == "B" and event["sources"][0].startswith("B:"):
                b_stream.append(event["output"] == event["expected"])
        expected_panels = {(phase, panel) for phase in ("A1", "B", "A2")
                           for panel in ("stable", "superseded", "revoked", "scope", "composition")}
        if set(grouped) != expected_panels or trial_counts["probe"] != 60:
            raise ValueError("missing probe panel or query")
        boundary = "owner_change" if manifest["owner_change"] else "owner_stationary"
        if trial_counts["prequential"] != 240 or trial_counts["recovery"] != 3 or trial_counts[boundary] != 1:
            raise ValueError("incomplete stream/recovery/owner-boundary coverage")
        for (phase, panel), rows in grouped.items():
            score = result["panels"][phase][panel]
            derived = {"n": len(rows), "accuracy": sum(row["correct"] for row in rows) / len(rows),
                       "coverage": sum(row["output"] is not None for row in rows) / len(rows),
                       "wrong_assertions": sum(row["output"] is not None and row["output"] != row["expected"] for row in rows),
                       "stale_assertions": sum(row["stale_assertion"] for row in rows),
                       "invalid_assertions": sum(row["output"] is not None and not row["eligible"] for row in rows)}
            if score != derived:
                raise ValueError("summary differs from raw probe outcomes")
        retention = result["panels"]["B"]["stable"]["accuracy"] - result["panels"]["A1"]["stable"]["accuracy"]
        if result["retention_delta"] != retention or result["b_prequential_accuracy"] != sum(b_stream) / len(b_stream):
            raise ValueError("retention/plasticity summary drift")
        for kind in ("online", "sleep", "rebuild"):
            if result["counts"][kind + "_updates"] != updates[kind]:
                raise ValueError("update ledger differs from event log")
        sleep_expected = 128 if result["arm"] in {"rag_replay", "fast_uniform", "fast_structured", "fast_stabilized"} else 0
        if updates["sleep"] != sleep_expected:
            raise ValueError("offline training opportunity mismatch")
        for path in folder.glob("candidate-*.json"):
            candidate = json.loads(path.read_text())
            if hashlib.sha256(path.with_suffix(".bin").read_bytes()).hexdigest() != candidate["sha256"]:
                raise ValueError("candidate bytes differ from manifest")
            if candidate["model_adoption"] != "NoUpdate":
                raise ValueError("unqualified shared-model adoption")
        for key, limit in manifest["budget"].items():
            if result["capacity_and_compute"][key] > limit:
                raise ValueError("budget exceeded")
        if not result["coverage_floor_passed"] or not all(result["native_recoveries"]):
            raise ValueError("coverage/recovery gate failed")
    return {"verified_runs": len(results), "raw_events": dict(counts),
            "scope": "reference output consistency; not an independent real-task evaluator"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output")
    args = parser.parse_args()
    print(json.dumps(verify(args.output), indent=2, sort_keys=True))
