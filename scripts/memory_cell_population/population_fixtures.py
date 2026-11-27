"""Registered source-derived heterogeneous memory and untouched transfer probes.

Exact recall, event interpolation and procedure extrapolation are distinct tasks.
The finite suite does not certify arbitrary general memory or unseen programs.
"""

import hashlib
import json
import random


SEEDS = (1907, 2719, 4051)
TRAIN_TEMPLATES = (
    "What is the {relation} for {entity}?",
    "Recall the {relation} of {entity}.",
    "For {entity}, return the stored {relation}.",
    "Give {entity}'s {relation}.",
)
SELECTION_TEMPLATE = "In this memory, which {relation} belongs to {entity}?"
RETENTION_TEMPLATE = (
    "According to the retained record, state the {relation} associated with {entity}."
)
COLORS = ("red", "blue", "green", "yellow", "black", "white", "orange", "purple")
LOCATIONS = (
    "harbor",
    "garden",
    "market",
    "station",
    "museum",
    "tower",
    "bridge",
    "park",
)
PROTOCOL = {
    "schema": "hepta.population.source-fixtures.v1",
    "seeds": list(SEEDS),
    "semantic_sources": 16,
    "event_sources": 24,
    "procedure_sources": 4,
    "training_examples": 64,
    "event_days": [1, 3, 5],
    "event_transfer_days": [2, 4],
    "procedure_training_inputs": list(range(6)),
    "procedure_transfer_inputs": list(range(6, 10)),
    "procedure_dsl": "(multiplier * input + offset) mod 11",
    "selection_contains_transfer_queries": False,
    "routing_features_may_include_final_answers": False,
    "general_memory_proven": False,
}


