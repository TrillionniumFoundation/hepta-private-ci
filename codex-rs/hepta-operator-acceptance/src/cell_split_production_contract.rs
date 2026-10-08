//! Owner-bound production adapter for the DecisionCell split lifecycle.
//!
//! This module only composes externally owned handles.  It never opens a CAS,
//! CNS socket, signer, fault injector, telemetry source, or ledger itself.  A
//! missing handle, namespace, trust root, receipt, or non-secret binding is a
//! structured fail-closed error.  Consequently this adapter cannot manufacture
//! target-host evidence from a digest or an in-memory fixture.

use std::fmt;
use std::sync::Arc;

use serde::Deserialize;
use serde::Serialize;

use crate::CellSplitTargetResourceSampleV1;

pub const CELL_SPLIT_PRODUCTION_RUNTIME_SCHEMA_V1: &str =
    "hepta.learning.cell-split.production-target-host-runtime.v1";
pub(crate) const ZERO_DIGEST: &str =
    "0000000000000000000000000000000000000000000000000000000000000000";

/// Exactly fourteen externally witnessed lifecycle steps.
#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(rename_all = "kebab-case")]
pub enum CellSplitProductionLifecycleStepV1 {
    OwnersBound,
    ArtifactsLoaded,
    RouteCutover,
    Dispatched,
    CleanRestarted,
    ApprovedPowerLoss,
    Recovered,
    RolledBack,
    Tombstoned,
    OldGenerationRejected,
    FutureWindowEvaluated,
    EvidenceSigned,
    TaskFlowLedgerReplayed,
    IndependentlyVerified,
}

impl CellSplitProductionLifecycleStepV1 {
    pub(crate) fn ordinal(self) -> u8 {
        match self {
            Self::OwnersBound => 1,
            Self::ArtifactsLoaded => 2,
            Self::RouteCutover => 3,
            Self::Dispatched => 4,
            Self::CleanRestarted => 5,
            Self::ApprovedPowerLoss => 6,
            Self::Recovered => 7,
            Self::RolledBack => 8,
            Self::Tombstoned => 9,
            Self::OldGenerationRejected => 10,
            Self::FutureWindowEvaluated => 11,
            Self::EvidenceSigned => 12,
            Self::TaskFlowLedgerReplayed => 13,
            Self::IndependentlyVerified => 14,
        }
    }
}

/// Non-secret identity of one externally owned boundary.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ProductionOwnerBindingV1 {
    pub owner_id: String,
    pub namespace: String,
    pub trust_root_digest: String,
}

/// Common receipt returned by a real owner.  The adapter validates it and
/// preserves it; it never derives a successful receipt locally.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ProductionOwnerOperationReceiptV1 {
    pub operation_id: String,
    pub step: CellSplitProductionLifecycleStepV1,
    pub occurred_at_unix_nanos: u128,
    pub generation: u64,
    pub predecessor_receipt_digest: String,
    pub artifact_digest: String,
    pub route_digest: String,
    pub tombstone_digest: String,
    pub witness_digest: String,
    pub receipt_digest: String,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ProductionOwnerRequestV1 {
    pub split_id: String,
    pub namespace: String,
    pub parent_generation: u64,
    pub child_generation: u64,
    pub parent_artifact_digest: String,
    pub child_artifact_digest: String,
    pub parameter_bundle_digest: String,
    pub migration_digest: String,
    pub predecessor_receipt_digest: String,
}

/// CAS and registry witness for parent/child artifact loading.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ArtifactCasRegistryPacketV1 {
    pub owner_id: String,
    pub namespace: String,
    pub parent_generation: u64,
    pub child_generation: u64,
    pub parent_artifact_digest: String,
    pub child_artifact_digest: String,
    pub parameter_bundle_digest: String,
    pub registry_head_digest: String,
    pub cas_read_receipt_digest: String,
}

