"""After a published input/source freeze, construct full targets and roundtrip.

This is a material/action check. It never imports upstream code, calls a model,
replays native tests, trains, changes source order, or revises frozen inputs.
"""

import argparse
import json
import platform
import time
from pathlib import Path

from source_actions import apply, canonical, reference_action
from source_units import sha
from visible_material import checked, load_visible, runtime_path


def main():
    parser = argparse.ArgumentParser()
    for option in ("materials", "contexts", "freeze", "output"):
        parser.add_argument("--" + option, type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    started, cpu = time.monotonic(), time.process_time()
    freeze = json.loads(args.freeze.read_bytes())
    for name, digest in freeze["source_sha256"].items():
        assert sha((Path(__file__).parent / name).read_bytes()) == digest, name
    index_raw = (args.materials / "MATERIAL_INDEX.json").read_bytes()
    assert sha(index_raw) == freeze["material_index_sha256"]
    index = json.loads(index_raw)
    rows, requests = [], []
    for ordinal, entry in enumerate(index["materials"]):
        raw = (args.materials / entry["path"]).read_bytes()
        assert sha(raw) == entry["sha256"] and len(raw) == entry["bytes"]
        material = json.loads(raw)
        context_raw = (args.contexts / f"{ordinal:02d}" / "CONTEXT.json").read_bytes()
        assert sha(context_raw) == freeze["before_contexts"][ordinal]["sha256"]
        context = json.loads(context_raw)
        assert (
            material["source_id"]
            == context["source_id"]
            == freeze["before_contexts"][ordinal]["source_id"]
        )
        visible = load_visible(args.materials, material)
        assert visible["identity_sha256"] == context["visible_identity_sha256"]
        before = visible["runtime"]
        # Only this phase reads runtime after bytes. Neither selection nor
        # rendering is called here: the frozen prompt is used verbatim.
        after = {
            r["path"]: checked(args.materials, r)
            for r in material["snapshots"]["after"]
            if runtime_path(r["path"], material["runtime_roots"])
            and r["path"].endswith((".py", ".pyx"))
        }
        destination = args.output / f"{ordinal:02d}"
        destination.mkdir()
        row = {
            "ordinal": ordinal,
            "source_id": material["source_id"],
            "context_sha256": sha(context_raw),
            "prompt_sha256": context["prompt_sha256"],
            "v1_static_context_closed": context["v1_static_context_closed"],
            "static_blockers": context["blockers"],
            "structural_roundtrip": False,
            "visible_action_roundtrip": False,
            "training_execution_admitted": False,
        }
        payload = None
        try:
            payload, binding, units = reference_action(
                material["source_id"], before, after
            )
            assert binding == context["binding"]
            assert payload == reference_action(material["source_id"], before, after)[0]
            candidate = apply(before, binding, payload, {u["unit_id"] for u in units})
            assert candidate == after
            (destination / "TARGET.json").write_bytes(payload)
            changed = [p for p in sorted(before) if before[p] != after[p]]
            row.update(
                {
                    "structural_roundtrip": True,
                    "target_bytes": len(payload),
                    "target_sha256": sha(payload),
                    "edit_count": len(json.loads(payload)["edits"]),
                    "changed_runtime_files": [
                        {
                            "path": p,
                            "before_sha256": sha(before[p]),
                            "after_sha256": sha(after[p]),
                        }
                        for p in changed
                    ],
                }
            )
            try:
                assert (
                    apply(before, binding, payload, set(context["allowed_units"]))
                    == after
                )
                row["visible_action_roundtrip"] = True
            except (ValueError, SyntaxError) as error:
                row["visible_action_rejection"] = (
                    type(error).__name__ + ": " + str(error)
                )
            controls = {}
            corrupted = json.loads(payload)
            corrupted["binding_sha256"] = "0" * 64
            try:
                apply(
                    before, binding, canonical(corrupted), {u["unit_id"] for u in units}
                )
                raise AssertionError("changed binding accepted")
            except ValueError:
                controls["changed_root_binding_rejected"] = True
            if changed:
                corrupt_before = dict(before)
                corrupt_before[changed[0]] += b"\n# source tamper\n"
                try:
                    apply(
                        corrupt_before, binding, payload, {u["unit_id"] for u in units}
                    )
                    raise AssertionError("changed original accepted")
                except ValueError:
                    controls["changed_original_bytes_rejected"] = True
            row["negative_controls"] = controls
        except (ValueError, SyntaxError) as error:
            row["structural_rejection"] = type(error).__name__ + ": " + str(error)
        (destination / "RESULT.json").write_bytes(canonical(row) + b"\n")
        rows.append(row)
        requests.append(
            {
                "ordinal": ordinal,
                "source_id": row["source_id"],
                "prompt": context["prompt"],
                "prompt_sha256": context["prompt_sha256"],
                "target": payload.decode() if row["structural_roundtrip"] else None,
                "v1_static_context_closed": row["v1_static_context_closed"],
                "structural_roundtrip": row["structural_roundtrip"],
                "visible_action_roundtrip": row["visible_action_roundtrip"],
            }
        )
        print(
            json.dumps({k: v for k, v in row.items() if k != "static_blockers"}),
            flush=True,
        )
    result = {
        "schema": "hepta.e5-source-action-target-readout.v1",
        "python": platform.python_version(),
        "source_freeze_sha256": sha(args.freeze.read_bytes()),
        "source_sha256": freeze["source_sha256"],
        "results": rows,
        "wall_seconds": time.monotonic() - started,
        "self_cpu_seconds": time.process_time() - cpu,
        "generation_calls": 0,
        "training_updates": 0,
        "native_replays": 0,
        "input_selection_changed_after_freeze": False,
    }
    result_raw = canonical(result) + b"\n"
    (args.output / "RESULT.json").write_bytes(result_raw)
    request = {
        "schema": "hepta.e5-codec-tokenizer-request.v1",
        "source_freeze_sha256": sha(args.freeze.read_bytes()),
        "target_readout_sha256": sha(result_raw),
        "tokenizer_freeze_sha256": freeze["tokenizer_freeze_sha256"],
        "records": requests,
    }
    (args.output / "TOKENIZER_REQUEST.json").write_bytes(canonical(request) + b"\n")


if __name__ == "__main__":
    main()
