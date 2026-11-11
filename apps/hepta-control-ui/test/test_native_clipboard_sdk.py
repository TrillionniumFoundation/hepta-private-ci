"""Source-graph rejection tests using temporary Git trees and synthetic metadata.

These fixtures exercise the canonical verifier, not Cargo or SDK compilation.
The two num-traits copies model the observed Git-discovery/path-source failure.
"""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch


SPEC = importlib.util.spec_from_file_location(
    "verify_clipboard_sdk", Path(__file__).with_name("verify-native-clipboard-sdk.py"))
VERIFY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VERIFY)


class OriginalSdkGraphTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="sdk-source-graph-test-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.prepared = self.root / "prepared"
        self.prepared.mkdir()
        self.hepta = self.root / "hepta"
        patch_root = self.hepta / "third_party/makepad-patches"
        patch_root.mkdir(parents=True)
        self.packages = [
            ("makepad-widgets", "2.0.0", "widgets/Cargo.toml"),
            ("makepad-draw", "2.0.0", "draw/Cargo.toml"),
            ("makepad-platform", "2.0.0", "platform/Cargo.toml"),
            ("makepad-script", "2.0.0", "platform/script/Cargo.toml"),
            ("unicode-segmentation", "1.12.0", "libs/unicode/Cargo.toml"),
            ("makepad-half", "2.7.1", "libs/vulkan/makepad-half/Cargo.toml"),
            ("naga", "27.0.3", "libs/vulkan/naga/Cargo.toml"),
            ("num-traits", "0.2.20", "libs/rapier/vendor/num-traits/Cargo.toml"),
        ]
        unused = [
            ("num-traits", "0.2.19", "libs/vulkan/num-traits/Cargo.toml"),
            ("num-traits", "0.2.20", "unselected/num-traits/Cargo.toml"),
            ("unknown-sdk-crate", "1.0.0", "unselected/unknown/Cargo.toml"),
        ]
        for name, version, relative in self.packages + unused:
            self.write_manifest(self.prepared / relative, name, version)
        license_bytes = b"Synthetic source fixture; not the original SDK license.\n"
        (self.prepared / "LICENSE").write_bytes(license_bytes)
        self.git("init", "--quiet")
        self.git("add", "--all")
        self.git("-c", "user.name=Source graph fixture", "-c", "user.email=fixture@example.invalid",
                 "commit", "--quiet", "-m", "Synthetic verifier source fixture")
        base = self.git("rev-parse", "HEAD")
        source = "git+" + VERIFY.PREPARE.SOURCE + "?rev=" + base + "#" + base
        for attribute, value in (("BASE", base), ("ORIGINAL_SOURCE", source)):
            scoped = patch.object(VERIFY.PREPARE, attribute, value)
            scoped.start()
            self.addCleanup(scoped.stop)
        manifest = {"upstream_commit": base, "upstream_repository": VERIFY.PREPARE.SOURCE,
                    "patched_tree": self.git("rev-parse", "HEAD^{tree}"),
                    "patches": [], "changed_files": [],
                    "license": {"path": "LICENSE", "bytes": len(license_bytes),
                                "sha256": hashlib.sha256(license_bytes).hexdigest()}}
        (patch_root / "MANIFEST.json").write_text(json.dumps(manifest))
        self.original = {"version": 1, "packages": [], "resolve": {"nodes": []}}
        self.candidate = copy.deepcopy(self.original)
        self.ids = {}
        for name, version, relative in self.packages:
            original_id = source + "::" + name + "@" + version
            candidate_id = "path+" + (self.prepared / relative).parent.as_uri() + "#" + version
            self.ids[name] = (original_id, candidate_id)
            self.original["packages"].append({"id": original_id, "name": name, "version": version,
                                               "source": source,
                                               "manifest_path": str(self.root / "original" / relative)})
            self.candidate["packages"].append({"id": candidate_id, "name": name, "version": version,
                                                "source": None,
                                                "manifest_path": str(self.prepared / relative)})
            for metadata, package_id in ((self.original, original_id), (self.candidate, candidate_id)):
                metadata["resolve"]["nodes"].append({"id": package_id, "features": [], "deps": []})
        self.registry_id = "registry+https://github.com/rust-lang/crates.io-index#num-traits@0.2.19"
        registry_path = self.root / "registry/num-traits/Cargo.toml"
        self.write_manifest(registry_path, "num-traits", "0.2.19")
        ui_path = self.root / "host-ui/Cargo.toml"
        self.write_manifest(ui_path, "hepta-robrix-ui", "0.1.0")
        for metadata in (self.original, self.candidate):
            metadata["packages"].extend([
                {"id": self.registry_id, "name": "num-traits", "version": "0.2.19",
                 "source": "registry+https://github.com/rust-lang/crates.io-index",
                 "manifest_path": str(registry_path)},
                {"id": "original-ui", "name": "hepta-robrix-ui", "version": "0.1.0",
                 "source": None, "manifest_path": str(ui_path)},
            ])
            metadata["resolve"]["nodes"].extend([
                {"id": self.registry_id, "features": [], "deps": []},
                {"id": "original-ui", "features": ["native-clipboard-sdk"], "deps": []},
            ])
        for index, metadata in enumerate((self.original, self.candidate)):
            for name in ("makepad-half", "naga"):
                self.node(metadata, self.ids[name][index])["deps"] = [
                    {"name": "num_traits", "pkg": self.ids["num-traits"][index],
                     "dep_kinds": [{"kind": None, "target": None}]}]
        _, config = VERIFY.PREPARE.cargo_override(self.original, self.prepared)
        self.config = config.encode()

    def git(self, *args):
        return subprocess.check_output(["git", "-C", str(self.prepared), *args], text=True).strip()

    def write_manifest(self, path, name, version):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f'[package]\nname = "{name}"\nversion = "{version}"\n')

    def node(self, metadata, package_id):
        return next(node for node in metadata["resolve"]["nodes"] if node["id"] == package_id)

    def verify(self, candidate=None):
        return VERIFY.verify(self.hepta, self.prepared, json.dumps(self.original).encode(),
                             json.dumps(self.candidate if candidate is None else candidate).encode(),
                             self.config)

    def test_exact_original_vendor_graph_keeps_registry_copy_distinct(self):
        result = self.verify()
        self.assertEqual([item for item in result["resolved_packages"] if item["name"] == "num-traits"],
                         [{"name": "num-traits", "version": "0.2.20",
                           "manifest": "libs/rapier/vendor/num-traits/Cargo.toml"}])
        self.assertFalse(result["compiled"])
        self.assertFalse(result["effects_authority"])

    def test_literal_vulkan_path_downgrade_is_rejected(self):
        candidate = copy.deepcopy(self.candidate)
        package = next(p for p in candidate["packages"] if p["id"] == self.ids["num-traits"][1])
        package.update(version="0.2.19", manifest_path=str(self.prepared / "libs/vulkan/num-traits/Cargo.toml"))
        with self.assertRaisesRegex(ValueError, "Mixed, missing or substituted SDK package: num-traits"):
            self.verify(candidate)

    def test_same_version_at_unselected_manifest_is_rejected(self):
        candidate = copy.deepcopy(self.candidate)
        package = next(p for p in candidate["packages"] if p["id"] == self.ids["num-traits"][1])
        package["manifest_path"] = str(self.prepared / "unselected/num-traits/Cargo.toml")
        with self.assertRaisesRegex(ValueError, "Mixed, missing or substituted SDK package: num-traits"):
            self.verify(candidate)

    def test_extra_prepared_crate_is_rejected_even_in_the_verified_tree(self):
        candidate = copy.deepcopy(self.candidate)
        candidate["packages"].append({"id": "extra-path", "name": "unknown-sdk-crate", "version": "1.0.0",
                                      "source": None,
                                      "manifest_path": str(self.prepared / "unselected/unknown/Cargo.toml")})
        with self.assertRaisesRegex(ValueError, "Mixed, missing or substituted SDK package: unknown-sdk-crate"):
            self.verify(candidate)

    def test_original_incoming_edges_cannot_be_redirected_to_registry(self):
        for parent in ("makepad-half", "naga"):
            with self.subTest(parent=parent):
                candidate = copy.deepcopy(self.candidate)
                self.node(candidate, self.ids[parent][1])["deps"][0]["pkg"] = self.registry_id
                with self.assertRaisesRegex(ValueError, "SDK dependency edge points to a different source: " + parent):
                    self.verify(candidate)

    def test_original_git_copy_cannot_remain_alongside_the_path_copy(self):
        candidate = copy.deepcopy(self.candidate)
        candidate["packages"].append(next(p for p in self.original["packages"]
                                          if p["id"] == self.ids["num-traits"][0]))
        with self.assertRaisesRegex(ValueError, "Candidate still resolves a Git SDK"):
            self.verify(candidate)

    def test_prepared_source_mutation_is_rejected_before_graph_validation(self):
        path = self.prepared / "libs/rapier/vendor/num-traits/Cargo.toml"
        path.write_text(path.read_text().replace('version = "0.2.20"', 'version = "0.2.19"'))
        with self.assertRaisesRegex(ValueError, "undeclared working source changes"):
            self.verify()


if __name__ == "__main__":
    unittest.main()
