"""Fresh authored values and train/calibration language; no held templates."""

import hashlib
import json

import numpy as np

from export_native import canonical, sha


ADJECTIVES = ("Amber", "Azure", "Brass", "Cobalt", "Coral", "Crimson", "Copper", "Gold",
              "Indigo", "Ivory", "Jade", "Lilac", "Olive", "Pearl", "Silver", "Violet")
NOUNS = ("Anchor", "Badger", "Canyon", "Dolphin", "Falcon", "Garden", "Heron", "Island")
OPCODES = ("keep", "reserve_gap", "pack", "cap", "add_reserve", "halve", "stop")
TEMPLATES = {
    "train": {
        "semantic": ["Read the reserve, pack and limit for {entity}.", "What stock policy belongs to {entity}?"],
        "skill": ["List the four procedure steps of {workflow}.", "Which operations define {workflow}?"],
        "compose": ["Execute {workflow} using the latest inventory at {entity}.", "Apply {workflow} to the current stock of {entity}."],
        "unknown": ["Translate a poem about {entity}.", "Erase the policy for {entity}.",
                    "Read the policy of {unknown_entity}.", "Read the policy for {entity} and {second_entity}."]},
    "calibration": {
        "semantic": ["Show {entity}'s inventory thresholds.", "Retrieve the three stored policy numbers of {entity}."],
        "skill": ["Inspect the operation sequence called {workflow}.", "Give the saved workflow instructions for {workflow}."],
        "compose": ["Calculate the outcome at {entity} with {workflow}.", "Run {workflow} on the current record for {entity}."],
        "unknown": ["Sell shares in {entity}.", "Predict the weather for {entity}.",
                    "Retrieve inventory rules from {unknown_entity}.", "Show both {entity}'s and {second_entity}'s policies."]},
}


def entity_name(index):
    return f"{ADJECTIVES[index // 8]} {NOUNS[index % 8]} Depot"


def workflow_name(index):
    return f"{ADJECTIVES[(index // 8 + 5) % 16]} {NOUNS[(index % 8 + 3) % 8]} Circuit"


def source_id(kind, index, version=0):
    return sha(canonical(["memory-v10-authored", kind, index, version]))


def records(capacity, *, dataset_seed=817400):
    if capacity not in (32, 64, 128):
        raise ValueError("undeclared capacity")
    # Generate the full population before slicing so prefixes remain identical.
    rng = np.random.default_rng(dataset_seed)
    policies = rng.integers(0, 16, (128, 3))
    programs = np.concatenate((rng.integers(0, 6, (128, 3)), np.full((128, 1), 6)), axis=1)
    events = rng.integers(-12, 65, 128)
    rows = []
    for kind, names, values in (("semantic", entity_name, policies), ("procedure", workflow_name, programs)):
        for index in range(capacity):
            name = names(index)
            rows.append({"kind": kind, "index": index, "key": name, "value": values[index].tolist(),
                         "canonical_text": f"{'Inventory policy' if kind == 'semantic' else 'Operational procedure'} record: {name}.",
                         "source_id": source_id(kind, index), "version": 0, "active": True})
    return {"records": rows, "events": events[:capacity].tolist(),
            "event_records": [{"index": index, "effective_at": at, "value": int(events[index]) + delta,
                               "source_id": source_id("event", index, at)}
                              for index in range(capacity) for at, delta in ((10, -3), (20, 0))],
            "hold_records": [{"index": index, "effective_at": 20, "value": index % 17 == 9,
                              "source_id": source_id("hold", index)} for index in range(capacity)],
            "holds": [index for index in range(capacity) if index % 17 == 9]}


def targets(values, kind):
    if kind == "semantic":
        return np.asarray([[(value >> bit) & 1 for value in row for bit in range(4)]
                           for row in values], dtype=np.float32)
    return np.concatenate([np.eye(7, dtype=np.float32)[np.asarray(values)[:, i]] for i in range(4)], axis=1)


def pairs(capacity, phase):
    offsets = {"train": (0, 1), "calibration": (5, 7), "held": (11, 13)}[phase]
    return [(i, (i + offset) % capacity) for i in range(capacity) for offset in offsets]


def queries(capacity, phase, templates=None):
    templates = TEMPLATES[phase] if templates is None else templates
    result = []
    for role, texts in templates.items():
        indices = pairs(capacity, phase) if role == "compose" else [(i, i) for i in range(capacity)]
        for group, text in enumerate(texts):
            for entity, workflow in indices:
                result.append({"id": f"{phase}:{role}:{group}:{entity}:{workflow}",
                               "text": text.format(entity=entity_name(entity), workflow=workflow_name(workflow),
                                                   second_entity=entity_name((entity + 1) % capacity),
                                                   unknown_entity=f"Quartz {phase.title()} {entity} Depot"),
                               "role": role, "entity": entity if role in ("semantic", "compose") else None,
                               "workflow": workflow if role in ("skill", "compose") else None,
                               "wording_group": f"{phase}:{role}:{group}"})
    return result


def interpret(value, policy, program, *, hold=False, budget=4):
    """A bounded reference contract; integer division is floor division."""
    if hold:
        return {"status": "held", "value": None, "trace": []}
    reserve, pack, limit = policy
    trace = []
    for position, opcode in enumerate(program):
        if position >= budget:
            return {"status": "budget_stop", "value": None, "trace": trace}
        if type(opcode) is not int or not 0 <= opcode < 7:
            return {"status": "invalid_program", "value": None, "trace": trace}
        before = value
        if opcode == 1:
            value = max(0, reserve - value)
        elif opcode == 2:
            value *= pack
        elif opcode == 3:
            value = min(value, limit)
        elif opcode == 4:
            value += reserve
        elif opcode == 5:
            value //= 2
        if not -(2**63) <= value < 2**63:
            return {"status": "overflow", "value": None, "trace": trace}
        trace.append({"op": OPCODES[opcode], "before": before, "after": value})
        if opcode == 6:
            return {"status": "completed", "value": value, "trace": trace}
    return {"status": "missing_stop", "value": None, "trace": trace}
