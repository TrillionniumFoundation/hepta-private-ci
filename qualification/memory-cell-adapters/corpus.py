"""Finite authored operations memory; targets never enter encoder input.

Training and calibration wording are declared here. Held wording is authored in
a separate file and is loaded only by the evaluation stage after training exits.
The task has arbitrary post-pretraining facts and a bounded program vocabulary;
it is not a benchmark of open-world language understanding.
"""

from runtime_contract import ENTITIES, WORKFLOWS, ROLES, canonical, digest, source_id


POLICIES = ((11, 3, 14), (7, 2, 13), (13, 4, 9), (9, 1, 12),
            (6, 3, 15), (14, 2, 8), (8, 4, 11), (12, 1, 10))
PROGRAMS = ((1, 2, 3, 6), (4, 5, 3, 6), (2, 1, 3, 6), (5, 4, 3, 6),
            (1, 3, 2, 6), (3, 5, 4, 6), (2, 3, 5, 6), (4, 3, 5, 6))
TRAIN = {
    "semantic": ["What are the inventory policy numbers for {entity}?",
                 "Read the reserve, pack and limit settings of {entity}.",
                 "Give me the stored stock policy for {entity}.",
                 "List {entity}'s inventory parameters.",
                 "Retrieve the three policy values assigned to {entity}.",
                 "Which reserve level and packing limits does {entity} use?"],
    "skill": ["What are the four operations in {workflow}?",
              "Retrieve the stored program called {workflow}.",
              "Show the sequence of actions for {workflow}.",
              "Read the instruction steps of {workflow}.",
              "Which operations are encoded by {workflow}?",
              "Give the ordered procedure for {workflow}."],
    "compose": ["Execute {workflow} on the latest stock count for {entity}.",
                "Use {entity}'s current inventory and policy to run {workflow}.",
                "Calculate the action for {entity} using {workflow}.",
                "Apply {workflow} to the newest event for {entity}.",
                "Run the {workflow} procedure with the live state of {entity}.",
                "Determine the result of {workflow} for {entity} now."],
    "unknown": ["Predict tomorrow's weather at {entity}.",
                "Translate a poem about {entity}.",
                "Delete every file associated with {entity}.",
                "Buy shares for {entity} using {workflow}.",
                "Change the credentials for {entity}.",
                "Invent a new workflow for {entity}."]}
CALIBRATION = {
    "semantic": ["Inspect the stock rules currently stored under {entity}.",
                 "I need {entity}'s reserve, pack size, and upper bound."],
    "skill": ["Explain the registered action sequence named {workflow}.",
              "Read back the steps that define {workflow}."],
    "compose": ["Work out today's inventory action at {entity} via {workflow}.",
                "Combine the latest observation of {entity} with {workflow} to get the result."],
    "unknown": ["Schedule a flight to {entity}.",
                "Give me medical advice based on {workflow}."]}


def memory_rows():
    result = []
    for kind, names, values in (("semantic", ENTITIES, POLICIES), ("skill", WORKFLOWS, PROGRAMS)):
        for i, (name, value) in enumerate(zip(names, values, strict=True)):
            result.append({"kind": kind, "index": i, "name": name, "value": list(value),
                           "source_id": source_id(kind, i), "version": 0})
    return result


def canonical_key(kind, index):
    if kind == "semantic":
        return f"Inventory policy record: {ENTITIES[index]}."
    return f"Operational procedure record: {WORKFLOWS[index]}."


def bits(values):
    return [(int(value) >> bit) & 1 for value in values for bit in range(4)]


def query_rows(templates, phase):
    rows = []
    for role in ROLES:
        for wording, template in enumerate(templates[role]):
            pairs = [(i, j) for i in range(8) for j in range(8)
                     if (i + j) % 4 == (1 if phase == "held" else 0)] if role == "compose" else [(i, i) for i in range(8)]
            for entity, workflow in pairs:
                # Held pair combinations are disjoint from train/calibration.
                rows.append({"id": f"{phase}:{role}:{wording}:{entity}:{workflow}",
                             "text": template.format(entity=ENTITIES[entity], workflow=WORKFLOWS[workflow]),
                             "role": role, "entity": entity if role in ("semantic", "compose") else None,
                             "workflow": workflow if role in ("skill", "compose") else None,
                             "wording_group": f"{phase}:{role}:{wording}"})
    return rows


