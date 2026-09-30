use std::collections::BTreeMap;
use std::ffi::OsString;
use std::fs;
use std::fs::File;
use std::fs::OpenOptions;
use std::io::Read;
use std::io::Write;
use std::path::Path;
use std::path::PathBuf;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use serde::Deserialize;
use serde::Serialize;
use sha2::Digest;
use sha2::Sha256;

use crate::control_contracts::OutputStorageMode;
use crate::control_contracts::ProtectedOutput;
use crate::control_contracts::ReconciledTerminalStatus;
use crate::control_contracts::VerifiedExecutionPlan;
use crate::control_contracts::VerifiedReconciliationReceipt;
use crate::control_contracts::VerifiedRetirement;

use super::DurableInferenceControl;
use super::Error;
use super::validate_digest;
use super::validate_identity;

pub(super) const JOURNAL_PREFIX: &str = "native-v1|";
const CHECKPOINT_SCHEMA_VERSION: u32 = 2;
const MAX_CHECKPOINT_BYTES: u64 = super::MAX_JOURNAL_BYTES;
const COMPACTION_HEADROOM_BYTES: u64 = 2 * super::MAX_JOURNAL_LINE_BYTES as u64;

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct NativeRequest {
    pub request_id: String,
    pub principal_id: String,
    pub worker_generation: u64,
    pub model: String,
    /// Binds the prompt, optional query, exact socket and execution timeout.
    pub payload_digest: String,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum NativeRunStatus {
    Completed,
    Failed,
    Interrupted,
    Indeterminate,
}

#[derive(Clone, Copy, Debug, Default, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum NativeBoundaryStatus {
    Succeeded,
    Failed,
    Interrupted,
    Cancelled,
    TimedOut,
    Quarantined,
    #[default]
    Indeterminate,
}

/// Provider terminality and the owner's authority observation are independent.
/// Missing historical fields never establish that authority was checked.
#[derive(Clone, Debug, Default, Deserialize, Eq, PartialEq, Serialize)]
#[serde(tag = "state", rename_all = "snake_case", deny_unknown_fields)]
pub enum NativeOwnerAuthority {
    #[default]
    Unverified,
    /// The exact owner was ready at the last health check, not an atomic grant
    /// against revocation after that check.
    ObservedReady,
    Lost {
        reason: String,
    },
}

/// Fields observed by the native client, never a provider billing assertion.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct NativeRunOutput {
    pub thread_id: String,
    pub turn_id: String,
    pub model: String,
    pub model_provider: String,
    pub status: NativeRunStatus,
    #[serde(default)]
    pub boundary_status: NativeBoundaryStatus,
    pub output: String,
    pub observed_output_tokens: Option<u64>,
    pub terminal_observed: bool,
    pub stop_reason: Option<String>,
    #[serde(default)]
    pub owner_authority: NativeOwnerAuthority,
    /// Present for new runtime.codex-bound terminal observations. Historical
    /// records may omit it, but a dispatch carrying a codex request digest may
    /// not settle terminally without it.
    #[serde(default)]
    pub codex_terminal_correlation_digest: Option<String>,
}

