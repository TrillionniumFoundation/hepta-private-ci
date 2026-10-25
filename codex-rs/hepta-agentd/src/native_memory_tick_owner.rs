//! Opt-in native decoder composition with the real NeuronRuntime transaction.

#[path = "native_memory_current_model.rs"]
mod current_model;

use current_model::NativeCurrentModel;

use crate::native_memory_model::NativeMemoryModelPort;
use crate::native_memory_shadow_namespace::NativeMemoryJournalContext;
use crate::native_memory_shadow_namespace::NativeMemoryShadowFilesV1;
use crate::native_memory_shadow_namespace::NativeMemoryShadowProfileV1;
use crate::native_memory_shadow_namespace::open_runtime;
use crate::native_memory_shadow_namespace::reject;
use crate::native_memory_shadow_namespace::source_namespace;
use crate::native_memory_types::NativeMemoryError;
use crate::native_memory_types::NativeMemoryExecutionV1;
use crate::native_memory_types::NativeMemoryModelConfigV1;
use crate::native_memory_types::query_features;
use codex_hepta_memory::CognitiveAccess;
use codex_hepta_memory::MemoryCellAdmissionV1;
use codex_hepta_memory::MemoryCellKeyV1;
use codex_hepta_memory::MemoryCellQueryV1;
use codex_hepta_memory::MemoryCellSourceClaimV1;
use codex_hepta_memory::MemoryCellUseReceiptV1;
use codex_hepta_memory::ProductionDurableWriter;
use codex_hepta_neuron::FileAnchorWitnessStore;
use codex_hepta_neuron::NeuronRuntime;
use codex_hepta_neuron::NeuronRuntimeError;
use codex_hepta_neuron::NeuronShadowOutputV1;
use codex_hepta_neuron::NeuronTickInputV1;
use codex_hepta_neuron::canonical_feature_vector_digest_v1;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::atomic::AtomicU64;
use tokio::sync::Semaphore;

/// The host must read its actual objective/NDU authority. No source hash,
/// fixture context, or user prompt is substituted when this provider is absent.
pub trait NativeMemoryContextAuthorityV1: Send {
    fn current(&mut self) -> Result<NativeMemoryTickContextV1, NativeMemoryError>;

    /// Stable identity of the checked owners; unbound contexts are reserved for
    /// the explicit qualification profile and cannot enroll a production owner.
    fn binding(&self) -> Option<&crate::NativeMemoryContextBindingV1> {
        None
    }

    fn validate_query(&self, _query: &MemoryCellQueryV1) -> Result<(), NativeMemoryError> {
        Ok(())
    }
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
        self.subject_id == input.subject_id
            && self.objective_digest == input.objective_digest
            && self.ndu_snapshot_digest == input.ndu_snapshot_digest
            && self.body_generation == input.body_generation
            && self.modulator_digest == input.modulator_digest
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
    context_binding: Option<crate::NativeMemoryContextBindingV1>,
}

/// Both receipts came from the same admitted callback. The shadow observation
/// always abstains; this result is not a calibrated NeuronSignalReceiptV1.
pub struct NativeMemoryShadowReadV1 {
    observation: NeuronShadowOutputV1,
    execution: NativeMemoryExecutionV1,
    source: MemoryCellUseReceiptV1,
    namespace: Digest32,
    admission: Arc<MemoryCellAdmissionV1>,
    input: NeuronTickInputV1,
    context_binding: Option<crate::NativeMemoryContextBindingV1>,
}

impl NativeMemoryShadowReadV1 {
    pub fn observation(&self) -> &NeuronShadowOutputV1 {
        &self.observation
    }
    pub fn execution(&self) -> &NativeMemoryExecutionV1 {
        &self.execution
    }
    pub fn source(&self) -> &MemoryCellUseReceiptV1 {
        &self.source
    }
    pub fn context_binding(&self) -> Option<&crate::NativeMemoryContextBindingV1> {
        self.context_binding.as_ref()
    }
}

