import importlib.util
from pathlib import Path
import unittest

MODULE_PATH = Path(__file__).with_name("hepta_ci_select.py")
SPEC = importlib.util.spec_from_file_location("hepta_ci_select", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
SELECTOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SELECTOR)


def metadata():
    root = Path(__file__).resolve().parents[1]
    packages = [
        ("core-id", "core", root / "codex-rs" / "core" / "Cargo.toml", []),
        (
            "memory-id",
            "codex-hepta-memory",
            root / "codex-rs" / "hepta-memory" / "Cargo.toml",
            [{"name": "core", "path": str(root / "codex-rs" / "core")}],
        ),
        (
            "agentd-id",
            "codex-hepta-agentd",
            root / "codex-rs" / "hepta-agentd" / "Cargo.toml",
            [
                {
                    "name": "codex-hepta-memory",
                    "path": str(root / "codex-rs" / "hepta-memory"),
                }
            ],
        ),
        (
            "other-id",
            "codex-other",
            root / "codex-rs" / "other" / "Cargo.toml",
            [],
        ),
    ]
    return {
        "workspace_members": [package_id for package_id, *_ in packages],
        "packages": [
            {
                "id": package_id,
                "name": name,
                "manifest_path": str(manifest),
                "dependencies": dependencies,
            }
            for package_id, name, manifest, dependencies in packages
        ],
    }


CANDIDATES = ["codex-hepta-memory", "codex-hepta-agentd", "codex-other"]


class SelectionTests(unittest.TestCase):
    def select(self, *paths):
        return SELECTOR.select_packages(paths, metadata(), CANDIDATES)

    def test_changed_package_selects_transitive_reverse_dependents(self):
        selected = self.select("codex-rs/hepta-memory/src/lib.rs")
        self.assertFalse(selected["full"])
        self.assertEqual(
            selected["packages"],
            ["codex-hepta-memory", "codex-hepta-agentd"],
        )

    def test_dependency_outside_owner_set_still_selects_owner_dependents(self):
        selected = self.select("codex-rs/core/src/lib.rs")
        self.assertEqual(
            selected["packages"],
            ["codex-hepta-memory", "codex-hepta-agentd"],
        )

    def test_non_workspace_change_skips_native_owner_packages(self):
        selected = self.select("docs/readiness/STABLE_TRUNK.md")
        self.assertFalse(selected["required"])
        self.assertEqual(selected["packages"], [])

    def test_lockfile_and_ci_control_changes_force_full_fallback(self):
        for path in [
            "codex-rs/Cargo.lock",
            ".github/workflows/hepta-consolidated-source.yml",
            "scripts/hepta_ci_select.py",
        ]:
            with self.subTest(path=path):
                selected = self.select(path)
                self.assertTrue(selected["required"])
                self.assertTrue(selected["full"])
                self.assertEqual(selected["packages"], CANDIDATES)

    def test_unknown_workspace_path_forces_full_fallback(self):
        selected = self.select("codex-rs/unmapped-native/input.txt")
        self.assertTrue(selected["full"])
        self.assertEqual(selected["packages"], CANDIDATES)

    def test_unrelated_workspace_package_does_not_expand_owner_set(self):
        selected = self.select("codex-rs/other/src/lib.rs")
        self.assertEqual(selected["packages"], ["codex-other"])


if __name__ == "__main__":
    unittest.main()
