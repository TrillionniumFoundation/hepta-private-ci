from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess
import unittest

import check_hepta_ui_native_convergence as native
import hepta_native_lifecycle_ci as lifecycle
import test_hepta_native_lifecycle_ci as coverage
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
SHA = re.compile(r"[0-9a-f]{40}\Z")


class UiNativeProductClosureTests(unittest.TestCase):
    def test_historical_identity_and_current_runtime_input_inventory_remain_exact(
        self,
    ) -> None:
        state = json.loads(
            (ROOT / "apps/hepta-native/CANDIDATE.json").read_text(encoding="utf-8")
        )
        implementation = state["implementationSourceSha"]
        tree = state["implementationSourceTree"]
        self.assertRegex(implementation, SHA)
        self.assertRegex(tree, SHA)
        observed_tree = subprocess.check_output(
            ["git", "rev-parse", f"{implementation}^{{tree}}"],
            cwd=ROOT,
            text=True,
        ).strip()
        self.assertEqual(observed_tree, tree)
        # The stored candidate remains historical evidence. Ordinary source
        # development must not claim or require that historical qualification.
        evidence = native.check_repository(profile="development")
        self.assertEqual(
            evidence["historicalQualificationSource"],
            {"commit": implementation, "tree": tree},
        )
        paths = native.implementation_paths()
        self.assertIn("apps/hepta-native/tools/package_unsigned.py", paths)
        self.assertIn("apps/hepta-native/tools/archive_safety.py", paths)

    def test_worker_ownership_gate_requires_executed_current_behavior(self):
        required = {
            ("hepta-native", "host_lifecycle::controller::tests::" + name)
            for name in (
                "mutation_and_history_are_serialized_while_picker_is_independent",
                "completion_wake_does_not_release_the_lane_before_join",
                "shutdown_drains_admitted_owner_and_cancelled_picker_before_close",
                "failed_spawn_preserves_empty_slots_and_close_retry",
                "panic_completion_is_joined_once_and_retains_failure",
            )
        }
        self.assertTrue(required <= lifecycle.REQUIRED)
        fixture = coverage.CoverageTests(
            "test_complete_executed_inventory_keeps_exclusions_explicit"
        )
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.verify()
        # Source member names are not execution. Failed or missing controller
        # cases must make the actual inventory/JUnit verifier refuse its seal.
        for binary, name in required:
            case = next(
                case
                for case in fixture.junit
                if case.attrib["classname"] == binary and case.attrib["name"] == name
            )
            failure = ET.SubElement(case, "failure")
            with self.assertRaises(ValueError):
                fixture.verify()
            case.remove(failure)
            fixture.junit.remove(case)
            with self.assertRaises(ValueError):
                fixture.verify()
            fixture.junit.append(case)

    def test_product_closure_contracts_remain_fail_closed(self) -> None:
        platform = (ROOT / "apps/hepta-native/src/platform.rs").read_text(
            encoding="utf-8"
        )
        picker = (ROOT / "apps/hepta-native/src/ui/native_picker.rs").read_text(
            encoding="utf-8"
        )
        runtime = (ROOT / "apps/hepta-native/src/runtime.rs").read_text(
            encoding="utf-8"
        )
        ui = (ROOT / "apps/hepta-native/src/ui.rs").read_text(encoding="utf-8")
        package = (ROOT / "apps/hepta-native/tools/package_unsigned.py").read_text(
            encoding="utf-8"
        )
        archive = (ROOT / "apps/hepta-native/tools/archive_safety.py").read_text(
            encoding="utf-8"
        )
        picker_linux = (
            ROOT / "apps/hepta-native/src/ui/native_picker_linux.rs"
        ).read_text(encoding="utf-8")
        contracts = {
            "Rust portal picker module": "native_picker_linux.rs",
            "owned native portal request": "native_portal::request(",
            "explicit retired backend validation": "HEPTA_NATIVE_PICKER_BACKEND",
            "verified resource opener": "open_verified_resource",
            "portal FD handoff": "Fd::from(file.as_fd())",
            "Windows AUMID": "Trillionnium.Hepta.Native",
            "durable history page": "operation_history_page",
            "Rust registrar package declaration": "WINDOWS_IDENTITY_COMMAND",
            "Linux portal package declaration": "linuxPortalFirstPicker",
        }
        joined = "\n".join(
            (platform, picker, picker_linux, runtime, ui, package, archive)
        )
        for name, token in contracts.items():
            self.assertIn(token, joined, name)
        for relative in (
            "apps/hepta-native/src/native_portal.rs",
            "apps/hepta-native/src/ui/native_picker_linux.rs",
            "apps/hepta-native/src/platform_linux.rs",
            "apps/hepta-native/src/platform_notification_helper.rs",
            "apps/hepta-native/platform-adapters/src/registrar.rs",
        ):
            path = ROOT / relative
            self.assertTrue(path.is_file() and not path.is_symlink(), relative)
        # Native resource/notification wiring has moved out of script helpers.
        # This lexical inventory does not prove installed native API execution
        # or the separate ui.control module's complete Rust-only qualification.
        native.check_native_platform_contracts()

    def test_release_flags_remain_false(self) -> None:
        for relative in (
            "apps/hepta-native/CANDIDATE.json",
            "docs/modules/ui.native/CURRENT_DELIVERY.json",
            "docs/modules/ui.native/IMPLEMENTATION_MAP.json",
            "docs/modules/ui.native/QUALIFICATION_MANIFEST.json",
        ):
            value = json.loads((ROOT / relative).read_text(encoding="utf-8"))
            self.assertIs(value["productionQualified"], False)
            self.assertIs(value["deploymentQualified"], False)
            self.assertIs(value["releaseAuthorized"], False)


if __name__ == "__main__":
    unittest.main()
