#!/usr/bin/env python3
"""Run and validate the target-host Cell Split qualification matrix.

The matrix evaluates a four-dimensional factor grid at 64, 256, 1024, and
4096 Cells (64 unique cases). Single-count runs are diagnostics only.
Every row receives the same frozen workload digest.  A row is accepted
only after the workload emits measured metrics and an independent observer
returns a receipt binding the case, source commit, workload and metric digest.
This harness never grants execution authority; the report is DENY_ALL evidence
for a later human/host gate.
"""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import math
import os
import platform
import re
import selectors
import secrets
import shlex
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any


SCHEMA = "hepta.cell-split.target-matrix.v1"
AUTHORITY = "DENY_ALL"
OBSERVER_SCHEMA = "hepta.cell-split.observer.ed25519.v1"
MAX_CHILD_CAPTURE_BYTES = 1 << 20
OBSERVER_RECEIPT_KEYS = frozenset(
    {
        "schema",
        "verified",
        "sourceCommit",
        "workloadDigest",
        "reportDigest",
        "metricsDigest",
        "observerId",
        "signatureHex",
    }
)
MATRIX_REPORT_KEYS = frozenset(
    {
        "schema",
        "authority",
        "cellCounts",
        "sourceCommit",
        "workloadDigest",
        "workloadSourceDigest",
        "host",
        "cases",
        "observer",
        "blockingCases",
        "status",
        "reportDigest",
    }
)
CELL_COUNTS: tuple[int, ...] = (64, 256, 1024, 4096)
FACTORS: tuple[tuple[str, tuple[str, str]], ...] = (
    ("encoder_topology", ("shared", "replicated")),
    ("execution", ("scalar", "batch")),
    ("feature_materialization", ("rematerialize", "snapshot_reuse")),
    ("persistence", ("full_snapshot", "incremental_wal")),
)
REQUIRED_METRICS = (
    "p50Micros",
    "p95Micros",
    "p99Micros",
    "throughputPerSecond",
    "cpuMicros",
    "rssBytes",
    "gpuObserved",
    "gpuMicros",
    "gpuBytes",
    "communicationBytes",
    "fsyncCount",
    "walBytes",
    "walFsyncCount",
    "lockWaitMicros",
    "recoveryMicros",
    "negativeMigrationQ32",
)


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode()


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def matrix_cases(cell_count: int | None = None) -> list[dict[str, Any]]:
    if cell_count is not None and cell_count not in CELL_COUNTS:
        raise ValueError("unsupported Cell count")
    names = [name for name, _ in FACTORS]
    choices = [values for _, values in FACTORS]
    counts = CELL_COUNTS if cell_count is None else (cell_count,)
    cases: list[dict[str, Any]] = []
    for count in counts:
        for index, values in enumerate(itertools.product(*choices), start=1):
            case: dict[str, Any] = {
                "caseId": f"cell-split-c{count:04d}-{index:02d}",
                "cellCount": count,
            }
            case.update(dict(zip(names, values, strict=True)))
            cases.append(case)
    return cases


def _number(value: Any, name: str, *, integer: bool = False) -> int | float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"metric {name} must be numeric")
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError(f"metric {name} must be finite")
    if (isinstance(value, int) and value.bit_length() > 64) or (
        isinstance(value, float) and value > (1 << 64) - 1
    ):
        raise ValueError(f"metric {name} exceeds the bounded counter range")
    if value < 0:
        raise ValueError(f"metric {name} must be non-negative")
    if integer and not isinstance(value, int):
        raise ValueError(f"metric {name} must be an integer")
    return value


