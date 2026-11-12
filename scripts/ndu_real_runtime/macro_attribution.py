"""Posthoc READ witnesses; changed pixels or OCR text do not prove useful knowledge."""

import math

from ndu_real_materials import common, evaluator
from .content_identity import check_selection
from .metacontrol_macro_contract import digest, sha


def _box(value):
    return (
        isinstance(value, list)
        and len(value) == 4
        and all(type(v) is int and 0 <= v <= 16_000_000 for v in value)
        and value[0] < value[2]
        and value[1] < value[3]
    )


def public_observation(root, pin, launch, case_id, index, action):
    """Read exact pre-action host bytes and the decodable observation they name."""
    raw = common.read_bound(root, pin, limit=131072)
    exchange = launch["host_exchanges"][index]
    if sha(raw) != exchange.get("reply_sha256") or len(raw) != exchange.get(
        "reply_bytes"
    ):
        raise ValueError("Retained public input differs from original host reply")
    public = common.strict_json(raw)
    if (
        set(public)
        != {
            "schema",
            "case_id",
            "step",
            "remaining_seconds",
            "prepared_roi",
            "observation",
            "delivery",
            "text_committed",
            "forced_action",
        }
        or public["schema"] != "ndu.real.actor-step.v1"
        or public["case_id"] != case_id
        or type(public["step"]) is not int
        or public["step"] != index
        or public["forced_action"] not in (None, action)
        or type(public["text_committed"]) is not bool
        or type(public["remaining_seconds"]) not in (int, float)
        or not math.isfinite(public["remaining_seconds"])
        or public["remaining_seconds"] < 0
        or public["prepared_roi"] is not None
        and not _box(public["prepared_roi"])
    ):
        raise ValueError("Public input differs from action state or leaks fields")
    packet, delivery = public["observation"], public["delivery"]
    if (
        not isinstance(packet, dict)
        or set(packet) != {"path", "sha256", "bbox", "kind"}
        or packet["kind"] not in ("overview", "roi")
        or not _box(packet["bbox"])
        or not isinstance(delivery, dict)
        or set(delivery) != {"schema", "case_id", "text", "image"}
        or delivery["schema"] != "ndu.real.delivery.v1"
        or delivery["case_id"] != case_id
        or delivery["text"] is not None
        and (
            not isinstance(delivery["text"], str)
            or len(delivery["text"].encode()) > 8192
        )
    ):
        raise ValueError("Invalid closed public observation/delivery contract")
    image = delivery["image"]
    if image is not None:
        if (
            not isinstance(image, dict)
            or set(image) != {"path", "sha256", "bytes", "bbox"}
            or not _box(image["bbox"])
        ):
            raise ValueError("Invalid closed public image contract")
        common.read_bound(
            root / "public", {k: image[k] for k in ("path", "sha256", "bytes")}
        )
    pixels = common.read_relative(root / "public", packet["path"])
    if sha(pixels) != packet["sha256"]:
        raise ValueError("Retained observation bytes differ from host input")
    evaluator.image_from_bytes(pixels)
    return packet["sha256"]


def candidate_view(step):
    candidates = step.get("candidate_metadata")
    selected = step.get("selected_candidate_index")
    receipt = check_selection(step)
    if candidates is None:
        if selected is not None:
            raise ValueError(
                "Selection trace requires its original candidate inventory"
            )
        return None, None
    if (
        type(candidates) is not list
        or not 1 <= len(candidates) <= 128
        or any(
            type(c) is not dict
            or set(c) != {"text", "bbox", "origin"}
            or type(c["text"]) is not str
            or len(c["text"].encode()) > 8192
            or c["origin"]
            not in ("pixel_ocr", "registered_public_text", "no_recognized_text")
            or type(c["bbox"]) is not list
            or len(c["bbox"]) != 4
            or any(type(v) is not int or not 0 <= v <= 16_000_000 for v in c["bbox"])
            for c in candidates
        )
    ):
        raise ValueError("Invalid retained candidate inventory")
    if selected is not None and (
        type(selected) is not int
        or not 0 <= selected < len(candidates)
        or receipt is not None
        and selected != receipt["selected_index"]
    ):
        raise ValueError(
            "Selection trace differs from bounded candidate/written selection"
        )
    if selected is None and receipt is not None:
        selected = receipt["selected_index"]
    return candidates, None if selected is None else candidates[selected]


def read_changes(steps, index, macro, initial_packet, final_packet, truth=None):
    """Compare admitted actor observations; never invent an unexecuted STOP score."""
    before, initial = candidate_view(steps[0])
    after, selected = candidate_view(steps[index])
    pair_known = before is not None and after is not None
    old_text = (
        {c["text"].strip() for c in before if c["text"].strip()} if before else set()
    )
    new_text = (
        {c["text"].strip() for c in after if c["text"].strip()} if after else set()
    )
    matches = []
    for candidates in (before, after):
        matches.append(
            None
            if truth is None or candidates is None
            else any(
                evaluator.canonical(c["text"], truth["field"])
                == evaluator.canonical(truth["expected_text"], truth["field"])
                for c in candidates
            )
        )
    return {
        "schema": "ndu.real.read-attribution.v1",
        "read_executed": macro == "READ",
        "initial_packet_sha256": initial_packet,
        "finalizer_packet_sha256": final_packet,
        "observation_bytes_changed": None
        if initial_packet is None or final_packet is None
        else initial_packet != final_packet,
        "candidate_inventory_changed": None
        if not pair_known
        else digest(before) != digest(after),
        "new_recognized_text": None if not pair_known else bool(new_text - old_text),
        "new_candidate_text_sha256s": None
        if not pair_known
        else sorted(digest(v) for v in new_text - old_text),
        "initial_candidate_set_sha256": None if before is None else digest(before),
        "finalizer_candidate_set_sha256": None if after is None else digest(after),
        "initial_selected_text_sha256": None
        if initial is None
        else digest(initial["text"]),
        "finalizer_selected_text_sha256": None
        if selected is None
        else digest(selected["text"]),
        "selected_candidate_changed": None
        if initial is None or selected is None
        else digest(initial) != digest(selected),
        "selected_text_changed": None
        if initial is None or selected is None
        else initial["text"] != selected["text"],
        "written_text_differs_from_initial_selection": None
        if initial is None
        else steps[index]["action"]["arguments"]["text"] != initial["text"],
        "initial_scorer_match_present": matches[0],
        "finalizer_scorer_match_present": matches[1],
        "new_reference_matching_candidate": None
        if None in matches
        else not matches[0] and matches[1],
        "semantic_information_gain": None,
        "terminal_quality_change": None,
        "scope": "within-execution observed candidates and choices; OCR changes are not semantic information gain; terminal change requires matched STOP execution",
    }
