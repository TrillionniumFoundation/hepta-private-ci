"""Inventory unallocated source identities using metadata only; allocate nothing."""

import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import resource
import time

from ...next_20261025.h2_sources import metadata
from ...next_20261025.sources import FILES as QFILES
from ...next_20261025.xnist_sources import FILES as XFILES
from ..sources import PREVIOUS, WORDS, previous_allocations


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def inventory(cache, audio_manifest, advance_allocation):
    started, cpu = time.perf_counter_ns(), time.process_time_ns()
    cache, audio_manifest, advance_allocation = Path(cache), Path(audio_manifest), Path(advance_allocation)
    prior = previous_allocations()
    advance = json.loads(advance_allocation.read_text())
    if advance["previous_allocation_sha256"] != PREVIOUS or sha(audio_manifest) != advance["audio_manifest_sha256"]:
        raise ValueError("Inventory must bind the exact existing source ledgers and complete speech manifest")
    inputs = {str(advance_allocation.resolve()): sha(advance_allocation), str(audio_manifest.resolve()): sha(audio_manifest),
              str(Path(__file__).resolve()): sha(__file__)}
    excluded = set()
    metadata_rows = {}
    for name in ("qmnist-train-labels-idx2-int.gz", "qmnist-test-labels-idx2-int.gz"):
        path = cache / name
        if sha(path) != QFILES[name]:
            raise ValueError("Official metadata identity differs")
        inputs[str(path.resolve())] = QFILES[name]
        count = 0
        for _, row in metadata(path):
            excluded.add(row[2]); count += 1
        metadata_rows[name] = count
    all_qmnist_writers = len(excluded)
    for name in ("XNIST_QUALIFICATION_ALLOCATION.json", "ACTION_VALUE_ALLOCATION.json"):
        excluded.update(prior[name]["pair_writer_ids"])
    for role in prior["NATIVE_H2_ALLOCATION.json"]["roles"].values():
        excluded.update(role["pair_writer_ids"])
    for role in prior["SOURCE_ALLOCATION.json"]["roles"].values():
        excluded.update(role["pair_writer_ids"])
    excluded.update(prior["SOURCE_ALLOCATION.json"]["reserved_writer_ids"])
    for role in advance["roles"].values():
        excluded.update(role.get("pair_writer_ids", []))
    path = cache / "xnist-labels-idx2-int.xz"
    if sha(path) != XFILES[path.name]:
        raise ValueError("Official XNIST metadata identity differs")
    inputs[str(path.resolve())] = XFILES[path.name]
    groups, all_unallocated, count = defaultdict(list), set(), 0
    for index, row in metadata(path):
        count += 1
        if row[2] not in excluded:
            all_unallocated.add(row[2])
            if row[0] <= 9 and row[6] == 0:
                groups[row[2]].append({"index": index, "label": row[0], "nist_digit": row[5]})
    metadata_rows[path.name] = count
    histogram = Counter(len(groups[writer]) for writer in all_unallocated)
    small = {str(writer): rows for writer, rows in sorted(groups.items()) if len(rows) in (2, 3)}
    old_audio = [row for rows in prior["media/AUDIO_SOURCE_ALLOCATION.json"]["roles"].values() for row in rows]
    old_audio.extend(prior["media/EVENT_QUALIFICATION_SOURCES.json"]["recordings"])
    old_audio.extend(prior["media/ENSEMBLE_QUALIFICATION_SOURCES_V3.json"]["recordings"])
    current = [row for role in advance["roles"].values()
               for row in role.get("audio_rows_by_source_digit", role.get("recordings", []))]
    used_speakers = {row["speaker"] for row in old_audio + current}
    used_sha = {row["sha256"] for row in old_audio + current}
    manifest = json.loads(audio_manifest.read_text())
    multiplicity = Counter(row["sha256"] for row in manifest["files"])
    all_speakers, usable = set(), defaultdict(list)
    for row in manifest["files"]:
        path = Path(row["path"])
        if path.suffix != ".wav" or path.parts[0] not in WORDS:
            continue
        speaker = path.stem.split("_nohash_")[0]
        all_speakers.add(speaker)
        if speaker not in used_speakers and row["sha256"] not in used_sha and multiplicity[row["sha256"]] == 1:
            usable[speaker].append(row)
    unassigned = all_speakers - used_speakers
    declared = advance["remaining_new_speech_speakers"]
    if len(usable) != declared:
        raise ValueError("Fresh inventory disagrees with existing declaration of usable unused speakers")
    return {"schema": "hepta.advance.metadata-only-unallocated-inventory.v1", "recorded_unix_ns": time.time_ns(),
            "source_identity_sha256": inputs, "previous_source_allocation_sha256": PREVIOUS,
            "metadata_rows_read": metadata_rows,
            "writer_exclusion": "All QMNIST train/test writers, every prior allocated or reserved writer, and all advance allocated writers",
            "all_qmnist_writer_count": all_qmnist_writers, "total_excluded_writer_count": len(excluded),
            "remaining_xnist_writer_count_any_metadata": len(all_unallocated),
            "eligible_digit_rule": "Official label <=9 and duplicate marker column6 ==0, identical to existing advance allocator",
            "remaining_writer_count_by_eligible_digit_count": {str(k): v for k, v in sorted(histogram.items())},
            "remaining_two_digit_writers": histogram[2], "remaining_three_digit_writers": histogram[3],
            "remaining_at_least_four_digit_writers": sum(value for size, value in histogram.items() if size >= 4),
            "two_or_three_digit_metadata_candidates": small,
            "small_writer_pixel_identity_exclusions_verified": False,
            "small_writer_scope": "Metadata availability upper bound; no pixels checked and no cohort or role allocated",
            "speech_manifest_digit_speakers": len(all_speakers), "already_used_speech_speakers": len(used_speakers),
            "completely_unassigned_speech_speakers": len(unassigned),
            "unassigned_speakers_with_unique_eligible_WAV_identity": len(usable),
            "unassigned_without_unique_eligible_WAV_identity": len(unassigned - set(usable)),
            "remaining_eligible_speech_recordings": sum(len(rows) for rows in usable.values()),
            "existing_declared_remaining_speakers": declared,
            "unassigned_speaker_identity_set_sha256": hashlib.sha256("\n".join(sorted(unassigned)).encode()).hexdigest(),
            "no_current_outcomes_read": True, "no_allocation_modified": True,
            "pixels_audio_models_opened": False,
            "wall_ns": time.perf_counter_ns() - started, "parent_cpu_ns": time.process_time_ns() - cpu,
            "peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("cache", "audio-manifest", "advance-allocation", "output"):
        parser.add_argument("--" + name, required=True, type=Path)
    args = parser.parse_args()
    result = inventory(args.cache, args.audio_manifest, args.advance_allocation)
    with args.output.open("x") as stream:
        json.dump(result, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps({key: result[key] for key in ("remaining_two_digit_writers", "remaining_three_digit_writers",
        "remaining_at_least_four_digit_writers", "completely_unassigned_speech_speakers",
        "unassigned_speakers_with_unique_eligible_WAV_identity", "wall_ns", "peak_rss_bytes")}))


if __name__ == "__main__":
    main()
