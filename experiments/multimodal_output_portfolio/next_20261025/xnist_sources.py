"""One thousand new-writer qualification pairs, excluding all QMNIST writers.

This supplements the prospective QMNIST allocation without changing it. The
sample size is fixed before qualification outcomes and is not extended on fail.
"""

import argparse
from collections import defaultdict
import hashlib
import json
import lzma
from pathlib import Path
import struct
import time

from .sources import COMMIT, _read, sha


FILES = {"xnist-images-idx3-ubyte.xz": "f075553993026d4359ded42208eff77a1941d3963c1eff49d6015814f15f0984",
         "xnist-labels-idx2-int.xz": "db042968723ec2b7aed5f1beac25d2b6e983b9286d4f4bf725f1086e5ae55c4f"}
STUDY = "native_qualification"
COUNT = 1000
SALT = "hepta-next-native-qualification-1000-new-writers-v1"
ORIGINAL_ALLOCATION_SHA = "6ad7fef099626d8ea1f4f6c123610016adfeca9aa828765f185f62d92afdb27e"


def _load(cache):
    cache = Path(cache)
    for name, expected in FILES.items():
        if sha(cache / name) != expected:
            raise ValueError("XNIST author data checksum differs")
    raw = lzma.decompress((cache / "xnist-labels-idx2-int.xz").read_bytes())
    if struct.unpack(">III", raw[:12]) != (3074, 402953, 8) or len(raw) != 12 + 402953 * 32:
        raise ValueError("XNIST metadata shape differs")
    labels = tuple(struct.iter_unpack(">8I", raw[12:]))
    raw = lzma.decompress((cache / "xnist-images-idx3-ubyte.xz").read_bytes())
    if struct.unpack(">IIII", raw[:16]) != (2051, 402953, 28, 28) or len(raw) != 16 + 402953 * 784:
        raise ValueError("XNIST pixel shape differs")
    return raw[16:], labels


def _rank(kind, value):
    return hashlib.sha256(f"{SALT}:{kind}:{value}".encode()).digest()


def register(cache, original_allocation, output):
    if sha(original_allocation) != ORIGINAL_ALLOCATION_SHA:
        raise ValueError("Original next-stage allocation changed")
    qpixels, qtest, qtrain = _read(cache)
    old_writers = {row[2] for row in qtrain + qtest}
    old_digits = {row[5] for row in qtrain + qtest}
    old_pixels = {hashlib.sha256(qpixels[i * 784:(i + 1) * 784]).hexdigest() for i in range(60000)}
    pixels, labels = _load(cache)
    candidates, duplicate_pixels = defaultdict(list), 0
    for index, row in enumerate(labels):
        if row[0] > 9 or row[6] != 0 or row[2] in old_writers or row[5] in old_digits:
            continue
        digest = hashlib.sha256(pixels[index * 784:(index + 1) * 784]).hexdigest()
        if digest in old_pixels:
            duplicate_pixels += 1
            continue
        candidates[row[2]].append((index, row[5], digest))
    eligible = sorted((w for w, rows in candidates.items() if len(rows) >= 2), key=lambda w: _rank("writer", w))
    if len(eligible) < COUNT:
        raise ValueError("Insufficient independent writers for original qualification bound")
    indices, nist_ids, hashes, source_ids = [], [], [], []
    writers = eligible[:COUNT]
    for writer in writers:
        for index, nist, digest in sorted(candidates[writer], key=lambda r: _rank("digit", r[1]))[:2]:
            indices.append(index); nist_ids.append(nist); hashes.append(digest)
            source_ids.append(f"xnist:{index}:nist:{nist}:writer:{writer}:{digest}")
    if len(set(hashes)) != len(hashes):
        raise ValueError("Duplicate selected pixel identity")
    result = {"schema": "hepta.next.xnist-qualification-allocation.v1", "registered_unix_ns": time.time_ns(),
              "author_commit": COMMIT, "archive_sha256": FILES, "allocator_sha256": sha(__file__),
              "original_allocation_sha256": ORIGINAL_ALLOCATION_SHA, "salt": SALT,
              "study": STUDY, "role": "next_" + STUDY, "pair_count": COUNT,
              "writer_count": COUNT, "pair_writer_ids": writers, "indices": indices,
              "nist_digit_ids": nist_ids, "source_ids": source_ids, "pixel_sha256": hashes,
              "source_ids_sha256": hashlib.sha256("\n".join(source_ids).encode()).hexdigest(),
              "all_qmnist_writers_excluded": len(old_writers), "eligible_unused_writers": len(eligible),
              "excluded_matching_qmnist_pixels": duplicate_pixels, "old_writer_overlap": 0,
              "old_digit_overlap": 0, "outcomes_opened": False,
              "selection": "One disjoint pair per writer, hash ordering with no label or output-quality filtering",
              "statistical_unit": "Writer, exactly one pair per writer; views and actions never increase N",
              "unused_writers_after_this_allocation": len(eligible) - COUNT,
              "unknown_external_use_attested": False}
    Path(output).parent.mkdir(parents=True, exist_ok=True)
    with Path(output).open("x") as stream:
        json.dump(result, stream, indent=2, sort_keys=True)
        stream.write("\n")
    return result


def load_registered(cache, allocation, protocol, study=STUDY):
    import torch
    from ..v6.data import SourceCorpus, SourceSplit

    record = json.loads(Path(allocation).read_text())
    specification = json.loads(Path(protocol).read_text())
    pins = specification.get("frozen_candidate_sha256", {})
    if (study != STUDY or specification.get("study") != STUDY or not pins
            or specification.get("source_allocation_sha256") != sha(allocation)
            or record.get("allocator_sha256") != sha(__file__)
            or record.get("original_allocation_sha256") != ORIGINAL_ALLOCATION_SHA):
        raise ValueError("Exact prospective qualification registration required")
    for path, expected in pins.items():
        if not Path(path).is_absolute() or sha(path) != expected:
            raise ValueError("Frozen candidate changed: " + path)
    _, qtest, qtrain = _read(cache)
    old_writers, old_digits = {r[2] for r in qtrain + qtest}, {r[5] for r in qtrain + qtest}
    pixels, labels = _load(cache)
    images, values, ids, hashes, writers = [], [], [], [], []
    for index, expected, expected_hash in zip(record["indices"], record["source_ids"], record["pixel_sha256"]):
        row = labels[index]
        raw = pixels[index * 784:(index + 1) * 784]
        digest = hashlib.sha256(raw).hexdigest()
        identity = f"xnist:{index}:nist:{row[5]}:writer:{row[2]}:{digest}"
        if identity != expected or digest != expected_hash or row[2] in old_writers or row[5] in old_digits:
            raise ValueError("Qualification source identity changed")
        images.append(torch.frombuffer(bytearray(raw), dtype=torch.uint8).reshape(1, 28, 28))
        values.append(row[0]); ids.append(identity); hashes.append(digest); writers.append(row[2])
    if (len(ids) != COUNT * 2 or len(set(ids)) != COUNT * 2 or len(set(writers)) != COUNT
            or writers[::2] != record["pair_writer_ids"] or writers[1::2] != record["pair_writer_ids"]):
        raise ValueError("Qualification is not one distinct pair per writer")
    split = SourceSplit(torch.stack(images), torch.tensor(values), tuple(ids), tuple(hashes))
    return SourceCorpus({record["role"]: split}, record)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--original-allocation", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = register(args.cache, args.original_allocation, args.output)
    print(json.dumps({"sha256": sha(args.output), "writers": result["writer_count"],
                      "pairs": result["pair_count"], "remaining_writers": result["unused_writers_after_this_allocation"]}))
