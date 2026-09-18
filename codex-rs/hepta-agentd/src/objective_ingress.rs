//! Signed Objective ingress composed through the existing AuthBus outbox and
//! canonical learning.ledger owner. Agentd owns only the host capability and
//! ephemeral run coordinator; it does not create a second Objective database.

use std::fs::File;
use std::fs::OpenOptions;
use std::path::Path;
use std::str::FromStr;
use std::sync::Mutex;

use codex_hepta_authbus::SignedMessage;
use codex_hepta_authbus::SignedMessageClaims;
use codex_hepta_evidence::AuthBusDelivery;
use codex_hepta_evidence::AuthBusDeliveryState;
use codex_hepta_evidence::AuthBusDeliveryStatus;
use codex_hepta_learning_ledger::DurableLearningJournal;
use codex_hepta_learning_ledger::DurableLedger;
use codex_hepta_learning_ledger::LedgerAnchor;
use codex_hepta_learning_ledger::LedgerEvent;
use codex_hepta_learning_ledger::LedgerRecovery;
use codex_hepta_learning_ledger::LedgerWitnessStore;
use codex_hepta_objective::ObjectiveAdmissionContextV1;
use codex_hepta_objective::ObjectiveAdmissionProfileV1;
use codex_hepta_objective::ObjectiveSourceAuthenticationV1;
use codex_hepta_objective::decode_admission_profile_json_v1;
use codex_hepta_objective::decode_source_envelope_json_v1;
use codex_hepta_objective::MAX_OBJECTIVE_ADMISSION_PROFILE_JSON_BYTES;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::Revision;
use codex_hepta_types::StableId;

use crate::AgentRunCoordinator;
use crate::AgentdError;
use crate::AgentdIdentity;
use crate::AgentdState;
use crate::AuthBusObjectiveBody;
use crate::AuthBusObjectiveIngress;
use crate::AuthBusObjectiveState;
use crate::AuthBusObjectiveStatus;
use crate::RuntimeComposition;
use crate::authbus_ingress;
use crate::authbus_trust::hex_bytes;
use crate::authbus_trust::read_private_owner_file;
use crate::objective_host::start_intelligence_run_v1;

const PRODUCT_SOURCE_JSON_BYTES: usize = 32 * 1024;
const PRODUCT_BODY_JSON_BYTES: usize = 48 * 1024;
const MAX_LEDGER_RECORDS: usize = 8_192;
const LEDGER_FILE: &str = "objective-learning-ledger-v1.bin";
const WITNESS_FILE: &str = "objective-learning-ledger-v1.witness";

pub(crate) struct ObjectiveIngressHost {
    profile: ObjectiveAdmissionProfileV1,
    profile_digest: Digest32,
    subject: StableId,
    scope: Digest32,
    state: Mutex<ObjectiveOwnerState>,
}

struct ObjectiveOwnerState {
    ledger: DurableLedger,
    witness: LedgerWitnessStore,
    coordinator: AgentRunCoordinator,
}

