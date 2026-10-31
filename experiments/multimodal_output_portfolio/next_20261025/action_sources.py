"""Independent new-writer sources for the richer paired action-value model."""

import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import time

from .sources import _read, sha
from .xnist_sources import _load, FILES


STUDY = "action_value"
WRITERS, PAIRS_PER_WRITER = 256, 2
QUALIFICATION_SHA = "c997590bb6c1a95a91d1ba469f6a8f1219764422d572b16f77175cd5e252252f"
SALT = "hepta-next-rich-action-value-writer-split-v1"


def _rank(kind, value):
    return hashlib.sha256(f"{SALT}:{kind}:{value}".encode()).digest()


def register(cache, qualification, output):
    if sha(qualification) != QUALIFICATION_SHA:
        raise ValueError("Previous native qualification allocation changed")
    previous = json.loads(Path(qualification).read_text())
    _, test, train = _read(cache)
    excluded = {r[2] for r in test + train} | set(previous["pair_writer_ids"])
    pixels, rows = _load(cache)
    groups = defaultdict(list)
    for index, row in enumerate(rows):
        if row[2] not in excluded and row[6] == 0:
            groups[row[2]].append(index)
    eligible = sorted((w for w, indices in groups.items() if len(indices) >= PAIRS_PER_WRITER * 2), key=lambda w: _rank("writer", w))
    if len(eligible) < WRITERS:
        raise ValueError("Insufficient new writers for the fixed value study")
    records = []
    for writer in eligible[:WRITERS]:
        for index in sorted(groups[writer], key=lambda i: _rank("digit", rows[i][5]))[:PAIRS_PER_WRITER * 2]:
            raw = pixels[index * 784:(index + 1) * 784]
            digest = hashlib.sha256(raw).hexdigest()
            records.append({"index": index, "writer": writer, "nist_digit": rows[index][5], "pixel_sha256": digest,
                            "source_id": f"xnist:{index}:nist:{rows[index][5]}:writer:{writer}:{digest}"})
    if len({r["pixel_sha256"] for r in records}) != len(records):
        raise ValueError("Duplicate pixel identity in value study")
    result = {"schema": "hepta.next.action-value-allocation.v1", "registered_unix_ns": time.time_ns(),
              "study": STUDY, "role": "next_action_value", "pair_count": WRITERS * PAIRS_PER_WRITER,
              "writer_count": WRITERS, "pair_writer_ids": [r["writer"] for r in records[::2]],
              "source_records": records, "archive_sha256": FILES, "allocator_sha256": sha(__file__),
              "source_reader_sha256": sha(Path(__file__).with_name("sources.py")),
              "xnist_reader_sha256": sha(Path(__file__).with_name("xnist_sources.py")),
              "native_qualification_allocation_sha256": QUALIFICATION_SHA,
              "all_qmnist_and_qualification_writer_overlap": 0, "excluded_writer_count": len(excluded),
              "remaining_writers": len(eligible) - WRITERS, "outcomes_opened": False,
              "selection": "Fixed metadata hash ordering; no model quality, label balancing, or sampling after results",
              "statistical_unit": "Writer; both disjoint pairs and all views/draws/seeds kept in one cluster"}
    with Path(output).open("x") as stream:
        json.dump(result, stream, sort_keys=True, indent=2); stream.write("\n")
    return result


def load_registered(cache, allocation, protocol, study=STUDY):
    import torch
    from ..v6.data import SourceCorpus, SourceSplit

    record = json.loads(Path(allocation).read_text())
    spec = json.loads(Path(protocol).read_text())
    pins = spec.get("frozen_candidate_sha256", {})
    if (study != STUDY or spec.get("study") != STUDY or not pins
            or spec.get("source_allocation_sha256") != sha(allocation)
            or record.get("allocator_sha256") != sha(__file__)
            or record.get("native_qualification_allocation_sha256") != QUALIFICATION_SHA
            or record.get("xnist_reader_sha256") != sha(Path(__file__).with_name("xnist_sources.py"))
            or record.get("source_reader_sha256") != sha(Path(__file__).with_name("sources.py"))
            or any(not Path(p).is_absolute() or sha(p) != h for p, h in pins.items())):
        raise ValueError("Exact frozen candidate and independent value-study registration required")
    pixels, rows = _load(cache)
    images, labels, ids, hashes, writers = [], [], [], [], []
    for entry in record["source_records"]:
        index = entry["index"]; row = rows[index]; raw = pixels[index * 784:(index + 1) * 784]
        digest = hashlib.sha256(raw).hexdigest()
        identity = f"xnist:{index}:nist:{row[5]}:writer:{row[2]}:{digest}"
        if (digest != entry["pixel_sha256"] or identity != entry["source_id"]
                or row[2] != entry["writer"] or row[5] != entry["nist_digit"]):
            raise ValueError("Value-study source identity changed")
        images.append(torch.frombuffer(bytearray(raw), dtype=torch.uint8).reshape(1, 28, 28))
        labels.append(row[0]); ids.append(identity); hashes.append(digest); writers.append(row[2])
    if (len(ids) != WRITERS * PAIRS_PER_WRITER * 2 or len(set(ids)) != len(ids) or len(set(writers)) != WRITERS
            or writers[::2] != record["pair_writer_ids"] or writers[1::2] != record["pair_writer_ids"]):
        raise ValueError("Value-study writer or pair census changed")
    return SourceCorpus({record["role"]: SourceSplit(torch.stack(images), torch.tensor(labels), tuple(ids), tuple(hashes))}, record)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cache", type=Path, required=True)
    p.add_argument("--qualification", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args(); result = register(a.cache, a.qualification, a.output)
    print(json.dumps({"sha256": sha(a.output), "writers": result["writer_count"], "pairs": result["pair_count"]}))
