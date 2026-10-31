"""Export the byte-verified frozen FullHX inputs; no training or data fitting."""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np

CHECKPOINT = "third/memory/checkpoints/memory_full_mass_seed29.npz"
TABLE = "next/full_kernel/baseline_table.npz"
EXPECTED = {
    CHECKPOINT: "4962cd6126dc5e393cf7dbe72bea5519125bfb7971a7e3665a36af908aff5fcb",
    TABLE: "c77e407162061c06a9a34c5822b8751ebb2a71b1a5ff2a584c60e6b6ec63e764",
}


def prepare(source, output):
    inputs, arrays = {}, {}
    for name in (CHECKPOINT, TABLE):
        path = source / name
        raw = path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        if digest != EXPECTED[name]:
            raise ValueError(("frozen FullHX input changed", name))
        with np.load(path, allow_pickle=False) as archive:
            arrays[name] = {k: archive[k].astype(np.float32).ravel().tolist() for k in archive}
        inputs[name] = dict(sha256=digest, bytes=len(raw), source=str(path))
    weights = dict(schema="hcsn.fullhx.frozen-f32.v1", checkpoint_sha256=EXPECTED[CHECKPOINT],
                   table_sha256=EXPECTED[TABLE], parameters=arrays[CHECKPOINT], table=arrays[TABLE])
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x") as stream:
        json.dump(weights, stream, separators=(",", ":"), allow_nan=False)
        stream.write("\n")
    record = dict(schema="hepta.r9.native.fullhx-export.v1", inputs=inputs,
                  exported_sha256=hashlib.sha256(output.read_bytes()).hexdigest(),
                  exported_bytes=output.stat().st_size, parameter_arithmetic="binary32",
                  table_conversion="same binary32 cast as frozen NumPy reference",
                  solve_arithmetic="binary64 Cholesky of symmetric positive ridge matrix",
                  retrained=False)
    output.with_suffix(".identity.json").write_text(json.dumps(record, indent=2)+"\n")
    return record


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hcsn-source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(prepare(args.hcsn_source, args.output)))
