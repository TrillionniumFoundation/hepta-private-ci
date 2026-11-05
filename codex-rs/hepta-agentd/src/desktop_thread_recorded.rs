//! Read-only navigation through the same protected sender and operation owner.
use super::*;
use crate::text_session::AgentdTextSessionConfig;
use codex_hepta_memory::OriginalDesktopThreadReference;
use codex_hepta_memory::ProductionRetainedOperation;
use codex_hepta_objective::decode_source_envelope_json_v1;
use serde_json::Value;

#[path = "desktop_thread_recovery.rs"]
mod recovery;

pub(crate) struct RecordedDesktopOperation {
    pub(crate) reference: OriginalDesktopThreadReference,
    pub(crate) run_id: String,
    pub(crate) request_sha256: String,
    pub(crate) operation: ProductionRetainedOperation,
}

pub(crate) enum RecordedDesktopLookup {
    Found(RecordedDesktopOperation),
    Unknown(&'static str),
}

pub(super) fn reference_ids(
    reference: &OriginalDesktopThreadReference,
    agent: &str,
) -> Result<(String, String), AgentdError> {
    reference
        .validate_shape()
        .map_err(|error| invalid(&error.to_string()))?;
    let turn = Digest32::of_bytes(&serde_json::to_vec(&(
        "hepta.desktop.original-thread-turn.v1",
        agent,
        &reference.app_server_session_id,
        &reference.thread_id,
        &reference.turn_id,
    ))?)
    .to_string();
    let call = Digest32::of_bytes(&serde_json::to_vec(&(
        "hepta.desktop.original-thread-call.v1",
        agent,
        &reference.app_server_session_id,
        &reference.thread_id,
        &reference.turn_id,
        &reference.call_id,
        &reference.tool,
    ))?)
    .to_string();
    Ok((turn, call))
}

pub(super) fn callback_matches(
    reference: &OriginalDesktopThreadReference,
    arguments: &Value,
) -> Result<bool, AgentdError> {
    reference
        .validate_shape()
        .map_err(|error| invalid(&error.to_string()))?;
    let params = codex_app_server_protocol::DynamicToolCallParams {
        thread_id: reference.thread_id.clone(),
        turn_id: reference.turn_id.clone(),
        call_id: reference.call_id.clone(),
        namespace: None,
        tool: reference.tool.clone(),
        arguments: arguments.clone(),
    };
    Ok(Digest32::of_bytes(&serde_json::to_vec(&params)?).to_string() == reference.callback_sha256)
}

fn payload_callback_matches(
    reference: &OriginalDesktopThreadReference,
    payload: &Value,
) -> Result<bool, AgentdError> {
    let keys: &[&str] = match reference.tool.as_str() {
        "hepta_notes_replace" => &["text", "expected_revision"],
        "hepta_calculator_evaluate" => &["left", "operator", "right", "expected_revision"],
        _ => return Err(invalid("recorded Desktop reference is not an effect tool")),
    };
    // Exact callback maps may preserve insertion order: at most 24 permutations.
    let mut permutations = vec![Vec::new()];
    for index in 0..keys.len() {
        let mut next = Vec::new();
        for order in permutations {
            for position in 0..=order.len() {
                let mut order = order.clone();
                order.insert(position, index);
                next.push(order);
            }
        }
        permutations = next;
    }
    for order in permutations {
        let mut arguments = serde_json::Map::new();
        for index in order {
            let key = keys[index];
            let value = payload
                .get(key)
                .ok_or_else(|| invalid("recorded Desktop arguments absent"))?;
            arguments.insert(key.into(), value.clone());
        }
        if callback_matches(reference, &Value::Object(arguments))? {
            return Ok(true);
        }
    }
    Ok(false)
}

impl AgentdNotesLiteralAdapter {
    /// The protected sender's original turn binding takes precedence over a
    /// possibly incomplete live Core history overlay. This is read-only and
    /// never supplies another send ticket, even for the same callback.
    pub(crate) async fn recorded_desktop_turn_operation(
        &self,
        route: &AgentdTextSessionConfig,
        turn_id: &str,
        end: tokio::time::Instant,
    ) -> Result<RecordedDesktopLookup, AgentdError> {
        let result = tokio::time::timeout_at(end, async {
            self.check_available()?;
            let turn = Digest32::of_bytes(&serde_json::to_vec(&(
                "hepta.desktop.original-thread-turn.v1",
                self.identity.agent_id.as_str(),
                &route.app_server_session_id,
                &route.thread_id,
                turn_id,
            ))?)
            .to_string();
            let Some(request) = self
                .sender
                .retained_request_for_run(&self.run_id(&turn)?)
                .await
                .map_err(|error| invalid(&error.to_string()))?
            else {
                return Ok(RecordedDesktopLookup::Unknown(
                    "original_request_not_observed",
                ));
            };
            let Some(reference) = &request.origin().original_desktop_thread else {
                return Ok(RecordedDesktopLookup::Unknown(
                    "versioned_reference_unavailable",
                ));
            };
            if reference.turn_id != turn_id {
                return Err(invalid(
                    "protected Desktop turn binding differs from requested turn",
                ));
            }
            let tool = reference.tool.clone();
            self.verify_desktop_recorded(route, &tool, request).await
        })
        .await;
        if tokio::time::Instant::now() >= end {
            return Ok(RecordedDesktopLookup::Unknown("deadline_elapsed"));
        }
        result.map_err(|_| invalid("original Desktop turn lookup timed out"))?
    }

