//! Recovery and deadline boundaries for native physical execution.

use super::*;

pub(super) async fn persist_unknown_turn_start(
    driver: &AppServerModelDriver,
    control: &DurableInferenceControl,
    request_id: &str,
    adapter_intent: &CodexOperationIntent,
    request_digest: Digest32,
    payload_digest: Digest32,
    source_admission_digest: Digest32,
    user_input_digest: Digest32,
    authority_epoch: u64,
    revocation_revision: u64,
    revocation_head_digest: &str,
    authority_witness_digest: &str,
    codex_home_digest: Digest32,
    connection_id: u64,
    app_server_session_id: &str,
    app_server_version: &str,
    intelligence: Option<&NativeIntelligenceRunBinding>,
    intelligence_revision: Option<u64>,
    prepared_revision: u64,
    output: &NativeRunOutput,
    reason: &str,
) -> Result<()> {
    use crate::runtime_codex_quarantine::DurableQuarantineStore;
    use crate::runtime_codex_quarantine::QuarantinedEffectV1;

    let now = unix_time_ms()?;
    let native_revision = control
        .native_record(request_id)
        .ok_or("native unknown outcome omitted its durable record")?
        .revision;
    let revocation_head: Digest32 = revocation_head_digest.parse()?;
    let authority_witness: Digest32 = authority_witness_digest.parse()?;
    let reason_evidence = Digest32::of_bytes(reason.as_bytes());
    let agent_run_id = intelligence
        .map(|binding| binding.run_id.clone())
        .unwrap_or_else(|| format!("local:{request_digest}"));
    let agent_revision = intelligence_revision.unwrap_or(prepared_revision);
    let mut diagnostic = String::new();
    for character in reason.chars() {
        if diagnostic.len() + character.len_utf8() > 1024 {
            break;
        }
        diagnostic.push(character);
    }
    let record = QuarantinedEffectV1 {
        schema_version: 1,
        quarantine_revision: native_revision,
        operation_id: adapter_intent.operation_id.as_str().to_string(),
        source_admission_sha256: *source_admission_digest.as_array(),
        request_sha256: *request_digest.as_array(),
        payload_sha256: *payload_digest.as_array(),
        local_dispatch_sha256: *request_digest.as_array(),
        local_dispatch_revision: prepared_revision,
        agent_run_id,
        agent_revision,
        agent_dispatch_sha256: *request_digest.as_array(),
        authority_epoch,
        revocation_revision,
        revocation_head_sha256: *revocation_head.as_array(),
        authority_witness_sha256: *authority_witness.as_array(),
        agent_generation: driver.config.generation,
        app_server_session_id: app_server_session_id.to_string(),
        app_server_version: app_server_version.to_string(),
        codex_home_sha256: *codex_home_digest.as_array(),
        connection_id,
        thread_id: output.thread_id.clone(),
        turn_id: (!output.turn_id.is_empty()).then(|| output.turn_id.clone()),
        client_user_message_id: request_id.to_string(),
        user_input_sha256: *user_input_digest.as_array(),
        model_id: format!("model:{}", Digest32::of_bytes(output.model.as_bytes())),
        provider_id: format!(
            "provider:{}",
            Digest32::of_bytes(output.model_provider.as_bytes())
        ),
        first_unknown_unix_ms: now,
        last_reconciled_unix_ms: now,
        reconciliation_attempts: 1,
        evidence_sha256: std::collections::BTreeSet::from([
            *source_admission_digest.as_array(),
            *request_digest.as_array(),
            *payload_digest.as_array(),
            *authority_witness.as_array(),
            *reason_evidence.as_array(),
        ]),
        reason_code: "TURN_START_UNKNOWN".to_string(),
        redacted_diagnostic: diagnostic,
    };
    let run_root = driver
        .config
        .agentd_socket
        .parent()
        .ok_or("Agentd socket omitted its exact-generation run root")?;
    let store = DurableQuarantineStore::open(
        &run_root.join("runtime-codex-quarantine-v1.sqlite3"),
        driver.config.agent_id.to_string(),
        driver.config.generation,
    )
    .await?;
    let result = store.record_unknown(&record).await;
    store.close().await;
    result?;
    Ok(())
}

pub(super) async fn await_before_effect<T, E, F>(
    clock: &crate::native_deadline::NativeDeadline,
    per_hop_cap: Duration,
    operation: &'static str,
    future: F,
) -> Result<T>
where
    F: std::future::Future<Output = std::result::Result<T, E>>,
    E: Into<Box<dyn std::error::Error + Send + Sync>>,
{
    let budget = clock.remaining(unix_time_ms()?)?.min(per_hop_cap);
    match timeout(budget, future).await {
        Ok(Ok(value)) => Ok(value),
        Ok(Err(error)) => Err(error.into()),
        Err(_) => Err(format!("{operation} exceeded the runtime.codex absolute deadline").into()),
    }
}
