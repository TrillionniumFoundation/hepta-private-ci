"""Explicit freeze / fit / final entry point; no automatic retry or reselection."""

import argparse
import json

import torch

from .protocol import execute, freeze


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("freeze", "fit", "final"))
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--plan")
    parser.add_argument("--source-manifest")
    parser.add_argument("--registry")
    parser.add_argument("--output")
    parser.add_argument("--selection-sha256")
    args = parser.parse_args()
    torch.set_num_threads(1)
    if torch.get_num_interop_threads() != 1:
        torch.set_num_interop_threads(1)
    if args.phase == "freeze":
        if not all((args.plan, args.source_manifest, args.registry)):
            parser.error("freeze requires plan, source-manifest and registry")
        result = freeze(args.plan, args.source_manifest, args.manifest, args.registry)
    else:
        if not args.output:
            parser.error("fit/final require output")
        result = execute(args.manifest, args.output, args.phase, args.selection_sha256)
    print(json.dumps(result, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
