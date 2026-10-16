"""Create-only E12 Cell handoff bundles and independent-process audits.

No selected weights, authority, new source labels or user payloads are emitted.
"""

from dataclasses import asdict, fields
from hashlib import sha256
import argparse
import json

from e12_nonlinear_cert import Law
from e12_cell_boundary import (CellSegment, SegmentBundle, TerminalCell,
                               review_segments, split_result)
from e12_study import PROFILES, _decode_cert, read_strict, write_once

SCHEMA = "hepta.e12.local-global-cell-boundary.v1"


def _scope(original_source_sha: str) -> str:
    return sha256((SCHEMA + "\n" + original_source_sha).encode()).hexdigest()


def _source(path: str, expected_sha: str):
    obj, digest = read_strict(path)
    if type(expected_sha) is not str or expected_sha != digest:
        raise ValueError("E12 source changed after freeze")
    expected = {
        "schema", "authority", "complete_registered_profiles", "repeat_count",
        "real_pretrained_encoder_forwards", "independent_natural_task_outcomes",
        "full_lifecycle_cost_or_target_host_attested", "continuous_time_fbsde_proven",
        "cost_adjusted_online_reasoning_gain", "production_accepted", "rows",
    }
    if (type(obj) is not dict or set(obj) != expected or
        obj["schema"] != "hepta.e12.nonlinear-stochastic-certified-study.v1" or
        obj["authority"] != "DENY_ALL" or obj["complete_registered_profiles"] is not True or
        type(obj["repeat_count"]) is not int or obj["repeat_count"] != 6 or
        type(obj["real_pretrained_encoder_forwards"]) is not int or
        obj["real_pretrained_encoder_forwards"] != 0 or
        any(obj[k] is not False for k in (
            "production_accepted", "independent_natural_task_outcomes",
            "full_lifecycle_cost_or_target_host_attested", "continuous_time_fbsde_proven",
            "cost_adjusted_online_reasoning_gain")) or
        type(obj["rows"]) is not list or len(obj["rows"]) != len(PROFILES)):
        raise ValueError("not a complete original E12 DENY_ALL source")
    return obj, digest


def produce(source: str, expected_sha: str, output: str) -> str:
    study, digest = _source(source, expected_sha)
    scope = _scope(digest)
    cases = []
    for row, (depth, a) in zip(study["rows"], PROFILES):
        if type(row) is not dict or row.get("profile") != asdict(Law(depth=depth, a=a)):
            raise ValueError("changed preregistered E12 study source")
        law = Law(depth=depth, a=a)
        result = _decode_cert(row["certificate"])
        bundle = split_result(law, result, scope)
        cases.append({"depth": depth, "coupling": a, "bundle": asdict(bundle)})
    return write_once(output, {
        "schema": SCHEMA,
        "source_sha256": digest,
        "scope_digest": scope,
        "cases": cases,
        "authority": "DENY_ALL",
        "producer_has_verified_global_solution": False,
        "natural_reasoning_gain_proven": False,
        "production_accepted": False,
    })


def _decode_bundle(raw: dict) -> SegmentBundle:
    if type(raw) is not dict or set(raw) != {f.name for f in fields(SegmentBundle)}:
        raise ValueError("invalid complete Cell boundary bundle")
    if type(raw["segments"]) is not list or type(raw["terminals"]) is not list:
        raise ValueError("invalid Cell boundary transport shape")
    segments = []
    for entry in raw["segments"]:
        if type(entry) is not dict or set(entry) != {f.name for f in fields(CellSegment)}:
            raise ValueError("invalid Cell segment")
        segments.append(CellSegment(**entry))
    terminals = []
    for entry in raw["terminals"]:
        if type(entry) is not dict or set(entry) != {f.name for f in fields(TerminalCell)}:
            raise ValueError("invalid terminal Cell")
        terminals.append(TerminalCell(**entry))
    return SegmentBundle(**{**raw, "segments": tuple(segments),
                            "terminals": tuple(terminals)})


def review(source: str, expected_source_sha: str, candidate: str,
           expected_candidate_sha: str, output: str) -> str:
    study, source_sha = _source(source, expected_source_sha)
    proposal, candidate_sha = read_strict(candidate)
    if (candidate_sha != expected_candidate_sha or type(proposal) is not dict or set(proposal) != {
        "schema", "source_sha256", "scope_digest", "cases", "authority",
        "producer_has_verified_global_solution", "natural_reasoning_gain_proven",
        "production_accepted",
    } or proposal["schema"] != SCHEMA or proposal["source_sha256"] != source_sha or
        proposal["scope_digest"] != _scope(source_sha) or proposal["authority"] != "DENY_ALL" or
        proposal["producer_has_verified_global_solution"] is not False or
        proposal["natural_reasoning_gain_proven"] is not False or
        proposal["production_accepted"] is not False or
        type(proposal["cases"]) is not list or len(proposal["cases"]) != len(PROFILES)):
        raise ValueError("changed Cell candidate source/shape or fabricated authority")
    reviews = []
    for entry, row, (depth, a) in zip(proposal["cases"], study["rows"], PROFILES):
        if (type(entry) is not dict or set(entry) != {"depth", "coupling", "bundle"} or
            type(entry["depth"]) is not int or entry["depth"] != depth or entry["coupling"] != a):
            raise ValueError("mismatched finite stochastic study arm")
        if type(row) is not dict or row.get("profile") != asdict(Law(depth=depth, a=a)):
            raise ValueError("mismatched original E12 law")
        law = Law(depth=depth, a=a)
        original = _decode_cert(row["certificate"])
        certification = review_segments(law, original, _decode_bundle(entry["bundle"]),
                                        proposal["scope_digest"])
        reviews.append({"depth": depth, "coupling": a, "review": asdict(certification)})
    return write_once(output, {
        "schema": SCHEMA + ".independent-review",
        "source_sha256": source_sha,
        "candidate_sha256": candidate_sha,
        "whole_public_prefix_graph_checked": True,
        "cases": reviews,
        "all_local_global_boundaries_qualified_for_finite_discrete_laws": True,
        "source_and_model_owner_authenticated": False,
        "general_continuous_fbsde_or_reasoning_gain_proven": False,
        "production_accepted": False,
        "authority": "DENY_ALL",
    })


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="mode", required=True)
    first = sub.add_parser("produce")
    first.add_argument("--source", required=True)
    first.add_argument("--source-sha256", required=True)
    first.add_argument("--output", required=True)
    second = sub.add_parser("review")
    second.add_argument("--source", required=True)
    second.add_argument("--source-sha256", required=True)
    second.add_argument("--candidate", required=True)
    second.add_argument("--candidate-sha256", required=True)
    second.add_argument("--output", required=True)
    args = parser.parse_args()
    if args.mode == "produce":
        digest = produce(args.source, args.source_sha256, args.output)
    else:
        digest = review(args.source, args.source_sha256, args.candidate,
                        args.candidate_sha256, args.output)
    print(json.dumps({"mode": args.mode, "sha256": digest, "authority": "DENY_ALL"},
                     sort_keys=True))


if __name__ == "__main__":
    main()