impl NativeRunOutput {
    /// The CLI and callers must not infer authorized success from provider
    /// completion alone, including when replaying a historical observation.
    pub fn succeeded(&self) -> bool {
        self.terminal_observed
            && self.status == NativeRunStatus::Completed
            && self.boundary_status == NativeBoundaryStatus::Succeeded
            && self.stop_reason.is_none()
            && self.owner_authority == NativeOwnerAuthority::ObservedReady
            && self.codex_terminal_correlation_digest.is_some()
    }
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum NativeReservationState {
    Reserved,
    Dispatching,
    Running,
    Cancelling,
    Indeterminate,
    Released,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct NativeDispatch {
    pub thread_id: String,
    pub model_provider: String,
    /// Exact serialized additional context passed to turn/start.
    pub context_digest: String,
    /// Digest of the owner-native CognitiveContextSnapshot nested inside the
    /// additional context. It joins retrieval assignment evidence to this
    /// durable dispatch without claiming provider acceptance by itself.
    #[serde(default)]
    pub owner_context_digest: Option<String>,
    /// Exact serialized turn/start payload digest. Optional only for replaying
    /// pre-runtime.codex journal records.
    #[serde(default)]
    pub codex_payload_digest: Option<String>,
    /// Adapter request digest binding durable admission + physical payload.
    #[serde(default)]
    pub codex_request_digest: Option<String>,
    /// Version reported by the App Server initialize handshake.
    #[serde(default)]
    pub app_server_version: Option<String>,
    /// Exact protocol family/version, for example codex.app-server.v2.
    #[serde(default)]
    pub protocol_id: Option<String>,
    #[serde(default)]
    pub codex_source_admission_digest: Option<String>,
    #[serde(default)]
    pub codex_home_digest: Option<String>,
    #[serde(default)]
    pub codex_connection_id: Option<u64>,
    /// Exact App Server session returned by thread/start.
    #[serde(default)]
    pub codex_session_id: Option<String>,
    /// Absolute wall-clock deadline used for final-use and turn/start.
    #[serde(default)]
    pub codex_deadline_ms: Option<u64>,
    /// Exact claim-time authority epoch used by the final-use token.
    #[serde(default)]
    pub codex_authority_epoch: Option<u64>,
    /// Exact claim-time revocation revision used by the final-use token.
    #[serde(default)]
    pub codex_revocation_revision: Option<u64>,
    /// Domain-separated digest of the complete claim-time revocation head,
    /// including its revoked-grant set.
    #[serde(default)]
    pub codex_revocation_head_sha256: Option<String>,
    /// Digest of the independently signed final-use grant + exact claim-time
    /// revocation head witness claimed for this dispatch before physical turn/start.
    #[serde(default)]
    pub codex_authority_witness_sha256: Option<String>,
}

/// Exact plan digests persisted before any provider effect.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct NativeExecutionBinding {
    pub authority_epoch: u64,
    pub bundle_digest: String,
    pub manifest_digest: String,
    pub quota_lease_digest: String,
    pub resource_lease_digest: String,
    pub output_policy_digest: String,
    pub execution_binding_digest: String,
    pub provider_id: String,
    pub model_id: String,
    pub model_revision: String,
    pub model_digest: String,
    pub tokenizer_digest: String,
    pub template_digest: String,
    pub runtime_digest: String,
    pub adapter_digest: String,
    pub worker_id: String,
    pub worker_generation: u64,
    pub maximum_input_tokens: u64,
    pub maximum_output_tokens: u64,
    pub maximum_cost_microunits: u64,
    pub valid_until_unix_ms: u64,
}

/// Audit metadata for a signed provider reconciliation.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct NativeReconciliationAudit {
    pub receipt_digest: String,
    pub authenticated_key_id: String,
    pub terminal_sequence: u64,
    pub usage_microunits: Option<u64>,
    pub output_digest: Option<String>,
    pub encrypted_output_reference: Option<String>,
}

/// Audit metadata for a dual-control retirement.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct NativeRetirementAudit {
    pub retirement_digest: String,
    pub operator_ids: [String; 2],
    pub key_ids: [String; 2],
    /// Domain-separated digests of the actual independent verifying keys.
    /// Missing historical evidence holds capacity until fresh retirement.
    #[serde(default)]
    pub independent_operator_key_digests: Option<[String; 2]>,
    pub reason_code: String,
    pub reason: String,
}

/// In-memory proof that this live process has durably prepared one dispatch but
/// has not crossed the external App Server effect boundary.
///
/// The token is deliberately non-cloneable and non-serializable. Recovery can
/// never recreate it. The original owner incarnation must still match, so
/// retaining a token across owner reopen cannot release a recovered dispatch.
pub struct NativePreEffectAbortToken {
    request_id: String,
    dispatch_revision: u64,
    owner: std::sync::Weak<()>,
}