def canonical_bytes(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode()


def source_digest(source):
    return hashlib.sha256(canonical_bytes(source)).hexdigest()


def _record(source):
    return {**source, "source_digest": source_digest(source)}


def validate_sources(sources):
    """Check the complete closed source ledger before computing baseline answers."""
    fields = {
        "semantic": {"kind", "entity", "relation", "value", "source_digest"},
        "episode": {"kind", "entity", "day", "location", "source_digest"},
        "procedure": {
            "kind",
            "rule",
            "operation",
            "multiplier",
            "offset",
            "modulus",
            "source_digest",
        },
    }
    if type(sources) is not list or not 1 <= len(sources) <= 128:
        raise ValueError("bounded source ledger required")
    roots, keys = set(), set()
    for row in sources:
        if (
            type(row) is not dict
            or type(row.get("kind")) is not str
            or row["kind"] not in fields
        ):
            raise ValueError("unknown source kind")
        if set(row) != fields[row["kind"]]:
            raise ValueError("closed source schema required")
        text_fields = {
            "semantic": ("entity", "relation", "value"),
            "episode": ("entity", "location"),
            "procedure": ("rule", "operation"),
        }
        if any(
            type(row[k]) is not str or not 1 <= len(row[k].encode()) <= 1024
            for k in text_fields[row["kind"]]
        ):
            raise ValueError("bounded source strings required")
        unsigned = {k: v for k, v in row.items() if k != "source_digest"}
        root = source_digest(unsigned)
        if row["source_digest"] != root or root in roots:
            raise ValueError("source digest mismatch or duplicate source")
        roots.add(root)
        if row["kind"] == "semantic":
            key = row["kind"], row["entity"], row["relation"]
        elif row["kind"] == "episode":
            if type(row["day"]) is not int or row["day"] < 1:
                raise ValueError("positive integer event day required")
            key = row["kind"], row["entity"], row["day"]
        else:
            if (
                row["operation"] != "affine_mod"
                or any(
                    type(row[k]) is not int for k in ("multiplier", "offset", "modulus")
                )
                or not 1 <= row["multiplier"] <= 4
                or not 0 <= row["offset"] < 11
                or row["modulus"] != 11
            ):
                raise ValueError("registered bounded procedure required")
            key = row["kind"], row["rule"]
        if key in keys:
            raise ValueError("ambiguous source key")
        keys.add(key)
    return sources


def exact_baseline(sources, operation):
    """Execute a closed request from original sources; never inspect probe gold."""
    validate_sources(sources)
    if type(operation) is not dict or type(operation.get("kind")) is not str:
        raise ValueError("closed structured operation required")
    kind = operation["kind"]
    shapes = {
        "semantic": {"kind", "entity", "relation"},
        "event_at": {"kind", "entity", "day"},
        "event_asof": {"kind", "entity", "day"},
        "procedure": {"kind", "rule", "input"},
    }
    if kind not in shapes or set(operation) != shapes[kind]:
        raise ValueError("unknown or nonclosed operation")
    if any(
        type(operation[k]) is not str or not 1 <= len(operation[k].encode()) <= 1024
        for k in shapes[kind] - {"day", "input"}
    ):
        raise ValueError("bounded operation strings required")
    if kind == "semantic":
        rows = [
            r
            for r in sources
            if r["kind"] == "semantic"
            and r["entity"] == operation["entity"]
            and r["relation"] == operation["relation"]
        ]
        return (
            (rows[0]["value"], [rows[0]["source_digest"]]) if rows else ("unknown", [])
        )
    if kind in ("event_at", "event_asof"):
        if type(operation["day"]) is not int or not 0 <= operation["day"] <= 100:
            raise ValueError("bounded integer event query required")
        events = [
            r
            for r in sources
            if r["kind"] == "episode" and r["entity"] == operation["entity"]
        ]
        if kind == "event_at":
            eligible = [r for r in events if r["day"] == operation["day"]]
            return (
                (eligible[0]["location"], [eligible[0]["source_digest"]])
                if eligible
                else ("unknown", [])
            )
        eligible = [r for r in events if r["day"] <= operation["day"]]
        roots = sorted(r["source_digest"] for r in events)
        return (
            (max(eligible, key=lambda r: r["day"])["location"], roots)
            if eligible
            else ("unknown", roots)
        )
    if type(operation["input"]) is not int or not 0 <= operation["input"] <= 100:
        raise ValueError("bounded integer procedure input required")
    rows = [
        r
        for r in sources
        if r["kind"] == "procedure" and r["rule"] == operation["rule"]
    ]
    if not rows:
        return "unknown", []
    rule = rows[0]
    value = (rule["multiplier"] * operation["input"] + rule["offset"]) % rule["modulus"]
    return str(value), [rule["source_digest"]]


def dataset(seed):
    """Return stable sources, training examples and separately named probe sets."""
    if type(seed) is not int or seed not in SEEDS:
        raise ValueError("one of the three registered seeds required")
    rng = random.Random(seed)
    scope = f"population-{seed}"
    sources = []
    for i in range(16):
        sources.append(
            _record(
                {
                    "kind": "semantic",
                    "entity": f"person N{i:02d}",
                    "relation": "color",
                    "value": rng.choice(COLORS),
                }
            )
        )
    for i in range(8):
        visits = rng.sample(LOCATIONS, 3)
        for day, location in zip((1, 3, 5), visits, strict=True):
            sources.append(
                _record(
                    {
                        "kind": "episode",
                        "entity": f"courier E{i:02d}",
                        "day": day,
                        "location": location,
                    }
                )
            )
    multipliers = rng.sample((1, 2, 3, 4), 4)
    for i in range(4):
        sources.append(
            _record(
                {
                    "kind": "procedure",
                    "rule": f"rule P{i:02d}",
                    "operation": "affine_mod",
                    "multiplier": multipliers[i],
                    "offset": rng.randrange(11),
                    "modulus": 11,
                }
            )
        )
    validate_sources(sources)
    facts, families, operations, groups = [], [], [], []

    def fact(source, entity, relation, value, family, operation):
        facts.append(
            {
                "scope": scope,
                "entity": entity,
                "relation": relation,
                "value": value,
                "source_digest": source["source_digest"],
            }
        )
        families.append(family)
        operations.append(operation)
        if family == "semantic":
            groups.append("semantic:" + source["entity"])
        elif family == "episode":
            groups.append("event-history:" + source["entity"])
        else:
            groups.append("program:" + source["rule"])

    for source in sources:
        family = source["kind"]
        if family == "semantic":
            operation = {
                "kind": "semantic",
                "entity": source["entity"],
                "relation": source["relation"],
            }
            fact(
                source,
                source["entity"],
                source["relation"],
                source["value"],
                family,
                operation,
            )
        elif family == "episode":
            operation = {
                "kind": "event_at",
                "entity": source["entity"],
                "day": source["day"],
            }
            fact(
                source,
                f"{source['entity']} on day {source['day']}",
                "location",
                source["location"],
                family,
                operation,
            )
        else:
            for x in range(6):
                operation = {"kind": "procedure", "rule": source["rule"], "input": x}
                value, _ = exact_baseline(sources, operation)
                fact(
                    source,
                    f"{source['rule']} with input {x}",
                    "result",
                    value,
                    family,
                    operation,
                )

    def probe(name, question, operation, family):
        value, roots = exact_baseline(sources, operation)
        return {
            "probe_id": name,
            "question": question,
            "value": value,
            "source_roots": roots,
            "family": family,
            "operation": operation,
        }

    def recall_probes(prefix, template):
        return [
            probe(
                f"{prefix}-{i:03d}",
                template.format(entity=f["entity"], relation=f["relation"]),
                op,
                family,
            )
            for i, (f, op, family) in enumerate(
                zip(facts, operations, families, strict=True)
            )
        ]

    transfer = []
    for i in range(8):
        for day in (2, 4):
            operation = {
                "kind": "event_asof",
                "entity": f"courier E{i:02d}",
                "day": day,
            }
            transfer.append(
                probe(
                    f"event-transfer-{i}-{day}",
                    f"As of day {day}, where was courier E{i:02d} according to its latest recorded visit?",
                    operation,
                    "event_interpolation",
                )
            )
    for i in range(4):
        for x in range(6, 10):
            operation = {"kind": "procedure", "rule": f"rule P{i:02d}", "input": x}
            transfer.append(
                probe(
                    f"procedure-transfer-{i}-{x}",
                    f"Apply rule P{i:02d} to the unseen input {x}. What result does it produce?",
                    operation,
                    "procedure_extrapolation",
                )
            )
    ood = []
    for i in range(4):
        requests = [
            (
                f"unknown-person-{i}",
                f"What is the color for person U{i:02d}?",
                {"kind": "semantic", "entity": f"person U{i:02d}", "relation": "color"},
            ),
            (
                f"unknown-relation-{i}",
                f"What is the temperature for person N{i:02d}?",
                {
                    "kind": "semantic",
                    "entity": f"person N{i:02d}",
                    "relation": "temperature",
                },
            ),
            (
                f"unknown-courier-{i}",
                f"Where was courier U{i:02d} as of day 2?",
                {"kind": "event_asof", "entity": f"courier U{i:02d}", "day": 2},
            ),
            (
                f"unknown-rule-{i}",
                f"What result does rule U{i:02d} give for input 7?",
                {"kind": "procedure", "rule": f"rule U{i:02d}", "input": 7},
            ),
        ]
        for name, question, operation in requests:
            ood.append(probe(name, question, operation, "unknown"))
    for i in range(8):
        ood.append(
            probe(
                f"before-first-event-{i}",
                f"Where was courier E{i:02d} as of day 0?",
                {"kind": "event_asof", "entity": f"courier E{i:02d}", "day": 0},
                "unknown",
            )
        )
    reject_training = []
    for i in range(3):
        requests = [
            (
                f"reject-person-{i}",
                f"Recall the color associated with person Z{i:02d}.",
                {"kind": "semantic", "entity": f"person Z{i:02d}", "relation": "color"},
            ),
            (
                f"reject-relation-{i}",
                f"Give the stored weight of person N{i + 8:02d}.",
                {
                    "kind": "semantic",
                    "entity": f"person N{i + 8:02d}",
                    "relation": "weight",
                },
            ),
            (
                f"reject-courier-{i}",
                f"Recall courier Z{i:02d}'s last location before day 4.",
                {"kind": "event_asof", "entity": f"courier Z{i:02d}", "day": 4},
            ),
            (
                f"reject-rule-{i}",
                f"Return the result of rule Z{i:02d} on input 3.",
                {"kind": "procedure", "rule": f"rule Z{i:02d}", "input": 3},
            ),
        ]
        for name, question, operation in requests:
            reject_training.append(probe(name, question, operation, "unknown"))
    return {
        "schema": PROTOCOL["schema"],
        "seed": seed,
        "scope": scope,
        "sources": sources,
        "sources_sha256": source_digest(sources),
        "train_facts": facts,
        "parent_facts": [dict(f) for f in facts[:16]],
        "family_by_training_index": families,
        "partition_groups": groups,
        "train_templates": list(TRAIN_TEMPLATES),
        "router_training": recall_probes("router", TRAIN_TEMPLATES[0]),
        "router_reject_training": reject_training,
        "source_selection": recall_probes("selection", SELECTION_TEMPLATE),
        "retention_final": recall_probes("retention", RETENTION_TEMPLATE),
        "transfer_final": transfer,
        "ood_final": ood,
        "protocol": json.loads(json.dumps(PROTOCOL)),
    }
