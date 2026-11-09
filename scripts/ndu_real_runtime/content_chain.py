"""Bind public candidates, selected content, actual delivery and scorer identity.

These byte checks do not authenticate an independent owner, release sealed
references or establish task quality. Catalogs contain public inputs only.
"""

import json
import os
from pathlib import Path

from ndu_real_materials.common import digest, read_bound, read_relative, strict_json
from .controllers import ACTIONS
from .metering import atomic_json, canonical_sha


MAX_CATALOG_BYTES = 8 * 1024 * 1024


def delivery_semantic_sha(delivery):
    """Image relocation keeps content identity; raw snapshot bytes stay separate."""
    if (
        not isinstance(delivery, dict)
        or set(delivery) != {"schema", "case_id", "text", "image"}
        or delivery["schema"] != "ndu.real.delivery.v1"
    ):
        raise ValueError("Invalid content-chain delivery")
    image = delivery["image"]
    if image is not None:
        if not isinstance(image, dict) or set(image) != {
            "path",
            "sha256",
            "bytes",
            "bbox",
        }:
            raise ValueError("Invalid content-chain image binding")
        image = {key: value for key, value in image.items() if key != "path"}
    return canonical_sha({**delivery, "image": image})


def catalog_document(state, candidates):
    if (
        not isinstance(state["case_id"], str)
        or not 1 <= len(state["case_id"]) <= 256
        or type(state["step"]) is not int
        or not 0 <= state["step"] < 8
        or not isinstance(candidates, list)
        or len(candidates) > 128
    ):
        raise ValueError("Candidate catalog exceeds the frozen identity/count bounds")
    for candidate in candidates:
        if (
            not isinstance(candidate, dict)
            or set(candidate) != {"text", "bbox", "origin"}
            or not isinstance(candidate["text"], str)
            or len(candidate["text"]) > 8192
            or not isinstance(candidate["origin"], str)
            or not 1 <= len(candidate["origin"]) <= 128
            or not isinstance(candidate["bbox"], list)
            or len(candidate["bbox"]) != 4
            or any(
                type(value) is not int or not 0 <= value < 2**31
                for value in candidate["bbox"]
            )
        ):
            raise ValueError("Invalid bounded public candidate")
    return {
        "schema": "ndu.real.public-candidate-catalog.v1",
        "case_id": state["case_id"],
        "step": state["step"],
        "observation_sha256": canonical_sha(state["observation"]),
        "candidates": candidates,
    }


def selection_receipt(state, candidates, selected_index, action, binding):
    if (
        not isinstance(action, dict)
        or set(action) != {"schema", "action", "arguments"}
        or action["schema"] != "ndu.real.actor-action.v1"
        or action["action"] not in ACTIONS
        or not isinstance(action["arguments"], dict)
    ):
        raise ValueError("Invalid content-chain action")
    selected = None
    if candidates:
        if type(selected_index) is not int or not 0 <= selected_index < len(candidates):
            raise ValueError("Selected candidate index is outside the actual catalog")
        selected = candidates[selected_index]
    elif selected_index is not None or action["action"] != "STOP":
        raise ValueError("Only an explicit STOP may have no candidate")
    if action["action"] == "WRITE_TEXT":
        expected = (
            state["delivery"]["text"] if state["text_committed"] else selected["text"]
        )
        if action["arguments"] != {"text": expected if expected is not None else ""}:
            raise ValueError(
                "WRITE_TEXT differs from selected or committed public text"
            )
    return {
        "schema": "ndu.real.content-selection.v1",
        "case_id": state["case_id"],
        "step": state["step"],
        "observation_sha256": canonical_sha(state["observation"]),
        "catalog": binding,
        "selected_index": selected_index,
        "selected_candidate_sha256": None
        if selected is None
        else canonical_sha(selected),
        "selected_text_sha256": None
        if selected is None
        else canonical_sha(selected["text"]),
        "prior_delivery_sha256": delivery_semantic_sha(state["delivery"]),
        "action_sha256": canonical_sha(action),
    }


def publish_selection(root, state, candidates, selected_index, action):
    """Create one bounded catalog; caller includes this work in its active meter."""
    catalog = catalog_document(state, candidates)
    raw = (
        json.dumps(catalog, indent=2, sort_keys=True, allow_nan=False) + "\n"
    ).encode()
    if len(raw) > MAX_CATALOG_BYTES:
        raise ValueError("Serialized candidate catalog exceeds 8 MiB")
    binding = {
        "path": f"decision-{state['step']:02d}.candidates.json",
        "bytes": len(raw),
        "sha256": digest(raw),
    }
    receipt = selection_receipt(state, candidates, selected_index, action, binding)
    if atomic_json(Path(root) / binding["path"], catalog) != binding["sha256"]:
        raise ValueError("Published candidate catalog differs from its original bytes")
    return receipt


def verify_selection(root, state, action, receipt, *, retain_root=None):
    if not isinstance(receipt, dict) or not isinstance(receipt.get("catalog"), dict):
        raise ValueError("Missing original content-selection receipt")
    raw = read_bound(root, receipt["catalog"], limit=MAX_CATALOG_BYTES)
    catalog = strict_json(raw)
    if not isinstance(catalog, dict) or "candidates" not in catalog:
        raise ValueError("Invalid public candidate catalog")
    candidates = catalog["candidates"]
    if catalog != catalog_document(state, candidates):
        raise ValueError("Candidate catalog changes case, step or observation")
    expected = selection_receipt(
        state, candidates, receipt.get("selected_index"), action, receipt["catalog"]
    )
    if receipt != expected:
        raise ValueError(
            "Content-selection receipt differs from the original public step"
        )
    if retain_root is not None:
        destination = Path(retain_root)
        destination.mkdir(exist_ok=True)
        with (destination / f"decision-{state['step']:02d}.candidates.json").open(
            "xb"
        ) as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        descriptor = os.open(destination, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    return expected


def delivery_snapshot(directory):
    raw = read_relative(directory, "delivery.json", limit=65536)
    snapshot = {
        "delivery": {"path": "delivery.json", "bytes": len(raw), "sha256": digest(raw)},
        "semantic_sha256": delivery_semantic_sha(strict_json(raw)),
    }
    verify_snapshot(directory, snapshot)
    return snapshot


def verify_snapshot(directory, snapshot):
    raw = read_bound(directory, snapshot["delivery"], limit=65536)
    delivery = strict_json(raw)
    if delivery_semantic_sha(delivery) != snapshot["semantic_sha256"]:
        raise ValueError("Actual delivery differs from its retained snapshot")
    image = delivery["image"]
    if image is not None:
        read_bound(directory, {key: image[key] for key in ("path", "sha256", "bytes")})


def verify_evaluation(score, case, config, snapshot, directory):
    """Reconcile scorer identity and recheck original delivered bytes after it exits."""
    expected = {
        "schema": "ndu.real.independent-evaluation.v1",
        "case_id": case["id"],
        "source_group": case["source_id"],
        "episode_group": case["episode_group"],
        "role": case["role"],
        "rubric_sha256": config["rubric_sha256"],
        "reference_sha256": case["reference"]["sha256"],
        "evaluator_source_sha256": config["evaluator_sha256"],
        "delivery_sha256": snapshot["delivery"]["sha256"],
        "native_owner_authentication": "SEPARATE_REQUIRED",
    }
    if (
        not isinstance(score, dict)
        or any(score.get(key) != value for key, value in expected.items())
        or score.get("confirmation_evaluated") is not False
    ):
        raise ValueError(
            "External scorer identity differs from the frozen task and delivery"
        )
    verify_snapshot(directory, snapshot)
