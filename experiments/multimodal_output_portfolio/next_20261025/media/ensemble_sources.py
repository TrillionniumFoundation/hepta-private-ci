"""Register an untouched official-test cohort without reading audio or outcomes."""

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import time


WORDS = ("zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine")
SALT = "hepta-next-event-ensemble-20261026-v3"


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("sources", "allocation", "previous-qualification", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError("Never replace a registered source cohort")
    original = json.loads(args.allocation.read_text())
    previous = json.loads(args.previous_qualification.read_text())
    manifest = json.loads((args.sources / "manifest.json").read_text())
    test = set((args.sources / "testing_list.txt").read_text().splitlines())
    validation = set((args.sources / "validation_list.txt").read_text().splitlines())
    excluded = {row["speaker"] for rows in original["roles"].values() for row in rows}
    excluded |= {row["speaker"] for row in previous["recordings"]}
    excluded |= {Path(path).stem.split("_nohash_")[0] for path in validation}
    rows = []
    for row in manifest["files"]:
        path = Path(row["path"])
        if row["path"] not in test or path.suffix != ".wav" or path.parts[0] not in WORDS:
            continue
        speaker = path.stem.split("_nohash_")[0]
        if speaker not in excluded:
            rows.append({**row, "label": WORDS.index(path.parts[0]), "speaker": speaker})
    rank = lambda row: hashlib.sha256((SALT + ":" + row["path"]).encode()).digest()
    selected = [row for digit in range(10)
                for row in sorted((r for r in rows if r["label"] == digit), key=rank)[:30]]
    if len(selected) != 300 or any(count != 30 for count in Counter(row["label"] for row in selected).values()):
        raise ValueError("Insufficient preregistered class-balanced cohort")
    if excluded & {row["speaker"] for row in selected}:
        raise ValueError("Previously used or reserved speaker entered the new cohort")
    result = {"schema": "hepta.next.event-ensemble-sources.v3", "registered_unix_ns": time.time_ns(),
              "salt": SALT, "official_split": "test", "recordings": selected,
              "speakers": sorted({row["speaker"] for row in selected}),
              "eligible_recordings": len(rows), "eligible_speakers": len({row["speaker"] for row in rows}),
              "excluded_speakers": sorted(excluded), "overlap_with_excluded_speakers": 0,
              "selection": "Thirty recordings per digit by fixed metadata hash; no audio inspection or performance filtering",
              "reserved_media_joint_speakers_excluded": len(original["media_speakers"] + original["joint_speakers"]),
              "source_url": manifest["url"], "whole_archive_sha256": manifest["whole_archive_sha256"],
              "source_manifest_sha256": digest(args.sources / "manifest.json"),
              "previous_allocation_sha256": digest(args.allocation),
              "previous_qualification_allocation_sha256": digest(args.previous_qualification),
              "allocator_sha256": digest(__file__), "audio_opened": False,
              "pretrained_asr_training_overlap_known": False,
              "after_outcomes": "No change to ensemble, observer, parser, threshold or cohort using these outcomes"}
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"allocation_sha256": digest(args.output), "recordings": len(selected),
                      "speakers": len(result["speakers"]), "eligible_speakers": result["eligible_speakers"]}))


if __name__ == "__main__":
    main()
