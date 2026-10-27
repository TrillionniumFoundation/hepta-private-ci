"""Audit one sealed unified v4 run without training or modifying its evidence."""

import argparse
import json
from pathlib import Path

import bootstrap  # noqa: F401
from v4.joint_audit import audit_joint


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--allow-development", action="store_true")
    args = parser.parse_args()
    report = audit_joint(
        args.run, args.output, allow_development=args.allow_development
    )
    print(
        json.dumps(
            {
                key: report[key]
                for key in (
                    "verified",
                    "development_only",
                    "manifest_sha256",
                    "all_scoped_joint_gates",
                    "serving_queries",
                    "replayed_hops",
                )
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
