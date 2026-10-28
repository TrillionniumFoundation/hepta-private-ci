"""Strict native-compatible evaluation inputs and independent typed-value gold.

The fixture contains no fabricated owner digest. A Rust runner creates the
records through the real owner and fills the resulting scope into each request.
Evaluation labels are separate fields and never enter a worker request.
"""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re

from addressing.contracts import AddressError, OPERATIONS, OwnerRegistry, canonical, digest, normalize


SCHEMA = "hepta.memory.v9.language-suite.v1"
CATEGORIES = {"known", "unsupported", "unknown_entity", "ambiguous_alias", "time_conflict"}
IDENTITY = re.compile(r"[A-Za-z0-9][A-Za-z0-9:_.\-/]{0,127}")
MAX_TIME = 2**53 - 1


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate evaluation field")
        result[key] = value
    return result


def bounded_integer(value, low, high):
    return type(value) is int and low <= value <= high


def identifier(value):
    return isinstance(value, str) and IDENTITY.fullmatch(value) is not None


def validate_value(kind, value):
    if kind == "event":
        valid = bounded_integer(value, -1_000_000, 1_000_000)
    elif kind == "semantic":
        valid = (isinstance(value, dict) and set(value) == {"factor", "label"}
                 and bounded_integer(value["factor"], -1_000_000, 1_000_000)
                 and isinstance(value["label"], str) and 1 <= len(value["label"].encode()) <= 256
                 and "\0" not in value["label"])
    elif kind == "procedure":
        valid = (isinstance(value, dict) and set(value) == {"opcode", "bias", "limit"}
                 and value["opcode"] in ("identity", "add_bias", "multiply", "affine", "clamp")
                 and bounded_integer(value["bias"], -1_000_000, 1_000_000)
                 and bounded_integer(value["limit"], 0, 1_000_000))
    else:
        valid = False
    if not valid:
        raise ValueError("value is not a native typed-arithmetic-v1 value")


def native_request(row, scope):
    if not identifier(scope):
        raise ValueError("invalid observed native owner scope")
    return {"schema": "hepta.memory.request.v1", "query_id": row["id"], "scope": scope,
            "entity": row["entity"], "text": row["text"], "at": row["at"], "since": row["since"],
            "max_hops": 8, "max_cells": 8}


def registry_for(suite):
    # This synthetic identity is used ONLY for deterministic offline text
    # normalization. Actual native requests must bind their real owner's cut.
    return OwnerRegistry({"schema": "hepta.memory.v7.owner-registry.v1", "scope": "fixture:normalization",
                          "source_cut": digest(suite["entities"]),
                          "entities": [{"entity": item["entity"], "aliases": item["aliases"]} for item in suite["entities"]]})


def resolved_text(row, registry):
    request = native_request(row, "fixture:normalization")
    request.pop("schema")
    return registry.resolve(request)


def expected_value(suite, row):
    if row["expected_operation"] is None:
        return None
    item = next(item for item in suite["entities"] if item["entity"] == row["entity"])
    operation = row["expected_operation"]
    def latest(kind, cutoff=MAX_TIME):
        records = [record for record in item["records"] if record["kind"] == kind and record["effective_at"] <= cutoff]
        if not records:
            raise ValueError("known evaluation query lacks a required historical source")
        return max(records, key=lambda record: record["effective_at"])["value"]
    if operation == "current":
        return latest("event")
    if operation == "history":
        return latest("event", row["at"])
    if operation in ("semantic", "procedure"):
        return latest(operation)
    if operation == "change":
        return latest("event") - latest("event", row["since"])
    event, semantic, program = latest("event"), latest("semantic"), latest("procedure")
    if program["opcode"] == "identity":
        return event
    if program["opcode"] == "add_bias":
        return event + program["bias"]
    multiplied = event * semantic["factor"]
    if program["opcode"] == "multiply":
        return multiplied
    affine = multiplied + program["bias"]
    return max(-program["limit"], min(program["limit"], affine)) if program["opcode"] == "clamp" else affine


