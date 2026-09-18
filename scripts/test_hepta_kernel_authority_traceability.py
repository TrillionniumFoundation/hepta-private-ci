from __future__ import annotations

import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TECHNICAL = ROOT / "docs/modules/kernel.authority/TECHNICAL.md"
TRACEABILITY = ROOT / "docs/modules/kernel.authority/TRACEABILITY.md"
IMPLEMENTATION_MAP = ROOT / "docs/modules/kernel.authority/IMPLEMENTATION_MAP.json"
B4_INVENTORY = ROOT / "qa/b4-no-bypass/KERNEL_AUTHORITY_BOUNDARIES.json"

PORT_RE = re.compile(r"ModulePort::kernel\.authority::([a-z0-9_.]+)")
BROWSER_CALLERS = {
    "codex-rs/hepta-agentd/src/browser_servo.rs",
    "codex-rs/hepta-agentd/src/bin/hepta-agentd-browser.rs",
}


class KernelAuthorityTraceabilityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.technical = TECHNICAL.read_text(encoding="utf-8")
        self.traceability = TRACEABILITY.read_text(encoding="utf-8")
        self.implementation_map = json.loads(
            IMPLEMENTATION_MAP.read_text(encoding="utf-8")
        )
        self.b4 = json.loads(B4_INVENTORY.read_text(encoding="utf-8"))

    def test_every_registered_target_port_has_traceability_row(self) -> None:
        ports = sorted(set(PORT_RE.findall(self.technical)))
        self.assertTrue(ports, "kernel.authority technical guide declares no ModulePorts")
        for port in ports:
            self.assertIn(
                f"`ModulePort::kernel.authority::{port}`",
                self.traceability,
                f"missing traceability row for {port}",
            )

    def test_product_callers_are_bound_to_exact_source_objects(self) -> None:
        callers = {
            str(row["sourcePath"])
            for row in self.implementation_map.get("productCallers", [])
        }
        objects = {
            str(row["path"])
            for row in self.implementation_map.get("sourceObjects", [])
        }
        self.assertTrue(callers, "composed kernel.authority map requires product callers")
        self.assertTrue(
            callers.issubset(objects),
            f"product callers missing exact source-object bindings: {sorted(callers - objects)}",
        )

    def test_browser_product_path_matches_b4_closed_world(self) -> None:
        callers = {
            str(row["sourcePath"])
            for row in self.implementation_map.get("productCallers", [])
        }
        self.assertTrue(BROWSER_CALLERS.issubset(callers))

        boundaries = {
            str(row["id"]): set(map(str, row.get("allowedCallers", [])))
            for row in self.b4.get("boundaries", [])
        }
        self.assertEqual(
            boundaries.get("final_use_open_state"),
            {"codex-rs/hepta-agentd/src/bin/hepta-agentd-browser.rs"},
        )
        self.assertEqual(
            boundaries.get("final_use_claim_raw"),
            {"codex-rs/hepta-agentd/src/browser_servo.rs"},
        )
        self.assertEqual(
            boundaries.get("final_use_dispatch_raw"),
            {"codex-rs/hepta-agentd/src/browser_servo.rs"},
        )

        row = next(
            (
                line
                for line in self.traceability.splitlines()
                if "ModulePort::kernel.authority::browser.servo" in line
            ),
            "",
        )
        self.assertTrue(row, "missing browser.servo traceability row")
        self.assertIn("composed", row)
        self.assertNotIn("target-only", row)

    def test_composition_does_not_upgrade_external_claims(self) -> None:
        claim = self.implementation_map.get("claimBoundary", {})
        for key in (
            "productExecutionProved",
            "independentAcceptance",
            "activation",
            "release",
        ):
            self.assertFalse(claim.get(key), f"{key} must remain false without evidence")
        self.assertFalse(self.implementation_map.get("productionImplementation"))


if __name__ == "__main__":
    unittest.main()
