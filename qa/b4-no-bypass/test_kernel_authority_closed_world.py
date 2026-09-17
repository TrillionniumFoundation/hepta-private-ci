from __future__ import annotations

import importlib.util
import json
import re
import sys
import tomllib
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
INVENTORY = ROOT / "qa/b4-no-bypass/KERNEL_AUTHORITY_BOUNDARIES.json"
MANIFEST = ROOT / "CALLERS.toml"
SPEC = importlib.util.spec_from_file_location(
    "verify_hepta_callers", ROOT / "scripts/verify_hepta_callers.py"
)
assert SPEC is not None and SPEC.loader is not None
CALLER_PROOF = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = CALLER_PROOF
SPEC.loader.exec_module(CALLER_PROOF)


class KernelAuthorityClosedWorldTests(unittest.TestCase):
    def inventory(self) -> list[dict[str, object]]:
        data = json.loads(INVENTORY.read_text(encoding="utf-8"))
        self.assertEqual(data.get("schema"), "hepta.kernel-authority-privileged-boundaries.v1")
        rows = data.get("boundaries")
        self.assertIsInstance(rows, list)
        assert isinstance(rows, list)
        ids = [row.get("id") for row in rows]
        self.assertEqual(len(ids), len(set(ids)), "duplicate canonical privileged boundary id")
        return rows

    def rust_sources(self) -> list[Path]:
        return sorted((ROOT / "codex-rs").rglob("*.rs"))

    def test_canonical_kernel_authority_inventory_is_declared_in_callers_manifest(self) -> None:
        data = tomllib.loads(MANIFEST.read_text(encoding="utf-8"))
        declared_rows = data.get("boundary")
        self.assertIsInstance(declared_rows, list)
        assert isinstance(declared_rows, list)
        declared = {row.get("id") for row in declared_rows}
        manifest_inventory = data.get("privileged_inventory")
        self.assertIsInstance(manifest_inventory, dict)
        assert isinstance(manifest_inventory, dict)
        required = set(manifest_inventory.get("required_boundary_ids", []))
        canonical = {row["id"] for row in self.inventory()}
        self.assertTrue(
            canonical.issubset(declared),
            f"kernel.authority privileged boundaries missing from CALLERS.toml: {sorted(canonical - declared)}",
        )
        self.assertTrue(
            canonical.issubset(required),
            f"kernel.authority privileged boundaries missing from privileged_inventory: {sorted(canonical - required)}",
        )

    def test_type_anchored_callers_match_independent_closed_set(self) -> None:
        ignored = ("/tests/", "/examples/", "_tests.rs")
        sources = self.rust_sources()
        for row in self.inventory():
            boundary_id = str(row["id"])
            type_marker = str(row["typeMarker"])
            definition = str(row["definitionPath"])
            patterns = [re.compile(str(value)) for value in row["callPatterns"]]
            expected = {str(value) for value in row["allowedCallers"]}
            observed: set[str] = set()
            for path in sources:
                relative = path.relative_to(ROOT).as_posix()
                if relative == definition or any(fragment in f"/{relative}" for fragment in ignored):
                    continue
                raw = path.read_text(encoding="utf-8")
                # The type marker makes the method check receiver-aware enough to
                # catch aliases/imports without treating every generic `.verify`,
                # `.revoke`, or `.consume_kv_v2` call in the workspace as authority.
                if type_marker not in raw:
                    continue
                code = CALLER_PROOF._strip_rust_non_code(raw)
                if any(pattern.search(code) for pattern in patterns):
                    observed.add(relative)
            self.assertEqual(
                observed,
                expected,
                f"{boundary_id}: independent kernel.authority caller set drifted",
            )


if __name__ == "__main__":
    unittest.main()
