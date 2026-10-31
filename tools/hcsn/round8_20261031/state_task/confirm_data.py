"""Generate replacement confirmation only after publishing the review amendment."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import time

import numpy as np

from .data import HERE, make_data


def main(reference):
    if len(reference) != 40 or any(c not in "0123456789abcdef" for c in reference):
        raise ValueError("an immutable source Git commit is required")
    freeze = json.loads((HERE / "FREEZE.json").read_text())
    for name, sha in freeze["source_and_checkpoint_sha256"].items():
        if hashlib.sha256((HERE / name).read_bytes()).hexdigest() != sha:
            raise ValueError("frozen training source or model changed: " + name)
    amendment_path = HERE / "CONFIRMATION_AMENDMENT.json"
    amendment = json.loads(amendment_path.read_text())
    protocol = json.loads((HERE / "protocol.json").read_text())
    protocol["data_seeds"] |= amendment["replacement_seeds"]
    report = {"source_commit_before_generation": reference,
        "amendment_sha256": hashlib.sha256(amendment_path.read_bytes()).hexdigest(),
        "utc": datetime.now(timezone.utc).isoformat(), "datasets": {}}
    for name, seed in amendment["replacement_seeds"].items():
        path = HERE / "evidence/data" / (name + ".npz")
        if path.exists():
            raise FileExistsError(path)
        start, wall = time.process_time(), time.perf_counter()
        data = make_data(name, protocol)
        np.savez_compressed(path, **data)
        report["datasets"][name] = {"seed": seed, "samples": len(data["probability"]),
            "cpu_seconds": time.process_time() - start, "wall_seconds": time.perf_counter() - wall,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    (HERE / "evidence/data/confirmation_generation.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-commit", required=True)
    main(parser.parse_args().source_commit)
