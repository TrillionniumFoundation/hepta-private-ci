"""Preserve the completed language experiment, including failed development.

Copies exact bytes into a new evidence directory. Large and secondary files are
content-addressed in deterministic tar+xz chunks. The existing selected-model
transport is indexed, not duplicated. No experiment, training or inference runs.
"""

import argparse
import io
import json
import lzma
from pathlib import Path
import tarfile

from audit_addressing import RUNS, audit, read, require, sha
from reconstruct_addressing import below, safe_root


PROJECT = Path(__file__).resolve().parent
REPOSITORY = PROJECT.parents[1]
PART_BYTES = 400000
MAX_BLOB = 512000
SOURCE_NAMES = (*RUNS, "v7-addressing-held-01", "v7-independent-eval-author")


def write_new(path, raw):
    path = safe_root(path)
    require(len(raw) <= MAX_BLOB, "repository artifact exceeds blob bound: " + str(path))
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(raw)


def binding(path, raw):
    return {"path": path, "bytes": len(raw), "sha256": sha(raw)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=PROJECT / "evidence/addressing")
    args = parser.parse_args()
    base, output = safe_root(args.source_root), safe_root(args.output)
    require(not output.exists(), "archive output is create-only and must not exist")
    cost, model_index, review = audit(base, REPOSITORY)
    originals, excluded = {}, []
    for name in SOURCE_NAMES:
        root = safe_root(base / name)
        for path in sorted(root.rglob("*")):
            require(not path.is_symlink(), "symlinked source artifact")
            if path.is_dir():
                continue
            require(not path.is_symlink() and path.is_file(), "non-regular source artifact")
            relative = path.relative_to(base).as_posix()
            if "__pycache__" in path.parts or path.suffix == ".pyc":
                excluded.append(relative)
                continue
            originals[relative] = safe_root(path).read_bytes()
    for name in ("addressing-FREEZE.json", "addressing-HELD_LOCK.json"):
        originals["locks/" + name] = (PROJECT / "evidence" / name).read_bytes()
    originals["evaluator/address_eval.py"] = (PROJECT / "address_eval.py").read_bytes()
    originals["development-handoff/HANDOFF.json"] = (PROJECT / "addressing/HANDOFF.json").read_bytes()

    transport_root = PROJECT / "fixtures/address-model"
    transport = read(transport_root / "PARTS.json")
    selected_parts = []
    selected_weights = []
    for part in transport["parts"]:
        path = below(transport_root, part["path"])
        raw = path.read_bytes()
        require(len(raw) == part["bytes"] and sha(raw) == part["sha256"], "selected model part identity differs")
        selected_parts.append(binding(path.relative_to(REPOSITORY).as_posix(), raw))
        selected_weights.append(raw)
    require(sha(b"".join(selected_weights)) == transport["weights_sha256"], "selected weights identity differs")
    manifest_path = transport_root / "manifest.json"
    manifest_raw = manifest_path.read_bytes()
    require(sha(manifest_raw) == transport["manifest_sha256"], "selected manifest identity differs")
    external = {
        "selected-weights": {"bytes": transport["weights_bytes"], "sha256": transport["weights_sha256"], "parts": selected_parts},
        "selected-manifest": {"bytes": len(manifest_raw), "sha256": sha(manifest_raw),
                              "parts": [binding(manifest_path.relative_to(REPOSITORY).as_posix(), manifest_raw)]},
    }
    external_by_sha = {asset["sha256"]: name for name, asset in external.items()}

    core = {}
    for name in ("TRAINING.json", "DESIGN.json", "CALIBRATION.json", "SELECTION_LOCK.json"):
        core["v7-addressing-formal-01/" + name] = "formal/" + name
    for path in sorted((base / "v7-addressing-held-01").glob("*.json")):
        core["v7-addressing-held-01/" + path.name] = "held/" + path.name
    for name in ("calibration.json", "held.json", "PROTOCOL.json", "VALIDATION.json"):
        core["v7-independent-eval-author/" + name] = "author/" + name
    for name in ("addressing-FREEZE.json", "addressing-HELD_LOCK.json"):
        core["locks/" + name] = "locks/" + name
    direct_by_sha = {sha(originals[name]): target for name, target in core.items()}
    objects, entries = {}, []
    for name, raw in sorted(originals.items()):
        digest = sha(raw)
        if name in core:
            storage = {"kind": "direct", "path": core[name]}
        elif digest in direct_by_sha:
            storage = {"kind": "direct", "path": direct_by_sha[digest]}
        elif digest in external_by_sha:
            storage = {"kind": "external", "asset": external_by_sha[digest]}
        else:
            objects.setdefault(digest, raw)
            storage = {"kind": "object", "sha256": digest}
        entries.append({**binding(name, raw), "storage": storage})
    tar_buffer = io.BytesIO()
    with tarfile.open(fileobj=tar_buffer, mode="w", format=tarfile.USTAR_FORMAT) as stream:
        for digest, raw in sorted(objects.items()):
            member = tarfile.TarInfo("objects/" + digest)
            member.size, member.mode, member.mtime = len(raw), 0o644, 0
            member.uid, member.gid, member.uname, member.gname = 0, 0, "", ""
            stream.addfile(member, io.BytesIO(raw))
    tar_raw = tar_buffer.getvalue()
    packed = lzma.compress(tar_raw, format=lzma.FORMAT_XZ, check=lzma.CHECK_CRC64, preset=6)
    parts = []
    artifacts = []
    output.mkdir(parents=True, exist_ok=False)
    for name, target in sorted(core.items()):
        raw = originals[name]
        write_new(below(output, target), raw)
        artifacts.append(binding(target, raw))
    for offset in range(0, len(packed), PART_BYTES):
        name = f"archive/content.tar.xz.part-{offset // PART_BYTES:03}"
        raw = packed[offset:offset + PART_BYTES]
        write_new(below(output, name), raw)
        parts.append(binding(name, raw))
    for name, value in (("COST_SUMMARY.json", cost), ("MODEL_INDEX.json", model_index), ("REVIEW.json", review)):
        raw = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False).encode() + b"\n"
        write_new(below(output, name), raw)
        artifacts.append(binding(name, raw))
    tools = []
    for name in ("audit_addressing.py", "archive_addressing.py", "reconstruct_addressing.py"):
        path = PROJECT / name
        tools.append(binding(path.relative_to(REPOSITORY).as_posix(), path.read_bytes()))
    index = {
        "schema": "hepta.memory.v7.addressing-evidence-index.v1", "source_root": str(base),
        "original_file_count": len(entries), "original_bytes": sum(len(raw) for raw in originals.values()),
        "original_files": entries, "artifacts": artifacts, "tools": tools, "external_assets": external,
        "archive": {"format": "ustar+xz", "preset": 6, "check": "crc64", "bytes": len(packed), "sha256": sha(packed),
                    "tar_bytes": len(tar_raw), "tar_sha256": sha(tar_raw), "parts": parts},
        "objects": {digest: {"bytes": len(raw)} for digest, raw in sorted(objects.items())},
        "excluded_generated_bytecode": excluded, "base_encoder_copied": False,
        "source_labels_or_results_modified": False, "model_executions": 0,
        "reconstruction": "Run python -B qualification/memory-cell-v7/reconstruct_addressing.py to verify only; add --output NEW_DIRECTORY to reconstruct exact original paths and bytes.",
        "trust_anchor": "Review the repository commit and INDEX.sha256 together. A digest stored beside its data is integrity evidence, not independent authority.",
    }
    raw_index = json.dumps(index, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False).encode() + b"\n"
    write_new(output / "INDEX.json", raw_index)
    write_new(output / "INDEX.sha256", (sha(raw_index) + "\n").encode())
    files = [path for path in output.rglob("*") if path.is_file()]
    print(json.dumps({"output": str(output), "files": len(files), "bytes": sum(path.stat().st_size for path in files),
                      "largest_blob": max(path.stat().st_size for path in files), "archive_bytes": len(packed),
                      "archive_parts": len(parts), "original_file_count": len(entries), "index_sha256": sha(raw_index)}))


if __name__ == "__main__":
    main()
