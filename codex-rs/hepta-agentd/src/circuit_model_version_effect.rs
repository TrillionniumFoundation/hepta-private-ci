//! One bounded original Model operation encloses native preparation, the
//! separately authorized Root FinalUse request, publication and C factory.
//! Only the Version service's blocking lane enters this async continuation.
use std::sync::Arc;
use std::sync::atomic::Ordering;
use std::sync::atomic::AtomicBool;
use super::super::Error;
use super::super::Origin;
use super::super::OriginalCircuitModelVersionReadbackV1 as Readback;
use super::super::wire;
use super::OriginalCircuitModelVersionHostV1 as Host;
use super::artifact;
use crate::OriginalCircuitModelPublicationContextV1 as Context;
use crate::PreparedAgentdGenerationUpdateV1;
use crate::PreparedOriginalCircuitModelPublicationV1;
use crate::OriginalRootModelVersionIssuerV1;

struct EffectFence<'a> { host: &'a Host, completed: bool }
impl Drop for EffectFence<'_> {
    fn drop(&mut self) {
        if !self.completed { self.host.outcome.store(3, Ordering::Release); }
        self.host.installed.notify_waiters();
    }
}
impl Host {
    pub(super) async fn publish_original(&self, request: &wire::Request, cancelled: &AtomicBool) -> Result<Readback, Error> {
        require_not_cancelled(cancelled)?;
        self.require_lifetime()?;
        if self.origin != Origin::Fresh || self.requested.swap(true, Ordering::AcqRel) {
            return Err(Error::ReadbackRequired);
        }
        self.outcome.store(1, Ordering::Release);
        let mut fence = EffectFence { host: self, completed: false };
        let started = super::super::now()?;
        // Take custody once and release Version's mutex before any peer I/O.
        let awaiting = {
            let mut state = self.state.try_lock().map_err(|_| Error::Busy)?;
            state.awaiting.take().ok_or(Error::CommitUncertain)?
        };
        let operation = self.model.begin_original_model_read().await?;
        require_not_cancelled(cancelled)?;
        let context = self.original_predecessors().with_original_model(operation.model().clone())?;
        request.require_context(&context)?;
        operation.require_current(started)?;
        context.authenticate_material(operation.material(), started, true)?;
        let artifact_before = self.artifacts.read_current()?;
        awaiting.task.require_completed_a(&awaiting.inputs.completed)?;
        let pin = Arc::new(context.duplicate_response_pin());
        let prepared = super::super::super::prepare_in_original_model_operation(
            context, operation, *awaiting.inputs, started,
        ).await.map_err(|_| Error::CommitUncertain)?;
        require_not_cancelled(cancelled).map_err(|_| Error::CommitUncertain)?;
        let intent = prepared.intent_digest();
        {
            let mut state = self.state.try_lock().map_err(|_| Error::CommitUncertain)?;
            if state.context.is_some() || state.intent.is_some() || state.installed.is_some() {
                return Err(Error::CommitUncertain);
            }
            state.context = Some(Arc::clone(&pin));
            state.intent = Some(intent);
        }
        self.require_prepared_control(&pin, intent, Some(prepared.final_use_binding()))?;
        artifact::require_same(&artifact_before, &self.artifacts.read_current()?)?;
        prepared.observation.require_current(started)?;
        prepared.context.authenticate_material(prepared.observation.material(), started, true)?;
        self.require_lifetime()?;
        require_not_cancelled(cancelled).map_err(|_| Error::CommitUncertain)?;
        let mut issuer = awaiting.issuer;
        // No Version mutex spans Root I/O. The issuer sees the actual typed
        // Prepared binding; its existing changed-model policy can still deny.
        let signed = OriginalRootModelVersionIssuerV1::request_for_original_model_version(
            &mut issuer, &prepared,
        );
        let signed = match signed {
            Ok(signed) => signed,
            Err(crate::AgentdFinalUseIssuerError::Denied) => {
                let PreparedOriginalCircuitModelPublicationV1 { context, observation, .. } = prepared;
                let completed = observation.finish().await.map_err(|_| Error::CommitUncertain)?;
                self.require_prepared_control(&context, intent, None)?;
                artifact::require_same(&artifact_before, &self.artifacts.read_current()?)?;
                if completed.model() != context.model() { return Err(Error::CommitUncertain); }
                context.authenticate_material(completed.material(), started, false)?;
                require_not_cancelled(cancelled).map_err(|_| Error::CommitUncertain)?;
                self.outcome.store(2, Ordering::Release);
                fence.completed = true;
                return Err(Error::FinalUseDenied);
            }
            Err(_) => return Err(Error::CommitUncertain),
        };
        require_not_cancelled(cancelled).map_err(|_| Error::CommitUncertain)?;
        if &signed.grant.binding != prepared.final_use_binding() {
            return Err(Error::CommitUncertain);
        }
        prepared.observation.require_current(started).map_err(|_| Error::CommitUncertain)?;
        prepared.context.authenticate_material(prepared.observation.material(), started, true)
            .map_err(|_| Error::CommitUncertain)?;
        self.require_prepared_control(&pin, intent, Some(prepared.final_use_binding()))
            .map_err(|_| Error::CommitUncertain)?;
        artifact::require_same(&artifact_before, &self.artifacts.read_current()?)
            .map_err(|_| Error::CommitUncertain)?;
        self.require_lifetime().map_err(|_| Error::CommitUncertain)?;
        let PreparedOriginalCircuitModelPublicationV1 {
            context, observation, prepared, definition, source, completed, started_at,
        } = prepared;
        // These are blocking native owner operations on this original service
        // lane. No result/config leaves the invocation before actual Finish.
        require_not_cancelled(cancelled).map_err(|_| Error::CommitUncertain)?;
        let ready = PreparedAgentdGenerationUpdateV1::publish(prepared, &signed)
            .map_err(|_| Error::CommitUncertain)?;
        let published = ready.into_circuit_feature_task(definition, source, completed)
            .map_err(|_| Error::CommitUncertain)?;
        super::super::super::binding::require_published(&context, &published, true)
            .map_err(|_| Error::CommitUncertain)?;
        require_not_cancelled(cancelled).map_err(|_| Error::CommitUncertain)?;
        let (installed, config) = awaiting.task.install_original(published, &context, intent)
            .map_err(|_| Error::CommitUncertain)?;
        let before = installed.observe(&context).map_err(|_| Error::CommitUncertain)?;
        let closed = observation.finish().await.map_err(|_| Error::CommitUncertain)?;
        require_not_cancelled(cancelled).map_err(|_| Error::CommitUncertain)?;
        if closed.model() != context.model() {
            return Err(Error::CommitUncertain);
        }
        // Last physical Version/Artifact reads follow E/native Model Finish.
        let current = installed.observe(&context).map_err(|_| Error::CommitUncertain)?;
        artifact::require_same(&artifact_before, &self.artifacts.read_current()?)
            .map_err(|_| Error::CommitUncertain)?;
        if current != before { return Err(Error::CommitUncertain); }
        self.require_lifetime().map_err(|_| Error::CommitUncertain)?;
        context.authenticate_material(closed.material(), started_at, true)
            .map_err(|_| Error::CommitUncertain)?;
        require_not_cancelled(cancelled).map_err(|_| Error::CommitUncertain)?;
        {
            let mut state = self.state.try_lock().map_err(|_| Error::CommitUncertain)?;
            if state.installed.is_some() || state.config.is_some()
                || state.intent != Some(intent)
                || state.context.as_ref().is_none_or(|original| !Arc::ptr_eq(original, &pin))
            {
                return Err(Error::CommitUncertain);
            }
            state.installed = Some(installed);
            state.config = Some(config);
        }
        self.outcome.store(4, Ordering::Release);
        fence.completed = true;
        Ok(current)
    }
}

fn require_not_cancelled(cancelled: &AtomicBool) -> Result<(), Error> {
    if cancelled.load(Ordering::Acquire) { return Err(Error::Cancelled); }
    Ok(())
}
