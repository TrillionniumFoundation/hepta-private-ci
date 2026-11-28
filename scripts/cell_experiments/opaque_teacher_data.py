"""Unsigned completed-turn observations with explicit unknown teacher weights.

This profile supplies declarations and a local semantic check. It grants no
HumanTrain authority, execution receipt, signed outcome, or production eligibility.
The legacy data.py bytes and its verifier-source commitments remain unchanged.
"""

import copy
import hashlib
from pathlib import Path

from . import data

SCHEMA = "hepta.cell-experiments.opaque-teacher-observation.v1"
PROFILE = "hepta.teacher-observation-identity.v1"
SOURCE = "hepta.sdk-observed-turn-source.v1"
MAX_SOURCE_BYTES = 1_048_576
MAX_RECORD_BYTES = 32_768
FIELDS = frozenset(
    "schema record_id task_id lineage_id family_id project_id source_id teacher_id model_digest teacher_output_receipt_sha256 observed_at available_at split origin_kind exposure authorization source task final_answer trajectory teacher_observation production_eligible human_training_consent_proven".split()
)
PROFILE_FIELDS = frozenset(
    "schema identity_kind weights_sha256 generation_receipt_sha256 provider_reported model_reported source_sha256 thread_id session_id turn_id prompt_item_id prompt_item_sha256 answer_item_id answer_item_sha256 reported_phase student_policy_sha256 source_authentication selection_kind generation_authenticated execution_authenticated".split()
)
SOURCE_CLAIMS = {
    "raw_wire_preserved": False,
    "source_signed": False,
    "complete_original_trajectory_proven": False,
    "item_execution_verified": False,
    "human_training_consent_proven": False,
    "semantic_labels_verified": False,
    "evaluator_receipt_created": False,
    "training_record_created": False,
    "production_training_authorized": False,
}


def sha(value):
    data._hash(value, "observation commitment")
    data._require(value != "0" * 64, "nonzero observation commitment required")
    return value


def _object(value, name):
    data._require(isinstance(value, dict), "object required: " + name)
    return value


def _integer_json(value, depth=0):
    data._require(depth <= 32, "observation JSON nesting exceeds profile")
    if isinstance(value, dict):
        data._require(
            all(isinstance(key, str) for key in value), "JSON object keys must be text"
        )
        for child in value.values():
            _integer_json(child, depth + 1)
    elif isinstance(value, list):
        for child in value:
            _integer_json(child, depth + 1)
    else:
        data._require(
            value is None
            or type(value) in (str, bool)
            or type(value) is int
            and -(2**63) <= value < 2**64,
            "opaque record requires integer-only canonical JSON",
        )


