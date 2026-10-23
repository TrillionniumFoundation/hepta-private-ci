"""Keep vendored Rama DNS outside Bazel's workspace-only crate discovery."""

import tomllib
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class RamaDnsBazelBoundaryTests(unittest.TestCase):
    def test_cargo_patched_rama_dns_uses_external_bazel_crate(self):
        manifest = tomllib.loads(
            (ROOT / "codex-rs/Cargo.toml").read_text(encoding="utf-8")
        )
        patch_path = manifest["patch"]["crates-io"]["rama-dns"]["path"]
        vendored = Path("codex-rs") / patch_path
        self.assertEqual(
            vendored.as_posix(), "codex-rs/third_party/rama-dns-0.3.0-alpha.4"
        )
        self.assertTrue((ROOT / vendored / "BUILD.bazel").is_file())

        ignored = {
            line.strip()
            for line in (ROOT / ".bazelignore").read_text(
                encoding="utf-8"
            ).splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        }
        self.assertIn(vendored.as_posix(), ignored)
        # Do not hide an entire subtree, including legitimate workspace members.
        self.assertNotIn("codex-rs", ignored)
        self.assertNotIn("codex-rs/third_party", ignored)
        self.assertNotIn("codex-rs/third_party/i18n-config-0.4.8", ignored)


if __name__ == "__main__":
    unittest.main()
