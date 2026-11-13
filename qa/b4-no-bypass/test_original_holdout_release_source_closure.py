"""Original consumption continuity, not Root/data-custody authority."""

import importlib.util
from pathlib import Path
import sys
import tempfile
import tomllib
import unittest


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "original_holdout_release_proof", ROOT / "scripts/verify_hepta_callers.py"
)
assert SPEC is not None and SPEC.loader is not None
PROOF = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PROOF
SPEC.loader.exec_module(PROOF)
PREFIX = "codex-rs/hepta-intelligence-eval/src/"
RELEASE = PREFIX + "product_holdout_release.rs"
RUNNER = PREFIX + "product_runner.rs"
OWNER = PREFIX + "fenced_holdout.rs"
BOUNDARIES = {"product_original_holdout_release", "product_original_holdout_consumption_read"}


class OriginalHoldoutReleaseSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text())
        cls.rows = [row for row in cls.manifest["protected_file"] if row["path"] in (RELEASE, RUNNER, OWNER)]
        assert {row["path"] for row in cls.rows} == {RELEASE, RUNNER, OWNER}
        all_boundaries = PROOF._boundary_rows(cls.manifest)
        PROOF._verify_privileged_inventory(cls.manifest, all_boundaries)
        cls.boundaries = [row for row in all_boundaries if row.identifier in BOUNDARIES]
        assert {row.identifier for row in cls.boundaries} == BOUNDARIES
        cls.source_index = None

    @classmethod
    def index(cls):
        if cls.source_index is None:
            cls.source_index = {
                path.relative_to(ROOT).as_posix(): PROOF._strip_cfg_test_items(
                    PROOF._strip_rust_non_code(path.read_text()))
                for path in PROOF._source_files(ROOT, tuple(cls.manifest["source_roots"]))
            }
        return cls.source_index

    def reject_removal(self, path, function, markers):
        source = (ROOT / path).read_text()
        code = PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code(source))
        self.assertEqual(code.count(function), 1)
        start = code.index(function)
        end = PROOF._rust_item_end(code, start)
        self.assertIsNotNone(end)
        rows = [row for row in self.rows if row["path"] == path]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / path
            target.parent.mkdir(parents=True)
            target.write_text(source)
            PROOF._verify_protected_files(root, {"protected_file": rows})
            for marker in markers:
                with self.subTest(function=function, marker=marker):
                    offset = source.index(marker, start, end + 1)
                    target.write_text(source[:offset] + "/* " + marker + " */" + source[offset + len(marker):])
                    with self.assertRaises(PROOF.VerificationFailure):
                        PROOF._verify_protected_files(root, {"protected_file": rows})

    def test_actual_function_guards(self):
        PROOF._verify_protected_files(ROOT, {"protected_file": self.rows})

    def test_actual_two_caller_sets_scan_every_rust_source(self):
        for boundary in self.boundaries:
            with self.subTest(boundary=boundary.identifier):
                PROOF._verify_boundary(ROOT, boundary, self.index(), tuple(self.manifest["ignored_path_fragments"]))

    def test_undeclared_original_read_caller_is_rejected(self):
        boundary = next(row for row in self.boundaries if row.identifier == "product_original_holdout_consumption_read")
        index = dict(self.index())
        index["codex-rs/hepta-intelligence-eval/src/unregistered_release.rs"] = """
            fn unregistered<S: FinalHoldoutCasStoreV1>(owner: &mut FencedFinalHoldoutOwnerV1<S>, plan: &CrossFoldPlanReceiptV1) {
                FencedFinalHoldoutOwnerV1::read_consumption(owner, plan);
            }
        """
        with self.assertRaisesRegex(PROOF.VerificationFailure, "caller set mismatch"):
            PROOF._verify_boundary(ROOT, boundary, index, tuple(self.manifest["ignored_path_fragments"]))

    def test_undeclared_release_caller_is_rejected(self):
        boundary = next(row for row in self.boundaries if row.identifier == "product_original_holdout_release")
        index = dict(self.index())
        index["codex-rs/hepta-intelligence-eval/src/unregistered_release.rs"] = "fn unregistered() { release_original_holdout(owner, plan, receipt, provider); }"
        with self.assertRaisesRegex(PROOF.VerificationFailure, "caller set mismatch"):
            PROOF._verify_boundary(ROOT, boundary, index, tuple(self.manifest["ignored_path_fragments"]))

    def test_original_receipt_requires_full_namespace_record_and_disposition(self):
        self.reject_removal(RELEASE, "fn require_recorded(", (
            "original.observe_consumption(plan)?", "namespace != actual_namespace",
            "receipt.disposition != HoldoutUseDispositionV1::Recorded", "actual.as_ref() != Some(receipt)"))

    def test_borrow_rechecks_after_callback_including_error(self):
        self.reject_removal(RELEASE, "fn with_current_consumption(", (
            "require_recorded(self.original, self.namespace, self.plan, self.receipt)",
            "let released = release(self.namespace, self.plan, self.receipt)",
            "require_recorded(self.original, self.namespace, self.plan, self.receipt)\n            .map_err(|_| ProductProviderErrorV1::Indeterminate)?;\n        released"))

    def test_runner_checks_before_proof_and_after_provider_regardless_of_borrow_use(self):
        self.reject_removal(RELEASE, "fn release_original_holdout<S: FinalHoldoutCasStoreV1, P: FinalHoldoutProviderV1>(", (
            "FencedFinalHoldoutOwnerV1::read_consumption(original, plan)?",
            "receipt.disposition != HoldoutUseDispositionV1::Recorded", "recorded.as_ref() != Some(receipt)",
            "provider.release_after_original_consumption(OriginalFinalHoldoutConsumptionV1",
            "require_recorded(original, namespace, plan, receipt)?"))

    def test_receipt_only_entry_refuses_and_default_adapter_keeps_borrow(self):
        self.reject_removal(RUNNER, "fn release_after_consumption(", ("Err(ProductProviderErrorV1::Rejected)",))
        self.reject_removal(RUNNER, "fn release_after_original_consumption(", ("consumed.with_current_consumption(",))

    def test_fitting_follows_manifest_consumption_and_original_release(self):
        self.reject_removal(RUNNER, "fn evaluate_temporal_comparison<P: FinalHoldoutProviderV1>(", (
            "product_plan.validate_integrity()?", "manifest != product_plan.frozen_plan.final_holdout_digest",
            "self.holdout.consume(&product_plan.frozen_plan)?", "holdout_release::release_original_holdout(",
            "validate_released_inputs(&product_plan.frozen_plan, &inputs)?", "validate_comparable_observations("))

    def test_owner_reads_current_store_fence_snapshot_and_exact_plan(self):
        self.reject_removal(OWNER, "fn read_consumption(", (
            "if self.poisoned", ".load(self.binding)?", "current.validate(self.binding)?",
            "if current.fence != self.fence", "if current.state_digest != self.state_digest",
            "if journal.snapshot() != self.journal.snapshot()", "if &record.plan != plan"))


if __name__ == "__main__":
    unittest.main()
