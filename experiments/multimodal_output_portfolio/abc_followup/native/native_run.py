"""Exec a byte-pinned native binary under the common exact-PID process receipt."""

import argparse
import os
from pathlib import Path

from ...abc_recovery.training_run import file_sha


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--binary-sha256", required=True)
    parser.add_argument("arguments", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    binary = args.binary.resolve(strict=True)
    if file_sha(binary) != args.binary_sha256:
        raise ValueError("Native executable changed before exec")
    arguments = args.arguments[1:] if args.arguments[:1] == ["--"] else args.arguments
    os.execv(str(binary), [str(binary), *arguments])
