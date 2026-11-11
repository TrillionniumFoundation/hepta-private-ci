//! Original signed task -> actual Decision -> independent business Outcome.
//! CURRENT, issuers, role custody and stage profiles are explicit fixtures;
//! these methods are component checks, not ordinary-loop qualification.

use std::fs;

use codex_hepta_learning_ledger::*;
use codex_hepta_neuron::FileAnchorWitnessStore;
use codex_hepta_neuron::JournalScope;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use ed25519_dalek::SigningKey;
use pretty_assertions::assert_eq;

use super::*;
use crate::OriginalCellQ24TaskLedgerErrorV1 as Error;
use crate::OriginalCellQ24TaskLedgerStatusV1 as Status;
use crate::cell_q24_task_ledger::test_faults;
use crate::learning_iteration::CircuitLearningSourceV1;
use crate::learning_owner_journal::LearningOriginalOwnerErrorV1;

#[path = "cell_q24_task_ledger_fault_tests.rs"]
mod faults;
#[path = "cell_q24_task_ledger_test_support.rs"]
mod fixture;
#[path = "cell_q24_task_ledger_recovery_support.rs"]
mod recovery;
#[path = "cell_q24_retained_learning_source_tests.rs"]
mod retained_source;

#[path = "cell_q24_task_comparison_tests.rs"]
mod comparison;

use fixture::Fixture;

#[tokio::test]
async fn ordinary_task_ledger_keeps_task_success_until_original_outcome_and_reconcile()
-> anyhow::Result<()> {
    let mut f = Fixture::new(
        "ordinary-ledger-ready",
        /*lifetime*/ 600,
        /*automatic*/ true,
    )
    .await?;
    // Actual execute already returned circuit_succeeded, while learning has
    // only a real witnessed Decision and no invented successful Outcome.
    assert!(matches!(
        f.producer.readback()?,
        Status::AwaitingOutcome { .. }
    ));
    assert_eq!(f.ledger.lock().unwrap().snapshot()?.records().len(), 1);
    let task_bytes = f.task_bytes()?;
    f.no_outbox().await?;
    // Enrollment remains an explicit component fixture. Production obtains
    // this origin from the actual Root Q24 bootstrap, not from a run ID.
    f.session.runtime.state.attach_circuit_learning_delivery(
        vec![f.publication.original_record().snapshot.run_id.clone()],
        CircuitLearningSourceV1::OriginalQ24,
    )?;
    f.reconcile().await?;
    f.no_outbox().await?;
    assert!(matches!(
        f.producer.prepare_dataset(f.preparation()?, Vec::new()),
        Err(Error::PendingOutcome)
    ));
    let outcome = f.outcome();
    let signed = f.sign_outcome(&outcome, /*lifetime*/ 300);
    assert!(matches!(
        f.producer
            .submit_original_terminal_outcome(outcome.clone(), &signed)?,
        Status::Complete { .. }
    ));
    let complete_bytes = f.learning_bytes()?;
    // This is the original startup reconciliation body. It only reads the
    // original RunStart/trace and producer and never calls ObjectiveStart again.
    f.reconcile().await?;
    let row = f
        .session
        .runtime
        .state
        .circuit_task_store()?
        .circuit_learning_delivery(&f.session.request.body.run_id)
        .await
        .unwrap()
        .expect("original Ready completion pointer");
    assert_eq!(
        row.intent.completed_task_receipt,
        *f.publication.history_digest()
    );
    f.reconcile().await?;
    assert_eq!(f.learning_bytes()?, complete_bytes);
    assert!(matches!(
        f.producer
            .submit_original_terminal_outcome(outcome, &signed)?,
        Status::Complete { .. }
    ));
    assert_eq!(f.learning_bytes()?, complete_bytes);
    f.require_task_unchanged(&task_bytes)?;
    let prepared = f
        .producer
        .prepare_learning(f.preparation()?, Vec::new(), f.freeze_inputs()?)?;
    assert!(prepared.initial().receipts.is_empty());
    assert!(!prepared.scope().binding().is_zero());
    let facts = prepared.read_validated_facts()?;
    assert_eq!(
        facts.experience(),
        &codex_hepta_learning_artifacts::LearningIterationObservationV1::Experience {
            episode_digest: f.publication.publication_digest(),
            completed_task_receipt: f.publication.history_digest().as_str().parse()?,
        }
    );
    f.require_task_unchanged(&task_bytes)?;
    f.session.stop().await
}

