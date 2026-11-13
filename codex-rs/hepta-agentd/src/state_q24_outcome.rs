//! An accepted control future owns the real producer until its work returns.
//! A failed postcheck is uncertainty, even if the original append completed.

use codex_hepta_agent_protocol::Q24OriginalInitialTaskCompletionV1;
use codex_hepta_agent_protocol::Q24OriginalInitialTaskProgressV1;
use codex_hepta_agent_protocol::Q24OriginalTaskObservationV1;
use codex_hepta_agent_protocol::Q24OriginalTerminalOutcomeReceiptV1;
use codex_hepta_agent_protocol::Q24OriginalTerminalOutcomeRequestV1;
use codex_hepta_fleet::AgentLifecycle;

use super::*;

impl AgentdState {
    pub(crate) async fn read_original_q24_initial_task_progress(
        &self,
        request: &crate::AuthBusObjectiveIngress,
    ) -> Result<Q24OriginalInitialTaskProgressV1, AgentdError> {
        let original_started = std::time::Instant::now();
        trace_original_progress_phase(original_started, "current-before", None);
        self.require_original_q24_outcome_current()?;
        trace_original_progress_phase(original_started, "current-returned", None);
        let producer: &Arc<crate::OriginalCellQ24TaskLedgerProducerV1> =
            self.original_q24_outcome_control.get().ok_or_else(|| {
                AgentdError::Protocol("original Initial task producer unavailable".into())
            })?;
        let host: &Arc<crate::objective_runtime::ObjectiveRuntimeHost> =
            self.objective_runtime.get().ok_or_else(|| {
                AgentdError::Protocol("original Initial RunStart owner unavailable".into())
            })?;
        trace_original_progress_phase(original_started, "host-before", None);
        let (admission, record) =
            crate::objective_runtime::ObjectiveRuntimeHost::read_original_initial_request(
                host,
                &self.identity,
                request,
            )?;
        trace_original_progress_phase(original_started, "host-returned", None);
        trace_original_progress_phase(original_started, "run-start-before", None);
        self.require_current_run_start(&record)?;
        trace_original_progress_phase(original_started, "run-start-returned", None);
        trace_original_progress_phase(original_started, "producer-current-before", None);
        crate::OriginalCellQ24TaskLedgerProducerV1::require_original_initial_request(
            producer,
            &self.identity,
            &record,
        )?;
        trace_original_progress_phase(original_started, "producer-current-returned", None);
        let original_pending = self.circuit_task_pending_count();
        trace_original_progress_phase(original_started, "pending-sampled", Some(original_pending));
        let observed = if original_pending != 0 {
            // Only actual owned admission/worker guards produce InFlight.
            // Source, journal, signature and completion errors never do.
            trace_original_progress_phase(original_started, "in-flight", Some(original_pending));
            Ok(Q24OriginalInitialTaskProgressV1::InFlight {})
        } else {
            async {
                trace_original_progress_phase(original_started, "producer-before", None);
                let before =
                    crate::OriginalCellQ24TaskLedgerProducerV1::read_original_initial_task_observation(
                        producer, &self.identity, &record,
                    )?;
                trace_original_progress_phase(original_started, "producer-before-returned", None);
                trace_original_progress_phase(original_started, "store-before", None);
                let store = self.circuit_task_store()?;
                trace_original_progress_phase(original_started, "store-returned", None);
                trace_original_progress_phase(original_started, "trace-before", None);
                let trace = store
                    .bounded_circuit_committed_trace(record.snapshot.run_id.as_str())
                    .await
                    .map_err(|error| AgentdError::Protocol(format!("original Initial trace: {error}")))?
                    .ok_or_else(|| AgentdError::Protocol("original Initial trace missing".into()))?;
                trace_original_progress_phase(original_started, "trace-before-returned", None);
                if trace.run().outcome() != Some(codex_hepta_automation::CircuitExitV2::Succeeded)
                    || trace.run().unresolved() != 0
                    || trace.run().run_id() != record.snapshot.run_id.as_str()
                    || trace.history_digest() != before.1.history_digest()
                {
                    return Err(AgentdError::Protocol(
                        "original Initial successful trace/Source differs".into(),
                    ));
                }
                trace_original_progress_phase(original_started, "producer-after", None);
                let after =
                    crate::OriginalCellQ24TaskLedgerProducerV1::read_original_initial_task_observation(
                        producer, &self.identity, &record,
                    )?;
                trace_original_progress_phase(original_started, "producer-after-returned", None);
                trace_original_progress_phase(original_started, "trace-after", None);
                let after_trace = store
                    .bounded_circuit_committed_trace(record.snapshot.run_id.as_str())
                    .await
                    .map_err(|error| AgentdError::Protocol(format!("original Initial trace: {error}")))?;
                trace_original_progress_phase(original_started, "trace-after-returned", None);
                if before != after
                    || after_trace.as_ref() != Some(&trace)
                    || self.circuit_task_pending_count() != 0
                {
                    return Err(AgentdError::Protocol(
                        "original Initial completion changed during observation".into(),
                    ));
                }
                trace_original_progress_phase(original_started, "completed", None);
                Ok(Q24OriginalInitialTaskProgressV1::Completed {
                    data: Box::new(Q24OriginalInitialTaskCompletionV1 {
                        admission: admission.clone(),
                        observation: before.0,
                        circuit_revision: trace.run().revision(),
                        circuit_history_digest: trace.history_digest().as_str().to_owned(),
                    }),
                })
            }
            .await
        };
        trace_original_progress_phase(original_started, "body-returned", None);
        // Current owner/trust and exact request checks run even after a failed
        // observation. A zero pending count never supplies completion evidence.
        trace_original_progress_phase(original_started, "post-host-before", None);
        let after = crate::objective_runtime::ObjectiveRuntimeHost::read_original_initial_request(
            host,
            &self.identity,
            request,
        )?;
        trace_original_progress_phase(original_started, "post-host-returned", None);
        trace_original_progress_phase(original_started, "post-run-start-before", None);
        self.require_current_run_start(&record)?;
        trace_original_progress_phase(original_started, "post-run-start-returned", None);
        trace_original_progress_phase(original_started, "post-producer-current-before", None);
        crate::OriginalCellQ24TaskLedgerProducerV1::require_original_initial_request(
            producer,
            &self.identity,
            &record,
        )?;
        trace_original_progress_phase(original_started, "post-producer-current-returned", None);
        trace_original_progress_phase(original_started, "post-current-before", None);
        self.require_original_q24_outcome_current()?;
        trace_original_progress_phase(original_started, "post-current-returned", None);
        if after != (admission, record) {
            return Err(AgentdError::Protocol(
                "original Initial RunStart changed".into(),
            ));
        }
        trace_original_progress_phase(original_started, "response-return", None);
        observed
    }

