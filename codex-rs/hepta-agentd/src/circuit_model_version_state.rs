//! Independent Version reads use a new actual Model/E operation, then read
//! the original physical Control, Artifact and already-held C owners again.
use std::sync::Arc;
use std::sync::atomic::Ordering;
use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_types::Digest32;
use super::super::Error;
use super::super::OriginalCircuitModelVersionReadbackV1 as Readback;
use super::super::wire;
use super::OriginalCircuitModelVersionHostV1 as Host;
use super::artifact;
use crate::NeuronGenerationCurrentOwnerV1;
use crate::NeuronGenerationUpdateReadbackV1;
use crate::OriginalCircuitModelPublicationContextV1 as Context;

impl Host {
    pub(super) fn require_prepared_control(
        &self, context: &Context, intent: Digest32, expected: Option<&FinalUseBinding>,
    ) -> Result<(), Error> {
        let coordinator = context.authenticate(super::super::now()?, /*new_work*/ false)?;
        let operation = crate::learning_updated_task_operation_id_v1(&coordinator)?;
        let original = NeuronGenerationCurrentOwnerV1::recover_operation(
            &self.control, operation.as_str(), intent,
        )?;
        if original.intent_digest() != intent
            || expected.is_some_and(|binding| original.final_use_binding() != binding)
            || !matches!(NeuronGenerationCurrentOwnerV1::read_operation(&self.control, &original)?,
                NeuronGenerationUpdateReadbackV1::Prepared)
        {
            // A published Control record does not recreate an original C owner.
            return Err(Error::CommitUncertain);
        }
        Ok(())
    }

    pub(super) async fn read_original(
        &self, request: Option<&wire::Request>,
    ) -> Result<Readback, Error> {
        self.require_lifetime()?;
        if self.outcome.load(Ordering::Acquire) == 1 { return Err(Error::Busy); }
        let (expected, intent, installed) = {
            let state = self.state.try_lock().map_err(|_| Error::Busy)?;
            (Arc::clone(state.context.as_ref().ok_or(Error::ReadbackRequired)?),
                state.intent.ok_or(Error::CommitUncertain)?, state.installed.clone())
        };
        let started = super::super::now()?;
        let operation = self.model.begin_original_model_read().await?;
        let actual = self.original_predecessors().with_original_model(operation.model().clone())?;
        if let Some(request) = request { request.require_context(&actual)?; }
        if actual.model() != expected.model()
            || actual.original_version_binding(started)? != expected.original_version_binding(started)?
        {
            return Err(Error::CommitUncertain);
        }
        operation.require_current(started)?;
        actual.authenticate_material(operation.material(), started, /*new_work*/ false)?;
        let artifact_before = self.artifacts.read_current()?;
        let observe = || -> Result<Readback, Error> {
            match &installed {
                Some(original) => original.observe(&actual),
                None => {
                    self.require_prepared_control(&actual, intent, None)?;
                    Ok(Readback { intent, publication: None })
                }
            }
        };
        let before = observe()?;
        let completed = operation.finish().await?;
        if completed.model() != actual.model() { return Err(Error::CommitUncertain); }
        let after = observe()?;
        artifact::require_same(&artifact_before, &self.artifacts.read_current()?)?;
        if before != after { return Err(Error::CommitUncertain); }
        self.require_lifetime()?;
        actual.authenticate_material(completed.material(), started, /*new_work*/ false)?;
        Ok(after)
    }
}
