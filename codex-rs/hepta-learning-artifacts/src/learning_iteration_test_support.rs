use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use crate::CellBundleComponentsV1;
use crate::CellCompatibilityBundleV1;
use crate::CellStatePartitionV1;
use crate::CellTrainingLineageV1;
use crate::IterationEnvelopeV1;
use crate::LearningIterationCoordinatorV1;
use crate::learning_iteration_types::*;
use crate::test_support::FixtureValue;

pub(crate) fn id(value: &str) -> StableId {
    StableId::new(value).fixture("id")
}
pub(crate) fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}
pub(crate) fn request() -> LearningIterationRequestV1 {
    LearningIterationRequestV1 {
        operation_id: id("iteration:one"),
        principal_id: id("principal:one"),
        agent_id: id("agent:one"),
        cell_id: id("cell:one"),
        source_run_id: id("run:source"),
        completed_task_receipt: digest("task-receipt"),
        selected_artifact_digest: digest("base"),
        selected_bundle: CellCompatibilityBundleV1 {
            artifact_id: id("artifact:base"),
            generation: Generation::new(1).fixture("generation"),
            components: CellBundleComponentsV1 {
                base: digest("base"),
                organ_adapter: None,
                cell_adapter: None,
                heads: digest("heads"),
                composition: digest("composition"),
                encoder: digest("encoder"),
                tokenizer: digest("tokenizer"),
                normalizer: digest("normalizer"),
                calibration: digest("calibration"),
                numeric_profile: digest("numeric"),
                output_schema: digest("output"),
                state_schema: digest("state"),
                state_semantics: digest("semantics"),
            },
            training_lineage: None,
            rollback_predecessor: None,
        },
        envelope: IterationEnvelopeV1 {
            envelope_id: id("window:one"),
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
            maximum_dataset_rows: 10,
            maximum_dataset_bytes: 128,
            maximum_training_steps: 10,
            maximum_training_milliseconds: 100,
            maximum_artifact_bytes: 128,
        },
    }
}

pub(crate) fn owners() -> LearningIterationOwnersV1 {
    LearningIterationOwnersV1 {
        evidence_trust_digest: digest("trust"),
        experience: id("owner:experience"),
        dataset: id("owner:dataset"),
        trainer: id("owner:trainer"),
        evaluator: id("owner:evaluator"),
        proposal: id("owner:proposal"),
        selector: id("owner:selector"),
        next_use_observer: id("owner:observer"),
    }
}

pub(crate) fn receipt(coordinator: &LearningIterationCoordinatorV1) -> LearningIterationReceiptV1 {
    let snapshot = coordinator.snapshot();
    let stage = coordinator.next_stage().fixture("stage");
    let mut candidate = snapshot.request.selected_bundle.clone();
    candidate.artifact_id = id("artifact:next");
    candidate.generation = candidate.generation.next().fixture("generation");
    candidate.components.cell_adapter = Some(digest("trained-adapter"));
    let source_bundle = snapshot.request.selected_bundle.digest().fixture("source");
    candidate.training_lineage = Some(CellTrainingLineageV1 {
        source_bundle,
        dataset: digest("dataset"),
        update_rule: digest("rule"),
        evaluation_profile: digest("evaluation-profile"),
    });
    candidate.rollback_predecessor = Some(source_bundle);
    let candidate_bundle = candidate.digest().fixture("candidate");
    let observation = match stage {
        LearningIterationStageV1::Experience => LearningIterationObservationV1::Experience {
            episode_digest: digest("episode"),
            completed_task_receipt: snapshot.request.completed_task_receipt,
        },
        LearningIterationStageV1::Dataset => LearningIterationObservationV1::Dataset {
            snapshot_digest: digest("dataset"),
            episode_digest: digest("episode"),
            withdrawal_frontier: digest("withdrawals"),
            rows: 2,
            bytes: 64,
        },
        LearningIterationStageV1::Training => LearningIterationObservationV1::Training {
            candidate: Box::new(candidate),
            steps: 2,
            milliseconds: 10,
            artifact_bytes: 64,
        },
        LearningIterationStageV1::Evaluation => LearningIterationObservationV1::Evaluation {
            candidate_bundle,
            evaluation_profile: digest("evaluation-profile"),
            disposition: LearningEvaluationDispositionV1::Qualified,
        },
        LearningIterationStageV1::Proposal => LearningIterationObservationV1::Proposal {
            candidate_bundle,
            proposal_id: snapshot.request.operation_id.clone(),
            composition_digest: digest("proposal"),
            disposition: LearningProposalDispositionV1::UpdateCandidates,
        },
        LearningIterationStageV1::Selection => LearningIterationObservationV1::Selection {
            candidate_bundle: coordinator
                .next_task_bundle()
                .fixture("decision")
                .digest()
                .fixture("bundle"),
            selection_digest: digest("selection"),
        },
        LearningIterationStageV1::NextUse => LearningIterationObservationV1::NextUse {
            candidate_bundle: coordinator
                .next_task_bundle()
                .fixture("decision")
                .digest()
                .fixture("bundle"),
            state_partition: CellStatePartitionV1 {
                principal_id: snapshot.request.principal_id.clone(),
                agent_id: snapshot.request.agent_id.clone(),
                cell_id: snapshot.request.cell_id.clone(),
                run_id: id("run:next"),
            },
            checkpoint_digest: digest("checkpoint"),
            selection_digest: digest("selection"),
            committed_step_receipt: digest("step"),
            state_cutover_receipt: digest("state-cutover"),
        },
    };
    LearningIterationReceiptV1 {
        operation_id: snapshot.request.operation_id.clone(),
        predecessor: snapshot.head_digest,
        actor_id: snapshot.owners.owner(stage).clone(),
        evidence_digest: digest(&format!("{stage:?}")),
        observed_unix_seconds: 10 + snapshot.receipts.len() as u64,
        observation,
    }
}
