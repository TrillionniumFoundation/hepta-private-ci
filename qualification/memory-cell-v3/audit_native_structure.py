"""Independently recalculate native/structure evidence without fitting or writes.

CLI: python audit_native_structure.py RUN --output OUTSIDE_RUN.json
API: audit_run(run, output=None, allow_development=False)
Standalone historical development stages can be inspected explicitly with
--development-native / --development-structure and --allow-development.
The auditor only loads artifacts and evaluates saved queries; it never trains,
invokes the native executable, edits the experiment or updates its manifest."""

import argparse
import json
from pathlib import Path

from v3.native_structure_audit_run import audit_development, audit_run


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", nargs="?", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--allow-development", action="store_true")
    parser.add_argument("--development-native", type=Path)
    parser.add_argument("--development-structure", type=Path)
    args = parser.parse_args()
    if args.run is not None:
        if (
            args.development_native is not None
            or args.development_structure is not None
        ):
            parser.error(
                "a unified run cannot be mixed with unsealed development stages"
            )
        result = audit_run(
            args.run, args.output, allow_development=args.allow_development
        )
    else:
        if not args.allow_development or not (
            args.development_native or args.development_structure
        ):
            parser.error(
                "provide a unified RUN or explicit --allow-development stage directories"
            )
        result = audit_development(
            args.development_native, args.development_structure, args.output
        )
    print(
        json.dumps(
            {
                "verified": result["verified"],
                "mode": result.get("qualification_mode"),
                "stages": list(result["stages"]),
                "errors": result["errors"],
                "output": str(args.output.resolve()),
            },
            sort_keys=True,
        )
    )
    if not result["verified"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