impl ObjectiveIngressHost {
    pub(crate) fn open(
        identity: &AgentdIdentity,
        profile_file: &Path,
        now_ms: u64,
    ) -> Result<Self, AgentdError> {
        let bytes = read_private_owner_file(
            profile_file,
            identity,
            MAX_OBJECTIVE_ADMISSION_PROFILE_JSON_BYTES,
        )?;
        let profile = decode_admission_profile_json_v1(&bytes)
            .map_err(|error| objective_invalid(&format!("admission profile: {error}")))?;
        if profile.allowed_trusted_source_identities.is_empty() {
            return Err(objective_invalid(
                "admission profile must register at least one signed source identity",
            ));
        }
        let profile_digest = profile
            .digest()
            .map_err(|error| objective_invalid(&format!("admission profile: {error}")))?;
        let binding = ledger_binding(identity);
        let ledger_file = open_private_state_file(identity, LEDGER_FILE)?;
        let witness_file = open_private_state_file(identity, WITNESS_FILE)?;

        let mut witness = if witness_file.metadata()?.len() == 0 {
            LedgerWitnessStore::create(witness_file, binding)
                .map_err(|error| objective_invalid(&format!("ledger witness create: {error}")))?
        } else {
            LedgerWitnessStore::recover(witness_file, binding)
                .map_err(|error| objective_invalid(&format!("ledger witness recover: {error}")))?
        };
        let recovery = witness
            .latest()
            .map(LedgerRecovery::Acknowledged)
            .unwrap_or(LedgerRecovery::Unacknowledged);
        let ledger = if ledger_file.metadata()?.len() == 0 {
            if witness.latest().is_some() {
                return Err(objective_invalid(
                    "learning ledger is empty while its independent witness is not",
                ));
            }
            DurableLedger::create(ledger_file, binding, MAX_LEDGER_RECORDS)
                .map_err(|error| objective_invalid(&format!("learning ledger create: {error}")))?
        } else {
            DurableLedger::recover(ledger_file, binding, MAX_LEDGER_RECORDS, recovery)
                .map_err(|error| objective_invalid(&format!("learning ledger recover: {error}")))?
        };

        reconcile_witness(&ledger, &mut witness)?;
        let composition = RuntimeComposition {
            agent_id: identity.agent_id.as_str().to_string(),
            supervisor_generation: identity.spawn_generation,
            agentd_generation: identity.spawn_generation,
            configuration_digest: profile_digest.to_string(),
            ports_digest: Digest32::of_bytes(b"hepta.agentd.objective-ingress.v1").to_string(),
        };
        let mut coordinator = AgentRunCoordinator::compose_runtime(composition)
            .map_err(|error| objective_invalid(&format!("run coordinator: {error:?}")))?;
        recover_active_runs(identity, now_ms, &ledger, &mut coordinator)?;

        Ok(Self {
            profile,
            profile_digest,
            subject: StableId::new(identity.agent_id.as_str())
                .map_err(|error| objective_invalid(&error.to_string()))?,
            scope: objective_scope(identity),
            state: Mutex::new(ObjectiveOwnerState {
                ledger,
                witness,
                coordinator,
            }),
        })
    }

    pub(crate) fn subject(&self) -> &StableId {
        &self.subject
    }

    pub(crate) fn scope(&self) -> Digest32 {
        self.scope
    }

    pub(crate) fn permits_issuer(&self, issuer: &StableId) -> bool {
        self.profile.allowed_trusted_source_identities.contains(issuer)
    }

