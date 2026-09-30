#!/usr/bin/env python3
"""CLI projection for inference.control current-state evidence.

The importable core owns the source/current-status rendering and receipt logic.
This entry point composes that core with verifier-owned implementation-map
bindings without letting either generator erase the other one's fields.
"""

from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path
from typing import Any

_CORE_PATH = Path(__file__).with_name("hepta_inference_control_current_state_core.py")
_CORE_SHA256 = "10961f5e263e6ccbef29597eae2b4f2beafa716c2b45b975d91a646e861b8e2e"


def _load_core():
    raw = _CORE_PATH.read_bytes()
    actual = hashlib.sha256(raw).hexdigest()
    if actual != _CORE_SHA256:
        raise RuntimeError(
            "inference current-state core identity mismatch: "
            f"expected {_CORE_SHA256}, got {actual}"
        )
    spec = importlib.util.spec_from_file_location(
        "hepta_inference_control_current_state_core", _CORE_PATH
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load inference current-state core")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_CORE = _load_core()
for _name in dir(_CORE):
    if not _name.startswith("__"):
        globals()[_name] = getattr(_CORE, _name)

MAP_EXTENSION_KEYS = ("productCallers", "sourceObjects")


def build_map_projection(source: dict[str, Any]) -> dict[str, Any]:
    """Preserve the exact bindings owned by the global map verifier.

    The current-state generator owns the base projection. The global
    implementation-map migrator owns exact product-caller and source-object
    bindings. Both write the same JSON document, so deleting either delegated
    field here would create a permanent migrate/sync stale-file loop.
    """
    projected = _CORE.build_map(source)
    if not _CORE.MAP_PATH.is_file():
        return projected
    existing = _CORE.load_json(_CORE.MAP_PATH)
    if not isinstance(existing, dict):
        raise ValueError("implementation map must be an object")
    for key in MAP_EXTENSION_KEYS:
        if key in existing:
            projected[key] = existing[key]
    return projected


def projections(source: dict[str, Any]) -> dict[Path, str]:
    return {
        _CORE.CURRENT_PATH: _CORE.canonical_json(_CORE.build_current(source)),
        _CORE.MAP_PATH: _CORE.canonical_json(build_map_projection(source)),
        _CORE.TECHNICAL_STATUS_PATH: _CORE.render_status(source),
        _CORE.DOSSIER_STATUS_PATH: _CORE.render_dossier(source),
    }


# Core entry points resolve ``projections`` through core-module globals.
_CORE.projections = projections


if __name__ == "__main__":
    _CORE.main()
