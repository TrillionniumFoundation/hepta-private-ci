//! Signed production objective admission and durable immutable run publication.
//!
//! This path compiles no free text. A registered AuthBus issuer signs one
//! structured objective envelope; Agentd selects a frozen owner-local profile,
//! authenticates the issuer, derives its own generation/fence, atomically
//! persists the publication, and only then exposes the run snapshot to the
//! ephemeral runtime coordinator. No effect authority is granted here.

use std::collections::BTreeMap;
use std::fs::OpenOptions;
use std::path::Path;
use std::str::FromStr;
use std::sync::Mutex;

use codex_hepta_authbus::Error as AuthBusError;
use codex_hepta_authbus::SignedMessage;
use codex_hepta_authbus::SignedMessageClaims;
use codex_hepta_intelligence::ObjectiveRunBindingsV1;
use codex_hepta_intelligence::ObjectiveRunError;
use codex_hepta_intelligence::compile_and_publish_objective_run_v1;
use codex_hepta_learning_ledger::DurableRunStartJournal;
use codex_hepta_learning_ledger::RunStartAppendDisposition;
use codex_hepta_learning_ledger::RunStartAuthenticationV1;
use codex_hepta_learning_ledger::RunStartObjectiveDispositionV1;
use codex_hepta_learning_ledger::RunStartRecordV1;
use codex_hepta_learning_ledger::RunStartRecovery;
use codex_hepta_objective::ObjectiveAdmissionContextV1;
use codex_hepta_objective::ObjectiveAdmissionProfileV1;
use codex_hepta_objective::ObjectiveSourceAuthenticationV1;
use codex_hepta_objective::decode_admission_profile_json_v1;
use codex_hepta_objective::decode_source_envelope_json_v1;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::Revision;
use codex_hepta_types::StableId;

use crate::AgentRunCoordinator;
use crate::AgentRunError;
use crate::AgentdError;
use crate::AgentdIdentity;
use crate::AgentdState;
use crate::AuthBusObjectiveBody;
use crate::AuthBusObjectiveIngress;
use crate::ObjectiveRunAdmission;
use crate::RunSnapshot;
use crate::RuntimeComposition;
use crate::authbus_ingress;
use crate::authbus_trust::hex_bytes;
use crate::authbus_trust::invalid;
use crate::authbus_trust::read_private_owner_file;

const PRODUCT_SOURCE_JSON_BYTES: usize = 32 * 1024;
const PRODUCT_BODY_JSON_BYTES: usize = 48 * 1024;
const MAX_RUN_START_RECORDS: usize = 4_096;
const RUN_START_DIRECTORY: &str = "objective-run-start-v1";
const RUN_START_FILE: &str = "journal.bin";

pub(crate) enum ObjectiveStartResult {
    Admitted(ObjectiveRunAdmission),
    Conflict {
        run_id: String,
        conflict_digest: String,
    },
}

pub(crate) struct ObjectiveRuntimeHost {
    profile: ObjectiveAdmissionProfileV1,
    profile_digest: Digest32,
    state: Mutex<ObjectiveHostState>,
}

struct ObjectiveHostState {
    journal: DurableRunStartJournal,
    coordinator_generation: Option<u64>,
    coordinator: Option<AgentRunCoordinator>,
    highest_sequences: BTreeMap<(String, u64), u64>,
}

impl ObjectiveRuntimeHost {
    pub(crate) fn open(
        identity: &AgentdIdentity,
        profile_file: &Path,
    ) -> Result<Self, AgentdError> {
        let bytes = read_private_owner_file(profile_file, identity, 262_144)?;
        let profile = decode_admission_profile_json_v1(&bytes)
            .map_err(|error| invalid(&format!("objective profile: {error}")))?;
        if profile.allowed_trusted_source_identities.is_empty() {
            return Err(invalid(
                "objective profile must register at least one signed adapter identity",
            ));
        }
        let profile_digest = profile
            .digest()
            .map_err(|error| invalid(&format!("objective profile: {error}")))?;
        let journal = open_run_start_journal(identity, profile_digest)?;
        let highest_sequences = replay_frontier(&journal)?;
        Ok(Self {
            profile,
            profile_digest,
            state: Mutex::new(ObjectiveHostState {
                journal,
                coordinator_generation: None,
                coordinator: None,
                highest_sequences,
            }),
        })
    }