    pub(crate) fn process_delivery(
        &self,
        agentd: &AgentdState,
        delivery: &AuthBusDelivery,
        now_ms: u64,
    ) -> Result<Digest32, AgentdError> {
        let identity = agentd.identity();
        let body: AuthBusObjectiveBody = serde_json::from_slice(&delivery.payload)
            .map_err(|_| objective_invalid("stored Objective payload is not canonical JSON"))?;
        let canonical = objective_payload(identity, &body)?;
        if canonical != delivery.payload {
            return Err(objective_invalid("stored Objective payload is not canonical"));
        }
        if !self.permits_issuer(&delivery.message.claims.issuer_id) {
            return Err(objective_invalid(
                "signed issuer is not registered by the selected Objective profile",
            ));
        }

        let source = decode_source_envelope_json_v1(body.source_envelope_json.as_bytes())
            .map_err(|error| objective_invalid(&format!("source envelope: {error}")))?;
        let context = ObjectiveAdmissionContextV1 {
            revision: Revision::new(body.objective_revision)
                .map_err(|error| objective_invalid(&format!("revision: {error}")))?,
            now_unix_micros: now_ms
                .checked_mul(1_000)
                .ok_or_else(|| objective_invalid("host clock overflow"))?,
            selected_profile_digest: self.profile_digest,
            source_authentication: ObjectiveSourceAuthenticationV1::AuthorizedAdapter {
                source_identity: delivery.message.claims.issuer_id.clone(),
                source_digest: source.structured_intent.provenance.source_digest,
            },
        };
        let record_id = StableId::new(format!(
            "objective-run:{}",
            delivery.lease.delivery_id()
        ))
        .map_err(|error| objective_invalid(&format!("record id: {error}")))?;
        let run_id = StableId::new(&body.run_id)
            .map_err(|error| objective_invalid(&format!("run id: {error}")))?;

        let mut state = self
            .state
            .lock()
            .map_err(|_| AgentdError::Protocol("Objective owner mutex is poisoned".to_string()))?;
        let predecessor = predecessor_for_record(&state.ledger, &record_id)?;
        let result = codex_hepta_intelligence::prepare_intelligence_run_v1(
            &mut state.ledger,
            &source,
            &self.profile,
            &context,
            codex_hepta_intelligence::ProductionRunBindingsV1 {
                record_id,
                run_id,
                preference_state_digest: parse_digest(
                    &body.preference_state_digest,
                    "preference state",
                )?,
                model_tuple_digest: parse_digest(&body.model_tuple_digest, "model tuple")?,
                prompt_registry_digest: parse_digest(
                    &body.prompt_registry_digest,
                    "prompt registry",
                )?,
                artifact_set_digest: parse_digest(&body.artifact_set_digest, "artifact set")?,
                runtime_body_digest: parse_digest(&body.runtime_body_digest, "runtime body")?,
                authority_epoch: body.authority_epoch,
                generation: identity.spawn_generation,
                fence_digest: objective_fence(identity, self.profile_digest),
                expected_ledger_predecessor: predecessor,
            },
        )
        .map_err(|error| objective_invalid(&format!("canonical publication: {error}")))?;

        match result {
            codex_hepta_intelligence::ProductionObjectiveDispositionV1::Published(receipt) => {
                reconcile_witness(&state.ledger, &mut state.witness)?;
                // The durable publication may outlive an authority/generation
                // change. Revalidate the host and signed issuer after both
                // ledger and independent witness fsync, immediately before
                // exposing the ephemeral runtime admission.
                authbus_ingress::require_ready(agentd)?;
                let authbus = authbus_ingress::attached(agentd)?;
                let trust = authbus.trust(agentd)?;
                let issuer = trust.issuer()?;
                if issuer.revoked || !self.permits_issuer(&issuer.issuer_id) {
                    return Err(objective_invalid(
                        "issuer changed after durable RunStart publication",
                    ));
                }
                delivery
                    .message
                    .authenticate(
                        &issuer,
                        self.scope,
                        Digest32::of_bytes(&delivery.payload),
                        authbus_ingress::now_ms()?,
                    )
                    .map_err(|error| {
                        objective_invalid(&format!(
                            "post-publication signature revalidation: {error}"
                        ))
                    })?;
                start_intelligence_run_v1(
                    &mut state.coordinator,
                    authbus_ingress::now_ms()?,
                    &receipt.host_envelope,
                )
                .map_err(|error| objective_invalid(&error.to_string()))?;
                Ok(receipt.host_envelope.envelope_digest)
            }
            codex_hepta_intelligence::ProductionObjectiveDispositionV1::Conflict {
                conflict,
                ..
            } => Ok(conflict.conflict_digest),
            codex_hepta_intelligence::ProductionObjectiveDispositionV1::ExplicitAbstain {
                admission,
                compile,
            } => {
                let mut bytes = b"hepta.objective.explicit-abstain.v1\0".to_vec();
                bytes.extend_from_slice(admission.intent_digest.as_array());
                bytes.extend_from_slice(compile.objective.semantic_digest.as_array());
                bytes.extend_from_slice(body.run_id.as_bytes());
                Ok(Digest32::of_bytes(&bytes))
            }
        }
    }
}

