//! Read-only proof from the existing protected sender cut, never a Core item.
use codex_hepta_memory::OriginalNotesThreadReference;
use codex_hepta_memory::ProductionRetainedOperation;
use codex_hepta_objective::decode_source_envelope_json_v1;

use super::*;

pub(crate) struct RecordedNotesThreadOperation {
    reference: OriginalNotesThreadReference,
    turn_intent_id: String,
    call_intent_id: String,
    run_id: String,
    target: codex_hepta_memory::NotesTargetIdentity,
    state: codex_hepta_memory::LocalOutcomeState,
}

impl RecordedNotesThreadOperation {
    pub(crate) fn reference(&self) -> &OriginalNotesThreadReference {
        &self.reference
    }
    pub(crate) fn turn_intent_id(&self) -> &str {
        &self.turn_intent_id
    }
    pub(crate) fn call_intent_id(&self) -> &str {
        &self.call_intent_id
    }
    pub(crate) fn run_id(&self) -> &str {
        &self.run_id
    }
}

#[derive(Clone, Copy, PartialEq, Eq, serde::Serialize)]
#[serde(rename_all = "snake_case")]
pub(crate) enum RecordedNotesUnknownReason {
    OriginalRequestNotObserved,
    LegacyReferenceUnavailable,
    DeadlineElapsed,
    AmbiguousOriginalOrder,
}

pub(crate) enum RecordedNotesLookup {
    Found(RecordedNotesThreadOperation),
    Unknown {
        reason: RecordedNotesUnknownReason,
        operation_id: Option<String>,
    },
}

pub(super) fn reference_ids(
    reference: &OriginalNotesThreadReference,
    agent_id: &str,
) -> Result<(String, String), AgentdError> {
    reference
        .validate_shape()
        .map_err(|error| invalid(&error.to_string()))?;
    let turn = Digest32::of_bytes(&serde_json::to_vec(&(
        "hepta.notes.original-thread-turn.v1",
        agent_id,
        &reference.app_server_session_id,
        &reference.thread_id,
        &reference.turn_id,
    ))?)
    .to_string();
    let call = Digest32::of_bytes(&serde_json::to_vec(&(
        "hepta.notes.original-thread-call.v1",
        agent_id,
        &reference.app_server_session_id,
        &reference.thread_id,
        &reference.turn_id,
        &reference.call_id,
    ))?)
    .to_string();
    Ok((turn, call))
}

pub(super) fn callback_matches(
    reference: &OriginalNotesThreadReference,
    text: &str,
    revision: u64,
) -> Result<bool, AgentdError> {
    // Parsed callback arguments have exactly these two fields. Accommodate both
    // insertion orders when serde_json's preserve_order feature is selected.
    for reverse in [false, true] {
        let mut arguments = serde_json::Map::new();
        let text = ("text".into(), serde_json::json!(text));
        let revision = ("expected_revision".into(), serde_json::json!(revision));
        for (key, value) in if reverse {
            [revision, text]
        } else {
            [text, revision]
        } {
            arguments.insert(key, value);
        }
        let params = codex_app_server_protocol::DynamicToolCallParams {
            thread_id: reference.thread_id.clone(),
            turn_id: reference.turn_id.clone(),
            call_id: reference.call_id.clone(),
            namespace: None,
            tool: "hepta_notes_replace".into(),
            arguments: serde_json::Value::Object(arguments),
        };
        if Digest32::of_bytes(&serde_json::to_vec(&params)?).to_string()
            == reference.callback_sha256
        {
            return Ok(true);
        }
    }
    Ok(false)
}

impl AgentdNotesLiteralAdapter {
    pub(crate) async fn recorded_thread_operation(
        &self,
        route: &crate::text_session::AgentdTextSessionConfig,
        turn_id: &str,
        call_id: &str,
    ) -> Result<RecordedNotesLookup, AgentdError> {
        self.check_available()?;
        let intent = Digest32::of_bytes(&serde_json::to_vec(&(
            "hepta.notes.original-thread-turn.v1",
            self.identity.agent_id.as_str(),
            &route.app_server_session_id,
            &route.thread_id,
            turn_id,
        ))?)
        .to_string();
        let run_id = self.run_id(&intent)?;
        let Some(request) = self
            .sender
            .retained_request_for_run(&run_id)
            .await
            .map_err(|error| invalid(&error.to_string()))?
        else {
            return Ok(RecordedNotesLookup::Unknown {
                reason: RecordedNotesUnknownReason::OriginalRequestNotObserved,
                operation_id: None,
            });
        };
        let operation = self
            .writer
            .retained_operation(&run_id)
            .await?
            .ok_or_else(|| invalid("recorded original operation disappeared"))?;
        let result = self.verify_recorded_thread_operation(route, &request, &operation)?;
        if let RecordedNotesLookup::Found(found) = &result
            && (found.reference.turn_id != turn_id || found.reference.call_id != call_id)
        {
            return Err(invalid(
                "exact recorded Notes reference names another original call",
            ));
        }
        Ok(result)
    }