#[tokio::test]
async fn ordinary_task_ledger_rejects_wrong_business_facts_keys_and_withdrawal()
-> anyhow::Result<()> {
    let mut f = Fixture::new(
        "ordinary-ledger-rejections",
        /*lifetime*/ 600,
        /*automatic*/ true,
    )
    .await?;
    let original = f.learning_bytes()?;
    let valid = f.outcome();
    let mut cases = Vec::new();
    let mut bad = valid.clone();
    bad.episode_id = cell::id("different-original-episode");
    cases.push(bad);
    let mut bad = valid.clone();
    bad.unit_profile_digest = cell::d("different-business-unit");
    cases.push(bad);
    let mut bad = valid.clone();
    bad.support_digest = cell::d("different-source-publication");
    cases.push(bad);
    let mut bad = valid.clone();
    bad.value = None;
    cases.push(bad);
    let mut bad = valid.clone();
    bad.value = Some(FixedQ32::from_raw(9_i64 << 32));
    cases.push(bad);
    let mut bad = valid.clone();
    bad.watermark.terminality = OutcomeTerminalityV1::Pending;
    cases.push(bad);
    let mut bad = valid.clone();
    bad.observed_at = Some(fixture::now() + 600);
    cases.push(bad);
    for bad in cases {
        let signed = f.sign_outcome(&bad, /*lifetime*/ 300);
        assert!(
            f.producer
                .submit_original_terminal_outcome(bad, &signed)
                .is_err()
        );
        assert_eq!(f.learning_bytes()?, original);
    }
    let mut wrong_key = f.sign_outcome(&valid, /*lifetime*/ 300);
    wrong_key.signature[0] ^= 1;
    assert!(
        f.producer
            .submit_original_terminal_outcome(valid.clone(), &wrong_key)
            .is_err()
    );
    let mut wrong_role = f.sign_outcome(&valid, /*lifetime*/ 300);
    wrong_role.role = LearningEvidenceRoleV1::Generator;
    assert!(
        f.producer
            .submit_original_terminal_outcome(valid.clone(), &wrong_role)
            .is_err()
    );
    assert_eq!(f.learning_bytes()?, original);
    f.session
        .source
        .withdraw_for_dataset_test(&f.publication.original_record().snapshot.run_id)?;
    let signed = f.sign_outcome(&valid, /*lifetime*/ 300);
    assert!(
        f.producer
            .submit_original_terminal_outcome(valid, &signed)
            .is_err()
    );
    assert!(f.producer.readback().is_err());
    assert_eq!(f.learning_bytes()?, original);
    f.session.stop().await
}

#[tokio::test]
async fn ordinary_task_ledger_reads_witnessed_history_after_signature_expiry() -> anyhow::Result<()>
{
    let mut f = Fixture::new(
        "ordinary-ledger-delayed-observation",
        /*lifetime*/ 4,
        /*automatic*/ true,
    )
    .await?;
    let generator = test_faults::retained_decision(&f.producer)?;
    fixture::after_expiry(generator.expires_at).await;
    assert!(fixture::now() > generator.expires_at);
    let outcome = f.outcome();
    let signed = f.sign_outcome(&outcome, /*lifetime*/ 4);
    assert!(matches!(
        f.producer
            .submit_original_terminal_outcome(outcome.clone(), &signed)?,
        Status::Complete { .. }
    ));
    let original = f.learning_bytes()?;
    fixture::after_expiry(signed.expires_at).await;
    assert!(matches!(f.producer.readback()?, Status::Complete { .. }));
    assert!(matches!(
        f.producer
            .submit_original_terminal_outcome(outcome, &signed)?,
        Status::Complete { .. }
    ));
    assert_eq!(test_faults::retained_decision(&f.producer)?, generator);
    assert_eq!(f.learning_bytes()?, original);
    f.session.stop().await
}

