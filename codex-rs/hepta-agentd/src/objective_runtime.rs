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

use crate::AgentdError;
use crate::AgentdIdentity;
use crate::AgentdState;
use crate::AuthBusObjectiveBody;
use crate::AuthBusObjectiveIngress;
use crate::ObjectiveRunAdmission;
use crate::authbus_ingress;
use crate::authbus_trust::TextTrust;
use crate::authbus_trust::hex_bytes;
use crate::authbus_trust::invalid;
use crate::authbus_trust::read_private_owner_file;

const MAX_RUN_START_RECORDS: usize = 4_096;
const RUN_START_DIRECTORY: &str = "objective-run-start-v1";
const RUN_START_FILE: &str = "journal.bin";

#[path = "objective_history.rs"]
mod history;

#[path = "objective_submission.rs"]
mod submission;

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
    highest_sequences: BTreeMap<(String, u64), u64>,
    notes_cursor: usize,
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
                highest_sequences,
                notes_cursor: 0,
            }),
        })
    }

    pub(crate) fn reconcile(
        &self,
        agentd: &AgentdState,
        current_generation: u64,
        now_ms: u64,
    ) -> Result<(), AgentdError> {
        // Startup attaches the durable service before App Server readiness.
        // Runtime projection is deferred until the daemon owner admits runs.
        if !agentd.objective_admission_ready()? {
            return Ok(());
        }
        let trust = authbus_ingress::attached(agentd)?.trust(agentd)?;
        let state = self.state.lock().map_err(|_| {
            AgentdError::Protocol("objective runtime mutex is poisoned".to_string())
        })?;
        let fence = objective_fence(agentd.identity(), current_generation);
        for record in state.journal.records().map_err(store_error)? {
            if record.snapshot.generation != current_generation
                || record.snapshot.fence_digest != fence
                || record.disposition != RunStartObjectiveDispositionV1::Compiled
                || record.admission.deadline_unix_micros.div_ceil(1_000) <= now_ms
            {
                continue;
            }
            if authentication_is_current(record, &trust, agentd.identity(), now_ms)? {
                if agentd.canonical_intelligence_enabled() {
                    // A RunStart publication predates the seven-owner handoff.
                    // Until that exact handoff is durably recovered, startup
                    // must wait for the authenticated ObjectiveStart retry
                    // rather than silently entering the compatibility path.
                    continue;
                }
                agentd.start_current_run_start(&state.journal, &record.snapshot.run_id)?;
            }
        }
        Ok(())
    }

    pub(crate) async fn reconcile_notes(&self, agentd: &AgentdState) -> Result<(), AgentdError> {
        if agentd.notes_objective.get().is_none() {
            return Ok(());
        }
        let records = {
            let mut state = self
                .state
                .lock()
                .map_err(|_| invalid("objective runtime mutex poisoned"))?;
            let records = state.journal.records().map_err(store_error)?;
            let end = (state.notes_cursor + 16).min(records.len());
            let batch = records[state.notes_cursor.min(records.len())..end]
                .iter()
                .map(|record| (**record).clone())
                .collect::<Vec<_>>();
            state.notes_cursor = if end == records.len() { 0 } else { end };
            batch
        };
        for record in records {
            agentd.execute_notes_objective(&record).await?;
        }
        Ok(())
    }
}

include!("objective_claims.rs");

fn objective_fence(identity: &AgentdIdentity, current_generation: u64) -> Digest32 {
    let mut bytes = b"hepta:agentd:objective-fence:v1\0".to_vec();
    bytes.extend_from_slice(identity.agent_id.as_str().as_bytes());
    bytes.extend_from_slice(&identity.spawn_generation.to_be_bytes());
    bytes.extend_from_slice(&current_generation.to_be_bytes());
    Digest32::of_bytes(&bytes)
}

fn parse_digest(value: &str, field: &'static str) -> Result<Digest32, AgentdError> {
    codex_hepta_authority_client::parse_objective_digest(value, field)
        .map_err(objective_claims_error)
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
            return Err(invalid(
                "objective run-start journal must be a regular file",
            ));
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
        let journal = DurableRunStartJournal::create(
            file,
            run_start_binding(identity, profile_digest),
            MAX_RUN_START_RECORDS,
        )
        .map_err(store_error)?;
        sync_run_start_directory(&root)?;
        Ok(journal)
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

#[cfg(unix)]
fn sync_run_start_directory(path: &Path) -> Result<(), AgentdError> {
    std::fs::File::open(path)?.sync_all()?;
    Ok(())
}

#[cfg(not(unix))]
fn sync_run_start_directory(_path: &Path) -> Result<(), AgentdError> {
    // The selected non-Unix host profile must independently qualify directory-entry
    // durability. The journal file itself is synchronized before this boundary.
    Ok(())
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
    let mut highest: BTreeMap<(String, u64), u64> = BTreeMap::new();
    for (authentication, _) in journal.authentication_records().map_err(store_error)? {
        let key = (
            authentication.issuer_id.to_string(),
            authentication.key_epoch,
        );
        highest
            .entry(key)
            .and_modify(|value| *value = (*value).max(authentication.sequence))
            .or_insert(authentication.sequence);
    }
    Ok(highest)
}

fn require_replay_admission(
    state: &ObjectiveHostState,
    authentication: &RunStartAuthenticationV1,
    run_id: &StableId,
) -> Result<(), AgentdError> {
    let key = (
        authentication.issuer_id.to_string(),
        authentication.key_epoch,
    );
    let Some(highest) = state.highest_sequences.get(&key) else {
        return Ok(());
    };
    if authentication.sequence > *highest {
        return Ok(());
    }
    let exact = state
        .journal
        .authentication_records()
        .map_err(store_error)?
        .into_iter()
        .any(|(record_authentication, record_run_id)| {
            record_authentication == authentication && record_run_id == run_id
        });
    if exact {
        Ok(())
    } else {
        Err(invalid("objective signed sequence was already consumed"))
    }
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
    match message.authenticate(
        &issuer,
        objective_scope(identity),
        auth.signed_body_digest,
        now_ms,
    ) {
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

#[cfg(test)]
#[path = "objective_runtime_tests.rs"]
mod tests;
