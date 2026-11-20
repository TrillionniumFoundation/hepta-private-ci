"""A bounded, exact-source action transport; no upstream code is executed."""

import difflib
import json
from pathlib import PurePosixPath

from source_units import inventory, sha

SCHEMA = "hepta.source-unit-line-actions.v1"
MAX_ANSWER_BYTES = 32768
MAX_ACTIONS = 128


def canonical(value):
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode()


def unique(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate JSON key")
        value[key] = item
    return value


def bind(source_id, before):
    units = []
    files = []
    for path, raw in sorted(before.items()):
        name = PurePosixPath(path)
        if name.is_absolute() or str(name) != path or ".." in name.parts:
            raise ValueError("unsafe source path")
        current = inventory(path, raw)
        units += current
        files.append({"path": path, "bytes": len(raw), "sha256": sha(raw)})
    document = {
        "schema": SCHEMA,
        "source_id": source_id,
        "files": files,
        "units": [{k: v for k, v in u.items() if k != "text"} for u in units],
    }
    if len({u["unit_id"] for u in units}) != len(units):
        raise ValueError("source unit identifier collision")
    document["binding_sha256"] = sha(canonical(document))
    return document, units


def owner_unit(units, path, start, end):
    candidates = [
        u
        for u in units
        if u["path"] == path and u["start_line"] <= start <= end <= u["end_line"]
    ]
    if not candidates and start == end:
        # A new complete helper can be inserted at the end of a visible unit.
        candidates = [u for u in units if u["path"] == path and u["end_line"] <= start]
        if candidates:
            return max(candidates, key=lambda u: u["end_line"]), "insert_after"
    if not candidates:
        raise ValueError(
            f"changed line interval has no complete source-unit owner: {path}:{start + 1}-{end}"
        )
    return min(
        candidates, key=lambda u: u["end_line"] - u["start_line"]
    ), "replace_lines"


def reference_action(source_id, before, after):
    """The only function accepting after bytes; inputs are never selected here."""
    if set(before) != set(after):
        raise ValueError(
            "new/deleted files need a separate prospective file-creation protocol"
        )
    binding, units = bind(source_id, before)
    edits = []
    for path in sorted(before):
        a, b = (
            before[path].decode().splitlines(keepends=True),
            after[path].decode().splitlines(keepends=True),
        )
        for tag, i, j, x, y in difflib.SequenceMatcher(
            a=a, b=b, autojunk=False
        ).get_opcodes():
            if tag == "equal":
                continue
            unit, kind = owner_unit(units, path, i, j)
            edits.append(
                {
                    "unit_id": unit["unit_id"],
                    "kind": kind,
                    "start_line": i,
                    "end_line": j,
                    "replacement": "".join(b[x:y]),
                }
            )
    value = {
        "schema": SCHEMA,
        "binding_sha256": binding["binding_sha256"],
        "edits": edits,
    }
    payload = canonical(value)
    return payload, binding, units


def apply(before, binding, payload, allowed_units):
    if not isinstance(payload, bytes) or len(payload) > MAX_ANSWER_BYTES:
        raise ValueError("raw answer exceeds the original 32768-byte bound")
    action = json.loads(payload.decode("utf-8"), object_pairs_hook=unique)
    if (
        not isinstance(action, dict)
        or set(action) != {"schema", "binding_sha256", "edits"}
        or action["schema"] != SCHEMA
    ):
        raise ValueError("unknown action envelope")
    actual, units = bind(binding["source_id"], before)
    if actual != binding or action["binding_sha256"] != binding["binding_sha256"]:
        raise ValueError("source or action binding changed")
    if (
        not isinstance(action["edits"], list)
        or not 0 <= len(action["edits"]) <= MAX_ACTIONS
    ):
        raise ValueError("action count outside its bound")
    by = {u["unit_id"]: u for u in units}
    if not isinstance(allowed_units, (set, frozenset)) or not allowed_units <= set(by):
        raise ValueError("an explicit bound visible-unit set is required")
    edits = {}
    for edit in action["edits"]:
        if not isinstance(edit, dict) or set(edit) != {
            "unit_id",
            "kind",
            "start_line",
            "end_line",
            "replacement",
        }:
            raise ValueError("unknown edit fields")
        if not isinstance(edit["unit_id"], str) or edit["unit_id"] not in allowed_units:
            raise ValueError(
                "action targets a unit outside the admitted visible context"
            )
        unit = by[edit["unit_id"]]
        start, end = edit["start_line"], edit["end_line"]
        if (
            type(start) is not int
            or type(end) is not int
            or not isinstance(edit["replacement"], str)
        ):
            raise ValueError("invalid line index or replacement type")
        lines = before[unit["path"]].splitlines(keepends=True)
        if not 0 <= start <= end <= len(lines):
            raise ValueError("line interval outside the bound source")
        if edit["kind"] == "replace_lines":
            if not unit["start_line"] <= start <= end <= unit["end_line"]:
                raise ValueError("replacement crosses its complete source unit")
        elif edit["kind"] == "insert_after":
            if (
                start != end
                or start < unit["end_line"]
                or b"".join(lines[unit["end_line"] : start]).strip()
            ):
                raise ValueError(
                    "helper insertion is not adjacent through unchanged whitespace"
                )
            if not edit["replacement"].strip():
                raise ValueError("empty helper insertion")
        else:
            raise ValueError("unknown source action kind")
        edits.setdefault(unit["path"], []).append(edit)
    result = dict(before)
    for path, rows in edits.items():
        rows.sort(key=lambda e: (e["start_line"], e["end_line"]))
        cursor, output = 0, []
        lines = before[path].splitlines(keepends=True)
        previous = None
        for edit in rows:
            start, end = edit["start_line"], edit["end_line"]
            if start < cursor or previous == (start, end):
                raise ValueError("overlapping or duplicate source edits")
            output += [b"".join(lines[cursor:start]), edit["replacement"].encode()]
            cursor, previous = end, (start, end)
        result[path] = b"".join(output) + b"".join(lines[cursor:])
        inventory(path, result[path])  # Syntax/lexical boundary check only.
    # Existing Python/Cython twins are one correction material, not substitutes.
    paths = set(before)
    changed = {p for p in result if result[p] != before[p]}
    for path in changed:
        twin = path[:-3] + ".pyx" if path.endswith(".py") else path[:-4] + ".py"
        if twin in paths and twin not in changed:
            raise ValueError(
                "Python/Cython counterpart omitted from coupled correction"
            )
    return result
