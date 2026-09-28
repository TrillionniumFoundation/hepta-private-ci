#!/usr/bin/env python3
"""Load and validate the single repository-controlled memory.retrieval policy."""
from __future__ import annotations

import json
from pathlib import Path, PurePosixPath
from typing import Any

POLICY_RELATIVE_PATH = Path("qualification/memory-retrieval/qualification-policy.json")
REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


class PolicyError(ValueError):
    """The qualification policy is malformed or internally inconsistent."""


def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise PolicyError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def safe_path(value: Any) -> str:
    if not isinstance(value, str):
        raise PolicyError("repository path must be a string")
    path = PurePosixPath(value)
    if (not value or path.is_absolute() or ".." in path.parts
            or value.startswith(":") or "\\" in value or "\x00" in value):
        raise PolicyError(f"unsafe repository path: {value!r}")
    return value


def _nonempty_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PolicyError(f"{field} must be a non-empty string")
    return value


def load_policy(root: Path | str = REPOSITORY_ROOT) -> dict[str, Any]:
    root = Path(root)
    path = root / POLICY_RELATIVE_PATH
    data = path.read_bytes()
    if len(data) > 256 * 1024:
        raise PolicyError("qualification policy exceeds 256 KiB")
    value = json.loads(data, object_pairs_hook=unique_object)
    if not isinstance(value, dict):
        raise PolicyError("qualification policy must be an object")
    if value.get("schema") != "hepta.memory-retrieval.qualification-policy.v1":
        raise PolicyError("unsupported qualification policy schema")
    if value.get("module") != "memory.retrieval":
        raise PolicyError("qualification policy targets the wrong module")
    safe_path(value.get("implementationMap"))
    root_path = safe_path(value.get("sourceRoot"))
    activation = value.get("activationMode")
    if activation not in {"compatibility", "shadow", "canary", "required"}:
        raise PolicyError("unsupported activation mode")

    source_inputs = value.get("sourceInputs")
    object_inputs = value.get("sourceObjectInputs")
    if not isinstance(source_inputs, list) or not source_inputs:
        raise PolicyError("sourceInputs must be a non-empty list")
    if not isinstance(object_inputs, list) or not object_inputs:
        raise PolicyError("sourceObjectInputs must be a non-empty list")
    inputs = [safe_path(item) for item in source_inputs]
    objects = [safe_path(item) for item in object_inputs]
    if len(inputs) != len(set(inputs)) or inputs != sorted(inputs):
        raise PolicyError("sourceInputs must be unique and sorted")
    if len(objects) != len(set(objects)) or objects != sorted(objects):
        raise PolicyError("sourceObjectInputs must be unique and sorted")
    if root_path not in objects:
        raise PolicyError("sourceRoot must be explicitly object-bound")
    for item in objects:
        if not any(item == parent or item.startswith(parent.rstrip("/") + "/") for parent in inputs):
            raise PolicyError(f"source object is outside sourceInputs: {item}")

    claims = value.get("promotionClaims")
    boundary = value.get("claimBoundary")
    if not isinstance(claims, list) or not claims:
        raise PolicyError("promotionClaims must be a non-empty list")
    if not isinstance(boundary, dict):
        raise PolicyError("claimBoundary must be an object")
    for claim in claims:
        _nonempty_string(claim, "promotion claim")
        if boundary.get(claim) is not False:
            raise PolicyError(f"policy claim must remain false: {claim}")

    checks = value.get("requiredChecks")
    if not isinstance(checks, list) or not checks:
        raise PolicyError("requiredChecks must be a non-empty list")
    names: set[str] = set()
    for row in checks:
        if not isinstance(row, dict):
            raise PolicyError("required check rows must be objects")
        name = _nonempty_string(row.get("name"), "required check name")
        safe_path(row.get("workflow"))
        if name in names:
            raise PolicyError(f"duplicate required check: {name}")
        names.add(name)

    security = value.get("securityChecks")
    if not isinstance(security, list):
        raise PolicyError("securityChecks must be a list")
    security_names: set[str] = set()
    for row in security:
        if not isinstance(row, dict):
            raise PolicyError("security check rows must be objects")
        name = _nonempty_string(row.get("name"), "security check name")
        conclusion = _nonempty_string(row.get("requiredConclusion"), "security conclusion")
        if conclusion not in {"success", "neutral"}:
            raise PolicyError("unsupported security conclusion")
        if name in security_names:
            raise PolicyError(f"duplicate security check: {name}")
        security_names.add(name)

    external = value.get("externalGates")
    if not isinstance(external, list) or not external:
        raise PolicyError("externalGates must be a non-empty list")
    for row in external:
        if not isinstance(row, dict):
            raise PolicyError("external gate rows must be objects")
        _nonempty_string(row.get("name"), "external gate name")
        if row.get("state") not in {"missing_external", "satisfied_external"}:
            raise PolicyError("unsupported external gate state")
    return value


POLICY = load_policy()
MAP = POLICY["implementationMap"]
ROOT = POLICY["sourceRoot"]
INPUTS = tuple(POLICY["sourceInputs"])
OBJECT_INPUTS = tuple(POLICY["sourceObjectInputs"])
CLAIMS = tuple(POLICY["promotionClaims"])
REQUIRED_CHECKS = {row["name"]: row["workflow"] for row in POLICY["requiredChecks"]}
SECURITY_CHECKS = {row["name"]: row["requiredConclusion"] for row in POLICY["securityChecks"]}
