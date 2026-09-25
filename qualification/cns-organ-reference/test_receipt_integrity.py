"""Receipts bind the inspected registry bytes as well as Git identities."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("cns_verifier", ROOT / "scripts/hepta-cns.py")
VERIFIER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VERIFIER)


class ReceiptIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        for path in [VERIFIER.ARCH_PATH, VERIFIER.PROTOCOL_PATH, VERIFIER.GAPS_PATH]:
            target = self.root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("{}\n")
        self.head = "a" * 40
        self.tree = "b" * 40
        self.parents = ["c" * 40, "d" * 40]
        def git(*arguments):
            if arguments == ("rev-parse", "HEAD"):
                return self.head
            if arguments == ("rev-parse", "HEAD^{tree}"):
                return self.tree
            return " ".join([self.head, *self.parents])
        for context in [patch.object(VERIFIER, "ROOT", self.root), patch.object(VERIFIER, "git", git)]:
            context.start()
            self.addCleanup(context.stop)
        VERIFIER.receipt("merge-candidate", self.head, "receipt.json")

    def verify(self):
        return VERIFIER.receipt_verify("merge-candidate", self.head, "receipt.json")

    def test_exact_receipt_round_trip(self):
        self.assertEqual(self.verify(), 0)

    def test_forged_registry_digest_is_rejected(self):
        path = self.root / "receipt.json"
        value = json.loads(path.read_text())
        value["architectureSha256"] = "f" * 64
        path.write_text(json.dumps(value))
        with self.assertRaisesRegex(SystemExit, "receipt source digest"):
            self.verify()

    def test_registry_changed_after_receipt_is_rejected(self):
        (self.root / VERIFIER.PROTOCOL_PATH).write_text('{"changed":true}\n')
        with self.assertRaisesRegex(SystemExit, "receipt source digest"):
            self.verify()

    def test_single_parent_is_not_a_synthetic_merge(self):
        self.parents[:] = ["c" * 40]
        VERIFIER.receipt("merge-candidate", self.head, "receipt.json")
        with self.assertRaisesRegex(SystemExit, "receipt synthetic merge parents"):
            self.verify()


if __name__ == "__main__":
    unittest.main()