/// CNS route cutover and dispatch witness, including the old-generation fence.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CnsDispatchPacketV1 {
    pub owner_id: String,
    pub namespace: String,
    pub predecessor_route_digest: String,
    pub successor_route_digest: String,
    pub dispatch_receipt_digest: String,
    pub route_fence_digest: String,
    pub parent_generation: u64,
    pub child_generation: u64,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct RouteFenceRestartReplayPacketV1 {
    pub route_fence_digest: String,
    pub clean_restart_receipt_digest: String,
    pub recovery_receipt_digest: String,
    pub replay_chain_digest: String,
    pub child_generation: u64,
}

/// Durable restart, power-loss, rollback and tombstone witness bundle.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct RestartPowerLossRollbackTombstonePacketV1 {
    pub clean_restart_digest: String,
    pub approved_power_loss_digest: String,
    pub recovery_digest: String,
    pub rollback_digest: String,
    pub tombstone_digest: String,
    pub no_resurrection_digest: String,
    pub old_generation_reject_digest: String,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ProductionResourceSamplesPacketV1 {
    pub samples: Vec<CellSplitTargetResourceSampleV1>,
    pub hardware_attestation_digest: String,
    pub telemetry_receipt_digest: String,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct BaselinePacketV1 {
    pub baseline_digest: String,
    pub observation_count: u64,
    pub observer_receipt_digest: String,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct FutureWindowObserverPacketV1 {
    pub baseline_digest: String,
    pub future_window_digest: String,
    pub observation_count: u64,
    pub minimum_observation_count: u64,
    pub observer_receipt_digest: String,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct TaskFlowEventChainPacketV1 {
    pub taskflow_run_digest: String,
    pub event_chain_digest: String,
    pub replay_receipt_digest: String,
    pub event_count: u64,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct LearningLedgerWitnessFrontierPacketV1 {
    pub ledger_namespace: String,
    pub predecessor_frontier_digest: String,
    pub witness_frontier_digest: String,
    pub replay_receipt_digest: String,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct SignedTargetHostEvidencePacketV1 {
    pub evidence_digest: String,
    pub host_signature_digest: String,
    pub observer_signature_digest: String,
    pub trust_root_digest: String,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct IndependentEvaluatorReceiptPacketV1 {
    pub evaluator_id: String,
    pub receipt_digest: String,
    pub verified_evidence_digest: String,
    pub verified_taskflow_digest: String,
    pub verified_ledger_frontier_digest: String,
}

/// All packet schemas are carried together for durable export.  Empty optional
/// fields are absent until the corresponding owner has returned a receipt.
#[derive(Clone, Debug, Default, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CellSplitProductionPacketV1 {
    pub schema: String,
    pub artifact_cas_registry: Option<ArtifactCasRegistryPacketV1>,
    pub cns_dispatch: Option<CnsDispatchPacketV1>,
    pub route_fence_restart_replay: Option<RouteFenceRestartReplayPacketV1>,
    pub lifecycle_witness: Option<RestartPowerLossRollbackTombstonePacketV1>,
    pub resources: Option<ProductionResourceSamplesPacketV1>,
    pub baseline: Option<BaselinePacketV1>,
    pub future_window: Option<FutureWindowObserverPacketV1>,
    pub signed_evidence: Option<SignedTargetHostEvidencePacketV1>,
    pub taskflow: Option<TaskFlowEventChainPacketV1>,
    pub learning_ledger: Option<LearningLedgerWitnessFrontierPacketV1>,
    pub independent_evaluator: Option<IndependentEvaluatorReceiptPacketV1>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ProductionResourceMeasurementV1 {
    pub operation: ProductionOwnerOperationReceiptV1,
    pub sample: CellSplitTargetResourceSampleV1,
    pub hardware_attestation_digest: String,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ProductionFutureWindowReceiptV1 {
    pub operation: ProductionOwnerOperationReceiptV1,
    pub baseline: BaselinePacketV1,
    pub future_window: FutureWindowObserverPacketV1,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ProductionSigningReceiptV1 {
    pub operation: ProductionOwnerOperationReceiptV1,
    pub evidence: SignedTargetHostEvidencePacketV1,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ProductionIndependentVerificationReceiptV1 {
    pub operation: ProductionOwnerOperationReceiptV1,
    pub evaluator: IndependentEvaluatorReceiptPacketV1,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ProductionHardwareAttestationReceiptV1 {
    pub operation: ProductionOwnerOperationReceiptV1,
    pub attestation_digest: String,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ProductionLedgerReplayReceiptV1 {
    pub operation: ProductionOwnerOperationReceiptV1,
    pub frontier: LearningLedgerWitnessFrontierPacketV1,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ProductionTaskFlowReplayReceiptV1 {
    pub operation: ProductionOwnerOperationReceiptV1,
    pub taskflow: TaskFlowEventChainPacketV1,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ProductionExternalErrorV1 {
    pub detail: String,
}

impl fmt::Display for ProductionExternalErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(&self.detail)
    }
}

pub trait ArtifactOwnerHandleV1: fmt::Debug + Send + Sync {
    fn binding(&self) -> &ProductionOwnerBindingV1;
    fn load_parent_child(
        &self,
        request: &ProductionOwnerRequestV1,
    ) -> Result<ProductionOwnerOperationReceiptV1, ProductionExternalErrorV1>;
}

pub trait CnsRouteOwnerHandleV1: fmt::Debug + Send + Sync {
    fn binding(&self) -> &ProductionOwnerBindingV1;
    fn cutover(
        &self,
        request: &ProductionOwnerRequestV1,
    ) -> Result<ProductionOwnerOperationReceiptV1, ProductionExternalErrorV1>;
    fn dispatch(
        &self,
        request: &ProductionOwnerRequestV1,
    ) -> Result<ProductionOwnerOperationReceiptV1, ProductionExternalErrorV1>;
    fn reject_old_generation(
        &self,
        request: &ProductionOwnerRequestV1,
    ) -> Result<ProductionOwnerOperationReceiptV1, ProductionExternalErrorV1>;
    fn rollback_route(
        &self,
        request: &ProductionOwnerRequestV1,
    ) -> Result<ProductionOwnerOperationReceiptV1, ProductionExternalErrorV1>;
}

pub trait FaultInjectorOwnerHandleV1: fmt::Debug + Send + Sync {
    fn binding(&self) -> &ProductionOwnerBindingV1;
    fn clean_restart(
        &self,
        request: &ProductionOwnerRequestV1,
    ) -> Result<ProductionOwnerOperationReceiptV1, ProductionExternalErrorV1>;
    fn approved_power_loss(
        &self,
        request: &ProductionOwnerRequestV1,
    ) -> Result<ProductionOwnerOperationReceiptV1, ProductionExternalErrorV1>;
    fn recover(
        &self,
        request: &ProductionOwnerRequestV1,
    ) -> Result<ProductionOwnerOperationReceiptV1, ProductionExternalErrorV1>;
}

pub trait TombstoneOwnerHandleV1: fmt::Debug + Send + Sync {
    fn binding(&self) -> &ProductionOwnerBindingV1;
    fn commit_tombstone(
        &self,
        request: &ProductionOwnerRequestV1,
    ) -> Result<ProductionOwnerOperationReceiptV1, ProductionExternalErrorV1>;
    fn verify_no_resurrection(
        &self,
        request: &ProductionOwnerRequestV1,
    ) -> Result<ProductionOwnerOperationReceiptV1, ProductionExternalErrorV1>;
}

pub trait TaskFlowOwnerHandleV1: fmt::Debug + Send + Sync {
    fn binding(&self) -> &ProductionOwnerBindingV1;
    fn run(
        &self,
        request: &ProductionOwnerRequestV1,
    ) -> Result<ProductionOwnerOperationReceiptV1, ProductionExternalErrorV1>;
    fn replay(
        &self,
        request: &ProductionOwnerRequestV1,
    ) -> Result<ProductionTaskFlowReplayReceiptV1, ProductionExternalErrorV1>;
}

pub trait HostTelemetryOwnerHandleV1: fmt::Debug + Send + Sync {
    fn binding(&self) -> &ProductionOwnerBindingV1;
    fn sample(
        &self,
        request: &ProductionOwnerRequestV1,
    ) -> Result<Vec<ProductionResourceMeasurementV1>, ProductionExternalErrorV1>;
}

pub trait HardwareAttestationOwnerHandleV1: fmt::Debug + Send + Sync {
    fn binding(&self) -> &ProductionOwnerBindingV1;
    fn attest(
        &self,
        request: &ProductionOwnerRequestV1,
    ) -> Result<ProductionHardwareAttestationReceiptV1, ProductionExternalErrorV1>;
}

pub trait LearningLedgerOwnerHandleV1: fmt::Debug + Send + Sync {
    fn binding(&self) -> &ProductionOwnerBindingV1;
    fn append_witness(
        &self,
        request: &ProductionOwnerRequestV1,
    ) -> Result<ProductionOwnerOperationReceiptV1, ProductionExternalErrorV1>;
    fn replay(
        &self,
        request: &ProductionOwnerRequestV1,
    ) -> Result<ProductionLedgerReplayReceiptV1, ProductionExternalErrorV1>;
}

pub trait FutureWindowEvaluatorOwnerHandleV1: fmt::Debug + Send + Sync {
    fn binding(&self) -> &ProductionOwnerBindingV1;
    fn evaluate(
        &self,
        request: &ProductionOwnerRequestV1,
    ) -> Result<ProductionFutureWindowReceiptV1, ProductionExternalErrorV1>;
    fn independently_verify(
        &self,
        request: &ProductionOwnerRequestV1,
    ) -> Result<ProductionIndependentVerificationReceiptV1, ProductionExternalErrorV1>;
}

pub trait EvidenceSigningOwnerHandleV1: fmt::Debug + Send + Sync {
    fn binding(&self) -> &ProductionOwnerBindingV1;
    fn sign_host_and_observer(
        &self,
        request: &ProductionOwnerRequestV1,
    ) -> Result<ProductionSigningReceiptV1, ProductionExternalErrorV1>;
    fn verify_signatures(
        &self,
        request: &ProductionOwnerRequestV1,
    ) -> Result<ProductionOwnerOperationReceiptV1, ProductionExternalErrorV1>;
}

/// Non-secret composition inputs.  Private keys, credentials and tokens are
/// intentionally absent; the signing owner receives only a digest-bound request.
#[derive(Default)]
pub struct ProductionTargetHostRuntimeConfig {
    pub split_id: String,
    pub namespace: String,
    pub target_host_id: String,
    pub target_host_nonce: String,
    pub parent_generation: u64,
    pub child_generation: u64,
    pub parent_artifact_digest: String,
    pub child_artifact_digest: String,
    pub parameter_bundle_digest: String,
    pub migration_digest: String,
    pub trust_root_digest: String,
    pub approved_power_loss: bool,
    pub minimum_future_window_samples: u64,
    pub artifact_owner: Option<Arc<dyn ArtifactOwnerHandleV1>>,
    pub route_owner: Option<Arc<dyn CnsRouteOwnerHandleV1>>,
    pub fault_injector: Option<Arc<dyn FaultInjectorOwnerHandleV1>>,
    pub tombstone_owner: Option<Arc<dyn TombstoneOwnerHandleV1>>,
    pub taskflow_owner: Option<Arc<dyn TaskFlowOwnerHandleV1>>,
    pub telemetry_owner: Option<Arc<dyn HostTelemetryOwnerHandleV1>>,
    pub hardware_attestation_owner: Option<Arc<dyn HardwareAttestationOwnerHandleV1>>,
    pub learning_ledger_owner: Option<Arc<dyn LearningLedgerOwnerHandleV1>>,
    pub future_window_evaluator_owner: Option<Arc<dyn FutureWindowEvaluatorOwnerHandleV1>>,
    pub evidence_signing_owner: Option<Arc<dyn EvidenceSigningOwnerHandleV1>>,
}

impl fmt::Debug for ProductionTargetHostRuntimeConfig {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("ProductionTargetHostRuntimeConfig")
            .field("split_id", &self.split_id)
            .field("namespace", &self.namespace)
            .field("target_host_id", &self.target_host_id)
            .field("parent_generation", &self.parent_generation)
            .field("child_generation", &self.child_generation)
            .field("child_artifact_digest", &self.child_artifact_digest)
            .field("parameter_bundle_digest", &self.parameter_bundle_digest)
            .field("migration_digest", &self.migration_digest)
            .field("trust_root_digest", &self.trust_root_digest)
            .field("approved_power_loss", &self.approved_power_loss)
            .field(
                "minimum_future_window_samples",
                &self.minimum_future_window_samples,
            )
            .finish_non_exhaustive()
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum CellSplitTargetHostRuntimeErrorV1 {
    MissingExternalInput {
        input: &'static str,
    },
    UnboundOwner {
        owner: &'static str,
        namespace: String,
    },
    InvalidConfiguration(&'static str),
    WrongTrustRoot {
        owner: &'static str,
    },
    InvalidTransition {
        expected: CellSplitProductionLifecycleStepV1,
        actual: Option<CellSplitProductionLifecycleStepV1>,
    },
    PredecessorReceiptMissing {
        step: CellSplitProductionLifecycleStepV1,
    },
    ReceiptMismatch {
        step: CellSplitProductionLifecycleStepV1,
        detail: &'static str,
    },
    IdempotencyConflict {
        operation_id: String,
    },
    PowerLossNotApproved,
    ResourceSampleMissing,
    FutureWindowInsufficient {
        observed: u64,
        minimum: u64,
    },
    ObserverSignatureMismatch,
    ReplayChainGap,
    TombstoneMissing,
    External {
        owner: &'static str,
        detail: String,
    },
    Aborted {
        step: CellSplitProductionLifecycleStepV1,
    },
}

impl fmt::Display for CellSplitTargetHostRuntimeErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::MissingExternalInput { input } => {
                write!(formatter, "missing external input: {input}")
            }
            Self::UnboundOwner { owner, namespace } => {
                write!(formatter, "unbound owner {owner} for namespace {namespace}")
            }
            Self::InvalidConfiguration(detail) => write!(
                formatter,
                "invalid production adapter configuration: {detail}"
            ),
            Self::WrongTrustRoot { owner } => {
                write!(formatter, "owner {owner} is bound to the wrong trust root")
            }
            Self::InvalidTransition { expected, actual } => write!(
                formatter,
                "invalid lifecycle transition: expected {expected:?}, actual {actual:?}"
            ),
            Self::PredecessorReceiptMissing { step } => {
                write!(formatter, "missing predecessor receipt before {step:?}")
            }
            Self::ReceiptMismatch { step, detail } => {
                write!(formatter, "receipt mismatch at {step:?}: {detail}")
            }
            Self::IdempotencyConflict { operation_id } => write!(
                formatter,
                "idempotency conflict for operation {operation_id}"
            ),
            Self::PowerLossNotApproved => {
                formatter.write_str("approved power-loss witness is missing")
            }
            Self::ResourceSampleMissing => formatter.write_str("resource sample is missing"),
            Self::FutureWindowInsufficient { observed, minimum } => write!(
                formatter,
                "future window has {observed} observations; {minimum} required"
            ),
            Self::ObserverSignatureMismatch => {
                formatter.write_str("host/observer signature verification failed")
            }
            Self::ReplayChainGap => {
                formatter.write_str("TaskFlow or learning-ledger replay chain has a gap")
            }
            Self::TombstoneMissing => formatter.write_str("tombstone witness is missing"),
            Self::External { owner, detail } => write!(formatter, "owner {owner} failed: {detail}"),
            Self::Aborted { step } => write!(formatter, "lifecycle aborted at {step:?}"),
        }
    }
}

impl std::error::Error for CellSplitTargetHostRuntimeErrorV1 {}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CellSplitProductionBlockedPacketV1 {
    pub schema: String,
    pub split_id: String,
    pub target_host_id: String,
    pub blocked_inputs: Vec<String>,
    pub reason: String,
    pub production_evidence: bool,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CellSplitProductionLifecycleReceiptV1 {
    pub schema: String,
    pub split_id: String,
    pub target_host_id: String,
    pub final_step: CellSplitProductionLifecycleStepV1,
    pub receipt_chain_digest: String,
    pub production_evidence: bool,
    pub blocked_inputs: Vec<String>,
}