    pub(crate) async fn latest_recorded_thread_operation(
        &self,
        route: &crate::text_session::AgentdTextSessionConfig,
    ) -> Result<RecordedNotesLookup, AgentdError> {
        let end = tokio::time::Instant::now() + Duration::from_secs(5);
        match tokio::time::timeout_at(end, async {
            self.check_available()?;
            let requests = self
                .sender
                .retained_owner_requests()
                .await
                .map_err(|error| invalid(&error.to_string()))?;
            let scope = RecordedScope {
                agent_id: &self.identity.agent_id,
                spawn_generation: self.identity.spawn_generation,
                bindings: &self.bindings,
                input_schema_digest: self.input_schema_digest,
                normalization_digest: self.normalization_digest,
            };
            let request = match latest_matching_request(scope, requests, end)? {
                RecordedChoice::Found(request) => request,
                RecordedChoice::Unknown(reason) => {
                    return Ok(RecordedNotesLookup::Unknown {
                        reason,
                        operation_id: None,
                    });
                }
            };
            let operation = self
                .writer
                .retained_operation(&request.identity().run_id)
                .await?
                .ok_or_else(|| invalid("recorded Notes operation disappeared"))?;
            let result = self.verify_recorded_thread_operation(route, &request, &operation)?;
            if tokio::time::Instant::now() >= end {
                return Ok(RecordedNotesLookup::Unknown {
                    reason: RecordedNotesUnknownReason::DeadlineElapsed,
                    operation_id: None,
                });
            }
            Ok(result)
        })
        .await
        {
            Ok(result) => result,
            Err(_) => Ok(RecordedNotesLookup::Unknown {
                reason: RecordedNotesUnknownReason::DeadlineElapsed,
                operation_id: None,
            }),
        }
    }

    fn verify_recorded_thread_operation(
        &self,
        route: &crate::text_session::AgentdTextSessionConfig,
        request: &ObjectiveSenderRequest,
        operation: &ProductionRetainedOperation,
    ) -> Result<RecordedNotesLookup, AgentdError> {
        if self.profile != NotesAdapterProfile::OriginalThread
            || route.agent_id != self.identity.agent_id
            || route.codex_home != self.identity.home_root
        {
            return Err(invalid("recorded Notes reader differs from original route"));
        }
        verify_recorded(
            RecordedScope {
                agent_id: &self.identity.agent_id,
                spawn_generation: self.identity.spawn_generation,
                bindings: &self.bindings,
                input_schema_digest: self.input_schema_digest,
                normalization_digest: self.normalization_digest,
            },
            route,
            request,
            operation,
        )
    }

    pub(crate) async fn latest_recorded_recovery_operation(
        &self,
        route: &crate::text_session::AgentdTextSessionConfig,
        previous_target: &codex_hepta_memory::NotesTargetIdentity,
    ) -> Result<String, AgentdError> {
        match self.latest_recorded_thread_operation(route).await? {
            RecordedNotesLookup::Found(original)
                if original.target == *previous_target
                    && matches!(
                        original.state,
                        codex_hepta_memory::LocalOutcomeState::Indeterminate
                            | codex_hepta_memory::LocalOutcomeState::Committed
                    ) =>
            {
                Ok(original.run_id)
            }
            _ => Err(invalid(
                "latest recorded Notes recovery has no exact executed original target; unknown, do not replay",
            )),
        }
    }
}

#[derive(Clone, Copy)]
struct RecordedScope<'a> {
    agent_id: &'a codex_hepta_contracts::AgentId,
    spawn_generation: u64,
    bindings: &'a AgentdNotesLiteralBindings,
    input_schema_digest: Digest32,
    normalization_digest: Digest32,
}

enum RecordedChoice {
    Found(ObjectiveSenderRequest),
    Unknown(RecordedNotesUnknownReason),
}
fn latest_matching_request(
    scope: RecordedScope<'_>,
    requests: Vec<ObjectiveSenderRequest>,
    end: tokio::time::Instant,
) -> Result<RecordedChoice, AgentdError> {
    let mut latest = None;
    let mut orders = std::collections::BTreeSet::new();
    for request in requests {
        if tokio::time::Instant::now() >= end {
            return Ok(RecordedChoice::Unknown(
                RecordedNotesUnknownReason::DeadlineElapsed,
            ));
        }
        let identity = request.identity();
        let ingress: AuthBusObjectiveIngress = serde_json::from_slice(request.exact_original())?;
        let Ok(source) =
            decode_source_envelope_json_v1(ingress.body.source_envelope_json.as_bytes())
        else {
            continue;
        };
        if source.input_schema_digest != scope.input_schema_digest
            || source
                .structured_intent
                .provenance
                .normalization_profile_digest
                != scope.normalization_digest
            || source.principal_scope_digest != scope.bindings.principal_scope_digest
            || identity.model_tuple_digest != scope.bindings.model_tuple_digest.to_string()
        {
            continue;
        }
        if &request.origin().agent_id != scope.agent_id
            || request.origin().spawn_generation > scope.spawn_generation
        {
            return Err(invalid("recorded Notes owner/generation differs"));
        }
        let order = (
            request.origin().spawn_generation,
            request.origin().request_id,
        );
        if !orders.insert(order) {
            return Ok(RecordedChoice::Unknown(
                RecordedNotesUnknownReason::AmbiguousOriginalOrder,
            ));
        }
        if latest
            .as_ref()
            .is_none_or(|(previous, _)| order > *previous)
        {
            latest = Some((order, request));
        }
    }
    if tokio::time::Instant::now() >= end {
        return Ok(RecordedChoice::Unknown(
            RecordedNotesUnknownReason::DeadlineElapsed,
        ));
    }
    Ok(match latest {
        Some((_, request)) => RecordedChoice::Found(request),
        None => RecordedChoice::Unknown(RecordedNotesUnknownReason::OriginalRequestNotObserved),
    })
}