    async fn verify_desktop_recorded(
        &self,
        route: &AgentdTextSessionConfig,
        tool: &str,
        request: ObjectiveSenderRequest,
    ) -> Result<RecordedDesktopLookup, AgentdError> {
        if self.profile != NotesAdapterProfile::OriginalDesktop
            || route.agent_id != self.identity.agent_id
            || route.codex_home != self.identity.home_root
        {
            return Err(invalid(
                "Desktop reader differs from the retained original route",
            ));
        }
        let Some(reference) = &request.origin().original_desktop_thread else {
            return Ok(RecordedDesktopLookup::Unknown(
                "versioned_reference_unavailable",
            ));
        };
        let (turn, call) = reference_ids(reference, self.identity.agent_id.as_str())?;
        let run_id = self.run_id(&turn)?;
        let ingress: AuthBusObjectiveIngress = serde_json::from_slice(request.exact_original())?;
        let source = decode_source_envelope_json_v1(ingress.body.source_envelope_json.as_bytes())
            .map_err(|error| invalid(&error.to_string()))?;
        let operation = self
            .writer
            .retained_operation(&run_id)
            .await?
            .ok_or_else(|| invalid("recorded original Desktop operation disappeared"))?;
        let payload: Value = serde_json::from_str(&operation.payload_json)?;
        let subject = codex_hepta_types::StableId::new(self.identity.agent_id.as_str())
            .map_err(|error| invalid(&error.to_string()))?;
        let (topic, exact) = match reference.tool.as_str() {
            "hepta_notes_replace" => {
                let target: codex_hepta_memory::NotesTargetIdentity =
                    serde_json::from_value(payload["target"].clone())?;
                (
                    codex_hepta_memory::NOTES_REPLACE_TOPIC_V1,
                    codex_hepta_memory::notes_operation_intent(
                        &target,
                        &operation.payload_json,
                        subject,
                        operation.operation.policy_generation(),
                    )
                    .map_err(AgentdError::Invalid)?,
                )
            }
            "hepta_calculator_evaluate" => {
                let target: codex_hepta_memory::CalculatorTargetIdentity =
                    serde_json::from_value(payload["target"].clone())?;
                (
                    codex_hepta_memory::CALCULATOR_EVALUATE_TOPIC_V1,
                    codex_hepta_memory::calculator_operation_intent(
                        &target,
                        &operation.payload_json,
                        subject,
                        operation.operation.policy_generation(),
                    )
                    .map_err(AgentdError::Invalid)?,
                )
            }
            _ => {
                return Err(invalid(
                    "recorded Desktop operation has another tool profile",
                ));
            }
        };
        if reference.tool != tool
            || reference.thread_id != route.thread_id
            || reference.app_server_session_id != route.app_server_session_id
            || request.origin().original_notes_thread.is_some()
            || request.origin().agent_id != self.identity.agent_id
            || request.origin().spawn_generation > self.identity.spawn_generation
            || ingress.issuer_id != self.bindings.issuer_id
            || ingress.body.model_tuple_digest != self.bindings.model_tuple_digest.to_string()
            || ingress.body.runtime_body_digest != self.bindings.runtime_body_digest.to_string()
            || ingress.body.preference_state_digest
                != self.bindings.preference_state_digest.to_string()
            || ingress.body.prompt_registry_digest
                != self.bindings.prompt_registry_digest.to_string()
            || ingress.body.artifact_set_digest != self.bindings.artifact_set_digest.to_string()
            || source.input_schema_digest != self.input_schema_digest
            || source
                .structured_intent
                .provenance
                .normalization_profile_digest
                != self.normalization_digest
            || source.principal_scope_digest != self.bindings.principal_scope_digest
            || source.request_id != call
            || request.identity().run_id != run_id
            || operation.topic != topic
            || operation.operation.policy_generation() != self.bindings.policy_generation
            || exact != operation.operation
            || payload["operation_id"] != run_id
            || source.structured_intent.provenance.source_digest
                != operation.operation.semantic_digest()
            || !payload_callback_matches(reference, &payload)?
        {
            return Err(invalid(
                "Desktop reference differs from the exact retained signed operation",
            ));
        }
        Ok(RecordedDesktopLookup::Found(RecordedDesktopOperation {
            reference: reference.clone(),
            run_id,
            request_sha256: request.identity().original_sha256.as_str().to_owned(),
            operation,
        }))
    }

