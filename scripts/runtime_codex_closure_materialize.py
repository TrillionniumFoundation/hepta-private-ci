#!/usr/bin/env python3
from pathlib import Path


def replace_once(source: str, old: str, new: str, label: str) -> str:
    count = source.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one match, found {count}")
    return source.replace(old, new)


path = Path("codex-rs/hepta-infer-worker-host/src/native_app_server.rs")
source = path.read_text(encoding="utf-8")

source = replace_once(
    source,
    "use std::time::Duration;\n",
    "use std::time::Duration;\nuse std::time::SystemTime;\nuse std::time::UNIX_EPOCH;\n",
    "Duration import",
)
source = replace_once(
    source,
    "use codex_hepta_agentd::AgentdClient;\n",
    """use codex_hepta_codex_adapter::AdapterStatus as CodexAdapterStatus;
use codex_hepta_codex_adapter::AppServerObservation;
use codex_hepta_codex_adapter::CodexAdapterReceipt;
use codex_hepta_codex_adapter::CodexOperationIntent;
use codex_hepta_codex_adapter::PreparedCodexRequest;
use codex_hepta_codex_adapter::RetryDisposition;
use codex_hepta_codex_adapter::observe_app_server_event;
use codex_hepta_codex_adapter::observe_server_notification;
use codex_hepta_codex_adapter::observe_turn_start_error;
use codex_hepta_codex_adapter::prepare as prepare_codex_request;
use codex_hepta_agentd::AgentdClient;
""",
    "Agentd import",
)
source = replace_once(
    source,
    "use codex_hepta_contracts::AgentId;\n",
    """use codex_hepta_contracts::AgentId;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
""",
    "AgentId import",
)

source = replace_once(
    source,
    """        control.dispatch_native(
            request_id,
            NativeDispatch {
                thread_id: started.thread.id.clone(),
                model_provider: started.model_provider.clone(),
                context_digest: control::digest(&serde_json::to_vec(&additional_context)?),
            },
        )?;
        let response = timeout(
            RPC_TIMEOUT,
            client.request_typed::<TurnStartResponse>(ClientRequest::TurnStart {
                request_id: RequestId::Integer(2),
                params: TurnStartParams {
                    thread_id: started.thread.id.clone(),
                    client_user_message_id: Some(request_id.to_string()),
                    input: vec![UserInput::Text {
                        text: prompt,
                        text_elements: Vec::new(),
                    }],
                    additional_context,
                    environments: Some(Vec::new()),
                    ..Default::default()
                },
            }),
        )
        .await;
""",
    """        let turn_params = TurnStartParams {
            thread_id: started.thread.id.clone(),
            client_user_message_id: Some(request_id.to_string()),
            input: vec![UserInput::Text {
                text: prompt,
                text_elements: Vec::new(),
            }],
            additional_context,
            environments: Some(Vec::new()),
            ..Default::default()
        };
        let payload_digest = Digest32::of_bytes(&serde_json::to_vec(&turn_params)?);
        let now_ms = unix_time_ms()?;
        let deadline_ms = now_ms
            .checked_add(u64::try_from(RPC_TIMEOUT.as_millis())?)
            .ok_or("runtime.codex admission deadline overflow")?;
        // This gate binds the exact TurnStartParams immediately before the
        // durable dispatch marker and physical App Server seam. It does not
        // mint authority: final-use authorization remains an independent gate.
        let prepared_codex = prepare_codex_request(
            now_ms,
            CodexOperationIntent {
                operation_id: codex_operation_id(request_id)?,
                thread_id: codex_id(&started.thread.id, "thread")?,
                method_id: codex_id("app-server.turn-start.v2", "method")?,
                payload_digest,
                lease_payload_digest: payload_digest,
                deadline_ms,
            },
        )?;
        control.dispatch_native(
            request_id,
            NativeDispatch {
                thread_id: started.thread.id.clone(),
                model_provider: started.model_provider.clone(),
                context_digest: control::digest(&serde_json::to_vec(
                    &turn_params.additional_context,
                )?),
            },
        )?;
        let response = timeout(
            RPC_TIMEOUT,
            client.request_typed::<TurnStartResponse>(ClientRequest::TurnStart {
                request_id: RequestId::Integer(2),
                params: turn_params,
            }),
        )
        .await;
""",
    "turn/start dispatch",
)

