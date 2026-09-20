import copy
import unittest
from pathlib import Path
from unittest.mock import patch

import verify_cargo_workspace_manifests as policy


HEPTA_PROFILE_CRATES = (
    "hepta-agentd",
    "hepta-automation",
    "hepta-contracts",
    "hepta-matrix-sdk",
    "hepta-matrixd",
    "hepta-supervisor",
)


class CargoWorkspaceManifestPolicyTest(unittest.TestCase):
    def manifest(self, crate: str) -> tuple[Path, dict]:
        path = policy.CARGO_RS_ROOT / crate / "Cargo.toml"
        return path, policy.load_manifest(path)

    def errors(self, path: Path, manifest: dict) -> list[str]:
        with patch.object(policy, "load_manifest", return_value=manifest):
            return policy.manifest_errors(
                path,
                {"codex-hepta-contracts", "codex-hepta-matrix-sdk"},
                set(),
                set(),
                set(),
            )

    def test_existing_hepta_profiles_are_accepted_with_defaults_disabled(self) -> None:
        for crate in HEPTA_PROFILE_CRATES:
            with self.subTest(crate=crate):
                path, manifest = self.manifest(crate)
                self.assertEqual(manifest["features"]["default"], [])
                self.assertEqual(self.errors(path, manifest), [])

    def test_enabling_an_existing_profile_by_default_is_rejected(self) -> None:
        for crate in HEPTA_PROFILE_CRATES:
            with self.subTest(crate=crate):
                path, manifest = self.manifest(crate)
                manifest["features"]["default"] = [
                    name for name in manifest["features"] if name != "default"
                ]
                self.assertTrue(
                    any("limit `[features]`" in error for error in self.errors(path, manifest))
                )

    def test_an_extra_feature_in_an_excepted_crate_is_rejected(self) -> None:
        for crate in HEPTA_PROFILE_CRATES:
            with self.subTest(crate=crate):
                path, manifest = self.manifest(crate)
                manifest["features"]["unreviewed-profile"] = []
                self.assertTrue(
                    any("limit `[features]`" in error for error in self.errors(path, manifest))
                )

    def test_removing_the_explicit_empty_default_is_rejected(self) -> None:
        for crate in HEPTA_PROFILE_CRATES:
            with self.subTest(crate=crate):
                path, manifest = self.manifest(crate)
                del manifest["features"]["default"]
                self.assertTrue(
                    any("limit `[features]`" in error for error in self.errors(path, manifest))
                )

    def test_feature_forwarding_is_bound_to_the_existing_matrix_sdk_profile(self) -> None:
        path, manifest = self.manifest("hepta-matrixd")
        for forwarding in (
            [],
            ["codex-hepta-supervisor/production-authority"],
            [
                "codex-hepta-matrix-sdk/qualification-failpoints",
                "codex-hepta-supervisor/production-authority",
            ],
        ):
            with self.subTest(forwarding=forwarding):
                changed = copy.deepcopy(manifest)
                changed["features"]["real-synapse-e2e"] = forwarding
                self.assertTrue(
                    any("limit `[features]`" in error for error in self.errors(path, changed))
                )

    def test_copying_an_allowed_profile_to_an_unknown_crate_is_rejected(self) -> None:
        _, manifest = self.manifest("hepta-contracts")
        path = policy.CARGO_RS_ROOT / "hepta-contracts-copy" / "Cargo.toml"
        manifest["package"]["name"] = "codex-hepta-contracts-copy"
        self.assertEqual(
            self.errors(path, manifest),
            ["remove `[features]`; new workspace crate features are not allowed"],
        )

    def test_profile_exception_does_not_allow_optional_dependencies(self) -> None:
        path, manifest = self.manifest("hepta-contracts")
        manifest["dependencies"]["zeroize"]["optional"] = True
        self.assertTrue(
            any("remove `optional = true`" in error for error in self.errors(path, manifest))
        )

    def test_profile_exception_does_not_allow_internal_dependency_feature_activation(self) -> None:
        path, manifest = self.manifest("hepta-matrixd")
        manifest["dependencies"]["codex-hepta-matrix-sdk"]["features"] = [
            "qualification-failpoints"
        ]
        self.assertTrue(
            any("remove `features = [...]`" in error for error in self.errors(path, manifest))
        )

    def test_removed_profile_requires_removal_of_its_temporary_exception(self) -> None:
        failures: dict[str, list[str]] = {}
        retired_path = "codex-rs/hepta-contracts/Cargo.toml"
        policy.add_unused_exception_errors(
            failures,
            set(policy.MANIFEST_FEATURE_EXCEPTIONS) - {retired_path},
            set(),
            set(),
        )
        self.assertEqual(
            failures,
            {
                retired_path: [
                    "remove the stale `[features]` exception from "
                    "`MANIFEST_FEATURE_EXCEPTIONS`"
                ]
            },
        )


if __name__ == "__main__":
    unittest.main()
