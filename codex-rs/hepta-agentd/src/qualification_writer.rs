//! Agentd-owned qualification turn writer capability.
//!
//! The positive path exists only in the explicit
//! `qualification-cognitive-write` build.  It binds each durable Codex turn
//! identity to one Agent-local lease and compact executor, and records local
//! lifecycle metadata only.  The epochs below are process-local
//! qualification witnesses; they are not production supervisor authority.

use std::sync::Arc;

use codex_hepta_memory::CognitiveRuntime;
use codex_hepta_memory_extension::QualificationTurnWriterHost;
#[cfg(feature = "qualification-cognitive-write")]
use codex_hepta_memory_extension::QualificationTurnWriterPrepareRequest;

use crate::AgentdIdentity;
use crate::AgentdState;

#[cfg(feature = "qualification-cognitive-write")]
const CAPABILITY_ID: &str = "hepta-agentd:qualification-turn-writer:v1";

#[cfg(feature = "qualification-cognitive-write")]
fn qualification_attempt_digest(
    agent_id: &codex_hepta_contracts::AgentId,
    logical_turn_id: &str,
    turn_id: &str,
    fleet_generation: u64,
    spawn_generation: u64,
) -> codex_hepta_contracts::Sha256Digest {
    let mut framed = Vec::new();
    let mut push = |part: &[u8]| {
        framed.extend_from_slice(&(part.len() as u64).to_be_bytes());
        framed.extend_from_slice(part);
    };
    push(b"hepta-agentd:qualification-attempt:v3");
    push(agent_id.as_str().as_bytes());
    push(logical_turn_id.as_bytes());
    push(turn_id.as_bytes());
    push(&fleet_generation.to_be_bytes());
    push(&spawn_generation.to_be_bytes());
    codex_hepta_contracts::Sha256Digest::for_bytes(&framed)
}

pub(crate) fn qualification_turn_writer_host(
    identity: &AgentdIdentity,
    state: Arc<AgentdState>,
    runtime: &CognitiveRuntime,
) -> Option<QualificationTurnWriterHost> {
    #[cfg(not(feature = "qualification-cognitive-write"))]
    {
        let _ = (identity, state, runtime);
        None
    }

    #[cfg(feature = "qualification-cognitive-write")]
    {
        let store = Arc::clone(runtime.available_store()?);
        if store.owner_agent_id() != &identity.agent_id
            || state.identity().agent_id != identity.agent_id
            || state.identity().spawn_generation != identity.spawn_generation
        {
            return None;
        }
        let agent_id = identity.agent_id.clone();
        let spawn_generation = identity.spawn_generation;
        Some(QualificationTurnWriterHost::from_request_fn(
            CAPABILITY_ID,
            move |request| {
                let state = Arc::clone(&state);
                let store = Arc::clone(&store);
                let agent_id = agent_id.clone();
                async move {
                    prepare_qualification_turn_writer_input_with_request(
                        state,
                        store,
                        agent_id,
                        spawn_generation,
                        request,
                    )
                    .await
                }
            },
        ))
    }
}

#[cfg(all(feature = "qualification-cognitive-write", test))]
pub(crate) async fn prepare_qualification_turn_writer_input(
    state: Arc<AgentdState>,
    store: Arc<codex_hepta_memory::CognitiveStore>,
    agent_id: codex_hepta_contracts::AgentId,
    spawn_generation: u64,
    turn_id: String,
) -> Result<
    codex_hepta_memory_extension::QualificationTurnWriterInput,
    codex_hepta_memory_extension::QualificationTurnWriterInputError,
> {
    let mut request = QualificationTurnWriterPrepareRequest::for_turn(turn_id);
    // This direct helper is used only by Agentd's bounded qualification tests
    // and explicit recovery seam; the runtime host path receives the richer
    // Core admission identity and never fabricates one.
    request.durable_admission = true;
    prepare_qualification_turn_writer_input_with_request(
        state,
        store,
        agent_id,
        spawn_generation,
        request,
    )
    .await
}

#[cfg(feature = "qualification-cognitive-write")]
async fn prepare_qualification_turn_writer_input_with_request(
    state: Arc<AgentdState>,
    store: Arc<codex_hepta_memory::CognitiveStore>,
    agent_id: codex_hepta_contracts::AgentId,
    spawn_generation: u64,
    request: QualificationTurnWriterPrepareRequest,
) -> Result<
    codex_hepta_memory_extension::QualificationTurnWriterInput,
    codex_hepta_memory_extension::QualificationTurnWriterInputError,
