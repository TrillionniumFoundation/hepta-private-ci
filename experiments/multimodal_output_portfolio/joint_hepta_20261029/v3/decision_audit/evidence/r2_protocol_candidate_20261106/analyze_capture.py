"""Read-only registered accounting/analysis; never loads or promotes a model."""

import argparse
import json
from pathlib import Path

from r2_capture import audit, digest
from r2_statistics import crossed_analysis, require


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", required=True)
    parser.add_argument("--protocol", default=str(Path(__file__).with_name("PROTOCOL.json")))
    parser.add_argument("--design-sha256", required=True)
    parser.add_argument("--capture-sha256", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    protocol = json.loads(Path(args.protocol).read_bytes())
    bundle = json.loads(Path(args.bundle).read_bytes())
    require(bundle.get("synthetic") is not True, "synthetic controls cannot enter the ordinary capture analyzer")
    matrix, accounting = audit(bundle, protocol, design_sha256=args.design_sha256,
                               capture_sha256=args.capture_sha256)
    stats = crossed_analysis(matrix, bundle["design"]["strong_reference"])
    result = {"schema": "hepta.r2.registered-arithmetic-report.v1",
              "protocol_sha256": digest(protocol), "design_sha256": args.design_sha256,
              "capture_sha256": args.capture_sha256, "accounting": accounting, "statistics": stats,
              "scientific_admission": "REQUIRES_INDEPENDENT_CUSTODY_QUALITY_POWER_BUDGET_AND_CANDIDATE_REVIEW",
              "confirmation": False, "no_update": True, "production_qualified": False}
    with Path(args.output).open("x") as out:
        json.dump(result, out, indent=2, allow_nan=False)
        out.write("\n")


if __name__ == "__main__":
    main()
