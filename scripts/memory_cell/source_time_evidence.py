"""Lossless, explicit source-session metadata projection for Reader research.

This module consumes public source documents only. It cannot inspect targets,
infer event times, select documents, change citation IDs or grant qualification.
The content-only profile preserves the prior input bytes. Date-aware experiments
are separate registered representations, not a reinterpretation of old results.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from typing import Any, Iterable

CONTENT_ONLY = "content-only-v1"
SOURCE_TIME = "source-session-time-v1"
PROFILES = (CONTENT_ONLY, SOURCE_TIME)
PREFIX = "SOURCE SESSION TIME (verbatim metadata; not an event date): "
SEPARATOR = "\nSOURCE CONTENT:\n"


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False,
                      separators=(",", ":")).encode("utf-8")


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def source_id(identity: str) -> str:
    if not isinstance(identity, str) or not identity:
        raise ValueError("public source identity required")
    return "E" + digest(identity)[:12]


def project(request: dict, documents: Iterable[Any], profile: str) -> tuple[dict, dict]:
    """Add only the date belonging to each ALREADY selected source.

    Native Document.observed_at is the session timestamp, not a proof of event
    time. Do not add Question.observed_at: LoCoMo ingress derives it from the
    last session and does not establish when the question was actually asked.
    Dates are JSON quoted verbatim; no timezone/calendar inference is performed.
    """
    if profile not in PROFILES:
        raise ValueError("unregistered evidence representation")
    if not isinstance(request, dict) or set(request) != {"question", "options", "evidence"}:
        raise ValueError("public request fields")
    if (not isinstance(request["question"], str) or not request["question"]
            or not isinstance(request["options"], list)
            or not isinstance(request["evidence"], list)):
        raise ValueError("invalid public request")
    # Materialize the source lookup without reading benchmark target/category.
    known = {}
    for document in documents:
        label = source_id(document.identity)
        if label in known:
            raise ValueError("duplicate or colliding public source identity")
        known[label] = document
    result = deepcopy(request)
    seen, records = set(), []
    for original, output in zip(request["evidence"], result["evidence"]):
        if (not isinstance(original, dict)
                or set(original) != {"id", "modality", "text", "asset_sha256", "position"}):
            raise ValueError("public evidence fields")
        label = original["id"]
        if not isinstance(label, str) or label in seen or label not in known:
            raise ValueError("missing, duplicate or unbound public evidence")
        seen.add(label)
        document = known[label]
        if (original["modality"] != "text" or original["asset_sha256"] is not None
                or type(original["position"]) is not int or original["position"] < 0
                or original["text"] != document.content):
            raise ValueError("selected source content or modality changed")
        entry = {"id": label, "source_identity_sha256": digest(document.identity),
                 "original_text_sha256": digest(document.content)}
        if profile == SOURCE_TIME:
            date = getattr(document, "observed_at", None)
            if not isinstance(date, str) or not date.strip() or len(date.encode("utf-8")) > 256:
                raise ValueError("bound source-session date missing or oversized")
            output["text"] = PREFIX + json.dumps(date, ensure_ascii=False) + SEPARATOR + document.content
            entry["source_session_time_sha256"] = digest(date)
        entry["projected_text_sha256"] = digest(output["text"])
        records.append(entry)
    # The evidence list, IDs, order, positions and body suffixes are never edited
    # to improve retrieval or an answer. This receipt stays outside model input.
    receipt = {"schema": "hepta.evidence.source-time-projection.v1", "profile": profile,
               "input_sha256": digest(request), "output_sha256": digest(result),
               "sources": records, "target_access": False,
               "event_date_inferred": False, "question_date_inferred": False,
               "independent_sufficiency": False, "production_accepted": False}
    return result, receipt