def validate_metrics(metrics: dict[str, Any]) -> dict[str, int | float | bool | None]:
    if not isinstance(metrics, dict):
        raise ValueError("metrics must be a JSON object")
    missing = [name for name in REQUIRED_METRICS if name not in metrics]
    if missing:
        raise ValueError(f"missing metrics: {','.join(missing)}")
    if set(metrics) != set(REQUIRED_METRICS):
        raise ValueError("metrics contain unrecognized fields")
    normalized: dict[str, int | float | bool | None] = {}
    for name in REQUIRED_METRICS:
        if name in {"gpuObserved", "gpuMicros", "gpuBytes"}:
            continue
        normalized[name] = _number(
            metrics[name],
            name,
            integer=name != "throughputPerSecond",
        )
    observed = metrics["gpuObserved"]
    if not isinstance(observed, bool):
        raise ValueError("gpuObserved must be a boolean")
    normalized["gpuObserved"] = observed
    if observed:
        normalized["gpuMicros"] = _number(
            metrics["gpuMicros"], "gpuMicros", integer=True
        )
        normalized["gpuBytes"] = _number(metrics["gpuBytes"], "gpuBytes", integer=True)
    else:
        if metrics["gpuMicros"] is not None or metrics["gpuBytes"] is not None:
            raise ValueError("unobserved GPU metrics must be null, not zero")
        normalized["gpuMicros"] = None
        normalized["gpuBytes"] = None
    if not (
        normalized["p50Micros"] <= normalized["p95Micros"] <= normalized["p99Micros"]
    ):
        raise ValueError("latency quantiles are not monotonic")
    if normalized["throughputPerSecond"] <= 0:
        raise ValueError("throughput must be positive")
    return normalized


def parse_json_object(stdout: str) -> dict[str, Any]:
    """Read the final JSON object emitted by a worker."""
    try:
        complete = json.loads(stdout.strip())
        if isinstance(complete, dict):
            return complete
    except json.JSONDecodeError:
        pass
    for line in reversed(stdout.splitlines()):
        line = line.strip()
        if not line:
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    raise ValueError("worker did not emit a JSON object")


def parse_workload_output(stdout: str) -> dict[str, Any]:
    value = parse_json_object(stdout)
    if "metrics" not in value:
        raise ValueError("workload did not emit a JSON object containing metrics")
    return value


def _command(argv: str, case: dict[str, Any]) -> list[str]:
    tokens = shlex.split(argv)
    return [token.format(**case) for token in tokens]


def observer_signing_bytes(receipt: dict[str, Any]) -> bytes:
    """Canonical signed observer claim; independent of caller-supplied digest."""
    fields = (
        "schema",
        "verified",
        "sourceCommit",
        "workloadDigest",
        "reportDigest",
        "metricsDigest",
        "observerId",
    )
    return b"hepta.cell-split.observer.ed25519.v1\0" + canonical_bytes(
        {field: receipt.get(field) for field in fields}
    )


