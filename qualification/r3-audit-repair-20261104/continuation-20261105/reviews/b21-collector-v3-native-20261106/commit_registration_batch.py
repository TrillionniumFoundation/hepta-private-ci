#!/usr/bin/env python3
"""Durably preserve actual API responses from lossless templates and local bodies.

The code-mode caller checks every actual full GET against the exact local body,
and checks that substituting the body back into each template exactly reproduces
its serialized original tool return. This helper preserves that representation;
it does not claim an original HTTP wire encoding.
"""
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def identity(data):
    return {"bytes": len(data), "git_blob": hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest(),
            "sha256": hashlib.sha256(data).hexdigest()}


def preserve(path, data):
    if path.exists():
        assert path.read_bytes() == data, f"Immutable original differs: {path.name}"
    else:
        path.write_bytes(data)


def main(batch):
    plan = json.loads((ROOT / "registration-plan.json").read_bytes())
    by_sha = {}
    for row in plan["files"]:
        by_sha.setdefault(row["git_blob"], row)
    raw_index = []
    for receipt in batch["receipts"]:
        raw = receipt["template"]
        if "payload_git_blob" in receipt:
            row = by_sha[receipt["payload_git_blob"]]
            b = Path(row["local_path"]).read_bytes()
            assert identity(b) == {key: row[key] for key in ("bytes", "git_blob", "sha256")}
            escaped = json.dumps(b.decode("utf-8"), ensure_ascii=False)[1:-1]
            assert raw.count(receipt["marker"]) == receipt["occurrences"]
            raw = raw.replace(receipt["marker"], escaped)
            result = json.loads(raw)
            assert result["isError"] is False
            assert result["structuredContent"]["content"] == b.decode("utf-8")
        data = raw.encode("utf-8")
        path = ROOT / "registration-raw" / receipt["filename"]
        preserve(path, data)
        raw_index.append({"path": "registration-raw/" + path.name, **identity(data),
                          "losslessly_reconstructed_serialized_actual_tool_return": True})
    raw_recipe = (json.dumps(batch, ensure_ascii=False, indent=2) + "\n").encode()
    name = f'batch-{batch["batch_index"]:04d}.json'
    preserve(ROOT / "registration-recipes" / name, raw_recipe)
    progress_path = ROOT / "registration-progress.actual.json"
    progress = json.loads(progress_path.read_bytes()) if progress_path.exists() else {
        "schema": "b21-v3-native-registration-progress-v1", "next_index": 0, "completed": [], "raw_tool_returns": [], "batches": []}
    assert progress["next_index"] == batch["start_index"]
    assert len(batch["completed"]) == batch["end_index"] - batch["start_index"]
    previous = {row["git_blob"] for row in progress["completed"]}
    assert not previous.intersection(row["git_blob"] for row in batch["completed"])
    progress["completed"].extend(batch["completed"])
    progress["raw_tool_returns"].extend(raw_index)
    progress["batches"].append({"recipe_path": "registration-recipes/" + name, **identity(raw_recipe)})
    progress["next_index"] = batch["end_index"]
    temp = progress_path.with_suffix(".tmp")
    temp.write_text(json.dumps(progress, ensure_ascii=False, indent=2) + "\n")
    temp.replace(progress_path)
    print(json.dumps({"next_index": progress["next_index"], "completed_unique_payloads": len(progress["completed"]),
                      "raw_tool_returns": len(progress["raw_tool_returns"]),
                      "receipt_templates_equal": [r["template"] for r in batch["receipts"]]}, ensure_ascii=False))


if __name__ == "__main__":
    main(json.loads("".join(sys.argv[1:])))
