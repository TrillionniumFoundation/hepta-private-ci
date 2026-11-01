"""Offline source/graph boundary tests; never substitute for actual Rust tests."""

import copy
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest

from . import prepare
from . import resolve


def archive_fixture(entries):
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w:gz") as archive:
        for name, payload, kind in entries:
            member = tarfile.TarInfo(name)
            member.type = kind
            if kind == tarfile.SYMTYPE:
                member.linkname = "/outside"
            elif kind == tarfile.REGTYPE:
                member.size = len(payload)
            archive.addfile(member, io.BytesIO(payload) if kind == tarfile.REGTYPE else None)
    return output.getvalue()


def graph_fixture():
    versions = {
        "anymap2": "0.13.0", "anymap3": "1.1.0", "aws-config": "1.8.12",
        "ctutils": "0.4.7", "crypto-bigint": "0.7.10", "i18n-config": "0.4.8",
        "keyring": "3.6.3", "matrix-sdk-crypto": "0.18.0", "oxiarc-bzip2": "0.4.2",
        "secret-service": "6.0.0", "toml": "1.1.8+spec-1.1.0", "zip": "9.1.2", "zbus": "6.0.0",
    }
    return {"package": [{"name": name, "version": version} for name, version in versions.items()]}


class SourceContracts(unittest.TestCase):
    def test_registered_overrides_and_patches_are_complete_and_hash_bound(self):
        plan = json.loads((prepare.HERE / "INPUTS.json").read_text())
        covered = set()
        for item in plan["new_files"]:
            prepare.check((prepare.HERE / item["source"]).read_bytes(), item, item["source"])
            covered.add(item["path"])
        for item in plan["patches"]:
            patch = prepare.HERE / item["patch"]
            prepare.check(patch.read_bytes(), item["patch_identity"], item["patch"])
            stat = prepare.git(prepare.HERE, "apply", "--numstat", str(patch)).decode().splitlines()
            self.assertEqual([line.split("\t")[-1] for line in stat], [item["path"]])
            self.assertNotEqual(item["before"], item["after"])
            covered.add(item["path"])
        self.assertTrue(covered <= set(plan["candidate_files"]))
        self.assertEqual(plan["policy_files_unchanged"], ["codex-rs/deny.toml"])
        self.assertFalse(any(path.startswith(("experiments/", "reports/")) for path in covered))

    def test_archive_retains_regular_bytes(self):
        raw = archive_fixture([("crate-1/src/lib.rs", b"pub fn preserved() {}\n", tarfile.REGTYPE)])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            prepare.extract_archive(raw, {"destination": "vendor/crate", "source_prefix": "crate-1"}, root)
            self.assertEqual((root / "vendor/crate/src/lib.rs").read_bytes(), b"pub fn preserved() {}\n")

    def test_archive_rejects_traversal_links_and_duplicate_files(self):
        examples = [
            [("crate-1/../escape", b"bad", tarfile.REGTYPE)],
            [("crate-1/link", b"", tarfile.SYMTYPE)],
            [("different/src/lib.rs", b"bad", tarfile.REGTYPE)],
            [("crate-1/file", b"one", tarfile.REGTYPE), ("crate-1/file", b"two", tarfile.REGTYPE)],
        ]
        for entries in examples:
            with tempfile.TemporaryDirectory() as directory:
                with self.assertRaises(ValueError):
                    prepare.extract_archive(archive_fixture(entries),
                                            {"destination": "vendor/crate", "source_prefix": "crate-1"},
                                            Path(directory))

    def test_candidate_graph_rejects_unsafe_versions_and_registry_backport_substitutions(self):
        graph = graph_fixture()
        self.assertIn("matrix-sdk-crypto", resolve.graph_contract(graph))
        for name in ("basic-toml", "zbus_names", "zvariant", "zvariant_derive", "libbz2-rs-sys", "bzip2-sys"):
            changed = copy.deepcopy(graph)
            changed["package"].append({"name": name, "version": "0.0.1"})
            with self.assertRaises(ValueError):
                resolve.graph_contract(changed)
        for name, version in (("ctutils", "0.4.2"), ("crypto-bigint", "0.5.5")):
            changed = copy.deepcopy(graph)
            next(item for item in changed["package"] if item["name"] == name)["version"] = version
            with self.assertRaises(ValueError):
                resolve.graph_contract(changed)
        changed = copy.deepcopy(graph)
        next(item for item in changed["package"] if item["name"] == "matrix-sdk-crypto")["source"] = "registry+unpatched"
        with self.assertRaises(ValueError):
            resolve.graph_contract(changed)


if __name__ == "__main__":
    unittest.main()
