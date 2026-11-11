//! Actual original material reads and retained role signatures. Keys, Root
//! scope and independent outcomes are explicit fixture custody; this is not a
//! claim that an ordinary daemon/Root session or adoption chain ran.

use std::sync::Arc;
use std::sync::atomic::AtomicBool;

use crate::CellQ24TrainingOutcomeV1;
use crate::CellQ24TrainingOwnerV1;
use crate::OriginalCellQ24TrainingReceiptOwnerV1;
use crate::OriginalCellQ24TrainingSigningConfigV1;
use crate::OriginalCellQ24TrainingStageV1;
use codex_hepta_learning_artifacts::LearningIterationObservationV1;

use super::*;

#[path = "cell_q24_material_receipt_support_tests.rs"]
mod support;
use support::Fixture;

fn journal_bytes(owners: &mut support::Owners) -> anyhow::Result<[Vec<u8>; 2]> {
    Ok([
        owners.experience.qualification_file_bytes(1024 * 1024)?,
        owners.dataset.qualification_file_bytes(1024 * 1024)?,
    ])
}

fn dataset_snapshot(
    initial: &LearningIterationSnapshotV1,
    experience: &LearningIterationReceiptV1,
    dataset: &LearningIterationReceiptV1,
) -> anyhow::Result<LearningIterationSnapshotV1> {
    let mut coordinator = LearningIterationCoordinatorV1::from_snapshot(initial.clone())?;
    coordinator.record(experience.clone(), experience.observed_unix_seconds)?;
    coordinator.record(dataset.clone(), dataset.observed_unix_seconds)?;
    Ok(coordinator.snapshot().clone())
}

#[tokio::test]
async fn original_material_pair_signs_recovers_and_feeds_actual_no_update_training()
-> anyhow::Result<()> {
    let mut fixture = Fixture::new(false).await?;
    let config = fixture.config.clone();
    let initial = config.initial.clone();
    let mut owners = fixture.create()?;
    let original_ledger = fixture.writer.qualification_file_bytes(8 * 1024 * 1024)?;
    let experience = owners.attest_experience(fixture.sources(&initial))?;
    assert_eq!(experience.receipt.actor_id, initial.owners.experience);
    assert_eq!(
        experience.attestation.role,
        LearningEvidenceRoleV1::Observer
    );
    let prefix = binding::experience_prefix(&config, &experience.receipt)?;
    let dataset = owners.attest_dataset(fixture.sources(&prefix))?;
    assert_eq!(dataset.receipt.actor_id, initial.owners.dataset);
    assert_ne!(
        dataset.attestation.principal_id,
        experience.attestation.principal_id
    );
    assert_ne!(
        dataset.attestation.signature,
        experience.attestation.signature
    );
    assert_eq!(
        dataset.material.provenance_digest(),
        experience.material.provenance_digest()
    );
    assert_eq!(
        dataset.material.experience_observation(),
        experience.receipt.observation
    );
    assert_eq!(
        dataset.material.dataset_observation(),
        dataset.receipt.observation
    );
    let full = dataset_snapshot(&initial, &experience.receipt, &dataset.receipt)?;
    assert_eq!(
        LearningIterationCoordinatorV1::from_snapshot(full.clone())?.next_stage(),
        Some(LearningIterationStageV1::Training)
    );
    let before = journal_bytes(&mut owners)?;
    let repeated = owners.readback_dataset(fixture.sources(&full))?;
    assert_eq!(repeated.receipt, dataset.receipt);
    assert_eq!(repeated.attestation, dataset.attestation);
    assert_eq!(journal_bytes(&mut owners)?, before);
    assert_eq!(
        fixture.writer.qualification_file_bytes(8 * 1024 * 1024)?,
        original_ledger
    );
    drop(owners);
    let disk_before = fixture.disk_bytes_after_drop()?;
    let mut recovered = fixture.recover(config.clone())?;
    let retained = recovered.attest_dataset(fixture.sources(&full))?;
    assert_eq!(retained.receipt, dataset.receipt);
    assert_eq!(retained.attestation, dataset.attestation);
    assert_eq!(
        retained.material.batch().encoded(),
        dataset.material.batch().encoded()
    );
    assert_eq!(journal_bytes(&mut recovered)?, before);
    drop(recovered);
    assert_eq!(fixture.disk_bytes_after_drop()?, disk_before);

    // This runs the original optimizer and Generator owner, using the actual
    // authenticated zero target. The target was not copied from model output.
    let plan = retained.material.training_plan(
        full.clone(),
        config.scope.clone(),
        Arc::clone(&fixture.baseline),
        fixture.optimizer,
    )?;
    let training = CellQ24TrainingOwnerV1::create(
        fixture.file("native-training", true)?,
        fixture.witness("native-training-witness", true)?,
        plan,
        retained.material.batch().clone(),
        fixture.optimizer,
    )?;
    let receipts = OriginalCellQ24TrainingReceiptOwnerV1::create(
        fixture.file("generator-receipts", true)?,
        fixture.witness("generator-witness", true)?,
        OriginalCellQ24TrainingSigningConfigV1 {
            dataset: full.clone(),
            scope: config.scope,
            signer: fixture.generator.clone(),
            verifier: config.verifier,
            maximum_signature_lifetime_seconds: 300,
        },
        SigningKey::from_bytes(&[1; 32]),
    )?;
    let stage = OriginalCellQ24TrainingStageV1::from_original_owners(training, receipts).await?;
    let trained = stage
        .execute_training(&full, Arc::new(AtomicBool::new(false)))
        .await?;
    let CellQ24TrainingOutcomeV1::NoUpdate {
        retained_bundle,
        metrics,
    } = &trained.outcome
    else {
        anyhow::bail!("zero authenticated residual must preserve the actual quantized row");
    };
    assert_eq!(*retained_bundle, initial.request.selected_bundle.digest()?);
    assert_eq!(metrics.optimizer_steps, 1);
    assert!(matches!(
        trained.receipt.observation,
        LearningIterationObservationV1::TrainingNoUpdateV2(_)
    ));
    let readback = stage.readback(&full).await?;
    assert_eq!(readback.receipt, trained.receipt);
    assert_eq!(readback.attestation, trained.attestation);
    Ok(())
}

