"""Shared deterministic mutation helpers for platform.types protocol checks."""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
VECTOR_PATH = ROOT / "codex-rs/hepta-types/MANIFEST_V1_CONFORMANCE.json"
ORACLE_PATH = ROOT / "codex-rs/hepta-types/conformance/verify_manifest_vectors.py"


class PropertyCheckError(RuntimeError):
    """A deterministic mutation/property invariant failed."""


def load_oracle() -> Any:
    spec = importlib.util.spec_from_file_location(
        "platform_types_manifest_oracle", ORACLE_PATH
    )
    if spec is None or spec.loader is None:
        raise PropertyCheckError(f"cannot load oracle: {ORACLE_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def read_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise PropertyCheckError(f"cannot read JSON {path}: {error}") from error
    if not isinstance(value, dict):
        raise PropertyCheckError(f"JSON object required: {path}")
    return value


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def digest(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def reverse_objects(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: reverse_objects(item)
            for key, item in reversed(list(value.items()))
        }
    if isinstance(value, list):
        return [reverse_objects(item) for item in value]
    return value


def set_path(value: dict[str, Any], path: tuple[str, ...], replacement: Any) -> None:
    cursor: dict[str, Any] = value
    for component in path[:-1]:
        child = cursor.get(component)
        if not isinstance(child, dict):
            raise PropertyCheckError(f"mutation path is not an object: {path}")
        cursor = child
    cursor[path[-1]] = replacement


def delete_path(value: dict[str, Any], path: tuple[str, ...]) -> None:
    cursor: dict[str, Any] = value
    for component in path[:-1]:
        child = cursor.get(component)
        if not isinstance(child, dict):
            raise PropertyCheckError(f"deletion path is not an object: {path}")
        cursor = child
    del cursor[path[-1]]


def expect_reject(oracle: Any, value: dict[str, Any], label: str) -> None:
    try:
        oracle.semantic_digest(value)
    except (ValueError, TypeError, KeyError):
        return
    raise PropertyCheckError(f"invalid mutation was accepted: {label}")


def mutations() -> dict[str, list[tuple[tuple[str, ...], Any]]]:
    return {
        "random_stream_manifest_v1": [
            (("manifest_id",), "random-manifest-2"),
            (("root_seed_digest",), digest("random-root-2")),
            (("algorithm_namespace",), "utility.ndu.v2"),
            (("episode_id",), "episode-2"),
            (("decision_id",), "decision-2"),
            (("stream_id",), "stream-2"),
            (("counter_start",), "9"),
            (("counter_end_exclusive",), "21"),
            (("generator_id",), "chacha20-counter-v2"),
            (("generator_version",), "1.0.1"),
        ],
        "external_system_manifest_v1": [
            (("system_id",), "external-system-2"),
            (("system_class",), "posix_host"),
            (("host_identity_digest",), digest("host-2")),
            (("os_release_digest",), digest("os-2")),
            (("package_inventory_digest",), digest("packages-2")),
            (("service_graph_digest",), digest("services-2")),
            (("filesystem_scope_digest",), digest("filesystem-2")),
            (("identity_map_digest",), digest("identity-map-2")),
            (("network_surface_digest",), digest("network-2")),
            (("secret_reference_digest",), digest("secret-ref-2")),
            (("observed_at",), "2026-09-25T01:02:04.123456Z"),
            (("authorization_witness",), digest("authorization-2")),
        ],
        "sensor_calibration_manifest_v1": [
            (("sensor_id",), "sensor-2"),
            (("sensor_class",), "browser_session"),
            (("hardware_or_adapter_digest",), digest("sensor-adapter-2")),
            (("calibration_generation",), "8"),
            (("clock_domain",), "monotonic-host-clock-v2"),
            (("valid_from",), "2026-09-24T00:00:00Z"),
            (("valid_until",), "2026-10-26T00:00:00Z"),
            (("uncertainty_profile", "distribution_class"), "normal_approximation"),
            (("uncertainty_profile", "lower_q32"), "-101"),
            (("uncertainty_profile", "upper_q32"), "101"),
            (("uncertainty_profile", "confidence_ppm"), 949999),
            (("operating_range", "unit"), "metres-per-second-v2"),
            (("operating_range", "minimum_q32"), "-1001"),
            (("operating_range", "maximum_q32"), "1001"),
            (("failure_policy",), "abstain"),
        ],
    }


def leaf_paths(value: dict[str, Any]) -> list[tuple[str, ...]]:
    result: list[tuple[str, ...]] = []

    def visit(current: Any, prefix: tuple[str, ...]) -> None:
        if isinstance(current, dict):
            for key, item in current.items():
                visit(item, prefix + (key,))
        else:
            result.append(prefix)

    visit(value, ())
    return result


def changed(value: dict[str, Any], path: tuple[str, ...], replacement: Any) -> dict[str, Any]:
    result = copy.deepcopy(value)
    set_path(result, path, replacement)
    return result
