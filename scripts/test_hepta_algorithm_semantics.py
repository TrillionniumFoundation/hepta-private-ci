"""Behavioral coverage for document ownership and committed-byte receipts."""

import contextlib
import importlib.util
import io
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location(
    "algorithm_semantics", Path(__file__).with_name("hepta-algorithm-docs.py")
)
VERIFIER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VERIFIER)


class AlgorithmSemanticsTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.row = {
            "id": "ALG-FIXTURE",
            "path": "docs/learning/fixture.md",
            "blobSha": "historical-observation",
            "documentationState": "closed",
            "implementationState": "not_implied",
            "modules": ["fixture.owner"],
            "paperIds": ["PAPER-FIXTURE"],
        }
        self.document = self.root / self.row["path"]
        self.document.parent.mkdir(parents=True)
        self.text = (
            "# Owner interface\n\nfixture.owner cites PAPER-FIXTURE.\n"
            f"Canonical contracts: `{VERIFIER.CONTRACTS_PATH}`.\n"
            f"Canonical schemas: `{VERIFIER.PROTOCOLS_PATH}`.\n"
        )
        self.document.write_text(self.text, encoding="utf-8")
        self.registry = {
            "documents": [self.row],
            "requiredProtocols": ["fixture.protocol"],
        }
        registry_path = self.root / VERIFIER.REGISTRY_PATH
        registry_path.write_text(json.dumps(self.registry), encoding="utf-8")
        self.papers = {"papers": [{"sourceLock": {"contentDigest": "fixture-digest"}}]}
        (self.root / VERIFIER.PAPER_PATH).write_text(
            json.dumps(self.papers), encoding="utf-8"
        )
        self.git("init", "-q")
        self.git("config", "user.name", "Receipt Fixture")
        self.git("config", "user.email", "fixture@example.invalid")
        self.commit()
        root_patch = patch.object(VERIFIER, "ROOT", self.root)
        root_patch.start()
        self.addCleanup(root_patch.stop)

    def git(self, *args):
        return subprocess.check_output(
            ["git", "-C", str(self.root), *args], text=True
        ).strip()

    def commit(self):
        self.git("add", ".")
        self.git("commit", "-qm", "Fixture revision")
        self.head = self.git("rev-parse", "HEAD")

    def verify_document(self):
        VERIFIER.validate_specification_document(self.row, {"PAPER-FIXTURE"})

    def test_editorial_revisions_preserve_module_and_protocol_ownership(self):
        self.verify_document()
        self.document.write_text(
            self.text.replace("# Owner interface", "# Operations")
            + "\nA revised explanation of the same interface.\n",
            encoding="utf-8",
        )
        self.verify_document()

    def test_unknown_cited_paper_and_missing_owner_are_rejected(self):
        with self.assertRaisesRegex(SystemExit, "unknown paper"):
            VERIFIER.validate_specification_document(self.row, set())
        self.document.write_text(self.text.replace("fixture.owner", "other.owner"))
        with self.assertRaisesRegex(SystemExit, "missing module"):
            self.verify_document()

    def test_missing_protocol_authority_and_empty_document_are_rejected(self):
        self.document.write_text(
            self.text.replace(VERIFIER.CONTRACTS_PATH, "other.json")
        )
        with self.assertRaisesRegex(SystemExit, "protocol authority boundary"):
            self.verify_document()
        self.document.write_text(" \n")
        with self.assertRaisesRegex(SystemExit, "empty document"):
            self.verify_document()

    def test_receipt_uses_committed_bytes_and_rejects_dirty_documents(self):
        observed = VERIFIER.specification_blob_shas(self.registry, self.head)
        self.assertEqual(
            observed,
            {self.row["id"]: self.git("rev-parse", f"HEAD:{self.row['path']}")},
        )
        self.document.write_text(self.text + "\nA new revision.\n")
        with self.assertRaisesRegex(SystemExit, "uncommitted receipt input"):
            VERIFIER.specification_blob_shas(self.registry, self.head)
        self.commit()
        self.assertNotEqual(
            VERIFIER.specification_blob_shas(self.registry, self.head), observed
        )

    def test_receipt_verification_checks_specification_bytes(self):
        receipt = {
            "schema": VERIFIER.RECEIPT_SCHEMA,
            "expectedSha": self.head,
            "headSha": self.head,
            "treeSha": self.git("rev-parse", "HEAD^{tree}"),
            "algorithmRegistryBlobSha": self.git("hash-object", VERIFIER.REGISTRY_PATH),
            "paperTraceabilityBlobSha": self.git("hash-object", VERIFIER.PAPER_PATH),
            "paperSourceLockSha256": VERIFIER.paper_source_lock_digest(self.papers),
            "requiredProtocolIds": self.registry["requiredProtocols"],
            "specificationBlobShas": VERIFIER.specification_blob_shas(
                self.registry, self.head
            ),
            "documentationGapState": "closed",
            "globalClosureState": "closed",
            "capabilityClaimsAdvanced": False,
            "authorityGranted": False,
        }
        path = self.root / "receipt.json"
        path.write_text(json.dumps(receipt))
        with contextlib.redirect_stdout(io.StringIO()):
            VERIFIER.receipt_verify(str(path), self.head)
        receipt["specificationBlobShas"][self.row["id"]] = "0" * 40
        path.write_text(json.dumps(receipt))
        with self.assertRaisesRegex(SystemExit, "receipt specification bytes"):
            VERIFIER.receipt_verify(str(path), self.head)
        receipt["specificationBlobShas"] = VERIFIER.specification_blob_shas(
            self.registry, self.head
        )
        for field, invalid, message in [
            ("paperTraceabilityBlobSha", "0" * 40, "receipt paper traceability bytes"),
            ("paperSourceLockSha256", "0" * 64, "receipt paper source locks"),
            ("requiredProtocolIds", [], "receipt protocols"),
        ]:
            with self.subTest(field=field):
                path.write_text(json.dumps(receipt | {field: invalid}))
                with self.assertRaisesRegex(SystemExit, message):
                    VERIFIER.receipt_verify(str(path), self.head)

    def test_dirty_registry_cannot_be_attested_as_the_committed_tree(self):
        (self.root / VERIFIER.REGISTRY_PATH).write_text(
            json.dumps(self.registry) + "\n"
        )
        with self.assertRaisesRegex(SystemExit, "uncommitted receipt input"):
            VERIFIER.committed_blob_sha(VERIFIER.REGISTRY_PATH, self.head)

    def test_authority_objects_validate_keys_and_boolean_values(self):
        flags = dict.fromkeys(reversed(VERIFIER.AUTHORITY_KEYS), False)
        VERIFIER.false_authority(flags, "fixture")
        for invalid in [True, 0, None, "", [], {}]:
            with self.subTest(value=invalid), self.assertRaises(SystemExit):
                VERIFIER.false_authority(
                    flags | {VERIFIER.AUTHORITY_KEYS[0]: invalid}, "fixture"
                )
        flags["unregistered"] = flags.pop(VERIFIER.AUTHORITY_KEYS[0])
        with self.assertRaisesRegex(SystemExit, "authority key closure"):
            VERIFIER.false_authority(flags, "fixture")


if __name__ == "__main__":
    unittest.main()
