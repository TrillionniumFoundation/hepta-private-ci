use std::error::Error as StdError;
use std::fmt;
use std::fs;
use std::fs::File;
use std::fs::OpenOptions;
use std::io::Read;
use std::io::Write;
use std::path::Path;
use std::path::PathBuf;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

use codex_hepta_objective::CompileDisposition;
use codex_hepta_objective::ConfirmationPolicy;
use codex_hepta_objective::ConstraintClass;
use codex_hepta_objective::ConstraintRelation;
use codex_hepta_objective::ObjectiveAdmissionContextV1;
use codex_hepta_objective::ObjectiveAdmissionError;
use codex_hepta_objective::ObjectiveAdmissionProfileV1;
use codex_hepta_objective::ObjectiveAdmissionReceiptV1;
use codex_hepta_objective::ObjectiveCompileReceipt;
use codex_hepta_objective::ObjectiveConflictReceipt;
use codex_hepta_objective::ObjectiveSourceEnvelopeV1;
use codex_hepta_objective::PredicateTerminality;
use codex_hepta_objective::SoftDirection;
use codex_hepta_objective::admit_and_compile_objective_v1;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use serde::Deserialize;
use serde::Serialize;

use crate::AgentRunCoordinator;
use crate::AgentRunError;
use crate::RunReceipt;
use crate::RunSnapshot;