    pub(crate) fn reconcile(
        &self,
        agentd: &AgentdState,
        current_generation: u64,
        now_ms: u64,
    ) -> Result<(), AgentdError> {
        let trust = authbus_ingress::attached(agentd)?.trust(agentd)?;
        let mut state = self
            .state
            .lock()
            .map_err(|_| AgentdError::Protocol("objective runtime mutex is poisoned".to_string()))?;
        ensure_coordinator(
            &mut state,
            agentd.identity(),
            self.profile_digest,
            &trust,
            current_generation,
            now_ms,
        )
    }

    pub(crate) fn submit(
        &self,
        agentd: &AgentdState,
        request: AuthBusObjectiveIngress,
        current_generation: u64,
    ) -> Result<ObjectiveStartResult, AgentdError> {
        authbus_ingress::require_ready(agentd)?;
        let now_ms = authbus_ingress::now_ms()?;
        let payload = objective_payload(agentd.identity(), &request.body)?;
        if request.expires_at_ms <= now_ms || request.expires_at_ms.saturating_sub(now_ms) > 300_000
        {
            return Err(invalid("objective expiry must be within five minutes"));
        }

        let authbus = authbus_ingress::attached(agentd)?;
        let trust = authbus.trust(agentd)?;
        let issuer = trust.issuer()?;
        let message = SignedMessage {
            claims: objective_claims(agentd.identity(), &request, &payload)?,
            signature: hex_bytes(&request.signature_hex)?,
        };
        let authenticated = message
            .authenticate(
                &issuer,
                objective_scope(agentd.identity()),
                Digest32::of_bytes(&payload),
                now_ms,
            )
            .map_err(|error| invalid(&format!("objective signature: {error}")))?;

        let source = decode_source_envelope_json_v1(request.body.source_envelope_json.as_bytes())
            .map_err(|error| invalid(&format!("objective source: {error}")))?;
        let now_unix_micros = now_ms
            .checked_mul(1_000)
            .ok_or_else(|| invalid("objective host clock overflow"))?;
        let context = ObjectiveAdmissionContextV1 {
            revision: Revision::new(request.body.objective_revision)
                .map_err(|error| invalid(&format!("objective revision: {error}")))?,
            now_unix_micros,
            selected_profile_digest: self.profile_digest,
            source_authentication: ObjectiveSourceAuthenticationV1::AuthorizedAdapter {
                source_identity: issuer.issuer_id.clone(),
                source_digest: source.structured_intent.provenance.source_digest,
            },
        };

        let runtime_body_digest =
            parse_digest(&request.body.runtime_body_digest, "runtime body")?;
        let preference_state_digest =
            parse_digest(&request.body.preference_state_digest, "preference state")?;
        let model_tuple_digest = parse_digest(&request.body.model_tuple_digest, "model tuple")?;
        let prompt_registry_digest =
            parse_digest(&request.body.prompt_registry_digest, "prompt registry")?;
        let artifact_set_digest =
            parse_digest(&request.body.artifact_set_digest, "artifact set")?;
        let run_id = StableId::new(&request.body.run_id)
            .map_err(|error| invalid(&format!("objective run id: {error}")))?;
        let authentication = RunStartAuthenticationV1 {
            issuer_id: authenticated.claims().issuer_id.clone(),
            key_epoch: authenticated.claims().key_epoch.get(),
            message_id: authenticated.claims().message_id.clone(),
            sequence: authenticated.claims().sequence,
            expires_at_ms: authenticated.claims().expires_at_ms,
            scope_digest: authenticated.claims().scope_digest,
            signed_body_digest: authenticated.claims().payload_digest,
            signature: message.signature,
        };

        let mut state = self
            .state
            .lock()
            .map_err(|_| AgentdError::Protocol("objective runtime mutex is poisoned".to_string()))?;
        ensure_coordinator(
            &mut state,
            agentd.identity(),
            self.profile_digest,
            &trust,
            current_generation,
            now_ms,
        )?;
        require_replay_admission(&state, &authentication, &run_id)?;

        let expected_run_start_head = state.journal.head_digest();
        let published = match compile_and_publish_objective_run_v1(
            &source,
            &self.profile,
            &context,
            ObjectiveRunBindingsV1 {
                authentication,
                run_id: run_id.clone(),
                runtime_body_digest,
                preference_state_digest,
                model_tuple_digest,
                prompt_registry_digest,
                artifact_set_digest,
                authority_epoch: request.body.authority_epoch,
                generation: current_generation,
                fence_digest: objective_fence(agentd.identity(), current_generation),
                expected_run_start_head,
            },
            &mut state.journal,
        ) {
            Ok(published) => published,
            Err(ObjectiveRunError::Conflict(conflict)) => {
                return Ok(ObjectiveStartResult::Conflict {
                    run_id: request.body.run_id,
                    conflict_digest: conflict.conflict_digest.to_string(),
                });
            }
            Err(error) => return Err(invalid(&format!("objective publication: {error}"))),
        };

        let record = state
            .journal
            .get(&run_id)
            .map_err(store_error)?
            .cloned()
            .ok_or_else(|| invalid("durable objective publication disappeared"))?;
        let key = (
            record.authentication.issuer_id.to_string(),
            record.authentication.key_epoch,
        );
        state
            .highest_sequences
            .entry(key)
            .and_modify(|value| *value = (*value).max(record.authentication.sequence))
            .or_insert(record.authentication.sequence);

        authbus_ingress::require_ready(agentd)?;
        let current = authbus.trust(agentd)?;
        if !authentication_is_current(
            &record,
            &current,
            agentd.identity(),
            authbus_ingress::now_ms()?,
        )? {
            return Err(invalid(
                "objective trust changed after durable publication; retry after reconciliation",
            ));
        }
        ensure_runtime_record(
            state
                .coordinator
                .as_mut()
                .ok_or_else(|| invalid("objective runtime coordinator is unavailable"))?,
            &record,
            now_ms,
        )?;

        Ok(ObjectiveStartResult::Admitted(ObjectiveRunAdmission {
            run_id: published.run_start.run_id.to_string(),
            objective_digest: published.run_start.objective_digest.to_string(),
            hard_constraint_digest: published.run_start.hard_constraint_digest.to_string(),
            publication_digest: published.publication.record_digest.to_string(),
            chain_digest: published.publication.chain_digest.to_string(),
            disposition: match record.disposition {
                RunStartObjectiveDispositionV1::Compiled => "compiled",
                RunStartObjectiveDispositionV1::ExplicitAbstain => "explicit_abstain",
            }
            .to_string(),
            idempotent: published.publication.disposition
                == RunStartAppendDisposition::IdempotentReplay,
        }))
    }
}

