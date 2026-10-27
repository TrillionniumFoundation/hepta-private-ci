"""Bounded-space actual write, fsync, reopen and hash of every archive member."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import tarfile
import time


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def run(archive, index, output):
    output.mkdir(parents=True, exist_ok=False)
    shutil.copyfile(Path(__file__), output / "executed-source.py")
    manifest = json.loads(index.read_text())
    expected = {entry["path"]: entry for entry in manifest["files"]}
    if len(expected) != manifest["file_count"]:
        raise ValueError("Duplicate members in the original inventory")
    archive_hash, index_hash = sha(archive), sha(index)
    temporary = None
    count = byte_count = maximum = 0
    seen = set()
    started = time.perf_counter_ns()
    with tarfile.open(archive, "r:gz") as source:
        for member in source:
            if member.name == "ARTIFACT_INDEX.json":
                if source.extractfile(member).read() != index.read_bytes():
                    raise ValueError("Internal and external inventories disagree")
                continue
            if not member.isfile() or member.name in seen or member.name not in expected:
                raise ValueError("Unregistered, duplicate, or non-file archive member")
            # A never-reused name also detects shared-filesystem ABA recovery
            # rather than trusting that an unlinked pathname stays absent.
            temporary = output / f"member-{count:06}-{expected[member.name]['sha256'][:16]}.bin"
            with source.extractfile(member) as original, temporary.open("xb") as restored:
                shutil.copyfileobj(original, restored, length=1024 * 1024)
                restored.flush()
                os.fsync(restored.fileno())
            # This opens the newly written filesystem file, not the tar stream.
            actual_hash, actual_size = sha(temporary), temporary.stat().st_size
            if actual_hash != expected[member.name]["sha256"] or actual_size != expected[member.name]["bytes"]:
                failure = {"member": member.name, "restored_path": str(temporary),
                    "expected": expected[member.name], "actual_sha256": actual_hash, "actual_bytes": actual_size}
                (output / "RESTORE_FAILURE.json").write_text(json.dumps(failure, indent=2) + "\n")
                raise ValueError("Actual filesystem restoration differs: " + member.name)
            temporary.unlink()
            count += 1
            byte_count += actual_size
            maximum = max(maximum, actual_size)
            seen.add(member.name)
            if count % 5000 == 0:
                print(f"actual disk member restoration {count}/{len(expected)}", flush=True)
    if seen != set(expected) or byte_count != manifest["total_uncompressed_file_bytes"] or sha(archive) != archive_hash:
        raise ValueError("Archive changed or restoration was incomplete")
    result = {"passed": True, "archive": str(archive), "archive_sha256": archive_hash,
        "index": str(index), "index_sha256": index_hash, "actual_members_written_fsynced_reopened_and_hashed": count,
        "actual_restored_bytes": byte_count, "maximum_simultaneous_restored_file_bytes": maximum,
        "every_restored_member_deleted_after_hash_check": not any(output.glob("member-*.bin")),
        "unique_per_member_filesystem_names": True,
        "archive_contents_unchanged": True, "uses_tar_stream_hash_as_substitute_for_disk_readback": False,
        "source_sha256": sha(output / "executed-source.py"), "wall_seconds": (time.perf_counter_ns() - started) / 1e9}
    with (output / "RESTORE_RECEIPT.json").open("x") as stream:
        json.dump(result, stream, sort_keys=True, indent=2)
        stream.write("\n")
    print(json.dumps(result), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    for name in ("archive", "index", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    run(args.archive, args.index, args.output)