const MAX_PUBLICATION_BYTES: usize = 512 * 1024;
const PUBLICATION_DOMAIN: &[u8] = b"hepta.agentd.objective-run-publication.v1";
static NEXT_PUBLICATION_TEMP: AtomicU64 = AtomicU64::new(0);

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ObjectiveRunBindingsV1 {
    pub run_id: StableId,
    pub body_digest: Digest32,
    pub preference_state_digest: Digest32,
    pub model_tuple_digest: Digest32,
    pub prompt_registry_digest: Digest32,
    pub artifact_set_digest: Digest32,
    pub authority_epoch: u64,
    pub generation: u64,
    pub fence_digest: Digest32,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ObjectiveProductRunDispositionV1 {
    Started,
    PublishedAbstain,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ObjectivePublicationReceiptV1 {
    pub run_id: StableId,
    pub publication_digest: Digest32,
    pub idempotent: bool,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ObjectiveProductRunReceiptV1 {
    pub admission: ObjectiveAdmissionReceiptV1,
    pub objective: ObjectiveCompileReceipt,
    pub publication: ObjectivePublicationReceiptV1,
    pub run: Option<RunReceipt>,
    pub disposition: ObjectiveProductRunDispositionV1,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct StoredObjectiveRunPublicationV1 {
    pub run_id: String,
    pub request_id: String,
    pub principal_scope: String,
    pub revision: u64,
    pub source_digest: String,
    pub schema_digest: String,
    pub hard_constraint_digest: String,
    pub semantic_digest: String,
    pub constraints: Vec<StoredConstraintV1>,
    pub success_predicates: Vec<StoredPredicateV1>,
    pub legal_actions: Vec<StoredActionV1>,
    pub soft_preferences: Vec<StoredPreferenceV1>,
    pub admission: StoredAdmissionReceiptV1,
    pub run_start_snapshot: StoredRunStartSnapshotV1,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct StoredConstraintV1 {
    pub id: String,
    pub class: String,
    pub axis: String,
    pub relation: String,
    pub bound_q32_raw: i64,
    pub evidence_source: String,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct StoredPredicateV1 {
    pub id: String,
    pub axis: String,
    pub relation: String,
    pub bound_q32_raw: i64,
    pub evidence_source: String,
    pub terminality: String,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct StoredActionV1 {
    pub id: String,
    pub confirmation: String,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct StoredPreferenceV1 {
    pub dimension: String,
    pub direction: String,
    pub weight_q32_raw: i64,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct StoredAdmissionReceiptV1 {
    pub profile_id: String,
    pub profile_revision: u64,
    pub profile_digest: String,
    pub supplied_source_digest: String,
    pub intent_digest: String,
    pub admitted_source_digest: String,
    pub observed_at_unix_micros: u64,
    pub deadline_unix_micros: Option<u64>,
    pub authority_denied: bool,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct StoredRunStartSnapshotV1 {
    pub run_id: String,
    pub objective_digest: String,
    pub hard_constraint_digest: String,
    pub preference_state_digest: String,
    pub model_tuple_digest: String,
    pub prompt_registry_digest: String,
    pub artifact_set_digest: String,
    pub authority_epoch: u64,
    pub generation: u64,
    pub fence_digest: String,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
struct StoredEnvelopeV1 {
    publication: StoredObjectiveRunPublicationV1,
    publication_digest: String,
}

#[derive(Debug)]
pub enum ObjectivePublicationError {
    Io(std::io::Error),
    Serialization(serde_json::Error),
    EncodedTooLarge { actual: usize, maximum: usize },
    Conflict,
    Integrity,
}

impl fmt::Display for ObjectivePublicationError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for ObjectivePublicationError {
    fn source(&self) -> Option<&(dyn StdError + 'static)> {
        match self {
            Self::Io(error) => Some(error),
            Self::Serialization(error) => Some(error),
            Self::EncodedTooLarge { .. } | Self::Conflict | Self::Integrity => None,
        }
    }
}

impl From<std::io::Error> for ObjectivePublicationError {
    fn from(value: std::io::Error) -> Self {
        Self::Io(value)
    }
}

impl From<serde_json::Error> for ObjectivePublicationError {
    fn from(value: serde_json::Error) -> Self {
        Self::Serialization(value)
    }
}

#[derive(Debug)]
pub enum ObjectiveProductRunError {
    Admission(ObjectiveAdmissionError),
    Conflict(ObjectiveConflictReceipt),
    MissingDeadline,
    InvalidBinding(&'static str),
    AuthorityEscalation,
    Publication(ObjectivePublicationError),
    Run(AgentRunError),
}

impl fmt::Display for ObjectiveProductRunError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for ObjectiveProductRunError {}

#[derive(Clone, Debug)]
pub struct ObjectiveRunFileStore {
    directory: PathBuf,
}

impl ObjectiveRunFileStore {
    pub fn open(directory: impl Into<PathBuf>) -> Result<Self, ObjectivePublicationError> {
        let directory = directory.into();
        fs::create_dir_all(&directory)?;
        Ok(Self { directory })
    }

    pub fn publish(
        &self,
        publication: &StoredObjectiveRunPublicationV1,
    ) -> Result<ObjectivePublicationReceiptV1, ObjectivePublicationError> {
        let payload = serde_json::to_vec(publication)?;
        if payload.len() > MAX_PUBLICATION_BYTES {
            return Err(ObjectivePublicationError::EncodedTooLarge {
                actual: payload.len(),
                maximum: MAX_PUBLICATION_BYTES,
            });
        }
        let publication_digest = publication_digest(&payload);
        let envelope = StoredEnvelopeV1 {
            publication: publication.clone(),
            publication_digest: publication_digest.to_string(),
        };
        let encoded = serde_json::to_vec(&envelope)?;
        if encoded.len() > MAX_PUBLICATION_BYTES {
            return Err(ObjectivePublicationError::EncodedTooLarge {
                actual: encoded.len(),
                maximum: MAX_PUBLICATION_BYTES,
            });
        }

        let run_id = StableId::new(publication.run_id.clone())
            .map_err(|_| ObjectivePublicationError::Integrity)?;
        let final_path = self.path_for(&run_id);
        if final_path.exists() {
            let (current, current_digest) = self
                .load(&run_id)?
                .ok_or(ObjectivePublicationError::Integrity)?;
            if current == *publication && current_digest == publication_digest {
                return Ok(ObjectivePublicationReceiptV1 {
                    run_id,
                    publication_digest,
                    idempotent: true,
                });
            }
            return Err(ObjectivePublicationError::Conflict);
        }

        // Publish with create-only link semantics. POSIX rename replaces an
        // existing destination, so a check-then-rename sequence would allow two
        // concurrent publishers with the same run identity to overwrite one
        // another. The temporary inode is fully synced first; hard_link is the
        // single atomic no-replace operation for the final name.
        let temp_path = write_publication_temp(&final_path, &encoded, publication_digest)?;
        match fs::hard_link(&temp_path, &final_path) {
            Ok(()) => {
                // The final name now points at the already-synced inode. Temp
                // cleanup is best effort: failing after publication would turn
                // a committed publication into an ambiguous caller outcome.
                let _ = fs::remove_file(&temp_path);
            }
            Err(error)
                if error.kind() == std::io::ErrorKind::AlreadyExists || final_path.exists() =>
            {
                let _ = fs::remove_file(&temp_path);
                let (current, current_digest) = self
                    .load(&run_id)?
                    .ok_or(ObjectivePublicationError::Integrity)?;
                if current == *publication && current_digest == publication_digest {
                    return Ok(ObjectivePublicationReceiptV1 {
                        run_id,
                        publication_digest,
                        idempotent: true,
                    });
                }
                return Err(ObjectivePublicationError::Conflict);
            }
            Err(error) => {
                let _ = fs::remove_file(&temp_path);
                return Err(ObjectivePublicationError::Io(error));
            }
        }
        sync_parent_directory(&self.directory)?;

        Ok(ObjectivePublicationReceiptV1 {
            run_id,
            publication_digest,
            idempotent: false,
        })
    }

    pub fn load(
        &self,
        run_id: &StableId,
    ) -> Result<Option<(StoredObjectiveRunPublicationV1, Digest32)>, ObjectivePublicationError>
    {
        let path = self.path_for(run_id);
        let file = match File::open(path) {
            Ok(file) => file,
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(None),
            Err(error) => return Err(ObjectivePublicationError::Io(error)),
        };
        let mut encoded = Vec::new();
        let mut limited = file.take((MAX_PUBLICATION_BYTES + 1) as u64);
        limited.read_to_end(&mut encoded)?;
        if encoded.len() > MAX_PUBLICATION_BYTES {
            return Err(ObjectivePublicationError::EncodedTooLarge {
                actual: encoded.len(),
                maximum: MAX_PUBLICATION_BYTES,
            });
        }
        let envelope: StoredEnvelopeV1 = serde_json::from_slice(&encoded)?;
        if envelope.publication.run_id != run_id.as_str() {
            return Err(ObjectivePublicationError::Integrity);
        }
        let payload = serde_json::to_vec(&envelope.publication)?;
        let observed = publication_digest(&payload);
        if envelope.publication_digest != observed.to_string() {
            return Err(ObjectivePublicationError::Integrity);
        }
        Ok(Some((envelope.publication, observed)))
    }

    fn path_for(&self, run_id: &StableId) -> PathBuf {
        let key = Digest32::of_bytes(run_id.as_str().as_bytes());
        self.directory.join(format!("{key}.objective-run-v1.json"))
    }
}

fn write_publication_temp(
    final_path: &Path,
    encoded: &[u8],
    publication_digest: Digest32,
) -> Result<PathBuf, ObjectivePublicationError> {
    for _ in 0..1_024 {
        let nonce = NEXT_PUBLICATION_TEMP.fetch_add(1, Ordering::Relaxed);
        let temp_path = final_path.with_extension(format!(
            "tmp.{publication_digest}.{}.{}",
            std::process::id(),
            nonce
        ));
        let mut options = OpenOptions::new();
        options.create_new(true).write(true);
        #[cfg(unix)]
        {
            use std::os::unix::fs::OpenOptionsExt;
            options.mode(0o600);
        }
        let mut file = match options.open(&temp_path) {
            Ok(file) => file,
            Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => continue,
            Err(error) => return Err(ObjectivePublicationError::Io(error)),
        };
        if let Err(error) = file.write_all(encoded).and_then(|()| file.sync_all()) {
            let _ = fs::remove_file(&temp_path);
            return Err(ObjectivePublicationError::Io(error));
        }
        return Ok(temp_path);
    }
    Err(ObjectivePublicationError::Io(std::io::Error::new(
        std::io::ErrorKind::AlreadyExists,
        "could not allocate unique objective publication staging file",
    )))
}

pub fn admit_publish_and_start_objective_run_v1(
    coordinator: &mut AgentRunCoordinator,
    store: &ObjectiveRunFileStore,
    now_ms: u64,
    envelope: &ObjectiveSourceEnvelopeV1,
    profile: &ObjectiveAdmissionProfileV1,
    context: &ObjectiveAdmissionContextV1,
    bindings: &ObjectiveRunBindingsV1,
) -> Result<ObjectiveProductRunReceiptV1, ObjectiveProductRunError> {
    validate_bindings(bindings)?;
    let outcome = admit_and_compile_objective_v1(envelope, profile, context)
        .map_err(ObjectiveProductRunError::Admission)?;
    if outcome.receipt.authority.grants_any() {
        return Err(ObjectiveProductRunError::AuthorityEscalation);
    }
    let objective = outcome
        .compile_result
        .map_err(ObjectiveProductRunError::Conflict)?;
    let deadline_micros = outcome
        .receipt
        .deadline_unix_micros
        .ok_or(ObjectiveProductRunError::MissingDeadline)?;
    let deadline_ms = deadline_micros / 1_000;
    let publication_value = stored_publication(&outcome.receipt, &objective, bindings);
    let publication = store
        .publish(&publication_value)
        .map_err(ObjectiveProductRunError::Publication)?;

    if objective.disposition == CompileDisposition::ExplicitAbstain {
        return Ok(ObjectiveProductRunReceiptV1 {
            admission: outcome.receipt,
            objective,
            publication,
            run: None,
            disposition: ObjectiveProductRunDispositionV1::PublishedAbstain,
        });
    }

    let run = coordinator
        .start_run(
            now_ms,
            RunSnapshot {
                run_id: bindings.run_id.to_string(),
                request_digest: outcome.receipt.admitted_source_digest.to_string(),
                objective_digest: objective.objective.semantic_digest.to_string(),
                body_digest: bindings.body_digest.to_string(),
                artifact_set_digest: bindings.artifact_set_digest.to_string(),
                authority_epoch: bindings.authority_epoch,
                deadline_ms,
            },
        )
        .map_err(ObjectiveProductRunError::Run)?;

    Ok(ObjectiveProductRunReceiptV1 {
        admission: outcome.receipt,
        objective,
        publication,
        run: Some(run),
        disposition: ObjectiveProductRunDispositionV1::Started,
    })
}

fn validate_bindings(bindings: &ObjectiveRunBindingsV1) -> Result<(), ObjectiveProductRunError> {
    if bindings.authority_epoch == 0 {
        return Err(ObjectiveProductRunError::InvalidBinding("authority epoch"));
    }
    if bindings.generation == 0 {
        return Err(ObjectiveProductRunError::InvalidBinding("generation"));
    }
    for (name, digest) in [
        ("body", bindings.body_digest),
        ("preference state", bindings.preference_state_digest),
        ("model tuple", bindings.model_tuple_digest),
        ("prompt registry", bindings.prompt_registry_digest),
        ("artifact set", bindings.artifact_set_digest),
        ("fence", bindings.fence_digest),
    ] {
        if digest.is_zero() {
            return Err(ObjectiveProductRunError::InvalidBinding(name));
        }
    }
    Ok(())
}

fn stored_publication(
    admission: &ObjectiveAdmissionReceiptV1,
    compile: &ObjectiveCompileReceipt,
    bindings: &ObjectiveRunBindingsV1,
) -> StoredObjectiveRunPublicationV1 {
    let objective = &compile.objective;
    StoredObjectiveRunPublicationV1 {
        run_id: bindings.run_id.to_string(),
        request_id: objective.request_id.to_string(),
        principal_scope: objective.principal_scope.to_string(),
        revision: objective.revision.get(),
        source_digest: objective.source_digest.to_string(),
        schema_digest: objective.schema_digest.to_string(),
        hard_constraint_digest: objective.hard_constraint_digest.to_string(),
        semantic_digest: objective.semantic_digest.to_string(),
        constraints: objective
            .constraints
            .iter()
            .map(|value| StoredConstraintV1 {
                id: value.id.to_string(),
                class: constraint_class(value.class).to_string(),
                axis: value.axis.to_string(),
                relation: relation(value.relation).to_string(),
                bound_q32_raw: value.bound.raw(),
                evidence_source: value.evidence_source.to_string(),
            })
            .collect(),
        success_predicates: objective
            .success_predicates
            .iter()
            .map(|value| StoredPredicateV1 {
                id: value.id.to_string(),
                axis: value.axis.to_string(),
                relation: relation(value.relation).to_string(),
                bound_q32_raw: value.bound.raw(),
                evidence_source: value.evidence_source.to_string(),
                terminality: terminality(value.terminality).to_string(),
            })
            .collect(),
        legal_actions: objective
            .legal_actions
            .iter()
            .map(|value| StoredActionV1 {
                id: value.id.to_string(),
                confirmation: confirmation(value.confirmation).to_string(),
            })
            .collect(),
        soft_preferences: objective
            .soft_preferences
            .iter()
            .map(|value| StoredPreferenceV1 {
                dimension: value.dimension.to_string(),
                direction: direction(value.direction).to_string(),
                weight_q32_raw: value.weight.raw(),
            })
            .collect(),
        admission: StoredAdmissionReceiptV1 {
            profile_id: admission.profile_id.to_string(),
            profile_revision: admission.profile_revision.get(),
            profile_digest: admission.profile_digest.to_string(),
            supplied_source_digest: admission.supplied_source_digest.to_string(),
            intent_digest: admission.intent_digest.to_string(),
            admitted_source_digest: admission.admitted_source_digest.to_string(),
            observed_at_unix_micros: admission.observed_at_unix_micros,
            deadline_unix_micros: admission.deadline_unix_micros,
            authority_denied: !admission.authority.grants_any(),
        },
        run_start_snapshot: StoredRunStartSnapshotV1 {
            run_id: bindings.run_id.to_string(),
            objective_digest: objective.semantic_digest.to_string(),
            hard_constraint_digest: objective.hard_constraint_digest.to_string(),
            preference_state_digest: bindings.preference_state_digest.to_string(),
            model_tuple_digest: bindings.model_tuple_digest.to_string(),
            prompt_registry_digest: bindings.prompt_registry_digest.to_string(),
            artifact_set_digest: bindings.artifact_set_digest.to_string(),
            authority_epoch: bindings.authority_epoch,
            generation: bindings.generation,
            fence_digest: bindings.fence_digest.to_string(),
        },
    }
}

fn publication_digest(payload: &[u8]) -> Digest32 {
    let mut bytes = Vec::with_capacity(PUBLICATION_DOMAIN.len() + payload.len());
    bytes.extend_from_slice(PUBLICATION_DOMAIN);
    bytes.extend_from_slice(payload);
    Digest32::of_bytes(&bytes)
}

fn constraint_class(value: ConstraintClass) -> &'static str {
    match value {
        ConstraintClass::Constitutional => "constitutional",
        ConstraintClass::Principal => "principal",
        ConstraintClass::Environment => "environment",
        ConstraintClass::Task => "task",
    }
}

fn relation(value: ConstraintRelation) -> &'static str {
    match value {
        ConstraintRelation::AtLeast => "at_least",
        ConstraintRelation::AtMost => "at_most",
        ConstraintRelation::Equal => "equal",
    }
}

fn terminality(value: PredicateTerminality) -> &'static str {
    match value {
        PredicateTerminality::Intermediate => "intermediate",
        PredicateTerminality::Terminal => "terminal",
    }
}

fn confirmation(value: ConfirmationPolicy) -> &'static str {
    match value {
        ConfirmationPolicy::NotRequired => "not_required",
        ConfirmationPolicy::Required => "required",
    }
}

fn direction(value: SoftDirection) -> &'static str {
    match value {
        SoftDirection::Maximize => "maximize",
        SoftDirection::Minimize => "minimize",
    }
}

#[cfg(unix)]
fn sync_parent_directory(path: &Path) -> Result<(), ObjectivePublicationError> {
    File::open(path)?.sync_all()?;
    Ok(())
}

#[cfg(not(unix))]
fn sync_parent_directory(_path: &Path) -> Result<(), ObjectivePublicationError> {
    Ok(())
}

#[cfg(test)]
#[path = "objective_runtime_tests.rs"]
mod tests;
