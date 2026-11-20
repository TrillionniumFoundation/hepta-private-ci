//! Direct DATA-reader controls using synthetic coordinator receipts only.
//! These fixtures do not authenticate stage signatures, register Root owners,
//! grant authority, or demonstrate completed-history acceptance by Root.

use codex_hepta_learning_artifacts::LearningIterationObservationV1;
use codex_hepta_learning_artifacts::LearningLocalDecisionV2;
use codex_hepta_learning_artifacts::LearningLocalDispositionV2;
use codex_hepta_learning_artifacts::LearningTrainingNoUpdateReasonV2;
use codex_hepta_learning_artifacts::LearningTrainingNoUpdateV2;
use codex_hepta_learning_artifacts::LearningUpdateScopeV2;
use pretty_assertions::assert_eq;

use super::test_support::Decision;
use super::test_support::snapshots;
use super::*;
use crate::neuron_generation_update_bootstrap::learning_test_receipt;

fn scope(initial: &LearningIterationSnapshotV1) -> anyhow::Result<FrozenLearningScopeV2> {
    Ok(FrozenLearningScopeV2::freeze(
        &initial.request,
        &initial.owners,
        LearningUpdateScopeV2::Cell,
        Digest32::of_bytes(b"rule"),
    )?)
}

fn record(
    scope: &FrozenLearningScopeV2,
    snapshot: &LearningIterationSnapshotV1,
) -> Result<LearningIterationCheckpointRecordV1, Error> {
    Ok(LearningIterationCheckpointRecordV1 {
        schema: 2,
        binding: scope.binding().to_string(),
        predecessor: snapshot
            .receipts
            .last()
            .map_or(Digest32::ZERO, |receipt| receipt.predecessor)
            .to_string(),
        snapshot: Some(STANDARD_NO_PAD.encode(codec::encode(snapshot)?)),
    })
}

fn append(
    coordinator: &mut LearningIterationCoordinatorV1,
    cuts: &mut Vec<LearningIterationSnapshotV1>,
    observation: LearningIterationObservationV1,
) -> anyhow::Result<()> {
    coordinator.record(
        learning_test_receipt(coordinator, observation),
        /*now_unix_seconds*/ 20,
    )?;
    cuts.push(coordinator.snapshot().clone());
    Ok(())
}

fn local_cuts(
    disposition: LearningLocalDispositionV2,
) -> anyhow::Result<Vec<LearningIterationSnapshotV1>> {
    let updated = snapshots(Decision::Update)?;
    let retained = snapshots(Decision::EvaluatedNoUpdate)?;
    let mut cuts = updated[..6].to_vec();
    let mut coordinator = LearningIterationCoordinatorV1::from_snapshot(updated[5].clone())?;
    let candidate_bundle = coordinator
        .candidate()
        .ok_or_else(|| anyhow::anyhow!("fixture candidate missing"))?
        .digest()?;
    let selected_bundle = match disposition {
        LearningLocalDispositionV2::AdoptCandidate => candidate_bundle,
        LearningLocalDispositionV2::DeferCandidate | LearningLocalDispositionV2::RetainParent => {
            coordinator.snapshot().request.selected_bundle.digest()?
        }
    };
    let observation = LearningIterationObservationV1::LocalDecisionV2(LearningLocalDecisionV2 {
        proposal_head: coordinator.snapshot().head_digest,
        candidate_bundle,
        selected_bundle,
        policy_digest: Digest32::of_bytes(b"fixture-local-policy"),
        reason_digest: Digest32::of_bytes(b"fixture-local-reason"),
        disposition,
    });
    append(&mut coordinator, &mut cuts, observation)?;
    let tail = match disposition {
        LearningLocalDispositionV2::AdoptCandidate => &updated[6..],
        LearningLocalDispositionV2::DeferCandidate | LearningLocalDispositionV2::RetainParent => {
            &retained[5..]
        }
    };
    for old in tail {
        let observation = old
            .receipts
            .last()
            .ok_or_else(|| anyhow::anyhow!("fixture tail missing"))?
            .observation
            .clone();
        append(&mut coordinator, &mut cuts, observation)?;
    }
    Ok(cuts)
}

