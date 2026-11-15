#!/usr/bin/env python3
"""Generate actual checkout paths without selecting an arithmetic policy."""
import argparse
import json
from pathlib import Path

from unified_policy_ci import configure, require


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--rustc", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--receipt-root", type=Path, required=True)
    parser.add_argument("--bind-input", type=Path, action="append", default=[])
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--github-env", type=Path)
    args = parser.parse_args()
    require(not args.report.exists(), "refusing to overwrite a configuration report")
    report = configure(args.repo, args.rustc, args.config, args.receipt_root, args.bind_input)
    if args.github_env:
        for key, value in report["environment"].items():
            require(not any(c in key + value for c in "\r\n\0"), "unsafe environment-file value")
        with args.github_env.open("a") as stream:
            for key, value in report["environment"].items():
                stream.write(key + "=" + value + "\n")
    args.report.parent.mkdir(parents=True, exist_ok=True)
    with args.report.open("x") as stream:
        json.dump(report, stream, indent=2)
        stream.write("\n")
    print(json.dumps({"passed": True, "report": str(args.report.resolve())}))


if __name__ == "__main__":
    main()