fn objective_payload(
    identity: &AgentdIdentity,
    body: &AuthBusObjectiveBody,
    current_generation: u64,
) -> Result<Vec<u8>, AgentdError> {
    if body.spawn_generation != identity.spawn_generation
        || body.objective_revision == 0
        || body.authority_epoch == 0
        || current_generation == 0
        || body.source_envelope_json.is_empty()
        || body.source_envelope_json.len() > PRODUCT_SOURCE_JSON_BYTES
    {
        return Err(invalid(
            "objective generation, revision, authority or source bound is invalid",
        ));
    }
    StableId::new(&body.run_id).map_err(|error| invalid(&format!("objective run id: {error}")))?;
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
        return Err(invalid("encoded objective body exceeds 48 KiB"));
    }
    Ok(bytes)
}

fn objective_claims(
    identity: &AgentdIdentity,
    request: &AuthBusObjectiveIngress,
    payload: &[u8],
) -> Result<SignedMessageClaims, AgentdError> {
    Ok(SignedMessageClaims {
        issuer_id: StableId::new(&request.issuer_id)
            .map_err(|error| invalid(&format!("objective issuer: {error}")))?,
        key_epoch: Generation::new(request.key_epoch)
            .map_err(|error| invalid(&format!("objective key epoch: {error}")))?,
        message_id: StableId::new(&request.message_id)
            .map_err(|error| invalid(&format!("objective message id: {error}")))?,
        subject_id: StableId::new(identity.agent_id.as_str())
            .map_err(|error| invalid(&format!("objective subject: {error}")))?,
        scope_digest: objective_scope(identity),
        payload_digest: Digest32::of_bytes(payload),
        sequence: request.sequence,
        expires_at_ms: request.expires_at_ms,
    })
}

