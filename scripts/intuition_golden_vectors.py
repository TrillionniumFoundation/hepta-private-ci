#!/usr/bin/env python3
"""Independent Python encoder for the checked-in intuition V2 golden contract.

No Rust subprocess, generated digest, or fixture rewrite is used to compute the
expected bytes. This checks the deterministic fixture; it is not a benchmark,
production acceptance receipt, or evidence of randomized-path coverage.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
import random


def digest(value: bytes) -> bytes:
    return hashlib.sha256(value).digest()


def text(value: str) -> bytes:
    if not isinstance(value, str) or not value:
        raise ValueError("expected nonempty UTF-8 text")
    return value.encode("utf-8")


def integer(value: int, bits: int, signed: bool = False) -> bytes:
    if type(value) is not int:
        raise ValueError("integer fields reject booleans and non-integers")
    return value.to_bytes(bits // 8, "big", signed=signed)


def probability(value: int) -> bytes:
    if type(value) is not int or not 0 <= value <= 1 << 32:
        raise ValueError("ProbabilityQ32 out of range")
    return integer(value, 64)


def flag(value: bool) -> bytes:
    if type(value) is not bool:
        raise ValueError("expected a boolean")
    return bytes([int(value)])


def compute(fixture: dict) -> dict[str, str]:
    if fixture["assignmentMode"] != "deterministic":
        raise ValueError("this golden schema covers deterministic assignment only")
    name = text(fixture["candidateId"])
    stable_id = integer(len(name), 32) + name
    count = integer(1, 32)
    identity = digest(
        b"hepta.intuition.candidate-identity.v2\0" + count + stable_id
        + flag(fixture["legal"]) + flag(fixture["hardVeto"])
        + digest(text(fixture["supportLabel"]))
    )
    scores = digest(
        b"hepta.intuition.scored-outputs.v2\0" + identity + count + stable_id
        + integer(fixture["utilityRawI64"], 64, signed=True)
        + probability(fixture["confidenceRawU64"])
        + probability(fixture["oodRawU64"])
    )
    distribution = digest(
        b"hepta.intuition.assignment-distribution.v2\0" + identity + count + stable_id
        + probability(fixture["assignmentProbabilityRawU64"])
        + b"\0" + integer(0, 64)
    )
    generation = fixture["policyGenerationU64"]
    if type(generation) is not int or generation <= 0:
        raise ValueError("policy generation must be nonzero")
    scoring = digest(
        b"hepta.intuition.scoring-commitment.v2\0"
        + b"".join(digest(text(fixture[key])) for key in (
            "modelLabel", "featureSnapshotLabel", "featureSchemaLabel", "scorerContractLabel"
        ))
        + identity + scores + digest(text(fixture["policyLabel"]))
        + integer(generation, 64)
    )
    assignment = digest(b"hepta.intuition.assignment-commitment.v2\0" + b"\0" + distribution)
    return {key: value.hex() for key, value in (
        ("candidateIdentityV2", identity), ("scoredOutputsV2", scores),
        ("assignmentDistributionV2", distribution), ("scoringCommitmentV2", scoring),
        ("assignmentCommitmentV2", assignment)
    )}


def unique_object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON field: " + key)
        result[key] = value
    return result


def verify(path: Path) -> dict:
    document = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique_object)
    if document["schema"] != "hepta.intuition.production-contract-golden.v1":
        raise ValueError("unsupported golden schema")
    actual = compute(document["fixture"])
    if actual != document["digests"]:
        raise ValueError("golden mismatch: " + json.dumps(actual, sort_keys=True))
    rng = random.Random(20260927)
    baseline = document["fixture"]
    mutations = 0
    for _ in range(256):
        fixture = copy.deepcopy(baseline)
        fixture["utilityRawI64"] = rng.randrange(-(1 << 63), 1 << 63)
        fixture["confidenceRawU64"] = rng.randrange((1 << 32) + 1)
        fixture["oodRawU64"] = rng.randrange((1 << 32) + 1)
        changed = compute(fixture)
        for key in ("candidateIdentityV2", "assignmentDistributionV2", "assignmentCommitmentV2"):
            if changed[key] != actual[key]:
                raise ValueError("scorer field leaked into " + key)
        if changed["scoredOutputsV2"] == actual["scoredOutputsV2"]:
            raise ValueError("scorer mutation was not bound")
        fixture = copy.deepcopy(baseline)
        fixture["assignmentProbabilityRawU64"] = rng.randrange(1, (1 << 32) + 1)
        changed = compute(fixture)
        for key in ("candidateIdentityV2", "scoredOutputsV2", "scoringCommitmentV2"):
            if changed[key] != actual[key]:
                raise ValueError("assignment field leaked into " + key)
        if changed["assignmentDistributionV2"] == actual["assignmentDistributionV2"]:
            raise ValueError("assignment mutation was not bound")
        mutations += 2
    return {"goldenDigestsVerified": len(actual), "ownerSeparationMutations": mutations}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("fixture", type=Path)
    args = parser.parse_args()
    print(json.dumps(verify(args.fixture), sort_keys=True))


if __name__ == "__main__":
    main()
