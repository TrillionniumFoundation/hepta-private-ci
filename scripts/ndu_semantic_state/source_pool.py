"""Unregistered real-source candidates, exposure history, and observation boundaries.

Integrity admission never supplies an owner registry, five-family annotation,
retention panel, independent scientific evaluator, or fresh confirmation source.
"""

from collections import Counter
import hashlib
import json
import time

import numpy as np

from .materials import _read, _strict_json, _text, check_file, load_public_case
from .state import exact_fields, sha256_value


SCHEMA = "hepta.real-source-candidates.v1"
HISTORY_SCHEMA = "hepta.candidate-exposure-history.v1"
SPLITS = {
    "train",
    "development",
    "confirmation",
    "retention_development",
    "retention_confirmation",
}
CASE_FIELDS = (
    "id",
    "source_id",
    "source_group_id",
    "episode_group_id",
    "derivative_root_ids",
    "group_evidence",
    "upstream_grouping_complete",
    "upstream_split",
    "project_split",
    "task_family",
    "retention_capability",
    "text",
    "image",
    "reference",
    "source_evidence",
    "image_pixel_sha256",
    "used_in_project_training",
    "observed_in_project",
    "pretraining_exposure",
)


def pixel_digest(rgb):
    return hashlib.sha256(
        str(tuple(rgb.shape)).encode() + rgb.tobytes(order="C")
    ).hexdigest()


def _case_keys(case):
    exact_fields(case, CASE_FIELDS, "candidate")
    for field in (
        "id",
        "source_id",
        "source_group_id",
        "episode_group_id",
        "group_evidence",
        "upstream_split",
    ):
        _text(case[field], field)
    if (
        case["project_split"] not in SPLITS
        or case["task_family"] is not None
        or case["retention_capability"] is not None
    ):
        raise ValueError(
            "Candidate roles cannot certify task families or retained capabilities"
        )
    roots = case["derivative_root_ids"]
    if not isinstance(roots, list) or not roots or len(set(roots)) != len(roots):
        raise ValueError("Nonempty unique derivative roots required")
    for root in roots:
        _text(root, "derivative root")
    for field in (
        "upstream_grouping_complete",
        "used_in_project_training",
        "observed_in_project",
    ):
        if type(case[field]) is not bool:
            raise ValueError("Explicit exposure/grouping booleans required")
    if case["pretraining_exposure"] not in {
        "unknown",
        "documented_unseen",
        "documented_seen",
    }:
        raise ValueError("Unknown model pretraining must remain unknown")
    if case["project_split"] in {"confirmation", "retention_confirmation"} and (
        case["observed_in_project"] or case["used_in_project_training"]
    ):
        raise ValueError("Consumed sources cannot be promoted to confirmation")
    for field in ("text", "image", "reference", "source_evidence"):
        exact_fields(case[field], ("path", "sha256", "bytes"), "candidate file")
        sha256_value(case[field]["sha256"], "candidate file hash")
    sha256_value(case["image_pixel_sha256"], "decoded image hash")
    return [
        ("source", case["source_id"]),
        ("group", case["source_group_id"]),
        ("episode", case["episode_group_id"]),
        ("image", case["image"]["sha256"]),
        ("pixels", case["image_pixel_sha256"]),
    ] + [("root", root) for root in roots]


