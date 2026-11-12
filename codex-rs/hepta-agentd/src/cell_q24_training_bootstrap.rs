//! Deferred original Trainer bootstrap. The host retains original files,
//! witnesses and Generator custody before Dataset exists. No future Dataset
//! head or signing payload is accepted; only an actual original read can bind
//! the native job. All connections share one non-resettable bootstrap state.
use std::fs::File;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::atomic::AtomicBool;

use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::TrustedLearningSignerV1;
use codex_hepta_neuron::AnchorWitnessStore;
use ed25519_dalek::SigningKey;
use tokio::runtime::Handle;
use tokio::sync::Semaphore;

use super::OriginalCellQ24TrainingCommandErrorV1;
use super::OriginalCellQ24TrainingCommandOwnerV1;
use super::now;
use crate::CellQ24SgdRuleV1;
use crate::CellQ24TrainingOwnerErrorV1;
use crate::LearningIterationEvidenceClientV1;
use crate::LoadedCellQ24ModelV1;
use crate::OriginalCellQ24DatasetCommandReadbackV1;
use crate::OriginalCellQ24MaterialCommandErrorV1;
use crate::OriginalCellQ24MaterialReceiptConfigV1;
use crate::OriginalCellQ24MaterialSourceConnectionV1;
use crate::OriginalCellQ24MaterialSourceErrorV1;
use crate::OriginalCellQ24TrainingReceiptErrorV1;
use crate::OriginalCellQ24TrainingSourceErrorV1;
use crate::OriginalCellQ24TrainingStageErrorV1;

#[path = "cell_q24_training_bootstrap_build.rs"]
mod build;
#[path = "cell_q24_model_command_host.rs"]
pub(super) mod model_host;
#[path = "cell_q24_training_bootstrap_service.rs"]
mod serving;

