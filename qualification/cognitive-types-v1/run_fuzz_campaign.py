#!/usr/bin/env python3
"""Run one bounded cognitive.types fuzz campaign and seal exact-source evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import resource
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Final

ROOT: Final = Path(__file__).resolve().parents[2]
TARGETS: Final[tuple[str, ...]] = (
    "hnmf_base",
    "hnmf_learning",
    "shared_experience_v2",
    "consumer_handoff",
    "canonical_json_grammar",
)
MAX_LOG_BYTES: Final = 2_000_000
MAX_SECONDS: Final = 3_600
MIN_RSS_MB: Final = 64
MAX_RSS_MB: Final = 8_192
STAT_RE: Final = re.compile(
    r"#(?P<executions>[0-9]+).*?cov:\s*(?P<coverage>[0-9]+).*?ft:\s*(?P<features>[0-9]+)",
    re.IGNORECASE,
)
FINAL_EXECUTIONS_RE: Final = re.compile(
    r"stat::number_of_executed_units:\s*(?P<executions>[0-9]+)",
    re.IGNORECASE,
)


def _run_text(command: list[str], *, check: bool = True) -> str:
    result = subprocess.run(
        command,
        cwd=ROOT,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if check and result.returncode != 0:
        raise RuntimeError(
            f"command failed ({result.returncode}): {' '.join(command)}\n"
            f"stdout: {result.stdout[-4000:]}\nstderr: {result.stderr[-4000:]}"
        )
    return result.stdout.strip()


def _git_clean() -> bool:
    return _run_text(["git", "status", "--porcelain=v1"]) == ""


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _directory_digest(path: Path) -> tuple[str, int, int]:
    if path.is_symlink() or not path.is_dir():
        raise ValueError(f"corpus must be a real directory: {path}")
    digest = hashlib.sha256()
    files = sorted(item for item in path.iterdir() if item.is_file())
    if any(item.is_symlink() for item in path.iterdir()):
        raise ValueError("symlinked corpus entries are forbidden")
    if not files:
        raise ValueError("empty corpus is not evidence")
    total = 0
    for item in files:
        data_digest = _sha256_file(item)
        size = item.stat().st_size
        digest.update(item.name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(bytes.fromhex(data_digest))
        digest.update(size.to_bytes(8, "big"))
        total += size
    return digest.hexdigest(), len(files), total


def _bounded(data: bytes) -> tuple[str, bool, str]:
    truncated = len(data) > MAX_LOG_BYTES
    selected = data[:MAX_LOG_BYTES]
    return (
        selected.decode("utf-8", errors="replace"),
        truncated,
        hashlib.sha256(data).hexdigest(),
    )


def _parse_stats(text: str) -> tuple[int, int | None, int | None]:
    executions = 0
    coverage: int | None = None
    features: int | None = None
    for match in STAT_RE.finditer(text):
        executions = max(executions, int(match.group("executions")))
        coverage = max(coverage or 0, int(match.group("coverage")))
        features = max(features or 0, int(match.group("features")))
    for match in FINAL_EXECUTIONS_RE.finditer(text):
        executions = max(executions, int(match.group("executions")))
    return executions, coverage, features


def _crash_inventory(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        return []
    if path.is_symlink() or not path.is_dir():
        raise ValueError("artifact directory must be a real directory")
    inventory: list[dict[str, object]] = []
    for item in sorted(path.iterdir()):
        if item.is_symlink() or not item.is_file():
            raise ValueError(f"unsafe artifact entry: {item}")
        inventory.append(
            {
                "name": item.name,
                "bytes": item.stat().st_size,
                "sha256": _sha256_file(item),
            }
        )
    return inventory


def run_campaign(
    target: str,
    seconds: int,
    rss_mb: int,
    corpus: Path,
    evidence: Path,
    campaign_class: str,
) -> dict[str, object]:
    if target not in TARGETS:
        raise ValueError(f"unknown target {target!r}")
    if not 1 <= seconds <= MAX_SECONDS:
        raise ValueError(f"seconds must be within 1..={MAX_SECONDS}")
    if not MIN_RSS_MB <= rss_mb <= MAX_RSS_MB:
        raise ValueError(f"rss-mb must be within {MIN_RSS_MB}..={MAX_RSS_MB}")
    if campaign_class not in {"smoke", "sustained"}:
        raise ValueError("campaign-class must be smoke or sustained")
    if evidence.exists():
        if evidence.is_symlink() or not evidence.is_dir():
            raise ValueError("evidence path must be a real directory")
        shutil.rmtree(evidence)
    evidence.mkdir(parents=True, mode=0o755)
    artifacts = evidence / "artifacts"
    artifacts.mkdir(mode=0o755)

    source_commit = _run_text(["git", "rev-parse", "HEAD"])
    source_tree = _run_text(["git", "rev-parse", "HEAD^{tree}"])
    source_clean_before = _git_clean()
    if not source_clean_before:
        raise RuntimeError("source tree is dirty before fuzz execution")
    expected_source = os.environ.get("GITHUB_HEAD_SHA") or os.environ.get("SOURCE_SHA")
    if expected_source and expected_source != source_commit:
        raise RuntimeError(
            f"checked-out source {source_commit} differs from expected {expected_source}"
        )

    corpus_sha256, seed_count, corpus_bytes = _directory_digest(corpus)
    cargo = shutil.which("cargo")
    if cargo is None:
        raise RuntimeError("cargo is unavailable")
    command = [
        cargo,
        "fuzz",
        "run",
        target,
        str(corpus),
        "--",
        f"-max_total_time={seconds}",
        f"-rss_limit_mb={rss_mb}",
        f"-artifact_prefix={artifacts}{os.sep}",
        "-print_final_stats=1",
        "-reload=0",
    ]

    fuzz_root = ROOT / "codex-rs/hepta-cognitive-types/fuzz"
    generated_lock = fuzz_root / "Cargo.lock"
    lock_existed_before = generated_lock.exists()
    lock_before_sha256 = _sha256_file(generated_lock) if lock_existed_before else None

    started_unix = int(time.time())
    started_monotonic = time.monotonic_ns()
    timed_out = False
    try:
        completed = subprocess.run(
            command,
            cwd=fuzz_root,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=seconds + 180,
        )
        return_code = completed.returncode
        stdout_bytes = completed.stdout
        stderr_bytes = completed.stderr
    except subprocess.TimeoutExpired as error:
        timed_out = True
        return_code = 124
        stdout_bytes = error.stdout or b""
        stderr_bytes = (error.stderr or b"") + b"\ncampaign process exceeded watchdog timeout\n"
    elapsed_ns = time.monotonic_ns() - started_monotonic
    completed_unix = int(time.time())
    stdout, stdout_truncated, stdout_sha256 = _bounded(stdout_bytes)
    stderr, stderr_truncated, stderr_sha256 = _bounded(stderr_bytes)
    combined = stdout + "\n" + stderr
    executions, coverage, features = _parse_stats(combined)
    crashes = _crash_inventory(artifacts)

    generated_lock_sha256: str | None = None
    if generated_lock.exists():
        generated_lock_sha256 = _sha256_file(generated_lock)
        shutil.copyfile(generated_lock, evidence / "resolved-Cargo.lock")
        if lock_existed_before:
            if generated_lock_sha256 != lock_before_sha256:
                raise RuntimeError("tracked fuzz Cargo.lock changed during campaign")
        else:
            generated_lock.unlink()

    default_artifacts = fuzz_root / "artifacts"
    if default_artifacts.exists():
        if default_artifacts.is_symlink() or not default_artifacts.is_dir():
            raise RuntimeError("unsafe default fuzz artifact path")
        # cargo-fuzz creates this directory even when artifact_prefix points to
        # the evidence directory. It must remain empty when no crash occurred.
        unexpected = [item for item in default_artifacts.rglob("*") if item.is_file()]
        if unexpected:
            raise RuntimeError("cargo-fuzz wrote crash data outside the sealed evidence path")
        shutil.rmtree(default_artifacts)

    source_clean_after = _git_clean()

    (evidence / "stdout.log").write_text(stdout, encoding="utf-8")
    (evidence / "stderr.log").write_text(stderr, encoding="utf-8")

    cargo_version = _run_text([cargo, "--version"])
    rustc_version = _run_text(["rustc", "--version", "--verbose"])
    fuzz_version = _run_text([cargo, "fuzz", "--version"])
    maximum_rss_raw = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
    # Linux reports KiB, while Darwin reports bytes. Record both the raw value
    # and a normalized best effort without using it as a pass/fail oracle.
    normalized_peak_rss_bytes = (
        maximum_rss_raw if platform.system() == "Darwin" else maximum_rss_raw * 1024
    )

    passed = (
        return_code == 0
        and not timed_out
        and not crashes
        and executions > 0
        and generated_lock_sha256 is not None
        and source_clean_after
        and not stdout_truncated
        and not stderr_truncated
    )
    receipt: dict[str, object] = {
        "schema": "hepta.cognitive-types.fuzz-campaign-receipt.v1",
        "schemaVersion": 1,
        "campaignClass": campaign_class,
        "target": target,
        "sourceCommit": source_commit,
        "sourceTree": source_tree,
        "sourceCleanBefore": source_clean_before,
        "sourceCleanAfter": source_clean_after,
        "expectedSourceCommit": expected_source,
        "corpusSha256": corpus_sha256,
        "seedCount": seed_count,
        "corpusBytes": corpus_bytes,
        "configuredSeconds": seconds,
        "configuredRssLimitMb": rss_mb,
        "startedAtUnixSeconds": started_unix,
        "completedAtUnixSeconds": completed_unix,
        "elapsedNanoseconds": str(elapsed_ns),
        "executions": executions,
        "coverageEdges": coverage,
        "featureCount": features,
        "peakRssRaw": maximum_rss_raw,
        "peakRssBytesBestEffort": normalized_peak_rss_bytes,
        "exitCode": return_code,
        "timedOut": timed_out,
        "resolvedCargoLockSha256": generated_lock_sha256,
        "sourceCargoLockExisted": lock_existed_before,
        "stdoutSha256": stdout_sha256,
        "stderrSha256": stderr_sha256,
        "stdoutTruncated": stdout_truncated,
        "stderrTruncated": stderr_truncated,
        "crashes": crashes,
        "toolchain": {
            "cargo": cargo_version,
            "rustc": rustc_version,
            "cargoFuzz": fuzz_version,
            "python": sys.version,
            "platform": platform.platform(),
        },
        "command": command,
        "passed": passed,
        "productionAuthority": False,
        "activationAuthority": False,
        "releaseAuthority": False,
    }
    receipt_bytes = (
        json.dumps(receipt, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        + "\n"
    ).encode("utf-8")
    (evidence / "receipt.json").write_bytes(receipt_bytes)
    (evidence / "receipt.sha256").write_text(
        hashlib.sha256(receipt_bytes).hexdigest() + "  receipt.json\n",
        encoding="ascii",
    )
    if not passed:
        raise RuntimeError(
            "fuzz campaign did not qualify: "
            f"exit={return_code} timeout={timed_out} executions={executions} "
            f"crashes={len(crashes)} "
            f"clean={source_clean_after} truncated={stdout_truncated or stderr_truncated}"
        )
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", choices=TARGETS, required=True)
    parser.add_argument("--seconds", type=int, required=True)
    parser.add_argument("--rss-mb", type=int, default=2048)
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--campaign-class", choices=("smoke", "sustained"), required=True)
    args = parser.parse_args()
    receipt = run_campaign(
        args.target,
        args.seconds,
        args.rss_mb,
        args.corpus.resolve(),
        args.evidence.resolve(),
        args.campaign_class,
    )
    print(json.dumps(receipt, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
