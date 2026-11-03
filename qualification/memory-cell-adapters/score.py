"""Evaluator-only ground truth; never imported by a model/owner reader."""

from collections import defaultdict

from corpus import POLICIES, PROGRAMS
from runtime_contract import OPCODES


def reference(entity, workflow, event_shift):
    if entity == 7:
        return {"status": "exception_stop", "value": None, "ops": []}
    value = (3*entity + 5 + event_shift) % 17
    reserve, pack, limit = POLICIES[entity]
    operations = {
        0: lambda x: x,
        1: lambda x: reserve-x if reserve > x else 0,
        2: lambda x: x*pack,
        3: lambda x: limit if x > limit else x,
        4: lambda x: x+reserve,
        5: lambda x: x//2,
    }
    names = []
    for operation in PROGRAMS[workflow]:
        names.append(OPCODES[operation])
        if operation == 6:
            return {"status": "completed", "value": value, "ops": names}
        value = operations[operation](value)
    raise ValueError("reference program missing stop")


def expected(row, event_shift):
    if row["role"] == "unknown":
        return {"status": "abstain", "value": None}
    if row["role"] == "semantic":
        return {"status": "read", "value": list(POLICIES[row["entity"]])}
    if row["role"] == "skill":
        return {"status": "read", "value": list(PROGRAMS[row["workflow"]])}
    return reference(row["entity"], row["workflow"], event_shift)


def score(report, held_rows, event_shift, expected_arms):
    by_id = {row["id"]: row for row in held_rows}
    if len(by_id) != len(held_rows) or report["arms"] != list(expected_arms) or len(set(expected_arms)) != len(expected_arms):
        raise ValueError("held/arm inventory mismatch")
    result = defaultdict(lambda: {"roles": {}, "wording_groups": {}})
    seen = set()
    for record in report["rows"]:
        key = (record["arm"], record["query_id"])
        if key in seen or record["arm"] not in expected_arms or record["query_id"] not in by_id:
            raise ValueError("duplicate or unrequested reader result")
        seen.add(key)
        row = by_id[record["query_id"]]
        inapplicable = record["arm"] == "joint/oracle" and row["role"] != "compose"
        if bool(record.get("skipped")) != inapplicable:
            raise ValueError("unplanned skip or missing joint not-applicable marker")
        if inapplicable:
            continue
        target = expected(row, event_shift)
        actual = record["result"]
        correct = actual["status"] == target["status"] and actual.get("value") == target["value"]
        address_correct = all(record["route"][k] == row[k] for k in ("role", "entity", "workflow"))
        if row["role"] != "unknown":
            correct = correct and address_correct
        if "ops" in target:
            correct = correct and [x["op"] for x in actual.get("trace", [])] == target["ops"]
        for container, key in ((result[record["arm"]]["roles"], row["role"]),
                               (result[record["arm"]]["wording_groups"], row["wording_group"])):
            counts = container.setdefault(key, {"correct": 0, "count": 0, "address_correct": 0,
                                                "accepted": 0, "unsupported_accept": 0})
            counts["correct"] += int(correct)
            counts["count"] += 1
            counts["address_correct"] += int(address_correct)
            counts["accepted"] += int(actual["status"] not in ("abstain", "not_applicable"))
            counts["unsupported_accept"] += int(row["role"] == "unknown" and actual["status"] != "abstain")
    if seen != {(arm, identity) for arm in expected_arms for identity in by_id}:
        raise ValueError("reader result inventory differs from frozen arm/query product")
    return dict(result)


def aggregate(scores):
    arms = defaultdict(lambda: defaultdict(lambda: {"correct": 0, "count": 0, "address_correct": 0,
                                                  "accepted": 0, "unsupported_accept": 0}))
    for entry in scores:
        for arm, result in entry["scores"].items():
            for role, counts in result["roles"].items():
                for key, value in counts.items():
                    arms[arm][role][key] += value
    return {arm: dict(roles) for arm, roles in arms.items()}
