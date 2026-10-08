"""Dated native occurrences and content versions without fabricated support.

Identical content at different dates remains distinct retrieval evidence but one
source family. Content conflicts reject by default. An explicit version-retention
profile preserves conflicts without choosing a variant using gold annotations.
"""
from __future__ import annotations

import hashlib
import json
from typing import Literal

OCCURRENCE = "#occ:"
CHUNK = "#chunk:"
VERSION = "~version:"
ConflictPolicy = Literal["reject", "retain-versioned"]


def source_id(identity: str) -> str:
    """Only strip occurrence/chunk selectors, never ambiguous content versions."""
    return identity.split(CHUNK, 1)[0].split(OCCURRENCE, 1)[0]


def normalize_sessions(sessions, identities, dates, *, conflict_policy: ConflictPolicy = "reject"):
    if conflict_policy not in ("reject", "retain-versioned"):
        raise ValueError("unknown native session conflict policy")
    if not all(isinstance(value, list) for value in (sessions, identities, dates)):
        raise ValueError("native session arrays must be lists")
    if not len(sessions) == len(identities) == len(dates) or not 1 <= len(identities) <= 10_000:
        raise ValueError("misaligned or oversized native session arrays")
    groups, occurrences, issues = {}, [], []
    for position, (turns, identity, date) in enumerate(zip(sessions, identities, dates, strict=True)):
        if (not isinstance(identity, str) or not identity.strip() or len(identity.encode()) > 256
            or any(marker in identity for marker in (OCCURRENCE, CHUNK, VERSION))
            or not isinstance(date, str) or not date.strip() or len(date.encode()) > 256
            or not isinstance(turns, list) or not 1 <= len(turns) <= 10_000):
            raise ValueError(f"invalid native session identity/date/turns at {position}")
        clean = []
        for turn in turns:
            if (not isinstance(turn, dict) or turn.get("role") not in ("user", "assistant", "system")
                or not isinstance(turn.get("content"), str) or not turn["content"].strip()
                or len(turn["content"].encode()) > 1_000_000):
                raise ValueError(f"invalid native history turn at occurrence {position}")
            clean.append((turn["role"], turn["content"]))
        body = hashlib.sha256(json.dumps(clean, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
        variants = groups.setdefault(identity, {})
        if variants and body not in variants and conflict_policy == "reject":
            raise ValueError(f"conflicting native session content at occurrence {position}: {identity}")
        timestamps = variants.setdefault(body, {})
        if date in timestamps:
            issues.append({"identity": identity, "position": position, "first_position": timestamps[date][1],
                           "disposition": "same-source-copy-not-independent"})
            continue
        timestamps[date] = (turns, position)
        occurrences.append((identity, body, date))
    normalized = []
    conflict_ids = {}
    for identity, body, date in occurrences:
        variants = groups[identity]
        occurrence = identity if len(variants) == 1 else f"{identity}{VERSION}{body}"
        if len(variants[body]) > 1:
            occurrence += OCCURRENCE + hashlib.sha256(date.encode()).hexdigest()
            issues.append({"identity": identity, "observed_at": date, "occurrence_id": occurrence,
                           "disposition": "distinct-date-preserved-same-support-root"})
        if len(variants) > 1:
            conflict_ids.setdefault(identity, []).append(occurrence)
        normalized.append((variants[body][date][0], occurrence, date))
    for identity, ids in conflict_ids.items():
        issues.append({"identity": identity, "versioned_identities": sorted(ids),
                       "disposition": "conflicting-observations-retained-annotation-not-resolved"})
    if len({identity for _, identity, _ in normalized}) != len(normalized):
        raise ValueError("native/generated session identity collision")
    return normalized, issues
