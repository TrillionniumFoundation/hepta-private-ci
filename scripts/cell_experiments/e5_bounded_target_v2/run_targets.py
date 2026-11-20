"""One frozen after-material pass; no retrieval, model, training or native execution."""

import argparse
import hashlib
import json
import resource
import sys
import time
from pathlib import Path


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def checked_json(path, expected, maximum=2097152):
    with path.open("rb") as handle:
        raw = handle.read(maximum + 1)
    if len(raw) > maximum or sha(raw) != expected:
        raise ValueError("frozen input/source changed: " + str(path))
    return json.loads(raw)


def main():
    parser = argparse.ArgumentParser()
    for name in ("root", "materials", "freeze", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--expected-freeze", required=True)
    args = parser.parse_args()
    started, cpu = time.monotonic(), time.process_time()
    freeze = checked_json(args.freeze, args.expected_freeze)
    root = args.root

    def verify_source():
        for pin in freeze["source_pins"]:
            path = root / pin["path"]
            raw = path.read_bytes()
            if len(raw) != pin["bytes"] or sha(raw) != pin["sha256"]:
                raise ValueError("target/source implementation changed: " + str(path))

    verify_source()
    policy = checked_json(
        root / "target-coverage-1/TARGET_POLICY.intent.json", freeze["policy_sha256"]
    )
    inputs = checked_json(
        root / "inputs-1/INPUT_FREEZE.json", policy["inputs_already_frozen_sha256"]
    )
    checked_json(root / "PREINPUT_SOURCE_FREEZE.json", policy["source_freeze_sha256"])
    index = checked_json(
        args.materials / "MATERIAL_INDEX.json", policy["material_index_sha256"]
    )
    pins = policy["ordered_input_pins"]
    assert len(pins) == len(inputs["rows"]) == len(index["materials"]) == 16
    views = {}
    for ordinal, pin in enumerate(pins):
        row = inputs["rows"][ordinal]
        assert pin["ordinal"] == row["ordinal"] == ordinal
        assert (
            pin["source_id"]
            == row["source_id"]
            == index["materials"][ordinal]["source_id"]
        )
        assert pin["status"] == row["status"]
        path = root / "inputs-1" / f"{ordinal:02d}"
        assert checked_json(path / "RESULT.json", pin["row_sha256"]) == row
        if pin["status"] != "SOURCE_REFUSAL":
            view = checked_json(path / "VIEW.json", pin["view_file_sha256"])
            assert sha((path / "PROMPT.txt").read_bytes()) == pin["prompt_sha256"]
            assert sha(view["prompt"].encode()) == pin["prompt_sha256"]
            assert view["view_digest"] == pin["view_digest"]
            views[ordinal] = view
    assert set(views) == set(range(16)) - {13}
    sys.path.insert(
        0, str(root / "source/scripts/cell_experiments/e5_bounded_retrieval_v2")
    )
    from bounded_material_io import BoundedBlobRoot
    from compact_wire import validate_view
    from target_actions import target_for_view
    from v2_common import canonical, require
    from v2_legacy import visible_material

    args.output.mkdir(parents=True, exist_ok=False)
    rows, requests = [], []
    for ordinal, pin in enumerate(pins):
        destination = args.output / f"{ordinal:02d}"
        destination.mkdir()
        t, c = time.monotonic(), time.process_time()
        before_store, after_store = (
            BoundedBlobRoot(args.materials),
            BoundedBlobRoot(args.materials),
        )
        after_store.byte_limit = policy["budgets"]["after_runtime_byte_cap_per_source"]
        after_store.call_limit = policy["budgets"][
            "after_runtime_blob_call_cap_per_source"
        ]
        row = {
            "ordinal": ordinal,
            "source_id": pin["source_id"],
            "structural_roundtrip": False,
            "visible_action_roundtrip": False,
            "training_execution_admitted": False,
            "target_sha256": None,
        }
        target = None
        if pin["status"] == "SOURCE_REFUSAL":
            row.update(
                status="SOURCE_REFUSAL", reason=pin["error"], runtime_after_reads=0
            )
        else:
            view = views[ordinal]
            try:
                entry = index["materials"][ordinal]
                material = checked_json(args.materials / entry["path"], entry["sha256"])
                require(
                    material["source_id"] == pin["source_id"],
                    "original source identity",
                )
                visible = visible_material.load_visible(before_store, material)
                validate_view(visible, view, pin["view_digest"])
                selected = [
                    r
                    for r in material["snapshots"]["after"]
                    if visible_material.runtime_path(
                        r["path"], material["runtime_roots"]
                    )
                    and r["path"].endswith((".py", ".pyx"))
                ]
                require(
                    len({r["path"] for r in selected}) == len(selected),
                    "duplicate after path",
                )
                require(
                    len(selected) <= after_store.call_limit, "after file count bound"
                )
                require(
                    all(
                        r["bytes"] <= policy["budgets"]["after_runtime_file_bytes_cap"]
                        for r in selected
                    ),
                    "after file byte bound",
                )
                after = {
                    r["path"]: visible_material.checked(after_store, r)
                    for r in selected
                }
                measured = target_for_view(visible, view, pin["view_digest"], after)
                reference = measured.pop("reference")
                target = measured.pop("target")
                (destination / "ORIGINAL_REFERENCE.json").write_bytes(reference)
                row.update(
                    measured,
                    reference_sha256=sha(reference),
                    reference_bytes=len(reference),
                    native_case_count=len(visible["cases"]),
                    view_digest=pin["view_digest"],
                    prompt_sha256=pin["prompt_sha256"],
                )
                row["status"] = (
                    "VISIBLE_TARGET_ROUNDTRIP"
                    if target is not None
                    else "TARGET_SCOPE_REFUSAL"
                )
                row["changed_runtime_files"] = [
                    {
                        "path": p,
                        "before_sha256": sha(visible["runtime"][p]),
                        "after_sha256": sha(after[p]),
                    }
                    for p in sorted(after)
                    if visible["runtime"][p] != after[p]
                ]
                if target is not None:
                    (destination / "TARGET.json").write_bytes(target)
                    row.update(target_sha256=sha(target), target_bytes=len(target))
            except Exception as error:
                row.update(
                    status="TARGET_REFUSAL",
                    reason=type(error).__name__ + ": " + str(error),
                )
                target = None
            requests.append(
                {
                    "ordinal": ordinal,
                    "source_id": pin["source_id"],
                    "prompt": view["prompt"],
                    "prompt_sha256": pin["prompt_sha256"],
                    "target": None if target is None else target.decode(),
                    "v1_static_context_closed": False,
                    "structural_roundtrip": row["structural_roundtrip"],
                    "visible_action_roundtrip": row["visible_action_roundtrip"],
                }
            )
        row.update(
            wall_seconds=time.monotonic() - t,
            cpu_seconds=time.process_time() - c,
            before_blob_reads=len(before_store.reads),
            before_blob_bytes=before_store.total,
            after_blob_reads=len(after_store.reads),
            after_blob_bytes=after_store.total,
            model_native_generation_training=0,
        )
        (destination / "BLOB_READS.json").write_bytes(
            canonical({"before": before_store.reads, "after": after_store.reads})
            + b"\n"
        )
        (destination / "RESULT.json").write_bytes(canonical(row) + b"\n")
        rows.append(row)
        print(json.dumps(row), flush=True)
    verify_source()
    for pin in pins:
        path = root / "inputs-1" / f"{pin['ordinal']:02d}"
        checked_json(path / "RESULT.json", pin["row_sha256"])
        if pin["status"] != "SOURCE_REFUSAL":
            checked_json(path / "VIEW.json", pin["view_file_sha256"])
            assert sha((path / "PROMPT.txt").read_bytes()) == pin["prompt_sha256"]
    result = {
        "schema": "hepta.e5.v2.independent-target-coverage.v1",
        "rows": rows,
        "source_freeze_sha256": args.expected_freeze,
        "policy_sha256": freeze["policy_sha256"],
        "original_input_freeze_sha256": policy["inputs_already_frozen_sha256"],
        "wall_seconds": time.monotonic() - started,
        "self_cpu_seconds": time.process_time() - cpu,
        "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "inputs_and_sources_unchanged": True,
        "retrieval_reruns": 0,
        "model_native_generation_training": 0,
        "optimizer_unit_mapping": None,
        "training_compute_or_verifier_budget": None,
        "independent_B_C": None,
        "training_prefixes_1_4_16": {str(n): False for n in (1, 4, 16)},
    }
    raw_result = canonical(result) + b"\n"
    (args.output / "RESULT.json").write_bytes(raw_result)
    request = {
        "schema": "hepta.e5.v2.complete-target-tokenizer-request.v1",
        "records": requests,
        "source_freeze_sha256": args.expected_freeze,
        "target_readout_sha256": sha(raw_result),
        "tokenizer_freeze_sha256": freeze["tokenizer_freeze_sha256"],
        "source_refusals": [r for r in rows if r["status"] == "SOURCE_REFUSAL"],
    }
    (args.output / "TOKENIZER_REQUEST.json").write_bytes(canonical(request) + b"\n")


if __name__ == "__main__":
    main()
