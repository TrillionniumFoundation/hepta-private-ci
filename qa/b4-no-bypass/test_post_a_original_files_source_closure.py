"""Root post-A custody source negatives; these do not execute a Root host."""

from dataclasses import replace
import tomllib
import unittest

import test_historical_ledger_readonly_source_closure as component
import test_historical_task_read_source_closure as route

ROOT = component.ROOT
FILE = component.AGENT + "authority_host_post_a_files.rs"


class PostAOriginalFilesSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text())

    reject_removal = component.HistoricalLedgerReadonlySourceTests.reject_removal
    check_markers = component.HistoricalLedgerReadonlySourceTests.check_markers

    def test_original_pins_cannot_be_replaced_by_paths_or_default_identity(self):
        self.check_markers(FILE, "fn retain_original_file(", (
            "original_root()?", "expected.device == 0", "expected.inode == 0",
            "expected.mode & 0o170000 != 0o100000", "expected.mode & 0o022 != 0",
            "OriginalFile::open_original(&expected.path)?", "held.read_handle()?"))

    def test_new_read_description_keeps_both_actual_file_and_path_checks(self):
        self.check_markers(FILE, "fn read_handle(", (
            "original_root()?", "self.original.original_descriptor()?",
            "self.require_identity(&descriptor)?", ".read(true)",
            ".custom_flags(libc::O_CLOEXEC | libc::O_NONBLOCK)",
            "descriptor.as_raw_fd()", "self.require_identity(&file)?"))
        for occurrence in (0, 1):
            self.reject_removal(FILE, "fn read_handle(",
                                "self.original.require_original_file()?", occurrence)

    def test_custody_matches_full_fixed_metadata(self):
        self.check_markers(FILE, "fn require_identity(", (
            "original_root()?", "self.original.require_original_file()?",
            "!actual.is_file()", "actual.nlink() != 1", "actual.dev()", "actual.ino()",
            "actual.uid()", "actual.gid()", "actual.mode()", "self.expected.device",
            "self.expected.inode", "self.expected.uid", "self.expected.gid", "self.expected.mode"))

    def test_models_are_parsed_from_retained_original_descriptors(self):
        self.check_markers(FILE, "fn read_model(", (
            "original_root()?", "LoadedCellQ24ModelV1::open_files(CellQ24ModelFilesV1 {",
            "base: self.base.read_handle()?", "encoder: self.encoder.read_handle()?",
            "heads: self.heads.read_handle()?"))

    def test_original_file_constructors_are_closed_to_actual_root_composition(self):
        proof = route.PROOF
        ids = ("root_post_a_original_file_open", "root_post_a_original_file_read",
               "root_post_a_original_file_identity", "root_post_a_baseline_files_open",
               "root_post_a_baseline_files_read")
        rows = [r for r in proof._boundary_rows(self.manifest) if r.identifier in ids]
        self.assertEqual(len(rows), 5)
        sources = {FILE: proof._strip_cfg_test_items(proof._strip_rust_non_code(
            (ROOT / FILE).read_text()))}
        for path in {path for row in rows for path in row.product_callers}:
            sources[path] = proof._strip_cfg_test_items(proof._strip_rust_non_code(
                (ROOT / path).read_text()))
        for row in rows:
            with self.subTest(boundary=row.identifier):
                self.assertIn(row.identifier,
                              self.manifest["privileged_inventory"]["required_boundary_ids"])
                proof._verify_boundary(ROOT, row, sources, ())
                forged = dict(sources)
                method = row.symbol.rsplit("::", 1)[1]
                forged[component.AGENT + "unregistered_post_a_owner.rs"] = (
                    f"fn bypass(owner: &{row.receiver_type}) {{ owner.{method}(); }}")
                with self.assertRaisesRegex(proof.VerificationFailure, "unexpected"):
                    proof._verify_boundary(ROOT, row, forged, ())
                if row.product_callers:
                    with self.assertRaisesRegex(proof.VerificationFailure, "unexpected"):
                        proof._verify_boundary(ROOT, replace(row, product_callers=()), sources, ())


if __name__ == "__main__":
    unittest.main()
