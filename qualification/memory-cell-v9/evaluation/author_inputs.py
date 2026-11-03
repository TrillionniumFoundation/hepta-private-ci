"""Create-once V9 evaluation inputs independently of model implementation."""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from language_materials import CALIBRATION, CALIBRATION_REJECT, HELD, HELD_REJECT


ROOT = Path(__file__).resolve().parent
OPS = ("current", "history", "semantic", "procedure", "change", "apply")
NAMES = {
    "calibration": (("Canopy lamp", "冠层灯"), ("Orchard tray", "果园盘"), ("Fern chamber", "蕨室"),
                    ("Moss panel", "苔板"), ("Copper lathe", "铜车床"), ("Bronze jig", "青铜夹具"),
                    ("Iron spindle", "铁主轴"), ("Cobalt press", "钴压机"), ("Heron crate", "鹭箱"),
                    ("Kestrel pallet", "隼托盘"), ("Otter dock", "獭码头"), ("Badger trolley", "獾推车")),
    "held": (("Polar vial", "极地瓶"), ("Glacier rack", "冰川架"), ("Tundra flask", "冻原壶"),
             ("Fjord freezer", "峡湾冷柜"), ("Brook weir", "溪堰"), ("Lagoon float", "潟湖浮标"),
             ("Reef inlet", "礁口"), ("Estuary sluice", "河口闸"), ("Comet bin", "彗星仓格"),
             ("Meteor shelf", "流星货架"), ("Orbit locker", "轨道储柜"), ("Nebula stack", "星云垛")),
}


def unix(day):
    return int(datetime.fromisoformat(day).replace(tzinfo=timezone.utc).timestamp())


