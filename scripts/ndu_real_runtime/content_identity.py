"""Bind selected text to the actual actor wire, delivery bytes and scorer input.

These are consistency receipts, not owner attestations or semantic correctness
labels. Old records without a selection witness retain an unknown selected-used
label. Hidden references are never inputs to this module or the actor.
"""

import hashlib

from ndu_real_materials.common import strict_json
from .metering import canonical_sha

SELECTION_SCHEMA = "ndu.real.content-selection.v1"


def selection_receipt(candidates, selected_index, action):
    if (
        action.get("action") != "WRITE_TEXT"
        or not isinstance(candidates, list)
        or not 1 <= len(candidates) <= 128
        or type(selected_index) is not int
        or not 0 <= selected_index < len(candidates)
    ):
        raise ValueError("Invalid bounded content selection")
    candidate_ids = [canonical_sha(candidate) for candidate in candidates]
    receipt = {
        "schema": SELECTION_SCHEMA,
        "candidate_sha256s": candidate_ids,
        "candidate_set_sha256": canonical_sha(candidate_ids),
        "selected_index": selected_index,
        "selected_candidate": candidates[selected_index],
        "selected_candidate_sha256": candidate_ids[selected_index],
        "selected_text_sha256": canonical_sha(candidates[selected_index]["text"]),
        "action_sha256": canonical_sha(action),
    }
    check_selection({"action": action, "content_selection": receipt}, required=True)
    return receipt


def check_selection(observation, *, required=False):
    action = observation["action"]
    if action["action"] != "WRITE_TEXT":
        return None
    if (
        set(action) != {"schema", "action", "arguments"}
        or action["schema"] != "ndu.real.actor-action.v1"
        or not isinstance(action["arguments"], dict)
        or set(action["arguments"]) != {"text"}
    ):
        raise ValueError("Invalid selected text action")
    receipt = observation.get("content_selection")
    if receipt is None:
        if required:
            raise ValueError("Actor omitted its declared content selection witness")
        return None
    if not isinstance(receipt, dict) or set(receipt) != {
        "schema",
        "candidate_sha256s",
        "candidate_set_sha256",
        "selected_index",
        "selected_candidate",
        "selected_candidate_sha256",
        "selected_text_sha256",
        "action_sha256",
    }:
        raise ValueError("Invalid content selection witness fields")
    ids, index = receipt["candidate_sha256s"], receipt["selected_index"]
    selected = receipt["selected_candidate"]
    if (
        receipt["schema"] != SELECTION_SCHEMA
        or not isinstance(ids, list)
        or not 1 <= len(ids) <= 128
        or any(
            not isinstance(value, str)
            or len(value) != 64
            or any(char not in "0123456789abcdef" for char in value)
            for value in ids
        )
        or type(index) is not int
        or not 0 <= index < len(ids)
        or not isinstance(selected, dict)
        or set(selected) != {"text", "bbox", "origin"}
        or not isinstance(selected["text"], str)
        or len(selected["text"].encode()) > 8192
        or selected["origin"]
        not in ("pixel_ocr", "registered_public_text", "no_recognized_text")
        or not isinstance(selected["bbox"], list)
        or len(selected["bbox"]) != 4
        or any(
            type(value) is not int or not 0 <= value <= 16_000_000
            for value in selected["bbox"]
        )
    ):
        raise ValueError("Invalid bounded selected candidate")
    if (
        receipt["candidate_set_sha256"] != canonical_sha(ids)
        or receipt["selected_candidate_sha256"] != ids[index]
        or canonical_sha(selected) != ids[index]
        or receipt["selected_text_sha256"] != canonical_sha(selected["text"])
        or receipt["action_sha256"] != canonical_sha(action)
        or selected["text"] != action["arguments"].get("text")
    ):
        raise ValueError("Selected candidate differs from the action payload")
    if "candidate_metadata" in observation and ids != [
        canonical_sha(candidate) for candidate in observation["candidate_metadata"]
    ]:
        raise ValueError("Selection witness differs from the observed candidate set")
    return receipt


def verify_evaluation(
    evaluation, delivery_raw, *, case_id, evaluator_sha256, rubric_sha256
):
    if (
        evaluation.get("schema") != "ndu.real.independent-evaluation.v1"
        or evaluation.get("case_id") != case_id
        or evaluation.get("evaluator_source_sha256") != evaluator_sha256
        or evaluation.get("rubric_sha256") != rubric_sha256
        or evaluation.get("delivery_sha256") != hashlib.sha256(delivery_raw).hexdigest()
    ):
        raise ValueError("External evaluation differs from the actual delivery binding")


