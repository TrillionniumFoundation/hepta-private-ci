"""Download exactly pinned public AG News parquet, with bounded 429 recovery.

The full upstream commit was observed in successful public source Run 38520007082,
not resolved from a floating branch during each new Actions job. Every copy is
independently SHA-256 verified against separately frozen expected source bytes.
A 429 remains a failed run if bounded retries are exhausted; never fabricate
source labels, substitute a nearby revision or waive digest checks.
"""
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path
from typing import Callable

from public_agnews_panel import FILES, REPOSITORY, check_file
from public_agnews_confirmatory import CONFIRM_SOURCE, check_new_source_file

DATASET_COMMIT = "98c532231d96ae10e176a909192ecac548949288"
MAX_FILE_BYTES = 4 * 1024 * 1024
MAX_ATTEMPTS = 3
MAX_RETRY_WAIT_SECONDS = 240
ROLES = ("train", "calibration_test", "new_val2")


class DatasetFetchError(ValueError):
    """External source unavailable, rate-limited, changed or unverified."""


def _status(exc: Exception) -> int | None:
    response = getattr(exc, "response", None)
    code = getattr(response, "status_code", None)
    return code if type(code) is int else None


def _retry_seconds(exc: Exception, attempt: int) -> int:
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None)
    seconds = headers.get("Retry-After") if hasattr(headers, "get") else None
    try:
        requested = int(seconds)
    except (ValueError, TypeError):
        requested = 0
    return min(MAX_RETRY_WAIT_SECONDS, max(10 * (2 ** attempt), requested))


def download_checked(role: str, destination: Path, *, downloader: Callable | None = None,
                     sleeper: Callable = time.sleep) -> dict:
    """Fetch one exact-commit parquet, rehash bytes and fail closed on retry exhaustion."""
    if role not in ROLES:
        raise DatasetFetchError("unregistered public source role")
    if (not re.fullmatch(r"[a-f0-9]{40}", DATASET_COMMIT)
            or not DATASET_COMMIT.startswith("98c5322")):
        raise DatasetFetchError("dataset commit must be an admitted full SHA")
    destination = Path(destination)
    if (destination.exists() or destination.is_symlink()
            or not destination.parent.is_dir()
            or destination.parent.is_symlink()):
        raise DatasetFetchError("destination must be a new local regular file")
    if downloader is None:
        from huggingface_hub import hf_hub_download
        downloader = hf_hub_download
    filename, expected = CONFIRM_SOURCE if role == "new_val2" else FILES[role]
    retries = 0
    for attempt in range(MAX_ATTEMPTS):
        try:
            cached = Path(downloader(
                repo_id=REPOSITORY, repo_type="dataset", filename=filename,
                revision=DATASET_COMMIT,
            ))
            break
        except Exception as exc:
            if _status(exc) != 429 or attempt == MAX_ATTEMPTS - 1:
                raise DatasetFetchError(
                    "exact source download failed; missing evidence is not a passing experiment"
                ) from exc
            wait = _retry_seconds(exc, attempt)
            print(f"public source 429; retry {attempt+1}/{MAX_ATTEMPTS-1} "
                  f"after {wait}s (exact commit retained)", file=sys.stderr)
            sleeper(wait)
            retries += 1
    if not cached.is_file():
        raise DatasetFetchError("download did not yield a regular source file")
    count = 0
    try:
        with cached.open("rb") as source, destination.open("xb") as output:
            while chunk := source.read(1024 * 1024):
                count += len(chunk)
                if count > MAX_FILE_BYTES:
                    raise DatasetFetchError("source exceeds preregistered byte bound")
                output.write(chunk)
        actual = (check_new_source_file(destination) if role == "new_val2"
                  else check_file(destination, role))
        if actual != expected:
            raise DatasetFetchError("public source digest does not match frozen inventory")
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    return {
        "schema": "hepta.stem.public-parquet-source.v1",
        "dataset": REPOSITORY,
        "dataset_commit": DATASET_COMMIT,
        "role": role,
        "filename": filename,
        "source_sha256": actual,
        "source_bytes": count,
        "rate_limit_retries": retries,
        "external_origin_signature_authenticated": False,
        "production_promotion": "DENY_ALL",
    }


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Fail-closed pinned public source acquisition")
    parser.add_argument("--role", choices=ROLES, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(download_checked(args.role, args.destination), sort_keys=True))
