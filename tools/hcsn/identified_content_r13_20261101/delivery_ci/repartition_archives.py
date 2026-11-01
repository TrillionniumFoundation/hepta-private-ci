"""Partition existing immutable evidence archives below the repository blob limit."""

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LIMIT = 512_000
PART_BYTES = 480_000


def digest(data):
    return hashlib.sha256(data).hexdigest()


def main():
    changes = []
    removed = []
    added = []
    for name in ["TRAINING_ARCHIVES.json", "EVIDENCE_ARCHIVES.json"]:
        path = ROOT / name
        index = json.loads(path.read_text())
        for record in index["archives"]:
            old_parts = record.get("parts", [])
            if old_parts:
                old_paths = [part["file"] for part in old_parts]
                blocks = [(ROOT / part["file"]).read_bytes() for part in old_parts]
                for part, block in zip(old_parts, blocks, strict=True):
                    if len(block) != part["bytes"] or digest(block) != part["sha256"]:
                        raise ValueError("Existing archive part identity mismatch")
                payload = b"".join(blocks)
            else:
                old_paths = [record["file"]]
                payload = (ROOT / record["file"]).read_bytes()
            if len(payload) != record["bytes"] or digest(payload) != record["sha256"]:
                raise ValueError("Existing immutable archive identity mismatch")
            if all((ROOT / old_path).stat().st_size <= LIMIT for old_path in old_paths):
                continue
            parts = []
            for number, offset in enumerate(range(0, len(payload), PART_BYTES), start=1):
                filename = f"{record['file']}.vol{number:03d}"
                block = payload[offset:offset + PART_BYTES]
                target = ROOT / filename
                if target.exists() and target.read_bytes() != block:
                    raise FileExistsError(f"Refusing different existing bytes: {filename}")
                target.write_bytes(block)
                parts.append({"file": filename, "bytes": len(block), "sha256": digest(block)})
                added.append(filename)
            record["parts"] = parts
            removed.extend(old_paths)
            changes.append({"archive": record["file"], "sha256": record["sha256"],
                            "bytes": len(payload), "previous_paths": old_paths,
                            "replacement_paths": [part["file"] for part in parts]})
        path.write_text(json.dumps(index, indent=2) + "\n")
    report = {"policy_limit_bytes": LIMIT, "part_bytes": PART_BYTES,
              "archive_payloads_and_member_hashes_unchanged": True,
              "prior_commits_preserved": True, "changes": changes,
              "remove_from_git_head_only": removed, "add_to_git": added}
    output = Path(__file__).with_name("REPARTITION.json")
    if changes or not output.exists():
        output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"repartitioned_archives": len(changes), "new_parts": len(added),
                      "removed_head_paths": len(removed)}))


if __name__ == "__main__":
    main()