def _ed25519_prime_order_public_key(encoded: bytes) -> bool:
    """Reject identity, torsion, mixed-order and noncanonical observer keys.

    A 32-byte Ed25519 key can decode to a small-order point even when the
    underlying signature library accepts its encoding. Verify that [L]P is
    the neutral point, and that P itself is not neutral, before trusting it.
    All arithmetic here handles public input, never a secret scalar.
    """
    prime = 2**255 - 19
    order = 2**252 + 27742317777372353535851937790883648493
    d = -121665 * pow(121666, -1, prime) % prime
    sqrt_minus_one = pow(2, (prime - 1) // 4, prime)
    if len(encoded) != 32:
        return False
    value = int.from_bytes(encoded, "little")
    y = value & ((1 << 255) - 1)
    sign = value >> 255
    if y >= prime:
        return False
    yy = y * y % prime
    denominator = (d * yy + 1) % prime
    if denominator == 0:
        return False
    xx = (yy - 1) * pow(denominator, -1, prime) % prime
    x = pow(xx, (prime + 3) // 8, prime)
    if x * x % prime != xx:
        x = x * sqrt_minus_one % prime
    if x * x % prime != xx or (x == 0 and sign):
        return False
    if (x & 1) != sign:
        x = -x % prime
    if x == 0 and y == 1:
        return False

    def add(
        a: tuple[int, int, int, int], b: tuple[int, int, int, int]
    ) -> tuple[int, int, int, int]:
        x1, y1, z1, t1 = a
        x2, y2, z2, t2 = b
        aa = (y1 - x1) * (y2 - x2) % prime
        bb = (y1 + x1) * (y2 + x2) % prime
        cc = 2 * d * t1 * t2 % prime
        dd = 2 * z1 * z2 % prime
        ee = (bb - aa) % prime
        ff = (dd - cc) % prime
        gg = (dd + cc) % prime
        hh = (bb + aa) % prime
        return ee * ff % prime, gg * hh % prime, ff * gg % prime, ee * hh % prime

    def double(a: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
        x, yy, z, _ = a
        aa = x * x % prime
        bb = yy * yy % prime
        cc = 2 * z * z % prime
        dd = -aa % prime
        ee = ((x + yy) ** 2 - aa - bb) % prime
        gg = (dd + bb) % prime
        ff = (gg - cc) % prime
        hh = (dd - bb) % prime
        return ee * ff % prime, gg * hh % prime, ff * gg % prime, ee * hh % prime

    point = (x, y, 1, x * y % prime)
    result = (0, 1, 1, 0)
    for bit in range(order.bit_length() - 1, -1, -1):
        result = double(result)
        if (order >> bit) & 1:
            result = add(result, point)
    result_x, result_y, result_z, _ = result
    return result_z != 0 and result_x == 0 and (result_y - result_z) % prime == 0


def verify_observer_signature(
    receipt: dict[str, Any],
    trusted_public_key_hex: str | None,
) -> None:
    """Verify a separately pinned operator trust root, never a receipt-provided key."""
    if not isinstance(trusted_public_key_hex, str) or not re.fullmatch(
        r"[0-9a-f]{64}", trusted_public_key_hex
    ):
        raise ValueError("trusted independent Ed25519 observer public key is required")
    signature = receipt.get("signatureHex")
    if not isinstance(signature, str) or not re.fullmatch(r"[0-9a-f]{128}", signature):
        raise ValueError("independent observer signature is missing or malformed")
    if (
        receipt.get("schema") != OBSERVER_SCHEMA
        or receipt.get("verified") is not True
        or not isinstance(receipt.get("observerId"), str)
        or not receipt["observerId"].strip()
    ):
        raise ValueError("invalid signed observer claim")
    # Only the v1 schema's named fields are signature-bound. A caller
    # may not attach a new "approval" or "authority" field under an
    # existing valid signature and then recompute the unsigned receipt hash.
    actual_fields = set(receipt)
    if actual_fields not in (
        OBSERVER_RECEIPT_KEYS,
        OBSERVER_RECEIPT_KEYS | {"receiptDigest"},
    ):
        raise ValueError("signed observer receipt has unknown or missing fields")
    try:
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    except ImportError as error:
        raise ValueError("trusted Ed25519 verifier dependency unavailable") from error
    trusted_public_key = bytes.fromhex(trusted_public_key_hex)
    if not _ed25519_prime_order_public_key(trusted_public_key):
        raise ValueError(
            "independent observer Ed25519 signature invalid: "
            "non-prime-order trusted key"
        )
    try:
        Ed25519PublicKey.from_public_bytes(trusted_public_key).verify(
            bytes.fromhex(signature), observer_signing_bytes(receipt)
        )
    except (InvalidSignature, ValueError) as error:
        raise ValueError("independent observer Ed25519 signature invalid") from error


def _terminate_process_group(pid: int) -> bool:
    """Kill the entire isolated process group; refuse unsafe cleanup."""
    try:
        os.killpg(pid, signal.SIGKILL)
    except ProcessLookupError:
        return False
    except OSError as error:
        raise RuntimeError("cannot safely terminate isolated process group") from error
    return True


def run_isolated_command(
    argv: list[str], *, env: dict[str, str], timeout_seconds: int | float
) -> subprocess.CompletedProcess[str]:
    """Bound output and kill whole process groups on timeout, flood or orphan."""
    if os.name != "posix" or timeout_seconds <= 0:
        raise ValueError("POSIX process-group isolation and positive timeout required")
    with subprocess.Popen(
        argv,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        start_new_session=True,
    ) as child:
        assert child.stdout is not None and child.stderr is not None
        stdout = bytearray()
        stderr = bytearray()
        deadline = time.monotonic() + timeout_seconds
        try:
            # communicate() is unbounded: a defective or adversarial producer
            # could exhaust the host before its deadline. Read at most the
            # fixed receipt/log budget from each pipe, with nonblocking I/O.
            with selectors.DefaultSelector() as selector:
                for stream, buffer in ((child.stdout, stdout), (child.stderr, stderr)):
                    os.set_blocking(stream.fileno(), False)
                    selector.register(stream, selectors.EVENT_READ, buffer)
                while selector.get_map():
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise ValueError(
                            "subprocess exceeded deadline; process group terminated"
                        )
                    for key, _ in selector.select(remaining):
                        try:
                            chunk = os.read(key.fileobj.fileno(), 65536)
                        except BlockingIOError:
                            continue
                        if not chunk:
                            selector.unregister(key.fileobj)
                            continue
                        buffer = key.data
                        if len(buffer) + len(chunk) > MAX_CHILD_CAPTURE_BYTES:
                            raise ValueError(
                                "subprocess output exceeds bounded capture"
                            )
                        buffer.extend(chunk)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ValueError(
                    "subprocess exceeded deadline; process group terminated"
                )
            try:
                child.wait(timeout=remaining)
            except subprocess.TimeoutExpired as error:
                raise ValueError(
                    "subprocess exceeded deadline; process group terminated"
                ) from error
        except BaseException:
            # Never leave an output-flooding or interrupted group running.
            _terminate_process_group(child.pid)
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired as stuck:
                raise RuntimeError(
                    "process descendants escaped cleanup; stop matrix"
                ) from stuck
            raise
        if _terminate_process_group(child.pid):
            raise ValueError("subprocess left descendant processes")
    return subprocess.CompletedProcess(
        argv, child.returncode, stdout.decode("utf-8"), stderr.decode("utf-8")
    )


def assert_exact_source_checkout(repo_root: Path, source_commit: str) -> None:
    """Reject uncommitted source changes as well as a mismatched Git HEAD."""
    command = ["git", "-C", str(repo_root)]
    try:
        head = subprocess.run(
            [*command, "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise ValueError("cannot verify measured repository HEAD") from error
    if head.stdout.strip() != source_commit:
        raise ValueError("measured source commit does not match repository HEAD")
    try:
        status = subprocess.run(
            [*command, "status", "--porcelain=v1", "--untracked-files=all"],
            check=True,
            capture_output=True,
            text=True,
            timeout=20,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise ValueError("cannot verify measured repository cleanliness") from error
    if status.stdout:
        raise ValueError("measured repository checkout is dirty")


def _check_report_output_target(output: Path, workload_path: Path | None) -> None:
    """Reject report paths that could overwrite frozen source evidence."""
    if output.is_symlink():
        raise ValueError("matrix report output must not be a symlink")
    if output.exists() and not output.is_file():
        raise ValueError("matrix report output must be a regular file")
    if workload_path is not None and (
        output.resolve(strict=False) == workload_path.resolve(strict=False)
        or (output.exists() and output.samefile(workload_path))
    ):
        raise ValueError("matrix report output aliases frozen workload")


def _write_report_atomically(output: Path, report: dict[str, Any]) -> None:
    """Durably publish under a pinned POSIX parent, without following redirects."""
    output.parent.mkdir(parents=True, exist_ok=True)
    if os.name != "posix":
        # Diagnostic-only compatibility: measured worker execution is POSIX-only.
        fd, temporary_name = tempfile.mkstemp(
            prefix=f".{output.name}.", suffix=".tmp", dir=output.parent
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                stream.write(json.dumps(report, sort_keys=True, indent=2) + "\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, output)
        finally:
            temporary.unlink(missing_ok=True)
        return

    # The directory file descriptor pins the publication directory even if
    # another process replaces its path with a symlink mid-operation.
    try:
        directory_fd = os.open(
            output.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        )
    except OSError as error:
        raise ValueError("matrix report parent must be a real directory") from error

    temporary_name = f".{output.name}.{secrets.token_hex(16)}.tmp"
    staged = False
    try:
        fd = os.open(
            temporary_name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
            dir_fd=directory_fd,
        )
        staged = True
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(json.dumps(report, sort_keys=True, indent=2) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(
            temporary_name,
            output.name,
            src_dir_fd=directory_fd,
            dst_dir_fd=directory_fd,
        )
        staged = False
        # fsync(file) does not make the new filename durable across power loss.
        os.fsync(directory_fd)
    finally:
        if staged:
            try:
                os.unlink(temporary_name, dir_fd=directory_fd)
            except FileNotFoundError:
                pass
        os.close(directory_fd)


def run_matrix(
    *,
    workload_command: str | None,
    observer_command: str | None,
    workload_digest: str,
    source_commit: str,
    output: Path,
    workload_path: Path | None = None,
    host_id: str | None = None,
    timeout_seconds: int = 1800,
    cell_count: int | None = None,
    trusted_observer_public_key: str | None = None,
) -> dict[str, Any]:
    if len(workload_digest) != 64 or any(
        char not in "0123456789abcdef" for char in workload_digest
    ):
        raise ValueError("workload digest must be a lowercase sha256")
    if not re.fullmatch(r"[0-9a-f]{40}", source_commit):
        raise ValueError("source commit must be a lowercase 40-character commit")
    # This is source-tree hygiene, not a signed worker-binary provenance claim.
    repo_root = Path(__file__).resolve().parent.parent
    if workload_command is not None:
        assert_exact_source_checkout(repo_root, source_commit)
    _check_report_output_target(output, workload_path)
    if workload_path is not None:
        actual_workload_digest = hashlib.sha256(workload_path.read_bytes()).hexdigest()
        if actual_workload_digest != workload_digest:
            raise ValueError("workload path does not match the frozen workload digest")
    host = host_id or platform.node() or "unknown-host"
    host_fingerprint = {
        "hostId": host,
        "platform": platform.platform(),
        "python": sys.version.split()[0],
    }
    cases = matrix_cases(cell_count)
    selected_counts = list(CELL_COUNTS if cell_count is None else (cell_count,))
    rows: list[dict[str, Any]] = []
    blocked: list[str] = []
    for case in cases:
        started = time.monotonic_ns()
        row: dict[str, Any] = {
            **case,
            "workloadDigest": workload_digest,
            "status": "blocked",
        }
        if workload_command is None:
            row["reason"] = "workload command not supplied"
            blocked.append(case["caseId"])
            rows.append(row)
            continue
        if workload_path is None:
            row["reason"] = "frozen workload path is required"
            blocked.append(case["caseId"])
            rows.append(row)
            continue
        env = os.environ.copy()
        env.update(
            {
                "HEPTA_MATRIX_CASE_ID": case["caseId"],
                "HEPTA_MATRIX_WORKLOAD_DIGEST": workload_digest,
                "HEPTA_MATRIX_SOURCE_COMMIT": source_commit,
                "HEPTA_MATRIX_WORKLOAD_PATH": str(workload_path),
                "HEPTA_MATRIX_CELL_COUNT": str(case["cellCount"]),
                **{
                    f"HEPTA_MATRIX_{key.upper()}": str(value)
                    for key, value in case.items()
                    if key != "caseId"
                },
            }
        )
        try:
            assert_exact_source_checkout(repo_root, source_commit)
            # Recheck the actual frozen bytes for every case, not only at entry.
            if (
                hashlib.sha256(workload_path.read_bytes()).hexdigest()
                != workload_digest
            ):
                raise ValueError("frozen workload changed before case execution")
            result = run_isolated_command(
                _command(
                    workload_command,
                    {
                        **case,
                        "workloadDigest": workload_digest,
                        "sourceCommit": source_commit,
                    },
                ),
                timeout_seconds=timeout_seconds,
                env=env,
            )
            assert_exact_source_checkout(repo_root, source_commit)
            if (
                hashlib.sha256(workload_path.read_bytes()).hexdigest()
                != workload_digest
            ):
                raise ValueError("frozen workload changed during case execution")
            if result.returncode != 0:
                raise ValueError(
                    f"workload exited {result.returncode}: {result.stderr[-512:]}"
                )
            emitted = parse_workload_output(result.stdout)
            if (
                emitted.get("caseId") != case["caseId"]
                or emitted.get("cellCount") != case["cellCount"]
                or emitted.get("sourceCommit") != source_commit
                or emitted.get("workloadDigest") != workload_digest
                or emitted.get("workloadSourceDigest") != workload_digest
                or any(emitted.get(name) != case[name] for name, _ in FACTORS)
            ):
                raise ValueError("workload identity does not bind the requested case")
            metrics = validate_metrics(emitted["metrics"])
            row.update(
                {
                    "metrics": metrics,
                    "status": "measured",
                    "metricsDigest": digest(metrics),
                }
            )
        except (KeyError, OSError, subprocess.SubprocessError, ValueError) as error:
            row["reason"] = str(error)
            blocked.append(case["caseId"])
        row["elapsedMicros"] = (time.monotonic_ns() - started) // 1_000
        rows.append(row)

    if cell_count is not None:
        blocked.append("full-scale-matrix")
    provisional = {
        "schema": SCHEMA,
        "authority": AUTHORITY,
        "cellCounts": selected_counts,
        "sourceCommit": source_commit,
        "workloadDigest": workload_digest,
        "workloadSourceDigest": workload_digest,
        "host": host_fingerprint,
        "cases": rows,
    }
    provisional_digest = digest(provisional)
    metrics_digest = digest(
        [
            {"caseId": row["caseId"], "metricsDigest": row.get("metricsDigest")}
            for row in rows
        ]
    )
    _write_report_atomically(output, provisional)

    observer_receipt: dict[str, Any] | None = None
    # Fail closed *before* spawning a supplied observer executable: a command
    # without an independently pinned, canonical prime-order trust root cannot
    # produce admissible v1 observer evidence. Diagnostic worker rows remain.
    if observer_command is not None and (
        not isinstance(trusted_observer_public_key, str)
        or re.fullmatch(r"[0-9a-f]{64}", trusted_observer_public_key) is None
        or not _ed25519_prime_order_public_key(
            bytes.fromhex(trusted_observer_public_key)
        )
    ):
        observer_receipt = {
            "verified": False,
            "reason": "trusted independent Ed25519 observer public key is required",
        }
        observer_command = None
    if observer_command is None:
        blocked.append("independent-observer")
    else:
        env = os.environ.copy()
        env.update(
            {
                "HEPTA_MATRIX_REPORT": str(output),
                "HEPTA_MATRIX_WORKLOAD_DIGEST": workload_digest,
                "HEPTA_MATRIX_SOURCE_COMMIT": source_commit,
                "HEPTA_MATRIX_PROVISIONAL_DIGEST": provisional_digest,
                "HEPTA_MATRIX_METRICS_DIGEST": metrics_digest,
            }
        )
        try:
            result = run_isolated_command(
                shlex.split(observer_command),
                timeout_seconds=timeout_seconds,
                env=env,
            )
            if result.returncode != 0:
                raise ValueError(
                    f"observer exited {result.returncode}: {result.stderr[-512:]}"
                )
            observer_receipt = parse_json_object(result.stdout)
            if observer_receipt.get("verified") is not True:
                raise ValueError("observer did not return verified=true")
            if (
                observer_receipt.get("sourceCommit") != source_commit
                or observer_receipt.get("workloadDigest") != workload_digest
                or observer_receipt.get("reportDigest") != provisional_digest
                or observer_receipt.get("metricsDigest") != metrics_digest
                or not isinstance(observer_receipt.get("observerId"), str)
                or not observer_receipt["observerId"].strip()
            ):
                raise ValueError("observer receipt binding mismatch")
            verify_observer_signature(observer_receipt, trusted_observer_public_key)
            observer_receipt["receiptDigest"] = digest(
                {
                    key: value
                    for key, value in observer_receipt.items()
                    if key != "receiptDigest"
                }
            )
        except (OSError, subprocess.SubprocessError, ValueError) as error:
            blocked.append("independent-observer")
            observer_receipt = {"verified": False, "reason": str(error)}

    if workload_command is not None:
        try:
            assert_exact_source_checkout(repo_root, source_commit)
        except ValueError as error:
            blocked.append("source-checkout")
            blocked.append("independent-observer")
            # This failure happened after the signer saw the provisional
            # report. Its otherwise-valid signature must never survive as
            # attachable proof that the now-dirty execution was qualified.
            observer_receipt = {
                "verified": False,
                "reason": f"post-observer source checkout violation: {error}",
            }
        if workload_path is not None:
            try:
                still_frozen = (
                    hashlib.sha256(workload_path.read_bytes()).hexdigest()
                    == workload_digest
                )
            except OSError:
                still_frozen = False
            if not still_frozen:
                blocked.append("frozen-workload")
                blocked.append("independent-observer")
                # A previous signed claim cannot certify bytes that changed
                # after the observer ran, even if its signature was valid.
                observer_receipt = {
                    "verified": False,
                    "reason": "post-observer frozen workload changed or is missing",
                }

    report = {
        **provisional,
        "observer": observer_receipt,
        "blockingCases": sorted(set(blocked)),
        "status": "qualified" if not blocked else "blocked",
        "reportDigest": digest({**provisional, "observer": observer_receipt}),
    }
    _write_report_atomically(output, report)
    return report


def validate_report(
    report: dict[str, Any],
    trusted_observer_public_key: str | None = None,
) -> None:
    # reportDigest deliberately hashes the provisional evidence and observer,
    # not status/blockers; reject extra unsigned extension fields separately.
    if not isinstance(report, dict) or set(report) != MATRIX_REPORT_KEYS:
        raise ValueError("matrix report has unknown or missing fields")
    if report.get("schema") != SCHEMA or report.get("authority") != AUTHORITY:
        raise ValueError("invalid report schema or authority posture")
    cases = report.get("cases")
    counts = report.get("cellCounts")
    if counts != list(CELL_COUNTS) and (
        not isinstance(counts, list) or len(counts) != 1 or counts[0] not in CELL_COUNTS
    ):
        raise ValueError("invalid matrix Cell-count coverage")
    expected = {
        case["caseId"]: case
        for case in matrix_cases(counts[0] if len(counts) == 1 else None)
    }
    if (
        not isinstance(cases, list)
        or len(cases) != len(expected)
        or any(not isinstance(case, dict) for case in cases)
        or any(not isinstance(case.get("caseId"), str) for case in cases)
        or {case.get("caseId") for case in cases} != set(expected)
    ):
        raise ValueError("report must contain unique and complete matrix cases")
    for case in cases:
        if any(
            case.get(name) != value for name, value in expected[case["caseId"]].items()
        ):
            raise ValueError("matrix factor or Cell-count identity mismatch")
    workload = report.get("workloadDigest")
    source = report.get("sourceCommit")
    if (
        not isinstance(workload, str)
        or not re.fullmatch(r"[0-9a-f]{64}", workload)
        or report.get("workloadSourceDigest") != workload
        or not isinstance(source, str)
        or not re.fullmatch(r"[0-9a-f]{40}", source)
    ):
        raise ValueError("invalid source/workload identity")
    provisional = {
        key: report[key]
        for key in (
            "schema",
            "authority",
            "cellCounts",
            "sourceCommit",
            "workloadDigest",
            "workloadSourceDigest",
            "host",
            "cases",
        )
    }
    if report.get("reportDigest") != digest(
        {**provisional, "observer": report.get("observer")}
    ):
        raise ValueError("report digest mismatch")
    for case in cases:
        if case.get("workloadDigest") != workload:
            raise ValueError("case workload binding mismatch")
        if case.get("status") == "measured":
            metrics = validate_metrics(case.get("metrics", {}))
            if case.get("metricsDigest") != digest(metrics):
                raise ValueError("metric digest mismatch")
    if report.get("status") == "qualified":
        if counts != list(CELL_COUNTS) or report.get("blockingCases") != []:
            raise ValueError("qualified report needs full scale and zero blockers")
        if any(case.get("status") != "measured" for case in cases):
            raise ValueError("qualified report contains an unmeasured case")
        observer = report.get("observer")
        if not isinstance(observer, dict) or observer.get("verified") is not True:
            raise ValueError("qualified report lacks an independent observer receipt")
        if (
            observer.get("sourceCommit") != source
            or observer.get("workloadDigest") != workload
        ):
            raise ValueError("observer binding mismatch")
        provisional = {
            key: report[key]
            for key in (
                "schema",
                "authority",
                "cellCounts",
                "sourceCommit",
                "workloadDigest",
                "workloadSourceDigest",
                "host",
                "cases",
            )
        }
        if observer.get("reportDigest") != digest(provisional):
            raise ValueError("observer report digest mismatch")
        metrics_digest = digest(
            [
                {"caseId": case["caseId"], "metricsDigest": case.get("metricsDigest")}
                for case in cases
            ]
        )
        if (
            observer.get("metricsDigest") != metrics_digest
            or not isinstance(observer.get("observerId"), str)
            or not observer["observerId"].strip()
        ):
            raise ValueError("observer metrics or identity binding mismatch")
        verify_observer_signature(observer, trusted_observer_public_key)
        if observer.get("receiptDigest") != digest(
            {key: value for key, value in observer.items() if key != "receiptDigest"}
        ):
            raise ValueError("observer receipt digest mismatch")

    status = report.get("status")
    if status not in ("blocked", "qualified"):
        raise ValueError("invalid matrix report status")
    blockers = report.get("blockingCases")
    if (
        not isinstance(blockers, list)
        or any(not isinstance(blocker, str) for blocker in blockers)
        or blockers != sorted(set(blockers))
    ):
        raise ValueError("noncanonical matrix blocker list")
    case_blockers = {
        case["caseId"] for case in cases if case.get("status") == "blocked"
    }
    if any(case.get("status") not in ("blocked", "measured") for case in cases):
        raise ValueError("invalid matrix case status")
    allowed_blockers = set(expected) | {
        "independent-observer",
        "full-scale-matrix",
        "source-checkout",
        "frozen-workload",
    }
    observer = report.get("observer")
    missing_observer = (
        not isinstance(observer, dict) or observer.get("verified") is not True
    )
    blocker_set = set(blockers)
    if (
        not blocker_set <= allowed_blockers
        or case_blockers != blocker_set.intersection(expected)
        or (len(counts) == 1 and "full-scale-matrix" not in blocker_set)
        or (missing_observer and "independent-observer" not in blocker_set)
        or (status == "qualified") != (not blockers)
    ):
        raise ValueError("matrix blocker list/status inconsistent with evidence")
    for case in cases:
        if case["status"] == "blocked" and (
            not isinstance(case.get("reason"), str)
            or not case["reason"]
            or "metrics" in case
            or "metricsDigest" in case
        ):
            raise ValueError("blocked matrix case has invalid reason or metrics")
        if case["status"] == "measured" and "reason" in case:
            raise ValueError("measured matrix case contains blocked reason")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--workload-command", help="argv template; {caseId} may be interpolated"
    )
    parser.add_argument("--observer-command", help="independent observer argv")
    parser.add_argument("--workload-digest", required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument(
        "--workload-path", type=Path, help="path to the frozen workload bytes"
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--host-id")
    parser.add_argument("--timeout-seconds", type=int, default=1800)
    parser.add_argument(
        "--cell-count",
        type=int,
        choices=CELL_COUNTS,
        help="single-count diagnostic only",
    )
    parser.add_argument(
        "--trusted-observer-public-key",
        help="out-of-band trusted Ed25519 key in lowercase hex",
    )
    parser.add_argument("--validate", action="store_true")
    args = parser.parse_args()
    if args.validate:
        validate_report(
            json.loads(args.output.read_text(encoding="utf-8")),
            trusted_observer_public_key=args.trusted_observer_public_key,
        )
        return 0
    report = run_matrix(
        workload_command=args.workload_command,
        observer_command=args.observer_command,
        workload_digest=args.workload_digest,
        source_commit=args.source_commit,
        output=args.output,
        workload_path=args.workload_path,
        host_id=args.host_id,
        timeout_seconds=args.timeout_seconds,
        cell_count=args.cell_count,
        trusted_observer_public_key=args.trusted_observer_public_key,
    )
    print(
        json.dumps(
            {"status": report["status"], "blockingCases": report["blockingCases"]},
            sort_keys=True,
        )
    )
    return 0 if report["status"] == "qualified" else 2


if __name__ == "__main__":
    raise SystemExit(main())
