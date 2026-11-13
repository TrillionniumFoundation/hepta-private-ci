"""The independent B source receives its own original Root handoff.

Source closure proves neither independent business observation nor a native
ordinary learning run. Those require their actual external owners and files.
"""

from pathlib import Path
import tempfile
import tomllib
import unittest

import test_historical_ledger_readonly_source_closure as component

ROOT, A, PROOF = component.ROOT, component.AGENT, component.PROOF
PREPARED = A + 'authority_host_historical_read_session.rs'
WORKER = A + 'authority_host_post_a_worker.rs'
CLI = A + 'bin/hepta-authority-host.rs'


class PostAIndependentSourceHandoffTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = tomllib.loads((ROOT / 'CALLERS.toml').read_text())

    reject_removal = component.HistoricalLedgerReadonlySourceTests.reject_removal
    check_markers = component.HistoricalLedgerReadonlySourceTests.check_markers

    def test_original_plan_keeps_two_distinct_b_handoffs_in_the_same_root_context(self):
        self.check_markers(PREPARED, 'fn enable_original_post_a_learning_with_independent_b(', (
            'independent_evaluation: Option<(&Path, UnixDatagram, UnixDatagram)>',
            'independent_evaluation.is_some() && publication.is_none()',
            'independent_evaluation.as_ref().map(|(path, _, _)| *path)',
            'Some((_, evaluation, source)) => (Some(evaluation), Some(source))',
            'None => (None, None)', 'post_a_worker::prepare(',
            'independent_evaluation,', 'independent_source,'))

    def test_both_listeners_are_bound_before_the_source_offer_or_learner_offers_escape(self):
        self.check_markers(WORKER, 'fn run_installation(', (
            'independent_b.is_some() != inputs.independent_b_handoff.is_some()',
            'independent_b.is_some() != inputs.independent_source_handoff.is_some()',
            'BoundLearning::bind(learning, config, publication)?',
            'PreparedRootIndependentBEvaluationV1::take_original_source_offer(&mut prepared)?',
            'PreparedRootIndependentBEvaluationV1::into_original_parts(prepared)',
            'BoundLearning::bind_original_independent_b(',
            '(inputs.independent_source_handoff, independent_source_offer)',
            'crate::send_root_independent_b_source_handoff(',
            'crate::send_root_learning_handoff('))

    def test_source_handoff_does_not_renew_the_session_or_acknowledge_installation_early(self):
        self.check_markers(WORKER, 'fn run_installation(', (
            'let end = submission.end.min(session_end)',
            'end.checked_duration_since(Instant::now())',
            '.map(|duration| duration.min(timeout))',
            'crate::send_root_independent_b_evaluation_handoff(',
            'compare_exchange(SUBMITTED, INSTALLED, Ordering::AcqRel, Ordering::Acquire)',
            'submission\n        .acknowledgement\n        .try_send(())',
            'crate::authority_host_runtime::serve_independent_b_until('))
        self.check_markers(WORKER, 'fn prepare(', (
            'independent_source_handoff: Option<UnixDatagram>',
            'Mutex::new(Some(OriginalInputs {', 'independent_source_handoff,'))

    def test_cli_requires_the_separate_original_descriptor_and_takes_it_once(self):
        rows = [row for row in self.manifest['protected_file'] if row['path'] == CLI]
        source = (ROOT / CLI).read_text()
        for marker in (
            'independent_b_deployment.is_some() != independent_source_handoff.is_some()',
            'let mut independent_source_handoff = independent_source_handoff',
            'independent_source_handoff.take()',
            'std::os::unix::net::UnixDatagram::from(source)',
        ):
            self.assertEqual(source.count(marker), 1)
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                target = root / CLI
                target.parent.mkdir(parents=True)
                target.write_text(source)
                PROOF._verify_protected_files(root, {'protected_file': rows})
                target.write_text(source.replace(marker, 'removed_source_handoff_guard'))
                with self.assertRaises(PROOF.VerificationFailure):
                    PROOF._verify_protected_files(root, {'protected_file': rows})


if __name__ == '__main__':
    unittest.main()
