//! A missing attempt is not proof. The original run's guarded cancellation
//! transaction must first exclude every later dispatch admission.

use super::*;
use codex_hepta_automation::TaskFlowCommand;
use codex_hepta_automation::TaskFlowTransition;

impl<A: RuntimeProcessOwner> RuntimeProcessEffectOwner<'_, A> {
    pub(super) async fn cancel_before_admission(&self) -> Result<StopObservation> {
        let effect = &self.admitted.0;
        let run = self
            .store
            .taskflow_run(&effect.intent.run_id)
            .await
            .map_err(|_| owner_error("original unstarted effect run unavailable"))?
            .ok_or(Error::Contract("original unstarted effect run absent"))?;
        // taskflow_run validates the immutable event chain. A prior successful
        // original Cancel command is sufficient after an acknowledgement loss
        // or process restart; no new fence/command/grant is allocated.
        if run.state == TaskFlowRunState::Cancelled && run.cancel_requested {
            return self.confirm_no_admitted_attempt().await;
        }
        let now = now_ms()?;
        self.check_fence(now, Contact::Cancel).await?;
        let command = TaskFlowCommand::new(
            &effect.intent.run_id,
            format!("native-process-cancel:{}", effect.mapping_digest),
            effect.fence.clone(),
            run.revision,
            TaskFlowTransition::Cancel {
                reason: "native cancellation before process admission".into(),
            },
            now,
        )
        .map_err(|_| Error::Contract("original unstarted cancellation command"))?;
        // The existing run transition guard and attempt admission transaction
        // serialize in the same database: admitted/unknown effects prevent
        // cancellation; successful cancellation prevents later admission.
        // A busy/failed/lost write reply proves nothing by itself.
        let _ = self.store.apply_taskflow_command(&command).await;
        self.confirm_no_admitted_attempt().await
    }

    async fn confirm_no_admitted_attempt(&self) -> Result<StopObservation> {
        let run = self
            .store
            .taskflow_run(&self.admitted.0.intent.run_id)
            .await
            .map_err(|_| owner_error("original cancellation proof unavailable"))?
            .ok_or(Error::Contract("original cancelled effect run absent"))?;
        if run.state == TaskFlowRunState::Cancelled
            && run.cancel_requested
            && self.pending().await?.is_none()
        {
            // Cancellation is irreversible for this original run. Original
            // begin_effect_dispatch_attempt rejects its state atomically.
            Ok(StopObservation::Stopped)
        } else {
            Ok(StopObservation::Unresolved)
        }
    }
}