pub fn authbus_objective_claims(
    owner: &codex_hepta_contracts::AgentId,
    request: &AuthBusObjectiveIngress,
) -> Result<SignedMessageClaims, AgentdError> {
    let identity_scope = objective_scope_for_agent(owner);
    let payload = serde_json::to_vec(&request.body)?;
    Ok(SignedMessageClaims {
        issuer_id: StableId::new(&request.issuer_id)
            .map_err(|error| objective_invalid(&format!("issuer: {error}")))?,
        key_epoch: Generation::new(request.key_epoch)
            .map_err(|error| objective_invalid(&format!("key epoch: {error}")))?,
        message_id: StableId::new(&request.message_id)
            .map_err(|error| objective_invalid(&format!("message id: {error}")))?,
        subject_id: StableId::new(owner.as_str())
            .map_err(|error| objective_invalid(&format!("subject: {error}")))?,
        scope_digest: identity_scope,
        payload_digest: Digest32::of_bytes(&payload),
        sequence: request.sequence,
        expires_at_ms: request.expires_at_ms,
    })
}

pub(crate) async fn submit(
    state: &AgentdState,
    request: AuthBusObjectiveIngress,
) -> Result<AuthBusObjectiveStatus, AgentdError> {
    authbus_ingress::require_ready(state)?;
    let objective = attached(state)?;
    let authbus = authbus_ingress::attached(state)?;
    let trust = authbus.trust(state)?;
    let issuer = trust.issuer()?;
    if issuer.revoked || !objective.permits_issuer(&issuer.issuer_id) {
        return Err(objective_invalid("issuer is revoked or not registered for Objective ingress"));
    }
    let payload = objective_payload(state.identity(), &request.body)?;
    let now = authbus_ingress::now_ms()?;
    if request.expires_at_ms <= now || request.expires_at_ms.saturating_sub(now) > 300_000 {
        return Err(objective_invalid("message expiry must be within five minutes"));
    }
    let message = SignedMessage {
        claims: authbus_objective_claims(&state.identity().agent_id, &request)?,
        signature: hex_bytes(&request.signature_hex)?,
    };
    let status = authbus
        .evidence
        .enqueue_authbus_message(
            &issuer,
            &message,
            objective.subject(),
            objective.scope(),
            &payload,
        )
        .await
        .map_err(|error| objective_invalid(&error.to_string()))?;
    map_status(status)
}

pub(crate) async fn status(
    state: &AgentdState,
    delivery_id: String,
) -> Result<AuthBusObjectiveStatus, AgentdError> {
    let objective = attached(state)?;
    let authbus = authbus_ingress::attached(state)?;
    let delivery_id = Digest32::from_str(&delivery_id)
        .map_err(|_| objective_invalid("invalid delivery id"))?;
    let status = authbus
        .evidence
        .authbus_delivery_status(delivery_id)
        .await
        .map_err(|error| objective_invalid(&error.to_string()))?;
    if status.subject_id != *objective.subject() || status.scope_digest != objective.scope() {
        return Err(objective_invalid("delivery belongs to another route"));
    }
    map_status(status)
}

pub(crate) fn attached(state: &AgentdState) -> Result<std::sync::Arc<ObjectiveIngressHost>, AgentdError> {
    state
        .objective_ingress
        .get()
        .cloned()
        .ok_or_else(|| objective_invalid("no owner Objective profile is configured"))
}

pub(crate) fn objective_payload(
    identity: &AgentdIdentity,
    body: &AuthBusObjectiveBody,
) -> Result<Vec<u8>, AgentdError> {
    if body.spawn_generation != identity.spawn_generation
        || body.objective_revision == 0
        || body.authority_epoch == 0
        || body.source_envelope_json.is_empty()
        || body.source_envelope_json.len() > PRODUCT_SOURCE_JSON_BYTES
    {
        return Err(objective_invalid(
            "generation, revision, authority or source bound is invalid",
        ));
    }
    StableId::new(&body.run_id)
        .map_err(|error| objective_invalid(&format!("run id: {error}")))?;
    for (digest, field) in [
        (&body.runtime_body_digest, "runtime body"),
        (&body.preference_state_digest, "preference state"),
        (&body.model_tuple_digest, "model tuple"),
        (&body.prompt_registry_digest, "prompt registry"),
        (&body.artifact_set_digest, "artifact set"),
    ] {
        parse_digest(digest, field)?;
    }
    let bytes = serde_json::to_vec(body)?;
    if bytes.len() > PRODUCT_BODY_JSON_BYTES {
        return Err(objective_invalid("encoded Objective body exceeds 48 KiB"));
    }
    Ok(bytes)
}

