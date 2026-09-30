use std::collections::BTreeMap;

use serde::Deserialize;
use serde::Serialize;

use super::DurableInferenceControl;
use super::Error;
use super::validate_digest;
use super::validate_identity;

pub(super) const JOURNAL_PREFIX: &str = "native-v1|";
pub const NATIVE_RECORD_SCHEMA_VERSION: u32 = 2;
const LOCAL_MODEL_PROVIDER_ID: &str = "local.model.experimental";

fn legacy_record_schema_version() -> u32 {
    1
}

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
    Lost { reason: String },
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
    /// Present for runtime.codex-bound terminal observations and reused by the
    /// experimental local adapter for a domain-separated terminal receipt.
    #[serde(default)]
    pub codex_terminal_correlation_digest: Option<String>,
}

impl NativeRunOutput {
    /// Callers must not infer authorized success from provider completion alone.
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
    #[serde(default)]
    pub owner_context_digest: Option<String>,
    #[serde(default)]
    pub codex_payload_digest: Option<String>,
    #[serde(default)]
    pub codex_request_digest: Option<String>,
    #[serde(default)]
    pub app_server_version: Option<String>,
    #[serde(default)]
    pub protocol_id: Option<String>,
    #[serde(default)]
    pub codex_source_admission_digest: Option<String>,
    #[serde(default)]
    pub codex_home_digest: Option<String>,
    #[serde(default)]
    pub codex_connection_id: Option<u64>,
    #[serde(default)]
    pub codex_session_id: Option<String>,
    #[serde(default)]
    pub codex_deadline_ms: Option<u64>,
    #[serde(default)]
    pub codex_authority_epoch: Option<u64>,
    #[serde(default)]
    pub codex_revocation_revision: Option<u64>,
    #[serde(default)]
    pub codex_revocation_head_sha256: Option<String>,
    #[serde(default)]
    pub codex_authority_witness_sha256: Option<String>,
}

/// In-memory proof that this live process durably prepared one dispatch but has
/// not crossed the physical effect boundary. Recovery can never recreate it.
pub struct NativePreEffectAbortToken {
    request_id: String,
    dispatch_revision: u64,
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

#[derive(Clone, Copy, Debug, Default, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum NativeUsageAuthority {
    #[default]
    Unknown,
    DriverObserved,
    ProviderVerified,
}

impl NativeUsageAuthority {
    fn rank(self) -> u8 {
        match self {
            Self::Unknown => 0,
            Self::DriverObserved => 1,
            Self::ProviderVerified => 2,
        }
    }
}

/// Monotonic live authority evidence observed for one exact request/grant.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct NativeAuthorityObservation {
    pub issuer: String,
    pub grant_id: String,
    pub authority_epoch: u64,
    pub revocation_revision: u64,
    pub revocation_head_digest: String,
    pub grant_witness_digest: String,
    pub authority_snapshot_digest: String,
    pub observed_at_unix_ms: u64,
    pub revoked: bool,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum NativeInterruptOutcome {
    Requested,
    Acknowledged,
    Terminal,
    Pending,
    MissingHistory,
    Ambiguous,
    Failed,
    TimedOut,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct NativeInterruptObservation {
    pub reason: String,
    pub requested_at_unix_ms: u64,
    pub observed_at_unix_ms: Option<u64>,
    pub outcome: NativeInterruptOutcome,
    pub evidence_digest: Option<String>,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct NativeCapacityReleaseEvidence {
    pub observed_at_unix_ms: u64,
    pub evidence_digest: String,
    pub reason: String,
}

#[derive(Clone, Debug, Default, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct NativeObservationEvidence {
    pub observed_at_unix_ms: u64,
    pub usage_units: Option<u64>,
    #[serde(default)]
    pub usage_authority: NativeUsageAuthority,
    #[serde(default)]
    pub resource_attestation_digest: Option<String>,
    #[serde(default)]
    pub terminal_evidence_digest: Option<String>,
    #[serde(default)]
    pub quarantine_reason: Option<String>,
    #[serde(default)]
    pub generation_fence_identity: Option<String>,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct NativeRunRecord {
    #[serde(default = "legacy_record_schema_version")]
    pub schema_version: u32,
    pub request: NativeRequest,
    pub revision: u64,
    pub state: NativeReservationState,
    pub dispatch: Option<NativeDispatch>,
    pub turn_id: Option<String>,
    pub cancel_requested: bool,
    pub pre_dispatch_stop: Option<String>,
    #[serde(default)]
    pub dispatch_rejection: Option<NativeDispatchRejection>,
    pub observation: Option<NativeRunOutput>,
    #[serde(default)]
    pub observed_usage_units: Option<u64>,
    #[serde(default)]
    pub first_indeterminate_at_unix_ms: Option<u64>,
    #[serde(default)]
    pub last_observed_at_unix_ms: Option<u64>,
    #[serde(default)]
    pub effect_entered_at_unix_ms: Option<u64>,
    #[serde(default)]
    pub authority_observation: Option<NativeAuthorityObservation>,
    #[serde(default)]
    pub interrupt_observation: Option<NativeInterruptObservation>,
    #[serde(default)]
    pub usage_authority: NativeUsageAuthority,
    #[serde(default)]
    pub resource_attestation_digest: Option<String>,
    #[serde(default)]
    pub terminal_evidence_digest: Option<String>,
    #[serde(default)]
    pub quarantine_reason: Option<String>,
    #[serde(default)]
    pub generation_fence_identity: Option<String>,
    #[serde(default)]
    pub capacity_release_evidence: Option<NativeCapacityReleaseEvidence>,
}

#[derive(Clone, Debug, Default, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct NativeJournal {
    maximum_in_flight: Option<usize>,
    pub(super) records: BTreeMap<String, NativeRunRecord>,
}

#[derive(Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
enum Event {
    Reserve {
        request: NativeRequest,
        maximum_in_flight: usize,
    },
    Dispatch {
        request_id: String,
        dispatch: NativeDispatch,
    },
    /// Legacy event retained for replay.
    Started {
        request_id: String,
        turn_id: String,
    },
    StartedAt {
        request_id: String,
        turn_id: String,
        effect_entered_at_unix_ms: u64,
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
        /// Zero is accepted only while replaying a pre-metadata journal event.
        #[serde(default)]
        observed_at_unix_ms: u64,
        /// `None` is unknown and never means zero.
        #[serde(default)]
        usage_units: Option<u64>,
    },
    ObserveV2 {
        request_id: String,
        output: NativeRunOutput,
        evidence: NativeObservationEvidence,
    },
    AuthorityObserved {
        request_id: String,
        observation: NativeAuthorityObservation,
    },
    InterruptIntent {
        request_id: String,
        observation: NativeInterruptObservation,
    },
    InterruptOutcome {
        request_id: String,
        observation: NativeInterruptObservation,
    },
    ReleaseQuarantine {
        request_id: String,
        evidence: NativeCapacityReleaseEvidence,
    },
}
