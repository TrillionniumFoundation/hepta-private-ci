"""Require every independent source guard in one consolidated manifest row.

Combining records for the same file must retain all required/forbidden markers,
ordered checks, function scopes and top-level constraints. Extra guards are
allowed; no source constraint can be dropped just because another record exists.
"""


from copy import deepcopy
import hashlib
import json
from pathlib import Path

_FORMAT_MAP = Path(__file__).with_name("protected_marker_format_20261115.json")
_FORMAT_MAP_SHA256 = "6c445c7bdc306ac23e72b26c14b5a9457f2b02e103255b05265477db78412e00"
_format_bytes = _FORMAT_MAP.read_bytes()
if hashlib.sha256(_format_bytes).hexdigest() != _FORMAT_MAP_SHA256:
    raise AssertionError("reviewed source guard format map changed")
_FORMATTED_MARKERS = json.loads(_format_bytes)["paths"]


def _variants(path, marker):
    return [marker, *_FORMATTED_MARKERS.get(path, {}).get(marker, [])]


def _project_sequence(path, expected, actual):
    position = 0
    projected = []
    for marker in expected:
        alternatives = _variants(path, marker)
        for index in range(position, len(actual)):
            if actual[index] in alternatives:
                projected.append(actual[index])
                position = index + 1
                break
        else:
            return None
    return projected


def align_protected_record(expected, rows):
    """Apply only hash-pinned formatter spellings, retaining every constraint."""
    matches = [row for row in rows if row["path"] == expected["path"]]
    if len(matches) != 1:
        raise AssertionError(("one consolidated protected record", expected["path"]))
    actual = matches[0]
    path = expected["path"]
    aligned = deepcopy(expected)
    for index, marker in enumerate(aligned.get("required", [])):
        candidates = [value for value in _variants(path, marker)
                      if value in actual.get("required", [])]
        if not candidates:
            raise AssertionError(("missing independent source guard", path, marker))
        aligned["required"][index] = candidates[0]
    for index, sequence in enumerate(aligned.get("required_order", [])):
        candidates = [_project_sequence(path, sequence, candidate)
                      for candidate in actual.get("required_order", [])]
        candidates = [candidate for candidate in candidates if candidate is not None]
        if not candidates:
            raise AssertionError(("missing independent ordered guard", path, sequence))
        aligned["required_order"][index] = candidates[0]
    for rule in aligned.get("required_function_order", []):
        for candidate in actual.get("required_function_order", []):
            if candidate["function"] != rule["function"]:
                continue
            sequence = _project_sequence(path, rule["sequence"], candidate["sequence"])
            if sequence is None:
                continue
            additions = {}
            for field in ("top_level", "literal_calls"):
                projected = [next((value for value in _variants(path, marker)
                                   if value in candidate.get(field, [])), None)
                             for marker in rule.get(field, [])]
                if any(value is None for value in projected):
                    break
                if field in rule:
                    additions[field] = projected
            else:
                rule["sequence"] = sequence
                rule.update(additions)
                break
        else:
            raise AssertionError(("missing independent function guard", path, rule))
    return aligned


def _subsequence(expected, actual):
    position = 0
    for value in expected:
        try:
            position = actual.index(value, position) + 1
        except ValueError:
            return False
    return True


def require_protected_record(expected, rows):
    expected = align_protected_record(expected, rows)
    matches = [row for row in rows if row["path"] == expected["path"]]
    if len(matches) != 1:
        raise AssertionError(("one consolidated protected record", expected["path"]))
    actual = matches[0]
    for key, value in expected.items():
        if key in ("required", "forbidden"):
            if any(marker not in actual.get(key, []) for marker in value):
                raise AssertionError(("missing independent source guard", expected["path"], key))
        elif key == "required_order":
            for sequence in value:
                if not any(_subsequence(sequence, candidate) for candidate in actual.get(key, [])):
                    raise AssertionError(("missing independent ordered guard", expected["path"], sequence))
        elif key == "required_function_order":
            for rule in value:
                candidates = [candidate for candidate in actual.get(key, [])
                              if candidate["function"] == rule["function"]]
                def contains(candidate):
                    for field, required in rule.items():
                        if field == "sequence":
                            if not _subsequence(required, candidate.get(field, [])):
                                return False
                        elif field in ("top_level", "literal_calls"):
                            if any(marker not in candidate.get(field, []) for marker in required):
                                return False
                        elif candidate.get(field) != required:
                            return False
                    return True
                if not any(contains(candidate) for candidate in candidates):
                    raise AssertionError(("missing independent function guard", expected["path"], rule))
        elif actual.get(key) != value:
            raise AssertionError(("changed source authority metadata", expected["path"], key))
    return actual


def align_boundary_definition(expected, actual):
    result = deepcopy(expected)
    path = expected["definition_path"]
    for index, marker in enumerate(result["definition_markers"]):
        candidates = [value for value in _variants(path, marker)
                      if value in actual["definition_markers"]]
        if not candidates:
            raise AssertionError(("missing independent definition guard", path, marker))
        result["definition_markers"][index] = candidates[0]
    return result
