"""Evict only byte-verified expanded copies of a complete historical archive.

The complete archive and original manifest remain authoritative and unchanged.
No model, source input, active output, summary or repository file is eligible.
"""

import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import tarfile
import time


ARCHIVE_SHA = "0fa928448405e1d65ead9642b7b6db2d79e5eedbc34966b15e069d3f15bb171e"
MANIFEST_SHA = "deb6d182bc8ea117ecc25bab1311a300649eaea8e4202db19f300725a8f81622"
PREFIXES = ("qualification-001/commits", "qualification-001/media",
            "calibration-002/commits", "calibration-002/media",
            "expanded-old-001/calibration/commits", "expanded-old-001/calibration/media",
            "expanded-old-001/validation/commits", "expanded-old-001/validation/media")


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    manifest = Path(str(args.archive) + ".manifest.json")
    if sha(args.archive) != ARCHIVE_SHA or sha(manifest) != MANIFEST_SHA:
        raise ValueError("Complete historical archive or its member identity ledger changed")
    root = Path("/tmp/hepta-ndu-next-native-h2")
    prefixes = tuple(root / name for name in PREFIXES)
    selected = {row["member"]: row for row in json.loads(manifest.read_text())["files"]
                if any(Path(row["original_path"]).is_relative_to(prefix) for prefix in prefixes)}
    if not selected:
        raise ValueError("No explicitly permitted historical expanded members")
    args.output.mkdir(parents=True, exist_ok=False)
    before = os.statvfs(root)
    receipt = {"schema": "hepta.advance.verified-raw-eviction.v1", "started_unix_ns": time.time_ns(),
               "archive": str(args.archive), "archive_sha256": ARCHIVE_SHA,
               "manifest": str(manifest), "manifest_sha256": MANIFEST_SHA,
               "eligible_prefixes": list(PREFIXES), "selected_members": len(selected),
               "execute": args.execute, "actual_free_before": before.f_bfree * before.f_frsize,
               "status": "running", "archive_and_models_unchanged": True}
    (args.output / "STARTED.json").write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    verified, removed, logical, disk_blocks = 0, 0, 0, 0
    with gzip.open(args.output / "members.jsonl.gz", "xt") as log, tarfile.open(args.archive, "r|gz") as archive:
        for member in archive:
            row = selected.get(member.name)
            if row is None:
                continue
            if not member.isfile() or member.size != row["bytes"]:
                raise ValueError("Historical member type/size differs")
            if hashlib.file_digest(archive.extractfile(member), "sha256").hexdigest() != row["sha256"]:
                raise ValueError("Historical archive bytes do not match its member identity ledger")
            verified += 1
            path = Path(row["original_path"])
            if not path.exists():
                continue
            stat = path.lstat()
            if path.is_symlink() or not path.is_file() or stat.st_size != row["bytes"] or sha(path) != row["sha256"]:
                raise ValueError("Expanded copy is unique or changed; preserve it: " + str(path))
            current = path.lstat()
            if (current.st_ino, current.st_size, current.st_mtime_ns) != (stat.st_ino, stat.st_size, stat.st_mtime_ns):
                raise ValueError("Expanded copy changed during byte verification")
            event = {**row, "verified_archive_and_expanded_bytes": True, "removed": args.execute}
            log.write(json.dumps(event, sort_keys=True) + "\n")
            if args.execute:
                path.unlink()
                removed += 1
                logical += stat.st_size
                disk_blocks += stat.st_blocks * 512
            if verified % 10000 == 0:
                log.flush()
                print(json.dumps({"archive_members_verified": verified, "expanded_copies_removed": removed}), flush=True)
    if verified != len(selected):
        raise ValueError("A selected member was absent from the verified archive")
    if args.execute:
        for prefix in prefixes:
            for directory, _, _ in os.walk(prefix, topdown=False):
                try:
                    Path(directory).rmdir()
                except OSError:
                    pass
    after = os.statvfs(root)
    receipt.update(status="completed", completed_unix_ns=time.time_ns(),
                   verified_members=verified, removed_files=removed, logical_bytes=logical,
                   removed_file_allocated_bytes=disk_blocks, actual_free_after=after.f_bfree * after.f_frsize,
                   restoration="Extract each original member to original_path using the unchanged archive manifest",
                   removal_ledger_sha256=sha(args.output / "members.jsonl.gz"))
    (args.output / "RESULT.json").write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    print(json.dumps(receipt), flush=True)


if __name__ == "__main__":
    main()
