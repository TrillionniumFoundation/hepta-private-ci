"""Source-only input freezer. It contains no target, model, training or native runner."""

import argparse
import json
import time
from pathlib import Path

from bounded_material_io import BoundedBlobRoot
from retrieve_once import select_once
from v2_common import POLICY_SHA, canonical, code_identity, require, sha
from v2_legacy import visible_material

INDEX_SHA = "6f7ae3e77cbd23a488622a982fc4718f8cbd4bd7049c5d1a9642ee76ea578767"
PREFIX_SHA = "1319a7884200321c108f08bae4c48e9a0e6417b9eb00b34cb1b9d12c0bf38a69"


def read_json(path, expected_sha, maximum):
    with path.open("rb") as handle:
        raw = handle.read(maximum + 1)
    require(
        len(raw) <= maximum and sha(raw) == expected_sha,
        "trusted input index/record changed",
    )
    return json.loads(raw)


def freeze_all(materials, prefix_path, destination):
    destination.mkdir(parents=True, exist_ok=False)
    index = read_json(materials / "MATERIAL_INDEX.json", INDEX_SHA, 1048576)
    prefix = read_json(prefix_path, PREFIX_SHA, 1048576)
    require(
        len(index["materials"]) == 16
        and [r["source_id"] for r in index["materials"]]
        == [r["source_id"] for r in prefix["materials"]],
        "original sixteen/prefix identity changed",
    )
    original_code = code_identity()
    rows = []
    for ordinal, entry in enumerate(index["materials"]):
        directory = destination / f"{ordinal:02d}"
        directory.mkdir()
        started, cpu = time.monotonic(), time.process_time()
        store = BoundedBlobRoot(materials)
        result = {
            "ordinal": ordinal,
            "source_id": entry["source_id"],
            "token_admission": None,
            "training_execution_admitted": False,
            "model_forward_generation_train_native": 0,
        }
        try:
            material = read_json(materials / entry["path"], entry["sha256"], 2097152)
            require(
                material["source_id"] == entry["source_id"],
                "material source identity changed",
            )
            visible = visible_material.load_visible(store, material)
            loaded_wall, loaded_cpu = (
                time.monotonic() - started,
                time.process_time() - cpu,
            )
            view, receipt = select_once(visible)
            raw_view, raw_receipt = canonical(view) + b"\n", canonical(receipt) + b"\n"
            (directory / "VIEW.json").write_bytes(raw_view)
            (directory / "PREPARATION_RECEIPT.json").write_bytes(raw_receipt)
            (directory / "PROMPT.txt").write_text(view["prompt"])
            result.update(
                status="BYTE_VIEW_FROZEN_TOKENS_UNMEASURED",
                view_digest=view["view_digest"],
                view_file_sha256=sha(raw_view),
                preparation_receipt_sha256=sha(raw_receipt),
                prompt_bytes=len(view["prompt"].encode()),
                native_case_count=len(visible["cases"]),
                loader_wall_seconds=loaded_wall,
                loader_cpu_seconds=loaded_cpu,
            )
        except Exception as error:
            result.update(
                status="SOURCE_REFUSAL", error=type(error).__name__ + ": " + str(error)
            )
        result.update(
            blob_read_bytes=store.total,
            blob_read_count=len(store.reads),
            wall_seconds=time.monotonic() - started,
            cpu_seconds=time.process_time() - cpu,
        )
        (directory / "BLOB_READS.json").write_bytes(canonical(store.reads) + b"\n")
        (directory / "RESULT.json").write_bytes(canonical(result) + b"\n")
        rows.append(result)
        print(json.dumps(result), flush=True)
    require(code_identity() == original_code, "source changed during input freeze")
    receipt = {
        "schema": "hepta.e5.bounded-before-input-freeze.v2",
        "code_sha256": original_code,
        "policy_sha256": POLICY_SHA,
        "material_index_sha256": INDEX_SHA,
        "source_prefix_sha256": PREFIX_SHA,
        "rows": rows,
        "prefixes_1_4_16_training_admitted": {str(n): False for n in (1, 4, 16)},
        "source_64_status": "48 original project materials absent",
        "optimizer_unit_mapping": None,
        "compute_or_verifier_budget": None,
        "independent_B_C": None,
        "tokenizer_measurement": None,
        "new_model_forward_generation_train_native": 0,
        "after_supervision_read": False,
    }
    (destination / "INPUT_FREEZE.json").write_bytes(canonical(receipt) + b"\n")
    return receipt


def main():
    parser = argparse.ArgumentParser()
    for name in ("materials", "prefix", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    freeze_all(args.materials, args.prefix, args.output)


if __name__ == "__main__":
    main()
