#!/usr/bin/env python3
"""Verify the complete five-target cognitive.types fuzz receipt matrix."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Final

TARGETS: Final[tuple[str, ...]] = (
    "hnmf_base",
    "hnmf_learning",
    "shared_experience_v2",
    "consumer_handoff",
    "canonical_json_grammar",
)
SHA: Final = re.compile(r"[0-9a-f]{40,64}")
SHA256: Final = re.compile(r"[0-9a-f]{64}")
MAX_RECEIPT_BYTES: Final = 2 * 1024 * 1024
MAX_LOG_BYTES: Final = 2_000_000


class EvidenceError(ValueError):
    """Missing, inconsistent, unsafe, or incomplete fuzz evidence."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise EvidenceError(message)


def no_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        require(key not in result, f"duplicate JSON key: {key}")
        result[key] = value
    return result


def no_nonfinite_number(value: str) -> None:
    raise EvidenceError(f"nonfinite JSON number: {value}")


def file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def regular_file(directory: Path, name: str, maximum: int | None = None) -> Path:
    require(
        Path(name).name == name and name not in {"", ".", ".."},
        "unsafe evidence filename",
    )
    path = directory / name
    require(
        not path.is_symlink() and path.is_file(),
        f"missing or symlinked evidence: {name}",
    )
    if maximum is not None:
        require(path.stat().st_size <= maximum, f"oversize evidence: {name}")
    return path


def load_receipt(directory: Path) -> tuple[dict[str, object], str]:
    path = regular_file(directory, "receipt.json", MAX_RECEIPT_BYTES)
    data = path.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    sidecar = regular_file(directory, "receipt.sha256", 128).read_text(
        encoding="ascii"
    )
    require(sidecar == f"{digest}  receipt.json\n", "receipt digest sidecar mismatch")
    receipt = json.loads(
        data,
        object_pairs_hook=no_duplicate_keys,
        parse_constant=no_nonfinite_number,
    )
    require(isinstance(receipt, dict), "receipt must be a JSON object")
    return receipt, digest


def integer(receipt: dict[str, object], field: str, minimum: int = 0) -> int:
    value = receipt.get(field)
    require(type(value) is int and value >= minimum, f"invalid {field}")
    return value


def nonempty_text(receipt: dict[str, object], field: str) -> str:
    value = receipt.get(field)
    require(isinstance(value, str) and bool(value), f"invalid {field}")
    return value


def verify_target(
    directory: Path,
    target: str,
    source: str,
    campaign_class: str,
    expected_seconds: int,
    expected_rss_mb: int,
) -> dict[str, object]:
    require(
        not directory.is_symlink() and directory.is_dir(),
        f"missing artifact directory: {directory.name}",
    )
    for item in directory.rglob("*"):
        require(not item.is_symlink(), f"symlinked fuzz evidence: {item}")

    receipt, receipt_digest = load_receipt(directory)
    require(
        receipt.get("schema")
        == "hepta.cognitive-types.fuzz-campaign-receipt.v1",
        "wrong receipt schema",
    )
    require(receipt.get("schemaVersion") == 1, "wrong receipt schema version")
    require(receipt.get("target") == target, "target substitution")
    require(receipt.get("campaignClass") == campaign_class, "campaign class mismatch")
    require(receipt.get("sourceCommit") == source, "source commit mismatch")
    require(receipt.get("expectedSourceCommit") == source, "expected source mismatch")
    source_tree = nonempty_text(receipt, "sourceTree")
    require(SHA.fullmatch(source_tree) is not None, "invalid source tree")
    require(receipt.get("sourceCleanBefore") is True, "dirty source before campaign")
    require(receipt.get("sourceCleanAfter") is True, "dirty source after campaign")

    corpus_sha = nonempty_text(receipt, "corpusSha256")
    require(SHA256.fullmatch(corpus_sha) is not None, "invalid corpus digest")
    seed_count = integer(receipt, "seedCount", 1)
    corpus_bytes = integer(receipt, "corpusBytes", 0)
    require(
        receipt.get("configuredSeconds") == expected_seconds,
        "configured duration mismatch",
    )
    require(
        receipt.get("configuredRssLimitMb") == expected_rss_mb,
        "configured RSS mismatch",
    )

    started = integer(receipt, "startedAtUnixSeconds", 1)
    completed = integer(receipt, "completedAtUnixSeconds", 1)
    require(started <= completed, "campaign time ordering mismatch")
    elapsed = nonempty_text(receipt, "elapsedNanoseconds")
    require(
        elapsed.isascii() and elapsed.isdigit() and int(elapsed) > 0,
        "invalid elapsed time",
    )

    executions = integer(receipt, "executions", 1)
    coverage = integer(receipt, "coverageEdges", 1)
    features = integer(receipt, "featureCount", 1)
    peak_rss = integer(receipt, "peakRssBytesBestEffort", 1)
    integer(receipt, "peakRssRaw", 1)

    require(receipt.get("exitCode") == 0, "nonzero fuzz exit")
    require(receipt.get("timedOut") is False, "campaign timed out")
    crashes = receipt.get("crashes")
    require(isinstance(crashes, list), "invalid crash inventory")
    crash_hasher = hashlib.sha256()
    for crash in crashes:
        require(isinstance(crash, dict), "invalid crash entry")
        name = crash.get("name")
        digest = crash.get("sha256")
        size = crash.get("bytes")
        require(isinstance(name, str) and bool(name), "invalid crash name")
        require(
            isinstance(digest, str) and SHA256.fullmatch(digest) is not None,
            "invalid crash digest",
        )
        require(type(size) is int and size >= 0, "invalid crash size")
        crash_hasher.update(name.encode("utf-8"))
        crash_hasher.update(b"\0")
        crash_hasher.update(bytes.fromhex(digest))
        crash_hasher.update(size.to_bytes(8, "big"))
    crash_set = crash_hasher.hexdigest()
    require(not crashes, "crash artifacts present")
    require(receipt.get("passed") is True, "campaign did not pass")
    for field in ("productionAuthority", "activationAuthority", "releaseAuthority"):
        require(receipt.get(field) is False, f"unexpected authority claim: {field}")
    for field in ("stdoutTruncated", "stderrTruncated"):
        require(receipt.get(field) is False, f"truncated campaign log: {field}")

    stdout = regular_file(directory, "stdout.log", MAX_LOG_BYTES)
    stderr = regular_file(directory, "stderr.log", MAX_LOG_BYTES)
    require(receipt.get("stdoutSha256") == file_digest(stdout), "stdout digest mismatch")
    require(receipt.get("stderrSha256") == file_digest(stderr), "stderr digest mismatch")
    resolved_lock = regular_file(directory, "resolved-Cargo.lock")
    lock_digest = nonempty_text(receipt, "resolvedCargoLockSha256")
    require(SHA256.fullmatch(lock_digest) is not None, "invalid lock digest")
    require(lock_digest == file_digest(resolved_lock), "resolved lock digest mismatch")

    toolchain = receipt.get("toolchain")
    require(isinstance(toolchain, dict), "missing toolchain identity")
    for field in ("cargo", "rustc", "cargoFuzz", "python", "platform"):
        require(
            isinstance(toolchain.get(field), str) and bool(toolchain[field]),
            f"missing toolchain field: {field}",
        )

    command = receipt.get("command")
    require(
        isinstance(command, list) and all(isinstance(arg, str) for arg in command),
        "invalid command",
    )
    require(
        len(command) >= 9 and command[1:4] == ["fuzz", "run", target],
        "fuzz command substitution",
    )
    require(
        f"-max_total_time={expected_seconds}" in command,
        "duration flag substitution",
    )
    require(f"-rss_limit_mb={expected_rss_mb}" in command, "RSS flag substitution")
    require(
        "-print_final_stats=1" in command and "-reload=0" in command,
        "missing deterministic fuzz flags",
    )

    return {
        "target": target,
        "artifact": directory.name,
        "receiptSha256": receipt_digest,
        "sourceTree": source_tree,
        "corpusSha256": corpus_sha,
        "seedCount": seed_count,
        "corpusBytes": corpus_bytes,
        "executions": executions,
        "coverageEdges": coverage,
        "featureCount": features,
        "peakRssBytesBestEffort": peak_rss,
        "crashSetSha256": crash_set,
    }


