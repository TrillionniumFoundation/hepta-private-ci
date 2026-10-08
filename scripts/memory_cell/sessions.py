"""Native session occurrences preserve dates without multiplying source evidence.

LongMemEval may sample identical filler content at several timestamps. A dated
occurrence is a different retrieval item, not a different independent source.
Content changes under one native ID still fail closed. Gold annotations never
participate in either identity or deduplication.
"""

from __future__ import annotations

import hashlib

OCCURRENCE = "#occ:"
CHUNK = "#chunk:"


def source_id(identity: str) -> str:
    """Map a dated occurrence/chunk to its original benchmark evidence ID."""
    return identity.split(CHUNK, 1)[0].split(OCCURRENCE, 1)[0]


def normalize_sessions(sessions, identities, dates):
    if not all(isinstance(value, list) for value in (sessions, identities, dates)):
        raise ValueError("native session arrays must be lists")
    if not len(sessions) == len(identities) == len(dates) or len(identities) > 10_000:
        raise ValueError("misaligned or oversized native session arrays")
    bodies, timestamps = {}, {}
    records = []
    for position, (turns, identity, date) in enumerate(zip(sessions, identities, dates, strict=True)):
        if (
            not isinstance(identity, str) or not identity or len(identity) > 256
            or OCCURRENCE in identity or CHUNK in identity
            or not isinstance(date, str) or not date.strip() or len(date) > 256
            or not isinstance(turns, list) or not 1 <= len(turns) <= 10_000
        ):
            raise ValueError("invalid native session identity, date, or turns")
        clean = []
        for turn in turns:
            if (
                not isinstance(turn, dict) or turn.get("role") not in ("user", "assistant", "system")
                or not isinstance(turn.get("content"), str) or not turn["content"].strip()
                or len(turn["content"].encode()) > 1_000_000
            ):
                raise ValueError("invalid native session turn")
            clean.append((turn["role"], turn["content"]))
        body = tuple(clean)
        if identity in bodies and bodies[identity] != body:
            raise ValueError(f"conflicting native session content at occurrence {position}: {identity}")
        bodies[identity] = body
        timestamps.setdefault(identity, set()).add(date)
        records.append((turns, identity, date))
    normalized, seen, audit = [], set(), []
    for position, (turns, identity, date) in enumerate(records):
        if (identity, date) in seen:
            audit.append({"identity": identity, "position": position,
                          "disposition": "same-source-copy-not-independent"})
            continue
        seen.add((identity, date))
        occurrence = identity
        if len(timestamps[identity]) > 1:
            occurrence += OCCURRENCE + hashlib.sha256(date.encode()).hexdigest()
            audit.append({"identity": identity, "position": position, "observed_at": date,
                          "occurrence_id": occurrence,
                          "disposition": "distinct-date-preserved-same-support-root"})
        normalized.append((turns, occurrence, date))
    return normalized, audit