def validate_record(record, *, require_outcome=True):
    data._require(
        isinstance(record, dict) and record.get("schema") == SCHEMA,
        "opaque observation schema mismatch",
    )
    data._require(
        set(record)
        == FIELDS | ({"verified_outcome"} if "verified_outcome" in record else set()),
        "unexpected opaque record fields",
    )
    _integer_json(record)
    data._require(
        len(data.canonical(record)) <= MAX_RECORD_BYTES, "opaque record too large"
    )
    for name in (
        "record_id",
        "task_id",
        "lineage_id",
        "family_id",
        "project_id",
        "source_id",
        "teacher_id",
    ):
        data._text(record.get(name), name, 512)
    data._require(
        record.get("split") == "train"
        and record.get("origin_kind") == "authorized_agent_run",
        "opaque profile is an explicitly declared A training source",
    )
    data._require(
        record.get("exposure") in ("development", "previously_exposed", "unexposed"),
        "unknown exposure",
    )
    for name in ("observed_at", "available_at"):
        data._integer(record.get(name), name)
    data._require(
        record["observed_at"] <= record["available_at"],
        "availability precedes observation",
    )
    authorization = _object(record.get("authorization"), "authorization")
    data._require(
        type(authorization.get("training_allowed")) is bool
        and authorization.get("evaluation_allowed") is True,
        "explicit authorization declarations required",
    )
    for name in ("rights_basis", "scope"):
        data._text(authorization.get(name), "authorization." + name, 4096)
    source = _object(record.get("source"), "source")
    for name in ("repository", "path"):
        data._text(source.get(name), "source." + name, 4096)
    source_sha = sha(source.get("sha256"))
    task = _object(record.get("task"), "task")
    data._text(task.get("input"), "task.input", 8192)
    verifier = _object(task.get("verifier"), "verifier")
    data._require(
        verifier.get("name") == "json_artifact"
        and verifier.get("version") == "1"
        and isinstance(verifier.get("parameters"), dict),
        "unsupported observation verifier",
    )
    data._text(record.get("final_answer"), "observed correction text", 8192)
    data._require(
        "model_digest" in record
        and record["model_digest"] is None
        and "teacher_output_receipt_sha256" in record
        and record["teacher_output_receipt_sha256"] is None,
        "opaque teacher weights and generation receipt must remain unknown",
    )
    data._require(
        record.get("production_eligible") is False
        and record.get("human_training_consent_proven") is False,
        "observation declarations cannot grant authority",
    )
    data._require(
        not {"features", "target", "n_classes"}.intersection(record),
        "observations cannot invent native targets",
    )
    profile = _object(record.get("teacher_observation"), "teacher_observation")
    data._require(
        set(profile) == PROFILE_FIELDS, "unexpected observation identity fields"
    )
    data._require(
        profile.get("schema") == PROFILE
        and profile.get("identity_kind") == "opaque"
        and profile.get("source_authentication") == "local_unsigned_typed_projection"
        and profile.get("selection_kind") == "explicit_correction_candidate",
        "unsupported teacher observation identity",
    )
    data._require(
        profile.get("weights_sha256", "missing") is None
        and profile.get("generation_receipt_sha256", "missing") is None
        and profile.get("model_reported", "missing") is None,
        "unknown weights cannot be replaced by provider or model hashes",
    )
    data._require(
        profile.get("generation_authenticated") is False
        and profile.get("execution_authenticated") is False,
        "unsigned observation is not teacher execution",
    )
    data._require(
        profile.get("source_sha256") == source_sha, "observation source differs"
    )
    for name in (
        "thread_id",
        "session_id",
        "turn_id",
        "prompt_item_id",
        "answer_item_id",
    ):
        data._text(profile.get(name), name, 256)
    for name in ("prompt_item_sha256", "answer_item_sha256", "student_policy_sha256"):
        sha(profile.get(name))
    data._require(
        profile["prompt_item_id"] != profile["answer_item_id"],
        "prompt and answer identity overlap",
    )
    provider = profile.get("provider_reported")
    if provider is not None:
        data._text(provider, "reported provider", 512)
    data._require(
        profile.get("reported_phase") in (None, "commentary", "final_answer"),
        "unsupported reported phase",
    )
    expected = [
        {
            "index": 0,
            "actor": "teacher",
            "kind": "observation",
            "content": record["final_answer"],
            "executed": False,
            "trainable": False,
            "receipt_sha256": None,
            "source_item_id": profile["answer_item_id"],
            "source_item_sha256": profile["answer_item_sha256"],
        }
    ]
    data._require(
        record.get("trajectory") == expected,
        "teacher observation must remain unexecuted and masked",
    )
    if require_outcome:
        outcome = _object(record.get("verified_outcome"), "verified_outcome")
        data._require(
            type(outcome.get("success")) is bool, "explicit local outcome required"
        )
        sha(outcome.get("receipt_sha256"))
        data._require(
            (outcome.get("verifier_name"), outcome.get("verifier_version"))
            == ("json_artifact", "1"),
            "observation verifier differs",
        )
    return record


