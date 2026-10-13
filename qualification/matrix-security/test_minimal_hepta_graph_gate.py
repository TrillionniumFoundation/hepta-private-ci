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

    def metadata(self):
        # Cargo metadata v1 exposes both the legacy flattened package list
        # and typed dependency edges. Construct a consistent normal baseline;
        # adversarial cases can mutate only one representation to test drift.
        nodes = copy.deepcopy(self.nodes)
        for node in nodes:
            node.setdefault("features", [])
            node["deps"] = [
                {"name": dep, "pkg": dep,
                 "dep_kinds": [{"kind": None, "target": None}]}
                for dep in node["dependencies"]
            ]
        return {"packages": copy.deepcopy(self.packages),
                "resolve": {"nodes": nodes}}

    def report(self):
        return audit(self.metadata(), self.sdk, self.hepta)

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
                r = audit({**self.metadata(), "packages": p}, self.sdk, self.hepta)
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


    def test_dev_only_anymap3_does_not_fake_runtime_security(self):
        data = self.metadata()
        sdk = data["resolve"]["nodes"][0]
        edge = next(d for d in sdk["deps"] if d["pkg"] == "anymap3")
        edge["dep_kinds"] = [{"kind": "dev", "target": None}]
        report = audit(data, self.sdk, self.hepta)
        self.assertFalse(report["isolated_prerequisite_passed"])
        self.assertIn("SDK_DISCONNECTED_FROM_ANYMAP3", report["rejections"])

    def test_build_only_crypto_does_not_fake_e2ee_runtime(self):
        data = self.metadata()
        for node in data["resolve"]["nodes"]:
            for edge in node["deps"]:
                if edge["pkg"] == "matrix-sdk-crypto":
                    edge["dep_kinds"] = [{"kind": "build", "target": None}]
        report = audit(data, self.sdk, self.hepta)
        self.assertFalse(report["isolated_prerequisite_passed"])
        self.assertIn("SDK_DISCONNECTED_FROM_MATRIX_SDK_CRYPTO", report["rejections"])

    def test_dev_only_matrix_adapter_cannot_claim_product_link(self):
        data = self.metadata()
        adapter = data["resolve"]["nodes"][4]
        adapter["deps"][0]["dep_kinds"] = [{"kind": "dev", "target": None}]
        result = audit(data, self.sdk, self.hepta)
        self.assertIn("HEPTA_NOT_LINKED_TO_PINNED_SDK_CODEX_HEPTA_MATRIX_SDK",
                      result["rejections"])

    def test_missing_or_forged_typed_edges_do_not_fallback_to_flat_graph(self):
        good = self.metadata()
        for mutated in ("remove_deps", "empty_kinds", "foreign_edge", "flat_drift"):
            with self.subTest(mutated=mutated):
                data = copy.deepcopy(good)
                sdk = data["resolve"]["nodes"][0]
                if mutated == "remove_deps":
                    sdk.pop("deps")
                elif mutated == "empty_kinds":
                    sdk["deps"][0]["dep_kinds"] = []
                elif mutated == "foreign_edge":
                    sdk["deps"][0]["pkg"] = "unregistered-security-package"
                else:
                    sdk["dependencies"].append("anymap3")  # Duplicate flat ID.
                outcome = audit(data, self.sdk, self.hepta)
                self.assertFalse(outcome["isolated_prerequisite_passed"])
                self.assertTrue(any(
                    value in outcome["rejections"] for value in (
                        "MALFORMED_RESOLVED_NODE", "MALFORMED_TYPED_CARGO_EDGE",
                        "FLAT_TYPED_CARGO_GRAPH_MISMATCH",
                    )
                ), outcome["rejections"])

    def test_unknown_dev_kind_and_dangling_node_rejected(self):
        for mutation in ("unknown_kind", "unknown_target", "missing_node", "duplicate_node"):
            with self.subTest(mutation=mutation):
                data = self.metadata()
                if mutation == "unknown_kind":
                    data["resolve"]["nodes"][0]["deps"][0]["dep_kinds"] = [
                        {"kind": "transitive-security", "target": None}]
                elif mutation == "unknown_target":
                    data["resolve"]["nodes"][0]["deps"][0]["dep_kinds"] = [
                        {"kind": None, "target": 512}]
                elif mutation == "missing_node":
                    data["resolve"]["nodes"].pop()
                else:
                    data["resolve"]["nodes"].append(
                        copy.deepcopy(data["resolve"]["nodes"][0]))
                result = audit(data, self.sdk, self.hepta)
                self.assertFalse(result["isolated_prerequisite_passed"])

    def test_synthetic_missing_or_malformed_metadata_refused(self):
        self.assertFalse(audit({}, self.sdk, self.hepta)["isolated_prerequisite_passed"])
        self.packages.append({"name": "no-package-id"})
        self.assertFalse(self.report()["isolated_prerequisite_passed"])


if __name__ == "__main__":
    unittest.main()
