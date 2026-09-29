#!/usr/bin/env python3
"""Render and attest exact-candidate platform.types documentation and evidence."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from lane_a_foundation_lib import CANDIDATE_KINDS, VerificationError
from platform_types_candidate_evidence import (
    _validate_registry_benchmark,
    write_diagnostics,
    write_receipt,
)
from platform_types_candidate_render import render_bundle
from platform_types_candidate_support import CandidateBundleError, parse_named_values


def add_identity_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--candidate-kind", choices=sorted(CANDIDATE_KINDS), required=True)
    parser.add_argument("--expected-sha", required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--base-sha")
    parser.add_argument("--pr-number", type=int)


def _benchmark_fixture(*, threshold: int | None = None) -> dict:
    fields = {
        "constructionElapsedNs": 1,
        "constructionNsPerEntry": 1,
        "identityElapsedNs": 1,
        "identityNsPerLookup": 1,
        "digestElapsedNs": 1,
        "digestNsPerLookup": 1,
        "registryIdentityElapsedNs": 1,
        "registryIdentityNsPerLookup": 1,
    }
    return {
        "schema": "hepta.platform-types.registry-lookup-benchmark.v1",
        "schemaVersion": 1,
        "iterationsPerLookup": 1,
        "acceptanceThreshold": threshold,
        "cases": [
            {"entryCount": 8, **fields},
            {"entryCount": 256, **fields},
        ],
    }


def self_test() -> None:
    outcomes = parse_named_values(["truth=success", "miri=failure"], outcomes=True)
    if outcomes != {"truth": "success", "miri": "failure"}:
        raise CandidateBundleError("named outcome parser drift")
    try:
        parse_named_values(["truth=green"], outcomes=True)
    except CandidateBundleError:
        pass
    else:
        raise CandidateBundleError("invalid outcome accepted")

    _validate_registry_benchmark(_benchmark_fixture())
    try:
        _validate_registry_benchmark(_benchmark_fixture(threshold=10))
    except CandidateBundleError:
        return
    raise CandidateBundleError("unearned registry benchmark threshold accepted")


def main() -> int:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)

    render = commands.add_parser("render")
    add_identity_arguments(render)
    render.add_argument("--output-dir", type=Path, required=True)

    diagnostics = commands.add_parser("diagnostics")
    add_identity_arguments(diagnostics)
    diagnostics.add_argument("--outcome", action="append", default=[], required=True)
    diagnostics.add_argument("--evidence", action="append", default=[], required=True)
    diagnostics.add_argument("--output", type=Path, required=True)

    receipt = commands.add_parser("receipt")
    add_identity_arguments(receipt)
    receipt.add_argument("--outcome", action="append", default=[], required=True)
    receipt.add_argument("--evidence", action="append", default=[], required=True)
    receipt.add_argument("--msrv-toolchain", required=True)
    receipt.add_argument("--miri-toolchain", required=True)
    receipt.add_argument("--output", type=Path, required=True)

    commands.add_parser("self-test")
    args = parser.parse_args()
    try:
        if args.command == "render":
            render_bundle(args)
        elif args.command == "diagnostics":
            write_diagnostics(args)
        elif args.command == "receipt":
            write_receipt(args)
        else:
            self_test()
    except (CandidateBundleError, VerificationError, OSError, ValueError) as error:
        print(f"platform.types candidate bundle failed: {error}", file=sys.stderr)
        return 1
    print(f"platform.types candidate bundle {args.command}: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
