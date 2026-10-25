//! Read/cancel through the original authenticated control and retained sender.
//! None of these methods compiles, signs, prepares or resends an Objective.

use super::*;
use crate::AgentRunCancellation;
use crate::AgentRunReceipt;
use crate::AgentdMethod;
use crate::AgentdPayload;
use crate::AgentdRequest;
use crate::AgentdResponse;
use codex_hepta_memory::ObjectiveSenderRetainedPosition;
use codex_hepta_objective::decode_source_envelope_json_v1;

/// Bounded live navigation over the original owner, not a history database.
pub struct AgentdNotesRetainedIntents {
    pub client_intent_ids: Vec<String>,
    pub complete: bool,
}

impl AgentdNotesLiteralAdapter {
    pub(super) fn next_origin(&mut self) -> Result<ObjectiveSenderOrigin, AgentdError> {
        let request_id = self.next_request;
        self.next_request = request_id
            .checked_add(1)
            .ok_or_else(|| invalid("Notes control request counter exhausted"))?;
        // SAFETY: geteuid takes no pointers and only reads this process's UID.
        let expected_peer_uid = unsafe { libc::geteuid() };
        Ok(ObjectiveSenderOrigin {
            agent_id: self.identity.agent_id.clone(),
            spawn_generation: self.identity.spawn_generation,
            request_id,
            expected_peer_uid,
            expected_peer_pid: std::process::id(),
            endpoint_identity: self
                .identity
                .control_socket
                .to_str()
                .ok_or_else(|| invalid("original control path is not UTF-8"))?
                .into(),
        })
    }

    pub(super) async fn query(
        &mut self,
        method: AgentdMethod,
    ) -> Result<AgentdResponse, AgentdError> {
        let origin = self.next_origin()?;
        let request = AgentdRequest {
            schema_version: crate::AGENTD_CONTROL_SCHEMA_VERSION,
            request_id: origin.request_id,
            spawn_generation: origin.spawn_generation,
            method,
        };
        let mut frame = serde_json::to_vec(&request)?;
        frame.push(b'\n');
        let mut written = 0;
        tokio::time::timeout(
            self.deadline,
            crate::notes_literal_control::exchange(&origin, &frame, &mut written),
        )
        .await
        .map_err(|_| invalid("original control query deadline elapsed"))?
        .map_err(invalid)
    }

    /// A real owner capability check precedes any new operation preparation.
    /// A startup gap stays unavailable and creates no original send fence.
    pub async fn require_objective_ready(&mut self) -> Result<(), AgentdError> {
        self.check_available()?;
        let response = self.query(AgentdMethod::Capabilities).await?;
        let AgentdPayload::Capabilities(capabilities) = response.payload else {
            return Err(invalid("original Objective capability unavailable"));
        };
        capabilities.validate().map_err(AgentdError::Protocol)?;
        if !capabilities
            .capabilities
            .iter()
            .any(|capability| capability.id == "objective.start" && capability.major == 1)
        {
            return Err(invalid("original Objective start v1 unavailable"));
        }
        self.check_available()
    }

    pub async fn observe_run(
        &mut self,
        client_intent_id: &str,
    ) -> Result<Option<AgentRunReceipt>, AgentdError> {
        let run_id = self.run_id(client_intent_id)?;
        if self
            .sender
            .retained_request_for_run(&run_id)
            .await
            .map_err(|error| invalid(&error.to_string()))?
            .is_none()
        {
            return Err(invalid("Notes intent has no retained original request"));
        }
        let response = self
            .query(AgentdMethod::RunStatus {
                run_id: run_id.clone(),
            })
            .await?;
        let AgentdPayload::RunStatus { run } = response.payload else {
            return Err(invalid("original Notes RunStatus unavailable"));
        };
        if run.as_ref().is_some_and(|run| {
            run.run_id != run_id
                || run.generation < self.identity.spawn_generation
                || run.generation > response.current_generation
        }) {
            return Err(invalid("original Notes RunStatus identity mismatch"));
        }
        Ok(run)
    }

    /// Only the original RunCancel consumes a freshly read revision. A race or
    /// lost reply is unknown; this function does not retry or undo an effect.
    pub async fn cancel(
        &mut self,
        client_intent_id: &str,
    ) -> Result<AgentRunCancellation, AgentdError> {
        let run = self
            .observe_run(client_intent_id)
            .await?
            .ok_or_else(|| invalid("missing run is not evidence of non-admission"))?;
        let response = self
            .query(AgentdMethod::RunCancel {
                run_id: run.run_id.clone(),
                expected_revision: run.revision,
                reason: "user_requested".into(),
            })
            .await?;
        let AgentdPayload::RunCancellation(cancel) = response.payload else {
            return Err(invalid("original Notes cancellation unknown"));
        };
        if cancel.receipt.run_id != run.run_id
            || cancel.receipt.revision < run.revision
            || cancel.receipt.generation < self.identity.spawn_generation
            || cancel.receipt.generation > response.current_generation
        {
            return Err(invalid("original Notes cancellation identity mismatch"));
        }
        Ok(cancel)
    }

    pub async fn retained_intents(&self) -> Result<AgentdNotesRetainedIntents, AgentdError> {
        tokio::time::timeout(self.deadline, async {
            let mut ids = std::collections::BTreeSet::new();
            let mut position = ObjectiveSenderRetainedPosition::Beginning;
            for _ in 0..64 {
                let page = self
                    .sender
                    .retained_page(position)
                    .await
                    .map_err(|error| invalid(&error.to_string()))?;
                for request in page.requests {
                    if request.origin().agent_id != self.identity.agent_id
                        || request.origin().spawn_generation > self.identity.spawn_generation
                    {
                        return Err(invalid("Notes retained owner/generation mismatch"));
                    }
                    let ingress: AuthBusObjectiveIngress =
                        serde_json::from_slice(request.exact_original())?;
                    let Ok(source) = decode_source_envelope_json_v1(
                        ingress.body.source_envelope_json.as_bytes(),
                    ) else {
                        continue;
                    };
                    if source.input_schema_digest != self.input_schema_digest
                        || source
                            .structured_intent
                            .provenance
                            .normalization_profile_digest
                            != self.normalization_digest
                        || source.principal_scope_digest != self.bindings.principal_scope_digest
                    {
                        continue;
                    }
                    if self.run_id(&source.request_id)? != request.identity().run_id
                        || ids.contains(&source.request_id)
                    {
                        return Err(invalid("Notes retained navigation identity mismatch"));
                    }
                    if ids.len() == 128 {
                        return Ok(AgentdNotesRetainedIntents {
                            client_intent_ids: ids.into_iter().collect(),
                            complete: false,
                        });
                    }
                    ids.insert(source.request_id);
                }
                match page.next {
                    Some(cursor) => position = ObjectiveSenderRetainedPosition::After(cursor),
                    None => {
                        return Ok(AgentdNotesRetainedIntents {
                            client_intent_ids: ids.into_iter().collect(),
                            complete: true,
                        });
                    }
                }
            }
            Ok(AgentdNotesRetainedIntents {
                client_intent_ids: ids.into_iter().collect(),
                complete: false,
            })
        })
        .await
        .map_err(|_| invalid("Notes retained navigation deadline elapsed"))?
    }
}
