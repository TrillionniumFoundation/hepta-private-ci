//! Reconcile previously dispatched App Server operations without another dispatch.

use codex_app_server_client::RemoteAppServerClient;
use codex_app_server_client::RemoteAppServerConnectArgs;
use codex_app_server_client::RemoteAppServerEndpoint;
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
    pub(crate) async fn reconcile_existing(
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
        if observed.response().thread.model_provider != dispatch.model_provider {
            let _ = timeout(RPC_TIMEOUT, client.shutdown()).await;
            return Err("reconciled model provider does not match durable dispatch".into());
        }
        let receipt = adapt_observed_thread_read_reconciliation(
            &intent,
            &record.request.request_id,
            &expected_input,
            &observed,
        )?;
        let Some(receipt) = receipt else {
            let _ = timeout(RPC_TIMEOUT, client.shutdown()).await;
            return Ok(None);
        };
        let turn_id = receipt
            .turn_id
            .as_ref()
            .ok_or("reconciled terminal receipt omitted turn id")?
            .as_str();
        let turn = observed
            .response()
            .thread
            .turns
            .iter()
            .find(|turn| turn.id == turn_id)
            .ok_or("reconciled terminal receipt turn disappeared")?;

        let mut output_text = String::new();
        for item in &turn.items {
            if let ThreadItem::AgentMessage { text, .. } = item {
                if text.len() > MAX_OUTPUT_BYTES.saturating_sub(output_text.len()) {
                    let _ = timeout(RPC_TIMEOUT, client.shutdown()).await;
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
                let _ = timeout(RPC_TIMEOUT, client.shutdown()).await;
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
        let _ =
            verify_owner_health(&mut output, owner.health(), Instant::now() + RPC_TIMEOUT).await;
        downgrade_for_owner_loss(&mut output);
        let _ = timeout(RPC_TIMEOUT, client.shutdown()).await;
        Ok(Some(output))
    }
}
