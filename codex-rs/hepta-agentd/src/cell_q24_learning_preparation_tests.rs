//! Component protocol tests. Issuers, role keys and stage receipts remain
//! explicit fixtures; these tests do not establish an ordinary deployed loop.

use pretty_assertions::assert_eq;

use super::*;
use crate::CellQ24DatasetFreezePreparationV1;
use crate::CellQ24LearningPreparationConfigV1;
use crate::CellQ24LearningPreparationErrorV1 as Error;
use crate::CellQ24PreparedLearningV1;
use crate::HostAuthorityLearningProfileV1;

#[path = "cell_q24_training_source_operation_tests.rs"]
mod source_operation;

pub(super) fn config(
    dataset: &Dataset,
    publication: &CircuitTaskSourcePublicationV1,
    baseline: Arc<LoadedCellQ24ModelV1>,
    bundle: CellCompatibilityBundleV1,
) -> anyhow::Result<CellQ24LearningPreparationConfigV1> {
    let (prefix, _) = training_cut(publication, bundle)?;
    Ok(CellQ24LearningPreparationConfigV1 {
        request: prefix.request,
        owners: prefix.owners,
        baseline,
        head: CellQ24PrivateHeadV1::Drive { index: 0 },
        rule: CellQ24SgdRuleV1 {
            epochs: 2,
            learning_rate_q24: Q / 2,
        },
        projection: dataset.projection.clone(),
        snapshot_id: dataset.receipt.snapshot.snapshot_id.clone(),
    })
}

pub(super) fn prepare(
    config: CellQ24LearningPreparationConfigV1,
    dataset: &Dataset,
) -> anyhow::Result<CellQ24PreparedLearningV1> {
    let preparation = CellQ24DatasetFreezePreparationV1::capture(
        config,
        Arc::clone(&dataset.ledger),
        dataset.tasks.clone(),
    )?;
    let payload = preparation.signing_payload()?;
    let authorization = sign(
        &dataset.ledger.lock().unwrap(),
        LearningEvidenceRoleV1::Evaluator,
        &payload,
    );
    Ok(preparation.materialize(authorization)?)
}

fn dataset_cut(
    prepared: &CellQ24PreparedLearningV1,
) -> anyhow::Result<LearningIterationSnapshotV1> {
    let facts = prepared.read_validated_facts()?;
    let mut coordinator =
        LearningIterationCoordinatorV1::from_snapshot(prepared.initial().clone())?;
    for (observation, evidence) in [
        (
            facts.experience().clone(),
            facts.experience_evidence_digest(),
        ),
        (facts.dataset().clone(), facts.dataset_evidence_digest()),
    ] {
        let mut receipt = learning_test_receipt(&coordinator, observation);
        receipt.evidence_digest = evidence;
        receipt.observed_unix_seconds = now();
        coordinator.record(receipt, now())?;
    }
    Ok(coordinator.snapshot().clone())
}

