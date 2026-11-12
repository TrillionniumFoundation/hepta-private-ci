"""Guard the actual drained Initial Source handoff, without claiming execution."""

import unittest

import test_initial_artifact_readview_source_closure as component


CASES = [['control.rs',
  'fn run_for<P>(',
  ['JoinSet::new()',
   '_ = self.cancellation.cancelled() => break',
   'connections.spawn(async move',
   'while let Some(completion) = connections.join_next().await',
   'if let Some(error) = failure',
   'completion.acknowledge_original_control_completion()?']],
 ['control_source_capture.rs',
  'fn require_original_control_join(',
  ['self.0.try_recv()', 'Ok(OriginalControlJoinedV1 { _private: () })']],
 ['runtime_source_capture.rs',
  'fn run_until_original_source_drain(',
  ['Arc::downgrade(&state)',
   'shutdown.await?',
   'super::drain_runtime(state).await?',
   'completed.send(())',
   'observed.try_recv()',
   'control.require_original_control_join()?',
   'drained.require_released_state()?']],
 ['runtime_source_capture.rs',
  'fn require_released_state(',
  ['self.state.upgrade().is_some()']],
 ['circuit_task_source_close.rs',
  'fn retain_original_source_close<W>(',
  ['Arc::try_unwrap(source)',
   'Arc::try_unwrap(source.0)',
   'owner.into_inner()',
   'owner.require_current().map_err(agent_error)?',
   'drop(owner)']],
 ['circuit_task_source_close.rs',
  'fn close_after_drain(',
  ['drained.require_released_state()?',
   '(self.close)()?',
   'Ok(OriginalCircuitSourceClosedV1 { _private: () })']],
 ['config_source_capture.rs',
  'fn with_original_source_close<W>(',
  ['self.original_source_close.is_some()',
   'OriginalCircuitSourceCloseV1::retain_original_source_close(']],
 ['config_source_capture.rs',
  'fn install_original_source_capture(',
  ['self.original_source_close.is_none()',
   'self.circuit_task_bootstrap.is_none()',
   'self.circuit_task_invocation.is_none()',
   'request.identity != self.identity',
   'self.original_source_capture = Some(request)']],
 ['config_source_capture.rs',
  'fn take_original_source_capture(',
  ['self.original_source_capture.take()',
   'self.original_source_close.take()',
   '(Some(request), Some(close)) => Ok(Some((request, close)))']],
 ['root_generation_initial_source_capture.rs',
  'fn require_source_capture_session(',
  ['self.connection.require_same_original_session(session)?',
   'self.connection.original_launch_binding().1 != identity',
   'validate_profile(&self.profile)?',
   'self.observe_initial_current()?',
   'original_initial_record(&self.profile.prepared, &head)?.ok_or_else(uncertain)?',
   'self.connection.require_same_original_session(session)']],
 ['root_generation_initial_source_capture.rs',
  'fn capture_source_after_quiescence(',
  ['_closed: OriginalCircuitSourceClosedV1',
   'self.connection.require_original_publication_session()?',
   'self.observe_initial_current()?',
   'original_initial_record(&self.profile.prepared, &head)?.ok_or_else(uncertain)?',
   'self.lane.try_lock()',
   'self.fenced.store(true, Ordering::Release)',
   'held.take().ok_or_else(uncertain)?',
   'self.fenced.store(true, Ordering::Release)',
   'captured_id.checked_add(1)',
   'acknowledged_id.checked_add(1)',
   'Command::CaptureSource {}',
   'SourceCapturePhase::Captured',
   'Command::CaptureAck {}',
   '.exchange_source_capture_terminal(',
   'SourceCapturePhase::Acknowledged',
   'acknowledged != pin',
   'self.connection.require_original_publication_session()']],
 ['root_generation_initial_source_capture.rs',
  'fn source_capture_reply(',
  ['serde_json::from_slice(raw)',
   'reply.pin.parse()',
   'reply.schema != 1',
   'reply.purpose != SOURCE_CAPTURE_PURPOSE',
   'reply.request_id != request_id',
   'reply.profile != self.profile',
   'reply.mode != self.mode',
   'reply.phase != phase',
   'pin.is_zero()',
   'pin.to_string() != reply.pin']],
 ['root_generation_publication_source_close.rs',
  'fn exchange_source_capture_terminal(',
  ['request.len() > 16_384',
   '(Instant::now() + self.timeout).min(self.end)',
   'check_lifetime(&self.root)',
   'self.stream.shutdown(Shutdown::Write)?',
   'self.read_source_capture_terminal(&mut prefix, end)?',
   'size == 0 || size > 16_384',
   'self.read_source_capture_terminal(&mut response, end)?',
   'self.wait_source_capture_terminal(end)?',
   'Ok(0) => break',
   'Ok(_) => return Err(unavailable())',
   'check_lifetime(&self.root)',
   'Instant::now() >= end']],
 ['root_generation_publication_source_close.rs',
  'fn wait_source_capture_terminal(',
  ['.checked_duration_since(Instant::now())',
   'fd: self.root.as_raw_fd()',
   'fd: self.stream.as_raw_fd()',
   'fds[0].revents != 0',
   'fds[1].revents & (libc::POLLERR | libc::POLLNVAL) != 0',
   'Instant::now() >= end',
   'fds[1].revents & (libc::POLLIN | libc::POLLHUP) != 0']],
 ['production_source_capture.rs',
  'fn retain_original_initial_source_capture(',
  ['self.original_source_capture.is_some()',
   'self.root.bootstrap.registered_identity.identity()?',
   'published.original_initial_source_current(&self.root.session, &identity)?',
   'OriginalSourceCaptureRequestV1 { identity, current }']],
 ['production_source_capture.rs',
  'fn capture_after_close(',
  ['closed: OriginalCircuitSourceClosedV1',
   'tokio::task::spawn_blocking(move || self.current.capture_original_initial_source(closed))',
   '.await']],
 ['neuron_generation_update_live.rs',
  'fn original_initial_source_current(',
  ['RetainedPublication::Initial(_)',
   'self.check_current(self.publication.target())',
   '.require_original_initial_source_session(session, identity)?',
   'self.check_current(self.publication.target())',
   'Arc::clone(&self.current)']],
 ['runtime.rs',
  'fn run_with_shutdown(',
  ['config.take_original_source_capture()?',
   'control.original_source_capture_join()',
   'source_capture::run_until_original_source_drain(&mut tasks, state, shutdown, joined)',
   'close.close_after_drain(drained)?',
   'capture.capture_after_close(closed).await']]]


