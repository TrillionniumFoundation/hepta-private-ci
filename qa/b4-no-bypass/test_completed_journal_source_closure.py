"""Original completion read guards; no Root/native result is asserted here."""

from dataclasses import replace
from pathlib import Path
import tempfile
import tomllib
import unittest

import test_historical_task_read_source_closure as route

ROOT = Path(__file__).resolve().parents[2]
A = "codex-rs/hepta-agentd/src/"
PATH = A + "authority_host_completed_journal.rs"
PROOF = route.PROOF


class CompletedJournalSourceClosure(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text())

    def test_physical_checks_and_error_postchecks_cannot_disappear(self):
        source = (ROOT / PATH).read_text()
        rules = {"protected_file": [r for r in self.manifest["protected_file"] if r["path"] == PATH]}
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / PATH
            target.parent.mkdir(parents=True)
            target.write_text(source)
            PROOF._verify_protected_files(root, rules)
            for before, after in (
                ("PostAOriginalFile::same_file(&journal, &witness)", "false"),
                ("let result = action(&observation);", "let result = action(&observation)?; return Ok(result);"),
                ("after.cut != observation.cut || images != before || after.records != observation.records", "false"),
                ("access < 0 || access & libc::O_ACCMODE != libc::O_RDONLY", "false"),
                ("self.anchor(witness)? != anchor", "false"),
            ):
                with self.subTest(before=before):
                    self.assertIn(before, source)
                    target.write_text(source.replace(before, after, 1))
                    with self.assertRaises(PROOF.VerificationFailure):
                        PROOF._verify_protected_files(root, rules)

    def test_data_clone_does_not_make_original_descriptor_cloneable(self):
        path = A + "authority_host_post_a_files.rs"
        source = (ROOT / path).read_text()
        rules = {"protected_file": [r for r in self.manifest["protected_file"] if r["path"] == path]}
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / path
            target.parent.mkdir(parents=True)
            target.write_text(source)
            PROOF._verify_protected_files(root, rules)
            target.write_text(source.replace("pub(super) struct PostAOriginalFile {", "#[derive(Clone)]\npub(super) struct PostAOriginalFile {", 1))
            with self.assertRaises(PROOF.VerificationFailure):
                PROOF._verify_protected_files(root, rules)

    def test_original_read_callers_are_real_and_required(self):
        identifiers = (
            "root_post_a_original_file_open", "root_post_a_original_file_read",
            "root_post_a_original_file_identity", "root_post_a_original_file_distinct",
            "cell_original_physical_witness_codec", "learning_original_receipt_verification",
            "learning_original_receipt_signature_check", "learning_original_receipt_independence_roles",
            "root_independent_b_record_open", "root_independent_b_record_inspect",
        )
        rows = [r for r in PROOF._boundary_rows(self.manifest) if r.identifier in identifiers]
        self.assertEqual(len(rows), len(identifiers))
        paths = {r.definition_path for r in rows} | {p for r in rows for p in r.product_callers}
        index = {p: PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code((ROOT / p).read_text())) for p in paths}
        for row in rows:
            with self.subTest(boundary=row.identifier):
                PROOF._verify_boundary(ROOT, row, index, ())
                for path in row.product_callers:
                    if "completed_" not in path and "evaluation_history" not in path:
                        continue
                    with self.assertRaises(PROOF.VerificationFailure):
                        PROOF._verify_boundary(ROOT, replace(row, product_callers=tuple(p for p in row.product_callers if p != path)), index, ())


if __name__ == "__main__":
    unittest.main()