def load_suite(path, expected_split, forbidden_texts=(), forbidden_families=(), forbidden_text_digests=()):
    path = Path(path).absolute()
    if any(value.is_symlink() for value in (path, *path.parents)) or not path.is_file() or path.stat().st_size > 8_000_000:
        raise ValueError("invalid bounded evaluation input")
    raw = path.read_bytes()
    suite = json.loads(raw, object_pairs_hook=unique_object,
                       parse_constant=lambda value: (_ for _ in ()).throw(ValueError("nonfinite evaluation number")))
    if not isinstance(suite, dict) or set(suite) != {"schema", "split", "entities", "rows"} or suite["schema"] != SCHEMA:
        raise ValueError("invalid evaluation schema")
    if expected_split not in ("calibration", "held") or suite["split"] != expected_split:
        raise ValueError("evaluation split differs from the requested stage")
    if not isinstance(suite["entities"], list) or not 1 <= len(suite["entities"]) <= 32:
        raise ValueError("bounded nonempty native entity inventory required")
    identities, record_count = set(), 0
    now = int(datetime.now(timezone.utc).timestamp())
    for item in suite["entities"]:
        if not isinstance(item, dict) or set(item) != {"entity", "aliases", "records"}:
            raise ValueError("invalid evaluation entity fields")
        if not identifier(item["entity"]) or item["entity"] in identities:
            raise ValueError("invalid or duplicate evaluation entity")
        identities.add(item["entity"])
        if not isinstance(item["records"], list) or not 4 <= len(item["records"]) <= 32:
            raise ValueError("each entity requires bounded historical and current records")
        seen, kinds = set(), []
        for record in item["records"]:
            if not isinstance(record, dict) or set(record) != {"kind", "effective_at", "value"}:
                raise ValueError("invalid native source record")
            if not bounded_integer(record["effective_at"], 0, min(now, MAX_TIME)):
                raise ValueError("record timestamp is not a current-or-past Unix second")
            key = (record["kind"], record["effective_at"])
            if key in seen:
                raise ValueError("two initial writes occupy the same record address")
            seen.add(key)
            kinds.append(record["kind"])
            validate_value(record["kind"], record["value"])
        if kinds.count("event") < 2 or "semantic" not in kinds or "procedure" not in kinds:
            raise ValueError("three cell kinds and a historical event are required")
        record_count += len(item["records"])
    if record_count > 480:
        raise ValueError("fixture leaves insufficient room in the bounded owner snapshot")
    registry = registry_for(suite)
    rows = suite["rows"]
    if not isinstance(rows, list) or not 120 <= len(rows) <= 4096:
        raise ValueError("evaluation needs 120..4096 native-compatible rows")
    seen_ids, seen_texts, families, classifier, language_labels = set(), set(), set(), [], {}
    text_digests, normalization_rejections, rejection_counts = set(), [], {}
    forbidden_texts, forbidden_families = set(forbidden_texts), set(forbidden_families)
    forbidden_text_digests = set(forbidden_text_digests)
    for row in rows:
        if not isinstance(row, dict) or set(row) != {"id", "family", "language", "entity", "text", "at", "since", "expected_operation", "category"}:
            raise ValueError("invalid evaluation row fields")
        if not identifier(row["id"]) or row["id"] in seen_ids or not identifier(row["family"]) or not identifier(row["entity"]):
            raise ValueError("invalid or duplicate evaluation identifiers")
        seen_ids.add(row["id"])
        if row["family"] in forbidden_families:
            raise ValueError("evaluation family overlaps a prior fitting split")
        families.add(row["family"])
        if row["language"] not in ("en", "zh") or row["category"] not in CATEGORIES:
            raise ValueError("unsupported language or evaluation category")
        operation = row["expected_operation"]
        if (row["category"] == "known") != (operation in OPERATIONS) or operation is not None and operation not in OPERATIONS:
            raise ValueError("positive and negative labels disagree")
        if not bounded_integer(row["at"], 0, MAX_TIME) or not bounded_integer(row["since"], 0, row["at"]):
            raise ValueError("query timestamps violate the native contract")
        if not isinstance(row["text"], str) or not 1 <= len(row["text"].encode()) <= 8192 or any(ord(c) < 32 for c in row["text"]):
            raise ValueError("unbounded or malformed native query text")
        try:
            address = resolved_text(row, registry)
        except AddressError as error:
            if row["category"] not in ("unsupported", "unknown_entity", "ambiguous_alias"):
                raise
            address = None
            reason = str(error)
            normalization_rejections.append({"id": row["id"], "category": row["category"], "reason": reason})
            category_counts = rejection_counts.setdefault(row["category"], {})
            category_counts[reason] = category_counts.get(reason, 0) + 1
        if address is None:
            normalized = normalize(row["text"])
        else:
            if address.request["entity"] != row["entity"]:
                raise ValueError("native request slot must contain its canonical entity")
            normalized = address.normalized_text
            if row["category"] in ("unknown_entity", "ambiguous_alias"):
                raise ValueError("negative entity category unexpectedly resolves")
        key = (normalized, row["entity"], row["at"], row["since"], row["category"])
        text_digest = digest(normalized)
        if key in seen_texts or normalized in forbidden_texts or text_digest in forbidden_text_digests:
            raise ValueError("evaluation text duplicates itself or a prior fitting split")
        seen_texts.add(key)
        text_digests.add(text_digest)
        if address is not None and row["category"] in ("known", "unsupported"):
            if row["category"] == "known":
                if address.dates:
                    cutoff = row["since"] if operation == "change" else row["at"] if operation == "history" else None
                    expected = datetime.strptime(str(address.dates[0]), "%Y%m%d").replace(tzinfo=timezone.utc).timestamp()
                    if cutoff != expected:
                        raise ValueError("known query conflicts with the native UTC-midnight profile")
                expected_value(suite, row)
            label = operation or "reject"
            if normalized in language_labels and language_labels[normalized] != label:
                raise ValueError("the same normalized language has conflicting intent labels")
            if normalized not in language_labels:
                classifier.append({"id": row["id"], "family": row["family"], "language": row["language"],
                                   "text": normalized, "operation": label})
                language_labels[normalized] = label
    if set(row["operation"] for row in classifier) != {*OPERATIONS, "reject"}:
        raise ValueError("all six operations and near-domain unsupported rows are required")
    return suite, classifier, {"input_sha256": hashlib.sha256(raw).hexdigest(), "canonical_sha256": digest(suite),
                               "rows": len(rows), "classifier_rows": len(classifier), "families": sorted(families),
                               "record_count": record_count, "entity_count": len(identities),
                               "normalization_rejected_rows": len(normalization_rejections),
                               "normalization_rejections": normalization_rejections,
                               "normalization_rejection_counts": rejection_counts,
                               "all_native_normalized_text_sha256": sorted(text_digests),
                               "classifier_unit": "distinct successfully normalized known/unsupported wording; parser rejections and entity repetitions are native read cases only",
                               "population_risk_established": False, "native_rows_executed": 0}


def native_fixture(suite):
    records = [{"schema": "hepta.memory.cell-record.v1", "entity": item["entity"], **record}
               for item in suite["entities"] for record in item["records"]]
    return {"schema": "hepta.memory.v9.native-language-fixture.v1", "suite_digest": digest(suite),
            "split": suite["split"], "records": records,
            "aliases": {item["entity"]: item["aliases"] for item in suite["entities"]},
            "requests": [{"id": row["id"], "family": row["family"], "language": row["language"],
                          "category": row["category"], "entity": row["entity"], "text": row["text"],
                          "at": row["at"], "since": row["since"], "max_hops": 8, "max_cells": 8,
                          "expected_operation": row["expected_operation"], "expected_value": expected_value(suite, row)}
                         for row in suite["rows"]],
            "scope_source": "actual native owner's memory snapshot; never this fixture",
            "native_execution_claim": False}
