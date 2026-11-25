"""One-time pre-freeze repair of discarded timing-input proposal, no model use.

Reuses already decoded 128 features byte for byte. Leaves the old cache intact.
Actual timing survives as metadata but is removed from both model inputs.
"""

import argparse
from pathlib import Path
import shutil

import numpy as np

from .acquire import digest, save, stage
from .provenance import read


def retime(root):
    old, new = root/"prepared", root/"prepared_model_clock_v2"
    manifest = read(old/"DATASET.json")
    new.mkdir()
    rows = {}
    for split, row in manifest["splits"].items():
        source = old/row["path"]
        if digest(source.read_bytes()) != row["sha256"]:
            raise ValueError("discarded-proposal cache changed")
        with np.load(source, allow_pickle=False) as f:
            data = {k: f[k].copy() for k in f.files}
        clocks = np.broadcast_to(np.stack((np.arange(32)/31, np.full(32, 1/32)), -1), (len(data["y"]), 32, 2)).astype(np.float32)
        for modality in ("audio", "video"):
            original = data[modality][..., :128].copy()
            data[modality] = np.concatenate((original, clocks), -1)
            if not np.array_equal(original, data[modality][..., :128]):
                raise ValueError("low-level modality features changed")
        np.savez_compressed(new/row["path"], **data)
        rows[split] = {**row, "sha256": digest((new/row["path"]).read_bytes())}
    shutil.copyfile(old/"DECODE.json", new/"DECODE.json")
    manifest.update(splits=rows, time_contract="Normalized model dt=.25, common model-input t/31 and1/32; actual elapsed/dt audit metadata only.",
        design_revision="Pre-freeze replacement of shared real timing inputs, before any AV fit/test. Original proposal cache and all receipts preserved.",
        superseded_data_descriptor_sha256=digest((old/"DATASET.json").read_bytes()),
        input_time_moments="none; all clips use exactly the same two deterministic clock channels")
    manifest.pop("time_normalization_sha256", None)
    save(new/"DATASET.json", manifest)
    save(root/"TIMING_DESIGN_REVISION.json", {"stage": "before any AV fit or model evaluation", "old": "prepared", "adopted": "prepared_model_clock_v2",
        "reason": "Shared true duration could identify matched recordings without audiovisual content.",
        "low_level_128_features_unchanged": True, "real_time_metadata_preserved": True,
        "duration_only_negative_control": "Computed only after all nine fits sealed; never used for selection"})


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    stage(args.root, "retime", retime)
