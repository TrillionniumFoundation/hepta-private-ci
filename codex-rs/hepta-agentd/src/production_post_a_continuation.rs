//! One actual post-A continuation, owned and joined by historical delivery.
//! Decision is observed from its checkpointed successor slot. Every later
//! publication and C receipt comes from the original concrete owner path.

use std::sync::Arc;
use std::time::Duration;
use std::time::Instant;

use codex_hepta_contracts::AuthorityClock;
use codex_hepta_contracts::FinalUseAuthority;
use tokio_util::sync::CancellationToken;

use super::OriginalFiles;
use super::artifacts::OriginalArtifactPlan;
use super::artifacts::OriginalSelectedArtifacts;
use super::c_task::OriginalCTaskPlan;
use super::c_task::OriginalNewCTask;
use super::generation::OriginalGenerationFiles;
use super::material::OriginalMaterialWriter;
use super::post_a_remaining;
use super::refused;
use crate::AgentdError;
use crate::AgentdIdentity;
use crate::AgentdState;
use crate::AgentdUnixFinalUseGrantProvider;
use crate::LoadedCellQ24ModelV1;
use crate::OriginalCellQ24LearningStageOwnersV1;
use crate::OriginalQ24SuccessorHandoffV1;
use crate::cell_q24_publication_driver::require_successor_admission;
use crate::cell_q24_publication_driver::validation::Decision;
use crate::learning_iteration::historical_source::RegisteredHistoricalLearningSourceV1;
use crate::root_generation_publication_inputs::OriginalPreparedPublicationRoute;
use crate::root_historical_task_read_client::OriginalHistoricalLearningTrustV1;
use crate::root_historical_task_read_client::OriginalHistoricalTaskReadReceiptV1;

pub(super) struct OriginalContinuationInputs {
    pub source: Arc<RegisteredHistoricalLearningSourceV1>,
    pub owners: Arc<OriginalCellQ24LearningStageOwnersV1>,
    pub trust: Arc<OriginalHistoricalLearningTrustV1>,
    pub receipt: Arc<OriginalHistoricalTaskReadReceiptV1>,
    pub successor: OriginalQ24SuccessorHandoffV1,
    pub publication: OriginalPreparedPublicationRoute,
    pub material: OriginalMaterialWriter,
    pub artifacts: OriginalArtifactPlan,
    pub task: OriginalCTaskPlan,
    pub generation: OriginalGenerationFiles,
    pub files: OriginalFiles,
    pub baseline: Arc<LoadedCellQ24ModelV1>,
    pub final_use: Arc<FinalUseAuthority>,
    pub grants: Arc<AgentdUnixFinalUseGrantProvider>,
    pub clock: Arc<dyn AuthorityClock>,
    pub identity: AgentdIdentity,
    pub end: Instant,
}

pub(crate) struct OriginalPostAContinuationV1 {
    original: OriginalContinuationInputs,
}

impl OriginalPostAContinuationV1 {
    pub(super) fn from_original_inputs(
        original: OriginalContinuationInputs,
    ) -> Result<Self, AgentdError> {
        post_a_remaining(original.end)?;
        original.trust.require_original_receipt(&original.receipt)?;
        original.publication.require_current()?;
        Ok(Self { original })
    }

    pub(crate) fn require_original_delivery(
        &self,
        source: &Arc<RegisteredHistoricalLearningSourceV1>,
        owners: &Arc<OriginalCellQ24LearningStageOwnersV1>,
        identity: &AgentdIdentity,
    ) -> Result<(), AgentdError> {
        if !Arc::ptr_eq(source, &self.original.source)
            || !Arc::ptr_eq(owners, &self.original.owners)
            || identity != &self.original.identity
        {
            return Err(refused(
                "continuation belongs to another actual delivery or aggregate",
            ));
        }
        self.original
            .trust
            .require_original_receipt(&self.original.receipt)?;
        self.original.publication.require_current()?;
        post_a_remaining(self.original.end)?;
        Ok(())
    }

