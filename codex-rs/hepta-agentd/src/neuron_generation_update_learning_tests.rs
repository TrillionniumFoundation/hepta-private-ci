//! Actual file/CURRENT/nonce recovery with explicitly synthetic training,
//! evaluation, signatures and worker proposals. These are mechanism tests,
//! never production learning or model-quality qualification.

use codex_hepta_learning_artifacts::*;
use codex_hepta_neuron::*;
use codex_hepta_types::Generation;
use pretty_assertions::assert_eq;

use super::*;
use crate::AgentdGenerationUpdateRecoveryV1;
use crate::AgentdGenerationUpdateRequestV1;
use crate::neuron_generation_current::test_support::Fixture;
use crate::neuron_generation_current::test_support::config;
use crate::neuron_generation_current::test_support::request;
use crate::prepare_agentd_generation_same_model_task_v1;
use crate::recover_agentd_generation_update_v1;

fn d(label: &str) -> Digest32 {
    Digest32::of_bytes(label.as_bytes())
}

pub(crate) fn baseline() -> anyhow::Result<CellCompatibilityBundleV1> {
    Ok(CellCompatibilityBundleV1 {
        artifact_id: StableId::new("fixture-baseline")?,
        generation: Generation::new(1)?,
        components: CellBundleComponentsV1 {
            base: d("base"),
            organ_adapter: None,
            cell_adapter: None,
            heads: d("heads"),
            composition: d("composition"),
            encoder: d("encoder"),
            tokenizer: d("tokenizer"),
            normalizer: d("normalizer"),
            calibration: d("calibration"),
            numeric_profile: d("numeric"),
            output_schema: d("output"),
            state_schema: d("state"),
            state_semantics: d("semantics"),
        },
        training_lineage: None,
        rollback_predecessor: None,
    })
}

fn setup() -> anyhow::Result<(Fixture, LearningIterationCoordinatorV1)> {
    let baseline = baseline()?;
    let mut old = config()?;
    old.manifest.bundle_digest = baseline.digest()?.into_array();
    old.initial.manifest_digest = old.manifest.digest()?;
    let mut next = old.clone();
    next.initial.scope.run_id.push_str("-learning-next");
    next.initial.generation += 1;
    next.initial.writer_epoch += 1;
    next.task_digest = d("distinct next task").into_array();
    let f = Fixture::new_with_target(old, next)?;
    let coordinator = decision(&f, baseline, "none")?;
    Ok((f, coordinator))
}

