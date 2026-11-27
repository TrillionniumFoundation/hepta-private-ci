"""Numerical child; its process limit is applied by the parent before exec."""

import argparse
import json
from pathlib import Path

from qualification.hcsn_currentstate_n256_firststep_dense_oracle_source.dense_oracle import (
    run_warm_first_step,
)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--admission", type=Path, required=True)
    parser.add_argument("--capsule", type=Path, required=True)
    parser.add_argument("--result", type=Path, required=True)
    args = parser.parse_args()
    if args.capsule.exists() or args.result.exists():
        raise ValueError("output already exists")
    result = run_warm_first_step(args.root, args.request, args.admission, args.capsule)
    args.result.write_text(json.dumps(result, allow_nan=False, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, allow_nan=False, separators=(",", ":"), sort_keys=True))


if __name__ == "__main__":
    main()
