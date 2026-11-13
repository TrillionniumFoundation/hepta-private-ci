"""Guard the actual B manifest projection and witnessed exact readback."""

from dataclasses import replace
import importlib.util
from pathlib import Path
import sys
import tempfile
import tomllib
import unittest


ROOT = Path(__file__).resolve().parents[2]
AGENT = "codex-rs/hepta-agentd/src/"
DATA = AGENT + "root_independent_b_publication_data.rs"
EXECUTE = AGENT + "authority_host_q24_evaluation_execute.rs"
OUTPUTS = AGENT + "authority_host_q24_evaluation_outputs.rs"
IDENTIFIER = "root_independent_b_publication_encode"
SPEC = importlib.util.spec_from_file_location("b_publication_data_proof", ROOT / "scripts/verify_hepta_callers.py")
assert SPEC is not None and SPEC.loader is not None
PROOF = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PROOF
SPEC.loader.exec_module(PROOF)


class OriginalBPublicationDataSourceClosureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text())
        cls.row = next(row for row in PROOF._boundary_rows(cls.manifest) if row.identifier == IDENTIFIER)
        cls.rows = [row for row in cls.manifest["protected_file"] if row["path"] in (DATA, EXECUTE, OUTPUTS)]
        cls.raw = {path: (ROOT / path).read_text() for path in (DATA, EXECUTE, OUTPUTS)}
        cls.sources = {path: PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code(raw)) for path, raw in cls.raw.items()}

    def test_actual_manifest_caller_and_original_readback_are_guarded(self):
        self.assertIn(IDENTIFIER, self.manifest["privileged_inventory"]["required_boundary_ids"])
        self.assertEqual(self.row.product_callers, (EXECUTE,))
        PROOF._verify_boundary(ROOT, self.row, self.sources, ())
        PROOF._verify_protected_files(ROOT, {"protected_file": self.rows})

    def test_missing_or_unregistered_projection_caller_is_rejected(self):
        PROOF._verify_boundary(ROOT, self.row, self.sources, ())
        with self.assertRaisesRegex(PROOF.VerificationFailure, "unexpected"):
            PROOF._verify_boundary(ROOT, replace(self.row, product_callers=()), self.sources, ())
        sources = {**self.sources, AGENT + "unregistered_b_projection.rs": "fn extra() { OriginalRootBPublicationDataV2::encode_original(); }"}
        with self.assertRaisesRegex(PROOF.VerificationFailure, "unexpected"):
            PROOF._verify_boundary(ROOT, self.row, sources, ())

    def test_removing_manifest_binding_or_exact_readback_is_rejected(self):
        cases = (
            (EXECUTE, "manifest: &self.plan.record().candidate.manifest"),
            (EXECUTE, "execution != self.execution"),
            (EXECUTE, "decision.authentication_digest.is_zero()"),
            (EXECUTE, "decision.decision.authority != AuthorityPosture::DENY_ALL"),
            (EXECUTE, ".original_bytes(&bytes, self.mode)"),
            (DATA, "schema: 2"),
            (DATA, "manifest_digest: manifest.digest().map_err(io::Error::other)?"),
            (DATA, "manifest: manifest.clone()"),
            (DATA, "self.schema != 2"),
            (DATA, "self.purpose != PURPOSE"),
            (DATA, "self.manifest.digest().map_err(io::Error::other)? != self.manifest_digest"),
            (DATA, "serde_json::to_vec(&data).map_err(io::Error::other)? != bytes"),
            (OUTPUTS, "OriginalBResultMode::Readback => self.journal.read(&self.key)"),
            (OUTPUTS, "if saved != bytes"),
        )
        for path, marker in cases:
            with self.subTest(path=path, marker=marker), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                rows = [row for row in self.rows if row["path"] == path]
                target = root / path
                target.parent.mkdir(parents=True)
                target.write_text(self.raw[path])
                PROOF._verify_protected_files(root, {"protected_file": rows})
                self.assertIn(marker, self.raw[path])
                target.write_text(self.raw[path].replace(marker, "", 1))
                with self.assertRaises(PROOF.VerificationFailure):
                    PROOF._verify_protected_files(root, {"protected_file": rows})


if __name__ == "__main__":
    unittest.main()
