"""Bounded model-proposed text edits, converted to the common executor format."""

import hashlib
import json
from pathlib import PurePosixPath


EDIT_SCHEMA = {
    "type": "object",
    "properties": {
        "schema": {"const": "hepta.memory-cell.code-edits.v1"},
        "edits": {
            "type": "array",
            "minItems": 1,
            "maxItems": 8,
            "items": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "old": {"type": ["string", "null"]},
                    "new": {"type": "string"},
                },
                "required": ["path", "old", "new"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["schema", "edits"],
    "additionalProperties": False,
}


def canonical(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()


def sha(value):
    return hashlib.sha256(value).hexdigest()


def unique(pairs):
    value = dict(pairs)
    if len(value) != len(pairs):
        raise ValueError("duplicate JSON field")
    return value


def apply_edits(text, current, allowed):
    """An edit must name one allowed file and match one exact existing span."""
    if not isinstance(text, str) or not 0 < len(text.encode()) <= 131072:
        raise ValueError("bounded generated JSON required")
    if set(current) != set(allowed) or any(
        PurePosixPath(p).is_absolute() or ".." in PurePosixPath(p).parts
        for p in allowed
    ):
        raise ValueError("closed relative candidate source map required")
    value = json.loads(text, object_pairs_hook=unique)
    if (
        not isinstance(value, dict)
        or set(value) != {"schema", "edits"}
        or value["schema"] != "hepta.memory-cell.code-edits.v1"
        or not isinstance(value["edits"], list)
        or not 1 <= len(value["edits"]) <= 8
    ):
        raise ValueError("code edit schema")
    proposed = dict(current)
    for edit in value["edits"]:
        if not isinstance(edit, dict) or set(edit) != {"path", "old", "new"}:
            raise ValueError("edit fields")
        path, old, new = edit["path"], edit["old"], edit["new"]
        if path not in allowed or not isinstance(new, str) or "\0" in new:
            raise ValueError("out-of-scope edit")
        if old is None:
            if proposed[path] is not None:
                raise ValueError("create requires an absent admitted file")
            proposed[path] = new
        else:
            if (
                not isinstance(old, str)
                or not old
                or proposed[path] is None
                or proposed[path].count(old) != 1
            ):
                raise ValueError("old span must match exactly once")
            proposed[path] = proposed[path].replace(old, new, 1)
        if len(proposed[path].encode()) > 65536:
            raise ValueError("candidate file exceeds 64 KiB")
    if proposed == current:
        raise ValueError("proposal made no change")
    return proposed


def candidate_document(proposed, original):
    return {
        "schema": "hepta.memory-cell.implementation-candidate.v1",
        "files": [
            {"path": p, "content": proposed[p]}
            for p in sorted(proposed)
            if proposed[p] is not None and proposed[p] != original[p]
        ],
    }