fn verify_recorded(
    scope: RecordedScope<'_>,
    route: &crate::text_session::AgentdTextSessionConfig,
    request: &ObjectiveSenderRequest,
    operation: &ProductionRetainedOperation,
) -> Result<RecordedNotesLookup, AgentdError> {
    let Some(reference) = &request.origin().original_notes_thread else {
        return Ok(RecordedNotesLookup::Unknown {
            reason: RecordedNotesUnknownReason::LegacyReferenceUnavailable,
            operation_id: Some(request.identity().run_id.clone()),
        });
    };
    let ingress: AuthBusObjectiveIngress = serde_json::from_slice(request.exact_original())?;
    let source = decode_source_envelope_json_v1(ingress.body.source_envelope_json.as_bytes())
        .map_err(|error| invalid(&error.to_string()))?;
    let (turn_intent_id, call_intent_id) = reference_ids(reference, scope.agent_id.as_str())?;
    let run_id = format!(
        "notes.thread.{}",
        Digest32::of_bytes(&serde_json::to_vec(&(
            "organ.notes.original-turn.run.v1",
            scope.agent_id.as_str(),
            scope.bindings.principal_scope_digest.to_string(),
            &turn_intent_id
        ))?)
    );
    let payload: serde_json::Value = serde_json::from_str(&operation.payload_json)?;
    let target: codex_hepta_memory::NotesTargetIdentity =
        serde_json::from_value(payload["target"].clone())?;
    let exact_operation = codex_hepta_memory::notes_operation_intent(
        &target,
        &operation.payload_json,
        codex_hepta_types::StableId::new(scope.agent_id.as_str())
            .map_err(|error| invalid(&error.to_string()))?,
        operation.operation.policy_generation(),
    )
    .map_err(|error| invalid(&error))?;
    if reference.thread_id != route.thread_id
        || reference.app_server_session_id != route.app_server_session_id
        || &request.origin().agent_id != scope.agent_id
        || request.origin().spawn_generation > scope.spawn_generation
        || ingress.issuer_id != scope.bindings.issuer_id
        || ingress.body.model_tuple_digest != scope.bindings.model_tuple_digest.to_string()
        || ingress.body.runtime_body_digest != scope.bindings.runtime_body_digest.to_string()
        || ingress.body.preference_state_digest
            != scope.bindings.preference_state_digest.to_string()
        || ingress.body.prompt_registry_digest != scope.bindings.prompt_registry_digest.to_string()
        || ingress.body.artifact_set_digest != scope.bindings.artifact_set_digest.to_string()
        || source.input_schema_digest != scope.input_schema_digest
        || source
            .structured_intent
            .provenance
            .normalization_profile_digest
            != scope.normalization_digest
        || source.principal_scope_digest != scope.bindings.principal_scope_digest
        || source.request_id != call_intent_id
        || request.identity().run_id != run_id
        || operation.topic != codex_hepta_memory::NOTES_REPLACE_TOPIC_V1
        || operation.operation.policy_generation() != scope.bindings.policy_generation
        || exact_operation != operation.operation
        || payload["operation_id"] != run_id
        || source.structured_intent.provenance.source_digest
            != operation.operation.semantic_digest()
        || !callback_matches(
            reference,
            payload["text"]
                .as_str()
                .ok_or_else(|| invalid("recorded Notes text missing"))?,
            payload["expected_revision"]
                .as_u64()
                .ok_or_else(|| invalid("recorded Notes revision missing"))?,
        )?
    {
        return Err(invalid(
            "recorded Notes reference differs from its original signed operation",
        ));
    }
    Ok(RecordedNotesLookup::Found(RecordedNotesThreadOperation {
        reference: reference.clone(),
        turn_intent_id,
        call_intent_id,
        run_id,
        target,
        state: operation.state,
    }))
}

#[cfg(test)]
#[path = "notes_thread_recorded_tests.rs"]
mod tests;
