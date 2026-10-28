"""Fresh-process inference from bound learned parameters and unlabeled requests."""

import argparse
import json
from pathlib import Path
import time

from v5.contracts import file_identity, write_json
from v5.router import Router, parameter_digest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True)
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--requests", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    wall, cpu = time.perf_counter(), time.process_time()
    requests_path = Path(args.requests)
    requests = json.loads(requests_path.read_bytes())
    if not isinstance(requests, list):
        raise ValueError("requests file must be a list of unlabeled serving objects")
    router = Router.load(args.model, args.manifest_sha256)
    before = parameter_digest(router)
    decisions = router.decisions(requests)
    after = parameter_digest(router)
    if before != after:
        raise AssertionError("inference changed loaded model parameters")
    write_json(
        args.output,
        {
            "schema": "memory-cell-v5.fresh-router-read.v1",
            "requests": file_identity(requests_path),
            "request_count": len(requests),
            "decisions": decisions,
            "manifest_sha256": args.manifest_sha256,
            "parameter_digest_before": before,
            "parameter_digest_after": after,
            "numeric_parameter_bytes": router.numeric_parameter_bytes(),
            "wall_seconds": time.perf_counter() - wall,
            "process_cpu_seconds": time.process_time() - cpu,
            "pretrained_encoder_calls": 0,
            "training_performed": False,
            "loaded_training_examples": False,
            "loaded_numeric_memory_targets": False,
        },
    )


if __name__ == "__main__":
    main()
