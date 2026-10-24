//! Opt-in native decoder composition with the real NeuronRuntime transaction.

use std::sync::{Arc, Mutex};
use std::sync::atomic::AtomicU64;
use codex_hepta_memory::{CognitiveAccess, MemoryCellAdmissionV1, MemoryCellKeyV1,
    MemoryCellQueryV1, MemoryCellSourceClaimV1, MemoryCellUseReceiptV1, ProductionDurableWriter};
use codex_hepta_neuron::{FileAnchorWitnessStore, NeuronRuntime, NeuronRuntimeError,
    NeuronShadowOutputV1, NeuronTickInputV1, canonical_feature_vector_digest_v1};
use codex_hepta_types::{Digest32, StableId};
use tokio::sync::Semaphore;
use crate::native_memory_model::NativeMemoryModelPort;
use crate::native_memory_shadow_namespace::{NativeMemoryShadowFilesV1,
    NativeMemoryShadowProfileV1, open_runtime, reject, source_namespace};
use crate::native_memory_types::{NativeMemoryError, NativeMemoryExecutionV1, NativeMemoryModelConfigV1, query_features};

/// The host must read its actual objective/NDU authority. No source hash,
/// fixture context, or user prompt is substituted when this provider is absent.
pub trait NativeMemoryContextAuthorityV1: Send {
    fn current(&mut self) -> Result<NativeMemoryTickContextV1, NativeMemoryError>;
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NativeMemoryTickContextV1 {
    pub subject_id: StableId,
    pub objective_digest: Digest32,
    pub ndu_snapshot_digest: Digest32,
    pub monotonic_time_micros: u64,
    pub body_generation: Option<u64>,
    pub modulator_digest: Option<Digest32>,
}

impl NativeMemoryTickContextV1 {
    fn matches(&self, input: &NeuronTickInputV1) -> bool {
        self.subject_id == input.subject_id && self.objective_digest == input.objective_digest
            && self.ndu_snapshot_digest == input.ndu_snapshot_digest
            && self.body_generation == input.body_generation && self.modulator_digest == input.modulator_digest
    }
}

pub(crate) struct NativeShadowHostBinding {
    pub writer: Arc<ProductionDurableWriter>,
    pub access: CognitiveAccess,
    pub key: MemoryCellKeyV1,
    pub claim: MemoryCellSourceClaimV1,
    pub model: NativeMemoryModelConfigV1,
    pub dispatches: Arc<AtomicU64>,
    pub capacity: Arc<Semaphore>,
    pub cancellation: tokio_util::sync::CancellationToken,
}

struct PendingRead {
    admission: Arc<MemoryCellAdmissionV1>,
    input: NeuronTickInputV1,
    model: NativeMemoryModelPort,
}

struct ShadowState<C> {
    runtime: NeuronRuntime<FileAnchorWitnessStore>,
    context: C,
    pending: Option<PendingRead>,
    failed: bool,
}

pub struct AgentdNativeMemoryShadowOwner<C> {
    host: NativeShadowHostBinding,
    state: Mutex<ShadowState<C>>,
    namespace: Digest32,
    cell_id: StableId,
    subject: StableId,
    objective: Digest32,
    profile_digest: Digest32,
}

/// Both receipts came from the same admitted callback. The shadow observation
/// always abstains; this result is not a calibrated NeuronSignalReceiptV1.
pub struct NativeMemoryShadowReadV1 {
    pub observation: NeuronShadowOutputV1,
    pub execution: NativeMemoryExecutionV1,
    pub source: MemoryCellUseReceiptV1,
    admission: Arc<MemoryCellAdmissionV1>,
    input: NeuronTickInputV1,
}

impl<C: NativeMemoryContextAuthorityV1 + 'static> AgentdNativeMemoryShadowOwner<C> {
    pub(crate) async fn open(
        host: NativeShadowHostBinding,
        files: NativeMemoryShadowFilesV1,
        profile: NativeMemoryShadowProfileV1,
        mut context: C,
    ) -> Result<Arc<Self>, NativeMemoryError> {
        let current = context.current()?;
        if current.objective_digest.is_zero() || current.ndu_snapshot_digest.is_zero()
            || current.monotonic_time_micros == 0 || current.modulator_digest.is_some_and(Digest32::is_zero) {
            return Err(reject("live tick context is incomplete"));
        }
        let now = std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).map_err(reject)?.as_millis();
        let query = MemoryCellQueryV1 {
            request_id: StableId::new("memory-cell-shadow-install").map_err(reject)?,
            key: host.key.clone(), deadline_unix_ms: u64::try_from(now).map_err(reject)? + 300_000,
        };
        let source = host.writer.authorize_memory_cell(&host.access, &query, &host.claim).await?;
        let cell_id = profile.cell_id.clone();
        let (runtime, namespace) = open_runtime(files, profile, &host.model, &source,
            host.writer.owner_agent_id().as_str(), &current.subject_id, current.objective_digest)?;
        let profile_digest = runtime.shadow_profile().map_err(reject)?.semantic_digest().map_err(reject)?;
        Ok(Arc::new(Self { host, state: Mutex::new(ShadowState {
            runtime, context, pending: None, failed: false,
        }), namespace, cell_id, subject: current.subject_id, objective: current.objective_digest, profile_digest }))
    }

    /// One bounded callback at a time, sharing the original native cell's
    /// dispatch semaphore. Witness-only retry retains the same spent nonce.
    pub async fn read(self: &Arc<Self>, query: MemoryCellQueryV1) -> Result<NativeMemoryShadowReadV1, NativeMemoryError> {
        if query.key != self.host.key || self.host.cancellation.is_cancelled() {
            return Err(reject("closed owner or unknown typed key"));
        }
        let permit = Arc::clone(&self.host.capacity).try_acquire_owned().map_err(reject)?;
        let owner = Arc::clone(self);
        let handle = tokio::runtime::Handle::current();
        let (result, _permit) = tokio::task::spawn_blocking(move || {
            let mut state = owner.state.lock().map_err(reject)?;
            if state.failed { return Err(reject("shadow owner requires explicit recovery")); }
            if let Some(pending) = &state.pending
                && pending.admission.query() != &query {
                return Err(reject("pending witness requires the original admitted query"));
            }
            // Any incomplete operation other than a retained witness retry
            // stops this runtime. SQLite and the sparse journal are not one ACID transaction.
            state.failed = true;
            let current = state.context.current()?;
            if current.subject_id != owner.subject || current.objective_digest != owner.objective {
                return Err(reject("live subject/objective differs from enrolled journal"));
            }
            let mut job = match state.pending.take() {
                Some(job) => job,
                None => {
                    let admission = Arc::new(handle.block_on(owner.host.writer.admit_memory_cell(
                        &owner.host.access, &query, &owner.host.claim))?);
                    let actual_namespace = source_namespace(admission.binding(),
                        owner.host.writer.owner_agent_id().as_str(), &owner.subject, &owner.cell_id,
                        &owner.host.model, owner.profile_digest)?;
                    if actual_namespace != owner.namespace {
                        return Err(reject("source/profile namespace changed; fresh generation required"));
                    }
                    let anchor = state.runtime.current_anchor().map_err(reject)?;
                    let features = query_features(&query.key.question()?).map_err(reject)?;
                    let input = NeuronTickInputV1 {
                        tick_id: query.request_id.clone(), subject_id: current.subject_id.clone(),
                        logical_sequence: anchor.map_or(1, |a| a.sequence.saturating_add(1)),
                        monotonic_time_micros: current.monotonic_time_micros,
                        checkpoint_digest: anchor.map_or(Digest32::ZERO, |a| a.checkpoint_digest),
                        input_feature_digest: canonical_feature_vector_digest_v1(&features),
                        feature_vector_q24: features, objective_digest: current.objective_digest,
                        ndu_snapshot_digest: current.ndu_snapshot_digest, body_generation: current.body_generation,
                        modulator_digest: current.modulator_digest,
                    };
                    let mut model = NativeMemoryModelPort::new(Arc::clone(&owner.host.writer), Arc::clone(&admission),
                        owner.host.model.clone(), handle.clone(), Arc::clone(&owner.host.dispatches), owner.host.cancellation.clone())?;
                    model.bind_tick(&input, &state.runtime.model_request(&input).map_err(reject)?)?;
                    PendingRead { admission, input, model }
                }
            };
            if !current.matches(&job.input) { return Err(reject("live context changed before witness reconciliation")); }
            handle.block_on(owner.host.writer.revalidate_memory_cell(&job.admission))?;
            let observation = match state.runtime.tick_shadow(&mut job.model, job.input.clone()) {
                Ok(output) => output,
                Err(error @ NeuronRuntimeError::WitnessAfterCommit { .. }) => {
                    state.pending = Some(job);
                    state.failed = false;
                    return Err(reject(error));
                }
                Err(error) => return Err(reject(error)),
            };
            if !state.context.current()?.matches(&job.input) { return Err(reject("live context changed during model execution")); }
            let execution = job.model.take_execution()?;
            let execution_bytes = serde_json::to_vec(&execution).map_err(reject)?;
            let source = handle.block_on(owner.host.writer.finish_memory_cell(
                &job.admission, Digest32::of_bytes(&execution_bytes)))?;
            handle.block_on(owner.host.writer.revalidate_memory_cell_source(&job.admission))?;
            state.failed = false;
            Ok((NativeMemoryShadowReadV1 { observation, execution, source, admission: job.admission, input: job.input }, permit))
        }).await.map_err(reject)??;
        // Check again after asynchronous handoff. A completed nonce remains
        // spent even when current-source delivery is now refused.
        self.revalidate_delivery(&result).await?;
        Ok(result)
    }

    pub async fn revalidate_delivery(&self, result: &NativeMemoryShadowReadV1) -> Result<(), NativeMemoryError> {
        let checked = async {
            if self.host.cancellation.is_cancelled() { return Err(reject("native owner is closed")); }
            let namespace = source_namespace(result.admission.binding(), self.host.writer.owner_agent_id().as_str(),
                &self.subject, &self.cell_id, &self.host.model, self.profile_digest)?;
            if namespace != self.namespace { return Err(reject("result belongs to another source/profile namespace")); }
            self.host.writer.revalidate_memory_cell_source(&result.admission).await?;
            let mut state = self.state.try_lock().map_err(reject)?;
            if state.failed || !state.context.current()?.matches(&result.input) {
                return Err(reject("live context no longer supports delivery"));
            }
            Ok(())
        }.await;
        if checked.is_err() {
            self.host.cancellation.cancel();
            if let Ok(mut state) = self.state.try_lock() { state.failed = true; }
        }
        checked
    }
}
