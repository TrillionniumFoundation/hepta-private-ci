//! Reconcile exact retained App Server turns without another provider dispatch.

use codex_app_server_client::RemoteAppServerClient;
use codex_app_server_client::RemoteAppServerConnectArgs;
use codex_app_server_client::RemoteAppServerEndpoint;
use codex_app_server_client::RemoteAppServerObservedResponse;
use codex_app_server_protocol::ClientRequest;
use codex_app_server_protocol::RequestId;
use codex_app_server_protocol::ThreadItem;
use codex_app_server_protocol::ThreadReadParams;
use codex_app_server_protocol::ThreadReadResponse;
use codex_app_server_protocol::UserInput;
use codex_hepta_agentd::AgentdClient;
use codex_hepta_codex_adapter::APP_SERVER_V2_PROTOCOL_ID;
use codex_hepta_codex_adapter::AdapterStatus;
use codex_hepta_codex_adapter::AppServerRequestBinding;
use codex_hepta_codex_adapter::CodexOperationIntent;
use codex_hepta_codex_adapter::TURN_START_METHOD_ID;
use codex_hepta_codex_adapter::adapt_observed_thread_read_reconciliation;
use codex_hepta_codex_adapter::request_digest as codex_request_digest;
use codex_hepta_infer_core::durable_control::native::NativeRunRecord;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use codex_utils_absolute_path::AbsolutePathBuf;
use tokio::time::Instant;
use tokio::time::timeout;

use super::AppServerModelDriver;
use super::MAX_OUTPUT_BYTES;
use super::NativeBoundaryStatus;
use super::NativeOwnerAuthority;
use super::NativeRunOutput;
use super::NativeRunStatus;
use super::RPC_TIMEOUT;
use super::Result;
use super::downgrade_for_owner_loss;
use super::verify_owner_health;

