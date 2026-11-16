"""Versioned experiment data admission; declarations do not prove provenance."""

import copy
import hashlib
import inspect
import json
import math
from pathlib import Path
import re

SCHEMA = "hepta.cell-experiments.record.v1"
SPLITS = ("train", "selection", "confirmation")
MAX_RECORD_BYTES = 262144
MAX_RECORDS = 4096
_VERIFIERS = {}


def canonical(value):
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def record_digest(record):
    return digest(record)


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _text(value, name, maximum=65536):
    _require(
        isinstance(value, str) and 0 < len(value.encode("utf-8")) <= maximum,
        f"invalid {name}",
    )


def _hash(value, name):
    _require(
        isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value),
        f"invalid {name}",
    )


def _integer(value, name):
    _require(type(value) is int and value >= 0, f"invalid {name}")


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        _require(key not in result, f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _parse(raw):
    def reject(value):
        raise ValueError(f"nonfinite JSON number: {value}")

    return json.loads(raw, object_pairs_hook=_unique_object, parse_constant=reject)


def load_records(path, *, independent=False):
    """Read bounded JSONL; never rewrite source records or infer their authority."""
    records = []
    with Path(path).open("rb") as source:
        while raw := source.readline(MAX_RECORD_BYTES + 1):
            _require(len(raw) <= MAX_RECORD_BYTES, "record exceeds byte limit")
            _require(raw.strip(), "blank JSONL record")
            records.append(_parse(raw))
            _require(len(records) <= MAX_RECORDS, "too many records")
    validate_records(records, independent=independent)
    return records


def validate_record(record, *, require_outcome=True):
    _require(
        isinstance(record, dict) and record.get("schema") == SCHEMA, "schema mismatch"
    )
    _require(len(canonical(record)) <= MAX_RECORD_BYTES, "record exceeds byte limit")
    for name in (
        "record_id",
        "task_id",
        "lineage_id",
        "family_id",
        "project_id",
        "source_id",
    ):
        _text(record.get(name), name, 512)
    _require(record.get("split") in SPLITS, "unknown split")
    _require(
        record.get("origin_kind")
        in ("real_repository_history", "authorized_agent_run", "curated_development"),
        "unknown origin",
    )
    _require(
        record.get("exposure") in ("development", "previously_exposed", "unexposed"),
        "unknown exposure",
    )
    if record["origin_kind"] == "curated_development":
        _require(
            record["exposure"] == "development",
            "curated records retain development exposure",
        )
    for name in ("observed_at", "available_at"):
        _integer(record.get(name), name)
    _require(
        record["observed_at"] <= record["available_at"],
        "availability precedes observation",
    )
    auth = record.get("authorization", {})
    _require(
        type(auth.get("training_allowed")) is bool,
        "explicit training authorization required",
    )
    _require(
        auth.get("evaluation_allowed") is True, "evaluation authorization required"
    )
    for name in ("rights_basis", "scope"):
        _text(auth.get(name), "authorization." + name, 4096)
    source = record.get("source", {})
    for name in ("repository", "path"):
        _text(source.get(name), "source." + name, 4096)
    _hash(source.get("sha256"), "source.sha256")
    if record["origin_kind"] == "real_repository_history":
        _require(
            isinstance(source.get("revision"), str)
            and re.fullmatch(r"[0-9a-f]{40}", source["revision"]),
            "pinned Git revision required",
        )
    task = record.get("task", {})
    _text(task.get("input"), "task.input")
    verifier = task.get("verifier", {})
    for name in ("name", "version"):
        _text(verifier.get(name), "verifier." + name, 256)
    _require(
        isinstance(verifier.get("parameters"), dict), "verifier parameters required"
    )
    _text(record.get("final_answer"), "final_answer")
    teacher = record.get("teacher_id")
    if teacher is not None:
        _text(teacher, "teacher_id", 512)
        _hash(record.get("model_digest"), "teacher model_digest")
        _hash(
            record.get("teacher_output_receipt_sha256"), "teacher final output receipt"
        )
    events = record.get("trajectory")
    _require(
        isinstance(events, list) and len(events) <= 128, "bounded trajectory required"
    )
    for index, event in enumerate(events):
        _require(
            isinstance(event, dict) and event.get("index") == index,
            "trajectory order mismatch",
        )
        _require(
            event.get("actor") in ("teacher", "student", "environment", "curator"),
            "bad actor",
        )
        _require(
            event.get("kind") in ("observation", "action", "correction"),
            "bad event kind",
        )
        if not (
            event["actor"] == "student"
            and event["kind"] == "action"
            and event.get("content") == ""
        ):
            _text(event.get("content"), "trajectory content", 32768)
        _require(
            type(event.get("executed")) is bool, "explicit execution flag required"
        )
        if event["actor"] == "environment":
            _require(
                event["kind"] == "observation", "environment events are observations"
            )
        if event["actor"] == "curator":
            _require(
                record["origin_kind"] == "curated_development"
                and not event["executed"],
                "authored examples are development context, not execution",
            )
        if event["executed"]:
            _require(event["kind"] == "action", "only actions execute")
            _hash(event.get("receipt_sha256"), "executed action receipt")
        if event["actor"] == "teacher":
            _require(
                teacher is not None,
                "teacher identity missing; use curator for authored examples",
            )
            _hash(event.get("receipt_sha256"), "teacher output receipt")
        if event["actor"] == "student" and event["executed"]:
            _hash(event.get("policy_sha256"), "executing student policy")
            _require(
                event.get("receipt_actor") == "student",
                "teacher receipt is not student execution",
            )
    if require_outcome:
        outcome = record.get("verified_outcome", {})
        _require(
            type(outcome.get("success")) is bool, "explicit verified outcome required"
        )
        _hash(outcome.get("receipt_sha256"), "outcome receipt")
        _require(
            (outcome.get("verifier_name"), outcome.get("verifier_version"))
            == (verifier["name"], verifier["version"]),
            "outcome verifier mismatch",
        )
    features = record.get("features")
    if features is not None:
        values = features.get("values")
        _require(
            isinstance(values, list)
            and 0 < len(values) <= 4096
            and all(type(v) in (int, float) and math.isfinite(v) for v in values),
            "bad features",
        )
        _hash(features.get("binding"), "feature binding")
        for name in ("available_at", "preaction_at"):
            _integer(features.get(name), "features." + name)
        _require(
            features["available_at"] <= features["preaction_at"],
            "post-action feature leakage",
        )
    if "target" in record:
        _integer(record["target"], "target")
        _integer(record.get("n_classes"), "n_classes")
        _require(
            record["target"] < record["n_classes"], "target outside frozen class range"
        )
    return record


def validate_records(records, *, independent=False):
    """Check group/time separation; even passing cannot authenticate declarations."""
    _require(
        isinstance(records, list) and 0 < len(records) <= MAX_RECORDS,
        "bounded records required",
    )
    ids, groups, projects = set(), {}, {}
    by_split = {split: [] for split in SPLITS}
    for record in records:
        validate_record(record)
        _require(record["record_id"] not in ids, "duplicate record id")
        ids.add(record["record_id"])
        split = record["split"]
        by_split[split].append(record)
        keys = [
            (name, record[name])
            for name in ("task_id", "lineage_id", "family_id", "source_id")
        ]
        keys += [
            ("source_bytes", record["source"]["sha256"]),
            ("input", digest(record["task"]["input"])),
        ]
        for key in keys:
            _require(
                groups.setdefault(key, split) == split,
                f"cross-split duplicate group: {key[0]}",
            )
        projects.setdefault(record["project_id"], set()).add(split)
    project_overlap = sorted(key for key, value in projects.items() if len(value) > 1)
    temporal = all(
        max(r["available_at"] for r in by_split[a])
        < min(r["observed_at"] for r in by_split[b])
        for a, b in zip(SPLITS, SPLITS[1:])
        if by_split[a] and by_split[b]
    )
    if independent:
        _require(
            all(by_split.values()), "all three splits required for independence checks"
        )
        _require(
            not project_overlap and temporal, "project or time split is not independent"
        )
        for record in by_split["confirmation"]:
            _require(
                record["origin_kind"] != "curated_development"
                and record["exposure"] == "unexposed",
                "curated/exposed records cannot become independent confirmation",
            )
            custody = record.get("custody", {})
            _hash(custody.get("receipt_sha256"), "independent custody receipt")
            _integer(custody.get("frozen_at"), "custody.frozen_at")
            _require(
                custody["frozen_at"] < record["observed_at"]
                and custody.get("exposed_to_training") is False,
                "invalid freeze/exposure declaration",
            )
    return {
        "schema": "hepta.cell-experiments.admission.v1",
        "records": len(records),
        "record_digest": digest(records),
        "counts": {s: len(v) for s, v in by_split.items()},
        "project_overlap": project_overlap,
        "time_ordered": temporal,
        "declared_teacher_ids": sorted(
            {r["teacher_id"] for r in records if r.get("teacher_id")}
        ),
        "independent_declarations_checked": independent,
        "provenance_authenticated": False,
        "semantic_duplicate_detection_complete": False,
        "production_eligible": False,
    }


def assign_splits(records, *, train_before, selection_before, independent=False):
    """Time cutoffs are explicit Unix seconds; a crossing family is rejected."""
    _integer(train_before, "train_before")
    _integer(selection_before, "selection_before")
    _require(train_before < selection_before, "cutoffs out of order")
    result = copy.deepcopy(records)
    for record in result:
        available = record["available_at"]
        record["split"] = (
            "train"
            if available < train_before
            else "selection"
            if available < selection_before
            else "confirmation"
        )
    validate_records(result, independent=independent)
    return result


def build_sft_examples(records, mode="final_answer"):
    """Return untruncated segments; observations are context, never teacher actions."""
    _require(mode in ("final_answer", "trajectory"), "unknown SFT mode")
    validate_records(records)
    examples = []
    for record in records:
        _require(record["split"] == "train", "selection/confirmation cannot enter SFT")
        _require(record["authorization"]["training_allowed"], "training not authorized")
        _require(
            record["verified_outcome"]["success"],
            "failed example cannot become positive SFT",
        )
        segments = []
        if mode == "trajectory":
            _require(record["trajectory"], "complete trajectory missing")
            for event in record["trajectory"]:
                observation = event["kind"] == "observation"
                segments.append(
                    {
                        "role": "tool" if observation else "assistant",
                        "content": event["content"],
                        "train": not observation,
                        "actor": event["actor"],
                        "kind": event["kind"],
                    }
                )
        segments.append(
            {
                "role": "assistant",
                "content": record["final_answer"],
                "train": True,
                "actor": "answer",
                "kind": "final_answer",
            }
        )
        examples.append(
            {
                "record_id": record["record_id"],
                "input": record["task"]["input"],
                "target_text": "\n".join(s["content"] for s in segments),
                "segments": segments,
                "source_sha256": record["source"]["sha256"],
                "record_sha256": digest(record),
                "mode": mode,
            }
        )
    return examples


def register_verifier(name, version, callback):
    """Register trusted local semantic code, never a command supplied by a dataset."""
    key = (name, version)
    _require(key not in _VERIFIERS and callable(callback), "duplicate/invalid verifier")
    source_hash = hashlib.sha256(
        Path(inspect.getsourcefile(callback)).read_bytes()
    ).hexdigest()
    _VERIFIERS[key] = (callback, source_hash)


def verify_answer(record, answer):
    """Evaluate actual candidate bytes, binding exact input and verifier implementation."""
    validate_record(record, require_outcome=False)
    _require(
        isinstance(answer, str) and len(answer.encode("utf-8")) <= 65536,
        "candidate answer must be bounded text",
    )
    spec = record["task"]["verifier"]
    key = (spec["name"], spec["version"])
    _require(key in _VERIFIERS, "unregistered semantic verifier")
    callback, implementation = _VERIFIERS[key]
    result = callback(copy.deepcopy(spec["parameters"]), answer)
    _require(
        isinstance(result, dict) and type(result.get("success")) is bool,
        "invalid verifier result",
    )
    receipt = {
        "schema": "hepta.cell-experiments.semantic-receipt.v1",
        "record_id": record["record_id"],
        "input_sha256": hashlib.sha256(record["task"]["input"].encode()).hexdigest(),
        "answer_sha256": hashlib.sha256(answer.encode()).hexdigest(),
        "verifier": key,
        "verifier_source_sha256": implementation,
        "parameters_sha256": digest(spec["parameters"]),
        "result": result,
        "student_execution_claimed": False,
        "production_eligible": False,
    }
    return {**receipt, "receipt_sha256": digest(receipt), "success": result["success"]}


def _json_artifact(parameters, answer):
    """Semantic structure equality for real JSON-artifact tasks; no code execution."""
    _require(
        set(parameters) == {"expected"},
        "json_artifact requires exact expected structure",
    )
    try:
        parsed = _parse(answer)
        passed = canonical(parsed) == canonical(parameters["expected"])
    except (ValueError, TypeError):
        return {"success": False, "reason": "invalid_json"}
    return {
        "success": passed,
        "reason": "structure_equal" if passed else "structure_mismatch",
    }


register_verifier("json_artifact", "1", _json_artifact)