fn recover_active_runs(
    identity: &AgentdIdentity,
    now_ms: u64,
    ledger: &DurableLedger,
    coordinator: &mut AgentRunCoordinator,
) -> Result<(), AgentdError> {
    for record in ledger
        .records()
        .map_err(|error| objective_invalid(&format!("learning ledger: {error}")))?
    {
        let LedgerEvent::RunStart(publication) = &record.event else {
            continue;
        };
        if publication.runtime_body_digest.is_zero()
            || publication.run_start.generation != identity.spawn_generation
        {
            continue;
        }
        let Some(deadline) = publication.admission.deadline_unix_micros else {
            return Err(objective_invalid(
                "recoverable product RunStart is missing its admitted deadline",
            ));
        };
        if deadline / 1_000 <= now_ms {
            continue;
        }
        let envelope = codex_hepta_intelligence::recover_intelligence_host_envelope_v1(record)
            .map_err(|error| objective_invalid(&format!("RunStart recovery: {error}")))?;
        start_intelligence_run_v1(coordinator, now_ms, &envelope)
            .map_err(|error| objective_invalid(&format!("run recovery: {error}")))?;
    }
    Ok(())
}

fn predecessor_for_record(
    ledger: &DurableLedger,
    record_id: &StableId,
) -> Result<Digest32, AgentdError> {
    let records = ledger
        .records()
        .map_err(|error| objective_invalid(&format!("learning ledger: {error}")))?;
    if let Some(existing) = records
        .iter()
        .find(|record| event_record_id(&record.event) == record_id)
    {
        return Ok(existing.predecessor_chain_digest);
    }
    Ok(records
        .last()
        .map_or(Digest32::ZERO, |record| record.chain_digest))
}


fn event_record_id(event: &LedgerEvent) -> &StableId {
    match event {
        LedgerEvent::RunStart(value) => &value.record_id,
        LedgerEvent::Decision(value) => &value.record_id,
        LedgerEvent::Outcome(value) => &value.record_id,
        LedgerEvent::Credit(value) => &value.record_id,
        LedgerEvent::Revocation(value) => &value.record_id,
    }
}

fn reconcile_witness(
    ledger: &DurableLedger,
    witness: &mut LedgerWitnessStore,
) -> Result<(), AgentdError> {
    let anchor = ledger
        .anchor()
        .map_err(|error| objective_invalid(&format!("learning ledger anchor: {error}")))?;
    match witness.latest() {
        None if anchor.sequence == 0 => Ok(()),
        None if anchor.sequence == 1 => witness
            .persist(anchor)
            .map_err(|error| objective_invalid(&format!("learning witness: {error}"))),
        Some(current) if current == anchor => Ok(()),
        Some(current)
            if current.sequence.checked_add(1) == Some(anchor.sequence)
                && ledger
                    .contains_anchor(current)
                    .map_err(|error| objective_invalid(&format!("learning ledger anchor: {error}")))? =>
        {
            witness
                .persist(anchor)
                .map_err(|error| objective_invalid(&format!("learning witness: {error}")))
        }
        _ => Err(objective_invalid(
            "learning ledger and independent witness differ by more than one append",
        )),
    }
}

