"""Publish saved H4 arrays only; never import a generator or construct data."""

import csv
import hashlib
import json
import math
import time
from pathlib import Path


def main():
    cpu_start, wall_start = time.process_time_ns(), time.monotonic_ns()
    import numpy as np

    root = Path(__file__).resolve().parent
    targets = [root / name for name in (
        "paired-row.csv", "paired-source.csv", "paired-seed.json",
        "pairing-export-execution.json",
    )]
    if any(path.exists() for path in targets):
        raise FileExistsError("Do not overwrite an existing published export")
    meta = json.loads((root / "train-metadata.json").read_text())
    analysis = json.loads((root / "headroom-analysis.json").read_text())
    ids, hashes = meta["source_ids"], meta["input_hashes"]
    source_order = list(dict.fromkeys(ids))
    assert len(ids) == len(hashes) == 3072 and len(source_order) == 192
    assert ids == meta["groups"]
    indices = {source: np.array([i for i, value in enumerate(ids) if value == source])
               for source in source_order}
    assert all(len(value) == 16 for value in indices.values())
    fields = ["NC_full_raw", "NC_low_raw", "N_full_raw", "free_oracle_raw",
              "free_oracle_minus_N_full_raw", "N_minus_NC_full_raw",
              "NC_low_minus_NC_full_raw"]
    summaries = []
    row_count, source_count = 0, 0
    with np.load(root / "content-values.npz", allow_pickle=False) as arrays, \
            targets[0].open("x", newline="") as row_file, \
            targets[1].open("x", newline="") as source_file:
        row_writer, source_writer = csv.writer(row_file), csv.writer(source_file)
        row_writer.writerow(["seed", "row", "source_id", "source_scene", "input_sha256"] + fields)
        source_writer.writerow(["seed", "source_id", "source_scene", "rows"] + fields)
        for seed in (11, 23, 47):
            full = arrays[f"s{seed}_NC_full"]
            low = arrays[f"s{seed}_NC_low"]
            static = arrays[f"s{seed}_N_full"]
            assert full.shape == low.shape == static.shape == (3072,)
            oracle = np.maximum(full, low)
            values = np.column_stack((full, low, static, oracle, oracle - static,
                                      static - full, low - full))
            assert np.isfinite(values).all()
            for i, source in enumerate(ids):
                row_writer.writerow([seed, i, source, meta["sources"][source]["scene"], hashes[i]]
                                    + [format(float(value), ".17g") for value in values[i]])
                row_count += 1
            grouped = []
            for source in source_order:
                mean = np.array([math.fsum(values[indices[source], j]) / 16
                                 for j in range(len(fields))])
                grouped.append(mean)
                source_writer.writerow([seed, source, meta["sources"][source]["scene"], 16]
                                       + [format(float(value), ".17g") for value in mean])
                source_count += 1
            row_mean = np.array([math.fsum(values[:, j]) / len(values)
                                 for j in range(len(fields))])
            source_mean = np.array([math.fsum(value[j] for value in grouped) / len(grouped)
                                    for j in range(len(fields))])
            np.testing.assert_allclose(row_mean, source_mean, atol=2e-15, rtol=0)
            frozen = next(item for item in analysis["seeds"] if item["seed"] == seed)
            for key, column in (("NC_full_raw", 0), ("NC_low_raw", 1), ("N_full_raw", 2),
                                ("free_label_oracle_raw", 3),
                                ("free_label_oracle_raw_minus_N_full", 4),
                                ("content_gap_N_minus_NC", 5)):
                assert abs(float(row_mean[column]) - frozen[key]) < 2e-15, key
            summaries.append({"seed": seed, "rows": 3072, "physical_sources": 192,
                              "row_equal_means": dict(zip(fields, map(float, row_mean))),
                              "source_equal_means": dict(zip(fields, map(float, source_mean)))})
    targets[2].write_text(json.dumps({
        "schema": "hepta.h4.saved-array-pairings.v1", "seeds": summaries,
        "boundary": "Empirical expected decoded raw utility on saved TRAIN arrays only. "
                    "The rowwise max uses unavailable labels and bounds only these two "
                    "fixed NC action distributions. No CPU-net bound, CI, fit or new data.",
    }, indent=2, sort_keys=True) + "\n")
    for path, expected in ((targets[0], 9216), (targets[1], 576)):
        with path.open(newline="") as stream:
            assert len(list(csv.DictReader(stream))) == expected
    payload = {path.name: {"bytes": path.stat().st_size,
                          "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
               for path in targets[:3]}
    receipt = {
        "schema": "hepta.h4.saved-array-export-execution.v1", "exit_code": 0,
        "row_pairings": row_count, "source_pairings": source_count,
        "new_model_calls": 0, "new_data_constructions": 0,
        "qualification_credit": False,
        "cost_scope": "Separate publication R&D from before NumPy import through CSV "
                      "readback/hashing, before final receipt serialization. "
                      "Not credited against historical build or H4 diagnostic costs.",
        "outputs": payload,
        "process_cpu_ns_before_receipt": time.process_time_ns() - cpu_start,
        "wall_ns_before_receipt": time.monotonic_ns() - wall_start,
    }
    targets[3].write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    print(json.dumps(receipt, sort_keys=True))


if __name__ == "__main__":
    main()
