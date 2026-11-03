"""Score a frozen model once, retaining original fixture incompatibilities.

Intent decisions and owner-name resolution are measured separately. This does
not replace the real native/SQLite/socket integration tests with fixture lookup.
The authored semantic/program payloads do not implement the native V1 schema.
"""

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

PROJECT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT))
sys.path.insert(0, str(PROJECT.parent / "memory-cell-v6"))

from addressing.calibration import measure
from addressing.contracts import OwnerRegistry, normalize
from addressing.model import IntentModel
from addressing.planner import AddressPlanner
from v6.encoder import MiniLMEncoder


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def dump(path, value):
    with path.open("x", encoding="utf-8") as output:
        json.dump(value, output, ensure_ascii=False, indent=2, allow_nan=False)
        output.write("\n")


def breakdown(rows, decisions, field):
    result = {}
    for value in sorted({row[field] for row in rows}):
        indices = [i for i, row in enumerate(rows) if row[field] == value]
        result[value] = measure([rows[i] for i in indices], [decisions[i] for i in indices])
    return result


def resolve(registry, request):
    try:
        address = OwnerRegistry(registry).resolve(request)
        return {"entity": address.request["entity"], "error": None}
    except (ValueError, TypeError) as error:
        return {"entity": None, "error": str(error)}


def entity_metrics(rows, key):
    positive = [row for row in rows if row["expected"]["canonical_entity"] is not None]
    negative = [row for row in rows if row["expected"]["canonical_entity"] is None]
    assert (len(positive), len(negative)) == (40, 40)
    return {
        "known_alias_rows": len(positive),
        "known_alias_correct_owner": sum(row[key]["entity"] == row["expected"]["canonical_entity"] for row in positive),
        "known_alias_wrong_owner": sum(row[key]["entity"] not in (None, row["expected"]["canonical_entity"]) for row in positive),
        "ambiguous_or_unknown_rows": len(negative),
        "ambiguous_or_unknown_accepted": sum(row[key]["entity"] is not None for row in negative),
        "errors": dict(Counter(row[key]["error"] for row in rows if row[key]["error"])),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--held", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--encoder", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    lock_path = PROJECT / "evidence/addressing-HELD_LOCK.json"
    lock = json.loads(lock_path.read_bytes())
    raw_model = (args.model / "manifest.json").read_bytes()
    if sha(raw_model) != lock["model"]["manifest_sha256"]:
        raise ValueError("selected model differs from held lock")
    output = args.output.absolute()
    output.mkdir(parents=True, exist_ok=False)
    started, cpu = time.perf_counter(), time.process_time()
    encoder = MiniLMEncoder(args.encoder)
    model = IntentModel.load(args.model, encoder, lock["model"]["manifest_sha256"])
    run = {
        "schema": "hepta.memory.v7.address-held-execution.v1",
        "lock_sha256": sha(lock_path.read_bytes()),
        "model_digest": model.identity,
        "policy_digest": json.loads(raw_model)["policy_digest"],
        "source_model_commit": lock["source_commit"],
        "evaluator_sha256": sha(Path(__file__).read_bytes()),
        "execution_git_head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=PROJECT, text=True).strip(),
        "held_opened": False,
        "fixture_compatibility": lock["fixture_compatibility"],
        "scoring": lock["scoring"],
    }
    dump(output / "EXECUTION.json", run)
    raw = args.held.read_bytes()
    if sha(raw) != lock["held_sha256"]:
        raise ValueError("independent held corpus differs from sealed hash")
    held = json.loads(raw)
    intents, entities = held["intent_rows"], held["entity_rows"]
    assert len(intents) == 360 and len(entities) == 80
    normalized = [normalize(row["text"].replace("{entity}", "entity").replace("{at}", "date").replace("{since}", "date")) for row in intents]
    hypotheses = model.hypotheses(normalized)
    decisions = [model.decide(item) for item in hypotheses]
    intent_rows = [dict(row, normalized_text=text, hypothesis=hypothesis, decision=decision)
                   for row, text, hypothesis, decision in zip(intents, normalized, hypotheses, decisions)]
    # Chunk only transport; retain every row and the original fixed labels.
    for start in range(0, len(intent_rows), 60):
        dump(output / f"intent-readouts-{start // 60:02}.json", intent_rows[start:start + 60])
    entity_rows = []
    for row in entities:
        original = dict(row["request"])
        if original.pop("schema") != "hepta.memory.request.v1":
            raise ValueError("unexpected typed transport schema")
        # Removing schema follows the worker transport adapter. The budget
        # correction is a separately reported diagnostic declared before held.
        corrected = dict(original, max_cells=min(original["max_cells"], 8))
        planner = AddressPlanner(model, row["registry"])
        entity_rows.append({
            "id": row["id"], "language": row["language"], "family": row["family"],
            "expected": row["expected"], "original_request": row["request"],
            "diagnostic_request": corrected,
            "strict_resolution": resolve(row["registry"], original),
            "diagnostic_resolution": resolve(row["registry"], corrected),
            "strict_plan": planner.plan(original),
            "diagnostic_plan": planner.plan(corrected),
        })
    for start in range(0, len(entity_rows), 20):
        dump(output / f"entity-readouts-{start // 20:02}.json", entity_rows[start:start + 20])
    metrics = measure(intents, decisions)
    assert (metrics["known_rows"], metrics["ood_rows"]) == (240, 120)
    positive = [row for row in entity_rows if row["expected"]["canonical_entity"] is not None]
    plan_correct = sum(row["diagnostic_plan"]["status"] == "accepted"
                       and row["diagnostic_plan"]["plan"]["operation"] == row["expected"]["operation"]
                       and row["diagnostic_plan"]["request"]["entity"] == row["expected"]["canonical_entity"] for row in positive)
    result = {
        **run, "held_opened": True, "held_sha256": sha(raw),
        "intent_gate": metrics,
        "intent_by_operation": breakdown(intents, decisions, "operation"),
        "intent_by_language": breakdown(intents, decisions, "language"),
        "intent_by_family": breakdown(intents, decisions, "family"),
        "strict_original_owner_resolution": entity_metrics(entity_rows, "strict_resolution"),
        "uniform_budget_diagnostic_owner_resolution": entity_metrics(entity_rows, "diagnostic_resolution"),
        "diagnostic_known_alias_complete_plan": {"rows": 40, "correct_operation_and_owner": plan_correct},
        "native_fixture_execution": {"rows": 440, "executed": 0, "status": "fixture-incompatible",
                                     "reason": lock["fixture_compatibility"]["memory_values_not_scored"]},
        "intent_criteria_met": metrics["known_correct_rate"] >= .8 and metrics["ood_acceptance_rate"] <= .05,
        "complete_original_protocol_passed": False,
        "head_fit_calls": 0, "parameter_or_policy_changes": 0,
        "wall_seconds_including_load": time.perf_counter() - started,
        "cpu_seconds_including_load": time.process_time() - cpu,
        "population_risk_established": False,
        "qualification": "Fixed authored intent/address sample; native parameter execution and owner authority are qualified separately in real product CI.",
    }
    dump(output / "RESULT.json", result)
    print(json.dumps({key: result[key] for key in ("intent_gate", "strict_original_owner_resolution", "uniform_budget_diagnostic_owner_resolution", "diagnostic_known_alias_complete_plan", "intent_criteria_met", "complete_original_protocol_passed", "wall_seconds_including_load")}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
