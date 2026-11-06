//! Retain original protocol replies once per complete observed state. Repeated
//! status reads still authenticate the peer and re-acknowledge the live owner.

use super::*;
use codex_hepta_memory::ObjectiveSenderObservationAction;

impl<C: ObjectiveSenderCheckpoint> AgentdObjectiveClient<C> {
    pub(super) async fn retain_current_response(
        &self,
        ticket: &ObjectiveSenderTicket,
        response: &AgentdResponse,
        raw: String,
        expected_publication: Option<&crate::ObjectiveAdmissionPublication>,
    ) -> Result<(), AgentdObjectiveClientError> {
        let observation =
            ObjectiveSenderObservation::from_original(ObjectiveSenderObservationKind::History, raw)
                .map_err(ObjectiveSenderError::from)?;
        self.sender
            .retain_distinct_observation(ticket, &observation, |current| {
                if let Some(before) = publication(current, &self.original)?
                    && expected_publication != Some(&before)
                {
                    return Err(ObjectiveSenderError::ObservationConflict);
                }
                for observed in &current.observations {
                    if observed.kind() != ObjectiveSenderObservationKind::History {
                        continue;
                    }
                    let AgentdResponse {
                        schema_version,
                        request_id: _,
                        agent_id,
                        spawn_generation,
                        current_generation,
                        payload,
                    } = serde_json::from_slice(observed.exact_original())
                        .map_err(|_| ObjectiveSenderError::ObservationConflict)?;
                    // Only the request correlation ID is excluded. The exhaustive
                    // destructure forces new protocol fields to be reviewed too.
                    // Original response bytes are never rewritten or discarded.
                    if schema_version == response.schema_version
                        && agent_id == response.agent_id
                        && spawn_generation == response.spawn_generation
                        && current_generation == response.current_generation
                        && payload == response.payload
                    {
                        return Ok(ObjectiveSenderObservationAction::Reacknowledge);
                    }
                }
                Ok(ObjectiveSenderObservationAction::Append)
            })
            .await?;
        Ok(())
    }
}
