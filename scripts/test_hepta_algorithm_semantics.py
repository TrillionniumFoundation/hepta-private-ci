"""Semantic guards survive editorial changes without cached prose identities."""

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

spec = importlib.util.spec_from_file_location(
    "algorithm_semantics", Path(__file__).with_name("hepta-algorithm-docs.py")
)
DOCS = importlib.util.module_from_spec(spec)
spec.loader.exec_module(DOCS)


class AlgorithmSemanticTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        patch = mock.patch.object(DOCS, "ROOT", self.root)
        patch.start()
        self.addCleanup(patch.stop)
        self.row = {
            "id": "ALG-EXAMPLE",
            "path": "docs/learning/example.md",
            "documentationState": "closed",
            "implementationState": "not_implied",
            "modules": ["example.policy"],
            "paperIds": ["PAPER-EXAMPLE"],
            "blobSha": "0" * 40,
        }
        self.path = self.root / self.row["path"]
        self.path.parent.mkdir(parents=True)
        self.path.write_text("# Design\nA useful explanation in a different format.\n")
        self.papers = {"PAPER-EXAMPLE"}

    def test_editorial_rewrite_and_stale_optional_cache_do_not_block(self):
        self.assertTrue(DOCS.verify_specification(self.row, self.papers))
        self.path.write_text(
            "# Revised design\nDifferent headings, order and language.\n"
        )
        self.row.pop("blobSha")
        self.assertTrue(DOCS.verify_specification(self.row, self.papers))

    def test_missing_source_is_rejected(self):
        self.path.unlink()
        with self.assertRaisesRegex(SystemExit, "missing"):
            DOCS.verify_specification(self.row, self.papers)

    def test_path_escape_is_rejected(self):
        for path in (
            "/tmp/example.md",
            "docs/learning/../other.md",
            "docs/learning//x.md",
        ):
            with self.subTest(path=path), self.assertRaises(SystemExit):
                DOCS.verify_specification({**self.row, "path": path}, self.papers)

    def test_symlink_escape_is_rejected(self):
        with tempfile.TemporaryDirectory() as outside:
            target = Path(outside) / "outside.md"
            target.write_text("outside")
            self.path.unlink()
            self.path.symlink_to(target)
            with self.assertRaisesRegex(SystemExit, "escaped path"):
                DOCS.verify_specification(self.row, self.papers)

    def test_unknown_or_duplicate_paper_is_rejected(self):
        for ids in (["OTHER"], ["PAPER-EXAMPLE", "PAPER-EXAMPLE"], [None]):
            with (
                self.subTest(ids=ids),
                self.assertRaisesRegex(SystemExit, "paper references"),
            ):
                DOCS.verify_specification({**self.row, "paperIds": ids}, self.papers)

    def test_prose_cannot_promote_machine_implementation_state(self):
        self.path.write_text(
            "**Documentation state:** `closed`\nAll features are complete.\n"
        )
        row = {**self.row, "implementationState": "production"}
        with self.assertRaisesRegex(SystemExit, "implementation state"):
            DOCS.verify_specification(row, self.papers)

    def test_unknown_module_binding_remains_rejected(self):
        registry = {"criticalModules": ["example.policy"], "documents": [self.row]}
        registry["documents"] = [{**self.row, "modules": ["unknown.policy"]}]
        with self.assertRaisesRegex(SystemExit, "unknown module"):
            DOCS.coverage(registry)

    def test_protocol_and_data_owner_substitution_remains_rejected(self):
        closure = {
            "contractRegistryPath": DOCS.CONTRACTS_PATH,
            "protocolSchemaRegistryPath": DOCS.PROTOCOLS_PATH,
            "dataAuthorityPath": DOCS.DATA_PATH,
        }
        DOCS.verify_protocol_authority_bindings(closure)
        for key in closure:
            with (
                self.subTest(key=key),
                self.assertRaisesRegex(SystemExit, "authority binding"),
            ):
                DOCS.verify_protocol_authority_bindings({**closure, key: "other.json"})

    def test_authority_key_order_is_irrelevant_but_types_are_not(self):
        flags = dict.fromkeys(reversed(DOCS.AUTHORITY_KEYS), False)
        DOCS.false_authority(flags, "fixture")
        for value in (None, 0, "false", True):
            candidate = {**flags, DOCS.AUTHORITY_KEYS[0]: value}
            with self.subTest(value=value), self.assertRaises(SystemExit):
                DOCS.false_authority(candidate, "fixture")

    def test_receipt_checks_actual_specification_bytes(self):
        registry = {"documents": [self.row]}
        payload = {
            "schema": DOCS.RECEIPT_SCHEMA,
            "expectedSha": "head",
            "headSha": "head",
            "treeSha": "tree",
            "algorithmRegistryBlobSha": "registry",
            "specificationBlobShas": {self.row["id"]: "actual-spec"},
            "documentationGapState": "closed",
            "globalClosureState": "closed",
            "capabilityClaimsAdvanced": False,
            "authorityGranted": False,
        }
        output = self.root / "receipt.json"
        output.write_text(json.dumps(payload))

        def git(*args):
            return {
                ("rev-parse", "HEAD"): "head",
                ("rev-parse", "HEAD^{tree}"): "tree",
                ("hash-object", DOCS.REGISTRY_PATH): "registry",
                ("hash-object", self.row["path"]): "actual-spec",
            }[args]

        with (
            mock.patch.object(DOCS, "load", return_value=registry),
            mock.patch.object(DOCS, "git", git),
        ):
            DOCS.receipt_verify(str(output), "head")
            payload["specificationBlobShas"][self.row["id"]] = self.row["blobSha"]
            output.write_text(json.dumps(payload))
            with self.assertRaisesRegex(SystemExit, "specification identity"):
                DOCS.receipt_verify(str(output), "head")


if __name__ == "__main__":
    unittest.main()
