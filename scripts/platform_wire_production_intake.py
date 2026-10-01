#!/usr/bin/env python3
"""Download and bound the already selected production observation archive.

The protected workflow remains the producer-selection and receipt owner. Reuse
the paired-performance byte, digest and closed-ZIP checks before decompression.
"""

import hashlib
import json
from pathlib import Path

from platform_wire_performance_intake import (
    extract_archive,
    required,
    verified_archive,
)
from platform_wire_receipt_subject import unique_object

MAXIMUM = 20 * 1024 * 1024
LIMITS = {
    "production-plan.json": 256 * 1024,
    "production-observations.json": 16 * 1024 * 1024,
}


def intake() -> None:
    records = Path(required("RECORDS"))
    metadata_path = records / "producer.json"
    if metadata_path.is_symlink():
        raise SystemExit("production artifact metadata is symlinked")
    with metadata_path.open("rb") as stream:
        raw = stream.read(64 * 1024 + 1)
    if len(raw) > 64 * 1024:
        raise SystemExit("production artifact metadata exceeds its byte limit")
    metadata = json.loads(raw, object_pairs_hook=unique_object)
    if not isinstance(metadata, dict):
        raise SystemExit("production artifact metadata must be an object")
    artifact_id = metadata.get("artifact_id")
    if type(artifact_id) is not int or artifact_id <= 0:
        raise SystemExit("production artifact id is invalid")
    if metadata.get("run") != int(required("OBSERVATION_RUN_ID")):
        raise SystemExit("production artifact metadata differs from the selected run")
    archive = verified_archive(
        required("REPOSITORY"),
        required("GH_TOKEN"),
        artifact_id,
        metadata.get("artifact_digest"),
        MAXIMUM,
    )
    extract_archive(archive, Path(required("INPUT_DIR")), LIMITS, MAXIMUM)
    (records / "observation-archive.sha256").write_text(
        f"{hashlib.sha256(archive).hexdigest()}  observation-artifact.zip\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    intake()
