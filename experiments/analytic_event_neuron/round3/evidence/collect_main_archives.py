"""Package already completed and independently reviewed scopes, without rerunning them."""

import argparse
import hashlib
import json
from pathlib import Path

from .package_evidence import descriptor, sha


def collect(run_dir, repo, output, only_seed=None):
    root, repo, output = Path(run_dir), Path(repo), Path(output)
    index = json.loads((root / "main/RUN_INDEX.json").read_text())
    previous = json.loads(output.read_text()) if output.exists() else []
    known = {item["name"]: item for item in previous}
    destination = repo / "experiments/analytic_event_neuron/round3/evidence/confirmation"
    destination.mkdir(parents=True, exist_ok=True)
    added = []
    for entry in index["scopes"]:
        if only_seed is not None and entry["seed"] != only_seed:
            continue
        name = "MAIN_" + entry["scope"]
        if name in known:
            if known[name]["sha256"] != entry["archive_receipt"]["sha256"]:
                raise ValueError("An already registered archive changed")
            continue
        review_path = root / "independent_main_review" / (entry["scope"] + ".json")
        if not review_path.exists():
            continue
        review = json.loads(review_path.read_text())
        source = root / entry["archive"]
        expected = entry["archive_receipt"]
        if not entry["audit_passed"] or not review["passed"]:
            raise ValueError("Cannot publish an unreviewed scope as reviewed")
        if sha(source) != expected["sha256"] or source.stat().st_size != expected["compressed_bytes"]:
            raise ValueError("Changed completed archive")
        if review["archive_sha256"] != expected["sha256"]:
            raise ValueError("Independent review is bound to different archive bytes")
        if review["analysis_sha256"] != entry["analysis_sha256"]:
            raise ValueError("Independent review is bound to different analysis bytes")
        # The independent review verifies the complete member hash map, including
        # the manifest itself. Reuse that bound count rather than decompressing
        # tens of thousands of already checked files merely to count them again.
        if review["archive_members"] != expected["file_count"]:
            raise ValueError("Frozen audit and independent archive inventory differ")
        data_members = review["archive_members"] - 1
        parts, combined = [], hashlib.sha256()
        with source.open("rb") as stream:
            while block := stream.read(8 * 1024 * 1024):
                target = destination / (name + f".tar.gz.part{len(parts):03d}")
                wanted = hashlib.sha256(block).hexdigest()
                if target.exists():
                    if target.stat().st_size != len(block) or sha(target) != wanted:
                        raise FileExistsError("Refusing to replace a different archive part")
                else:
                    with target.open("xb") as sink:
                        sink.write(block)
                parts.append(descriptor(target, repo))
                combined.update(block)
        if combined.hexdigest() != expected["sha256"]:
            raise ValueError("Byte partitions differ from the original archive")
        item = {
            "name": name, "parts": parts, "bytes": source.stat().st_size,
            "sha256": expected["sha256"],
            "restore_root": "run/main/unpacked/" + entry["scope"],
            "member_manifest": "ARCHIVE_MANIFEST.json", "data_members": data_members,
            "all_member_hashes_verified": True,
            "independent_review_sha256": sha(review_path),
            "scientific_data_regenerated": False,
        }
        previous.append(item)
        output.write_text(json.dumps(previous, sort_keys=True, indent=2) + "\n")
        added.append(name)
    return {"archives_registered": len(previous), "added": added,
            "scientific_data_regenerated": False}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ("run-dir", "repo", "output"):
        parser.add_argument("--" + key, required=True, type=Path)
    parser.add_argument("--only-seed", type=int)
    args = parser.parse_args()
    print(json.dumps(collect(args.run_dir, args.repo, args.output, args.only_seed)))