#[derive(Debug, thiserror::Error)]
pub enum OriginalCellQ24TrainingBootstrapErrorV1 {
    #[error("original Trainer bootstrap binding: {0}")]
    Binding(&'static str),
    #[error("original Trainer bootstrap is busy or poisoned")]
    Busy,
    #[error("original Trainer bootstrap may have initialized original owners")]
    Uncertain,
    #[error("original Trainer command: {0}")]
    Command(#[from] OriginalCellQ24TrainingCommandErrorV1),
    #[error("original Material Dataset: {0}")]
    Material(#[from] OriginalCellQ24MaterialCommandErrorV1),
    #[error("original Material connection: {0}")]
    Connection(#[from] OriginalCellQ24MaterialSourceErrorV1),
    #[error("original live source: {0}")]
    Source(#[from] OriginalCellQ24TrainingSourceErrorV1),
    #[error("original native trainer: {0}")]
    Native(#[from] CellQ24TrainingOwnerErrorV1),
    #[error("original Generator receipt owner: {0}")]
    Receipt(#[from] OriginalCellQ24TrainingReceiptErrorV1),
    #[error("original SourceBound stage: {0}")]
    Stage(#[from] OriginalCellQ24TrainingStageErrorV1),
}

type Error = OriginalCellQ24TrainingBootstrapErrorV1;

/// Original Root/Material context only: no future Dataset or raw training data.
#[derive(Clone)]
pub struct OriginalCellQ24TrainingBootstrapConfigV1 {
    pub material: OriginalCellQ24MaterialReceiptConfigV1,
    pub optimizer: CellQ24SgdRuleV1,
    pub generator: TrustedLearningSignerV1,
    pub maximum_signature_lifetime_seconds: u64,
}

/// One original host transfer. Every connection was bound when supplied;
// neither delayed bootstrap nor cold recovery opens a path or restarts a peer.
pub struct OriginalCellQ24TrainingBootstrapCustodyV1<TW: AnchorWitnessStore, RW: AnchorWitnessStore>
{
    pub native_file: File,
    pub native_witness: TW,
    pub receipt_file: File,
    pub receipt_witness: RW,
    pub generator_key: SigningKey,
    pub baseline: Arc<LoadedCellQ24ModelV1>,
    pub material_source: OriginalCellQ24MaterialSourceConnectionV1,
    pub experience: LearningIterationEvidenceClientV1,
    pub dataset: LearningIterationEvidenceClientV1,
}

#[derive(Clone, Copy)]
enum Origin {
    Fresh,
    Recovered,
}

enum State<TW: AnchorWitnessStore, RW: AnchorWitnessStore> {
    Awaiting(OriginalCellQ24TrainingBootstrapCustodyV1<TW, RW>),
    Starting,
    Ready(Arc<OriginalCellQ24TrainingCommandOwnerV1<TW, RW>>),
    Fenced,
}

pub struct OriginalCellQ24TrainingBootstrapOwnerV1<TW: AnchorWitnessStore, RW: AnchorWitnessStore> {
    config: OriginalCellQ24TrainingBootstrapConfigV1,
    dataset: Arc<OriginalCellQ24DatasetCommandReadbackV1>,
    state: Mutex<State<TW, RW>>,
    origin: Origin,
    cancellation: Arc<AtomicBool>,
    runtime: Handle,
    bootstrap_lane: Semaphore,
    model_host_bound: AtomicBool,
    connections: Arc<Semaphore>,
    #[cfg(test)]
    writer_gate: Mutex<Option<tests::support::WriterGate>>,
}

impl<TW: AnchorWitnessStore + Send + 'static, RW: AnchorWitnessStore + Send + 'static>
    OriginalCellQ24TrainingBootstrapOwnerV1<TW, RW>
{
    /// Consume original host custody without reading a future Dataset or
    /// initializing either native or receipt journal. No key is generated.
    pub fn from_original_custody(
        custody: OriginalCellQ24TrainingBootstrapCustodyV1<TW, RW>,
        config: OriginalCellQ24TrainingBootstrapConfigV1,
        dataset: OriginalCellQ24DatasetCommandReadbackV1,
        cancellation: Arc<AtomicBool>,
    ) -> Result<Self, Error> {
        Self::bind_original_custody(custody, config, dataset, cancellation, Origin::Fresh)
    }

    /// Cold bootstrap is permanently readback-only. Native recovery keeps its
    /// existing minimum-anchor reconciliation semantics; it is not advertised
    /// as a strict no-write reopen. Missing owners are never initialized here.
    pub fn recover_original_custody(
        custody: OriginalCellQ24TrainingBootstrapCustodyV1<TW, RW>,
        config: OriginalCellQ24TrainingBootstrapConfigV1,
        dataset: OriginalCellQ24DatasetCommandReadbackV1,
        cancellation: Arc<AtomicBool>,
    ) -> Result<Self, Error> {
        Self::bind_original_custody(custody, config, dataset, cancellation, Origin::Recovered)
    }

    fn bind_original_custody(
        custody: OriginalCellQ24TrainingBootstrapCustodyV1<TW, RW>,
        config: OriginalCellQ24TrainingBootstrapConfigV1,
        dataset: OriginalCellQ24DatasetCommandReadbackV1,
        cancellation: Arc<AtomicBool>,
        origin: Origin,
    ) -> Result<Self, Error> {
        OriginalCellQ24DatasetCommandReadbackV1::require_initial_context(
            &dataset,
            &config.material,
        )?;
        OriginalCellQ24MaterialSourceConnectionV1::require_initial_context(
            &custody.material_source,
            &config.material.initial,
            &config.material.scope,
            &custody.baseline,
        )?;
        let at = now()?;
        if custody.generator_key.verifying_key().to_bytes() != config.generator.verifying_key
            || config.generator.principal.principal_id != config.material.initial.owners.trainer
            || !(1..=86_400).contains(&config.maximum_signature_lifetime_seconds)
            || custody.baseline.components()
                != &config.material.initial.request.selected_bundle.components
        {
            return Err(Error::Binding("original Generator custody and baseline"));
        }
        config
            .material
            .verifier
            .require_signer_binding(LearningEvidenceRoleV1::Generator, &config.generator, at)
            .map_err(OriginalCellQ24TrainingCommandErrorV1::from)?;
        Ok(Self {
            config,
            dataset: Arc::new(dataset),
            state: Mutex::new(State::Awaiting(custody)),
            origin,
            cancellation,
            runtime: Handle::current(),
            bootstrap_lane: Semaphore::new(1),
            model_host_bound: AtomicBool::default(),
            connections: Arc::new(Semaphore::new(4)),
            #[cfg(test)]
            writer_gate: Mutex::new(None),
        })
    }
}

#[cfg(test)]
#[path = "cell_q24_training_bootstrap_tests.rs"]
mod tests;
