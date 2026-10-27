"""Fresh-process value-free read interface for a published numeric memory."""

import argparse
import json
import os
from pathlib import Path
import sys

from v3.lifecycle import FactorOwner, canonical, read_regular, sha


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--owner", type=Path, required=True)
    parser.add_argument("--witness", type=Path, required=True)
    parser.add_argument("--queries", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--mode", choices=("parameters", "lossless_codec"), required=True
    )
    args = parser.parse_args()
    raw = read_regular(args.queries, 4_000_000)
    request = json.loads(raw)
    if (
        set(request) != {"scope", "generation", "coordinates"}
        or len(request["coordinates"]) > 100000
    ):
        raise ValueError(
            "read request must carry only scope, generation, and addresses"
        )
    owner = FactorOwner(args.owner, args.witness, scope=request["scope"])
    manifest = owner.recover()
    result = {
        "schema": "memory-cell-v3.fresh-owner-read.v1",
        "request_sha256": sha(raw),
        "model_sha256": manifest["model_sha256"],
        "generation": manifest["generation"],
        "mode": args.mode,
        "predictions": owner.read(
            request["coordinates"], generation=request["generation"], mode=args.mode
        ),
        "residual_loaded": args.mode == "lossless_codec",
        "resident_decoded_exact_cache_bytes": 0
        if owner._exact is None
        else sum(array.nbytes for array in owner._exact),
        "process_id": os.getpid(),
        "source_values_in_request": False,
        "source_ledger_loaded": False,
        "python": sys.version,
    }
    with args.output.open("xb") as stream:
        stream.write(canonical(result))


if __name__ == "__main__":
    main()