    pub(crate) async fn recorded_desktop_operation(
        &self,
        route: &AgentdTextSessionConfig,
        tool: &str,
        turn_id: &str,
        call_id: &str,
        end: tokio::time::Instant,
    ) -> Result<RecordedDesktopLookup, AgentdError> {
        let result = tokio::time::timeout_at(end, async {
            self.check_available()?;
            let turn = Digest32::of_bytes(&serde_json::to_vec(&(
                "hepta.desktop.original-thread-turn.v1",
                self.identity.agent_id.as_str(),
                &route.app_server_session_id,
                &route.thread_id,
                turn_id,
            ))?)
            .to_string();
            let run_id = self.run_id(&turn)?;
            let Some(request) = self
                .sender
                .retained_request_for_run(&run_id)
                .await
                .map_err(|error| invalid(&error.to_string()))?
            else {
                return Ok(RecordedDesktopLookup::Unknown(
                    "original_request_not_observed",
                ));
            };
            let result = self.verify_desktop_recorded(route, tool, request).await?;
            if let RecordedDesktopLookup::Found(found) = &result
                && (found.reference.turn_id != turn_id || found.reference.call_id != call_id)
            {
                return Err(invalid(
                    "exact Desktop reference names another original call",
                ));
            }
            Ok(result)
        })
        .await;
        if tokio::time::Instant::now() >= end {
            return Ok(RecordedDesktopLookup::Unknown("deadline_elapsed"));
        }
        result.map_err(|_| invalid("original Desktop lookup timed out"))?
    }

    pub(crate) async fn latest_recorded_desktop_operation(
        &self,
        route: &AgentdTextSessionConfig,
        tool: &str,
        end: tokio::time::Instant,
    ) -> Result<RecordedDesktopLookup, AgentdError> {
        let result = tokio::time::timeout_at(end, async {
            self.check_available()?;
            let requests = self
                .sender
                .retained_owner_requests()
                .await
                .map_err(|error| invalid(&error.to_string()))?;
            let mut latest = None;
            let mut orders = std::collections::BTreeSet::new();
            for request in requests {
                if tokio::time::Instant::now() >= end {
                    return Ok(RecordedDesktopLookup::Unknown("deadline_elapsed"));
                }
                let ingress: AuthBusObjectiveIngress =
                    serde_json::from_slice(request.exact_original())?;
                let source =
                    decode_source_envelope_json_v1(ingress.body.source_envelope_json.as_bytes())
                        .map_err(|error| invalid(&error.to_string()))?;
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
                if request.origin().agent_id != self.identity.agent_id
                    || request.origin().spawn_generation > self.identity.spawn_generation
                {
                    return Err(invalid(
                        "recorded Desktop cut has a different owner/generation",
                    ));
                }
                let Some(reference) = &request.origin().original_desktop_thread else {
                    return Ok(RecordedDesktopLookup::Unknown(
                        "versioned_reference_unavailable",
                    ));
                };
                reference
                    .validate_shape()
                    .map_err(|error| invalid(&error.to_string()))?;
                if reference.thread_id != route.thread_id
                    || reference.app_server_session_id != route.app_server_session_id
                    || reference.tool != tool
                {
                    continue;
                }
                let order = (
                    request.origin().spawn_generation,
                    request.origin().request_id,
                );
                if !orders.insert(order) {
                    return Ok(RecordedDesktopLookup::Unknown("ambiguous_original_order"));
                }
                if latest
                    .as_ref()
                    .is_none_or(|(previous, _)| order > *previous)
                {
                    latest = Some((order, request));
                }
            }
            let Some((_, request)) = latest else {
                return Ok(RecordedDesktopLookup::Unknown(
                    "original_request_not_observed",
                ));
            };
            self.verify_desktop_recorded(route, tool, request).await
        })
        .await;
        if tokio::time::Instant::now() >= end {
            return Ok(RecordedDesktopLookup::Unknown("deadline_elapsed"));
        }
        result.map_err(|_| invalid("original Desktop retained cut timed out"))?
    }
}