fn trainer_cuts() -> anyhow::Result<Vec<LearningIterationSnapshotV1>> {
    let retained = snapshots(Decision::EvaluatedNoUpdate)?;
    let mut cuts = retained[..3].to_vec();
    let mut coordinator = LearningIterationCoordinatorV1::from_snapshot(retained[2].clone())?;
    let observation =
        LearningIterationObservationV1::TrainingNoUpdateV2(LearningTrainingNoUpdateV2 {
            retained_bundle: coordinator.snapshot().request.selected_bundle.digest()?,
            dataset: Digest32::of_bytes(b"data"),
            update_rule: Digest32::of_bytes(b"rule"),
            steps: 1,
            milliseconds: 1,
            reason: LearningTrainingNoUpdateReasonV2::QuantizedWeightsUnchanged,
        });
    append(&mut coordinator, &mut cuts, observation)?;
    for old in &retained[5..] {
        let observation = old
            .receipts
            .last()
            .ok_or_else(|| anyhow::anyhow!("fixture tail missing"))?
            .observation
            .clone();
        append(&mut coordinator, &mut cuts, observation)?;
    }
    Ok(cuts)
}

#[test]
fn completed_reader_accepts_evaluated_and_proposed_terminal_histories() -> anyhow::Result<()> {
    for (decision, expected_receipts) in [
        (Decision::EvaluatedNoUpdate, 6),
        (Decision::ProposedNoUpdate, 7),
        (Decision::Update, 7),
    ] {
        let cuts = snapshots(decision)?;
        let initial = &cuts[0];
        let terminal = cuts.last().unwrap();
        let scope = scope(initial)?;
        assert_eq!(terminal.receipts.len(), expected_receipts);
        assert_eq!(
            record(&scope, terminal)?.read_original_completed_scoped(initial, &scope)?,
            *terminal
        );
    }
    Ok(())
}

#[test]
fn completed_reader_accepts_all_local_decisions_after_selection_and_actual_use()
-> anyhow::Result<()> {
    for disposition in [
        LearningLocalDispositionV2::AdoptCandidate,
        LearningLocalDispositionV2::DeferCandidate,
        LearningLocalDispositionV2::RetainParent,
    ] {
        let cuts = local_cuts(disposition)?;
        let initial = &cuts[0];
        let terminal = cuts.last().unwrap();
        let scope = scope(initial)?;
        assert_eq!(terminal.receipts.len(), 8);
        assert_eq!(
            record(&scope, terminal)?.read_original_completed_scoped(initial, &scope)?,
            *terminal
        );
    }
    Ok(())
}

#[test]
fn completed_reader_excludes_valid_trainer_no_update_for_this_history_purpose() -> anyhow::Result<()>
{
    let cuts = trainer_cuts()?;
    let initial = &cuts[0];
    let terminal = cuts.last().unwrap();
    let scope = scope(initial)?;
    assert_eq!(terminal.receipts.len(), 5);
    assert_eq!(
        LearningIterationCoordinatorV1::from_snapshot(terminal.clone())?.next_stage(),
        None
    );
    assert_eq!(codec::decode(&codec::encode(terminal)?)?, *terminal);
    assert_eq!(
        record(&scope, terminal)?.read_original_completed_scoped(initial, &scope),
        Err(Error::InvalidRecord)
    );
    Ok(())
}

