"""Register unused writer/speaker groups; open model inputs only after freezing.

Registration reads metadata and pixel identities, never a model or a score.
The final panel is shared by explicitly correlated studies. OOD units are
speakers with every input missing, not extra independent image writers.
"""

import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import time

from ..next_20261025.h2_sources import metadata, pixels
from ..next_20261025.sources import FILES as QFILES, MANIFEST_SHA, _read
from ..next_20261025.xnist_sources import FILES as XFILES


SALT = "hepta-advance-20261026-source-panel-v1"
WORDS = ("zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine")
PREVIOUS = {
    "SOURCE_ALLOCATION.json": "6ad7fef099626d8ea1f4f6c123610016adfeca9aa828765f185f62d92afdb27e",
    "XNIST_QUALIFICATION_ALLOCATION.json": "c997590bb6c1a95a91d1ba469f6a8f1219764422d572b16f77175cd5e252252f",
    "ACTION_VALUE_ALLOCATION.json": "7675debf5142f07d3f4150d8e986b3827e5cf764547d704520895fc8241a474c",
    "NATIVE_H2_ALLOCATION.json": "66aa5e30c26dc72736d8d4af2fac2de53cb9d5aa6fc7b514d56d0b06f5e60b7e",
    "media/AUDIO_SOURCE_ALLOCATION.json": "35862507212b97bc02bc1506070a31863f830e3c9e7747e5f3187ab2e6702fe5",
    "media/EVENT_QUALIFICATION_SOURCES.json": "2c9aa271394402a21dea81a34f6df4fd3afb9e86bd213f9b2dbd1de1ddabba75",
    "media/ENSEMBLE_QUALIFICATION_SOURCES_V3.json": "df08fa48f9627ab8d828d267599b9bcebb59470d020e4f70a7caff9dfaddb67c",
}


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def rank(kind, value):
    return hashlib.sha256(f"{SALT}:{kind}:{value}".encode()).digest()


def previous_allocations():
    root = Path(__file__).resolve().parents[1] / "next_20261025"
    records = {}
    for relative, expected in PREVIOUS.items():
        path = root / relative
        if sha(path) != expected:
            raise ValueError("Previous allocation identity differs: " + relative)
        records[relative] = json.loads(path.read_text())
    return records