    pub(crate) fn read_original_q24_control_task(
        &self,
    ) -> Result<Q24OriginalTaskObservationV1, AgentdError> {
        self.require_original_q24_outcome_current()?;
        let producer: &Arc<crate::OriginalCellQ24TaskLedgerProducerV1> =
            self.original_q24_outcome_control.get().ok_or_else(|| {
                AgentdError::Protocol("original Q24 task observation unavailable".into())
            })?;
        producer.require_original_control_identity(&self.identity)?;
        let observed = producer.read_original_task_observation().map_err(|error| {
            AgentdError::Protocol(format!("original Q24 task observation: {error}"))
        });
        self.require_original_q24_outcome_current()?;
        observed
    }

    pub(crate) fn attach_original_q24_outcome_control(
        &self,
        producer: Arc<crate::OriginalCellQ24TaskLedgerProducerV1>,
    ) -> Result<(), AgentdError> {
        producer.require_original_control_identity(&self.identity)?;
        if self.circuit_task.get().is_none() || self.circuit_task_invocation.get().is_none() {
            return Err(AgentdError::Invalid(
                "original Q24 task owner is absent".into(),
            ));
        }
        self.original_q24_outcome_control
            .set(producer)
            .map_err(|_| AgentdError::Invalid("original Q24 Outcome owner already attached".into()))
    }

    pub(crate) fn submit_original_q24_control_outcome(
        &self,
        request: &Q24OriginalTerminalOutcomeRequestV1,
    ) -> Result<Q24OriginalTerminalOutcomeReceiptV1, AgentdError> {
        self.require_original_q24_outcome_current()?;
        let producer: &Arc<crate::OriginalCellQ24TaskLedgerProducerV1> =
            self.original_q24_outcome_control.get().ok_or_else(|| {
                AgentdError::Protocol("original Q24 Outcome owner unavailable".into())
            })?;
        producer.require_original_control_identity(&self.identity)?;
        // No detached blocking task can outlive this accepted connection.
        // The original producer retains its signature, deadline and witness.
        let receipt = producer.submit_original_control_outcome(request)?;
        self.require_original_q24_outcome_current()?;
        Ok(receipt)
    }

    fn require_original_q24_outcome_current(&self) -> Result<(), AgentdError> {
        self.refresh_generation()?;
        let runtime = self.runtime.lock().map_err(poisoned_state)?;
        // Running is the lifecycle transition after this process was spawned.
        // The startup identity stays fixed while the Fleet generation advances.
        let running_generation = self.identity.spawn_generation.checked_add(1);
        if Some(runtime.current_generation) != running_generation
            || runtime.lifecycle != AgentLifecycle::Running
            || !runtime.app_server_ready
            || !runtime.critical_stores_ready
            || !runtime.revocation_ready
            || !runtime.required_ports_ready
            || !runtime.admission_open
            || runtime.drain_requested
            || runtime.fenced
        {
            return Err(AgentdError::GenerationFenced(
                "original Q24 Outcome admission is no longer current".into(),
            ));
        }
        Ok(())
    }
}

fn trace_original_progress_phase(
    started: std::time::Instant,
    phase: &'static str,
    pending: Option<usize>,
) {
    use std::io::Write;

    let _ = writeln!(
        std::io::stderr().lock(),
        "original Initial progress phase={phase}; elapsed_micros={}; pending={pending:?}",
        started.elapsed().as_micros(),
    );
}
