"""Native session identity: exact copies are not new independent evidence."""
from __future__ import annotations


def normalize_sessions(sessions, identities, dates):
    if not all(isinstance(value, list) for value in (sessions, identities, dates)) or not len(sessions) == len(identities) == len(dates) or len(identities) > 10_000:
        raise ValueError(f"misaligned native session arrays: {len(sessions)}/{len(identities)}/{len(dates)}")
    normalized, seen, duplicates = [], {}, []
    for position, (turns, identity, date) in enumerate(zip(sessions, identities, dates, strict=True)):
        if not isinstance(identity, str) or not identity or not isinstance(turns, list):
            raise ValueError("invalid native session identity/turns")
        clean = tuple((turn["role"], turn["content"]) for turn in turns)
        value = (date, clean)
        if identity in seen:
            if seen[identity] != value:
                raise ValueError(f"conflicting native session identity at occurrence {position}: {identity}")
            duplicates.append({"identity": identity, "position": position, "disposition": "same-source-copy-not-independent"})
            continue
        seen[identity] = value
        normalized.append((turns, identity, date))
    return normalized, duplicates