source = replace_once(
    source,
    """        let turn = match response {
            Ok(Ok(response)) => response.turn,
            _ => {
                let _ = timeout(RPC_TIMEOUT, client.shutdown()).await;
                return Ok(NativeRunOutput {
                    thread_id: started.thread.id,
                    turn_id: String::new(),
                    model: started.model,
                    model_provider: started.model_provider,
                    status: NativeRunStatus::Indeterminate,
                    output: String::new(),
                    observed_output_tokens: None,
                    terminal_observed: false,
                    owner_authority: NativeOwnerAuthority::Unverified,
                    stop_reason: Some("turn/start outcome unknown; do not replay".to_string()),
                });
            }
        };
""",
    """        let turn = match response {
            Ok(Ok(response)) => response.turn,
            Ok(Err(error)) => {
                let receipt = observe_turn_start_error(&prepared_codex, &error)?;
                let stop_reason = format!(
                    "turn/start {:?}; runtime.codex retry={:?}; durable dispatch marker forbids blind replay",
                    receipt.status, receipt.retry
                );
                let _ = timeout(RPC_TIMEOUT, client.shutdown()).await;
                return Ok(NativeRunOutput {
                    thread_id: started.thread.id,
                    turn_id: String::new(),
                    model: started.model,
                    model_provider: started.model_provider,
                    status: NativeRunStatus::Indeterminate,
                    output: String::new(),
                    observed_output_tokens: None,
                    terminal_observed: false,
                    owner_authority: NativeOwnerAuthority::Unverified,
                    stop_reason: Some(stop_reason),
                });
            }
            Err(_) => {
                let receipt = prepared_codex.clone().observe(Some(
                    AppServerObservation::timed_out(prepared_codex.thread_id().clone(), None),
                ))?;
                if receipt.status != CodexAdapterStatus::TimedOut
                    || receipt.retry != RetryDisposition::ReconcileBeforeRetry
                {
                    return Err("runtime.codex timeout classification drifted".into());
                }
                let _ = timeout(RPC_TIMEOUT, client.shutdown()).await;
                return Ok(NativeRunOutput {
                    thread_id: started.thread.id,
                    turn_id: String::new(),
                    model: started.model,
                    model_provider: started.model_provider,
                    status: NativeRunStatus::Indeterminate,
                    output: String::new(),
                    observed_output_tokens: None,
                    terminal_observed: false,
                    owner_authority: NativeOwnerAuthority::Unverified,
                    stop_reason: Some(
                        "turn/start timed out; reconcile exact admission before replay".to_string(),
                    ),
                });
            }
        };
""",
    "turn/start outcome classification",
)
source = replace_once(
    source,
    """                cancellation,
                Some(&owner),
            )
""",
    """                cancellation,
                &prepared_codex,
                Some(&owner),
            )
""",
    "primary observe call",
)
source = replace_once(
    source,
    """                    &grace,
                    /*owner*/ None,
                )
""",
    """                    &grace,
                    &prepared_codex,
                    /*owner*/ None,
                )
""",
    "grace observe call",
)
source = replace_once(
    source,
    """        cancellation: &CancellationToken,
        owner: Option<&AgentdClient>,
    ) -> std::result::Result<(), String> {
""",
    """        cancellation: &CancellationToken,
        prepared_codex: &PreparedCodexRequest,
        owner: Option<&AgentdClient>,
    ) -> std::result::Result<(), String> {
""",
    "observe signature",
)
source = replace_once(
    source,
    """            match event {
                AppServerEvent::ServerNotification(notification) => {
                    if observe_notification(output, *notification)? {
                        return Ok(());
                    }
                }
                AppServerEvent::ServerRequest(request) => {
""",
    """            let codex_receipt = observe_app_server_event(prepared_codex, &event)
                .map_err(|error| format!("runtime.codex event observation failed: {error}"))?;
            match event {
                AppServerEvent::ServerNotification(notification) => {
                    if observe_notification(output, *notification)? {
                        let receipt = codex_receipt.ok_or_else(|| {
                            "terminal App Server event lacked runtime.codex receipt".to_string()
                        })?;
                        verify_codex_receipt(output, &receipt)?;
                        return Ok(());
                    }
                }
                AppServerEvent::ServerRequest(request) => {
""",
    "server notification observation",
)
source = replace_once(
    source,
    """                AppServerEvent::Lagged { .. } => return Err("provider events lost".to_string()),
                AppServerEvent::Disconnected { message } => return Err(message),
""",
    """                AppServerEvent::Lagged { .. } => {
                    verify_uncertain_codex_receipt(codex_receipt.as_ref())?;
                    return Err("provider events lost; reconcile before replay".to_string());
                }
                AppServerEvent::Disconnected { message } => {
                    verify_uncertain_codex_receipt(codex_receipt.as_ref())?;
                    return Err(format!("{message}; reconcile before replay"));
                }
""",
    "stream-loss observation",
)

