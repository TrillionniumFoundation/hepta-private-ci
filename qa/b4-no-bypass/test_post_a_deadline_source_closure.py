"""Original control deadlines and Training capacity remain refusal boundaries.

These source mutation checks do not replace the native Unix socket tests or a
complete ordinary daemon and Root learning run.
"""

from pathlib import Path
import tempfile
import tomllib
import unittest

import test_historical_ledger_readonly_source_closure as component

ROOT, A, PROOF = component.ROOT, component.AGENT, component.PROOF
CONTROL = A + 'client_control.rs'
FEATURE = A + 'circuit_feature_learning_source.rs'


class PostADeadlineSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = tomllib.loads((ROOT / 'CALLERS.toml').read_text())

    reject_removal = component.HistoricalLedgerReadonlySourceTests.reject_removal
    check_markers = component.HistoricalLedgerReadonlySourceTests.check_markers

    def test_original_training_capacity_is_checked_before_any_owner_initialization(self):
        self.check_markers(A + 'production_post_a_q24_owners.rs',
                           'fn require_original_training_capacity(', (
            'self.training_receipt.owner.max_records < 5', 'return Err(', 'Ok(())'))
        self.check_markers(A + 'production_post_a_q24_owners.rs',
                           'fn into_original_inputs(', (
            'Self::require_original_training_capacity(&self)?',
            'prepared.revalidate_source()', 'self.experience'))
        self.check_markers(A + 'production_post_a_q24_deployment.rs', 'fn read(', (
            'serde_json::from_slice(&bytes)?',
            'owners::StageFilesData::require_original_training_capacity(&data.stages)?',
            'Ok(data)'))

    def test_each_transport_phase_preserves_the_original_absolute_end(self):
        self.check_markers(CONTROL, 'fn original_phase_end(', (
            'let now = Instant::now()',
            'end.map_or(now + self.timeout, |end| (now + self.timeout).min(end))',
            'if now >= deadline', 'return Err(', 'Ok(deadline)'))
        self.check_markers(CONTROL, 'fn objective_start_once_until(', (
            'self.objective_start_with_original_end(request, Some(end))',))
        self.check_markers(CONTROL, 'fn send_once_with_original_end(', (
            'self.original_phase_end(end)?',
            'timeout_at(self.original_phase_end(end)?, writer.write_all(&bytes))',
            'timeout_at(read_end, reader.read_until',
            'end.is_some_and(|end| Instant::now() >= end)'))

    def test_postwrite_transport_uncertainty_is_not_completed_or_resent(self):
        self.check_markers(CONTROL, 'fn send_once_with_original_end(', (
            'BufReader::new(reader).take(MAX_CONTROL_FRAME_BYTES + 1)',
            '.map_err(ControlCallError::AcknowledgementLost)',
            'if count == 0', 'if count as u64 > MAX_CONTROL_FRAME_BYTES || !response_bytes.ends_with',
            'response_bytes.as_slice() == AGENTD_CONTROL_OVERLOAD_FRAME',
            'response.schema_version != AGENTD_CONTROL_SCHEMA_VERSION',
            'response.request_id != expected_request_id',
            'response.agent_id != self.expected_agent_id',
            'response.spawn_generation != self.spawn_generation'))
        self.check_markers(CONTROL, 'fn objective_start_with_original_end(', (
            'Err(ControlCallError::AcknowledgementLost(error))',
            'ObjectiveStartReplyV1::AcknowledgementLost(error)',
            'Err(ControlCallError::Rejected(error)) => return Err(error)',
            'payload => return unexpected(payload)'))

    def test_feature_uses_the_original_source_window_lease_and_root_end(self):
        self.check_markers(FEATURE, 'fn submit_until(', (
            'self.submit_with_original_end(request, Some(original_end.into()))',))
        self.check_markers(FEATURE, 'fn submit_with_original_end(', (
            'deadline_micros', '.checked_sub(source.monotonic_micros)',
            'Duration::from_micros(window)',
            '.min(Duration::from_millis(source.lease_duration_ms))',
            '.min(Duration::from_secs(60))',
            '(Instant::now() + budget).min(end)',
            'if Instant::now() >= deadline',
            'objective_start_once_until(request, deadline)'))

    def test_feature_physical_readback_cannot_return_success_after_the_clamped_end(self):
        self.check_markers(FEATURE, 'fn submit_with_original_end(', (
            'ObjectiveStartReplyV1::AcknowledgementLost(error)',
            'observe_original_after_ack(deadline, expected, error)',
            'self.readback()?', 'completed.require_original_admission(&expected)?',
            'original_end.is_some() && Instant::now() >= deadline', 'Ok(completed)'))

    def test_control_and_feature_reject_detachment_resend_or_local_authority(self):
        for path, injected in (
            (CONTROL, 'fn bypass() { tokio::spawn(work); }'),
            (CONTROL, 'fn bypass() { loop { resend(); } }'),
            (CONTROL, 'fn bypass() { self.timeout = renewed; }'),
            (FEATURE, 'fn bypass() { key.sign(bytes); }'),
            (FEATURE, 'fn bypass() { owner.request_grant(); }'),
        ):
            rows = [row for row in self.manifest['protected_file'] if row['path'] == path]
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                target = root / path
                target.parent.mkdir(parents=True)
                source = (ROOT / path).read_text()
                target.write_text(source)
                PROOF._verify_protected_files(root, {'protected_file': rows})
                target.write_text(source + '\n' + injected)
                with self.assertRaises(PROOF.VerificationFailure):
                    PROOF._verify_protected_files(root, {'protected_file': rows})


if __name__ == '__main__':
    unittest.main()