def verify_matrix(
    evidence: Path,
    source: str,
    campaign_class: str,
    expected_seconds: int,
    expected_rss_mb: int,
) -> dict[str, object]:
    require(SHA.fullmatch(source) is not None, "full source SHA required")
    require(campaign_class in {"smoke", "sustained"}, "invalid campaign class")
    require(expected_seconds > 0, "positive expected duration required")
    require(expected_rss_mb > 0, "positive expected RSS required")
    require(not evidence.is_symlink() and evidence.is_dir(), "missing evidence root")

    expected = {
        f"cognitive-types-fuzz-{target}-{source}": target for target in TARGETS
    }
    actual = {item.name for item in evidence.iterdir()}
    require(
        actual == set(expected),
        "incomplete, duplicate, or unexpected fuzz artifact matrix",
    )

    verified = [
        verify_target(
            evidence / artifact,
            target,
            source,
            campaign_class,
            expected_seconds,
            expected_rss_mb,
        )
        for artifact, target in expected.items()
    ]
    source_trees = {row["sourceTree"] for row in verified}
    require(len(source_trees) == 1, "campaigns did not execute the same source tree")
    matrix_digest = hashlib.sha256()
    for row in verified:
        matrix_digest.update(row["target"].encode("utf-8"))
        matrix_digest.update(b"\0")
        matrix_digest.update(bytes.fromhex(row["receiptSha256"]))

    return {
        "schema": "hepta.cognitive-types.verified-fuzz-matrix.v1",
        "schemaVersion": 1,
        "qualificationPassed": True,
        "sourceCommit": source,
        "sourceTree": verified[0]["sourceTree"],
        "campaignClass": campaign_class,
        "configuredSeconds": expected_seconds,
        "configuredRssLimitMb": expected_rss_mb,
        "matrixSha256": matrix_digest.hexdigest(),
        "targets": verified,
        "productionAuthority": False,
        "activationAuthority": False,
        "releaseAuthority": False,
    }


def write_report(output: Path, report: dict[str, object]) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    data = (json.dumps(report, indent=2, sort_keys=True) + "\n").encode("utf-8")
    output.write_bytes(data)
    output.with_suffix(".sha256").write_text(
        hashlib.sha256(data).hexdigest() + "\n",
        encoding="ascii",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--source", required=True)
    parser.add_argument("--campaign-class", choices=("smoke", "sustained"), required=True)
    parser.add_argument("--expected-seconds", type=int, required=True)
    parser.add_argument("--expected-rss-mb", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        report = verify_matrix(
            args.evidence.resolve(),
            args.source,
            args.campaign_class,
            args.expected_seconds,
            args.expected_rss_mb,
        )
    except (OSError, ValueError, TypeError, KeyError) as error:
        report = {
            "schema": "hepta.cognitive-types.verified-fuzz-matrix.v1",
            "schemaVersion": 1,
            "qualificationPassed": False,
            "sourceCommit": args.source,
            "error": f"{type(error).__name__}: {error}",
            "productionAuthority": False,
            "activationAuthority": False,
            "releaseAuthority": False,
        }
        print(report["error"])
    write_report(args.output.resolve(), report)
    return 0 if report["qualificationPassed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
