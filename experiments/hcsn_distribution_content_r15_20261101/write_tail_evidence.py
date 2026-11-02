"""Serialize the frozen tail computation with explicit NumPy scalar support."""

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np

from . import tail_checks


def scalar(value):
    if isinstance(value, np.generic):
        return value.item()
    raise TypeError(f"Unsupported evidence value: {type(value).__name__}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = tail_checks.numerics()
    result["serialization"] = dict(
        computation_sha256=hashlib.sha256(Path(tail_checks.__file__).read_bytes()).hexdigest(),
        writer_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        scope="Only NumPy scalar JSON conversion; frozen numerical computation unchanged")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as stream:
        json.dump(result, stream, indent=2, sort_keys=True, allow_nan=False, default=scalar)
        stream.write("\n")
