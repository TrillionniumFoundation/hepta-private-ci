//! Explicit current-recipient post-A composition. Historical authority comes
//! from the actual Root receipt; descriptor data supplies only original files.

use super::initial_q24::files::OriginalFiles;
use super::*;
use crate::CellQ24DatasetFreezePreparationV1;
use crate::CellQ24DatasetTaskV1;
use crate::learning_iteration::historical_source::RegisteredHistoricalLearningSourceV1;
use crate::root_historical_task_read_client::OriginalHistoricalLearningTrustV1;
use crate::root_historical_task_read_client::OriginalHistoricalTaskReadReceiptV1;
use crate::root_historical_task_read_client::RootHistoricalTaskReadClientV1;

#[path = "production_post_a_q24_deployment.rs"]
mod deployment;
#[path = "production_post_a_q24_handoff.rs"]
mod handoff;
#[path = "production_post_a_q24_owners.rs"]
mod owners;
pub(super) use handoff::PendingHandoffs;

/// Own only the actual continuation handles. The independent B host retains
/// its own dataset and signing keys; it must later install a real B completion.
pub(super) struct OriginalPostAContinuationV1 {
    _owners: Arc<crate::OriginalCellQ24LearningStageOwnersV1>,
    _trust: Arc<OriginalHistoricalLearningTrustV1>,
    _receipt: Arc<OriginalHistoricalTaskReadReceiptV1>,
    _handle: crate::LearningIterationHandleV1,
    _successor: crate::OriginalQ24SuccessorHandoffV1,
}

