"""Use the canonical native v6 verifier without translating its map to v3."""

import importlib.util
from pathlib import Path

from hepta_ui_native_map_adapter import verify_native_map


def native_evidence(root: Path, row: dict) -> dict | None:
    version = 6 if row.get("module") == "ui.native" else 3
    if (
        row.get("schema") != f"hepta.module-implementation-map.v{version}"
        or type(row.get("schemaVersion")) is not int
        or row["schemaVersion"] != version
    ):
        raise ValueError(f"{row.get('module')}: requires map schema v{version}")
    if version == 3:
        return None

    spec = importlib.util.spec_from_file_location(
        "lane_b_native_canonical",
        Path(__file__).with_name("hepta-implementation-maps.py"),
    )
    assert spec and spec.loader
    canonical = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(canonical)
    canonical.ROOT = root
    registered = canonical.load("docs/modules/MODULES.json")["modules"]
    owners = {module["id"]: module for module in registered}
    if len(owners) != len(registered) or "ui.native" not in owners:
        raise ValueError("native registered owner is missing or duplicated")
    canonical.validate_claim_types(row)
    canonical.validate_closed_world_bindings(row)
    return verify_native_map(
        root, row, owners["ui.native"], canonical.current_source_base(), canonical.git
    )
