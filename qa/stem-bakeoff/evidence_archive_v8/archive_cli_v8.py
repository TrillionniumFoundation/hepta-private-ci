"""Explicit plan, measure, pack and independently verify evidence archives."""

import argparse
import json

from archive_pack_v8 import measure, pack
from archive_plan_v8 import make_plan
from archive_verify_v8 import verify_archive


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    plan = sub.add_parser("plan")
    plan.add_argument("--roots", required=True)
    plan.add_argument("--roots-sha256", required=True)
    plan.add_argument("--output", required=True)
    for command in ("measure", "pack"):
        child = sub.add_parser(command)
        child.add_argument("--plan", required=True)
        child.add_argument("--plan-sha256", required=True)
        if command == "pack":
            child.add_argument("--output", required=True)
            child.add_argument("--max-output-bytes", required=True, type=int)
            child.add_argument("--reserve-bytes", default=64 << 20, type=int)
    verify = sub.add_parser("verify")
    verify.add_argument("--archive", required=True)
    verify.add_argument("--manifest", required=True)
    verify.add_argument("--manifest-sha256", required=True)
    verify.add_argument("--archive-sha256")
    args = parser.parse_args()
    if args.command == "plan":
        result = make_plan(args.roots, args.roots_sha256, args.output)
    elif args.command == "measure":
        result = measure(args.plan, args.plan_sha256)
    elif args.command == "pack":
        result = pack(args.plan, args.plan_sha256, args.output, args.max_output_bytes, args.reserve_bytes)
    else:
        result = verify_archive(args.archive, args.manifest, args.manifest_sha256, args.archive_sha256)
    print(json.dumps(result, sort_keys=True, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
