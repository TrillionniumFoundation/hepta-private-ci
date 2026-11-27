"""CLI for the read-only ORG-1 reference reviewer."""

import argparse
import json
from pathlib import Path

from .metering import atomic_json
from .organization_artifacts import _strict_json
from .organization_policy import review_organization


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--trusted-protocol-sha256", required=True)
    parser.add_argument("--trusted-observer-sha256", action="append", default=[])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = review_organization(
        _strict_json(args.protocol.read_bytes()),
        _strict_json(args.evidence.read_bytes()),
        args.evidence_root,
        trusted_protocol_sha256=args.trusted_protocol_sha256,
        trusted_observer_sha256=args.trusted_observer_sha256,
    )
    atomic_json(args.output, result)
    print(
        json.dumps(
            {
                "status": result["status"],
                "decision": "NoUpdate",
                "reasons": result["reasons"],
            }
        )
    )
    return 0 if result["status"] == "REFERENCE_CONSISTENT" else 2


if __name__ == "__main__":
    raise SystemExit(main())