def from_capture(draft, raw, *, prompt_item_id, answer_item_id, student_policy_sha256):
    """Bind explicit text-item selection to retained capture bytes; never infer consent."""
    data._require(
        type(raw) is bytes and 0 < len(raw) <= MAX_SOURCE_BYTES,
        "bounded capture bytes required",
    )
    record = copy.deepcopy(_object(draft, "draft"))
    data._require(
        record.get("schema") == SCHEMA
        and "verified_outcome" not in record
        and "teacher_observation" not in record
        and "final_answer" not in record
        and not record.get("trajectory"),
        "fresh opaque observation draft required",
    )
    source_sha = hashlib.sha256(raw).hexdigest()
    data._require(
        record.get("source", {}).get("sha256") == source_sha,
        "original capture bytes differ",
    )
    source = _object(data._parse(raw), "capture")
    data._require(
        data.canonical(source) == raw,
        "capture serialization differs from the retained producer profile",
    )
    _object(source.get("turn"), "captured turn")
    _object(source.get("thread"), "captured thread")
    data._require(
        source.get("read_method") == "AsyncThread.read(include_turns=True)",
        "unsupported capture method",
    )
    data._text(source.get("sdk_version"), "reported SDK version", 128)
    data._require(
        source.get("schema") == SOURCE
        and source.get("claims") == SOURCE_CLAIMS
        and all(type(value) is bool for value in source["claims"].values())
        and source.get("teacher_opaque_id", "missing") is None
        and source.get("teacher_model_sha256", "missing") is None,
        "unsigned SDK observation source required",
    )
    data._require(
        source.get("serialization")
        == "pydantic-json-aliases-exclude-unset/utf8-sorted-compact-v1"
        and source.get("items_view_explicit") is True
        and source.get("turn", {}).get("itemsView") == "full"
        and source["turn"].get("status") == "completed",
        "explicit completed full turn required",
    )
    items, omitted = source.get("items"), source.get("omitted_items")
    data._require(
        isinstance(items, list)
        and isinstance(omitted, list)
        and type(source.get("returned_item_count")) is int
        and len(items) + len(omitted) == source.get("returned_item_count")
        and 0 < len(items) + len(omitted) <= 256,
        "bounded captured inventory required",
    )
    all_items = items + omitted
    data._require(
        all(isinstance(item, dict) for item in all_items), "invalid item identity"
    )
    ids = [item.get("item_id") for item in all_items]
    data._require(
        all(isinstance(value, str) for value in ids)
        and len(set(ids)) == len(ids)
        and all(type(item.get("source_index")) is int for item in all_items)
        and sorted(item.get("source_index", -1) for item in all_items)
        == list(range(len(all_items))),
        "ambiguous captured item identities",
    )
    selected = {item["item_id"]: item for item in items}
    prompt, answer = selected.get(prompt_item_id, {}), selected.get(answer_item_id, {})
    data._require(
        prompt.get("type") == "userMessage"
        and answer.get("type") == "agentMessage"
        and prompt["source_index"] < answer["source_index"],
        "explicit ordered user and agent items required",
    )
    user = _object(prompt.get("sdk_payload"), "captured user payload")
    teacher = _object(answer.get("sdk_payload"), "captured agent payload")
    data._require(
        user.get("type") == "userMessage"
        and user.get("id") == prompt_item_id
        and teacher.get("type") == "agentMessage"
        and teacher.get("id") == answer_item_id,
        "captured payload identity differs",
    )
    content = user.get("content")
    data._require(
        isinstance(content, list)
        and len(content) == 1
        and isinstance(content[0], dict)
        and content[0].get("type") == "text"
        and content[0].get("text") == record.get("task", {}).get("input"),
        "profile requires the exact single text prompt",
    )
    data._text(teacher.get("text"), "selected teacher text", 8192)
    record["final_answer"] = teacher["text"]
    profile = {
        "schema": PROFILE,
        "identity_kind": "opaque",
        "weights_sha256": None,
        "generation_receipt_sha256": None,
        "provider_reported": source.get("thread", {}).get("modelProvider"),
        "model_reported": None,
        "source_sha256": source_sha,
        "thread_id": source.get("thread", {}).get("id"),
        "session_id": source.get("thread", {}).get("sessionId"),
        "turn_id": source["turn"].get("id"),
        "prompt_item_id": prompt_item_id,
        "prompt_item_sha256": data.digest(user),
        "answer_item_id": answer_item_id,
        "answer_item_sha256": data.digest(teacher),
        "reported_phase": teacher.get("phase"),
        "student_policy_sha256": sha(student_policy_sha256),
        "source_authentication": "local_unsigned_typed_projection",
        "selection_kind": "explicit_correction_candidate",
        "generation_authenticated": False,
        "execution_authenticated": False,
    }
    record["teacher_observation"] = profile
    record["trajectory"] = [
        {
            "index": 0,
            "actor": "teacher",
            "kind": "observation",
            "content": teacher["text"],
            "executed": False,
            "trainable": False,
            "receipt_sha256": None,
            "source_item_id": answer_item_id,
            "source_item_sha256": profile["answer_item_sha256"],
        }
    ]
    return validate_record(record, require_outcome=False)


def verify_source(record, raw):
    """Rebuild the observation projection from original bytes; authenticate no actor."""
    validate_record(record, require_outcome=False)
    profile = record["teacher_observation"]
    draft = {
        key: copy.deepcopy(value)
        for key, value in record.items()
        if key
        not in {"teacher_observation", "trajectory", "final_answer", "verified_outcome"}
    }
    expected = from_capture(
        draft,
        raw,
        prompt_item_id=profile["prompt_item_id"],
        answer_item_id=profile["answer_item_id"],
        student_policy_sha256=profile["student_policy_sha256"],
    )
    observed = {
        key: value for key, value in record.items() if key != "verified_outcome"
    }
    data._require(
        data.canonical(expected) == data.canonical(observed),
        "record differs from captured observation",
    )


def verify_answer(record):
    """Run the existing trusted semantic callback; this is never an Evaluator signature."""
    validate_record(record, require_outcome=False)
    spec = record["task"]["verifier"]
    key = (spec["name"], spec["version"])
    data._require(key in data._VERIFIERS, "unregistered semantic verifier")
    callback, implementation = data._VERIFIERS[key]
    result = callback(copy.deepcopy(spec["parameters"]), record["final_answer"])
    data._require(
        isinstance(result, dict) and type(result.get("success")) is bool,
        "invalid semantic result",
    )
    receipt = {
        "schema": "hepta.cell-experiments.opaque-observation-semantic-receipt.v1",
        "record_id": record["record_id"],
        "input_sha256": hashlib.sha256(record["task"]["input"].encode()).hexdigest(),
        "answer_sha256": hashlib.sha256(record["final_answer"].encode()).hexdigest(),
        "source_sha256": record["source"]["sha256"],
        "teacher_observation_sha256": data.digest(record["teacher_observation"]),
        "verifier": key,
        "verifier_source_sha256": implementation,
        "observation_verifier_source_sha256": hashlib.sha256(
            Path(__file__).read_bytes()
        ).hexdigest(),
        "parameters_sha256": data.digest(spec["parameters"]),
        "result": result,
        "student_execution_claimed": False,
        "teacher_execution_claimed": False,
        "evaluator_signature_created": False,
        "production_eligible": False,
    }
    return {
        **receipt,
        "receipt_sha256": data.digest(receipt),
        "success": result["success"],
    }