def admit_candidate_pool(root, manifest_path, history_path, *, expected_history_sha256):
    """Check every historical group, including records absent from this selection.

    The caller pins the local history separately. This does not authenticate an
    external experiment owner or prove upstream grouping completeness.
    """
    started = time.process_time(), time.perf_counter()
    raw, manifest_hash, _ = _read(root, manifest_path, 8 * 1024**2)
    history_raw, history_hash, _ = _read(root, history_path, 8 * 1024**2)
    if history_hash != sha256_value(expected_history_sha256, "history pin"):
        raise ValueError("Candidate history differs from the separately supplied pin")
    manifest, history = _strict_json(raw), _strict_json(history_raw)
    exact_fields(
        manifest,
        (
            "schema",
            "study_id",
            "history_sha256",
            "acquisition_plan",
            "acquisition_receipt",
            "cases",
        ),
        "candidate manifest",
    )
    exact_fields(history, ("schema", "cases"), "candidate history")
    if (
        manifest["schema"] != SCHEMA
        or history["schema"] != HISTORY_SCHEMA
        or manifest["history_sha256"] != history_hash
    ):
        raise ValueError("Candidate schema or history binding differs")
    _text(manifest["study_id"], "study id")
    for field in ("acquisition_plan", "acquisition_receipt"):
        check_file(root, manifest[field], limit=8 * 1024**2)
    if (
        not isinstance(history["cases"], list)
        or not isinstance(manifest["cases"], list)
        or not manifest["cases"]
    ):
        raise ValueError("Nonempty candidate selection and full history required")
    registered, roles = {}, {}
    for case in history["cases"]:
        keys = _case_keys(case)
        if case["id"] in registered:
            raise ValueError("Duplicate candidate identity in history")
        registered[case["id"]] = case
        for key in keys:
            if key in roles and roles[key] != case["project_split"]:
                raise ValueError(
                    "Source/episode/derivative/image group crosses splits in full history"
                )
            roles[key] = case["project_split"]
    selected = set()
    for case in manifest["cases"]:
        _case_keys(case)
        if case["id"] in selected or registered.get(case["id"]) != case:
            raise ValueError(
                "Candidate reassigns its source, role, inputs or hidden reference"
            )
        selected.add(case["id"])
        public = load_candidate_public_case(root, case)
        if pixel_digest(public["image_rgb"]) != case["image_pixel_sha256"]:
            raise ValueError("Candidate decoded pixels differ")
        check_file(root, case["reference"], limit=2 * 1024**2)
        check_file(root, case["source_evidence"], limit=2 * 1024**2)
    return {
        "schema": "hepta.candidate-admission.v1",
        "manifest_sha256": manifest_hash,
        "history_sha256": history_hash,
        "integrity_status": "VERIFIED",
        "case_counts": dict(Counter(c["project_split"] for c in manifest["cases"])),
        "selected_source_groups": len(
            {c["source_group_id"] for c in manifest["cases"]}
        ),
        "history_records_checked": len(registered),
        "independent_cluster_count": None,
        "upstream_grouping_complete": all(
            c["upstream_grouping_complete"] for c in manifest["cases"]
        ),
        "owner_registration_verified": False,
        "task_families_verified": [],
        "retention_panel_registered": False,
        "independent_domain_evaluation_verified": False,
        "scientific_admission": False,
        "research_status": "HOLD",
        "new_training_started": False,
        "cpu_seconds": time.process_time() - started[0],
        "wall_seconds": time.perf_counter() - started[1],
        "cost_scope": "admission function before receipt serialization",
        "unknown_costs": [
            "process_startup",
            "receipt_write",
            "energy",
            "actual_charges",
        ],
    }


def load_candidate_public_case(root, candidate):
    """Keep the existing controller contract: current text and RGB pixels only."""
    return load_public_case(root, candidate)


def evaluator_public_view(public, delivered):
    """View for a learned evaluator/critic; never receives target or future data.

    These copies provide an API boundary, not an OS/filesystem sandbox. Native
    execution must enforce worker access separately.
    """
    exact_fields(public, ("text", "image_rgb"), "public observation")
    exact_fields(delivered, ("text", "image_rgb"), "current delivered output")

    def view(value):
        if value["text"] is not None and not isinstance(value["text"], str):
            raise ValueError("Current delivered text must be text or missing")
        rgb = value["image_rgb"]
        if rgb is not None:
            if (
                not isinstance(rgb, np.ndarray)
                or rgb.dtype != np.uint8
                or rgb.ndim != 3
                or rgb.shape[2] != 3
            ):
                raise ValueError("RGB uint8 observation required")
            rgb = rgb.copy()
            rgb.setflags(write=False)
        return {"text": value["text"], "image_rgb": rgb}

    return {"input": view(public), "current_output": view(delivered)}


def score_vizwiz_reference(reference, delivered_text):
    """Deterministic external reference grading, separate from any learned model.

    Ten-choose-nine human consensus with Unicode casefold/whitespace matching.
    This deliberately named local metric is NOT the official VQA normalization
    or a semantic image-quality evaluator. No action/future-outcome inputs exist.
    """
    if not isinstance(delivered_text, str):
        raise ValueError("A terminal text delivery is required")
    exact_fields(
        reference,
        ("image", "question", "answers", "answer_type", "answerable"),
        "original human reference",
    )
    answers = reference.get("answers")
    if not isinstance(answers, list) or len(answers) != 10:
        raise ValueError("Ten original human answers required")

    def normalize(value):
        return " ".join(_text(value, "human answer").casefold().split())

    for answer in answers:
        exact_fields(answer, ("answer", "answer_confidence"), "human annotation")
    predicted = " ".join(delivered_text.casefold().split())
    actual = [normalize(a["answer"]) for a in answers]
    score = (
        sum(
            min(1.0, sum(predicted == a for j, a in enumerate(actual) if j != i) / 3)
            for i in range(10)
        )
        / 10
    )
    return {
        "metric": "human_consensus_casefold_whitespace.v1",
        "score": score,
        "reference_canonical_sha256": hashlib.sha256(
            json.dumps(reference, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest(),
        "delivery_text_sha256": hashlib.sha256(
            delivered_text.encode("utf-8")
        ).hexdigest(),
        "learned_evaluator_used": False,
        "official_vqa_score": False,
        "image_quality": None,
        "task_family_verified": False,
        "independent_domain_evaluator_verified": False,
        "scientific_admission": False,
    }