#[tokio::test]
async fn original_material_pair_rejects_changed_custody_prefix_and_valid_freeze_resigning()
-> anyhow::Result<()> {
    let mut fixture = Fixture::new(false).await?;
    let config = fixture.config.clone();
    let initial = config.initial.clone();
    let mut wrong = config.clone();
    wrong.dataset_signer = wrong.experience_signer.clone();
    assert!(matches!(
        binding::validate_config(
            &wrong,
            &SigningKey::from_bytes(&[4; 32]),
            &SigningKey::from_bytes(&[5; 32])
        ),
        Err(Error::Owner(LearningOriginalOwnerErrorV1::Binding(
            "original material custody and frozen profile"
        )))
    ));
    let mut owners = fixture.create()?;
    let experience = owners.attest_experience(fixture.sources(&initial))?;
    let before = journal_bytes(&mut owners)?;
    assert!(matches!(
        owners.attest_dataset(fixture.sources(&initial)),
        Err(Error::Owner(LearningOriginalOwnerErrorV1::Binding(
            "exact new Dataset cut"
        )))
    ));
    assert_eq!(journal_bytes(&mut owners)?, before);
    let prefix = binding::experience_prefix(&config, &experience.receipt)?;
    let dataset = owners.attest_dataset(fixture.sources(&prefix))?;
    let mut foreign_experience = experience.receipt.clone();
    foreign_experience.evidence_digest = support::d("foreign-experience-proof");
    let foreign_prefix = binding::experience_prefix(&config, &foreign_experience)?;
    let before = journal_bytes(&mut owners)?;
    assert!(matches!(
        owners.readback_dataset(fixture.sources(&foreign_prefix)),
        Err(Error::Owner(LearningOriginalOwnerErrorV1::Binding(
            "full CURRENT contains another material receipt"
        )))
    ));
    assert_eq!(journal_bytes(&mut owners)?, before);
    drop(owners);
    let disk_before = fixture.disk_bytes_after_drop()?;
    let mut renewed = config.clone();
    renewed.freeze_evidence = fixture.renewed_freeze();
    fixture.assert_renewed_freeze_is_valid(&renewed.freeze_evidence)?;
    assert!(fixture.recover(renewed).is_err());
    assert_eq!(fixture.disk_bytes_after_drop()?, disk_before);
    let mut original = fixture.recover(config)?;
    assert_eq!(
        original
            .readback_dataset(fixture.sources(&prefix))?
            .attestation,
        dataset.attestation
    );
    Ok(())
}