pub(crate) fn decision(
    f: &Fixture,
    baseline: CellCompatibilityBundleV1,
    change: &str,
) -> anyhow::Result<LearningIterationCoordinatorV1> {
    let scope = &f.old_config.initial.scope;
    let mut request = LearningIterationRequestV1 {
        operation_id: StableId::new("learning-operation")?,
        principal_id: StableId::new(Digest32::from_array(scope.principal_digest).to_string())?,
        agent_id: StableId::new(&scope.agent_id)?,
        cell_id: StableId::new(&scope.cell_id)?,
        source_run_id: StableId::new(&scope.run_id)?,
        completed_task_receipt: d("fixture-completed-task"),
        selected_artifact_digest: baseline.components.base,
        selected_bundle: baseline,
        envelope: IterationEnvelopeV1 {
            envelope_id: StableId::new("learning-envelope")?,
            base_commit: d("commit"),
            base_tree: d("tree"),
            objective_digest: d("objective"),
            grammar_digest: d("grammar"),
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
    match change {
        "principal" => request.principal_id = StableId::new("unmapped-principal")?,
        "agent" => request.agent_id = StableId::new("other-agent")?,
        "cell" => request.cell_id = StableId::new("other-cell")?,
        "run" => request.source_run_id = StableId::new(&f.target_config.initial.scope.run_id)?,
        "operation" => request.operation_id = StableId::new("other-operation")?,
        "bundle" => request.selected_bundle.components.calibration = d("other-calibration"),
        "none" | "decision" => {}
        _ => anyhow::bail!("unknown decision mutation"),
    }
    let mut candidate = request.selected_bundle.clone();
    candidate.artifact_id = StableId::new("fixture-rejected-candidate")?;
    candidate.generation = candidate.generation.next()?;
    candidate.rollback_predecessor = Some(request.selected_bundle.digest()?);
    candidate.training_lineage = Some(CellTrainingLineageV1 {
        source_bundle: request.selected_bundle.digest()?,
        dataset: d("dataset"),
        update_rule: d("update"),
        evaluation_profile: d("evaluation"),
    });
    let candidate_bundle = candidate.digest()?;
    let completed = request.completed_task_receipt;
    let mut coordinator = LearningIterationCoordinatorV1::new(
        request,
        LearningIterationOwnersV1 {
            evidence_trust_digest: d("fixture-trust"),
            experience: StableId::new("experience")?,
            dataset: StableId::new("dataset")?,
            trainer: StableId::new("trainer")?,
            evaluator: StableId::new("evaluator")?,
            proposal: StableId::new("proposal")?,
            selector: StableId::new("selector")?,
            next_use_observer: StableId::new("observer")?,
        },
    )?;
    for observation in [
        LearningIterationObservationV1::Experience {
            episode_digest: d("episode"),
            completed_task_receipt: completed,
        },
        LearningIterationObservationV1::Dataset {
            snapshot_digest: d("dataset"),
            episode_digest: d("episode"),
            withdrawal_frontier: d("withdrawals"),
            rows: 1,
            bytes: 64,
        },
        LearningIterationObservationV1::Training {
            candidate: Box::new(candidate),
            steps: 1,
            milliseconds: 1,
            artifact_bytes: 64,
        },
        LearningIterationObservationV1::Evaluation {
            candidate_bundle,
            evaluation_profile: d("evaluation"),
            disposition: LearningEvaluationDispositionV1::NoUpdate,
        },
    ] {
        let mut receipt = observed(&coordinator, observation);
        if change == "decision"
            && receipt.observation.stage() == LearningIterationStageV1::Evaluation
        {
            receipt.evidence_digest = d("different evaluation evidence");
        }
        coordinator.record(receipt, 20)?;
    }
    Ok(coordinator)
}

pub(crate) fn observed(
    coordinator: &LearningIterationCoordinatorV1,
    observation: LearningIterationObservationV1,
) -> LearningIterationReceiptV1 {
    let snapshot = coordinator.snapshot();
    LearningIterationReceiptV1 {
        operation_id: snapshot.request.operation_id.clone(),
        predecessor: snapshot.head_digest,
        actor_id: snapshot.owners.owner(observation.stage()).clone(),
        evidence_digest: d("fixture-role-attestation"),
        observed_unix_seconds: 20,
        observation,
    }
}

fn recover_after_lost_ack(
    f: &Fixture,
    coordinator: &LearningIterationCoordinatorV1,
) -> anyhow::Result<ReadyAgentdGenerationUpdateV1<FileAnchorWitnessStore>> {
    let operation = learning_retained_task_operation_id_v1(coordinator)?;
    let prepared = prepare_agentd_generation_same_model_task_v1(
        f.current.clone(),
        f.authorities()?,
        f.stopped_old()?,
        f.selection()?,
        f.target_create()?,
        AgentdGenerationUpdateRequestV1 {
            operation_id: operation.as_str().into(),
        },
    )?;
    let intent_digest = prepared.intent_digest();
    let signed = f.sign(prepared.final_use_binding())?;
    f.lose_publication_ack();
    assert!(prepared.publish(&signed).is_err());
    assert_eq!(f.authority.capacity()?.used_nonces, 1);
    Ok(recover_agentd_generation_update_v1(
        f.reopen_current()?,
        f.authorities()?,
        f.selection()?,
        f.target_reopen()?,
        AgentdGenerationUpdateRecoveryV1 {
            operation_id: operation.as_str().into(),
            intent_digest,
        },
    )?)
}

fn settle(
    ready: &mut ReadyAgentdGenerationUpdateV1<FileAnchorWitnessStore>,
    f: &Fixture,
    request: &CellGenerationRequestV2,
    disposition: CellGenerationDispositionV2,
) -> anyhow::Result<()> {
    ready.journal.commit(
        CellGenerationProposalV2 {
            request_digest: request.digest()?,
            bundle_digest: f.target_config.manifest.bundle_digest,
            runtime_digest: f.target_config.manifest.runtime_digest,
            device_digest: f.target_config.manifest.device_digest,
            successor_state: request.predecessor.state.clone(),
            output_delta: Vec::new(),
            disposition,
            cost: CellTaskCostV2::new(CellTaskCostIdentityV2 {
                task_digest: f.target_config.task_digest,
                source_digest: f.target_config.manifest.source_digest,
            })?,
        },
        /*now_micros*/ 11,
    )?;
    Ok(())
}

#[test]
fn actual_same_model_use_cold_reopens_without_new_nonce_or_journal_work() -> anyhow::Result<()> {
    let (f, mut coordinator) = setup()?;
    let operation = learning_retained_task_operation_id_v1(&coordinator)?;
    assert!(operation.as_str().len() <= 128);
    let mut ready = recover_after_lost_ack(&f, &coordinator)?;
    for change in [
        "principal",
        "agent",
        "cell",
        "run",
        "operation",
        "bundle",
        "decision",
    ] {
        let other = decision(
            &f,
            coordinator.snapshot().request.selected_bundle.clone(),
            change,
        )?;
        assert_ne!(
            learning_retained_task_operation_id_v1(&other)?,
            operation,
            "{change}"
        );
        assert!(ready.read_learning_selection(&other).is_err(), "{change}");
    }
    let selection = ready.read_learning_selection(&coordinator)?;
    coordinator.record(observed(&coordinator, selection), 20)?;
    assert_eq!(
        learning_retained_task_operation_id_v1(&coordinator)?,
        operation
    );
    let request = request(&ready.journal, &f.target_config, "actual-new-task-step")?;
    let intent = request.intent()?;
    assert!(ready.read_learning_next_use(&coordinator, &intent).is_err());
    ready.journal.admit(request.clone(), /*now_micros*/ 10)?;
    assert!(ready.read_learning_next_use(&coordinator, &intent).is_err());
    settle(
        &mut ready,
        &f,
        &request,
        CellGenerationDispositionV2::Advanced,
    )?;
    let first = ready.read_learning_next_use(&coordinator, &intent)?;
    let LearningIterationObservationV1::RetainedModelNextUse {
        task_owner_publication,
        ..
    } = &first
    else {
        anyhow::bail!("same-model task was mislabeled as a bundle cutover");
    };
    assert_ne!(*task_owner_publication, ready.publication.intent_digest());
    let intent_digest = ready.publication.intent_digest();
    let retained = (
        f.bytes("current.json")?,
        f.bytes("target-journal")?,
        f.bytes("target-witness")?,
        f.bytes("final-use/authority.claims")?,
    );
    drop(ready);
    coordinator = LearningIterationCoordinatorV1::from_snapshot(coordinator.snapshot().clone())?;
    let ready = recover_agentd_generation_update_v1(
        f.reopen_current()?,
        f.authorities()?,
        f.selection()?,
        f.target_reopen()?,
        AgentdGenerationUpdateRecoveryV1 {
            operation_id: operation.as_str().into(),
            intent_digest,
        },
    )?;
    assert_eq!(ready.read_learning_next_use(&coordinator, &intent)?, first);
    let mut wrong = intent.clone();
    wrong.input_digest = d("different task input").into_array();
    assert!(ready.read_learning_next_use(&coordinator, &wrong).is_err());
    wrong = intent;
    wrong.task_digest = f.old_config.task_digest;
    assert!(ready.read_learning_next_use(&coordinator, &wrong).is_err());
    assert_eq!(
        (
            f.bytes("current.json")?,
            f.bytes("target-journal")?,
            f.bytes("target-witness")?,
            f.bytes("final-use/authority.claims")?
        ),
        retained
    );
    assert_eq!(f.authority.capacity()?.used_nonces, 1);
    coordinator.record(observed(&coordinator, first), 20)?;
    let completed = LearningIterationCoordinatorV1::from_snapshot(coordinator.snapshot().clone())?;
    assert_eq!(
        completed.disposition(),
        LearningIterationDispositionV1::UsedByNextTask
    );
    assert_eq!(
        learning_retained_task_operation_id_v1(&coordinator)?,
        operation
    );
    assert_eq!(
        learning_retained_task_operation_id_v1(&completed)?,
        operation
    );
    assert!(ready.read_learning_selection(&completed).is_err());
    assert!(
        ready
            .read_learning_next_use(&completed, &request.intent()?)
            .is_err()
    );
    Ok(())
}

#[test]
fn retained_use_rejects_failed_cancelled_rejected_and_late_work() -> anyhow::Result<()> {
    for disposition in [
        CellGenerationDispositionV2::Failed,
        CellGenerationDispositionV2::Cancelled,
        CellGenerationDispositionV2::Rejected,
        CellGenerationDispositionV2::DeadlineExceeded,
    ] {
        let (f, mut coordinator) = setup()?;
        let mut ready = recover_after_lost_ack(&f, &coordinator)?;
        let selection = ready.read_learning_selection(&coordinator)?;
        coordinator.record(observed(&coordinator, selection), 20)?;
        let request = request(&ready.journal, &f.target_config, "unsuccessful-step")?;
        ready.journal.admit(request.clone(), /*now_micros*/ 10)?;
        settle(&mut ready, &f, &request, disposition)?;
        assert!(
            ready
                .read_learning_next_use(&coordinator, &request.intent()?)
                .is_err(),
            "{disposition:?}"
        );
        assert_eq!(f.authority.capacity()?.used_nonces, 1);
    }
    Ok(())
}

#[test]
fn current_withdrawal_and_revocation_refuse_new_learning_observations_and_recovery()
-> anyhow::Result<()> {
    for change in ["current", "withdrawal", "revocation"] {
        let (f, coordinator) = setup()?;
        let ready = recover_after_lost_ack(&f, &coordinator)?;
        let intent_digest = ready.publication.intent_digest();
        let operation_id = learning_retained_task_operation_id_v1(&coordinator)?
            .as_str()
            .to_owned();
        let old_selection = f.selection()?;
        match change {
            "current" => f.advance_artifact_current()?,
            "withdrawal" => f.withdraw()?,
            "revocation" => {
                let mut head = f.authority.revocation_head()?;
                head.revision += 1;
                head.revoked_grant_ids
                    .insert(ready.publication.signed_grant().grant.grant_id.clone());
                f.authority.update_revocations(head)?;
            }
            _ => anyhow::bail!("unknown authority mutation"),
        }
        let retained = (
            f.bytes("target-journal")?,
            f.bytes("target-witness")?,
            f.bytes("final-use/authority.claims")?,
        );
        assert!(
            ready.read_learning_selection(&coordinator).is_err(),
            "{change}"
        );
        drop(ready);
        assert!(
            recover_agentd_generation_update_v1(
                f.reopen_current()?,
                f.authorities()?,
                old_selection,
                f.target_reopen()?,
                AgentdGenerationUpdateRecoveryV1 {
                    operation_id,
                    intent_digest
                },
            )
            .is_err(),
            "{change}"
        );
        assert_eq!(
            (
                f.bytes("target-journal")?,
                f.bytes("target-witness")?,
                f.bytes("final-use/authority.claims")?
            ),
            retained
        );
        assert_eq!(f.authority.capacity()?.used_nonces, 1);
    }
    Ok(())
}
