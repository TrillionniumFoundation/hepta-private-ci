"""Frozen primitive/relationship tasks; actors receive no terminal labels."""

import copy
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "memory_cell_mem1"))
from environment import Owner

SEEDS = (0, 1, 2, 3, 4)
PHASES = ("base", "version", "revoke", "expiry")
ARMS = ("exact", "bm25", "native")


def encoded(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()


def digest(value):
    return hashlib.sha256(encoded(value)).hexdigest()


def tasks():
    programs = (
        ["A", "A"],
        ["A", "B"],
        ["B", "A"],
        ["B", "B"],
        ["A", "B", "A"],
        ["B", "A", "B"],
    )
    rows = [
        {"family": "new_composition", "start": n, "program": p, "budget": 3}
        for n in range(8)
        for p in programs
    ]
    rows += [
        {
            "family": "constraint",
            "start": n,
            "program": ["A", "B"],
            "budget": 1 if n < 4 else 3,
            "allowed_end": [0, 1, 2, 3],
        }
        for n in range(8)
    ]
    rows += [
        {
            "family": "version",
            "start": n,
            "program": ["A", "B"],
            "budget": 3,
            "required_versions": {f"A:{n}": 1},
        }
        for n in (0, 1)
    ]
    rows += [
        {"family": family, "start": n, "program": p, "budget": budget}
        for family, n, p, budget in (
            ("revocation", 2, ["A", "B"], 3),
            ("dependency", 3, ["B", "A"], 3),
            ("expiry", 7, ["B", "A"], 3),
            ("unknown", 8, ["A", "B"], 3),
            ("unknown", 0, ["C", "A"], 3),
            ("constraint", 0, ["A", "B", "A"], 2),
        )
    ]
    return [{"task_id": f"task-{i:02d}", **row} for i, row in enumerate(rows)]


def fixture():
    result = {
        "schema": "hepta-mem3-composition-v1",
        "seeds": SEEDS,
        "phases": PHASES,
        "arms": ARMS,
        "tasks": tasks(),
        "streams": [],
    }
    for seed in SEEDS:
        original = Owner(seed)
        facts = [
            {
                "source": f"{r}:{n}",
                "node": n,
                "relation": r,
                "value": original.facts[f"{r}:{n}"].label,
                "version": 1,
                "live": True,
                "expires": 3 if (r, n) == ("B", 7) else 100,
                "dependencies": [["A:2", 1]] if (r, n) == ("B", 3) else [],
            }
            for r in "AB"
            for n in range(8)
        ]
        stages = []
        for generation, phase in enumerate(PHASES, 1):
            if phase == "version":
                for fact in facts[:2]:
                    fact.update(value=(fact["value"] + 3) % 8, version=2)
            if phase == "revoke":
                facts[2].update(live=False, version=2)
            stages.append(
                {
                    "phase": phase,
                    "generation": generation,
                    "tick": 4 if phase == "expiry" else generation - 1,
                    "facts": copy.deepcopy(facts),
                }
            )
        result["streams"].append(
            {
                "seed": seed,
                "stages": stages,
                "features": {
                    f["source"]: original.features[f["source"]] for f in facts
                },
            }
        )
    return result


def metadata(facts):
    return {f["source"]: {k: v for k, v in f.items() if k != "value"} for f in facts}


def gate(meta, source, version, tick, required=None, seen=()):
    fact = meta.get(source)
    if fact is None:
        return "unknown"
    if source in seen:
        return "dependency_cycle"
    if not fact["live"]:
        return "revoked"
    if tick > fact["expires"]:
        return "expired"
    if version != fact["version"] or (required is not None and version != required):
        return "version"
    if any(
        gate(meta, parent, wanted, tick, seen=(*seen, source)) is not None
        for parent, wanted in fact["dependencies"]
    ):
        return "dependency"
    return None


def expected_answer(facts, task, tick):
    """Evaluator-only traversal; the actor composer never calls this function."""
    if len(task["program"]) > task["budget"]:
        return None
    by_source, meta = {f["source"]: f for f in facts}, metadata(facts)
    node = task["start"]
    for relation in task["program"]:
        source = f"{relation}:{node}"
        fact = by_source.get(source)
        required = task.get("required_versions", {}).get(source)
        if (
            fact is None
            or gate(meta, source, fact["version"], tick, required) is not None
        ):
            return None
        node = fact["value"]
    return node if "allowed_end" not in task or node in task["allowed_end"] else None