def register(cache, old_manifest, audio_root, output):
    cache, audio_root, output = Path(cache), Path(audio_root), Path(output)
    if output.exists() or sha(old_manifest) != MANIFEST_SHA:
        raise ValueError("Never replace a cohort or change the original source ledger")
    prior = previous_allocations()
    for name, expected in {**QFILES, **XFILES}.items():
        if sha(cache / name) != expected:
            raise ValueError("Official source archive changed: " + name)
    raw_q, qtest, qtrain = _read(cache)
    old = json.loads(Path(old_manifest).read_text())
    old_pixels = {v.rsplit(":", 1)[-1] for r in old["roles"].values() for v in r["source_ids"]}
    old_pixels.update(h for role in prior["SOURCE_ALLOCATION.json"]["roles"].values() for h in role["pixel_sha256"])
    q_pixels = {hashlib.sha256(raw_q[i * 784:(i + 1) * 784]).hexdigest() for i in range(60000)}
    old_writers = {row[2] for row in qtest + qtrain}
    old_writers.update(prior["XNIST_QUALIFICATION_ALLOCATION.json"]["pair_writer_ids"])
    old_writers.update(prior["ACTION_VALUE_ALLOCATION.json"]["pair_writer_ids"])
    h2 = prior["NATIVE_H2_ALLOCATION.json"]
    for role in h2["roles"].values():
        old_writers.update(role["pair_writer_ids"])
    groups = defaultdict(list)
    for index, row in metadata(cache / "xnist-labels-idx2-int.xz"):
        if row[2] not in old_writers and row[0] <= 9 and row[6] == 0:
            groups[row[2]].append((index, row))
    writers = sorted((w for w, rows in groups.items() if len(rows) >= 4), key=lambda w: rank("writer", w))
    if len(writers) != h2["remaining_writers"] or len(writers) != 85:
        raise ValueError("Expected the exact 85 previously unused eligible XNIST writers")
    chosen_x = [(i, row) for w in writers for i, row in sorted(groups[w], key=lambda r: rank("digit", r[1][5]))[:4]]
    xbytes = dict(pixels(cache / "xnist-images-idx3-ubyte.xz", {i for i, _ in chosen_x}))
    q_reserved = prior["SOURCE_ALLOCATION.json"]["reserved_writer_ids"]
    if len(q_reserved) != 10:
        raise ValueError("Expected ten untouched QMNIST qualification writers")
    chosen_q = []
    for writer in sorted(q_reserved, key=lambda w: rank("writer", w)):
        candidates = [(i, row) for i, row in enumerate(qtest) if i >= 10000 and row[2] == writer]
        if len(candidates) < 8:
            raise ValueError("Qualification writer has fewer than eight source digits")
        chosen_q.extend(sorted(candidates, key=lambda r: rank("digit", r[1][5]))[:8])
    roles = {}
    for name, dataset, chosen in (("confirmation", "xnist", chosen_x), ("qualification_id", "qmnist", chosen_q)):
        records = []
        for index, row in chosen:
            raw = xbytes[index] if dataset == "xnist" else raw_q[index * 784:(index + 1) * 784]
            digest = hashlib.sha256(raw).hexdigest()
            if digest in old_pixels or (dataset == "xnist" and digest in q_pixels):
                raise ValueError("Selected pixel duplicates an old source census")
            records.append({"dataset": dataset, "index": index, "writer": row[2], "label": row[0],
                            "nist_digit": row[5], "pixel_sha256": digest,
                            "source_id": f"{dataset}:{index}:nist:{row[5]}:writer:{row[2]}:{digest}"})
        roles[name] = {"role": "advance_" + name, "source_records": records,
                       "writer_count": len(set(r["writer"] for r in records)), "pair_count": len(records) // 2,
                       "pair_writer_ids": [r["writer"] for r in records[::2]]}
    previous_x_pixels = set(prior["XNIST_QUALIFICATION_ALLOCATION.json"]["pixel_sha256"])
    previous_x_pixels.update(r["pixel_sha256"] for r in prior["ACTION_VALUE_ALLOCATION.json"]["source_records"])
    previous_x_pixels.update(r["pixel_sha256"] for role in h2["roles"].values() for r in role["source_records"])
    new_hashes = [r["pixel_sha256"] for role in roles.values() for r in role["source_records"]]
    if len(set(new_hashes)) != len(new_hashes) or previous_x_pixels.intersection(new_hashes):
        raise ValueError("New source pixels duplicate another current or previous source")
    manifest = json.loads((audio_root / "manifest.json").read_text())
    old_audio = [r for rows in prior["media/AUDIO_SOURCE_ALLOCATION.json"]["roles"].values() for r in rows]
    old_audio += prior["media/EVENT_QUALIFICATION_SOURCES.json"]["recordings"]
    old_audio += prior["media/ENSEMBLE_QUALIFICATION_SOURCES_V3.json"]["recordings"]
    used_speakers, used_sha = {r["speaker"] for r in old_audio}, {r["sha256"] for r in old_audio}
    multiplicity = Counter(r["sha256"] for r in manifest["files"])
    speech = defaultdict(lambda: defaultdict(list))
    for item in manifest["files"]:
        path = Path(item["path"]); speaker = path.stem.split("_nohash_")[0]
        if speaker in used_speakers or item["sha256"] in used_sha or multiplicity[item["sha256"]] != 1:
            continue
        if path.suffix == ".wav" and path.parts[0] in WORDS:
            speech[speaker][WORDS.index(path.parts[0])].append({**item, "speaker": speaker, "label": WORDS.index(path.parts[0])})
    required = {}
    for role in roles.values():
        for row in role["source_records"]:
            required.setdefault(row["writer"], set()).add(row["label"])
    choices = {w: sorted((s for s, labels in speech.items() if labels.keys() >= needed), key=lambda s: rank("speaker", s))
               for w, needed in required.items()}
    assignment = {}

    def match(writer, visited):
        for speaker in choices[writer]:
            if speaker in visited:
                continue
            visited.add(speaker)
            if speaker not in assignment or match(assignment[speaker], visited):
                assignment[speaker] = writer
                return True
        return False

    for writer in sorted(required, key=lambda w: (len(choices[w]), rank("writer", w))):
        if not match(writer, set()):
            raise ValueError("Cannot obtain one disjoint new speaker per writer")
    mapping = {writer: speaker for speaker, writer in assignment.items()}
    for role in roles.values():
        selected = {w: {digit: min(speech[mapping[w]][digit], key=lambda r: rank("recording", r["path"]))
                        for digit in required[w]} for w in set(role["pair_writer_ids"])}
        role["speaker_by_writer"] = {str(w): mapping[w] for w in selected}
        role["audio_rows_by_source_digit"] = [selected[r["writer"]][r["label"]] for r in role["source_records"]]
        role["cluster_unit"] = "One image writer and one unique matched speech speaker"
    available_ood = sorted(set(speech) - set(assignment), key=lambda s: rank("ood-speaker", s))
    if len(available_ood) < 600:
        raise ValueError("Fewer than 600 unused independent OOD speakers")
    ood = [min((r for rows in speech[s].values() for r in rows), key=lambda r: rank("recording", r["path"]))
           for s in available_ood[:600]]
    roles["qualification_ood"] = {"role": "advance_qualification_ood", "source_group_unit": "speech speaker",
                                   "speaker_count": 600, "recordings": ood,
                                   "all_inputs_missing": True, "waveform_is_source_identity_only_not_model_input": True}
    result = {"schema": "hepta.advance.source-allocation.v1", "registered_unix_ns": time.time_ns(),
              "baseline_commit": "8ec9386fe4c7f277bbeb858d493b88a7847a7865", "salt": SALT,
              "allocator_sha256": sha(__file__), "previous_allocation_sha256": PREVIOUS,
              "archive_sha256": {**QFILES, **XFILES}, "original_mnist_manifest_sha256": MANIFEST_SHA,
              "audio_manifest_sha256": sha(audio_root / "manifest.json"), "audio_source_url": manifest["url"],
              "audio_whole_archive_sha256": manifest["whole_archive_sha256"], "roles": roles,
              "selection": "Fixed metadata hashes, exact pixel identity exclusion and deterministic speaker matching; no model or outcome filtering",
              "pixels_read_for_identity": True, "model_outcomes_opened": False, "audio_bytes_opened": False,
              "qualification_and_confirmation_source_overlap": 0, "remaining_eligible_xnist_writers": 0,
              "remaining_reserved_qmnist_writers": 0, "remaining_new_speech_speakers": len(available_ood) - 600,
              "confirmation_shared_across_studies": True,
              "inference_scope": "Repeated routes, seeds and policies remain in 85 paired writer/speaker clusters; studies share sources and are correlated",
              "ood_scope": "600 disjoint new speaker identities with all modalities absent; not general out-of-distribution robustness",
              "pretrained_external_model_source_overlap_known": False}
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x") as stream:
        json.dump(result, stream, indent=2, sort_keys=True); stream.write("\n")
    return result