def verify_content_identity(
    observation,
    delivery_raw,
    evaluation,
    *,
    expected_evaluator_sha256,
    expected_rubric_sha256,
    actor_payload_raw=None,
    expected_payload_sha256=None,
    require_selection=False,
):
    if (
        observation.get("schema") != "ndu.real.actor-observation.v1"
        or not isinstance(observation.get("case_id"), str)
        or type(observation.get("step")) is not int
        or observation["step"] < 0
    ):
        raise ValueError("Invalid content observation identity")
    selection = check_selection(observation, required=require_selection)
    action = observation["action"]
    if action["action"] != "WRITE_TEXT":
        raise ValueError("Text identity receipt requires a WRITE_TEXT action")
    delivery = strict_json(delivery_raw)
    if (
        delivery.get("schema") != "ndu.real.delivery.v1"
        or delivery.get("case_id") != observation["case_id"]
        or delivery.get("text") != action["arguments"]["text"]
    ):
        raise ValueError("Persisted delivery differs from the action payload")
    payload_sha = None
    if actor_payload_raw is not None:
        payload_sha = hashlib.sha256(actor_payload_raw).hexdigest()
        supplied = strict_json(actor_payload_raw)
        original = {
            key: value
            for key, value in observation.items()
            if key != "observed_action_seconds"
        }
        if payload_sha != expected_payload_sha256 or supplied != original:
            raise ValueError("Actor wire differs from the observed action")
    if evaluation is not None:
        verify_evaluation(
            evaluation,
            delivery_raw,
            case_id=observation["case_id"],
            evaluator_sha256=expected_evaluator_sha256,
            rubric_sha256=expected_rubric_sha256,
        )
    status = (
        "legacy_selection_missing"
        if selection is None
        else "actor_payload_missing"
        if payload_sha is None
        else "unscored_delivery"
        if evaluation is None
        else "complete"
    )
    return {
        "schema": "ndu.real.content-identity.v1",
        "case_id": observation["case_id"],
        "step": observation["step"],
        "status": status,
        "selected_used": True if status == "complete" else None,
        "payload_delivered": True,
        "effect_occurred": None,
        "candidate_set_sha256": None
        if selection is None
        else selection["candidate_set_sha256"],
        "selected_index": None if selection is None else selection["selected_index"],
        "selected_candidate_sha256": None
        if selection is None
        else selection["selected_candidate_sha256"],
        "selected_text_sha256": None
        if selection is None
        else selection["selected_text_sha256"],
        "action_sha256": canonical_sha(action),
        "actor_payload_sha256": payload_sha,
        "delivery_sha256": hashlib.sha256(delivery_raw).hexdigest(),
        "delivered_text_sha256": canonical_sha(delivery["text"]),
        "evaluator_source_sha256": None
        if evaluation is None
        else evaluation["evaluator_source_sha256"],
        "evaluator_delivery_sha256": None
        if evaluation is None
        else evaluation["delivery_sha256"],
        "rubric_sha256": None if evaluation is None else evaluation["rubric_sha256"],
    }


def content_identity_report(
    steps, snapshots, scores, launch, *, evaluator_sha256, rubric_sha256
):
    # Complete wire/score consistency cannot certify an aborted or unisolated
    # actor. Incomplete historical attempts are inspected by content_audit,
    # where selected_used remains unknown rather than being promoted.
    if (
        type(launch.get("exit_code")) is not int
        or launch["exit_code"] != 0
        or launch.get("enforced_before_actor_exec") is not True
        or launch.get("callback_error") is not None
        or launch.get("protocol_error") is not None
        or launch.get("limit_reason") is not None
    ):
        raise ValueError("Content identity requires a completed isolated actor")
    lines = [line.encode() for line in launch["stdout"].split("\n") if line.strip()]
    exchanges = launch["host_exchanges"]
    if len(lines) != len(exchanges):
        raise ValueError("Actor wire/exchange count differs")
    wires, require_selection = {}, False
    for raw, exchange in zip(lines, exchanges):
        if hashlib.sha256(raw).hexdigest() != exchange["event_sha256"]:
            raise ValueError("Actor wire digest differs from its host exchange")
        value = strict_json(raw)
        if value.get("schema") == "ndu.real.actor-ready.v1":
            require_selection = (
                value.get("content_identity_profile") == SELECTION_SCHEMA
            )
        elif value.get("schema") == "ndu.real.actor-observation.v1":
            key = (value["case_id"], value["step"])
            if key in wires:
                raise ValueError("Duplicate actor content step")
            wires[key] = (raw, exchange["event_sha256"])
    # score() evaluates either EVERY snapshot (training) or ONLY the final
    # snapshot (inference). A shared delivery digest is not a snapshot ID:
    # identical repeat writes must never borrow a later evaluation, nor may
    # a conflicting earlier scorer receipt be overwritten by a later one.
    if len(snapshots) != len(steps) + 1:
        raise ValueError("Content snapshot count differs from actor steps")
    if len(scores) == len(snapshots):
        scored_snapshots = scores
    elif len(scores) == 1:
        scored_snapshots = [None] * (len(snapshots) - 1) + list(scores)
    elif len(scores) == 0:
        scored_snapshots = [None] * len(snapshots)
    else:
        raise ValueError("Ambiguous evaluator snapshot coverage")
    receipts = []
    for index, step in enumerate(steps):
        if step["action"]["action"] != "WRITE_TEXT":
            continue
        raw = (snapshots[index + 1] / "delivery.json").read_bytes()
        wire, wire_sha = wires[(step["case_id"], step["step"])]
        receipts.append(
            verify_content_identity(
                step,
                raw,
                scored_snapshots[index + 1],
                expected_evaluator_sha256=evaluator_sha256,
                expected_rubric_sha256=rubric_sha256,
                actor_payload_raw=wire,
                expected_payload_sha256=wire_sha,
                require_selection=require_selection,
            )
        )
    return {
        "schema": "ndu.real.content-identity-report.v1",
        "receipts": receipts,
        "write_text_count": len(receipts),
        "complete_count": sum(row["status"] == "complete" for row in receipts),
        "native_owner_authentication": "SEPARATE_REQUIRED",
        "semantic_success_established": False,
    }