#[tokio::test]
async fn original_material_pair_withdrawal_refuses_cached_material_without_dataset_claim()
-> anyhow::Result<()> {
    let mut fixture = Fixture::new(false).await?;
    let initial = fixture.config.initial.clone();
    let config = fixture.config.clone();
    let mut owners = fixture.create()?;
    let experience = owners.attest_experience(fixture.sources(&initial))?;
    let prefix = binding::experience_prefix(&config, &experience.receipt)?;
    let before = journal_bytes(&mut owners)?;
    let ledger_before = fixture.writer.qualification_file_bytes(8 * 1024 * 1024)?;
    fixture
        .source
        .withdraw_source(&initial.request.source_run_id)?;
    assert!(matches!(
        owners.attest_dataset(fixture.sources(&prefix)),
        Err(Error::Material(_))
    ));
    assert!(matches!(
        owners.readback_experience(fixture.sources(&initial)),
        Err(Error::Material(_))
    ));
    assert_eq!(journal_bytes(&mut owners)?, before);
    assert_eq!(
        fixture.writer.qualification_file_bytes(8 * 1024 * 1024)?,
        ledger_before
    );
    drop(owners);
    let mut recovered = fixture.recover(config)?;
    assert!(matches!(
        recovered.attest_dataset(fixture.sources(&prefix)),
        Err(Error::Material(_))
    ));
    assert_eq!(journal_bytes(&mut recovered)?, before);
    Ok(())
}

#[tokio::test]
async fn original_material_pair_pending_claim_reopens_without_signing_or_replacing_bytes()
-> anyhow::Result<()> {
    let mut fixture = Fixture::new(false).await?;
    let initial = fixture.config.initial.clone();
    let config = fixture.config.clone();
    let mut owners = fixture.create()?;
    let experience = owners.attest_experience(fixture.sources(&initial))?;
    let prefix = binding::experience_prefix(&config, &experience.receipt)?;
    let saved = binding::dataset_saved(&config, owners.dataset_binding, &experience)?;
    // Model interruption after the actual claim/witness but before signing.
    assert!(matches!(
        owners
            .dataset
            .commit_once(&saved, || Err(binding::owner_invalid(
                "interrupted explicit fixture"
            ))),
        Err(LearningOriginalOwnerErrorV1::Binding(
            "interrupted explicit fixture"
        ))
    ));
    let before = journal_bytes(&mut owners)?;
    drop(owners);
    let disk_before = fixture.disk_bytes_after_drop()?;
    let mut recovered = fixture.recover(config)?;
    assert!(matches!(
        recovered.attest_dataset(fixture.sources(&prefix)),
        Err(Error::Owner(LearningOriginalOwnerErrorV1::Pending))
    ));
    assert!(matches!(
        recovered.readback_dataset(fixture.sources(&prefix)),
        Err(Error::Owner(LearningOriginalOwnerErrorV1::Pending))
    ));
    assert_eq!(journal_bytes(&mut recovered)?, before);
    drop(recovered);
    assert_eq!(fixture.disk_bytes_after_drop()?, disk_before);
    Ok(())
}