impl AppServerModelDriver {
    /// Reconcile a previously prepared/dispatched operation without issuing a
    /// new turn/start. Only an opaque thread/read response from the current
    /// exact-generation Agent/App Server may settle the durable record.
    pub(super) async fn reconcile_existing(
        &self,
        record: &NativeRunRecord,
        expected_prompt: &str,
    ) -> Result<Option<NativeRunOutput>> {
        if record.request.principal_id != self.config.agent_id.to_string()
            || record.request.worker_generation != self.config.generation
            || record.request.model != self.config.model
        {
            return Err("durable native request no longer matches configured Agent/model".into());
        }
        let Some(dispatch) = record.dispatch.as_ref() else {
            return Ok(None);
        };
        let (
            Some(payload_digest),
            Some(expected_request_digest),
            Some(app_server_version),
            Some(protocol_id),
            Some(source_admission_digest),
            Some(codex_home_digest),
            Some(original_connection_id),
            Some(session_id),
            Some(deadline_ms),
            Some(_authority_witness),
        ) = (
            dispatch.codex_payload_digest.as_deref(),
            dispatch.codex_request_digest.as_deref(),
            dispatch.app_server_version.as_deref(),
            dispatch.protocol_id.as_deref(),
            dispatch.codex_source_admission_digest.as_deref(),
            dispatch.codex_home_digest.as_deref(),
            dispatch.codex_connection_id,
            dispatch.codex_session_id.as_deref(),
            dispatch.codex_deadline_ms,
            dispatch.codex_authority_witness_sha256.as_deref(),
        )
        else {
            // Historical dispatches predate exact runtime.codex recovery binding.
            return Ok(None);
        };
        if protocol_id != APP_SERVER_V2_PROTOCOL_ID {
            return Err("durable runtime.codex protocol is not App Server v2".into());
        }

        let owner = AgentdClient::new(
            self.config.agentd_socket.clone(),
            self.config.agent_id.clone(),
            self.config.generation,
        )?;
        let health = owner.health().await?;
        if !health.ready || health.fenced {
            return Ok(None);
        }
        let ingress = owner.session_ingress().await?;
        let socket_path = AbsolutePathBuf::from_absolute_path(ingress.socket_path)?;
        let client = match timeout(
            RPC_TIMEOUT,
            RemoteAppServerClient::connect_with_bounded_events(
                RemoteAppServerConnectArgs {
                    endpoint: RemoteAppServerEndpoint::UnixSocket { socket_path },
                    client_name: "hepta-infer-worker-reconciler".to_string(),
                    client_version: env!("CARGO_PKG_VERSION").to_string(),
                    experimental_api: true,
                    mcp_server_openai_form_elicitation: false,
                    opt_out_notification_methods: Vec::new(),
                    channel_capacity: 32,
                },
                /*event_channel_capacity*/ 64,
            ),
        )
        .await
        {
            Ok(Ok(client)) => client,
            _ => return Ok(None),
        };
        let observed_home = match client.codex_home() {
            Some(home) => home.to_string(),
            None => {
                let _ = timeout(RPC_TIMEOUT, client.shutdown()).await;
                return Ok(None);
            }
        };
        let expected_home_digest: Digest32 = codex_home_digest.parse()?;
        if Digest32::of_bytes(observed_home.as_bytes()) != expected_home_digest
            || Some(observed_home.as_str()) != health.home_root.to_str()
            || client.server_version() != Some(app_server_version)
        {
            let _ = timeout(RPC_TIMEOUT, client.shutdown()).await;
            return Err(
                "reconciliation App Server identity does not match durable dispatch".into(),
            );
        }

        let expected_input = vec![UserInput::Text {
            text: expected_prompt.to_string(),
            text_elements: Vec::new(),
        }];
        let payload_digest: Digest32 = payload_digest.parse()?;
        let source_admission_digest: Digest32 = source_admission_digest.parse()?;
        if source_admission_digest.to_string() != record.request.payload_digest {
            let _ = timeout(RPC_TIMEOUT, client.shutdown()).await;
            return Err("durable runtime.codex source admission binding drifted".into());
        }
        let intent = CodexOperationIntent {
            operation_id: StableId::new(format!(
                "native:{}",
                Digest32::of_bytes(record.request.request_id.as_bytes())
            ))?,
            thread_id: StableId::new(dispatch.thread_id.clone())?,
            method_id: StableId::new(TURN_START_METHOD_ID)?,
            payload_digest,
            lease_payload_digest: payload_digest,
            deadline_ms,
            app_server_binding: Some(AppServerRequestBinding {
                source_admission_digest,
                agent_generation: Generation::new(record.request.worker_generation)?,
                session_id: StableId::new(session_id.to_string())?,
                client_user_message_id: StableId::new(record.request.request_id.clone())?,
                user_input_digest: Digest32::of_bytes(&serde_json::to_vec(&expected_input)?),
                protocol_id: StableId::new(protocol_id.to_string())?,
                app_server_version: app_server_version.to_string(),
                codex_home_digest: expected_home_digest,
                connection_id: original_connection_id,
            }),
        };
        if codex_request_digest(&intent).to_string() != expected_request_digest {
            let _ = timeout(RPC_TIMEOUT, client.shutdown()).await;
            return Err("durable runtime.codex request digest mismatch during recovery".into());
        }

        let observed = match timeout(
            RPC_TIMEOUT,
            client.request_typed_observed_response::<ThreadReadResponse>(
                ClientRequest::ThreadRead {
                    request_id: RequestId::Integer(20),
                    params: ThreadReadParams {
                        thread_id: dispatch.thread_id.clone(),
                        include_turns: true,
                    },
                },
            ),
        )
        .await
        {
            Ok(Ok(observed)) => observed,
            _ => {
                let _ = timeout(RPC_TIMEOUT, client.shutdown()).await;
                return Ok(None);
            }
        };
        let recovered = reconciled_terminal_output(record, &intent, &expected_input, &observed);
        let mut output = match recovered {
            Ok(Some(output)) => output,
            Ok(None) => {
                let _ = timeout(RPC_TIMEOUT, client.shutdown()).await;
                return Ok(None);
            }
            Err(error) => {
                let _ = timeout(RPC_TIMEOUT, client.shutdown()).await;
                return Err(error);
            }
        };
        let _ =
            verify_owner_health(&mut output, owner.health(), Instant::now() + RPC_TIMEOUT).await;
        downgrade_for_owner_loss(&mut output);
        let _ = timeout(RPC_TIMEOUT, client.shutdown()).await;
        Ok(Some(output))
    }
}

