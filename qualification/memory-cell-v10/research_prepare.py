"""Materialize only train/calibration inputs before fitting; held is a later job."""

import argparse
import importlib.util
import json
from pathlib import Path
import sqlite3

import numpy as np

from corpus import records, queries
from export_native import canonical, sha


def make_encoder(directory):
    path = Path(__file__).resolve().parents[1] / "memory-cell-adapters" / "encoder.py"
    spec = importlib.util.spec_from_file_location("research_pinned_encoder", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.PinnedMiniLMEncoder(directory)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--encoder-dir", type=Path, required=True)
    parser.add_argument("--held-only", action="store_true")
    args = parser.parse_args()
    protocol = json.loads(Path(__file__).with_name("PROTOCOL.json").read_text())
    encoder, cache = make_encoder(args.encoder_dir), {}

    def encode(texts):
        missing = list(dict.fromkeys(text for text in texts if text not in cache))
        for text, value in zip(missing, encoder.encode(missing), strict=True):
            cache[text] = value
        return np.asarray([cache[text] for text in texts], dtype=np.float32)

    for capacity in protocol["capacities"]:
        directory = args.output / f"capacity-{capacity}"
        if args.held_only:
            held = json.loads(Path(__file__).with_name("held_templates.json").read_text())
            rows = queries(capacity, "held", held)
            for earlier in ("train", "calibration"):
                previous = json.loads((directory / f"{earlier}-queries.json").read_text())
                if {row["text"] for row in rows} & {row["text"] for row in previous}:
                    raise ValueError("wording leakage between frozen partitions")
            (directory / "held-queries.json").write_bytes(canonical(rows))
            np.savez_compressed(directory / "held-features.npz", features=encode([row["text"] for row in rows]))
            continue
        directory.mkdir(parents=True, exist_ok=False)
        population = records(capacity, dataset_seed=protocol["dataset_seed"])
        (directory / "sources.json").write_bytes(canonical(population))
        values = {}
        for kind in ("semantic", "procedure"):
            rows = [row for row in population["records"] if row["kind"] == kind]
            values[kind] = encode([row["canonical_text"] for row in rows])
        np.savez_compressed(directory / "canonical.npz", **values)
        earlier = set()
        for phase in ("train", "calibration"):
            rows = queries(capacity, phase)
            texts = [row["text"] for row in rows]
            if earlier & set(texts):
                raise ValueError("training/calibration text overlap")
            earlier.update(texts)
            (directory / f"{phase}-queries.json").write_bytes(canonical(rows))
            np.savez_compressed(directory / f"{phase}-features.npz", features=encode(texts))
        connection = sqlite3.connect(directory / "exact.sqlite")
        connection.executescript("CREATE TABLE memory(kind TEXT, idx INTEGER, key TEXT, value TEXT, source_id TEXT, PRIMARY KEY(kind,idx)); CREATE TABLE episode(idx INTEGER,at INTEGER,value INTEGER,source_id TEXT,PRIMARY KEY(idx,at)); CREATE TABLE exception(idx INTEGER PRIMARY KEY,held INTEGER,source_id TEXT);")
        connection.executemany("INSERT INTO memory VALUES(?,?,?,?,?)", [(row["kind"], row["index"], row["key"], json.dumps(row["value"]), row["source_id"]) for row in population["records"]])
        connection.executemany("INSERT INTO episode VALUES(?,?,?,?)", [(row["index"], row["effective_at"], row["value"], row["source_id"]) for row in population["event_records"]])
        connection.executemany("INSERT INTO exception VALUES(?,?,?)", [(row["index"], row["value"], row["source_id"]) for row in population["hold_records"]])
        connection.commit()
        connection.close()
    receipt = encoder.receipt()
    receipt.update(schema="hepta.memory.v10.preparation.v1", held_files_read=args.held_only,
                   distinct_cached_texts=len(cache), protocol_sha256=sha(Path(__file__).with_name("PROTOCOL.json").read_bytes()))
    (args.output / ("HELD_ENCODER.json" if args.held_only else "TRAIN_ENCODER.json")).write_bytes(canonical(receipt))
    print(json.dumps({"held_only": args.held_only, "encoder_calls": encoder.calls, "encoder_seconds": encoder.seconds}))


if __name__ == "__main__":
    main()
