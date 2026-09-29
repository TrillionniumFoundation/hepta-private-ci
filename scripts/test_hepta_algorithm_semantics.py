"""Semantic guards survive editorial changes without cached prose identities."""

import importlib.util
import contextlib
import io
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
        papers = {"papers": [{"sourceLock": {"contentDigest": "source-content"}}]}
        payload = {
            "schema": DOCS.RECEIPT_SCHEMA,
            "expectedSha": "head",
            "headSha": "head",
            "treeSha": "tree",
            "algorithmRegistryBlobSha": "registry",
            "paperTraceabilityBlobSha": "actual-paper-registry",
            "paperSourceLockSha256": DOCS.paper_source_lock_digest(papers),
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
                ("hash-object", DOCS.PAPER_PATH): "actual-paper-registry",
                ("hash-object", self.row["path"]): "actual-spec",
            }[args]

        with (
            mock.patch.object(
                DOCS,
                "load",
                side_effect=lambda path: (
                    registry if path == DOCS.REGISTRY_PATH else papers
                ),
            ),
            mock.patch.object(DOCS, "git", git),
        ):
            DOCS.receipt_verify(str(output), "head")
            for key in ("paperTraceabilityBlobSha", "paperSourceLockSha256"):
                for invalid in (None, "stale-cache", "0" * 64):
                    candidate = {**payload, key: invalid}
                    output.write_text(json.dumps(candidate))
                    with self.subTest(key=key, invalid=invalid):
                        with self.assertRaisesRegex(SystemExit, "receipt paper"):
                            DOCS.receipt_verify(str(output), "head")
            payload["specificationBlobShas"][self.row["id"]] = self.row["blobSha"]
            output.write_text(json.dumps(payload))
            with self.assertRaisesRegex(SystemExit, "specification identity"):
                DOCS.receipt_verify(str(output), "head")


class PaperObjectSemanticsTests(unittest.TestCase):
    @staticmethod
    def papers():
        return DOCS.load(DOCS.PAPER_PATH)

    def test_complete_verifier_accepts_missing_or_stale_paper_registry_cache(self):
        original_load = DOCS.load
        for retain_cache in (False, True):

            def load(path):
                value = original_load(path)
                if path == DOCS.REGISTRY_PATH:
                    value.pop("paperTraceabilityBlobSha", None)
                    if retain_cache:
                        value["paperTraceabilityBlobSha"] = "old-presentation-cache"
                if path == DOCS.PAPER_PATH:
                    value["papers"] = [
                        dict(reversed(list(row.items()))) for row in value["papers"]
                    ]
                return value

            with self.subTest(retain_cache=retain_cache):
                with mock.patch.object(DOCS, "load", side_effect=load):
                    with contextlib.redirect_stdout(io.StringIO()):
                        self.assertEqual(DOCS.verify(), 0)

    def test_receipt_uses_actual_paper_bytes_not_optional_registry_cache(self):
        registry = DOCS.load(DOCS.REGISTRY_PATH)
        papers = self.papers()
        registry["paperTraceabilityBlobSha"] = "stale-presentation-cache"
        source = "1" * 40

        def git(*args):
            if args == ("rev-parse", "HEAD"):
                return source
            return "actual:" + args[-1]

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "receipt.json"
            with (
                mock.patch.object(DOCS, "verify", return_value=0),
                mock.patch.object(DOCS, "git", side_effect=git),
                mock.patch.object(
                    DOCS,
                    "load",
                    side_effect=lambda path: (
                        registry if path == DOCS.REGISTRY_PATH else papers
                    ),
                ),
            ):
                DOCS.receipt(source, str(output))
                result = json.loads(output.read_text())
                self.assertEqual(
                    result["paperTraceabilityBlobSha"], "actual:" + DOCS.PAPER_PATH
                )
                self.assertEqual(
                    result["paperSourceLockSha256"],
                    DOCS.paper_source_lock_digest(papers),
                )
                DOCS.receipt_verify(str(output), source)

    def test_nested_paper_object_reordering_preserves_source_lock_validation(self):
        def reorder(value):
            if isinstance(value, dict):
                return {
                    key: reorder(item) for key, item in reversed(list(value.items()))
                }
            if isinstance(value, list):
                return [reorder(item) for item in value]
            return value

        self.assertEqual(DOCS.validate_paper_sources(reorder(self.papers())), 4)

    def test_paper_shapes_still_reject_unknown_and_missing_fields(self):
        for path in (
            (),
            ("sourceLock",),
            ("claimAnchors", 0),
            ("claimAnchors", 0, "locator"),
            ("nonClaimAnchors", 0),
        ):
            for unknown in (False, True):
                with self.subTest(path=path, unknown=unknown):
                    papers = self.papers()
                    row = papers["papers"][0]
                    for key in path:
                        row = row[key]
                    if unknown:
                        row["unexpected_field"] = False
                    else:
                        # Keep identity fields so rejection tests the shape itself.
                        del row[
                            next(
                                key
                                for key in reversed(list(row))
                                if key not in {"id", "claim", "nonClaim"}
                            )
                        ]
                    with self.assertRaises(SystemExit):
                        DOCS.validate_paper_sources(papers)

    def test_source_lock_policy_requires_literal_booleans_not_numeric_aliases(self):
        for key, expected in self.papers()["sourceLockPolicy"].items():
            for invalid in (int(expected), float(expected), None, str(expected)):
                with self.subTest(key=key, invalid=invalid):
                    papers = self.papers()
                    papers["sourceLockPolicy"][key] = invalid
                    with self.assertRaisesRegex(SystemExit, "source lock policy"):
                        DOCS.validate_paper_sources(papers)

    def test_reordered_source_record_still_rejects_content_and_locator_substitution(
        self,
    ):
        for kind in ("content", "claim", "locator"):
            with self.subTest(kind=kind):
                papers = self.papers()
                row = papers["papers"][0]
                row["sourceLock"] = dict(reversed(list(row["sourceLock"].items())))
                if kind == "content":
                    row["sourceLock"]["contentDigest"] = "0" * 64
                elif kind == "claim":
                    row["claimAnchors"][0]["sourceTextDigest"] = "0" * 64
                else:
                    row["claimAnchors"][0]["locator"]["sentenceIndex"] = 99
                with self.assertRaises(SystemExit):
                    DOCS.validate_paper_sources(papers)


if __name__ == "__main__":
    unittest.main()
