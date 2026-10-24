//! Read and acknowledge existing observations, then query only the exact
//! retained signed ingress. Recovery cannot recreate a sending permission.

use super::*;
use codex_hepta_agent_protocol::ObjectiveAdmissionOutcome;
use codex_hepta_agent_protocol::ObjectiveAdmissionQuery;
use codex_hepta_memory::ObjectiveSenderError;
use codex_hepta_memory::ObjectiveSenderObservation;
use codex_hepta_memory::ObjectiveSenderObservationKind;
use crate::AgentdMethod;
use crate::AgentdPayload;
use crate::AgentdRequest;
use crate::notes_literal_receipts as receipts;
use crate::notes_ui_wire::*;

impl AgentdNotesLiteralAdapter {
    pub(crate) async fn retained_view(&mut self, client_intent_id: &str) -> Result<ObjectiveObservation, AgentdError> {
        tokio::time::timeout(self.deadline, self.retained_view_until(client_intent_id)).await
            .map_err(|_| invalid("Notes retained observation acknowledgement unknown"))?
    }

    async fn retained_view_until(&mut self, client_intent_id: &str) -> Result<ObjectiveObservation, AgentdError> {
        self.check_available()?;
        let run_id = self.run_id(client_intent_id)?;
        let mut view = ObjectiveObservation::new(Some(client_intent_id.into()), ObjectiveStage::Unavailable);
        let Some(request) = self.sender.retained_request_for_run(&run_id).await
            .map_err(|error| invalid(&error.to_string()))? else {
                view.issue = Some(ObjectiveHostIssue::NoRetainedIntent);
                return Ok(view);
            };
        let ticket = self.sender.recover_pending(request.clone()).await
            .map_err(|error| invalid(&error.to_string()))?;
        let snapshot = self.sender.snapshot_acknowledged(&ticket).await
            .map_err(|error| invalid(&error.to_string()))?;
        let projected = receipts::project(&request, &snapshot)
            .map_err(|_| invalid("original Notes retained metadata identity mismatch"))?;
        view.request_retained = true;
        view.stage = projected.stage;
        view.publication_retained = projected.known.is_some();
        // Existing positive evidence is immutable and already independently
        // acknowledged. Unknown queries cannot erase or replace it.
        if view.publication_retained || snapshot.locally_cancelled { return Ok(view); }
        let origin = self.next_origin()?;
        let ingress: AuthBusObjectiveIngress = serde_json::from_slice(request.exact_original())?;
        let query = AgentdRequest {
            schema_version: crate::AGENTD_CONTROL_SCHEMA_VERSION, request_id: origin.request_id,
            spawn_generation: origin.spawn_generation,
            method: AgentdMethod::ObjectiveAdmission { query: ObjectiveAdmissionQuery { request: ingress, anchor: None } },
        };
        let mut frame = serde_json::to_vec(&query)?;
        frame.push(b'\n');
        let mut written = 0;
        let response = match crate::notes_literal_control::exchange(&origin, &frame, &mut written).await {
            Ok(response) => response,
            Err(_) => { view.issue = Some(ObjectiveHostIssue::TransportUnknown); return Ok(view); }
        };
        let AgentdPayload::ObjectiveAdmission { outcome } = response.payload else {
            view.issue = Some(ObjectiveHostIssue::TransportUnknown); return Ok(view);
        };
        let ObjectiveAdmissionOutcome::Published { publication } = outcome else {
            // Absence is unknown and supplies neither a retry nor a no-effect
            // receipt. Do not fill the bounded original journal by polling it.
            return Ok(view);
        };
        let known = receipts::publication(&request, &publication)
            .map_err(|_| invalid("original Notes history publication identity mismatch"))?;
        let record = receipts::History {
            schema: 1, original_sha256: request.identity().original_sha256.to_string(),
            query: receipts::identity(&request, &origin), requested_anchor: None,
            bytes_written: written, request_frame_bytes: Some(frame.len()),
            status: receipts::HistoryStatus::HistoricalPublication { publication, response_generation: response.current_generation },
        };
        let observation = ObjectiveSenderObservation::from_original(ObjectiveSenderObservationKind::History, serde_json::to_string(&record)?)
            .map_err(|error| invalid(&error.to_string()))?;
        self.sender.retain_observation_checked(&ticket, &observation, |current| {
            let previous = receipts::project(&request, current).map_err(|_| ObjectiveSenderError::ObservationConflict)?;
            if previous.known.as_ref().is_some_and(|previous| *previous != known) {
                return Err(ObjectiveSenderError::ObservationConflict);
            }
            // Re-parse the combined immutable metadata under the original
            // transaction, including first publication sequence/chain identity.
            let mut combined = codex_hepta_memory::ObjectiveSenderSnapshot {
                observations: current.observations.clone(), locally_cancelled: current.locally_cancelled,
            };
            combined.observations.push(observation.clone());
            receipts::project(&request, &combined).map_err(|_| ObjectiveSenderError::ObservationConflict)?;
            Ok(())
        }).await.map_err(|error| invalid(&error.to_string()))?;
        self.check_available()?;
        view.stage = known.stage();
        view.publication_retained = true;
        Ok(view)
    }
}