def load_rows(allocation, protocol, role):
    record = json.loads(Path(allocation).read_text()); spec = json.loads(Path(protocol).read_text())
    pins = spec.get("frozen_candidate_sha256", {})
    if (role not in record["roles"] or role not in spec.get("source_roles", []) or not pins
            or spec.get("source_allocation_sha256") != sha(allocation)
            or record["allocator_sha256"] != sha(__file__) or record["previous_allocation_sha256"] != PREVIOUS):
        raise ValueError("Exact prospective candidate and source role must be registered")
    previous_allocations()
    for path, expected in pins.items():
        if not Path(path).is_absolute() or sha(path) != expected:
            raise ValueError("Frozen candidate identity changed: " + path)
    return record["roles"][role], record


def load_images(cache, allocation, protocol, role):
    import torch
    from ..v6.data import SourceCorpus, SourceSplit

    selected, record = load_rows(allocation, protocol, role)
    if role not in ("confirmation", "qualification_id"):
        raise ValueError("All-missing OOD records have no image input")
    cache = Path(cache)
    for name, expected in record["archive_sha256"].items():
        if sha(cache / name) != expected:
            raise ValueError("Official image source changed")
    rows = selected["source_records"]; indices = {r["index"] for r in rows}
    if rows[0]["dataset"] == "xnist":
        actual = dict(pixels(cache / "xnist-images-idx3-ubyte.xz", indices))
        meta = {i: r for i, r in metadata(cache / "xnist-labels-idx2-int.xz") if i in indices}
    else:
        raw, meta, _ = _read(cache); actual = {i: raw[i * 784:(i + 1) * 784] for i in indices}
    tensors, labels, ids, hashes = [], [], [], []
    for item in rows:
        raw, m = actual[item["index"]], meta[item["index"]]
        if sha_bytes(raw) != item["pixel_sha256"] or (m[0], m[2], m[5]) != (item["label"], item["writer"], item["nist_digit"]):
            raise ValueError("Image source byte or metadata identity differs")
        tensors.append(torch.frombuffer(bytearray(raw), dtype=torch.uint8).reshape(1, 28, 28))
        labels.append(m[0]); ids.append(item["source_id"]); hashes.append(item["pixel_sha256"])
    return SourceCorpus({selected["role"]: SourceSplit(torch.stack(tensors), torch.tensor(labels), tuple(ids), tuple(hashes))}, record)


def sha_bytes(value):
    return hashlib.sha256(value).hexdigest()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("cache", "old-manifest", "audio-root", "output"):
        parser.add_argument("--" + name, required=True, type=Path)
    args = parser.parse_args()
    result = register(args.cache, args.old_manifest, args.audio_root, args.output)
    print(json.dumps({"allocation_sha256": sha(args.output), "roles": {k: {f: v[f] for f in ("writer_count", "pair_count", "speaker_count") if f in v} for k, v in result["roles"].items()}}))
