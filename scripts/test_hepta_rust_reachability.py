from __future__ import annotations

import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).with_name("hepta_rust_reachability.py")
SPEC = importlib.util.spec_from_file_location("hepta_rust_reachability", SCRIPT)
assert SPEC and SPEC.loader
reachability = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(reachability)


class RustReachabilityTests(unittest.TestCase):
    def repository(self) -> tuple[tempfile.TemporaryDirectory[str], Path]:
        temporary = tempfile.TemporaryDirectory()
        root = Path(temporary.name)
        subprocess.run(["git", "init", "-q", root], check=True)
        package = root / "codex-rs/hepta-example"
        (package / "src").mkdir(parents=True)
        (package / "tests/support").mkdir(parents=True)
        (package / "Cargo.toml").write_text(
            '[package]\nname="codex-hepta-example"\nversion="0.0.0"\nedition="2024"\n',
            encoding="utf-8",
        )
        return temporary, root

    def metadata(self, root: Path) -> dict:
        package = root / "codex-rs/hepta-example"
        return {
            "packages": [
                {
                    "name": "codex-hepta-example",
                    "manifest_path": str(package / "Cargo.toml"),
                    "targets": [
                        {"src_path": str(package / "src/lib.rs")},
                        {"src_path": str(package / "tests/product.rs")},
                    ],
                }
            ]
        }

    def track(self, root: Path) -> None:
        subprocess.run(["git", "-C", root, "add", "."], check=True)

    def test_global_target_walk_follows_mod_path_and_include(self) -> None:
        temporary, root = self.repository()
        self.addCleanup(temporary.cleanup)
        package = root / "codex-rs/hepta-example"
        (package / "src/lib.rs").write_text(
            'mod owner;\ninclude!("generated.rs");\n', encoding="utf-8"
        )
        (package / "src/owner.rs").write_text(
            '#[path = "shared.rs"]\nmod shared;\n', encoding="utf-8"
        )
        (package / "src/shared.rs").write_text("pub fn shared() {}\n", encoding="utf-8")
        (package / "src/generated.rs").write_text("pub fn generated() {}\n", encoding="utf-8")
        (package / "tests/product.rs").write_text("mod support;\n", encoding="utf-8")
        (package / "tests/support/mod.rs").write_text("pub fn fixture() {}\n", encoding="utf-8")
        self.track(root)
        report = reachability.scan(root, self.metadata(root))
        self.assertEqual(report["status"], "aligned", json.dumps(report, indent=2))

    def test_unreferenced_tracked_source_fails(self) -> None:
        temporary, root = self.repository()
        self.addCleanup(temporary.cleanup)
        package = root / "codex-rs/hepta-example"
        (package / "src/lib.rs").write_text("pub fn live() {}\n", encoding="utf-8")
        (package / "src/orphan.rs").write_text("pub fn orphan() {}\n", encoding="utf-8")
        (package / "tests/product.rs").write_text("#[test]\nfn product() {}\n", encoding="utf-8")
        self.track(root)
        report = reachability.scan(root, self.metadata(root))
        self.assertEqual(report["status"], "orphan_source")
        self.assertEqual(
            report["unreachableSources"],
            [{"package": "codex-hepta-example", "path": "codex-rs/hepta-example/src/orphan.rs"}],
        )


if __name__ == "__main__":
    unittest.main()
