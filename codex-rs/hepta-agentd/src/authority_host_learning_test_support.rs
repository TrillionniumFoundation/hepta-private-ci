//! Shared synthetic iteration metadata for the profile and Root storage tests.

use super::*;
use crate::AgentdIdentity;
use codex_hepta_contracts::AgentId;
use codex_hepta_fleet::ResourceBudget;
use codex_hepta_learning_artifacts::IterationEnvelopeV1;
use codex_hepta_learning_artifacts::LearningIterationBudgetV1;
use codex_hepta_learning_artifacts::LearningIterationObservationV1;
use codex_hepta_learning_artifacts::LearningIterationReceiptV1;
use codex_hepta_types::StableId;

pub(crate) fn fixture() -> anyhow::Result<(
    tempfile::TempDir,
    AgentdIdentity,
    LearningIterationCoordinatorV1,
)> {
    let directory = tempfile::tempdir()?;
    let root = directory.path().canonicalize()?;
    let fleet_root = root.join("fleet");
    let workspace = root.join("workspace");
    std::fs::create_dir(&fleet_root)?;
    std::fs::create_dir(&workspace)?;
    let registered = crate::HostAuthorityRegisteredIdentity {
        agent_id: AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12")
            .map_err(anyhow::Error::msg)?,
        spawn_generation: 1,
        fleet_root,
        workspace,
        resources: ResourceBudget::local_default(),
    };
    let identity = registered.identity()?;
    let digest = |name: &str| Digest32::of_bytes(name.as_bytes());
    let request = LearningIterationRequestV1 {
        operation_id: StableId::new("profile-learning-operation")?,
        principal_id: StableId::new("profile-principal")?,
        agent_id: StableId::new(identity.agent_id.as_str())?,
        cell_id: StableId::new("profile-cell")?,
        source_run_id: StableId::new("profile-source-run")?,
        completed_task_receipt: digest("completed-task"),
        selected_artifact_digest: digest("selected-artifact"),
        evaluation_profile: digest("evaluation-profile"),
        selected_bundle: crate::neuron_generation_update_bootstrap::learning_test_baseline()?,
        envelope: IterationEnvelopeV1 {
            envelope_id: StableId::new("profile-envelope")?,
            base_commit: digest("commit"),
            base_tree: digest("tree"),
            objective_digest: digest("objective"),
            grammar_digest: digest("grammar"),
            maximum_files: 1,
            maximum_diff_bytes: 128,
            maximum_candidates: 1,
            maximum_parallel_sandboxes: 1,
            expiry_unix_seconds: 100,
        },
        budget: LearningIterationBudgetV1 {
            maximum_dataset_rows: 1,
            maximum_dataset_bytes: 128,
            maximum_training_steps: 1,
            maximum_training_milliseconds: 1,
            maximum_artifact_bytes: 128,
        },
    };
    let owners = LearningIterationOwnersV1 {
        evidence_trust_digest: digest("evidence-trust"),
        experience: StableId::new("profile-experience")?,
        dataset: StableId::new("profile-dataset")?,
        trainer: StableId::new("profile-trainer")?,
        evaluator: StableId::new("profile-evaluator")?,
        proposal: StableId::new("profile-proposal")?,
        selector: StableId::new("profile-selector")?,
        next_use_observer: StableId::new("profile-next-use")?,
    };
    Ok((
        directory,
        identity,
        LearningIterationCoordinatorV1::new(request, owners)?,
    ))
}

pub(crate) fn record_experience(
    coordinator: &mut LearningIterationCoordinatorV1,
) -> anyhow::Result<()> {
    let before = coordinator.snapshot();
    let receipt = LearningIterationReceiptV1 {
        operation_id: before.request.operation_id.clone(),
        predecessor: before.head_digest,
        actor_id: before.owners.experience.clone(),
        evidence_digest: Digest32::of_bytes(b"synthetic-experience-evidence"),
        observed_unix_seconds: 10,
        observation: LearningIterationObservationV1::Experience {
            episode_digest: Digest32::of_bytes(b"synthetic-episode"),
            completed_task_receipt: before.request.completed_task_receipt,
        },
    };
    coordinator.record(receipt, /*now_unix_seconds*/ 10)?;
    Ok(())
}