> {
    use std::time::SystemTime;
    use std::time::UNIX_EPOCH;

    use codex_hepta_contracts::Sha256Digest;
    use codex_hepta_memory::CompactFence;
    use codex_hepta_memory::LocalTurnLifecycleBinding;
    use codex_hepta_memory::LogicalTurnAttemptRequest;
    use codex_hepta_memory::LogicalTurnRegistryError;
    use codex_hepta_memory::LogicalTurnRequest;
    use codex_hepta_memory::LogicalTurnReservation;
    use codex_hepta_memory_extension::QualificationTurnWriterInput;
    use codex_hepta_memory_extension::QualificationTurnWriterInputError;

    const LOCAL_QUALIFICATION_AUTHORITY_EPOCH: u64 = 1;
    const LEASE_TTL_SECONDS: u64 = 3_600;

    fn fenced() -> QualificationTurnWriterInputError {
        QualificationTurnWriterInputError::Invalid(
            "Agentd generation fence rejected the qualification turn writer".to_string(),
        )
    }

    let turn_id = request.turn_id.clone();
    if !request.durable_admission {
        return Err(QualificationTurnWriterInputError::Invalid(
            "qualification host requires a durable user-message admission identity".to_string(),
        ));
    }
    if turn_id.starts_with("auto-compact-") {
        return Err(QualificationTurnWriterInputError::Invalid(
            "process-local auto-compaction ids are not stable qualification turns".to_string(),
        ));
    }
    if turn_id.trim().is_empty() || turn_id.len() > 256 || turn_id.as_bytes().contains(&0) {
        return Err(QualificationTurnWriterInputError::Invalid(
            "qualification turn id must contain 1..=256 non-NUL bytes".to_string(),
        ));
    }
    if request.logical_turn_id.trim().is_empty()
        || request.logical_scope_key.trim().is_empty()
        || request.logical_binding_sha256.as_str().len() != 64
    {
        return Err(QualificationTurnWriterInputError::Invalid(
            "host logical-turn identity is incomplete".to_string(),
        ));
    }

    let fleet_generation = state.qualification_turn_authority().map_err(|_| fenced())?;
    if state.identity().spawn_generation != spawn_generation
        || state.identity().agent_id != agent_id
        || store.owner_agent_id() != &agent_id
    {
        return Err(fenced());
    }

    // LocalLeaseOutbox::generation is the append-only generation of this
    // lease, not the Agent/fleet lifecycle generation. Every physical spawn
    // gets a fresh attempt tuple; the stable registry decides whether this
    // tuple wins, replays, or must adopt an older in-flight attempt.
    const LOCAL_LEASE_GENERATION: u64 = 1;

    let expires_at = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|_| {
            QualificationTurnWriterInputError::Invalid(
                "system clock is before the Unix epoch".to_string(),
            )
        })?
        .as_secs()
        .checked_add(LEASE_TTL_SECONDS)
        .ok_or_else(|| {
            QualificationTurnWriterInputError::Invalid(
                "qualification lease expiry overflowed".to_string(),
            )
        })?;
    let authority_epoch = LOCAL_QUALIFICATION_AUTHORITY_EPOCH;
    let owner_epoch = fleet_generation;
    let attempt_suffix = qualification_attempt_digest(
        &agent_id,
        &request.logical_turn_id,
        &turn_id,
        fleet_generation,
        spawn_generation,
    )
    .as_str()
    .to_string();
    let attempt_id = format!("qualification-attempt:{attempt_suffix}");
    let lease_id = format!("qualification-turn-attempt:{attempt_suffix}");
    let journal_id = format!("qualification-turn-journal-attempt:{attempt_suffix}");
    let trajectory_id = format!("qualification:trajectory-attempt:{attempt_suffix}");
    let occurrence_key = format!("qualification-turn-start-attempt:{attempt_suffix}");
    let fencing_token = Sha256Digest::for_bytes(
        format!("hepta-agentd:qualification-turn-fence:v2:{attempt_id}").as_bytes(),
    )
    .as_str()
    .to_string();

    let logical_request = LogicalTurnRequest::new(
        request.logical_turn_id.clone(),
        request.logical_scope_key.clone(),
        request.logical_binding_sha256.clone(),
    )
    .map_err(|error| QualificationTurnWriterInputError::Invalid(error.to_string()))?;
    let attempt_request = LogicalTurnAttemptRequest::new(
        attempt_id,
        lease_id,
        journal_id,
        trajectory_id,
        occurrence_key,
        authority_epoch,
        owner_epoch,
        LOCAL_LEASE_GENERATION,
        fencing_token,
        expires_at,
    )
    .map_err(|error| QualificationTurnWriterInputError::Invalid(error.to_string()))?;
    let reservation = store
        .reserve_or_replay_logical_turn(logical_request, attempt_request)
        .await
        .map_err(|error: LogicalTurnRegistryError| {
            QualificationTurnWriterInputError::Invalid(format!(
                "logical-turn registry rejected qualification prepare: {error}"
            ))
        })?;
    let attempt = match reservation {
        LogicalTurnReservation::Acquired { attempt }
        | LogicalTurnReservation::Replayed { attempt }
        | LogicalTurnReservation::Takeover { attempt, .. } => attempt,
        LogicalTurnReservation::ExistingInFlight { .. } => {
            // A live different physical attempt belongs to another callback
            // or spawn.  Reusing its journal/trajectory with the current
            // turn id would cross the attempt fence; only an exact
            // `Replayed` tuple may reopen a writable input.
            return Err(QualificationTurnWriterInputError::Invalid(
                "logical-turn attempt is already in flight under another physical fence"
                    .to_string(),
            ));
        }
        LogicalTurnReservation::Conflict { reason } => {
            return Err(QualificationTurnWriterInputError::Invalid(format!(
                "logical-turn registry conflict: {reason}"
            )));
        }
        LogicalTurnReservation::BlockedByEvidence { evidence, .. } => {
            // Evidence is a durable quarantine witness, not an implicit
            // terminal or owner-death proof.  Schema 0010 has no abort
            // projection, so leave the exact old head untouched and require
            // an explicit later lifecycle/authority decision.
            return Err(QualificationTurnWriterInputError::Invalid(format!(
                "logical-turn registry blocked qualification attempt with {} evidence rows",
                evidence.total_rows()
            )));
        }
    };

    // Reopen only the exact winner returned by the registry.  A caller's
    // freshly computed tuple is never substituted for a durable winner.
    let inspected = store
        .inspect_local_lease_head(&attempt.lease_id)
        .await
        .map_err(|error| QualificationTurnWriterInputError::Invalid(error.to_string()))?;
    let head = match inspected.disposition {
        codex_hepta_memory::LocalLeaseHeadDisposition::Active => {
            inspected.head.ok_or_else(fenced)?
        }
        codex_hepta_memory::LocalLeaseHeadDisposition::ExpiredActive
        | codex_hepta_memory::LocalLeaseHeadDisposition::Released
        | codex_hepta_memory::LocalLeaseHeadDisposition::RolledBack
        | codex_hepta_memory::LocalLeaseHeadDisposition::Missing => return Err(fenced()),
    };
    // A returned in-flight attempt may belong to an older fleet lifecycle
    // generation.  It is not safe to adopt that physical fence merely because
    // the stable logical identity matches; only the registry's expired,
    // zero-evidence takeover may mint a successor under the current owner
    // epoch.
    if attempt.authority_epoch != authority_epoch || attempt.owner_epoch != owner_epoch {
        return Err(fenced());
    }
    if head.owner_agent_id != agent_id
        || head.generation != attempt.generation
        || head.fencing_token != attempt.fencing_token
        || head.authority_epoch != Some(attempt.authority_epoch)
        || head.owner_epoch != Some(attempt.owner_epoch)
        || head.lease_expires_at_unix_seconds != Some(attempt.lease_expires_at_unix_seconds)
        || head.lease_sequence != attempt.lease_sequence
        || head.lease_sha256 != attempt.lease_head_sha256
    {
        return Err(fenced());
    }
    let lease = store
        .reopen_host_bound_lease(
            head,
            attempt.authority_epoch,
            attempt.owner_epoch,
            attempt.lease_expires_at_unix_seconds,
        )
        .await?;

    let fence = CompactFence::new(
        attempt.authority_epoch,
        attempt.owner_epoch,
        attempt.generation,
        attempt.fencing_token.clone(),
    )
    .map_err(|error| QualificationTurnWriterInputError::Invalid(error.to_string()))?;
    let executor = match store
        .open_local_compact_executor_bound(attempt.journal_id.clone(), fence, &lease)
        .await
    {
        Ok(executor) => executor,
        Err(error) => return Err(error.into()),
    };
    let current_fleet_generation = match state.qualification_turn_authority() {
        Ok(generation) => generation,
        Err(_) => return Err(fenced()),
    };
    if current_fleet_generation != fleet_generation {
        return Err(fenced());
    }
    let binding = match LocalTurnLifecycleBinding::from_handles(&turn_id, &lease, &executor) {
        Ok(binding) => binding,
        Err(error) => return Err(error.into()),
    };
    let payload_json = serde_json::json!({
        "schema_version": 1,
        "turn_id_sha256": binding.turn_id_sha256.as_str(),
        "fleet_generation": fleet_generation,
        "spawn_generation": spawn_generation,
        "logical_turn_id": request.logical_turn_id,
        "logical_binding_sha256": request.logical_binding_sha256.as_str(),
        "attempt_id": attempt.attempt_id,
        "external_effect": false,
        "kg_write_authority": false,
        "production_caller": false
    })
    .to_string();
    match QualificationTurnWriterInput::new_with_trajectory(
        turn_id,
        attempt.trajectory_id,
        binding,
        lease.clone(),
        executor,
        attempt.occurrence_key,
        payload_json,
    ) {
        Ok(input) => Ok(input),
        Err(error) => Err(error),
    }
}
