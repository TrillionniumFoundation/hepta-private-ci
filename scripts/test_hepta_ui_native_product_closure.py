from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess
import unittest

import check_hepta_ui_native_convergence as native

ROOT = Path(__file__).resolve().parents[1]
SHA = re.compile(r"[0-9a-f]{40}\Z")
FROZEN_PATHS = (
    "apps/hepta-native/tools",
    "apps/hepta-native/packaging",
    "apps/hepta-native/portal",
    "apps/hepta-native/platform-adapters",
)


class UiNativeProductClosureTests(unittest.TestCase):
    def test_portal_packaging_and_identity_are_frozen_with_candidate(self) -> None:
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
        result = subprocess.run(
            ["git", "diff", "--quiet", implementation, "HEAD", "--", *FROZEN_PATHS],
            cwd=ROOT,
            check=False,
        )
        self.assertEqual(result.returncode, 0, "product adapters changed after freeze")

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
            "mutation lane": "pending_runtime",
            "read lane": "pending_read",
            "picker lane": "pending_picker",
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
