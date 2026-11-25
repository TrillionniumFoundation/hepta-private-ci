"""Exchange one already-frozen statistic per host through the checked TCP peer.

This engineering entry generates no examples or labels. Its source, configuration,
local archived statistics and remote payload digest are pinned before any socket
opens. The old multihost research generator and its failed runs remain unchanged.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import socket
import sys
import time
import zlib

import numpy as np

from distributed import array_hash, durable_write, hashed, seal
from transport import worker

SCHEMA = "pft-direct-frozen-snapshot-v1"
SOURCES = ("direct_snapshot.py", "distributed.py", "transport.py")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def prepare(config, folder):
    """Verify retained inputs and project them into the existing Receiver wire."""
    require(config["schema"] == SCHEMA, "Unknown direct snapshot namespace")
    require(config["scope"] == "engineering_frozen_statistics", "Incorrect qualification scope")
    require(config["training_runs"] == 0 and config["real_user_adoptions"] == 0,
            "This entry cannot qualify training or adoption")
    here = Path(__file__).parent
    require(config["source_sha256"] == {
        name: hashlib.sha256((here / name).read_bytes()).hexdigest() for name in SOURCES
    }, "Pinned peer implementation differs")
    require(len(config["hosts"]) == len(config["addresses"]) == len(config["expected_contributions"])
            == len(config["expected_contribution_ids"]) == 2,
            "Exactly two frozen peers are required")
    node = config["node"]
    require(type(node) is int and node in (0, 1), "Unknown local peer")
    require(config["deadline_seconds"] == 45 and config["retry_interval_seconds"] == 1,
            "The direct engineering connection budget differs")
    compressed = Path(config["archive"]).read_bytes()
    require(hashlib.sha256(compressed).hexdigest() == config["archive_sha256"],
            "Original archived statistics changed")
    original = json.loads(zlib.decompress(compressed))
    require(original["configured_host"] == config["hosts"][node], "Original host differs")
    require(original["source_sha256"] == config["original_source_sha256"], "Original generator source differs")
    selected = [record for record in original["records"]
                if record["size"] == config["size"] and record["seed"] == config["seed"]]
    require(len(selected) == 1, "Ambiguous original statistic selection")
    record = selected[0]
    require(hashed(record) == config["record_sha256"], "Selected original statistic changed")
    parent = np.asarray(config["parent"], dtype=float)
    require(parent.shape == (config["size"],) and np.isfinite(parent).all(), "Invalid original parent")
    require(record["header"]["parent"] == hashed(config["parent"]), "Original parent commitment differs")
    require(record["header"]["coordinates"] == hashed(["identity", config["size"]]),
            "Original coordinates differ")
    require(record["header"]["objective"] == hashed([.01, "sum_squared_residual", config["original_source_sha256"]]),
            "Original objective differs")
    header = {"size": config["size"], "parent_id": array_hash(parent),
              "coordinate_id": array_hash(np.eye(config["size"])),
              "objective_id": hashed({"ridge": .01, "loss": "sum squared residual", "version": 1})}
    message = seal({**header, "client_id": str(node), "count": record["sample_count"],
                    "data_sha256": hashed(record["data_hashes"]),
                    "gram": record["gram"], "moment": record["moment"]})
    require(message["payload_sha256"] == config["expected_contributions"][node],
            "Projected original contribution differs")
    require(message["contribution_id"] == config["expected_contribution_ids"][node],
            "Projected original contribution identity differs")
    return {"node": node, "directory": str(folder), "header": header, "message": message,
            "expected_contributions": config["expected_contributions"], "retain_frames": True,
            "crash_once": False, "addresses": config["addresses"], "startup_delay_seconds": 0,
            "round_id": config["round_id"], "ridge": .01, "parent": config["parent"],
            "deadline_seconds": config["deadline_seconds"], "retry_interval_seconds": config["retry_interval_seconds"]}


def run(path, expected):
    raw = Path(path).read_bytes()
    require(hashlib.sha256(raw).hexdigest() == expected, "Independent configuration pin differs")
    config = json.loads(raw)
    folder = Path(config["output"])
    projected = prepare(config, folder)
    # Create-exclusive: uncertain or completed attempts are never replayed here.
    folder.mkdir(mode=0o700)
    started = time.monotonic_ns()
    identity = {"schema": SCHEMA, "config_sha256": expected, "pid": os.getpid(),
                "hostname": socket.gethostname(), "python": sys.version, "executable": sys.executable,
                "numpy": np.__version__, "started_unix_ns": time.time_ns()}
    durable_write(folder / "STARTED.json", identity)
    durable_write(folder / "worker.json", projected)
    error = None
    try:
        worker(folder / "worker.json", False)
        result = json.loads((folder / "result.json").read_text())
        require(sorted(result["accepted_ids"]) == sorted(config["expected_contribution_ids"]),
                "Exactly both registered contribution identities are required")
        require(any(item["direction"] == "receive" and item["frame_bytes"] > 0
                    for item in result["transfers"]), "No direct incoming application frame")
    except BaseException as failure:
        error = {"type": type(failure).__name__, "message": str(failure)}
        raise
    finally:
        durable_write(folder / "END.json", {**identity, "wall_ns": time.monotonic_ns() - started,
                      "status": "FAILED" if error else "COMPLETE", "error": error,
                      "training_runs": 0, "real_user_adoptions": 0, "data_generated": False,
                      "scope": "engineering_frozen_statistics"})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path)
    parser.add_argument("--expected", required=True)
    args = parser.parse_args()
    run(args.config, args.expected)


if __name__ == "__main__":
    main()
