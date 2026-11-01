"""Verify the final guard fix against preserved pre-fix source and real inputs."""

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

import numpy as np

from experiments.hcsn_v7_support_20261101.content_interface.content_interface import ContractError, Modality
from .legacy_v3 import prepared_observation
from .replay import episode_arrays, legacy_data


def run(before, output):
    specification = importlib.util.spec_from_file_location("historical_guard_snapshot", before)
    old = importlib.util.module_from_spec(specification)
    sys.modules[specification.name] = old
    specification.loader.exec_module(old)
    count, all_finite = 0, True
    for task in ("async_av", "av_binding"):
        for split in ("train", "val", "test"):
            data = legacy_data(task, split)
            for index in range(len(data["x"])):
                x, observed, times = episode_arrays(data, index)
                all_finite = all_finite and bool(np.isfinite(x).all())
                for modality in Modality:
                    for prefix in (1, 2, 3):
                        kwargs = {"object_id": "same-source-row", "modality": modality,
                                  "prefix_end": prefix, "completed_at": float(prefix)}
                        previous = old.prepared_observation(x, observed, times, **kwargs)
                        current = prepared_observation(x, observed, times, **kwargs)
                        if previous != current:
                            raise AssertionError("Guard hardening changed a historical packet")
                        count += 1
    x = np.zeros((2, 40))
    x[:, 32] = x[:, 34] = 1
    x[1, :16] = np.nan
    observed, times = np.ones(2, bool), np.array([.5, 1.5])
    kwargs = {"object_id": "future-malformation", "modality": Modality.AUDIO,
              "prefix_end": 1, "completed_at": 1.0}
    try:
        old.prepared_observation(x, observed, times, **kwargs)
        old_rejected = False
    except ContractError:
        old_rejected = True
    packet = prepared_observation(x, observed, times, **kwargs)
    x[1, :16] = 999
    unchanged = packet == prepared_observation(x, observed, times, **kwargs)
    report = {
        "scope": "Final future-payload validation hardening; historical packets are unchanged",
        "before_sha256": hashlib.sha256(before.read_bytes()).hexdigest(),
        "after_sha256": hashlib.sha256(Path(__file__).with_name("legacy_v3.py").read_bytes()).hexdigest(),
        "historical_packets_compared": count, "all_historical_inputs_finite": all_finite,
        "all_historical_packets_equal": True, "old_future_nan_rejects_current_read": old_rejected,
        "new_future_nan_does_not_change_current_packet": unchanged,
        "fresh_confirmation": False,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x") as stream:
        json.dump(report, stream, indent=2)
        stream.write("\n")
    if not old_rejected or not unchanged or not all_finite:
        raise AssertionError("Causal hardening check failed")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--before", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run(args.before, args.output)