#[tokio::test]
async fn ordinary_task_ready_rejects_same_run_changed_authentication_and_withdrawal()
-> anyhow::Result<()> {
    let mut f = Fixture::new(
        "ordinary-ledger-ready-binding",
        /*lifetime*/ 600,
        /*automatic*/ true,
    )
    .await?;
    let outcome = f.outcome();
    let signed = f.sign_outcome(&outcome, /*lifetime*/ 300);
    f.producer
        .submit_original_terminal_outcome(outcome, &signed)?;
    let trace = f
        .session
        .runtime
        .state
        .circuit_task_store()?
        .bounded_circuit_committed_trace(&f.session.request.body.run_id)
        .await?
        .expect("original committed trace");
    let record = f.publication.original_record().clone();
    let crate::CircuitTaskLearningReadinessV1::Ready(ready) =
        f.producer
            .observe_learning(&f.session.runtime.identity, &record, &trace)
    else {
        anyhow::bail!("accepted original observations did not become Ready")
    };
    ready.require_task(&f.session.runtime.identity, &record, &trace)?;
    let original = f.learning_bytes()?;
    let mut different = record.clone();
    different.authentication.message_id = StableId::new(format!(
        "{}-different",
        different.authentication.message_id.as_str(),
    ))?;
    assert!(
        ready
            .require_task(&f.session.runtime.identity, &different, &trace)
            .is_err()
    );
    assert!(matches!(
        f.producer
            .observe_learning(&f.session.runtime.identity, &different, &trace),
        crate::CircuitTaskLearningReadinessV1::Pending(
            crate::CircuitTaskLearningPendingV1::Refused(_)
        )
    ));
    assert_eq!(f.learning_bytes()?, original);
    f.session
        .source
        .withdraw_for_dataset_test(&record.snapshot.run_id)?;
    assert!(
        ready
            .require_task(&f.session.runtime.identity, &record, &trace)
            .is_err()
    );
    assert_eq!(f.learning_bytes()?, original);
    f.session.stop().await
}

#[tokio::test]
async fn ordinary_q24_missing_installed_producer_never_falls_back_to_trace_only_learning()
-> anyhow::Result<()> {
    let mut f = Fixture::new(
        "ordinary-ledger-uninstalled-producer",
        /*lifetime*/ 600,
        /*automatic*/ false,
    )
    .await?;
    f.session.runtime.state.attach_circuit_learning_delivery(
        vec![f.publication.original_record().snapshot.run_id.clone()],
        CircuitLearningSourceV1::OriginalQ24,
    )?;
    let task_bytes = f.task_bytes()?;
    f.reconcile().await?;
    f.no_outbox().await?;
    f.producer.resume_from_original_source()?;
    let outcome = f.outcome();
    let signed = f.sign_outcome(&outcome, /*lifetime*/ 300);
    assert!(matches!(
        f.producer
            .submit_original_terminal_outcome(outcome, &signed)?,
        Status::Complete { .. }
    ));
    // Even real accepted data elsewhere is not an installed original producer
    // capability. The plain provider must remain explicitly NonLearning.
    f.reconcile().await?;
    f.no_outbox().await?;
    f.require_task_unchanged(&task_bytes)?;
    f.session.stop().await
}