fn objective_scope(identity: &AgentdIdentity) -> Digest32 {
    let mut bytes = b"hepta:agentd:signed-objective:v1\0".to_vec();
    bytes.extend_from_slice(identity.agent_id.as_str().as_bytes());
    Digest32::of_bytes(&bytes)
}

fn objective_fence(identity: &AgentdIdentity, current_generation: u64) -> Digest32 {
    let mut bytes = b"hepta:agentd:objective-fence:v1\0".to_vec();
    bytes.extend_from_slice(identity.agent_id.as_str().as_bytes());
    bytes.extend_from_slice(&identity.spawn_generation.to_be_bytes());
    bytes.extend_from_slice(&current_generation.to_be_bytes());
    Digest32::of_bytes(&bytes)
}

fn parse_digest(value: &str, field: &'static str) -> Result<Digest32, AgentdError> {
    let digest =
        Digest32::from_str(value).map_err(|_| invalid(&format!("invalid {field} digest")))?;
    if digest.is_zero() {
        return Err(invalid(&format!("empty {field} digest")));
    }
    Ok(digest)
}

fn run_start_binding(identity: &AgentdIdentity, profile_digest: Digest32) -> Digest32 {
    let mut bytes = b"hepta:agentd:objective-run-start-owner:v1\0".to_vec();
    bytes.extend_from_slice(identity.agent_id.as_str().as_bytes());
    bytes.extend_from_slice(profile_digest.as_array());
    Digest32::of_bytes(&bytes)
}

fn open_run_start_journal(
    identity: &AgentdIdentity,
    profile_digest: Digest32,
) -> Result<DurableRunStartJournal, AgentdError> {
    let root = identity.home_root.join(RUN_START_DIRECTORY);
    prepare_private_directory(&root)?;
    let path = root.join(RUN_START_FILE);
    if path.exists() {
        let metadata = std::fs::symlink_metadata(&path)?;
        if !metadata.is_file() || metadata.file_type().is_symlink() {
            return Err(invalid("objective run-start journal must be a regular file"));
        }
    }
    let mut options = OpenOptions::new();
    options.read(true).write(true).create(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.mode(0o600);
    }
    let file = options.open(path)?;
    if file.metadata()?.len() == 0 {
        DurableRunStartJournal::create(
            file,
            run_start_binding(identity, profile_digest),
            MAX_RUN_START_RECORDS,
        )
        .map_err(store_error)
    } else {
        DurableRunStartJournal::recover(
            file,
            run_start_binding(identity, profile_digest),
            MAX_RUN_START_RECORDS,
            RunStartRecovery::Unacknowledged,
        )
        .map_err(store_error)
    }
}

fn prepare_private_directory(path: &Path) -> Result<(), AgentdError> {
    std::fs::create_dir_all(path)?;
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        std::fs::set_permissions(path, std::fs::Permissions::from_mode(0o700))?;
    }
    let metadata = std::fs::symlink_metadata(path)?;
    if !metadata.is_dir() || metadata.file_type().is_symlink() {
        return Err(invalid("objective run-start root must be a real directory"));
    }
    Ok(())
}

fn replay_frontier(
    journal: &DurableRunStartJournal,
) -> Result<BTreeMap<(String, u64), u64>, AgentdError> {
    let mut highest = BTreeMap::new();
    for record in journal.records().map_err(store_error)? {
        let key = (
            record.authentication.issuer_id.to_string(),
            record.authentication.key_epoch,
        );
        highest
            .entry(key)
            .and_modify(|value| *value = (*value).max(record.authentication.sequence))
            .or_insert(record.authentication.sequence);
    }
    Ok(highest)
}

fn require_replay_admission(
    state: &ObjectiveHostState,
    authentication: &RunStartAuthenticationV1,
    run_id: &StableId,
) -> Result<(), AgentdError> {
    let key = (authentication.issuer_id.to_string(), authentication.key_epoch);
    let Some(highest) = state.highest_sequences.get(&key) else {
        return Ok(());
    };
    if authentication.sequence > *highest {
        return Ok(());
    }
    let exact = state
        .journal
        .records()
        .map_err(store_error)?
        .into_iter()
        .any(|record| {
            record.authentication == *authentication && record.snapshot.run_id == *run_id
        });
    if exact {
        Ok(())
    } else {
        Err(invalid("objective signed sequence was already consumed"))
    }
}

