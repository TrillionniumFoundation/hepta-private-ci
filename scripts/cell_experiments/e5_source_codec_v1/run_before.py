"""Read and freeze all visible contexts before constructing any real target."""

import argparse
import copy
import json
import resource
import time
from pathlib import Path

from source_actions import canonical
from source_units import sha
from visible_context import select
from visible_material import load_visible, runtime_path

PREFIX_SHA = "1319a7884200321c108f08bae4c48e9a0e6417b9eb00b34cb1b9d12c0bf38a69"
INDEX_SHA = "6f7ae3e77cbd23a488622a982fc4718f8cbd4bd7049c5d1a9642ee76ea578767"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--materials", type=Path, required=True)
    parser.add_argument("--prefix", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    started, cpu = time.monotonic(), time.process_time()
    assert sha(args.prefix.read_bytes()) == PREFIX_SHA
    index_bytes = (args.materials / "MATERIAL_INDEX.json").read_bytes()
    assert sha(index_bytes) == INDEX_SHA
    index, prefix = json.loads(index_bytes), json.loads(args.prefix.read_bytes())
    assert [r["source_id"] for r in index["materials"]] == [
        r["source_id"] for r in prefix["materials"]
    ]
    results = []
    source = {
        p.name: sha(p.read_bytes()) for p in sorted(Path(__file__).parent.glob("*.py"))
    }
    for ordinal, row in enumerate(index["materials"]):
        stamp = time.monotonic()
        raw = (args.materials / row["path"]).read_bytes()
        assert sha(raw) == row["sha256"] and len(raw) == row["bytes"]
        material = json.loads(raw)
        destination = args.output / f"{ordinal:02d}"
        destination.mkdir()
        try:
            visible = load_visible(args.materials, material)
            poisoned = copy.deepcopy(material)
            poisoned["runtime_patches"] = "FORBIDDEN_AFTER_CHANNEL"
            poisoned["existing_codec"] = "FORBIDDEN_CHANGED_NODE_CHANNEL"
            for binding in poisoned["snapshots"]["after"]:
                if runtime_path(binding["path"], material["runtime_roots"]):
                    binding["sha256"] = "0" * 64
            assert load_visible(args.materials, poisoned) == visible
            context = select(visible)
            (destination / "VISIBLE_INPUT_IDENTITY.json").write_bytes(
                canonical(visible["identity"]) + b"\n"
            )
            (destination / "CONTEXT.json").write_bytes(canonical(context) + b"\n")
            (destination / "PROMPT.txt").write_bytes(context["prompt"].encode())
            result = {
                "ordinal": ordinal,
                "source_id": material["source_id"],
                "v1_static_context_closed": context["v1_static_context_closed"],
                "blockers": context["blockers"],
                "unit_count": len(context["units"]),
                "allowed_action_units": len(context["allowed_units"]),
                "selected_case_count": context["selected_case_count"],
                "prompt_bytes": context["prompt_bytes"],
                "prompt_sha256": context["prompt_sha256"],
                "context_identity_sha256": context["context_identity_sha256"],
                "after_runtime_and_patch_poison_invariance": True,
                "wall_seconds": time.monotonic() - stamp,
            }
        except Exception as error:
            result = {
                "ordinal": ordinal,
                "source_id": material["source_id"],
                "v1_static_context_closed": False,
                "error": type(error).__name__ + ": " + str(error),
                "wall_seconds": time.monotonic() - stamp,
            }
        (destination / "RESULT.json").write_bytes(canonical(result) + b"\n")
        results.append(result)
        print(json.dumps(result), flush=True)
    final = {
        "schema": "hepta.e5-before-only-context-readout.v1",
        "prefix_sha256": PREFIX_SHA,
        "material_index_sha256": INDEX_SHA,
        "source_sha256": source,
        "results": results,
        "wall_seconds": time.monotonic() - started,
        "self_cpu_seconds": time.process_time() - cpu,
        "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "after_runtime_blobs_read": 0,
        "model_calls": 0,
        "native_replays": 0,
        "training_updates": 0,
        "training_execution_admitted": False,
    }
    (args.output / "RESULT.json").write_bytes(canonical(final) + b"\n")


if __name__ == "__main__":
    main()
