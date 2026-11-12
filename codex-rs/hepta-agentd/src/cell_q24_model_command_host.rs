//! The original host consumes one Model File/witness and one already bound
//! Evaluator material connection. No new key, path open or callback exists.
//! The retained Bootstrap is shared only inside this original process.
use super::super::OriginalCellQ24TrainingCommandOwnerV1;
use super::super::model_command::OriginalCellQ24ModelCommandErrorV1 as Error;
use super::super::model_command::OriginalCellQ24ModelCommandReceiptV1;
use super::super::model_command::context::Context;
use super::super::model_command::now;
use super::super::model_command::require_clock;
use super::Origin as BootstrapOrigin;
use super::OriginalCellQ24TrainingBootstrapOwnerV1;
use crate::CellQ24ModelProposalOwnerV1;
use crate::OriginalCellEvaluationModelMaterialClientV1;
use crate::OriginalCellEvaluationModelMaterialConnectionV1;
use crate::OriginalCellEvaluationModelMaterialV1;
use crate::OriginalCellEvaluationModelReadV1;
use crate::OriginalCellQ24MaterialCommandReceiptV1;
use crate::OriginalCellQ24TrainingCommandReceiptV1;
use crate::OriginalCellEvaluationPanelRegistrationV1;
use crate::OriginalCellQ24DatasetCommandReadbackV1;
use codex_hepta_neuron::FileAnchorWitnessStore;
use std::fs::File;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::atomic::Ordering;
use tokio::runtime::Handle;
use tokio::sync::Semaphore;

type Bootstrap =
    OriginalCellQ24TrainingBootstrapOwnerV1<FileAnchorWitnessStore, FileAnchorWitnessStore>;
type Trainer =
    OriginalCellQ24TrainingCommandOwnerV1<FileAnchorWitnessStore, FileAnchorWitnessStore>;
type Model = CellQ24ModelProposalOwnerV1<FileAnchorWitnessStore>;
#[path = "cell_q24_model_command_effect.rs"]
mod effect;
#[path = "cell_q24_model_command_service.rs"]
mod service;
#[path = "cell_q24_model_read_host_operation.rs"]
mod read_operation;

enum Origin {
    Fresh,
    Recovered,
}
struct State {
    custody: Option<(File, FileAnchorWitnessStore)>,
    material_connection: Option<OriginalCellEvaluationModelMaterialConnectionV1>,
    material: Option<Arc<OriginalCellEvaluationModelMaterialClientV1>>,
    context: Option<Context>,
    model: Option<Model>,
    execution_requested: bool,
    fenced: bool,
    retained: Option<OriginalCellQ24ModelCommandReceiptV1>,
}
struct OriginalModelInputs {
    original: Arc<Trainer>,
    dataset: OriginalCellQ24MaterialCommandReceiptV1,
    training: OriginalCellQ24TrainingCommandReceiptV1,
    material: Arc<OriginalCellEvaluationModelMaterialClientV1>,
    started: u64,
}
pub struct OriginalCellQ24ModelCommandHostV1 {
    bootstrap: Arc<Bootstrap>,
    registration: OriginalCellEvaluationPanelRegistrationV1,
    state: Mutex<State>,
    runtime: Handle,
    connections: Arc<Semaphore>,
}
impl OriginalCellQ24ModelCommandHostV1 {
    /// Reserve this original Bootstrap's sole Model host before future T/E
    /// exists. Every subsequent connection shares the retained once/state.
    pub fn from_original_bootstrap(
        bootstrap: Arc<Bootstrap>,
        file: File,
        witness: FileAnchorWitnessStore,
        material: OriginalCellEvaluationModelMaterialConnectionV1,
        registration: OriginalCellEvaluationPanelRegistrationV1,
    ) -> Result<Self, Error> {
        if !matches!(bootstrap.origin, BootstrapOrigin::Fresh) {
            return Err(Error::ReadbackRequired);
        }
        Self::bind(
            bootstrap,
            file,
            witness,
            material,
            registration,
            Origin::Fresh,
        )
    }

    /// Explicit original-host deployment recovery, separate from all commands.
    /// It can acknowledge the old Model journal's already persisted suffix.
    /// It cannot fit, sign, claim a Model, create a missing owner, or enable Execute.
    pub async fn recover_original_bootstrap(
        bootstrap: Arc<Bootstrap>,
        file: File,
        witness: FileAnchorWitnessStore,
        material: OriginalCellEvaluationModelMaterialConnectionV1,
        registration: OriginalCellEvaluationPanelRegistrationV1,
    ) -> Result<Self, Error> {
        let host = Self::bind(
            bootstrap,
            file,
            witness,
            material,
            registration,
            Origin::Recovered,
        )?;
        tokio::task::spawn_blocking(move || {
            host.recover_deployment()?;
            Ok(host)
        })
        .await
        .map_err(|_| Error::CommitUncertain)?
    }

