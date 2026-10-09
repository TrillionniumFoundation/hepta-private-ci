//! Concrete selected-LoRA consumer, not an alternate installer or routing owner.
//! The caller is the existing active module composition, and supplies CURRENT
//! owners and node identity. Supervisor still owns durable cutover and recovery.
use super::*;
use crate::memory_serving_process::MemoryServingJobV1;
use crate::{MemoryServingProcessV1, MemoryServingQueryV1, MemoryServingResultV1};
use codex_hepta_contracts::{FinalUseBinding, VerifiedUseToken};
use codex_hepta_intelligence_eval::VerifiedSelfEvolutionSelectionV1;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_types::StableId;

impl AgentdSharedReplayHostV1 {
    fn memory_serving_job(
        &self,
        model: &SelectedMemoryTensorModelV1,
        qualified: &VerifiedSelfEvolutionSelectionV1,
        query: &MemoryServingQueryV1,
        process: &MemoryServingProcessV1,
        destination: &StableId,
    ) -> Result<MemoryServingJobV1, SharedMemoryTrainingError> {
        let manifest = model.pinned.manifest();
        let receipt = qualified.receipt();
        let frozen = model.candidate.frozen();
        let profile = frozen.profile();
        if model.unavailable || manifest.artifact_id != receipt.candidate_id
            || manifest.content_digest != receipt.candidate_artifact_digest
            || manifest.generation != receipt.candidate_generation
            || manifest.objective_digest != receipt.objective_digest
            || manifest.support_digest != receipt.dataset_digest
            || receipt.minimum_dataset_records < 200
            || manifest.kind != codex_hepta_learning_artifacts::ArtifactKind::Parameters
        {
            return Err(SharedMemoryTrainingError::Invalid("selected memory qualification mismatch"));
        }
        Ok(MemoryServingJobV1 {
            schema: "hepta.memory-serving.job.v1",
            request_id: query.request_id.as_str().to_owned(),
            subject_id: self.consumer.agent_id().to_string(),
            destination_id: destination.as_str().to_owned(),
            route_generation: receipt.candidate_generation.get(),
            base_digest: profile.base_digest.to_string(),
            encoder_digest: profile.encoder_digest.to_string(),
            payload_digest: manifest.content_digest.to_string(),
            scope_digest: profile.scope_digest.to_string(),
            selection_digest: model.selection_digest().to_string(),
            qualification_digest: qualified.selection_digest().to_string(),
            source_support_digest: frozen.source_support().to_string(),
            training_job_digest: frozen.job_digest().to_string(),
            trainer_digest: profile.trainer_digest.to_string(),
            runtime_digest: process.runtime_digest().to_string(),
            interpreter_digest: process.interpreter_digest().to_string(),
            question: query.question.clone(),
            question_time: query.question_time.clone(),
            deadline_unix_millis: query.deadline_unix_millis,
        })
    }

    /// Unsigned request proposal for the existing authority issuer. Changing any
    /// model, selection, runtime, node, generation or query changes the binding.
    /// Returning this DTO does not issue a final-use grant or select a route.
    pub fn selected_memory_serving_binding_v1(
        &self,
        model: &SelectedMemoryTensorModelV1,
        qualified: &VerifiedSelfEvolutionSelectionV1,
        query: &MemoryServingQueryV1,
        process: &MemoryServingProcessV1,
        destination: &StableId,
    ) -> Result<FinalUseBinding, SharedMemoryTrainingError> {
        self.memory_serving_job(model, qualified, query, process, destination)?
            .binding().map_err(|_| SharedMemoryTrainingError::Invalid("invalid memory serving request"))
    }

    /// Execute the actual pinned LoRA backend, then refresh source permission,
    /// registry selection and independent qualification BEFORE releasing text.
    /// A cancellation/error closes this model instance; restoring it needs the
    /// full current source/selection load path, not an old cache or checkpoint.
    /// This is parameter-only: Replay permission never becomes plaintext Recall.
    #[allow(clippy::too_many_arguments)]
    pub async fn execute_selected_memory_v1(
        &self,
        model: &mut SelectedMemoryTensorModelV1,
        qualified: &VerifiedSelfEvolutionSelectionV1,
        query: &MemoryServingQueryV1,
        process: MemoryServingProcessV1,
        destination: &StableId,
        token: VerifiedUseToken,
        ledger: &LedgerWriter,
        owner: &LearningArtifactOwnerService,
        selector: &ArtifactSelectionVerifierV1,
        evidence_verifier: &LearningEvidenceVerifierV1,
        clock: impl Fn() -> Result<u64, SharedMemoryTrainingError>,
    ) -> Result<MemoryServingResultV1, SharedMemoryTrainingError> {
        qualified.revalidate_current(evidence_verifier, clock()?)
            .map_err(|_| SharedMemoryTrainingError::Invalid("stale independent memory qualification"))?;
        let job = self.memory_serving_job(model, qualified, query, &process, destination)?;
        job.binding().map_err(|_| SharedMemoryTrainingError::Invalid("invalid memory serving request"))?;
        let payload = self.with_current_selected_memory_tensor_v1(
            model, ledger, owner, selector, &clock, <[u8]>::to_vec,
        ).await?;
        model.unavailable = true;
        // Do not serialize unrelated Tokio workers behind CPU model loading.
        // Dropping this future cancels and reaps its blocking child. No response
        // escapes and this borrowed model stays unavailable until fresh loading.
        let cancel = tokio_util::sync::CancellationToken::new();
        let _cancel_on_drop = cancel.clone().drop_guard();
        let result = tokio::task::spawn_blocking(move || process.execute(job, payload, token, cancel))
            .await.map_err(|_| SharedMemoryTrainingError::Invalid("memory serving worker lost"))?
            .map_err(|_| SharedMemoryTrainingError::Invalid("memory serving worker rejected"))?;
        if owner.recovery_required().is_some() {
            return Err(SharedMemoryTrainingError::Invalid("artifact recovery required"));
        }
        self.revalidate_memory_source(&model.source, ledger, model.candidate.frozen().dataset(), clock()?).await?;
        let now = clock()?;
        qualified.revalidate_current(evidence_verifier, now)
            .map_err(|_| SharedMemoryTrainingError::Invalid("qualification changed during serving"))?;
        let current = owner.current_registry_view(now)
            .map_err(|_| SharedMemoryTrainingError::Invalid("current registry unavailable"))?;
        model.pinned.with_current(selector, current, now, |_| ())
            .map_err(|_| SharedMemoryTrainingError::Invalid("selection changed during serving"))?;
        model.unavailable = false;
        Ok(result)
    }
}
