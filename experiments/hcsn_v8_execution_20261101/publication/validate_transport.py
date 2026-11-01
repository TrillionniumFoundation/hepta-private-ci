"""Restore actual packaged evidence, compare original bytes, and reject damage."""

import argparse
import json
from pathlib import Path
import shutil
import tempfile

from .transport import checked_path, digest, restore


def run(root, manifest_path, report_path):
    root = root.resolve()
    manifest_path = manifest_path.resolve()
    manifest = json.loads(manifest_path.read_text())
    source_path = Path(__file__).with_name("transport.py")
    source_before = digest(source_path)
    base = Path(tempfile.mkdtemp(prefix="hcsn-v8-transport-verify-", dir="/tmp"))
    target = base / "restored"
    restored = restore(manifest_path, target)
    files = []
    for entry in manifest["files"]:
        original = checked_path(root, entry["path"])
        copy = checked_path(target, entry["path"])
        identical = True
        with original.open("rb") as first, copy.open("rb") as second:
            while True:
                left, right = first.read(1048576), second.read(1048576)
                if left != right:
                    identical = False
                    break
                if not left:
                    break
        files.append({"path": entry["path"], "bytes": original.stat().st_size,
                      "original_sha256": digest(original), "restored_sha256": digest(copy),
                      "byte_by_byte_identical": identical,
                      "original_unchanged": digest(original) == entry["sha256"]})
    reused = restore(manifest_path, target)
    checks = {"all_original_bytes_restored": all(f["byte_by_byte_identical"] for f in files),
              "all_originals_unchanged": all(f["original_unchanged"] for f in files),
              "all_existing_identical_files_reused": reused["identical_existing_files"] == len(files)}
    distinct_parts = {p["path"]: p for e in manifest["files"] for p in e["parts"]}
    checks["all_parts_below_512000_bytes"] = all(p["bytes"] < 512000 for p in distinct_parts.values())
    checks["all_gzip_mtime_zero"] = all(
        int.from_bytes((manifest_path.parent / name).read_bytes()[4:8], "little") == 0
        for name in distinct_parts)
    negatives = []

    conflict = base / "conflict"
    conflict_file = checked_path(conflict, manifest["files"][0]["path"])
    conflict_file.parent.mkdir(parents=True)
    conflict_file.write_bytes(b"preexisting bytes must survive")
    try:
        restore(manifest_path, conflict)
        checks["conflicting_existing_file_refused"] = False
    except FileExistsError as error:
        checks["conflicting_existing_file_refused"] = conflict_file.read_bytes() == b"preexisting bytes must survive"
        negatives.append({"case": "conflict", "exception": type(error).__name__, "reason": str(error)})

    linked, link_target = base / "linked", base / "link-target"
    linked.mkdir()
    link_target.mkdir()
    (linked / manifest["scope"].split("/")[0]).symlink_to(link_target, target_is_directory=True)
    try:
        restore(manifest_path, linked)
        checks["symlink_ancestor_refused"] = False
    except ValueError as error:
        checks["symlink_ancestor_refused"] = not list(link_target.rglob("*"))
        negatives.append({"case": "symlink", "exception": type(error).__name__, "reason": str(error)})

    traversal = base / "traversal-manifest.json"
    damaged = json.loads(manifest_path.read_text())
    damaged["files"][0]["path"] = "../escape"
    traversal.write_text(json.dumps(damaged))
    try:
        restore(traversal, base / "traversal-output")
        checks["path_traversal_refused"] = False
    except ValueError as error:
        checks["path_traversal_refused"] = not (base / "escape").exists()
        negatives.append({"case": "traversal", "exception": type(error).__name__, "reason": str(error)})

    tampered = base / "tampered"
    tampered.mkdir()
    shutil.copy2(manifest_path, tampered / "MANIFEST.json")
    shutil.copytree(manifest_path.parent / "parts", tampered / "parts")
    first_part = tampered / next(iter(distinct_parts))
    with first_part.open("r+b") as stream:
        first = stream.read(1)
        stream.seek(0)
        stream.write(bytes((first[0] ^ 1,)))
    tampered_output = base / "tampered-output"
    try:
        restore(tampered / "MANIFEST.json", tampered_output)
        checks["part_tamper_refused_before_original_write"] = False
    except ValueError as error:
        checks["part_tamper_refused_before_original_write"] = not tampered_output.exists()
        negatives.append({"case": "part_tamper", "exception": type(error).__name__, "reason": str(error)})
    checks["transport_source_unchanged"] = source_before == digest(source_path)
    result = {"schema": "hcsn-v8-transport-validation.v1", "all_passed": all(checks.values()),
              "checks": checks, "files": files, "negative_cases": negatives,
              "fresh_restoration_directory": str(target), "initial_restore": restored,
              "identical_restore": reused, "manifest_sha256": digest(manifest_path),
              "transport_source_sha256": source_before,
              "scope": "Actual byte-preserving package restore and narrow damage/path boundary checks; no scientific reruns"}
    with report_path.open("x") as stream:
        json.dump(result, stream, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps({"all_passed": result["all_passed"], "files": len(files),
                      "restored_directory": str(target), "checks": checks}), flush=True)
    return 0 if result["all_passed"] else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    raise SystemExit(run(args.root, args.manifest, args.report))