    fn bind(
        bootstrap: Arc<Bootstrap>,
        file: File,
        witness: FileAnchorWitnessStore,
        material: OriginalCellEvaluationModelMaterialConnectionV1,
        registration: OriginalCellEvaluationPanelRegistrationV1,
        origin: Origin,
    ) -> Result<Self, Error> {
        let config = &bootstrap.config.material;
        crate::OriginalCellQ24MaterialReceiptConfigV1::require_original_command_initial(config)?;
        material.require_initial(
            &config.initial,
            &config.scope,
            &registration,
            &config.verifier,
        )?;
        if config.initial.request.evaluation_profile != registration.evaluation_profile() {
            return Err(Error::Binding("same original pre-registered Model panel"));
        }
        // This bit is on the original shared Bootstrap, not a connection and
        // not a fresh constructor argument. It is never reset after failure.
        bootstrap
            .model_host_bound
            .compare_exchange(
                /*current*/ false,
                /*new*/ true,
                Ordering::AcqRel,
                Ordering::Acquire,
            )
            .map_err(|_| Error::ReadbackRequired)?;
        Ok(Self {
            bootstrap,
            registration,
            runtime: Handle::current(),
            connections: Arc::new(Semaphore::new(4)),
            state: Mutex::new(State {
                custody: Some((file, witness)),
                material_connection: Some(material),
                material: None,
                context: None,
                model: None,
                execution_requested: matches!(origin, Origin::Recovered),
                fenced: false,
                retained: None,
            }),
        })
    }

    fn original_inputs(
        &self,
        state: &mut State,
    ) -> Result<OriginalModelInputs, Error> {
        let started = now()?;
        let original = self.bootstrap.ready()?.ok_or(Error::Unavailable)?;
        let dataset = self
            .runtime
            .block_on(OriginalCellQ24DatasetCommandReadbackV1::readback(
                &self.bootstrap.dataset,
            ))?;
        let training = self.runtime.block_on(
            OriginalCellQ24TrainingCommandOwnerV1::read_original_model_training(
                original.as_ref(),
                &dataset,
            ),
        )?;
        if state.material.is_none() {
            let connection = state.material_connection.take().ok_or(Error::Unavailable)?;
            state.material =
                Some(Arc::new(connection.bind_original_training(dataset.snapshot().clone(), &training)?));
        }
        let material = Arc::clone(state.material.as_ref().ok_or(Error::Unavailable)?);
        Ok(OriginalModelInputs { original, dataset, training, material, started })
    }

    fn original_context(
        &self,
        state: &mut State,
        inputs: &OriginalModelInputs,
        material: &OriginalCellEvaluationModelMaterialV1,
    ) -> Result<Context, Error> {
        let context = Context::from_original(
            self.bootstrap.config.material.clone(),
            self.registration.clone(),
            inputs.dataset.clone(),
            inputs.training.clone(),
            material.original_evaluation().clone(),
        )?;
        if let Some(retained) = &state.context {
            if retained.binding()? != context.binding()? {
                return Err(Error::Binding("unchanged original Model predecessors"));
            }
        }
        let fresh = context.authenticate(inputs.started)?;
        material.authenticate_current(fresh)?;
        state.context = Some(context.clone());
        Ok(context)
    }

    fn recover_deployment(&self) -> Result<(), Error> {
        let mut state = self.state.try_lock().map_err(|_| Error::Busy)?;
        let inputs = self.original_inputs(&mut state)?;
        // The opaque transfer borrows the same original client. No original
        // Trainer lane or owner lock spans these actual Evaluator exchanges.
        let operation = self.runtime.block_on(
            OriginalCellEvaluationModelMaterialClientV1::begin_model_read(inputs.material.as_ref()),
        )?;
        let context = self.original_context(&mut state, &inputs, OriginalCellEvaluationModelReadV1::material(&operation))?;
        let original = &inputs.original;
        let before = OriginalCellEvaluationModelReadV1::material(&operation);
        context.require_qualified()?;
        before.require_original_model_input(
            &context.training_cut,
            context.training.attestation(),
            context.authenticate(now()?)?,
        )?;
        let (file, witness) = state.custody.take().ok_or(Error::ReadbackRequired)?;
        // The shared once was consumed by bind before recovery could mutate a
        // minimum anchor. Missing or failed recovery never creates a new owner.
        state.model = Some(
            OriginalCellQ24TrainingCommandOwnerV1::recover_original_model(
                original.as_ref(),
                file,
                witness,
                &context,
                before,
            )?,
        );
        let (observed, material, fresh) =
            self.current_after(&mut state, original, &context, operation)?;
        if let effect::Observed::Completed(receipt) = observed {
            use super::super::model_command::wire;
            let wire::Outcome::Completed { record } =
                wire::encode_completed(&context, &receipt, material, fresh)?
            else {
                return Err(Error::CommitUncertain);
            };
            state.retained = Some(wire::decode_completed(&context, &record, fresh)?);
        }
        Ok(())
    }
}
