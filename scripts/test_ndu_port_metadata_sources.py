"""Recheck native metadata source selections without relaxing historical features."""

import copy
import hashlib
import json
from pathlib import Path
import tomllib
import unittest

import ndu_port_candidate_common as common
import test_ndu_port_dependency_amendment as fixtures


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = (
    "qualification/ndu-ci-repairs-20261106/port-metadata-sources/"
    "native-metadata-projection.json"
)
FIXTURE_SHA256 = "9fb64bc3e4dbce93f5c410a67738a5dbc0798ee63c752d61bf40b413c83d4b71"


class MetadataSourceTests(unittest.TestCase):
    def setUp(self):
        fixtures.DependencyAmendmentTests.setUp(self)
        raw = (ROOT / FIXTURE).read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(), FIXTURE_SHA256)
        fixture = json.loads(raw)
        self.assertEqual(fixture["schema"], "ndu.native-metadata-source-projection.v1")
        self.metadata = fixture["metadata"]
        self.assertEqual(len(self.metadata["packages"]), 56)
        self.assertEqual(len(self.metadata["resolve"]["nodes"]), 56)
        self.locked = tomllib.loads((self.root / common.LOCKS[0]).read_text())[
            "package"
        ]

    def validate(self, metadata=None):
        common.validate_graph(
            self.root, self.recipe, self.metadata if metadata is None else metadata
        )

    def test_native_projection_passes_complete_guard_without_mutating_recipe(self):
        original = copy.deepcopy(self.recipe)
        self.validate()
        self.assertEqual(self.recipe, original)
        expected = {
            (p["name"], p["version"]): p["manifest_path"]
            for p in self.amendment["path_packages"]
        }
        self.assertEqual(len(expected), 5)
        self.assertEqual(
            common.verify_dependency_graph(
                self.root, self.recipe, self.metadata, self.locked
            ),
            expected,
        )

    def test_every_other_registry_expectation_still_rejects_path_sources(self):
        for expected in self.recipe["expected_packages"]:
            if expected["source"] != "registry" or (
                expected["name"],
                expected["version"],
            ) in {(p["name"], p["version"]) for p in self.amendment["path_packages"]}:
                continue
            with self.subTest(package=expected["name"]):
                altered = copy.deepcopy(self.metadata)
                package = next(
                    p for p in altered["packages"] if p["name"] == expected["name"]
                )
                package["source"] = None
                with self.assertRaisesRegex(ValueError, "Registry source"):
                    self.validate(altered)

    def test_all_five_backports_reject_wrong_source_path_version_and_node(self):
        for expected in self.amendment["path_packages"]:
            for mutation in (
                "registry",
                "other_vendor",
                "outside_workspace",
                "wrong_version",
                "missing_node",
                "duplicate_package",
            ):
                with self.subTest(package=expected["name"], mutation=mutation):
                    altered = copy.deepcopy(self.metadata)
                    package = next(
                        p
                        for p in altered["packages"]
                        if (p["name"], p["version"])
                        == (expected["name"], expected["version"])
                    )
                    if mutation == "registry":
                        package["source"] = (
                            "registry+https://github.com/rust-lang/crates.io-index"
                        )
                    elif mutation == "other_vendor":
                        package["manifest_path"] = str(
                            Path(altered["workspace_root"])
                            / "third_party/unreviewed/Cargo.toml"
                        )
                    elif mutation == "outside_workspace":
                        package["manifest_path"] = "/outside/Cargo.toml"
                    elif mutation == "wrong_version":
                        package["version"] = "99.0.0"
                    elif mutation == "missing_node":
                        altered["resolve"]["nodes"] = [
                            n
                            for n in altered["resolve"]["nodes"]
                            if n["id"] != package["id"]
                        ]
                    else:
                        altered["packages"].append(copy.deepcopy(package))
                    with self.assertRaises(ValueError):
                        self.validate(altered)

    def test_all_original_required_and_exact_feature_contracts_remain(self):
        for expected in self.recipe["expected_packages"]:
            for mutation in ("missing_required", "extra_exact"):
                if mutation == "missing_required" and not expected.get(
                    "required_features"
                ):
                    continue
                if mutation == "extra_exact" and "exact_features" not in expected:
                    continue
                with self.subTest(package=expected["name"], mutation=mutation):
                    altered = copy.deepcopy(self.metadata)
                    package = next(
                        p for p in altered["packages"] if p["name"] == expected["name"]
                    )
                    node = next(
                        n
                        for n in altered["resolve"]["nodes"]
                        if n["id"] == package["id"]
                    )
                    if mutation == "missing_required":
                        node["features"].remove(expected["required_features"][0])
                    else:
                        node["features"].append("unreviewed-feature")
                    with self.assertRaisesRegex(ValueError, "features"):
                        self.validate(altered)

    def test_original_forbidden_packages_and_pin_utils_stay_rejected(self):
        for name in [*self.recipe["forbidden_packages"], "pin-utils"]:
            with self.subTest(package=name):
                altered = copy.deepcopy(self.metadata)
                altered["packages"].append({"name": name, "version": "0.0.0"})
                with self.assertRaises(ValueError):
                    self.validate(altered)

    def test_original_registry_versions_remain_unique_and_resolved(self):
        for mutation in ("version", "duplicate", "missing_node"):
            with self.subTest(mutation=mutation):
                altered = copy.deepcopy(self.metadata)
                package = next(p for p in altered["packages"] if p["name"] == "zstd")
                if mutation == "version":
                    package["version"] = "99.0.0"
                elif mutation == "duplicate":
                    altered["packages"].append(copy.deepcopy(package))
                else:
                    altered["resolve"]["nodes"] = [
                        n
                        for n in altered["resolve"]["nodes"]
                        if n["id"] != package["id"]
                    ]
                with self.assertRaisesRegex(ValueError, "Expected"):
                    self.validate(altered)

    def test_missing_amendment_cannot_select_the_backports_as_legacy_sources(self):
        (self.root / common.DEPENDENCY_AMENDMENT).unlink()
        self.assertEqual(
            common.verify_dependency_graph(
                self.root, self.recipe, self.metadata, self.locked
            ),
            {},
        )
        with self.assertRaisesRegex(ValueError, "Registry source"):
            self.validate()


if __name__ == "__main__":
    unittest.main()