fn ensure_coordinator(
    state: &mut ObjectiveHostState,
    identity: &AgentdIdentity,
    profile_digest: Digest32,
    trust: &TextTrust,
    current_generation: u64,
    now_ms: u64,
) -> Result<(), AgentdError> {
    if state.coordinator_generation == Some(current_generation) {
        return Ok(());
    }
    let fence = objective_fence(identity, current_generation);
    let mut coordinator = AgentRunCoordinator::compose_runtime(RuntimeComposition {
        agent_id: identity.agent_id.as_str().to_string(),
        supervisor_generation: current_generation,
        agentd_generation: current_generation,
        configuration_digest: profile_digest.to_string(),
        ports_digest: Digest32::of_bytes(b"agentd.objective.start.v1").to_string(),
        fence_digest: fence.to_string(),
    })
    .map_err(run_error)?;
    for record in state.journal.records().map_err(store_error)? {
        if record.snapshot.generation != current_generation || record.snapshot.fence_digest != fence
        {
            continue;
        }
        if authentication_is_current(record, trust, identity, now_ms)? {
            ensure_runtime_record(&mut coordinator, record, now_ms)?;
        }
    }
    state.coordinator = Some(coordinator);
    state.coordinator_generation = Some(current_generation);
    Ok(())
}

fn ensure_runtime_record(
    coordinator: &mut AgentRunCoordinator,
    record: &RunStartRecordV1,
    now_ms: u64,
) -> Result<(), AgentdError> {
    if record.disposition == RunStartObjectiveDispositionV1::ExplicitAbstain {
        return Ok(());
    }
    let deadline_ms = record
        .admission
        .deadline_unix_micros
        .checked_add(999)
        .map(|value| value / 1_000)
        .ok_or_else(|| invalid("objective deadline overflow"))?;
    if deadline_ms <= now_ms {
        return Ok(());
    }
    coordinator
        .start_run(
            now_ms,
            RunSnapshot {
                run_id: record.snapshot.run_id.to_string(),
                request_digest: record.admission.admitted_source_digest.to_string(),
                objective_digest: record.snapshot.objective_digest.to_string(),
                body_digest: record.runtime_body_digest.to_string(),
                artifact_set_digest: record.snapshot.artifact_set_digest.to_string(),
                authority_epoch: record.snapshot.authority_epoch,
                generation: record.snapshot.generation,
                fence_digest: record.snapshot.fence_digest.to_string(),
                deadline_ms,
            },
        )
        .map(|_| ())
        .map_err(run_error)
}

fn authentication_is_current(
    record: &RunStartRecordV1,
    trust: &TextTrust,
    identity: &AgentdIdentity,
    now_ms: u64,
) -> Result<bool, AgentdError> {
    let issuer = trust.issuer()?;
    let auth = &record.authentication;
    let key_epoch = Generation::new(auth.key_epoch)
        .map_err(|error| invalid(&format!("objective key epoch: {error}")))?;
    let message = SignedMessage {
        claims: SignedMessageClaims {
            issuer_id: auth.issuer_id.clone(),
            key_epoch,
            message_id: auth.message_id.clone(),
            subject_id: StableId::new(identity.agent_id.as_str())
                .map_err(|error| invalid(&format!("objective subject: {error}")))?,
            scope_digest: auth.scope_digest,
            payload_digest: auth.signed_body_digest,
            sequence: auth.sequence,
            expires_at_ms: auth.expires_at_ms,
        },
        signature: auth.signature,
    };
    match message.authenticate(&issuer, objective_scope(identity), auth.signed_body_digest, now_ms) {
        Ok(_) => Ok(true),
        Err(AuthBusError::Expired | AuthBusError::Revoked | AuthBusError::IssuerMismatch) => {
            Ok(false)
        }
        Err(error) => Err(invalid(&format!(
            "durable objective authentication is invalid: {error}"
        ))),
    }
}

fn store_error(error: codex_hepta_learning_ledger::RunStartStoreError) -> AgentdError {
    invalid(&format!("objective run-start journal: {error}"))
}

fn run_error(error: AgentRunError) -> AgentdError {
    invalid(&format!("objective runtime admission: {error:?}"))
}

#[cfg(test)]
#[path = "objective_runtime_tests.rs"]
mod tests;