#[test]
fn completed_reader_refuses_every_unfinished_prefix_and_vacant_owner() -> anyhow::Result<()> {
    let paths = [
        snapshots(Decision::EvaluatedNoUpdate)?,
        snapshots(Decision::ProposedNoUpdate)?,
        snapshots(Decision::Update)?,
        local_cuts(LearningLocalDispositionV2::AdoptCandidate)?,
        local_cuts(LearningLocalDispositionV2::DeferCandidate)?,
        local_cuts(LearningLocalDispositionV2::RetainParent)?,
        trainer_cuts()?,
    ];
    for cuts in paths {
        let initial = &cuts[0];
        let scope = scope(initial)?;
        let vacant = LearningIterationCheckpointRecordV1::vacant_scoped_v2(
            initial.request.clone(),
            initial.owners.clone(),
            &scope,
        )?;
        assert_eq!(
            vacant.read_original_completed_scoped(initial, &scope),
            Err(Error::InvalidRecord)
        );
        for prefix in &cuts[..cuts.len() - 1] {
            assert!(
                LearningIterationCoordinatorV1::from_snapshot(prefix.clone())?
                    .next_stage()
                    .is_some()
            );
            assert_eq!(
                record(&scope, prefix)?.read_original_completed_scoped(initial, &scope),
                Err(Error::InvalidRecord)
            );
        }
    }
    Ok(())
}

#[test]
fn completed_reader_keeps_original_scope_request_owner_and_outer_record_binding()
-> anyhow::Result<()> {
    let cuts = snapshots(Decision::EvaluatedNoUpdate)?;
    let initial = &cuts[0];
    let terminal = cuts.last().unwrap();
    let scope = scope(initial)?;
    let original = record(&scope, terminal)?;
    let organ = FrozenLearningScopeV2::freeze(
        &initial.request,
        &initial.owners,
        LearningUpdateScopeV2::Organ,
        Digest32::of_bytes(b"rule"),
    )?;
    assert_eq!(
        original.read_original_completed_scoped(initial, &organ),
        Err(Error::WrongScope)
    );
    let wrong_rule = FrozenLearningScopeV2::freeze(
        &initial.request,
        &initial.owners,
        LearningUpdateScopeV2::Cell,
        Digest32::of_bytes(b"different-rule"),
    )?;
    assert!(
        record(&wrong_rule, terminal)?
            .read_original_completed_scoped(initial, &wrong_rule)
            .is_err()
    );
    let mut other_request = initial.clone();
    other_request.request.budget.maximum_training_steps -= 1;
    assert!(
        original
            .read_original_completed_scoped(&other_request, &scope)
            .is_err()
    );
    let mut other_owners = initial.clone();
    other_owners.owners.evidence_trust_digest = Digest32::of_bytes(b"different-trust");
    assert!(
        original
            .read_original_completed_scoped(&other_owners, &scope)
            .is_err()
    );
    let mut legacy = original.clone();
    legacy.schema = 1;
    let mut wrong_binding = original.clone();
    wrong_binding.binding = initial.head_digest.to_string();
    let mut wrong_predecessor = original.clone();
    wrong_predecessor.predecessor = Digest32::ZERO.to_string();
    for changed in [legacy, wrong_binding, wrong_predecessor] {
        assert!(
            changed
                .read_original_completed_scoped(initial, &scope)
                .is_err()
        );
    }
    Ok(())
}

#[test]
fn completed_reader_replays_missing_duplicate_reordered_and_tampered_receipts() -> anyhow::Result<()>
{
    let cuts = snapshots(Decision::EvaluatedNoUpdate)?;
    let initial = &cuts[0];
    let terminal = cuts.last().unwrap();
    let scope = scope(initial)?;
    let mut missing = terminal.clone();
    missing.receipts.remove(/*index*/ 1);
    let mut duplicate = terminal.clone();
    duplicate
        .receipts
        .insert(/*index*/ 2, terminal.receipts[1].clone());
    let mut reordered = terminal.clone();
    reordered.receipts.swap(/*a*/ 0, /*b*/ 1);
    let mut wrong_chain = terminal.clone();
    wrong_chain.receipts[2].predecessor = Digest32::ZERO;
    let mut wrong_head = terminal.clone();
    wrong_head.head_digest = initial.head_digest;
    let mut wrong_actor = terminal.clone();
    wrong_actor.receipts[3].actor_id = initial.owners.trainer.clone();
    let mut wrong_operation = terminal.clone();
    wrong_operation.receipts[1].operation_id = initial.request.source_run_id.clone();
    let mut empty_evidence = terminal.clone();
    empty_evidence.receipts[1].evidence_digest = Digest32::ZERO;
    let mut expired = terminal.clone();
    expired.receipts.last_mut().unwrap().observed_unix_seconds =
        initial.request.envelope.expiry_unix_seconds;
    for changed in [missing, duplicate, reordered, wrong_chain, wrong_head] {
        assert!(
            record(&scope, &changed)?
                .read_original_completed_scoped(initial, &scope)
                .is_err()
        );
    }
    for (changed, expected) in [
        (wrong_actor, LearningIterationError::WrongOwner),
        (wrong_operation, LearningIterationError::WrongOperation),
        (empty_evidence, LearningIterationError::EmptyEvidence),
        (expired, LearningIterationError::DeadlineExceeded),
    ] {
        assert_eq!(
            record(&scope, &changed)?.read_original_completed_scoped(initial, &scope),
            Err(Error::Snapshot(expected))
        );
    }
    Ok(())
}

