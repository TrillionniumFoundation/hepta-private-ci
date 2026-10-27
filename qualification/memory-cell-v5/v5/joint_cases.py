"""Post-freeze held-case creation with value-free, label-independent addresses."""

from collections import Counter
import json
import string

import numpy as np

from legacy_v3.numeric_graph import SERIES_NAMES
from .contracts import INTENTS, file_identity, sha256
from .graph_assets import Assets, DOMAINS
from .joint_binding import GATES as GATES, PROJECT as PROJECT, SEEDS as SEEDS, verify_freeze as verify_freeze
from .joint_binding import immutable_path, relative_path


OFFSETS = {"at": [0], "previous": [-1], "change": [-1, 0], "mean3": [-2, -1, 0], "range3": [-2, -1, 0], "peak3": [-2, -1, 0]}


def load_held(path, frozen):
    path = immutable_path(path)
    seal_path = immutable_path(path.parent / "SEAL.json")
    raw = seal_path.read_bytes()
    if sha256(raw) != frozen["held_seal_sha256"]:
        raise ValueError("independent held seal differs from pre-execution freeze")
    seal = json.loads(raw)
    if seal["schema"] != "hepta.memory.v5.held-seal.v1" or seal["sealed"] is not True or seal["evaluated_by_any_router"] is not False:
        raise ValueError("held authoring/seal boundary differs")
    if path.name != seal["corpus_file"] or path.name not in seal["files"]:
        raise ValueError("held language file differs from sealed source")
    corpus_raw = None
    for name, expected in seal["files"].items():
        source = immutable_path(path.parent.joinpath(*relative_path(name).parts))
        payload = source.read_bytes()
        if {"bytes": len(payload), "sha256": sha256(payload)} != expected:
            raise ValueError("held seal file bytes differ: " + name)
        if source == path:
            corpus_raw = payload
    if corpus_raw is None:
        raise ValueError("held corpus is absent from the complete seal inventory")
    if seal["inference_fields"] != ["utterance", "series_name", "date"]:
        raise ValueError("held inference field contract differs")
    document = json.loads(corpus_raw)
    if set(document) != {"schema", "queries"} or document["schema"] != "hepta.memory.v5.sealed-language.v1":
        raise ValueError("held corpus schema differs")
    rows = document["queries"]
    required = {"query_id", "utterance", "series_name", "date", "gold_intent", "ood_family", "risk_group",
                "partition", "language", "allow_numeric_read", "expected_provenance_offsets", "requested_operator", "label_reason"}
    if len(rows) != 216 or len({row["query_id"] for row in rows}) != 216:
        raise ValueError("held inventory must contain 216 independent template IDs")
    counts = Counter()
    families = Counter()
    for row in rows:
        if set(row) != required or row["partition"] != "sealed_held_v5" or row["language"] != "en":
            raise ValueError("held row fields or partition differ")
        if row["series_name"] != "{series_name}" or row["date"] != "{date}":
            raise ValueError("held slots must not encode task labels")
        fields = []
        for _, field, spec, conversion in string.Formatter().parse(row["utterance"]):
            if field is not None:
                if field not in {"series_name", "date"} or spec or conversion:
                    raise ValueError("unsupported held template interpolation")
                fields.append(field)
        if set(fields) != {"series_name", "date"}:
            raise ValueError("held template must include both explicit address slots")
        intent = row["gold_intent"]
        if intent is None:
            if row["risk_group"] != "near" or row["allow_numeric_read"] is not False or not row["ood_family"]:
                raise ValueError("held OOD annotations disagree")
            families[row["ood_family"]] += 1
        else:
            if intent not in INTENTS or row["risk_group"] != "known" or row["ood_family"] is not None or row["allow_numeric_read"] is not True or row["expected_provenance_offsets"] != OFFSETS[intent]:
                raise ValueError("held supported-operation annotations disagree")
            counts[intent] += 1
    if counts != Counter({intent: 24 for intent in INTENTS}) or len(families) != 12 or set(families.values()) != {6}:
        raise ValueError("held intent/OOD family denominators differ")
    if seal["counts"]["total"] != 216 or seal["counts"]["known"] != 144 or seal["counts"]["near_ood"] != 72:
        raise ValueError("held seal denominator differs")
    if seal["counts"]["per_intent"] != dict(counts) or seal["counts"]["per_ood_family"] != dict(families) or seal["corpus_schema"] != document["schema"]:
        raise ValueError("held seal per-class inventory or corpus schema differs")
    return rows, {"seal": file_identity(seal_path), "corpus": file_identity(path), "counts": seal["counts"]}