impl<C: NativeMemoryContextAuthorityV1 + 'static> AgentdNativeMemoryShadowOwner<C> {
    #[cfg(feature = "qualification-cognitive-write")]
    pub(crate) async fn open(
        host: NativeShadowHostBinding,
        files: NativeMemoryShadowFilesV1,
        profile: NativeMemoryShadowProfileV1,
        context: C,
    ) -> Result<Arc<Self>, NativeMemoryError> {
        let now = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map_err(reject)?
            .as_millis();
        let query = MemoryCellQueryV1 {
            request_id: StableId::new("memory-cell-shadow-install").map_err(reject)?,
            key: host.key.clone(),
            deadline_unix_ms: u64::try_from(now).map_err(reject)? + 300_000,
        };
        Self::open_for_query(host, files, profile, context, &query).await
    }

    pub(crate) async fn open_for_query(
        host: NativeShadowHostBinding,
        files: NativeMemoryShadowFilesV1,
        profile: NativeMemoryShadowProfileV1,
        mut context: C,
        query: &MemoryCellQueryV1,
    ) -> Result<Arc<Self>, NativeMemoryError> {
        if query.key != host.key || host.cancellation.is_cancelled() {
            return Err(reject("closed owner or unknown typed key"));
        }
        context.validate_query(query)?;
        let current = context.current()?;
        let context_binding = context.binding().cloned();
        if context_binding.is_none() && !cfg!(feature = "qualification-cognitive-write") {
            return Err(reject("production shadow requires checked current owners"));
        }
        if current.objective_digest.is_zero()
            || current.ndu_snapshot_digest.is_zero()
            || current.monotonic_time_micros == 0
            || current.modulator_digest.is_some_and(Digest32::is_zero)
        {
            return Err(reject("live tick context is incomplete"));
        }
        let source = host
            .writer
            .authorize_memory_cell(&host.access, query, &host.claim)
            .await?;
        let after_source = context.current()?;
        if after_source.subject_id != current.subject_id
            || after_source.objective_digest != current.objective_digest
            || after_source.ndu_snapshot_digest != current.ndu_snapshot_digest
            || after_source.body_generation != current.body_generation
            || after_source.modulator_digest != current.modulator_digest
            || after_source.monotonic_time_micros < current.monotonic_time_micros
            || context.binding() != context_binding.as_ref()
        {
            return Err(reject(
                "current context changed during source authorization",
            ));
        }
        let cell_id = profile.cell_id.clone();
        let (runtime, namespace) = open_runtime(
            files,
            profile,
            &host.model,
            &source,
            host.writer.owner_agent_id().as_str(),
            NativeMemoryJournalContext {
                subject: &current.subject_id,
                objective: current.objective_digest,
                binding: context_binding.as_ref(),
            },
        )?;
        let profile_digest = runtime
            .shadow_profile()
            .map_err(reject)?
            .semantic_digest()
            .map_err(reject)?;
        Ok(Arc::new(Self {
            host,
            state: Mutex::new(ShadowState {
                runtime,
                context,
                pending: None,
                failed: false,
            }),
            namespace,
            cell_id,
            subject: current.subject_id,
            objective: current.objective_digest,
            profile_digest,
            context_binding,
        }))
    }

    /// One bounded callback at a time, sharing the original native cell's
    /// dispatch semaphore. Witness-only retry retains the same spent nonce.
    pub async fn read(
        self: &Arc<Self>,
        query: MemoryCellQueryV1,
    ) -> Result<NativeMemoryShadowReadV1, NativeMemoryError> {
        if query.key != self.host.key || self.host.cancellation.is_cancelled() {
            return Err(reject("closed owner or unknown typed key"));
        }
        let permit = Arc::clone(&self.host.capacity)
            .try_acquire_owned()
            .map_err(reject)?;
        let owner = Arc::clone(self);
        let handle = tokio::runtime::Handle::current();
        let (result, _permit) = tokio::task::spawn_blocking(move || {
            let mut state = owner.state.lock().map_err(reject)?;
            if state.failed {
                return Err(reject("shadow owner requires explicit recovery"));
            }
            state.context.validate_query(&query)?;
            if let Some(pending) = &state.pending
                && pending.admission.query() != &query
            {
                return Err(reject(
                    "pending witness requires the original admitted query",
                ));
            }
            // Any incomplete operation other than a retained witness retry
            // stops this runtime. SQLite and the sparse journal are not one ACID transaction.
            state.failed = true;
            let current = state.context.current()?;
            if state.context.binding() != owner.context_binding.as_ref() {
                return Err(reject(
                    "current owner binding differs from enrolled journal",
                ));
            }
            if current.subject_id != owner.subject || current.objective_digest != owner.objective {
                return Err(reject(
                    "live subject/objective differs from enrolled journal",
                ));
            }
            let mut job = match state.pending.take() {
                Some(job) => job,
                None => {
                    let admission =
                        Arc::new(handle.block_on(owner.host.writer.admit_memory_cell(
                            &owner.host.access,
                            &query,
                            &owner.host.claim,
                        ))?);
                    let actual_namespace = source_namespace(
                        admission.binding(),
                        owner.host.writer.owner_agent_id().as_str(),
                        &owner.subject,
                        &owner.cell_id,
                        &owner.host.model,
                        owner.profile_digest,
                        owner.context_binding.as_ref(),
                    )?;
                    if actual_namespace != owner.namespace {
                        return Err(reject(
                            "source/profile namespace changed; fresh generation required",
                        ));
                    }
                    let anchor = state.runtime.current_anchor().map_err(reject)?;
                    let features = query_features(&query.key.question()?).map_err(reject)?;
                    let input = NeuronTickInputV1 {
                        tick_id: query.request_id.clone(),
                        subject_id: current.subject_id.clone(),
                        logical_sequence: anchor.map_or(1, |a| a.sequence.saturating_add(1)),
                        monotonic_time_micros: current.monotonic_time_micros,
                        checkpoint_digest: anchor.map_or(Digest32::ZERO, |a| a.checkpoint_digest),
                        input_feature_digest: canonical_feature_vector_digest_v1(&features),
                        feature_vector_q24: features,
                        objective_digest: current.objective_digest,
                        ndu_snapshot_digest: current.ndu_snapshot_digest,
                        body_generation: current.body_generation,
                        modulator_digest: current.modulator_digest,
                    };
                    let mut model = NativeMemoryModelPort::new(
                        Arc::clone(&owner.host.writer),
                        Arc::clone(&admission),
                        owner.host.model.clone(),
                        handle.clone(),
                        Arc::clone(&owner.host.dispatches),
                        owner.host.cancellation.clone(),
                    )?;
                    model.bind_tick(
                        &input,
                        &state.runtime.model_request(&input).map_err(reject)?,
                    )?;
                    PendingRead {
                        admission,
                        input,
                        model,
                    }
                }
            };
            if !current.matches(&job.input) {
                return Err(reject("live context changed before witness reconciliation"));
            }
            handle.block_on(owner.host.writer.revalidate_memory_cell(&job.admission))?;
            let tick = {
                let ShadowState {
                    runtime, context, ..
                } = &mut *state;
                let mut model = NativeCurrentModel {
                    inner: &mut job.model,
                    context,
                    input: &job.input,
                    binding: owner.context_binding.as_ref(),
                };
                runtime.tick_shadow(&mut model, job.input.clone())
            };
            let observation = match tick {
                Ok(output) => output,
                Err(error @ NeuronRuntimeError::WitnessAfterCommit { .. }) => {
                    state.pending = Some(job);
                    state.failed = false;
                    return Err(reject(error));
                }
                Err(error) => return Err(reject(error)),
            };
            if !state.context.current()?.matches(&job.input)
                || state.context.binding() != owner.context_binding.as_ref()
            {
                return Err(reject("live context changed during model execution"));
            }
            let execution = job.model.take_execution()?;
            let execution_bytes = serde_json::to_vec(&execution).map_err(reject)?;
            let source = handle.block_on(
                owner
                    .host
                    .writer
                    .finish_memory_cell(&job.admission, Digest32::of_bytes(&execution_bytes)),
            )?;
            handle.block_on(
                owner
                    .host
                    .writer
                    .revalidate_memory_cell_source(&job.admission),
            )?;
            state.failed = false;
            Ok((
                NativeMemoryShadowReadV1 {
                    observation,
                    execution,
                    source,
                    namespace: owner.namespace,
                    admission: job.admission,
                    input: job.input,
                    context_binding: owner.context_binding.clone(),
                },
                permit,
            ))
        })
        .await
        .map_err(reject)??;
        // Check again after asynchronous handoff. A completed nonce remains
        // spent even when current-source delivery is now refused.
        self.revalidate_delivery(&result).await?;
        Ok(result)
    }

    pub async fn revalidate_delivery(
        &self,
        result: &NativeMemoryShadowReadV1,
    ) -> Result<(), NativeMemoryError> {
        let checked = async {
            if self.host.cancellation.is_cancelled() {
                return Err(reject("native owner is closed"));
            }
            if result.namespace != self.namespace || result.context_binding != self.context_binding
            {
                return Err(reject("result belongs to another enrolled owner namespace"));
            }
            let namespace = source_namespace(
                result.admission.binding(),
                self.host.writer.owner_agent_id().as_str(),
                &self.subject,
                &self.cell_id,
                &self.host.model,
                self.profile_digest,
                self.context_binding.as_ref(),
            )?;
            if namespace != self.namespace {
                return Err(reject("result belongs to another source/profile namespace"));
            }
            self.host
                .writer
                .revalidate_memory_cell_source(&result.admission)
                .await?;
            let mut state = self.state.try_lock().map_err(reject)?;
            state.context.validate_query(result.admission.query())?;
            if state.failed
                || !state.context.current()?.matches(&result.input)
                || state.context.binding() != self.context_binding.as_ref()
            {
                return Err(reject("live context no longer supports delivery"));
            }
            Ok(())
        }
        .await;
        if checked.is_err() {
            self.host.cancellation.cancel();
            if let Ok(mut state) = self.state.try_lock() {
                state.failed = true;
            }
        }
        checked
    }
}

#[cfg(all(test, feature = "qualification-cognitive-write"))]
#[path = "native_memory_tick_owner_tests.rs"]
mod tests;

