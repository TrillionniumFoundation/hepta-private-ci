"""Digest-only observations of text selection and post-actor delivery continuity.

These receipts establish byte continuity within the research host, not owner
authentication, semantic quality, or a proof that the model computed its logits.
"""

import hashlib
import json


def digest(value):
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


def text_digest(text):
    if not isinstance(text, str):
        raise ValueError("Text identity requires an actual string")
    return hashlib.sha256(text.encode()).hexdigest()


def selection_receipt(candidates, index, action):
    if action["action"] != "WRITE_TEXT":
        return None
    if type(index) is not int or not 0 <= index < len(candidates):
        raise ValueError("Selected candidate index is outside the candidate set")
    selected = candidates[index]
    return {
        "schema": "ndu.real.content-selection.v1",
        "candidate_count": len(candidates),
        "candidate_set_sha256": digest(candidates),
        "selected_index": index,
        "selected_candidate_sha256": digest(selected),
        "selected_text_sha256": text_digest(selected["text"]),
        "serialized_text_sha256": text_digest(action["arguments"]["text"]),
        "action_sha256": digest(action),
    }


def validate_selection(step):
    """Check a new receipt without requiring one in historical actor records."""
    receipt = step.get("content_selection")
    if receipt is None:
        return "UNOBSERVED"
    action = step["action"]
    index, count = receipt["selected_index"], receipt["candidate_count"]
    if (
        action["action"] != "WRITE_TEXT"
        or receipt["schema"] != "ndu.real.content-selection.v1"
        or type(count) is not int
        or type(index) is not int
        or not 0 <= index < count
        or receipt["action_sha256"] != digest(action)
        or receipt["serialized_text_sha256"] != text_digest(action["arguments"]["text"])
        or receipt["selected_text_sha256"] != receipt["serialized_text_sha256"]
    ):
        raise ValueError("Selected candidate and serialized action identity differ")
    candidates = step.get("candidate_metadata")
    if candidates is not None:
        if receipt != selection_receipt(candidates, index, action):
            raise ValueError("Selection receipt differs from recorded candidate set")
        return "RECORDED_CANDIDATE_VERIFIED"
    return "ACTOR_DECLARED_CANDIDATE"


def observe_delivery(step, delivered_raw, evaluation):
    """Observe downstream bytes after actor exit; never return labels to actor."""
    delivery = json.loads(delivered_raw)
    if step["action"]["action"] != "WRITE_TEXT":
        raise ValueError("Text continuity observation requires WRITE_TEXT")
    if (
        delivery["case_id"] != step["case_id"]
        or evaluation["case_id"] != step["case_id"]
    ):
        raise ValueError("Evaluator, actor and delivery case identities differ")
    selection = validate_selection(step)
    serialized_sha = text_digest(step["action"]["arguments"]["text"])
    delivered_sha = None if delivery["text"] is None else text_digest(delivery["text"])
    delivery_sha = hashlib.sha256(delivered_raw).hexdigest()
    delivery_matches = serialized_sha == delivered_sha
    evaluator_matches = evaluation["delivery_sha256"] == delivery_sha
    return {
        "schema": "ndu.real.content-continuity.v1",
        "case_id": step["case_id"],
        "step": step["step"],
        "selection_provenance": selection,
        "selection_receipt_sha256": digest(step.get("content_selection")),
        "serialized_text_sha256": serialized_sha,
        "delivered_text_sha256": delivered_sha,
        "delivery_sha256": delivery_sha,
        "evaluation_sha256": digest(evaluation),
        "serialized_to_delivered": delivery_matches,
        "delivered_to_evaluator": evaluator_matches,
        "selected_to_evaluator": None
        if selection != "RECORDED_CANDIDATE_VERIFIED"
        else delivery_matches and evaluator_matches,
        "declared_selection_to_evaluator": None
        if selection == "UNOBSERVED"
        else delivery_matches and evaluator_matches,
        "semantic_quality": evaluation["quality"],
        "native_owner_authentication": "SEPARATE_REQUIRED",
        "policy_evaluation_performed": False,
    }
