#!/usr/bin/env python3
"""Validate exact-candidate release recovery measurements, never certify an SLO.

The measurement executable owns the observations. This read-only gate checks
identity, workload coverage and honest resource/fixture declarations. Command
success, report validity and independently approved target-host SLOs are distinct.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat

MAX_REPORT_BYTES = 1024 * 1024
FIELDS = {"schema", "sourceCommit", "testedCommit", "testedTree", "debugAssertions", "records",
          "repetitions", "initialAnchorAcquisitionUs", "initialAnchorHeldTransactionUs", "runs",
          "samplingIntervalMs", "sampleCount", "rssPeakSampledBytes", "rootBaselineBytes",
          "rootPeakSampledBytes", "additionalDiskPeakSampledBytes", "fixtureAuthorityVerificationUs",
          "claimBoundary"}
RUN_FIELDS = {"iteration", "descriptorRecoveryUs", "anchorAcquisitionUs", "anchorHeldTransactionUs",
              "pageUs", "retainedRecords", "rootBytesIncludingRetainedGenerations", "activeDatabaseBytes",
              "exactCutPreserved"}
BOUNDARY = {"sampledPeaksAreLowerBounds": True, "authorityIsFixture": True,
            "targetHostQualified": False, "destructivePruningPerformed": False, "physicalErasureProved": False}


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise ValueError(reason)


def integer(value: object, minimum: int = 0, maximum: int = (1 << 64) - 2) -> int:
    require(type(value) is int and minimum <= value <= maximum, "invalid or saturated measurement integer")
    return value


def oid(value: str) -> None:
    require(isinstance(value, str) and re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", value) is not None
            and set(value) != {"0"}, "invalid exact Git identity")


def validate(report: dict, *, source_commit: str, tested_commit: str, tested_tree: str,
             records: int, minimum_repetitions: int = 3, require_rss: bool = False) -> dict:
    for value in (source_commit, tested_commit, tested_tree):
        oid(value)
    integer(records, 1, 16384)
    integer(minimum_repetitions, 3, 32)
    require(isinstance(report, dict) and set(report) == FIELDS, "missing or unknown recovery report field")
    require(report["schema"] == "hepta.cognitive-store-recovery-perf.v1", "unsupported recovery report")
    for key, value in (("sourceCommit", source_commit), ("testedCommit", tested_commit), ("testedTree", tested_tree)):
        require(report[key] == value, "recovery report belongs to another candidate: " + key)
    require(report["debugAssertions"] is False, "release measurement was not built with the release profile")
    require(integer(report["records"], 1, 16384) == records, "recovery workload differs from required profile")
    repetitions = integer(report["repetitions"], minimum_repetitions, 32)
    require(isinstance(report["runs"], list) and len(report["runs"]) == repetitions,
            "recovery repetitions are incomplete")
    boundary = report["claimBoundary"]
    require(isinstance(boundary, dict) and set(boundary) == set(BOUNDARY) and
            all(boundary[key] is value for key, value in BOUNDARY.items()),
            "measurement escalated fixture, sampled peak, pruning, erasure or host claims")
    for key in ("initialAnchorAcquisitionUs", "initialAnchorHeldTransactionUs"):
        integer(report[key])
    integer(report["samplingIntervalMs"], 1)
    integer(report["sampleCount"], 1)
    for key in ("rootBaselineBytes", "rootPeakSampledBytes"):
        integer(report[key], 1)
    delta = integer(report["additionalDiskPeakSampledBytes"])
    require(delta == max(0, report["rootPeakSampledBytes"] - report["rootBaselineBytes"]),
            "sampled additional-disk accounting is inconsistent")
    rss = report["rssPeakSampledBytes"]
    require(not require_rss or rss is not None, "required Linux RSS observation is absent")
    if rss is not None:
        integer(rss, 1)
    timings = report["fixtureAuthorityVerificationUs"]
    require(isinstance(timings, list) and 2 * repetitions <= len(timings) <= 32 * repetitions,
            "initial and final-use verifier observations are incomplete or unbounded")
    for duration in timings:
        integer(duration)
    for index, run in enumerate(report["runs"]):
        require(isinstance(run, dict) and set(run) == RUN_FIELDS, "incomplete recovery iteration")
        require(integer(run["iteration"], 0, 31) == index, "recovery iteration duplicated or reordered")
        require(integer(run["retainedRecords"], 1, 16384) == records, "recovery lost or duplicated records")
        require(run["exactCutPreserved"] is True, "recovery did not preserve the exact owner cut")
        for key in ("descriptorRecoveryUs", "anchorAcquisitionUs", "anchorHeldTransactionUs"):
            integer(run[key])
        require(integer(run["rootBytesIncludingRetainedGenerations"], 1) >=
                integer(run["activeDatabaseBytes"], 1), "active database exceeds measured directory bytes")
        pages = run["pageUs"]
        require(isinstance(pages, list) and len(pages) == (records + 511) // 512,
                "512-head paging workload is incomplete")
        for duration in pages:
            integer(duration)
    # A sampled peak MAY be lower than an independently observed endpoint. Do
    # not upgrade a sample to a peak guarantee or manufacture percentile SLOs.
    return {"schema": "hepta.cognitive.recovery-report-validation.v1", "result": "valid_measurement",
            "sourceCommit": source_commit, "testedCommit": tested_commit, "testedTree": tested_tree,
            "records": records, "repetitions": repetitions, "targetHostQualified": False,
            "sloAccepted": False, "sampledPeaksAreLowerBounds": True}


def no_duplicates(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "duplicate JSON report field")
        result[key] = value
    return result


def no_float(value):
    raise ValueError("floating point or nonfinite recovery measurement")


def load_report(path: Path) -> tuple[dict, str]:
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    with os.fdopen(descriptor, "rb") as stream:
        before = os.fstat(stream.fileno())
        require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and
                0 < before.st_size <= MAX_REPORT_BYTES, "invalid or oversized recovery report file")
        content = stream.read(MAX_REPORT_BYTES + 1)
        after = os.fstat(stream.fileno())
        current = path.stat(follow_symlinks=False)
        def identity(value):
            return value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns
        require(identity(before) == identity(after) == identity(current), "recovery report changed while reading")
    require(len(content) <= MAX_REPORT_BYTES, "recovery report exceeds byte budget")
    return json.loads(content, object_pairs_hook=no_duplicates, parse_float=no_float,
                      parse_constant=no_float), hashlib.sha256(content).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--tested-commit", required=True)
    parser.add_argument("--tested-tree", required=True)
    parser.add_argument("--records", required=True, type=int)
    parser.add_argument("--minimum-repetitions", type=int, default=3)
    parser.add_argument("--require-rss", action="store_true")
    args = parser.parse_args()
    report, report_digest = load_report(args.report)
    result = validate(report, source_commit=args.source_commit, tested_commit=args.tested_commit,
                      tested_tree=args.tested_tree, records=args.records,
                      minimum_repetitions=args.minimum_repetitions, require_rss=args.require_rss)
    print(json.dumps({**result, "reportSha256": report_digest}, sort_keys=True))


if __name__ == "__main__":
    main()
