#!/usr/bin/env python3
"""Small runner-facing API for submitting external evidence manifests.

The runner must call ``validate_external_manifest`` before handing a manifest
to the promotion gate. This API rejects synthetic shadow fixtures and any
manifest that has not met the minimum observed evidence shape.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from ndu_evidence_manifest import EvidenceManifestError, qualification_status, validate_manifest


class RunnerContractError(EvidenceManifestError):
    """The runner did not provide qualifying observed evidence."""


def validate_external_manifest(manifest: Mapping[str, Any]) -> Mapping[str, Any]:
    """Validate and require real, independent observed evidence."""
    try:
        validate_manifest(manifest, require_observed=True)
    except EvidenceManifestError as error:
        raise RunnerContractError(str(error)) from error
    status = qualification_status(manifest)
    if not status["eligible"]:
        raise RunnerContractError(status["reason"])
    return manifest


def write_external_manifest(manifest: Mapping[str, Any], path: str | Path) -> None:
    """Write only a validated external manifest; never write a shadow fixture."""
    validate_external_manifest(manifest)
    Path(path).write_text(json.dumps(dict(manifest), indent=2, sort_keys=True) + "\n", encoding="utf-8")