// Reconstruct only a terminal observation for this durable request, retaining
// usage and irreversible boundary facts observed before transport/process loss.
fn reconciled_terminal_output(
    record: &NativeRunRecord,
    intent: &CodexOperationIntent,
    expected_input: &[UserInput],
    observed: &RemoteAppServerObservedResponse<ThreadReadResponse>,
) -> Result<Option<NativeRunOutput>> {
    let dispatch = record
        .dispatch
        .as_ref()
        .ok_or("missing durable dispatch binding")?;
    let request_digest = codex_request_digest(intent).to_string();
    let binding = intent
        .app_server_binding
        .as_ref()
        .ok_or("missing runtime.codex request binding")?;
    if intent.thread_id.as_str() != dispatch.thread_id
        || binding.agent_generation.get() != record.request.worker_generation
        || dispatch.codex_request_digest.as_deref() != Some(request_digest.as_str())
        || binding.source_admission_digest.to_string() != record.request.payload_digest
        || dispatch.codex_source_admission_digest.as_deref()
            != Some(record.request.payload_digest.as_str())
    {
        return Err("reconciled request does not match the durable dispatch binding".into());
    }
    if observed.response().thread.model_provider != dispatch.model_provider {
        return Err("reconciled model provider does not match durable dispatch".into());
    }
    let receipt = adapt_observed_thread_read_reconciliation(
        intent,
        &record.request.request_id,
        expected_input,
        observed,
    )?;
    let Some(receipt) = receipt else {
        return Ok(None);
    };
    let turn_id = receipt
        .turn_id
        .as_ref()
        .ok_or("reconciled terminal receipt omitted turn id")?
        .as_str();
    let mut matching_turns = observed
        .response()
        .thread
        .turns
        .iter()
        .filter(|turn| turn.id == turn_id);
    let turn = matching_turns
        .next()
        .ok_or("reconciled terminal receipt turn disappeared")?;
    if matching_turns.next().is_some() {
        return Err("reconciled terminal receipt has an ambiguous turn identity".into());
    }

    if record
        .turn_id
        .as_deref()
        .is_some_and(|id| id != turn.id.as_str())
    {
        return Err("reconciled turn does not match the durable turn identity".into());
    }

    let mut output_text = String::new();
    for item in &turn.items {
        if let ThreadItem::AgentMessage { text, .. } = item {
            if text.len() > MAX_OUTPUT_BYTES.saturating_sub(output_text.len()) {
                return Err("reconciled output byte limit exceeded".into());
            }
            output_text.push_str(text);
        }
    }
    let (status, boundary_status) = match receipt.status {
        AdapterStatus::Succeeded => {
            (NativeRunStatus::Completed, NativeBoundaryStatus::Succeeded)
        }
        AdapterStatus::Failed => (NativeRunStatus::Failed, NativeBoundaryStatus::Failed),
        AdapterStatus::Interrupted => (
            NativeRunStatus::Interrupted,
            NativeBoundaryStatus::Interrupted,
        ),
        _ => {
            return Err("thread/read reconciliation produced nonterminal status".into());
        }
    };
    let mut output = NativeRunOutput {
        thread_id: dispatch.thread_id.clone(),
        turn_id: turn.id.clone(),
        model: record.request.model.clone(),
        model_provider: dispatch.model_provider.clone(),
        status,
        boundary_status,
        output: output_text,
        observed_output_tokens: None,
        terminal_observed: true,
        owner_authority: NativeOwnerAuthority::Unverified,
        stop_reason: turn
            .error
            .as_ref()
            .map(|error| error.message.chars().take(1024).collect()),
        codex_terminal_correlation_digest: Some(
            receipt
                .correlation_digest
                .ok_or("reconciled terminal receipt omitted correlation digest")?
                .to_string(),
        ),
    };
    if let Some(previous) = &record.observation {
        if previous.thread_id != output.thread_id
            || previous.model != output.model
            || previous.model_provider != output.model_provider
            || (!previous.turn_id.is_empty() && previous.turn_id != output.turn_id)
            || (previous.turn_id.is_empty() && previous.observed_output_tokens.is_some())
        {
            return Err("prior native observation does not match the reconciled assignment".into());
        }
        // thread/read proves terminality, but supplies no usage. Preserve only
        // usage already observed for this exact assignment; None stays unknown.
        output.observed_output_tokens = previous.observed_output_tokens;
        // As in the live event path, late completion cannot clear a stop or
        // restore authority after loss, even if the current owner is healthy.
        if previous.boundary_status != NativeBoundaryStatus::Indeterminate {
            output.boundary_status = previous.boundary_status;
            output.stop_reason = previous.stop_reason.clone().or(output.stop_reason);
        }
        if matches!(previous.owner_authority, NativeOwnerAuthority::Lost { .. }) {
            output.owner_authority = previous.owner_authority.clone();
        }
    }
    // Cancellation intent may have committed before the process could record
    // its stop boundary. Its boolean does not distinguish cancellation, timeout
    // or observation loss; a later completion must not silently become success.
    if record.cancel_requested && output.boundary_status == NativeBoundaryStatus::Succeeded {
        output.boundary_status = NativeBoundaryStatus::Quarantined;
        output.stop_reason = Some(
            "durable cancellation intent has no preserved boundary observation".to_string(),
        );
    }
    downgrade_for_owner_loss(&mut output);
    Ok(Some(output))
}

#[cfg(all(test, unix))]
#[path = "native_recovery_tests.rs"]
mod tests;

#[cfg(test)]
#[path = "native_reconciliation_tests.rs"]
mod reconciliation_tests;
