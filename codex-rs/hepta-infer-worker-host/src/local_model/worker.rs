use std::collections::{BTreeMap, BTreeSet};
use std::sync::{Arc, Mutex};

use codex_hepta_infer_core::durable_control::{
    Assignment, DurableInferenceControl, InferenceRequest as DurableRequest,
    RequestRecord, RequestState, Reservation as DurableReservation,
    TerminalObservation,
};
use tokio_util::sync::CancellationToken;

use super::{
    digest, validate_digest, validate_identity, AttestedModelHandle,
    DriverLoadEvidence, DriverRunEvidence, DriverTerminalStatus, Error,
    HostResourceObservation, LocalModelDriver, ModelManifestEvidence,
    OperationId, RequestReservation, ResourceManager, TrustedClock,
    TrustedResourceObserver, VerifiedInput, VerifiedModelManifest,
    VerifiedResourceGrant, MAX_TOKENS,
};

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum LoadedModelState {
    Ready,
    Unloading,
    RepairRequired,
}

#[derive(Clone, Debug)]
struct LoadedModel {
    manifest: VerifiedModelManifest,
    handle: AttestedModelHandle,
    state: LoadedModelState,
    active_operations: BTreeSet<String>,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum LocalRunStatus {
    Succeeded,
    Failed,
    Cancelled,
    Indeterminate,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct LocalRunReceipt {
    pub operation_id: String,
    pub status: LocalRunStatus,
    pub output_digest: Option<String>,
    pub consumed_tokens: Option<u32>,
    pub terminal_observed: bool,
    /// Always false. Existing durable assignments are inspect-only.
    pub replayed_provider: bool,
    pub stop_reason: Option<String>,
}

pub struct DurableLocalWorker<D, O, C> {
    worker_id: String,
    generation: u64,
    driver: Arc<D>,
    observer: Arc<O>,
    clock: C,
    resources: ResourceManager,
    models: Arc<Mutex<BTreeMap<String, LoadedModel>>>,
}


include!("worker_construct.rs");
include!("worker_models.rs");
include!("worker_execute.rs");
include!("worker_reconcile.rs");
include!("worker_state.rs");
include!("worker_helpers.rs");
