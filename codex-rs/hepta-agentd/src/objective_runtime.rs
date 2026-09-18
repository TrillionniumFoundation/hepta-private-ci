//! Signed production objective admission and durable immutable run publication.
//!
//! This path compiles no free text. A registered AuthBus issuer signs one
//! structured objective envelope; Agentd selects a frozen owner-local profile,
//! authenticates the issuer, derives its own generation/fence, atomically
//! persists the publication, and only then exposes the run snapshot to the
//! ephemeral runtime coordinator. No effect authority is granted here.

use std::collections::BTreeMap;
use std::fs::File;
use std::fs::OpenOptions;
use std::io::Read;
use std::io::Write;
use std::path::Path;
use std::path::PathBuf;
use std::str::FromStr;
use std::sync::Mutex;

use codex_hepta_authbus::SignedMessage;
use codex_hepta_authbus::SignedMessageClaims;
use codex_hepta_objective::CompileDisposition;
use codex_hepta_objective::ObjectiveAdmissionContextV1;
use codex_hepta_objective::ObjectiveAdmissionProfileV1;
use codex_hepta_objective::ObjectiveRunPublicationV1;
use codex_hepta_objective::ObjectiveSourceAuthenticationV1;
use codex_hepta_objective::RunStartBindingsV1;
use codex_hepta_objective::RunStartSnapshotV1;
use codex_hepta_objective::admit_and_compile_objective_v1;
use codex_hepta_objective::decode_admission_profile_json_v1;
use codex_hepta_objective::decode_source_envelope_json_v1;
use codex_hepta_objective::objective_run_publication_digest_v1;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::Revision;
use codex_hepta_types::StableId;
use serde::Deserialize;
use serde::Serialize;

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
const MAX_STORED_RUNS: usize = 1_024;
const STORE_SCHEMA_VERSION: u32 = 1;

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
    root: PathBuf,
    state: Mutex<ObjectiveHostState>,
}

struct ObjectiveHostState {
    coordinator: AgentRunCoordinator,
    highest_sequences: BTreeMap<(String, u64), u64>,
}

impl ObjectiveRuntimeHost {
    pub(crate) fn open(
        identity: &AgentdIdentity,
        profile_file: &Path,
        now_ms: u64,
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
        let root = identity.home_root.join("objective-runs-v1");
        prepare_store(&root)?;
        let composition = RuntimeComposition {
            agent_id: identity.agent_id.as_str().to_string(),
            supervisor_generation: identity.spawn_generation,
            agentd_generation: identity.spawn_generation,
            configuration_digest: profile_digest.to_string(),
            ports_digest: Digest32::of_bytes(b"hepta.agentd.objective-start.v1").to_string(),
        };
        let mut state = ObjectiveHostState {
            coordinator: AgentRunCoordinator::compose_runtime(composition)
                .map_err(runtime_error)?,
            highest_sequences: BTreeMap::new(),
        };
        recover_store(&root, now_ms, &mut state)?;
        Ok(Self {
            profile,
            profile_digest,
            root,
            state: Mutex::new(state),
        })
    }