#[tokio::test]
async fn original_task_preparation_recovers_retained_cut_without_new_freeze() -> anyhow::Result<()>
{
    let mut f = Fixture::new(
        "ordinary-ledger-retained-preparation",
        /*lifetime*/ 600,
        /*automatic*/ true,
    )
    .await?;
    let outcome = f.outcome();
    let signed = f.sign_outcome(&outcome, /*lifetime*/ 300);
    f.producer
        .submit_original_terminal_outcome(outcome, &signed)?;
    let config = f.preparation()?;
    let prepared = f
        .producer
        .prepare_learning(config.clone(), Vec::new(), f.freeze_inputs()?)?;
    let frozen = prepared.frozen_dataset().clone();
    let initial = prepared.initial().clone();
    let scope = prepared.scope().clone();
    let facts = prepared.read_validated_facts()?;
    let freeze_bytes = ["freeze", "freeze.witness"]
        .map(|name| fs::read(f.root.path().join(name)))
        .into_iter()
        .collect::<Result<Vec<_>, _>>()?;
    let task_bytes = f.task_bytes()?;
    test_faults::append_unrelated_decision(&f.producer)?;
    assert!(f.ledger.lock().unwrap().snapshot()?.records().len() > frozen.snapshot.records().len());
    let ledger_bytes = f.learning_bytes()?;
    // Same-cut Recover cannot silently recapture and rewrite this old scope.
    assert!(
        f.producer
            .prepare_learning(config.clone(), Vec::new(), recover_freeze_inputs(&f)?,)
            .is_err()
    );
    let recovered = f.producer.recover_learning(
        config.clone(),
        Vec::new(),
        frozen.clone(),
        &initial,
        &scope,
        recover_freeze_inputs(&f)?,
    )?;
    assert_eq!(recovered.frozen_dataset().snapshot, frozen.snapshot);
    assert_eq!(recovered.frozen_dataset().receipt, frozen.receipt);
    assert_eq!(
        recovered.frozen_dataset().authorization,
        frozen.authorization
    );
    assert_eq!(recovered.initial(), &initial);
    assert_eq!(recovered.scope(), &scope);
    assert_eq!(recovered.read_validated_facts()?, facts);
    let mut changed_authorization = frozen.clone();
    changed_authorization.authorization.signature[0] ^= 1;
    assert!(matches!(
        f.producer.recover_learning(
            config.clone(),
            Vec::new(),
            changed_authorization,
            &initial,
            &scope,
            recover_freeze_inputs(&f)?,
        ),
        Err(Error::Binding("original retained Dataset authorization"))
    ));
    let mut changed_receipt = frozen.clone();
    changed_receipt.receipt.snapshot.dataset_digest = cell::d("not-the-original-dataset");
    assert!(
        f.producer
            .recover_learning(
                config.clone(),
                Vec::new(),
                changed_receipt,
                &initial,
                &scope,
                recover_freeze_inputs(&f)?,
            )
            .is_err()
    );
    let mut changed_initial = initial.clone();
    changed_initial.head_digest = cell::d("not-the-original-empty-initial");
    assert!(
        f.producer
            .recover_learning(
                config.clone(),
                Vec::new(),
                frozen.clone(),
                &changed_initial,
                &scope,
                recover_freeze_inputs(&f)?,
            )
            .is_err()
    );
    assert!(matches!(
        f.producer.recover_learning(
            config.clone(),
            Vec::new(),
            frozen.clone(),
            &initial,
            &scope,
            f.freeze_inputs()?,
        ),
        Err(Error::Binding("retained Dataset requires explicit Recover"))
    ));
    assert_eq!(f.learning_bytes()?, ledger_bytes);
    assert_eq!(
        ["freeze", "freeze.witness"]
            .map(|name| fs::read(f.root.path().join(name)))
            .into_iter()
            .collect::<Result<Vec<_>, _>>()?,
        freeze_bytes
    );
    f.require_task_unchanged(&task_bytes)?;
    f.session
        .source
        .withdraw_for_dataset_test(&f.publication.original_record().snapshot.run_id)?;
    assert!(
        f.producer
            .recover_learning(
                config,
                Vec::new(),
                frozen,
                &initial,
                &scope,
                recover_freeze_inputs(&f)?,
            )
            .is_err()
    );
    assert_eq!(f.learning_bytes()?, ledger_bytes);
    assert_eq!(
        ["freeze", "freeze.witness"]
            .map(|name| fs::read(f.root.path().join(name)))
            .into_iter()
            .collect::<Result<Vec<_>, _>>()?,
        freeze_bytes
    );
    f.session.stop().await
}

fn recover_freeze_inputs(
    f: &Fixture,
) -> anyhow::Result<crate::OriginalCellQ24TaskDatasetFreezeInputsV1> {
    let mut inputs = f.freeze_inputs()?;
    inputs.open_mode = crate::CircuitQ24TaskOpenModeV1::Recover;
    Ok(inputs)
}