impl std::fmt::Debug for NativePreEffectAbortToken {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter.write_str("NativePreEffectAbortToken([LOCAL ONLY])")
    }
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum NativeDispatchRejectionStatus {
    Rejected,
    Overloaded,
    /// Legacy journal spelling retained for replay.
    Unavailable,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct NativeDispatchRejection {
    pub status: NativeDispatchRejectionStatus,
    pub reason: String,
    pub response_digest: String,
    /// Only overload/pre-processing refusal may carry this bit.
    pub retry_safe_before_admission: bool,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct NativeRunRecord {
    pub request: NativeRequest,
    pub revision: u64,
    pub state: NativeReservationState,
    pub dispatch: Option<NativeDispatch>,
    pub turn_id: Option<String>,
    pub cancel_requested: bool,
    /// A locally proven pre-dispatch stop releases a slot without pretending
    /// to have observed a provider terminal event or zero token consumption.
    pub pre_dispatch_stop: Option<String>,
    #[serde(default)]
    pub dispatch_rejection: Option<NativeDispatchRejection>,
    pub observation: Option<NativeRunOutput>,
    #[serde(default)]
    pub execution_binding: Option<NativeExecutionBinding>,
    #[serde(default)]
    pub protected_output: Option<ProtectedOutput>,
    #[serde(default)]
    pub reconciliation: Option<NativeReconciliationAudit>,
    #[serde(default)]
    pub retirement: Option<NativeRetirementAudit>,
}

#[derive(Clone, Debug, Default)]
pub(super) struct NativeJournal {
    maximum_in_flight: Option<usize>,
    pub(super) records: BTreeMap<String, NativeRunRecord>,
    checkpoint_generation: u64,
    archive_chain_digest: Option<String>,
    checkpoint_digest: Option<String>,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
struct NativeCheckpoint {
    schema_version: u32,
    generation: u64,
    maximum_in_flight: Option<usize>,
    records: BTreeMap<String, NativeRunRecord>,
    archive_segment_digest: String,
    archive_chain_digest: String,
    created_at_unix_ms: u64,
}

#[derive(Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
enum Event {
    Reserve {
        request: NativeRequest,
        maximum_in_flight: usize,
    },
    BindExecution {
        request_id: String,
        binding: NativeExecutionBinding,
    },
    Dispatch {
        request_id: String,
        dispatch: NativeDispatch,
    },
    Started {
        request_id: String,
        turn_id: String,
    },
    RejectBeforeStart {
        request_id: String,
        rejection: NativeDispatchRejection,
    },
    Cancel {
        request_id: String,
    },
    Stop {
        request_id: String,
        reason: String,
    },
    AbortBeforeEffect {
        request_id: String,
        reason: String,
    },
    Observe {
        request_id: String,
        output: NativeRunOutput,
        #[serde(default)]
        protected_output: Option<ProtectedOutput>,
    },
    Reconcile {
        request_id: String,
        output: NativeRunOutput,
        audit: NativeReconciliationAudit,
    },
    Retire {
        request_id: String,
        audit: NativeRetirementAudit,
    },
    CheckpointReference {
        generation: u64,
        checkpoint_path: String,
        checkpoint_digest: String,
        archive_segment_digest: String,
        archive_chain_digest: String,
    },
}

/// Deterministic maintenance boundary for crash/fault tests.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum NativeMaintenanceStage {
    BeforeArchiveWrite,
    AfterArchiveSync,
    BeforeCheckpointWrite,
    AfterCheckpointSync,
    BeforeGenerationWrite,
    AfterGenerationSync,
    AfterGenerationRename,
    AfterParentSync,
}

/// Deterministic failpoint used by tests and target-host qualification.
pub trait NativeMaintenanceFailpoint {
    fn hit(&mut self, stage: NativeMaintenanceStage) -> Result<(), Error>;
}

impl<F> NativeMaintenanceFailpoint for F
where
    F: FnMut(NativeMaintenanceStage) -> Result<(), Error>,
{
    fn hit(&mut self, stage: NativeMaintenanceStage) -> Result<(), Error> {
        self(stage)
    }
}

struct NoMaintenanceFailpoint;

impl NativeMaintenanceFailpoint for NoMaintenanceFailpoint {
    fn hit(&mut self, _stage: NativeMaintenanceStage) -> Result<(), Error> {
        Ok(())
    }
}

/// Durable maintenance evidence emitted after a successful atomic generation.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct NativeMaintenanceReceipt {
    pub generation: u64,
    pub archive_segment_digest: String,
    pub archive_chain_digest: String,
    pub checkpoint_digest: String,
    pub active_journal_bytes: u64,
    pub record_count: usize,
    pub expired_encrypted_references: Vec<String>,
}

/// Bounded operational metrics, suitable for a scrape adapter.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct NativeControlMetrics {
    pub journal_bytes: u64,
    pub checkpoint_generation: u64,
    pub reserved: usize,
    pub dispatching: usize,
    pub running: usize,
    pub cancelling: usize,
    pub indeterminate: usize,
    pub released: usize,
    pub protected_outputs: usize,
    pub expired_output_references: usize,
}
