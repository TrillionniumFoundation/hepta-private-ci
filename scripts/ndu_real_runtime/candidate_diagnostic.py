"""Read-only DEVELOPMENT diagnosis of original candidate and ROI observations.

Accepts registered train v2 chains or linked development observations with schema
``ndu.real.development-transition.v1``. Never calls actors, OCR or training. Uses
the frozen scorer's normalizer; observed ROI coverage is not a causal benefit.
Hashes bind observations, not native owner authority. All attempts remain visible.
"""

import argparse
from collections import Counter, defaultdict
import hashlib
import json
import math
from pathlib import Path
import sys
import time

if __package__ and "." in __package__:
    from ..ndu_real_materials.evaluator import canonical
    from .trajectory import V2_SCHEMA, is_digest, validate_link
    from .objective import canonical_sha
else:
    from ndu_real_materials.evaluator import canonical
    from ndu_real_runtime.trajectory import V2_SCHEMA, is_digest, validate_link
    from ndu_real_runtime.objective import canonical_sha

DEVELOPMENT_SCHEMA = "ndu.real.development-transition.v1"
ROLES = {"train", "development"}
FIELDS = ("company", "date", "address", "total")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def number(value, *, positive=False):
    return (
        type(value) in (int, float)
        and math.isfinite(value)
        and (value > 0 if positive else value >= 0)
    )


def strict_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "Duplicate JSON field")
        result[key] = value
    return result


def decode(raw):
    return json.loads(raw, object_pairs_hook=strict_object)