def raw_json(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()


def identity(raw):
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def owner_entities(split):
    result = []
    for i, aliases in enumerate(NAMES[split]):
        aliases = list(aliases)
        if i < 2:
            aliases.extend([f"Shared {split} channel", f"共用{split}通道"])
        records = [{"kind": "event", "effective_at": unix(day), "value": (i + 3) * multiplier - 31}
                   for day, multiplier in (("2024-07-01", 3), ("2025-07-01", -4), ("2026-03-01", 7))]
        records.extend([
            {"kind": "semantic", "effective_at": unix("2024-07-01"),
             "value": {"factor": i % 7 - 3, "label": f"{split}-attribute-{i}"}},
            {"kind": "procedure", "effective_at": unix("2024-07-01"),
             "value": {"opcode": ("identity", "add_bias", "multiply", "affine", "clamp")[i % 5],
                       "bias": 2 * i - 9, "limit": 61 + 13 * i}},
        ])
        result.append({"entity": f"unit:v9-{split}-{i:02}", "aliases": aliases, "records": records})
    return result


def language_suite(split):
    templates, negatives = (CALIBRATION, CALIBRATION_REJECT) if split == "calibration" else (HELD, HELD_REJECT)
    date = "2025-09-03" if split == "calibration" else "2025-11-17"
    cutoff, present = unix(date), unix("2026-09-01")
    entities, rows = owner_entities(split), []

    def append(family, language, entity, text, operation, category, at=present, since=cutoff):
        rows.append({"id": f"v9-{split}-{len(rows):04}", "family": f"v9-evaluator-{split}-{family}",
                     "language": language, "entity": entity, "text": text, "at": at, "since": since,
                     "expected_operation": operation, "category": category})

    for op_index, operation in enumerate(OPS):
        assert len(templates[operation]) == 12
        for wording, template in enumerate(templates[operation]):
            language, alias = ("en", 0) if wording < 6 else ("zh", 1)
            for replica in range(2):
                item = entities[(2 * op_index + wording + 5 * replica) % len(entities)]
                append(f"known-{operation}-{language}-{wording % 6}", language, item["entity"],
                       template.format(entity=item["aliases"][alias], date=date), operation, "known",
                       cutoff if operation == "history" else present)
    assert len(negatives) == 48
    for wording, template in enumerate(negatives):
        language, alias = ("en", 0) if wording < 24 else ("zh", 1)
        for replica in range(2):
            item = entities[(wording + 5 * replica) % len(entities)]
            append(f"unsupported-{language}-{wording % 24}", language, item["entity"],
                   template.format(entity=item["aliases"][alias], date=date), None, "unsupported")
    for alias, language in enumerate(("en", "zh")):
        for i in range(6):
            name = f"Unlisted {split} unit {i}" if alias == 0 else f"未登记{split}单元{i}"
            append(f"unknown-{language}-{i}", language, f"unit:v9-unknown-{split}-{i}",
                   templates["current"][6 * alias + i].format(entity=name, date=date), None, "unknown_entity")
        for i in range(4):
            name = f"Shared {split} channel" if alias == 0 else f"共用{split}通道"
            append(f"ambiguous-{language}-{i}", language, entities[i % 2]["entity"],
                   templates["current"][6 * alias + i].format(entity=name, date=date), None, "ambiguous_alias")
        for i in range(6):
            item, operation = entities[i], "history" if i % 2 == 0 else "change"
            wrong = cutoff + 3600 * (i + 1)
            append(f"time-conflict-{language}-{i}", language, item["entity"],
                   templates[operation][6 * alias + i].format(entity=item["aliases"][alias], date=date),
                   None, "time_conflict", wrong if operation == "history" else present,
                   cutoff if operation == "history" else wrong)
    return {"schema": "hepta.memory.v9.language-suite.v1", "split": split, "entities": entities, "rows": rows}


def task(identifier, family, addresses, operations, offset):
    return {"id": identifier, "family": family,
            "queries": [{"entity": entity, "operation": operations[i % len(operations)]}
                        for i, entity in enumerate(addresses)],
            "coefficients": [(-1 if (i + offset) % 3 == 0 else 1 + (i % 2)) for i in range(len(addresses))],
            "threshold": 7 * offset - 15}


def continual_suite():
    stages, prior = [], []
    domains = (("horticulture", "fabrication"), ("cryogenics", "hydrology"), ("logistics", "energy"))
    for stage, domain_pair in enumerate(domains):
        writes, current = [], []
        for i in range(8):
            entity = f"unit:v9-continual-{stage}-{i}"
            current.append(entity)
            writes.append({"entity": entity, "domain": domain_pair[i // 4], "event": 11 * i - 29 + 17 * stage,
                           "semantic": {"factor": (i + 2 * stage) % 7 - 3, "label": f"class-{stage}-{i % 3}"},
                           "procedure": {"opcode": ("affine", "clamp", "add_bias", "multiply")[i % 4],
                                         "bias": 3 * i - 5 * stage - 7, "limit": 31 + 9 * i + 11 * stage}})
        prefix = [task(f"s{stage}-prefix-{i:02}", "completed-observation", current[(i % 2) * 4:(i % 2 + 1) * 4],
                       ["current"], i) for i in range(16)]
        all_entities = prior + current
        future = []
        for i in range(24):
            family = ("local-new-domain", "bridge-old-new", "interleaved-programs")[i % 3]
            if i % 3 == 0:
                group = current[(i % 2) * 4:(i % 2 + 1) * 4]
                addresses = list(reversed(group)) + group[:2]
            elif i % 3 == 1:
                old = prior if prior else current[4:]
                addresses = [old[(i + j) % len(old)] if j % 2 == 0 else current[(i + j) % 8] for j in range(6)]
            else:
                addresses = [all_entities[(i + 5 * j) % len(all_entities)] for j in range(6)]
            future.append(task(f"s{stage}-future-{i:02}", family, addresses,
                               ["apply", "semantic", "procedure"], i + stage))
        retained = prior if prior else current[:4]
        retention = [task(f"s{stage}-retention-{i:02}", "earlier-written-facts",
                          [retained[(i + j) % len(retained)] for j in range(6)],
                          ["semantic", "procedure", "apply"], i) for i in range(8)]
        stages.append({"id": f"stage-{stage}", "writes": writes, "prefix": prefix,
                       "future": future, "retention": retention})
        prior.extend(current)
    return {"schema": "hepta.memory.v9.continual-fixture.v1", "stages": stages}


def main():
    lock = {"schema": "hepta.memory.v9.evaluator-input-lock.v1",
            "author": "root evaluator, distinct from addressing and learning implementers",
            "model_results_seen_before_authoring": False, "external_third_party": False,
            "iid_population_guarantee": False, "language_entity_replicas_per_wording": 2,
            "continual_domains_are_authored_use_cases_not_new_type_discovery": True,
            "training_receives_future_retention_family_or_domain_fields": False,
            "source_files": {name: identity((ROOT / name).read_bytes())
                             for name in ("author_inputs.py", "language_materials.py")}, "files": {}}
    values = {"calibration.json": language_suite("calibration"), "held.json": language_suite("held"),
              "continual-held.json": continual_suite()}
    for name, value in values.items():
        raw = raw_json(value)
        with (ROOT / name).open("xb") as stream:
            stream.write(raw)
        extra = ({"rows": len(value["rows"]), "entities": len(value["entities"]),
                  "categories": {category: sum(row["category"] == category for row in value["rows"])
                                 for category in sorted({row["category"] for row in value["rows"]})}}
                 if "rows" in value else {"stages": len(value["stages"]),
                                          "entities": sum(len(stage["writes"]) for stage in value["stages"])})
        lock["files"][name] = {**identity(raw), **extra}
    with (ROOT / "INPUT_LOCK.json").open("xb") as stream:
        stream.write(raw_json(lock))
    print(json.dumps(lock, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