CASES.append(['control.rs', 'fn serve_connection(', ['request.schema_version == AGENTD_CONTROL_SCHEMA_VERSION', 'state.circuit_task_enabled()', 'crate::AgentdMethod::ObjectiveStart', 'P::response(&state, request).await', 'let completed_circuit = circuit_admission', 'matches!(&response.payload, AgentdPayload::ObjectiveRun(receipt)', 'if receipt.disposition', '.eq("circuit_succeeded")', 'match frames::write_frame(&mut writer, &bytes).await', 'Err(AgentdError::Io(error))', 'if completed_circuit', 'ErrorKind::BrokenPipe | ErrorKind::ConnectionReset', 'result => result']])

class OriginalSourceExitClosureTests(unittest.TestCase):
    setUpClass = classmethod(component.InitialArtifactReadviewClosureTests.setUpClass.__func__)
    reject_removal = component.InitialArtifactReadviewClosureTests.reject_removal
    # Reuse the mutation helper without inheriting another component's tests.
    def verify_cases(self, indices):
        for index in indices:
            filename, function, markers = CASES[index]
            seen = {}
            for marker in markers:
                occurrence = seen.get(marker, 0)
                seen[marker] = occurrence + 1
                with self.subTest(file=filename, function=function, marker=marker, occurrence=occurrence):
                    self.reject_removal(filename, function, marker, occurrence)

    def test_only_original_completed_circuit_ack_disconnect_is_nonfatal(self):
        self.verify_cases([18])

    def test_control_completion_requires_all_accepted_connections(self):
        self.verify_cases([0, 1])

    def test_drain_receipt_requires_original_state_release(self):
        self.verify_cases([2, 3])

    def test_source_close_requires_both_original_owners(self):
        self.verify_cases([4, 5])

    def test_config_transfers_the_exact_source_and_selector(self):
        self.verify_cases([6, 7, 8])

    def test_capture_consumes_same_initial_lane_and_checks_both_replies(self):
        self.verify_cases([9, 10, 11])

    def test_terminal_framing_requires_original_deadline_and_clean_eof(self):
        self.verify_cases([12, 13])

    def test_launcher_retains_current_until_actual_capture_finishes(self):
        self.verify_cases([14, 15, 16, 17])


if __name__ == "__main__":
    unittest.main()
