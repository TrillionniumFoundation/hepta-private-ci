"""Keep the complete historical recipient context inside the RunStart arm.

These source mutations do not execute the actual UID0 storage tests or prove
the final Source/Cell/Ledger/RunStart historical product join.
"""

from dataclasses import replace
import tomllib
import unittest

import test_original_run_start_retention_source_closure as original


ROOT = original.ROOT
PROOF = original.PROOF
PATH = original.A + "authority_host_run_start_historical.rs"
CALLERS = {
    "root_initial_run_start_historical_context": (),
    "root_initial_run_start_historical_publisher": (),
    "root_initial_run_start_historical_physical": (),
    "root_initial_run_start_historical_digest": (),
    "root_initial_run_start_physical_unchecked": (PATH,),
}


def require_structure(source):
    code = original.component.function_code(source, "with_original_run_start_data<T>")
    begin, end = original.span(code, "RootDataRefusalV1::inspect(&self.refusal, || {")
    action = code.index("let value = action(&read)?")
    finish = code.index("read.finish()?")
    if not begin < action < finish < end:
        raise PROOF.VerificationFailure("entire historical action and postchecks require one arm")
    all_code = PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code(source))
    if all_code.count("RootDataRefusalV1::inspect(") != 1:
        raise PROOF.VerificationFailure("borrowed historical read must not nest refusal arms")


class RunStartHistoricalJoinSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text())
        cls.boundaries = {r.identifier: r for r in PROOF._boundary_rows(cls.manifest)}
        paths = {PATH, original.STORE}
        cls.sources = {path: PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code(
            (ROOT / path).read_text())) for path in paths}

    def verify_path(self, root, path):
        rows = [r for r in self.manifest["protected_file"] if r["path"] == path]
        self.assertTrue(rows)
        PROOF._verify_protected_files(root, {"protected_file": rows})
        require_structure((root / path).read_text())

    mutation = original.OriginalRunStartRetentionSourceTests.mutation
    remove = original.OriginalRunStartRetentionSourceTests.remove

    def test_only_actual_unchecked_reader_has_a_product_caller(self):
        for identifier, expected in CALLERS.items():
            with self.subTest(boundary=identifier):
                row = self.boundaries[identifier]
                self.assertIn(identifier, self.manifest["privileged_inventory"]["required_boundary_ids"])
                self.assertEqual(row.product_callers, expected)
                PROOF._verify_boundary(ROOT, row, self.sources, ())
        row = self.boundaries["root_initial_run_start_physical_unchecked"]
        with self.assertRaisesRegex(PROOF.VerificationFailure, "unexpected"):
            PROOF._verify_boundary(ROOT, replace(row, product_callers=()), self.sources, ())

    def test_unregistered_whole_context_or_borrowed_data_calls_are_rejected(self):
        for identifier in CALLERS:
            with self.subTest(boundary=identifier):
                row = self.boundaries[identifier]
                method = row.symbol.rsplit("::", 1)[-1]
                sources = dict(self.sources)
                sources[original.A + "unregistered_run_start_join.rs"] = (
                    f"fn unregistered(owner: &{row.receiver_type}) {{ owner.{method}(); }}"
                )
                with self.assertRaisesRegex(PROOF.VerificationFailure, "unexpected"):
                    PROOF._verify_boundary(ROOT, row, sources, ())

    def test_whole_actual_action_finishes_before_refusal_can_become_ready(self):
        self.remove(PATH, "with_original_run_start_data<T>", (
            "RootDataRefusalV1::inspect(&self.refusal, || {", "require_end(end)?",
            "self.state.require_exact_unchecked()?", "state: Mutex::new(ReadState::AwaitingBinding)",
            "failed: AtomicBool::new(false)", "let value = action(&read)?", "read.finish()?",
        ))

    def test_publisher_match_contains_every_original_registration_field(self):
        self.remove(PATH, "require_original_publisher", (
            "std::mem::replace(&mut *state, ReadState::Verifying)", "ReadState::AwaitingBinding",
            "require_end(self.end)?", "self.retained.state.require_exact_unchecked()?",
            "neuron_generation_process_identity_digest_v1(identity)",
            "original.spawn_generation != identity.spawn_generation", "&original.target != target",
            "target.scope().agent_id != identity.agent_id.as_str()", "&original.publisher != publisher",
            "original.publisher_epoch != publisher_epoch", "publisher_epoch == 0",
            "original.initial_profile != initial_profile", "original.writer != writer",
            "original.target_files != target_files", "*state = ReadState::Bound(identity.clone())",
        ))

    def test_real_read_holds_original_files_and_cannot_swallow_failure(self):
        self.remove(PATH, "read_original_publication", (
            "let ReadState::Bound(bound_identity)",
            "std::mem::replace(&mut *state, ReadState::Verifying)", "if &bound_identity != identity",
            "RootRetainedRunStartDataV1::read_original_publication_unchecked(",
            "*state = ReadState::Complete {", "files,", "identity: bound_identity", "frame: frame.clone()",
        ))
        self.remove(PATH, "retained_digest", (
            "std::mem::replace(&mut *state, ReadState::Verifying)", "ReadState::Complete { .. }",
            "self.retained.state.require_exact_unchecked()?", "*state = complete",
        ))

    def test_finish_repeats_physical_record_and_checks_actual_original_end(self):
        self.remove(PATH, "finish", (
            "let ReadState::Complete {", "std::mem::replace(&mut *state, ReadState::Verifying)",
            "RootRetainedRunStartDataV1::read_original_publication_unchecked(", ")? != frame",
            "self.retained.state.require_exact_unchecked()?", "if self.failed.load(Ordering::Acquire)",
            "require_end(self.end)",
        ))
        for name in ("require_original_publisher", "read_original_publication", "retained_digest", "finish"):
            self.remove(PATH, name, ("self.failed.store(true, Ordering::Release)",))

    def test_ignored_root_parent_is_in_exact_native_roster(self):
        name = "authority_host_service::generation_initial::run_start_retention::tests::root_run_start_historical_join_cannot_skip_or_swallow_physical_read"
        workflow = (ROOT / ".github/workflows/hepta-daemon-learning-native.yml").read_text()
        self.assertEqual(workflow.count('"' + name + '"'), 1)
        tests = (ROOT / original.A / "authority_host_run_start_retention_tests.rs").read_text()
        self.assertIn("fn root_run_start_historical_join_cannot_skip_or_swallow_physical_read()", tests)
        self.assertIn("assert!(read.retained_digest().is_err())", tests)
        self.assertIn("assert!(RootRetainedRunStartDataV1::open_finalized(root, &target).is_err())", tests)


if __name__ == "__main__":
    unittest.main()
