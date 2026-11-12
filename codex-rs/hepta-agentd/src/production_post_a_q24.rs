//! Explicit current-recipient post-A composition. Historical authority comes
//! from the actual Root receipt; descriptor data supplies only original files.

use super::initial_q24::files::OriginalFiles;
use super::*;
use crate::CellQ24DatasetFreezePreparationV1;
use crate::CellQ24DatasetTaskV1;
use crate::learning_iteration::historical_source::RegisteredHistoricalLearningSourceV1;
use crate::root_historical_task_read_client::OriginalHistoricalLearningTrustV1;
use crate::root_historical_task_read_client::OriginalHistoricalTaskReadReceiptV1;
use crate::root_historical_task_read_client::OriginalPostAFrozenLearningAckV1;
use crate::root_historical_task_read_client::RootHistoricalTaskReadClientV1;

#[path = "production_post_a_artifacts.rs"]
mod artifacts;
#[path = "production_post_a_c_task.rs"]
mod c_task;
#[path = "production_post_a_continuation.rs"]
mod continuation;
pub(crate) use continuation::OriginalPostAContinuationV1;
#[path = "production_post_a_q24_deployment.rs"]
mod deployment;
#[path = "production_post_a_generation.rs"]
mod generation;
#[path = "production_post_a_q24_handoff.rs"]
mod handoff;
#[path = "production_post_a_late_input.rs"]
mod late_input;
#[path = "production_post_a_material.rs"]
mod material;
#[path = "production_post_a_q24_owners.rs"]
mod owners;
pub(super) use handoff::PendingHandoffs;

impl AgentdProductionLaunch {
    /// The explicit ordinary post-A profile uses the same actual Root session
    /// from historical admission through Dataset freeze and scoped assembly.
    /// Independent B remains its original Root host's capability. Actual C is
    /// installed by the supervised continuation after the checkpointed result.
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
        let baseline = Arc::clone(&preparation.baseline);
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
        let ack: OriginalPostAFrozenLearningAckV1 =
            OriginalHistoricalTaskReadReceiptV1::install_original_post_a_learning(
                &receipt,
                &client,
                &self.root.session,
            )?;
        OriginalPostAFrozenLearningAckV1::require_prepared_scope(&ack, prepared.scope())?;
        let pending: PendingHandoffs = self
            .post_a_handoffs
            .take()
            .ok_or_else(|| refused("original deferred handoffs are absent"))?;
        let (learning, model, publication) = pending
            .receive_original_after_ack(&self.root, &identity, &ack, &prepared, self.session_end)
            .await?;
        self.require_original_post_a_context(&identity)?;
        config = config.with_root_learning_inputs(learning)?;
        self.q24_model = Some(model);
        self.publication = Some(publication);
        let authorities = OriginalHistoricalLearningTrustV1::original_stage_authorities(&trust)?;
        let generation = data
            .continuation
            .generation
            .open_original(&mut files, &authorities)?;
        let artifacts = artifacts::OriginalArtifactPlan::open_original(
            data.continuation.artifacts,
            &mut files,
            self.session_end,
        )?;
        let task = data
            .continuation
            .task
            .open_original(&mut files, self.session_end)?;
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
                Arc::clone(&source),
                &identity,
                journal,
                witness,
                data.delivery_mode.original(),
            )?;
        config = config.with_learning_iteration_bootstrap(bootstrap)?;
        let (launch, mut config, successor) = self
            .prepare_original_q24_successor(config, data.queue_capacity)
            .await?;
        self = launch;
        self.require_original_post_a_context(&identity)?;
        let publication = crate::RootGenerationPublicationHandoffV1::retain_original_preparation(
            self.take_generation_publication_handoff()?,
            self.take_generation_publication_connection()?,
            &prepared,
            self.session_end,
        )?;
        let material = material::OriginalMaterialWriter::open_from_original_root(
            &publication,
            &mut files,
            self.session_end,
        )?;
        let final_use = publication.with_original_data(|fixed| {
            Ok(Arc::new(match fixed.inputs.consumer {
                crate::RootPublicationFinalUseConsumerV1::Device => self.root.device.clone(),
                crate::RootPublicationFinalUseConsumerV1::Notes => self.root.notes.clone(),
            }))
        })?;
        let continuation = OriginalPostAContinuationV1::from_original_inputs(
            continuation::OriginalContinuationInputs {
                source,
                owners: stage_owners,
                trust,
                receipt,
                successor,
                publication,
                material,
                artifacts,
                task,
                generation,
                files,
                baseline,
                final_use,
                grants: Arc::clone(&self.root.grants),
                clock: self.root.session.clock(),
                identity: identity.clone(),
                end: self.session_end,
            },
        )?;
        let bootstrap = config
            .take_learning_iteration_bootstrap()
            .ok_or_else(|| refused("original successor learning bootstrap absent"))?;
        let bootstrap = bootstrap.with_original_post_a_continuation(continuation, &identity)?;
        config = config.with_learning_iteration_bootstrap(bootstrap)?;
        // The mandatory delivery now owns both the handle and continuation.
        drop(handle);
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