def episode_diagnostic(case, packet, rows, trajectory, final_delivery=None):
    """Separate actual coverage, selection, stopping and acquisition evidence."""
    role = case["role"]
    require(role in ROLES, "Only train/development observations are admitted")
    require(rows and len(rows) <= 8, "An observed episode needs 1..8 rows")
    require(
        packet["case_id"] == case["id"] and packet["requirements"]["text"] is True,
        "Public text-task identity differs",
    )
    require(len(trajectory["steps"]) == len(rows), "Incomplete trajectory companion")
    first, prior = rows[0], None
    delivered, preparation = packet["initial_delivery"]["text"], []
    field = first["reference_field"]
    require(field in FIELDS, "Unknown frozen reference field")
    expected = canonical(first["expected_text"], field)
    require(expected is not None, "Reference outside the frozen normalizer")
    records, roi, coverage, ids = [], [], [], set()
    for index, (row, step) in enumerate(zip(rows, trajectory["steps"])):
        require(
            row["schema"] == (V2_SCHEMA if role == "train" else DEVELOPMENT_SCHEMA)
            and row["split"] == role
            and row["episode_id"] == case["id"]
            and row["source_group"] == case["source_id"]
            and row["origin_run_id"] == first["origin_run_id"]
            and row["episode_step"] == index,
            "Role, source, episode or original attempt differs",
        )
        validate_link(row)
        require(row["record_id"] not in ids, "Duplicate original record")
        ids.add(row["record_id"])
        require(
            row["reference_field"] == field
            and row["expected_text"] == first["expected_text"]
            and all(
                row[key] == first[key]
                for key in (
                    "source_size",
                    "memory_mode",
                    "utility_profile_sha256",
                    "rubric_sha256",
                    "behavior_control_profile_sha256",
                )
            ),
            "Mixed labels or profiles within an episode",
        )
        if prior is not None:
            require(
                row["previous_record_sha256"] == prior["record_sha256"]
                and row["candidate_features"] == prior["next_candidate_features"]
                and row["public_metadata"] == prior["next_public_metadata"]
                and row["before_score"] == prior["after_score"]
                and row["remaining_seconds"] <= prior["remaining_seconds"]
                and prior.get("terminal_reason") is None,
                "Broken original observation chain",
            )
        meta, candidates = row["public_metadata"], row["candidate_metadata"]
        require(
            len(meta) == 16
            and meta[:4] == [float(field == f) for f in FIELDS]
            and len(candidates) == len(row["candidate_features"])
            and 1 <= len(candidates) <= 128
            and all(
                isinstance(c["text"], str) and len(c["text"]) <= 8192
                for c in candidates
            )
            and number(row["duration_seconds"], positive=True)
            and row["execution_status"] in {"completed", "failed"},
            "Invalid observed candidates, metadata or duration",
        )
        require(
            step["case_id"] == case["id"]
            and step["step"] == index
            and step["action"]["action"] == row["action"]
            and step["candidate_metadata"] == candidates
            and step["candidate_features"] == row["candidate_features"]
            and step["public_metadata"] == meta
            and step["observed_action_seconds"] == row["duration_seconds"],
            "Original trajectory does not bind the diagnostic row",
        )
        correct = [c for c in candidates if canonical(c["text"], field) == expected]
        coverage.append(bool(correct))
        action, selected, decision = row["action"], None, "other_action"
        if row["execution_status"] == "failed":
            decision = "execution_failed"
        elif action == "WRITE_TEXT":
            selected = step["action"]["arguments"]["text"]
            require(
                isinstance(selected, str) and len(selected) <= 8192,
                "Invalid actual text action",
            )
            delivered = selected
            decision = (
                "out_of_candidate_write"
                if not any(selected == c["text"] for c in candidates)
                else "write_correct"
                if canonical(selected, field) == expected
                else "ranking_error"
                if correct
                else "write_without_correct_candidate"
            )
        elif action == "STOP":
            decision = (
                "stop_after_reconstructed_text_success"
                if canonical(delivered, field) == expected
                else "stop_with_unmet_reconstructed_text"
            )
        elif action == "PREPARE_ROI":
            preparation.append(row)
            decision = "prepare_roi"
        elif action == "READ_ROI":
            decision = "read_roi"
            roi.append(
                {
                    "record_id": row["record_id"],
                    "step": index,
                    "preparation_record_ids": [p["record_id"] for p in preparation],
                    "preparation_seconds": sum(
                        p["duration_seconds"] for p in preparation
                    ),
                    "read_seconds": row["duration_seconds"],
                    "cost_scope": "observed actions; already included in attempt envelope",
                }
            )
            preparation = []
        records.append(
            {
                "record_id": row["record_id"],
                "record_sha256": row["record_sha256"],
                "step": index,
                "action": action,
                "execution_status": row["execution_status"],
                "candidate_count": len(candidates),
                "correct_candidate_count": len(correct),
                "correct_candidate_origins": dict(
                    Counter(c["origin"] for c in correct)
                ),
                "candidate_status": "covered"
                if correct
                else "missing_correct_candidate",
                "decision": decision,
                "selected_text_sha256": canonical_sha(selected)
                if selected is not None
                else None,
                "duration_seconds": row["duration_seconds"],
            }
        )
        prior = row
    require(
        prior["next_candidate_features"] is None
        and prior["next_public_metadata"] is None
        and (
            prior.get("terminal_reason") in {"actor_stop", "budget_stop"}
            or prior["execution_status"] == "failed"
        ),
        "No observed terminal boundary",
    )
    for item in roi:
        index = item["step"]
        following = coverage[index + 1] if index + 1 < len(coverage) else None
        item.update(
            before_covered=coverage[index],
            after_covered=following,
            successor_record_sha256=rows[index + 1]["record_sha256"]
            if following is not None
            else None,
            outcome="successor_unobserved"
            if following is None
            else (
                "coverage_retained"
                if following and coverage[index]
                else "coverage_gained"
                if following
                else "coverage_lost"
                if coverage[index]
                else "still_missing"
            ),
        )
    if final_delivery is not None:
        require(
            final_delivery["case_id"] == case["id"], "Final delivery identity differs"
        )
    return {
        "reference_field": field,
        "reference_canonical_sha256": canonical_sha(expected),
        "rows": records,
        "roi_reads": roi,
        "decision_scope": "recorded action arguments and public initial text; final effects are separate",
        "reconstructed_text_correct": canonical(delivered, field) == expected,
        "observed_final_text_correct": None
        if final_delivery is None
        else canonical(final_delivery["text"], field) == expected,
        "final_delivery_matches_reconstruction": None
        if final_delivery is None
        else final_delivery["text"] == delivered,
        "observed_action_seconds": sum(r["duration_seconds"] for r in rows),
        "unconsumed_preparation_seconds": sum(
            r["duration_seconds"] for r in preparation
        ),
    }
