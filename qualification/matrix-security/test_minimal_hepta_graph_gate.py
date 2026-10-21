"""Reject misleading Matrix candidate metadata even if version labels look safe."""

import copy
from pathlib import Path
import tempfile
import unittest

from minimal_hepta_graph_gate import audit


class MinimalGraphTests(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        root = Path(t.name)
        self.sdk = root / "pinned-release"
        self.hepta = root / "detached-Hepta"
        self.sdk.mkdir()
        self.hepta.mkdir()
        self.packages = []
        self.nodes = []
        for name in ("matrix-sdk", "matrix-sdk-base", "matrix-sdk-crypto", "matrix-sdk-sqlite"):
            self.packages.append({"id": name, "name": name, "version": "0.19.1",
                                  "manifest_path": str(self.sdk / "crates" / name / "Cargo.toml"),
                                  "source": None})
        for name in ("codex-hepta-matrix-sdk", "codex-hepta-matrixd"):
            self.packages.append({"id": name, "name": name, "version": "0.0.0",
                                  "manifest_path": str(self.hepta / "codex-rs" / name / "Cargo.toml"),
                                  "source": None})
        self.packages.append({"id": "anymap3", "name": "anymap3", "version": "1.1.0",
                              "manifest_path": str(root / "registry" / "anymap3" / "Cargo.toml"),
                              "source": "registry+crates.io"})
        self.nodes = [
            {"id": "matrix-sdk", "features": ["e2e-encryption", "sqlite"],
             "dependencies": ["matrix-sdk-base", "matrix-sdk-crypto", "matrix-sdk-sqlite", "anymap3"]},
            {"id": "matrix-sdk-base", "dependencies": ["matrix-sdk-crypto"]},
            {"id": "matrix-sdk-crypto", "dependencies": []},
            {"id": "matrix-sdk-sqlite", "dependencies": ["matrix-sdk-base"]},
            {"id": "codex-hepta-matrix-sdk", "dependencies": ["matrix-sdk"]},
            {"id": "codex-hepta-matrixd", "dependencies": ["codex-hepta-matrix-sdk"]},
            {"id": "anymap3", "dependencies": []},
        ]

    def report(self):
        return audit({"packages": self.packages,
                      "resolve": {"nodes": self.nodes}}, self.sdk, self.hepta)

    def test_full_safe_graph_is_still_diagnostic_only(self):
        result = self.report()
        self.assertTrue(result["isolated_prerequisite_passed"], result["rejections"])
        self.assertFalse(result["production_authorized"])
        self.assertFalse(result["cargo_deny_verified"])
        self.assertFalse(result["hepta_matrix_compiled"])

    def test_legacy_or_duplicate_package_never_passes(self):
        for old_name, old_version in (("anymap2", "0.13.0"), ("matrix-sdk-crypto", "0.18.0")):
            with self.subTest(name=old_name):
                p = copy.deepcopy(self.packages)
                p.append({"id": old_name + "-extra", "name": old_name, "version": old_version,
                          "manifest_path": str(self.sdk / "crates" / old_name / "Cargo.toml"),
                          "source": None})
                r = audit({"packages": p, "resolve": {"nodes": self.nodes}}, self.sdk, self.hepta)
                self.assertFalse(r["isolated_prerequisite_passed"])
        self.packages[2]["version"] = "0.18.0"
        self.assertFalse(self.report()["isolated_prerequisite_passed"])

    def test_hidden_old_matrix_family_and_duplicate_anymap3_refused(self):
        old = {
            "id": "matrix-sdk-store-encryption-old",
            "name": "matrix-sdk-store-encryption", "version": "0.18.0",
            "manifest_path": str(self.sdk / "crates/matrix-sdk-store-encryption/Cargo.toml"),
            "source": None,
        }
        self.packages.append(old)
        self.assertFalse(self.report()["isolated_prerequisite_passed"])
        self.packages.pop()
        self.packages.append(dict(self.packages[-1], id="anymap3-unreviewed"))
        self.assertFalse(self.report()["isolated_prerequisite_passed"])
        self.packages.pop()

    def test_missing_e2ee_or_sqlite_refused(self):
        for feat in ("e2e-encryption", "sqlite"):
            with self.subTest(feature=feat):
                saved = self.nodes[0]["features"]
                self.nodes[0]["features"] = [x for x in saved if x != feat]
                self.assertFalse(self.report()["isolated_prerequisite_passed"])
                self.nodes[0]["features"] = saved

    def test_unpinned_sdk_manifest_and_source_refused(self):
        sdk = self.packages[0]
        sdk["manifest_path"] = str(self.hepta / "unreviewed" / "Cargo.toml")
        self.assertFalse(self.report()["isolated_prerequisite_passed"])
        sdk["manifest_path"] = str(self.sdk / "crates/matrix-sdk/Cargo.toml")
        sdk["source"] = "git+https://github.com/unreviewed/sdk"
        self.assertFalse(self.report()["isolated_prerequisite_passed"])

    def test_disconnected_adapters_and_crypto_refused(self):
        self.nodes[5]["dependencies"] = []
        self.assertFalse(self.report()["isolated_prerequisite_passed"])
        self.nodes[5]["dependencies"] = ["codex-hepta-matrix-sdk"]
        self.nodes[0]["dependencies"].remove("matrix-sdk-crypto")
        # Crypto still reachable through Base; make both routes unavailable.
        self.nodes[1]["dependencies"] = []
        self.assertFalse(self.report()["isolated_prerequisite_passed"])

    def test_synthetic_missing_or_malformed_metadata_refused(self):
        self.assertFalse(audit({}, self.sdk, self.hepta)["isolated_prerequisite_passed"])
        self.packages.append({"name": "no-package-id"})
        self.assertFalse(self.report()["isolated_prerequisite_passed"])


if __name__ == "__main__":
    unittest.main()
