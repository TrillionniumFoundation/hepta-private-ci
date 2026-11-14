"""Zero-numerical static inspector for the N256 reference-stream interface."""

import hashlib
import json
from pathlib import Path

from .reference_stream_contract import require_reference_execution_admission, validate_request


ROOT = Path(__file__).parent
REPO = ROOT.parents[1]


def _digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    request = json.loads((ROOT / "REQUEST.json").read_text())
    validate_request(request)
    freeze = json.loads((ROOT / "SOURCE_FREEZE.json").read_text())
    for relative, expected in freeze["source_sha256"].items():
        path = REPO / relative
        actual = _digest(path)
        if actual != expected:
            raise SystemExit(f"source mismatch: {relative}: {actual} != {expected}")
    try:
        require_reference_execution_admission(ROOT / "REQUEST.json", None)
    except RuntimeError:
        pass
    else:
        raise SystemExit("reference source intent failed open")
    print("PASS_N256_REFERENCE_STREAM_INTERFACE_SOURCE_ONLY")


if __name__ == "__main__":
    main()
