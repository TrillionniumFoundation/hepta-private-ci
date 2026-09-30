from __future__ import annotations

import importlib.util
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).with_name("hepta_kg_legacy_guard.py")
SPEC = importlib.util.spec_from_file_location("hepta_kg_legacy_guard", SCRIPT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("cannot load hepta_kg_legacy_guard.py")
legacy_guard = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(legacy_guard)


class KnowledgeGraphLegacyGuardTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        files = {
            "codex-rs/hepta-kg/Cargo.toml": """
[package]
name = "codex-hepta-kg"
version = "0.1.0"

[features]
default = []
legacy-v1 = []
fixture = ["legacy-v1"]
""".lstrip(),
            "codex-rs/hepta-kg/src/lib.rs": """
#[cfg(feature = "legacy-v1")]
mod legacy_v1;
#[cfg(feature = "legacy-v1")]
pub use legacy_v1::Error;
#[cfg(feature = "legacy-v1")]
pub use legacy_v1::KnowledgeEdge;
#[cfg(feature = "legacy-v1")]
pub use legacy_v1::KnowledgeProjection;
#[cfg(feature = "legacy-v1")]
#[allow(deprecated)]
pub use legacy_v1::rebuild;
""".lstrip(),
            "codex-rs/product/Cargo.toml": """
[package]
name = "product"
version = "0.1.0"

[dependencies]
codex-hepta-kg = { path = "../hepta-kg" }
""".lstrip(),
            "codex-rs/product/src/lib.rs": "pub fn product() {}\n",
        }
        for relative, content in files.items():
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        subprocess.run(["git", "-C", str(self.root), "config", "user.name", "test"], check=True)
        subprocess.run(
            ["git", "-C", str(self.root), "config", "user.email", "test@example.invalid"],
            check=True,
        )
        subprocess.run(["git", "-C", str(self.root), "add", "."], check=True)
        subprocess.run(["git", "-C", str(self.root), "commit", "-qm", "fixture"], check=True)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_default_workspace_dependency_is_allowed(self) -> None:
        result = legacy_guard.verify(self.root)
        self.assertEqual(result["status"], "PASS_HEPTA_KG_LEGACY_GUARD")
        self.assertFalse(result["productionLegacyFeatureEnabled"])

    def test_explicit_fixture_feature_is_rejected(self) -> None:
        manifest = self.root / "codex-rs/product/Cargo.toml"
        manifest.write_text(
            manifest.read_text(encoding="utf-8").replace(
                'codex-hepta-kg = { path = "../hepta-kg" }',
                'codex-hepta-kg = { path = "../hepta-kg", features = ["fixture"] }',
            ),
            encoding="utf-8",
        )
        subprocess.run(["git", "-C", str(self.root), "add", "."], check=True)
        subprocess.run(["git", "-C", str(self.root), "commit", "-qm", "enable fixture"], check=True)
        with self.assertRaisesRegex(legacy_guard.LegacyGuardError, "forbidden KG features"):
            legacy_guard.verify_manifest_boundary(self.root)

    def test_ungated_legacy_export_is_rejected(self) -> None:
        source = self.root / "codex-rs/hepta-kg/src/lib.rs"
        source.write_text(
            source.read_text(encoding="utf-8").replace(
                '#[cfg(feature = "legacy-v1")]\npub use legacy_v1::KnowledgeProjection;',
                "pub use legacy_v1::KnowledgeProjection;",
            ),
            encoding="utf-8",
        )
        subprocess.run(["git", "-C", str(self.root), "add", "."], check=True)
        subprocess.run(["git", "-C", str(self.root), "commit", "-qm", "ungate"], check=True)
        with self.assertRaisesRegex(legacy_guard.LegacyGuardError, "escaped or lost"):
            legacy_guard.verify_source_gate(self.root)


if __name__ == "__main__":
    unittest.main()