#[test]
fn completed_reader_requires_the_selected_parent_and_real_next_task_use() -> anyhow::Result<()> {
    #[derive(Clone, Copy, Debug)]
    enum Mutation {
        CandidateInsteadOfParent,
        SourceRun,
        MissingStep,
        MissingPublication,
    }
    let cuts = snapshots(Decision::EvaluatedNoUpdate)?;
    let initial = &cuts[0];
    let terminal = cuts.last().unwrap();
    let scope = scope(initial)?;
    for mutation in [
        Mutation::CandidateInsteadOfParent,
        Mutation::SourceRun,
        Mutation::MissingStep,
        Mutation::MissingPublication,
    ] {
        let mut changed = terminal.clone();
        let LearningIterationObservationV1::RetainedModelNextUse {
            retained_bundle,
            state_partition,
            committed_step_receipt,
            task_owner_publication,
            ..
        } = &mut changed.receipts.last_mut().unwrap().observation
        else {
            anyhow::bail!("fixture retained-use observation missing");
        };
        match mutation {
            Mutation::CandidateInsteadOfParent => {
                *retained_bundle = LearningIterationCoordinatorV1::from_snapshot(terminal.clone())?
                    .candidate()
                    .unwrap()
                    .digest()?;
            }
            Mutation::SourceRun => state_partition.run_id = initial.request.source_run_id.clone(),
            Mutation::MissingStep => *committed_step_receipt = Digest32::ZERO,
            Mutation::MissingPublication => *task_owner_publication = Digest32::ZERO,
        }
        assert_eq!(
            record(&scope, &changed)?.read_original_completed_scoped(initial, &scope),
            Err(Error::Snapshot(LearningIterationError::ContextMismatch)),
            "wrong semantic refusal for actual-use mutation: {mutation:?}"
        );
    }
    Ok(())
}

#[test]
fn completed_reader_rejects_truncated_trailing_and_noncanonical_encoded_payloads()
-> anyhow::Result<()> {
    let cuts = snapshots(Decision::EvaluatedNoUpdate)?;
    let initial = &cuts[0];
    let terminal = cuts.last().unwrap();
    let scope = scope(initial)?;
    let original = record(&scope, terminal)?;
    let bytes = codec::encode(terminal)?;
    let mut truncated = original.clone();
    truncated.snapshot = Some(STANDARD_NO_PAD.encode(&bytes[..bytes.len() - 1]));
    let mut trailing_bytes = bytes;
    trailing_bytes.push(/*value*/ 0);
    let mut trailing = original.clone();
    trailing.snapshot = Some(STANDARD_NO_PAD.encode(trailing_bytes));
    let mut noncanonical = original;
    noncanonical.snapshot.as_mut().unwrap().push('=');
    for changed in [truncated, trailing, noncanonical] {
        assert!(
            changed
                .read_original_completed_scoped(initial, &scope)
                .is_err()
        );
    }
    Ok(())
}