fn open_private_state_file(identity: &AgentdIdentity, name: &str) -> Result<File, AgentdError> {
    let path = identity.home_root.join(name);
    #[cfg(unix)]
    {
        use std::os::unix::fs::MetadataExt;
        use std::os::unix::fs::OpenOptionsExt;

        let home = std::fs::metadata(&identity.home_root)?;
        if !home.is_dir() || home.mode() & 0o077 != 0 {
            return Err(objective_invalid("Agent home is not private"));
        }
        if let Ok(meta) = std::fs::symlink_metadata(&path) {
            if !meta.is_file()
                || meta.nlink() != 1
                || meta.uid() != home.uid()
                || meta.mode() & 0o077 != 0
            {
                return Err(objective_invalid("Objective owner state file is not private"));
            }
        }
        let file = OpenOptions::new()
            .create(true)
            .read(true)
            .write(true)
            .mode(0o600)
            .open(&path)?;
        let meta = file.metadata()?;
        if !meta.is_file()
            || meta.nlink() != 1
            || meta.uid() != home.uid()
            || meta.mode() & 0o077 != 0
        {
            return Err(objective_invalid("Objective owner state file changed while opening"));
        }
        Ok(file)
    }
    #[cfg(not(unix))]
    {
        let _ = path;
        Err(objective_invalid(
            "Objective durable owner profile currently requires Unix ownership checks",
        ))
    }
}

fn map_status(status: AuthBusDeliveryStatus) -> Result<AuthBusObjectiveStatus, AgentdError> {
    let state = match status.state {
        AuthBusDeliveryState::Queued => AuthBusObjectiveState::Queued,
        AuthBusDeliveryState::Leased => AuthBusObjectiveState::Leased,
        AuthBusDeliveryState::Acked => AuthBusObjectiveState::Processed,
        AuthBusDeliveryState::Expired => AuthBusObjectiveState::Expired,
        AuthBusDeliveryState::Quarantined => AuthBusObjectiveState::Quarantined,
    };
    Ok(AuthBusObjectiveStatus {
        delivery_id: status.delivery_id.to_string(),
        state,
        delivery_attempts: u32::try_from(status.attempts)
            .map_err(|_| objective_invalid("invalid delivery attempt count"))?,
        acknowledgement_digest: status.acknowledgement.map(|digest| digest.to_string()),
    })
}

pub(crate) fn objective_scope(identity: &AgentdIdentity) -> Digest32 {
    objective_scope_for_agent(&identity.agent_id)
}

fn objective_scope_for_agent(agent: &codex_hepta_contracts::AgentId) -> Digest32 {
    let mut bytes = b"hepta:agentd:signed-objective:v1\0".to_vec();
    bytes.extend_from_slice(agent.as_str().as_bytes());
    Digest32::of_bytes(&bytes)
}

fn ledger_binding(identity: &AgentdIdentity) -> Digest32 {
    let mut bytes = b"hepta.learning-ledger.agent-objective.v1\0".to_vec();
    bytes.extend_from_slice(identity.agent_id.as_str().as_bytes());
    Digest32::of_bytes(&bytes)
}

fn objective_fence(identity: &AgentdIdentity, profile_digest: Digest32) -> Digest32 {
    let mut bytes = b"hepta.agentd.objective-fence.v1\0".to_vec();
    bytes.extend_from_slice(identity.agent_id.as_str().as_bytes());
    bytes.extend_from_slice(&identity.spawn_generation.to_be_bytes());
    bytes.extend_from_slice(profile_digest.as_array());
    Digest32::of_bytes(&bytes)
}

pub(crate) fn parse_digest(value: &str, field: &'static str) -> Result<Digest32, AgentdError> {
    let digest = Digest32::from_str(value)
        .map_err(|_| objective_invalid(&format!("invalid {field} digest")))?;
    if digest.is_zero() {
        return Err(objective_invalid(&format!("empty {field} digest")));
    }
    Ok(digest)
}

pub(crate) fn objective_invalid(message: &str) -> AgentdError {
    AgentdError::Invalid(format!("Objective ingress: {message}"))
}