#[tokio::test]
async fn q24_preparation_freezes_actual_batch_before_empty_root_scope_and_recovers()
-> anyhow::Result<()> {
    let root = tempfile::tempdir()?;
    let (mut session, baseline, bundle, _current) = ordinary(
        root.path(),
        "prepare-original",
        /*source_envelope*/ None,
    )
    .await?;
    let publication = execute(&session, /*request_id*/ 1).await?;
    let files = tempfile::tempdir()?;
    let dataset = Dataset::new(
        files.path(),
        &[(&session, &publication, Some(2_i64 << 32))],
        OutcomeTerminalityV1::Terminal,
    )?;
    let config = config(&dataset, &publication, baseline, bundle)?;
    let prepared = prepare(config.clone(), &dataset)?;
    assert!(prepared.initial().receipts.is_empty());
    let facts = prepared.read_validated_facts()?;
    assert_eq!(
        facts.experience(),
        &LearningIterationObservationV1::Experience {
            episode_digest: publication.publication_digest(),
            completed_task_receipt: publication.history_digest().as_str().parse()?,
        }
    );
    let batch = dataset.batch()?;
    assert_eq!(
        facts.dataset(),
        &LearningIterationObservationV1::Dataset {
            snapshot_digest: dataset.receipt.snapshot.dataset_digest,
            episode_digest: publication.publication_digest(),
            withdrawal_frontier: dataset.receipt.revocation_cut_digest,
            rows: batch.rows(),
            bytes: batch.encoded().len() as u64,
        }
    );
    let identity = &session.runtime.identity;
    let proof = [7; 32];
    let profile = prepared.root_profile(identity, proof)?;
    prepared.require_profile(&profile, identity, proof)?;
    let legacy = HostAuthorityLearningProfileV1::new(
        identity,
        proof,
        config.request.clone(),
        config.owners.clone(),
    )?;
    assert!(matches!(
        prepared.require_profile(&legacy, identity, proof),
        Err(Error::Binding("scoped Root profile required"))
    ));
    assert!(
        prepared
            .require_profile(&profile, identity, [8; 32])
            .is_err()
    );
    let cut = dataset_cut(&prepared)?;
    let material = prepared.training_material(cut.clone(), prepared.scope().clone())?;
    let owner = CellQ24TrainingOwnerV1::create(
        file(files.path(), "prepared-trainer")?,
        witness(files.path(), &cut)?,
        material.plan,
        material.batch,
        material.rule,
    )?;
    let before = fs::read(files.path().join("prepared-trainer"))?;
    owner.require_original_dataset_provenance()?;
    assert_eq!(fs::read(files.path().join("prepared-trainer"))?, before);
    let recovered = CellQ24PreparedLearningV1::recover(
        config.clone(),
        Arc::clone(&dataset.ledger),
        dataset.tasks.clone(),
        prepared.frozen_dataset().clone(),
        prepared.initial(),
        prepared.scope(),
    )?;
    assert_eq!(recovered.read_validated_facts()?, facts);
    assert_eq!(recovered.initial(), prepared.initial());
    assert_eq!(recovered.scope(), prepared.scope());
    let mut wrong = config;
    wrong.rule.epochs += 1;
    wrong.request.budget.maximum_training_steps += 1;
    assert!(
        CellQ24PreparedLearningV1::recover(
            wrong,
            Arc::clone(&dataset.ledger),
            dataset.tasks.clone(),
            prepared.frozen_dataset().clone(),
            prepared.initial(),
            prepared.scope()
        )
        .is_err()
    );
    let mut forged = cut;
    forged.receipts[1].evidence_digest = cell::d("caller-supplied-evidence");
    assert!(matches!(
        prepared.training_material(forged, prepared.scope().clone()),
        Err(Error::Binding(
            "original Experience and Dataset observations"
        ))
    ));
    session.stop().await?;
    Ok(())
}

#[tokio::test]
async fn q24_preparation_rejects_wrong_task_scope_and_observer_as_freezer() -> anyhow::Result<()> {
    let root = tempfile::tempdir()?;
    let (mut session, baseline, bundle, _current) = ordinary(
        root.path(),
        "prepare-binding",
        /*source_envelope*/ None,
    )
    .await?;
    let publication = execute(&session, /*request_id*/ 1).await?;
    let files = tempfile::tempdir()?;
    let dataset = Dataset::new(
        files.path(),
        &[(&session, &publication, Some(0))],
        OutcomeTerminalityV1::Terminal,
    )?;
    let config = config(&dataset, &publication, baseline, bundle)?;
    for field in [
        "source",
        "completed",
        "principal",
        "objective",
        "baseline",
        "expired",
    ] {
        let mut wrong = config.clone();
        match field {
            "source" => wrong.request.source_run_id = cell::id("different-source"),
            "completed" => wrong.request.completed_task_receipt = cell::d("different-completion"),
            "principal" => wrong.request.principal_id = cell::id("different-principal"),
            "objective" => wrong.request.envelope.objective_digest = cell::d("different-objective"),
            "baseline" => wrong.projection.baseline_bundle = cell::d("different-baseline"),
            "expired" => wrong.request.envelope.expiry_unix_seconds = now() - 1,
            _ => unreachable!(),
        }
        assert!(
            CellQ24DatasetFreezePreparationV1::capture(
                wrong,
                Arc::clone(&dataset.ledger),
                dataset.tasks.clone()
            )
            .is_err(),
            "{field}"
        );
    }
    let preparation = CellQ24DatasetFreezePreparationV1::capture(
        config,
        Arc::clone(&dataset.ledger),
        dataset.tasks.clone(),
    )?;
    let payload = preparation.signing_payload()?;
    let authorization = sign(
        &dataset.ledger.lock().unwrap(),
        LearningEvidenceRoleV1::Observer,
        &payload,
    );
    assert!(matches!(
        preparation.materialize(authorization),
        Err(Error::Ledger(_))
    ));
    session.stop().await?;
    Ok(())
}

