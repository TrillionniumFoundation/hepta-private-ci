"""Source-map freshness and non-activation checks for the source-only candidate."""
from __future__ import annotations

from collections.abc import Callable
from pathlib import PurePosixPath
import re

SHA = re.compile(r"[0-9a-f]{40}\Z")
DENIED = ("productionImplementation", "productExecutionProved", "independentAcceptance", "activation", "release")


def validate(value: dict, resolve: Callable[[str], str]) -> list[str]:
    errors: list[str] = []
    if value.get("schema") != "hepta.module-implementation-map.v3" or value.get("module") != "learning.artifacts":
        return ["wrong implementation-map identity"]
    boundary = value.get("claimBoundary", {})
    if not isinstance(boundary, dict) or any(boundary.get(name) is not False for name in DENIED):
        errors.append("source-only qualification cannot assert production/acceptance/activation/release")
    if value.get("productionImplementation") is not False:
        errors.append("productionImplementation must remain false until separate production acceptance")
    for field in ("state", "status", "completionState"):
        if str(value.get(field, "")).upper() == "COMPLETE":
            errors.append("unified COMPLETE is not a qualified completion dimension")
    dimensions = value.get("completionDimensions", {})
    if not isinstance(dimensions, dict) or dimensions.get("currentHeadQualification") != "requires_two_successful_exact_candidate_receipts":
        errors.append("current-head status must defer to two executed lane receipts")
    objects = value.get("sourceObjects", [])
    operations = value.get("operations", [])
    if not isinstance(objects, list) or not objects or not isinstance(operations, list) or not operations:
        return errors + ["missing source inventory or operation mapping"]
    pairs = [(item.get("path"), item.get("object")) for item in objects if isinstance(item, dict)]
    pairs += [(item.get("sourcePath"), item.get("sourceBlob")) for item in operations if isinstance(item, dict)]
    if len(pairs) != len(objects) + len(operations):
        errors.append("invalid source inventory member")
    seen = {}
    for path, expected in pairs:
        if not isinstance(path, str) or not path or PurePosixPath(path).is_absolute() or ".." in PurePosixPath(path).parts or "\\" in path or not isinstance(expected, str) or not SHA.fullmatch(expected):
            errors.append("invalid source object binding")
            continue
        if path in seen and seen[path] != expected:
            errors.append("conflicting source object binding: " + path)
        seen[path] = expected
    if "codex-rs/hepta-learning-artifacts" not in seen:
        errors.append("module tree is not bound")
    for path, expected in seen.items():
        try:
            if resolve(path) != expected:
                errors.append("stale source object: " + path)
        except (OSError, ValueError) as error:
            errors.append("unresolvable source object: " + path + ": " + str(error))
    return errors