def previous_month(address, offset):
    serial = address[0] * 12 + address[1] - 1 + offset
    return serial // 12, serial % 12 + 1


def uniform_addresses(reader, count, seed, domain):
    positions = {year: index for index, year in enumerate(reader.years)}
    valid = []
    for year in reader.years:
        for month in range(1, 13):
            addresses = [previous_month((year, month), offset) for offset in (-2, -1, 0)]
            if all(y in positions and reader.bank.mask[positions[y], m - 1] for y, m in addresses):
                valid.append((year, month))
    if not valid:
        raise ValueError("no available complete three-month windows")
    indices = np.arange(count, dtype=np.int64) * len(valid) // count
    order = np.random.default_rng(seed + 7919 + DOMAINS.index(domain) * 104729).permutation(count)
    chosen = [valid[int(indices[index])] for index in order]
    return chosen, {"eligible_three_month_addresses": len(valid), "requested_addresses": count,
                    "unique_selected_addresses": len(set(chosen)), "selection": "uniform rank grid, then seed/domain-only permutation",
                    "labels_predictions_and_numeric_values_used": False}


def independent_target(exact, domain, intent, address):
    if intent is None:
        return None
    positions = {year: index for index, year in enumerate(exact.years)}
    coordinates = [previous_month(address, offset) for offset in OFFSETS[intent]]
    values = []
    for year, month in coordinates:
        if year not in positions or not exact.mask[positions[year], month - 1]:
            raise ValueError("grader address is absent from the exact source")
        values.append(int(exact.matrix[positions[year], month - 1]))
    if intent in {"at", "previous"}:
        value = values[0]
    elif intent == "change":
        value = values[1] - values[0]
    elif intent == "mean3":
        value = (values[0] + values[1] + values[2]) / 3
    elif intent == "range3":
        value = max(values) - min(values)
    else:
        value = max(values)
    return {"kind": "number", "value": value, "support": [f"{domain}:{year:04d}-{month:02d}" for year, month in coordinates]}


def make_cases(templates, assets_directory, domain, seed):
    assets = Assets(assets_directory)
    parameter = assets.parameter(domain)
    exact, exact_info = assets.exact(domain)
    if parameter.years != exact.years or not np.array_equal(parameter.bank.mask, exact.mask):
        raise ValueError("parameter and exact address availability differ")
    addresses, schedule = uniform_addresses(parameter, len(templates), seed, domain)
    requests, graders = [], []
    for index, (template, address) in enumerate(zip(templates, addresses, strict=True)):
        date = f"{address[0]:04d}-{address[1]:02d}"
        request = {"utterance": template["utterance"].format(series_name=SERIES_NAMES[domain], date=date),
                   "series_name": SERIES_NAMES[domain], "date": date}
        target = independent_target(exact, domain, template["gold_intent"], address)
        requests.append(request)
        graders.append({"index": index, "template_id": template["query_id"], "gold_intent": template["gold_intent"],
                        "ood_family": template["ood_family"], "address": list(address), "target": target,
                        "authored_expected_provenance_offsets": template["expected_provenance_offsets"],
                        "requested_operator": template["requested_operator"], "label_reason": template["label_reason"]})
    return requests, graders, {"address_schedule": schedule, "strong_source": exact_info, "source_files": assets.verify_consumed()}