#[tokio::test]
async fn q24_preparation_rejects_changed_freeze_cut_and_current_correction() -> anyhow::Result<()> {
    let root = tempfile::tempdir()?;
    let (mut session, baseline, bundle, _current) =
        ordinary(root.path(), "prepare-cut", /*source_envelope*/ None).await?;
    let publication = execute(&session, /*request_id*/ 1).await?;
    let files = tempfile::tempdir()?;
    let dataset = Dataset::new(
        files.path(),
        &[(&session, &publication, Some(0))],
        OutcomeTerminalityV1::Terminal,
    )?;
    let config = config(&dataset, &publication, baseline, bundle)?;
    let prepared = prepare(config.clone(), &dataset)?;
    let pending = CellQ24DatasetFreezePreparationV1::capture(
        config.clone(),
        Arc::clone(&dataset.ledger),
        dataset.tasks.clone(),
    )?;
    let payload = pending.signing_payload()?;
    let authorization = sign(
        &dataset.ledger.lock().unwrap(),
        LearningEvidenceRoleV1::Evaluator,
        &payload,
    );
    dataset.correct()?;
    assert!(matches!(
        pending.signing_payload(),
        Err(Error::Binding("original witnessed freeze cut changed"))
    ));
    assert!(matches!(
        pending.materialize(authorization),
        Err(Error::Binding("original witnessed freeze cut changed"))
    ));
    assert!(prepared.read_validated_facts().is_err());
    assert!(
        CellQ24PreparedLearningV1::recover(
            config,
            Arc::clone(&dataset.ledger),
            dataset.tasks.clone(),
            prepared.frozen_dataset().clone(),
            prepared.initial(),
            prepared.scope()
        )
        .is_err()
    );
    session.stop().await?;
    Ok(())
}

#[tokio::test]
async fn q24_preparation_requires_private_capability_and_live_source_on_recovery()
-> anyhow::Result<()> {
    let root = tempfile::tempdir()?;
    let (mut session, baseline, bundle, _current) = ordinary(
        root.path(),
        "prepare-withdrawal",
        /*source_envelope*/ None,
    )
    .await?;
    let publication = execute(&session, /*request_id*/ 1).await?;
    let files = tempfile::tempdir()?;
    let dataset = Dataset::new(
        files.path(),
        &[(&session, &publication, Some(0))],
        OutcomeTerminalityV1::Terminal,
    )?;
    let config = config(&dataset, &publication, baseline, bundle)?;
    let prepared = prepare(config.clone(), &dataset)?;
    let legacy = CellQ24TrainingBatchV1::new(
        dataset.receipt.snapshot.dataset_digest,
        vec![CellQ24TrainingSampleV1 {
            input: vec![Q, Q / 4],
            target: 0,
        }],
    )?;
    assert!(matches!(
        legacy.require_original_dataset_provenance(),
        Err(CellQ24TrainingErrorV1::Binding(
            "original Dataset capability required"
        ))
    ));
    let mut forged = prepared.frozen_dataset().clone();
    forged.authorization.signature[0] ^= 1;
    assert!(
        CellQ24PreparedLearningV1::recover(
            config.clone(),
            Arc::clone(&dataset.ledger),
            dataset.tasks.clone(),
            forged,
            prepared.initial(),
            prepared.scope()
        )
        .is_err()
    );
    session
        .source
        .withdraw_for_dataset_test(&publication.input().scope.run_id)?;
    assert!(prepared.read_validated_facts().is_err());
    assert!(
        prepared
            .root_profile(&session.runtime.identity, [7; 32])
            .is_err()
    );
    assert!(
        CellQ24PreparedLearningV1::recover(
            config,
            Arc::clone(&dataset.ledger),
            dataset.tasks.clone(),
            prepared.frozen_dataset().clone(),
            prepared.initial(),
            prepared.scope()
        )
        .is_err()
    );
    session.stop().await?;
    Ok(())
}