    pub(crate) fn submit(
        &self,
        agentd: &AgentdState,
        request: AuthBusObjectiveIngress,
        current_generation: u64,
    ) -> Result<ObjectiveStartResult, AgentdError> {
        authbus_ingress::require_ready(agentd)?;
        let now_ms = authbus_ingress::now_ms()?;
        let payload = objective_payload(agentd.identity(), &request.body, current_generation)?;
        if request.expires_at_ms <= now_ms || request.expires_at_ms.saturating_sub(now_ms) > 300_000 {
            return Err(invalid("objective expiry must be within five minutes"));
        }
        let authbus = authbus_ingress::attached(agentd)?;
        let trust = authbus.trust(agentd)?;
        let issuer = trust.issuer()?;
        let claims = objective_claims(agentd.identity(), &request, &payload)?;
        let message = SignedMessage {
            claims,
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
        let source_digest = source.structured_intent.provenance.source_digest;
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
                source_digest,
            },
        };
        let outcome = admit_and_compile_objective_v1(&source, &self.profile, &context)
            .map_err(|error| invalid(&format!("objective admission {}: {error}", error.code())))?;
        let admission = outcome.receipt;
        let compiled = match outcome.compile_result {
            Ok(compiled) => compiled,
            Err(conflict) => {
                return Ok(ObjectiveStartResult::Conflict {
                    run_id: request.body.run_id,
                    conflict_digest: conflict.conflict_digest.to_string(),
                });
            }
        };
        let run_id = StableId::new(&request.body.run_id)
            .map_err(|error| invalid(&format!("objective run id: {error}")))?;
        let publication = ObjectiveRunPublicationV1::new(
            admission,
            compiled,
            RunStartBindingsV1 {
                run_id,
                preference_state_digest: parse_digest(
                    &request.body.preference_state_digest,
                    "preference state",
                )?,
                model_tuple_digest: parse_digest(&request.body.model_tuple_digest, "model tuple")?,
                prompt_registry_digest: parse_digest(
                    &request.body.prompt_registry_digest,
                    "prompt registry",
                )?,
                artifact_set_digest: parse_digest(&request.body.artifact_set_digest, "artifact set")?,
                authority_epoch: request.body.authority_epoch,
                generation: current_generation,
                fence_digest: objective_fence(agentd.identity(), current_generation),
            },
        )
        .map_err(|error| invalid(&format!("objective run snapshot: {error}")))?;
        let deadline_ms = publication
            .admission
            .deadline_unix_micros
            .ok_or_else(|| invalid("production objective requires an explicit deadline"))
            .and_then(deadline_micros_to_ms)?;
        let publication_json = publication
            .canonical_json()
            .map_err(|error| invalid(&format!("objective publication: {error}")))?;
        let publication_digest = objective_run_publication_digest_v1(&publication_json);
        let run_start_digest = publication
            .run_start
            .semantic_digest()
            .map_err(|error| invalid(&format!("run snapshot: {error}")))?;
        let runtime_body_digest = parse_digest(&request.body.runtime_body_digest, "runtime body")?;
        let disposition = disposition_name(publication.compile.disposition);
        let stored = StoredObjectiveRun {
            schema_version: STORE_SCHEMA_VERSION,
            issuer_id: authenticated.receipt().issuer_id.to_string(),
            key_epoch: authenticated.receipt().key_epoch.get(),
            message_id: authenticated.receipt().message_id.to_string(),
            sequence: authenticated.receipt().sequence,
            signed_body_digest: Digest32::of_bytes(&payload).to_string(),
            run_id: publication.run_start.run_id.to_string(),
            admitted_source_digest: publication.admission.admitted_source_digest.to_string(),
            objective_digest: publication.run_start.objective_digest.to_string(),
            hard_constraint_digest: publication.run_start.hard_constraint_digest.to_string(),
            preference_state_digest: publication.run_start.preference_state_digest.to_string(),
            model_tuple_digest: publication.run_start.model_tuple_digest.to_string(),
            prompt_registry_digest: publication.run_start.prompt_registry_digest.to_string(),
            artifact_set_digest: publication.run_start.artifact_set_digest.to_string(),
            authority_epoch: publication.run_start.authority_epoch,
            generation: publication.run_start.generation,
            fence_digest: publication.run_start.fence_digest.to_string(),
            runtime_body_digest: runtime_body_digest.to_string(),
            deadline_ms,
            disposition: disposition.to_string(),
            run_start_digest: run_start_digest.to_string(),
            publication_digest: publication_digest.to_string(),
            publication_json: String::from_utf8(publication_json)
                .map_err(|_| invalid("objective publication is not UTF-8"))?,
        };

        let mut state = self
            .state
            .lock()
            .map_err(|_| AgentdError::Protocol("objective runtime mutex is poisoned".to_string()))?;
        let result = commit_or_replay(&self.root, &stored, &mut state, now_ms)?;
        authbus_ingress::require_ready(agentd)?;
        Ok(ObjectiveStartResult::Admitted(result))
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
        return Err(invalid("objective generation, revision, authority or source bound is invalid"));
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
    let digest = Digest32::from_str(value)
        .map_err(|_| invalid(&format!("invalid {field} digest")))?;
    if digest.is_zero() {
        return Err(invalid(&format!("empty {field} digest")));
    }
    Ok(digest)
}

fn deadline_micros_to_ms(value: u64) -> Result<u64, AgentdError> {
    value
        .checked_add(999)
        .map(|micros| micros / 1_000)
        .ok_or_else(|| invalid("objective deadline overflow"))
}