    pub(crate) async fn run(
        self,
        state: Arc<AgentdState>,
        cancelled: CancellationToken,
    ) -> Result<(), AgentdError> {
        let OriginalContinuationInputs {
            source,
            owners,
            trust,
            receipt,
            successor,
            publication,
            material,
            artifacts,
            task,
            generation,
            mut files,
            baseline,
            final_use,
            grants,
            clock,
            identity,
            end,
        } = self.original;
        loop {
            if cancelled.is_cancelled() {
                return Ok(());
            }
            post_a_remaining(end)?;
            if require_successor_admission(&state, &identity).is_ok() {
                break;
            }
            tokio::select! {
                _ = cancelled.cancelled() => return Ok(()),
                _ = tokio::time::sleep(post_a_remaining(end)?.min(Duration::from_millis(25))) => {}
            }
        }
        RegisteredHistoricalLearningSourceV1::require_current_historical_source(
            &source, &identity,
        )?;
        trust.require_original_receipt(&receipt)?;
        let snapshot = tokio::select! {
            _ = cancelled.cancelled() => return Ok(()),
            result = tokio::time::timeout_at(end.into(), successor.decision_snapshot()) => {
                result.map_err(|_| refused("original Decision handoff deadline"))?.map_err(refused)?
            }
        };
        require_continuation(&state, &identity, &cancelled, end)?;
        let decision = Decision::new(snapshot.clone()).map_err(refused)?;
        let OriginalSelectedArtifacts {
            selected,
            signed,
            custody: artifact_custody,
        } = artifacts
            .publish_and_select_original(
                &publication,
                Arc::clone(&owners),
                snapshot.clone(),
                final_use,
                clock,
                &mut files,
                &cancelled,
            )
            .await?;
        require_continuation(&state, &identity, &cancelled, end)?;
        let original: OriginalNewCTask = task
            .open_original_new_task(
                &publication,
                &identity,
                &decision,
                selected.selected_manifest(),
                baseline,
                &owners,
                &receipt,
                &mut files,
                &cancelled,
            )
            .await?;
        let OriginalNewCTask {
            predecessor,
            target,
            target_data,
            execution,
            ingress,
            custody: task_custody,
        } = original;
        artifact_custody.require_original()?;
        task_custody.require_original()?;
        publication.require_current()?;
        require_continuation(&state, &identity, &cancelled, end)?;
        // Only canonical target data and an already verified independent
        // signature are committed. Root still performs its own enrollment.
        let material = material.commit_original_material(&target_data, &signed)?;
        let (handoff, connection, original_end) = publication.into_original_connection()?;
        if original_end != end {
            return Err(refused("original publication and continuation ends differ"));
        }
        let driver = crate::OriginalCellQ24SelectedArtifactForRootV1::connect_current_until(
            selected,
            handoff,
            connection,
            post_a_remaining(end)?.min(Duration::from_millis(500)),
            end,
        )
        .await
        .map_err(refused)?;
        material.require_unchanged()?;
        require_continuation(&state, &identity, &cancelled, end)?;
        let prepared = crate::OriginalCellQ24RootPublicationDriverV1::prepare_original_successor(
            driver,
            successor,
            predecessor,
            target,
            execution,
        )
        .await
        .map_err(refused)?;
        // The required successor worker retains both original journals across
        // this joined issuer call. Cancellation cannot spawn another attempt.
        let binding = prepared.final_use_binding().clone();
        let issuer_cancelled = cancelled.clone();
        let signed = tokio::task::spawn_blocking(move || {
            post_a_remaining(end)?;
            if issuer_cancelled.is_cancelled() {
                return Err(refused("original FinalUse request cancelled"));
            }
            let signed = grants.request_grant(&binding).map_err(refused)?;
            post_a_remaining(end)?;
            Ok::<_, AgentdError>(signed)
        })
        .await
        .map_err(|_| refused("original FinalUse acknowledgement uncertain"))??;
        require_continuation(&state, &identity, &cancelled, end)?;
        let installed = crate::OriginalQ24PreparedSuccessorV1::publish(prepared, signed)
            .await
            .map_err(refused)?;
        artifact_custody.require_original()?;
        task_custody.require_original()?;
        material.require_unchanged()?;
        require_continuation(&state, &identity, &cancelled, end)?;
        let original_ingress =
            crate::OriginalQ24InstalledSuccessorV1::original_installed_successor_ingress(
                &installed,
            )?;
        let completed =
            crate::OriginalCircuitFeatureIngressV1::submit_until(&original_ingress, ingress, end)
                .await?;
        require_continuation(&state, &identity, &cancelled, end)?;
        task_custody.require_original()?;
        artifact_custody.require_original()?;
        material.require_unchanged()?;
        let original = generation.into_original_handoff(completed)?;
        OriginalCellQ24LearningStageOwnersV1::install_circuit_feature_generation(
            &owners, snapshot, original,
        )
        .await
        .map_err(refused)?;
        require_continuation(&state, &identity, &cancelled, end)?;
        // Retain actual custody until the supervised daemon shuts down. The
        // learner completes Selection/NextUse through its existing owner lane.
        cancelled.cancelled().await;
        drop((
            material,
            task_custody,
            artifact_custody,
            source,
            trust,
            receipt,
            files,
        ));
        Ok(())
    }
}

fn require_continuation(
    state: &AgentdState,
    identity: &AgentdIdentity,
    cancelled: &CancellationToken,
    end: Instant,
) -> Result<(), AgentdError> {
    post_a_remaining(end)?;
    if cancelled.is_cancelled() {
        return Err(refused("original post-A continuation cancelled"));
    }
    require_successor_admission(state, identity).map_err(refused)?;
    post_a_remaining(end)?;
    Ok(())
}
