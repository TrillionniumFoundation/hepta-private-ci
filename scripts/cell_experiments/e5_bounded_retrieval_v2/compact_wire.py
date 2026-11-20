"""Strict source-scoped edit transport. The expected view pin is caller authority."""

import json

from before_index import validate_visible
from retrieve_once import render, unit_view
from v2_common import Budget, POLICY_SHA, canonical, code_identity, policy, require, sha
from v2_legacy import source_actions


def validate_view(visible, view, expected_view_digest):
    validate_visible(visible, Budget())
    require(
        set(view) == {"schema", "payload", "view_digest", "prompt", "prompt_sha256"}
        and view["schema"] == "hepta.e5.before-retrieved-view.v2",
        "unknown view envelope",
    )
    payload = view["payload"]
    require(
        view["view_digest"] == expected_view_digest == sha(canonical(payload)),
        "view pin changed",
    )
    require(
        payload["policy_sha256"] == POLICY_SHA
        and payload["code_sha256"] == code_identity(),
        "view code/policy changed",
    )
    require(
        payload["visible_identity_sha256"] == visible["identity_sha256"],
        "view material changed",
    )
    require(
        view["prompt"] == render(payload, expected_view_digest)
        and view["prompt_sha256"] == sha(view["prompt"].encode()),
        "rendered prompt changed",
    )
    require(
        len(view["prompt"].encode()) <= policy()["packing"]["max_prompt_bytes"],
        "view byte cap",
    )
    binding, units = source_actions.bind(
        visible["identity"]["source_id"], visible["runtime"]
    )
    require(
        payload["runtime_binding_sha256"] == binding["binding_sha256"],
        "runtime root changed",
    )
    actual = {u["unit_id"]: unit_view(u) for u in units}
    selected = payload["runtime_units"]
    require(
        selected and len(selected) <= policy()["packing"]["max_runtime_units"],
        "invalid visible unit count",
    )
    require(
        len({u["unit_id"] for u in selected}) == len(selected), "duplicate visible unit"
    )
    require(
        all(actual.get(u["unit_id"]) == u for u in selected),
        "visible original unit changed",
    )
    return binding, selected


def apply_compact(visible, view, expected_view_digest, raw):
    require(
        type(raw) is bytes and len(raw) <= policy()["wire"]["max_raw_bytes"],
        "raw answer bound",
    )
    binding, units = validate_view(visible, view, expected_view_digest)
    value = json.loads(raw.decode("utf-8"))
    require(
        type(value) is list
        and len(value) == 3
        and type(value[0]) is int
        and value[0] == 2
        and value[1] == expected_view_digest,
        "unknown/stale compact envelope",
    )
    require(
        type(value[2]) is list and len(value[2]) <= policy()["wire"]["max_edits"],
        "edit count bound",
    )
    edits = []
    for row in value[2]:
        require(type(row) is list and len(row) == 5, "unknown compact edit fields")
        ordinal, operation, start, end, replacement = row
        require(
            all(type(x) is int for x in (ordinal, operation, start, end))
            and 0 <= ordinal < len(units)
            and operation in (0, 1)
            and type(replacement) is str,
            "invalid compact edit types/scope",
        )
        edits.append(
            {
                "unit_id": units[ordinal]["unit_id"],
                "kind": "replace_lines" if operation == 0 else "insert_after",
                "start_line": start,
                "end_line": end,
                "replacement": replacement,
            }
        )
    action = {
        "schema": source_actions.SCHEMA,
        "binding_sha256": binding["binding_sha256"],
        "edits": edits,
    }
    return source_actions.apply(
        visible["runtime"],
        binding,
        canonical(action),
        frozenset(u["unit_id"] for u in units),
    )


def require_training_admission():
    raise ValueError(
        "training refused: exact tokenizer measurement, original optimizer-unit/compute/"
        "verifier budgets and independent B/C bindings remain absent"
    )