fn disposition_name(value: CompileDisposition) -> &'static str {
    match value {
        CompileDisposition::Compiled => "compiled",
        CompileDisposition::ExplicitAbstain => "explicit_abstain",
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct StoredObjectiveRun {
    schema_version: u32,
    issuer_id: String,
    key_epoch: u64,
    message_id: String,
    sequence: u64,
    signed_body_digest: String,
    run_id: String,
    admitted_source_digest: String,
    objective_digest: String,
    hard_constraint_digest: String,
    preference_state_digest: String,
    model_tuple_digest: String,
    prompt_registry_digest: String,
    artifact_set_digest: String,
    authority_epoch: u64,
    generation: u64,
    fence_digest: String,
    runtime_body_digest: String,
    deadline_ms: u64,
    disposition: String,
    run_start_digest: String,
    publication_digest: String,
    publication_json: String,
}

impl StoredObjectiveRun {
    fn run_snapshot(&self) -> RunSnapshot {
        RunSnapshot {
            run_id: self.run_id.clone(),
            request_digest: self.admitted_source_digest.clone(),
            objective_digest: self.objective_digest.clone(),
            body_digest: self.runtime_body_digest.clone(),
            artifact_set_digest: self.artifact_set_digest.clone(),
            authority_epoch: self.authority_epoch,
            deadline_ms: self.deadline_ms,
        }
    }

    fn admission(&self, idempotent: bool) -> ObjectiveRunAdmission {
        ObjectiveRunAdmission {
            run_id: self.run_id.clone(),
            objective_digest: self.objective_digest.clone(),
            hard_constraint_digest: self.hard_constraint_digest.clone(),
            run_start_digest: self.run_start_digest.clone(),
            publication_digest: self.publication_digest.clone(),
            disposition: self.disposition.clone(),
            idempotent,
        }
    }
}

fn commit_or_replay(
    root: &Path,
    record: &StoredObjectiveRun,
    state: &mut ObjectiveHostState,
    now_ms: u64,
) -> Result<ObjectiveRunAdmission, AgentdError> {
    let path = record_path(root, &record.run_id);
    if path.exists() {
        let existing = read_record(&path)?;
        if existing == *record {
            ensure_runtime_snapshot(&existing, state, now_ms)?;
            return Ok(existing.admission(true));
        }
        return Err(invalid("objective run identity was reused with different semantics"));
    }
    let replay_key = (record.issuer_id.clone(), record.key_epoch);
    if state
        .highest_sequences
        .get(&replay_key)
        .is_some_and(|sequence| *sequence >= record.sequence)
    {
        return Err(invalid("objective signed sequence was already consumed"));
    }
    write_record_atomically(root, &path, record)?;
    state.highest_sequences.insert(replay_key, record.sequence);
    ensure_runtime_snapshot(record, state, now_ms)?;
    Ok(record.admission(false))
}

fn ensure_runtime_snapshot(
    record: &StoredObjectiveRun,
    state: &mut ObjectiveHostState,
    now_ms: u64,
) -> Result<(), AgentdError> {
    if record.disposition == "explicit_abstain" {
        return Ok(());
    }
    state
        .coordinator
        .start_run(now_ms, record.run_snapshot())
        .map(|_| ())
        .map_err(runtime_error)
}

fn recover_store(root: &Path, now_ms: u64, state: &mut ObjectiveHostState) -> Result<(), AgentdError> {
    let mut paths = std::fs::read_dir(root)?
        .collect::<Result<Vec<_>, _>>()?
        .into_iter()
        .map(|entry| entry.path())
        .collect::<Vec<_>>();
    paths.sort();
    let records = paths
        .iter()
        .filter(|path| path.extension().is_some_and(|extension| extension == "json"))
        .count();
    if records > MAX_STORED_RUNS {
        return Err(invalid("objective publication store exceeds retained-run bound"));
    }
    for path in paths {
        if path.extension().is_some_and(|extension| extension == "tmp") {
            let _ = std::fs::remove_file(path);
            continue;
        }
        if !path.extension().is_some_and(|extension| extension == "json") {
            return Err(invalid("objective publication store contains an unknown file"));
        }
        let record = read_record(&path)?;
        validate_record(&record)?;
        let key = (record.issuer_id.clone(), record.key_epoch);
        let current = state.highest_sequences.entry(key).or_insert(0);
        *current = (*current).max(record.sequence);
        if record.deadline_ms > now_ms {
            ensure_runtime_snapshot(&record, state, now_ms)?;
        }
    }
    Ok(())
}

fn validate_record(record: &StoredObjectiveRun) -> Result<(), AgentdError> {
    if record.schema_version != STORE_SCHEMA_VERSION
        || record.key_epoch == 0
        || record.sequence == 0
        || record.authority_epoch == 0
        || record.generation == 0
        || record.deadline_ms == 0
        || !matches!(record.disposition.as_str(), "compiled" | "explicit_abstain")
    {
        return Err(invalid("invalid durable objective record metadata"));
    }
    StableId::new(&record.run_id).map_err(|_| invalid("invalid durable objective run id"))?;
    StableId::new(&record.issuer_id).map_err(|_| invalid("invalid durable objective issuer"))?;
    StableId::new(&record.message_id).map_err(|_| invalid("invalid durable objective message id"))?;
    for (value, field) in [
        (&record.signed_body_digest, "signed body"),
        (&record.admitted_source_digest, "admitted source"),
        (&record.objective_digest, "objective"),
        (&record.hard_constraint_digest, "hard constraint"),
        (&record.preference_state_digest, "preference state"),
        (&record.model_tuple_digest, "model tuple"),
        (&record.prompt_registry_digest, "prompt registry"),
        (&record.artifact_set_digest, "artifact set"),
        (&record.fence_digest, "fence"),
        (&record.runtime_body_digest, "runtime body"),
        (&record.run_start_digest, "run start"),
        (&record.publication_digest, "publication"),
    ] {
        parse_digest(value, field)?;
    }
    let actual_publication = objective_run_publication_digest_v1(record.publication_json.as_bytes());
    if actual_publication.to_string() != record.publication_digest {
        return Err(invalid("durable objective publication digest mismatch"));
    }
    let snapshot = RunStartSnapshotV1 {
        run_id: StableId::new(&record.run_id).map_err(|_| invalid("invalid run id"))?,
        objective_digest: parse_digest(&record.objective_digest, "objective")?,
        hard_constraint_digest: parse_digest(&record.hard_constraint_digest, "hard constraint")?,
        preference_state_digest: parse_digest(&record.preference_state_digest, "preference state")?,
        model_tuple_digest: parse_digest(&record.model_tuple_digest, "model tuple")?,
        prompt_registry_digest: parse_digest(&record.prompt_registry_digest, "prompt registry")?,
        artifact_set_digest: parse_digest(&record.artifact_set_digest, "artifact set")?,
        authority_epoch: record.authority_epoch,
        generation: record.generation,
        fence_digest: parse_digest(&record.fence_digest, "fence")?,
    };
    let actual_run_start = snapshot
        .semantic_digest()
        .map_err(|error| invalid(&format!("durable run snapshot: {error}")))?;
    if actual_run_start.to_string() != record.run_start_digest {
        return Err(invalid("durable run-start digest mismatch"));
    }
    Ok(())
}

fn record_path(root: &Path, run_id: &str) -> PathBuf {
    let name = Digest32::of_bytes(run_id.as_bytes()).to_string();
    root.join(format!("{name}.json"))
}

fn read_record(path: &Path) -> Result<StoredObjectiveRun, AgentdError> {
    let mut file = File::open(path)?;
    let metadata = file.metadata()?;
    if !metadata.is_file() || metadata.len() > 1_048_576 {
        return Err(invalid("invalid durable objective record file"));
    }
    let mut bytes = Vec::new();
    file.by_ref().take(1_048_577).read_to_end(&mut bytes)?;
    if bytes.len() > 1_048_576 {
        return Err(invalid("durable objective record exceeds 1 MiB"));
    }
    let record: StoredObjectiveRun = serde_json::from_slice(&bytes)?;
    validate_record(&record)?;
    Ok(record)
}

fn write_record_atomically(
    root: &Path,
    final_path: &Path,
    record: &StoredObjectiveRun,
) -> Result<(), AgentdError> {
    let bytes = serde_json::to_vec(record)?;
    if bytes.len() > 1_048_576 {
        return Err(invalid("durable objective record exceeds 1 MiB"));
    }
    let temp_path = final_path.with_extension("tmp");
    let _ = std::fs::remove_file(&temp_path);
    let mut options = OpenOptions::new();
    options.create_new(true).write(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.mode(0o600);
    }
    let mut file = options.open(&temp_path)?;
    file.write_all(&bytes)?;
    file.sync_all()?;
    std::fs::rename(&temp_path, final_path)?;
    #[cfg(unix)]
    File::open(root)?.sync_all()?;
    Ok(())
}

fn prepare_store(root: &Path) -> Result<(), AgentdError> {
    std::fs::create_dir_all(root)?;
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        std::fs::set_permissions(root, std::fs::Permissions::from_mode(0o700))?;
    }
    let metadata = std::fs::symlink_metadata(root)?;
    if !metadata.is_dir() || metadata.file_type().is_symlink() {
        return Err(invalid("objective publication root must be a real directory"));
    }
    Ok(())
}

fn runtime_error(error: AgentRunError) -> AgentdError {
    AgentdError::Protocol(format!("objective run coordinator: {error:?}"))
}

#[cfg(test)]
#[path = "objective_runtime_tests.rs"]
mod tests;
