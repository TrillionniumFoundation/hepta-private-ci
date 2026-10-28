"""Independent audit of a selected new-interpreter neural continuation receipt."""

import json

import numpy as np

from online_audit_common import check, read_arrays, sha
from online_state_audit import audit_stream_snapshot


def audit_replay(
    directory,
    receipt,
    expected_selected,
    inputs,
    full_stream,
    model_sha,
    checkpoint_sha,
    final_state_bytes,
):
    if not expected_selected:
        check(receipt["status"] == "not_selected", "unplanned cross-process case")
        return {"selected": False}
    check(
        receipt["status"] == "completed" and receipt["returncode"] == 0,
        "cross-process completion",
    )
    check(
        receipt["passed"] and receipt["exact_logits"] and receipt["exact_final_state"],
        "recorded replay equality",
    )
    path = directory / "cold_replay"
    check(
        json.loads((path / "EXECUTION.json").read_text()) == receipt,
        "cross-process execution receipt",
    )
    check(
        sha(path / "REQUEST.json") == receipt["request_sha256"],
        "child request identity",
    )
    request = json.loads((path / "REQUEST.json").read_text())
    check(
        request["model_sha256"] == model_sha
        and request["checkpoint_manifest_sha256"] == checkpoint_sha,
        "child binds the measured selected model",
    )
    split = receipt["split_step"]
    batch, length = inputs["x"].shape[:2]
    check(split == max(1, length // 2), "preselected midpoint frontier")
    check(
        sha(path / "state/manifest.json")
        == request["state_manifest_sha256"]
        == receipt["state_receipt"]["manifest_sha256"],
        "bound midpoint snapshot identity",
    )
    check(
        sha(path / "state/state.npz") == receipt["state_receipt"]["payload_sha256"],
        "midpoint payload SHA",
    )
    check(
        sha(path / "inputs/manifest.json") == request["inputs_manifest_sha256"],
        "remainder input identity",
    )
    remainder = read_arrays(path / "inputs")
    check(set(remainder) == {"x", "dt"}, "child receives no expected logits/labels")
    check(
        all(
            np.array_equal(remainder[key], inputs[key][:, split:]) for key in remainder
        ),
        "exact measured remainder inputs",
    )
    state = audit_stream_snapshot(
        (path / "state/manifest.json").read_bytes(),
        (path / "state/state.npz").read_bytes(),
        model_sha,
        split,
        batch,
    )
    check(
        state == receipt["state_receipt"],
        "independent midpoint snapshot bytes/identity",
    )
    check(
        sha(path / "parent_expected/manifest.json")
        == receipt["parent_expected_manifest_sha256"],
        "parent continuation identity",
    )
    parent = read_arrays(path / "parent_expected")["logits"]
    check(
        np.array_equal(parent, full_stream[:, split:]),
        "parent continuation equals the independently saved full stream",
    )
    child = json.loads((path / "child/RESULT.json").read_text())
    check(child == receipt["child"], "child receipt identity")
    check(
        sha(path / "child/arrays/manifest.json") == child["arrays_manifest_sha256"],
        "child logits identity",
    )
    actual = read_arrays(path / "child/arrays")["logits"]
    check(np.array_equal(parent, actual), "exact fresh-process continuation logits")
    check(
        receipt["parent_expected_final_state_sha256"] == child["final_state_sha256"],
        "explicit parent/child final state digest",
    )
    check(
        child["model_sha256"] == request["model_sha256"], "fresh-process model binding"
    )
    check(
        child["steps"] == length
        and child["processed_rows"] == batch * length
        and child["state_bytes"] == final_state_bytes,
        "child final causal counters/state size",
    )
    check(
        child["pid"] != receipt["parent_pid"]
        and child["parent_pid"] == receipt["parent_pid"],
        "distinct interpreter process",
    )
    check(
        receipt["distinct_process"] and receipt["max_abs_logit_error"] == 0,
        "cold replay claims",
    )
    check(
        receipt["external_process_cost_seconds"]["wall"]
        >= child["module_total_wall_seconds"],
        "external startup/shutdown scope",
    )
    for costs in child["costs_seconds"].values():
        check(
            all(np.isfinite(x) and x >= 0 for x in costs.values()),
            "finite child phase costs",
        )
    return {
        "selected": True,
        "exact_logits": True,
        "exact_state_digest": True,
        "replayed_logits": int(actual.size),
        "external_process_cost_seconds": receipt["external_process_cost_seconds"],
    }