impl AgentdProductionLaunch {
    /// The explicit ordinary post-A profile uses the same actual Root session
    /// from historical admission through Dataset freeze and scoped assembly.
    /// Missing external B/C owners retain their existing refusal behavior.
    pub async fn assemble_original_post_a_q24(
        mut self,
        mut config: AgentdConfig,
    ) -> Result<(Self, AgentdConfig), AgentdError> {
        let deployment = match &mut self.inputs.primary {
            PrimaryInputs::PostAQ24 { deployment } => deployment
                .take()
                .ok_or_else(|| refused("original post-A deployment already consumed"))?,
            _ => return Ok((self, config)),
        };
        // Both dedicated Q24 entries require the same unconfigured original
        // Circuit/Root host and real AuthBus, replay and Objective inputs.
        config.require_original_initial_q24_configuration()?;
        self.require_original_post_a_context(config.identity())?;
        if self.q24_model.is_some()
            || self.initial_publication.is_some()
            || self.publication.is_some()
            || self.post_a_continuation.is_some()
            || self.original_source_capture.is_some()
            || self.original_run_start_retention.is_some()
        {
            return Err(refused(
                "post-A cannot reuse an Initial or already assembled owner",
            ));
        }
        let identity = config.identity().clone();
        let data = deployment::Deployment::read(deployment, &identity)?;
        let mut files = OriginalFiles::new()?;
        let client = self.take_original_historical_read()?;
        let receipt = Arc::new(RootHistoricalTaskReadClientV1::observe_original_task(
            &client,
        )?);
        let trust = OriginalHistoricalTaskReadReceiptV1::activate_current_learning_trust(
            &receipt,
            &client,
            &self.root.session,
        )?;
        let preparation = deployment::Deployment::preparation_config(
            &data,
            receipt.initial_snapshot(),
            &mut files,
        )?;
        let task = CellQ24DatasetTaskV1::capture_historical(
            Arc::clone(&receipt),
            &client,
            &self.root.session,
        )
        .map_err(refused)?;
        let phase = CellQ24DatasetFreezePreparationV1::capture_historical(
            preparation,
            Arc::clone(&receipt),
            Arc::clone(&trust),
            task,
        )
        .map_err(refused)?;
        let prepared = Arc::new(owners::SigningFilesData::freeze_original(
            &data.freeze,
            phase,
            &mut files,
            data.freeze_mode,
        )?);
        // freeze_original has dropped its concrete writer. Root independently
        // takes both original shared locks and verifies the retained signature.
        self.require_original_post_a_context(&identity)?;
        let ack = OriginalHistoricalTaskReadReceiptV1::install_original_post_a_learning(
            &receipt,
            &client,
            &self.root.session,
        )?;
        ack.require_prepared_scope(prepared.scope())?;
        let pending: PendingHandoffs = self
            .post_a_handoffs
            .take()
            .ok_or_else(|| refused("original deferred handoff pair is absent"))?;
        let (learning, model) = pending
            .receive_original_after_ack(&self.root, &identity, &ack, &prepared, self.session_end)
            .await?;
        self.require_original_post_a_context(&identity)?;
        config = config.with_root_learning_inputs(learning)?;
        self.q24_model = Some(model);
        let authorities = OriginalHistoricalLearningTrustV1::original_stage_authorities(&trust)?;
        // Retain one tracker from the baseline through every signing/journal
        // file, including dispatch. Earlier writer/read aliases are refused.
        let delivery = owners::JournalData::open(
            &data.delivery,
            &mut files,
            prepared.initial().request.envelope.objective_digest,
            data.delivery_mode,
        )?;
        let inputs = owners::StageFilesData::into_original_inputs(
            data.stages,
            Arc::clone(&prepared),
            authorities,
            &mut files,
            data.queue_capacity,
        )?;
        let source = RegisteredHistoricalLearningSourceV1::capture_original_historical_source(
            Arc::clone(&receipt),
            Arc::clone(&prepared),
            &client,
            &self.root.session,
            identity.clone(),
            self.session_end,
        )?;
        let (launch, configured, handle, stage_owners) =
            self.assemble_q24_learning(config, inputs).await?;
        self = launch;
        config = configured;
        let bootstrap = config
            .take_learning_iteration_bootstrap()
            .ok_or_else(|| refused("actual assembled learning bootstrap absent"))?;
        let (journal, witness) = delivery.open_witness()?;
        let bootstrap =
            crate::LearningIterationRuntimeBootstrapV1::with_original_historical_source(
                bootstrap,
                source,
                &identity,
                journal,
                witness,
                data.delivery_mode.original(),
            )?;
        config = config.with_learning_iteration_bootstrap(bootstrap)?;
        let (launch, config, successor) = self
            .prepare_original_q24_successor(config, data.queue_capacity)
            .await?;
        self = launch;
        self.require_original_post_a_context(&identity)?;
        self.post_a_continuation = Some(OriginalPostAContinuationV1 {
            _owners: stage_owners,
            _trust: trust,
            _receipt: receipt,
            _handle: handle,
            _successor: successor,
        });
        drop(files);
        Ok((self, config))
    }

    fn require_original_post_a_context(
        &self,
        identity: &AgentdIdentity,
    ) -> Result<(), AgentdError> {
        post_a_remaining(self.session_end)?;
        if self.root.bootstrap.registered_identity.identity()? != *identity {
            return Err(refused("original Root recipient identity differs"));
        }
        self.root
            .session
            .verifier()
            .verify_sender_process_binding(
                &self.root.session.authority(),
                &identity.agent_id,
                &self.root.bootstrap.writer.local_lease_id,
                self.root.bootstrap.writer.local_lease_generation,
                identity.spawn_generation,
            )
            .map_err(AgentdError::GenerationFenced)?;
        post_a_remaining(self.session_end)?;
        Ok(())
    }
}

fn post_a_remaining(end: Instant) -> Result<Duration, AgentdError> {
    end.checked_duration_since(Instant::now())
        .filter(|remaining| !remaining.is_zero() && *remaining <= Duration::from_secs(300))
        .ok_or_else(|| refused("original post-A Root session expired"))
}

fn refused(message: impl std::fmt::Display) -> AgentdError {
    AgentdError::GenerationFenced(format!("original post-A Q24: {message}"))
}