#[tokio::test]
async fn original_material_pair_expired_work_only_reads_original_completed_windows()
-> anyhow::Result<()> {
    let mut fixture = Fixture::new(true).await?;
    let config = fixture.config.clone();
    let initial = config.initial.clone();
    let mut owners = fixture.create()?;
    let empty = journal_bytes(&mut owners)?;
    assert!(matches!(
        owners.attest_experience(fixture.sources(&initial)),
        Err(Error::Owner(LearningOriginalOwnerErrorV1::Binding(
            "original material work deadline"
        )))
    ));
    assert_eq!(journal_bytes(&mut owners)?, empty);

    // Explicit historical fixture records exercise cold readback after the
    // work deadline; only this test uses private persistence/signing helpers.
    // No public new-work API can create these records at the current time.
    let mut sources = fixture.sources(&initial);
    let material = binding::read_material(&config, &mut sources, true)?;
    let experience_receipt = binding::receipt(
        &config,
        None,
        &material,
        config.initial.request.envelope.expiry_unix_seconds - 2,
    )?;
    let experience_bytes = binding::signed_bytes(
        &config,
        &config.experience_signer,
        &SigningKey::from_bytes(&[4; 32]),
        &experience_receipt,
        owners.experience_saved.binding_digest,
    )?;
    owners
        .experience
        .commit_once(&owners.experience_saved, || Ok(experience_bytes.clone()))?;
    let (_, experience_signature) = learning_owner_evidence::decode(&experience_bytes)?;
    let experience = OriginalCellQ24MaterialCompletionV1 {
        receipt: experience_receipt,
        attestation: experience_signature,
        material,
    };
    let prefix = binding::experience_prefix(&config, &experience.receipt)?;
    let saved = binding::dataset_saved(&config, owners.dataset_binding, &experience)?;
    let dataset_receipt = binding::receipt(
        &config,
        Some(&experience.receipt),
        &experience.material,
        config.initial.request.envelope.expiry_unix_seconds - 1,
    )?;
    let dataset_bytes = binding::signed_bytes(
        &config,
        &config.dataset_signer,
        &SigningKey::from_bytes(&[5; 32]),
        &dataset_receipt,
        saved.binding_digest,
    )?;
    owners
        .dataset
        .commit_once(&saved, || Ok(dataset_bytes.clone()))?;
    let (_, dataset_signature) = learning_owner_evidence::decode(&dataset_bytes)?;
    let full = dataset_snapshot(&initial, &experience.receipt, &dataset_receipt)?;
    let before = journal_bytes(&mut owners)?;
    let completed = owners.readback_dataset(fixture.sources(&full))?;
    assert_eq!(completed.receipt, dataset_receipt);
    assert_eq!(completed.attestation, dataset_signature);
    assert!(completed.receipt.observed_unix_seconds < initial.request.envelope.expiry_unix_seconds);
    assert!(binding::now()? >= initial.request.envelope.expiry_unix_seconds);
    assert_eq!(
        owners.attest_dataset(fixture.sources(&prefix))?.attestation,
        dataset_signature
    );
    assert_eq!(journal_bytes(&mut owners)?, before);
    drop(owners);
    let disk_before = fixture.disk_bytes_after_drop()?;
    let mut recovered = fixture.recover(config)?;
    assert_eq!(
        recovered
            .readback_dataset(fixture.sources(&full))?
            .attestation,
        dataset_signature
    );
    assert_eq!(journal_bytes(&mut recovered)?, before);
    drop(recovered);
    assert_eq!(fixture.disk_bytes_after_drop()?, disk_before);
    Ok(())
}

#[tokio::test]
async fn original_material_pair_partial_creation_never_finishes_missing_dataset_during_recovery()
-> anyhow::Result<()> {
    let fixture = Fixture::new(false).await?;
    let config = fixture.config.clone();
    // The host accidentally supplies a read-only second descriptor. Experience
    // initialization succeeds before the actual Dataset file rejects writing.
    drop(fixture.file("dataset-journal", true)?);
    let files = OriginalCellQ24MaterialReceiptFilesV1 {
        experience: fixture.file("experience-journal", true)?,
        experience_witness: fixture.witness("experience-witness", true)?,
        dataset: fixture.read_only_file("dataset-journal")?,
        dataset_witness: fixture.witness("dataset-witness", true)?,
    };
    assert!(
        support::Owners::create(
            files,
            config.clone(),
            SigningKey::from_bytes(&[4; 32]),
            SigningKey::from_bytes(&[5; 32]),
        )
        .is_err()
    );
    let partial = fixture.disk_bytes_after_drop()?;
    assert!(
        !partial[0].is_empty(),
        "the first original journal did initialize"
    );
    assert!(
        !partial[1].is_empty(),
        "the first independent witness is retained"
    );
    assert!(
        partial[2].is_empty(),
        "the read-only second journal was never initialized"
    );
    let mut dataset_witness = fixture.witness("dataset-witness", false)?;
    assert_eq!(dataset_witness.current()?, None);
    drop(dataset_witness);

    // Even with the original second file now opened read/write, recover is
    // open-only. It cannot take absence as permission to continue creation.
    for _ in 0..2 {
        assert!(fixture.recover(config.clone()).is_err());
        assert_eq!(fixture.disk_bytes_after_drop()?, partial);
    }
    let (saved, _) = binding::validate_config(
        &config,
        &SigningKey::from_bytes(&[4; 32]),
        &SigningKey::from_bytes(&[5; 32]),
    )?;
    let mut experience = LearningOwnerJournalV1::recover(
        fixture.file("experience-journal", false)?,
        fixture.witness("experience-witness", false)?,
        saved.binding_digest,
    )?;
    assert!(matches!(
        experience.read(&saved),
        Err(LearningOriginalOwnerErrorV1::Store(
            ProductEvaluationExecutionStoreErrorV1::Missing
        ))
    ));
    drop(experience);
    assert_eq!(fixture.disk_bytes_after_drop()?, partial);
    Ok(())
}

#[cfg(target_os = "linux")]
pub(crate) use support::ReadbackServiceFixture;