helpers = r'''fn codex_receipt_for_notification(
    prepared: &PreparedCodexRequest,
    output: &NativeRunOutput,
    notification: &ServerNotification,
) -> std::result::Result<Option<CodexAdapterReceipt>, String> {
    let receipt = observe_server_notification(prepared, notification)
        .map_err(|error| format!("runtime.codex notification observation failed: {error}"))?;
    if let Some(receipt) = receipt.as_ref() {
        let turn_matches = receipt
            .turn_id
            .as_ref()
            .is_some_and(|turn| turn.as_str() == output.turn_id);
        if receipt.thread_id.as_str() != output.thread_id || !turn_matches {
            return Err("runtime.codex receipt does not match native thread/turn".to_string());
        }
    }
    Ok(receipt)
}

fn verify_codex_receipt(
    output: &NativeRunOutput,
    receipt: &CodexAdapterReceipt,
) -> std::result::Result<(), String> {
    let status_matches = matches!(
        (receipt.status, output.status),
        (CodexAdapterStatus::Succeeded, NativeRunStatus::Completed)
            | (CodexAdapterStatus::Failed, NativeRunStatus::Failed)
            | (CodexAdapterStatus::Interrupted, NativeRunStatus::Interrupted)
    );
    let turn_matches = receipt
        .turn_id
        .as_ref()
        .is_some_and(|turn| turn.as_str() == output.turn_id);
    if receipt.thread_id.as_str() != output.thread_id
        || !turn_matches
        || !status_matches
        || receipt.retry != RetryDisposition::DoNotRetry
        || receipt.model_authority
        || receipt.provider_authority
        || receipt.authority.grants_any()
    {
        return Err("runtime.codex terminal receipt does not match native execution".to_string());
    }
    Ok(())
}

fn verify_uncertain_codex_receipt(
    receipt: Option<&CodexAdapterReceipt>,
) -> std::result::Result<(), String> {
    let Some(receipt) = receipt else {
        return Err("runtime.codex did not classify uncertain stream outcome".to_string());
    };
    if receipt.status != CodexAdapterStatus::Indeterminate
        || receipt.retry != RetryDisposition::ReconcileBeforeRetry
        || receipt.model_authority
        || receipt.provider_authority
        || receipt.authority.grants_any()
    {
        return Err("runtime.codex uncertain outcome classification drifted".to_string());
    }
    Ok(())
}

fn codex_operation_id(request_id: &str) -> Result<StableId> {
    codex_id(
        &format!("operation:{}", Digest32::of_bytes(request_id.as_bytes())),
        "operation",
    )
}

fn codex_id(value: &str, kind: &'static str) -> Result<StableId> {
    StableId::new(value.to_string())
        .map_err(|_| format!("invalid runtime.codex {kind} identifier").into())
}

fn unix_time_ms() -> Result<u64> {
    let millis = SystemTime::now().duration_since(UNIX_EPOCH)?.as_millis();
    Ok(u64::try_from(millis)?)
}

'''
source = replace_once(
    source,
    "async fn verify_owner_health(\n",
    helpers + "async fn verify_owner_health(\n",
    "runtime.codex helper insertion",
)

path.write_text(source, encoding="utf-8")
