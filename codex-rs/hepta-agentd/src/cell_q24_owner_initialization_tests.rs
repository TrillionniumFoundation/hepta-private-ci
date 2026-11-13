//! Actual component files, signatures and native owners under one Prepared
//! read. Fixture issuers are explicit; this is not ordinary Root acceptance.

use super::*;
use crate::OriginalCellQ24LearningOpenV1 as Mode;
use crate::OriginalCellQ24SourceFilesV1;
use crate::OriginalCellQ24SourceInputsV1;
use crate::OriginalCellQ24SourceJournalV1;
use crate::OriginalCellQ24TrainingFilesV1;
use crate::OriginalCellQ24TrainingInputsV1;
use pretty_assertions::assert_eq;

struct Initialized {
    _experience: OriginalCellQ24SourceReceiptOwnerV1<FileAnchorWitnessStore>,
    _dataset: OriginalCellQ24SourceReceiptOwnerV1<FileAnchorWitnessStore>,
    cut: LearningIterationSnapshotV1,
    stage: OriginalCellQ24TrainingStageV1<FileAnchorWitnessStore, FileAnchorWitnessStore>,
}

fn directories(root: &Path) -> anyhow::Result<()> {
    for name in ["experience", "dataset", "native", "generator"] {
        fs::create_dir(root.join(name))?;
    }
    Ok(())
}

fn sources(root: &Path, fixture: &Fixture) -> anyhow::Result<OriginalCellQ24SourceInputsV1> {
    let journal = |name: &str| -> anyhow::Result<_> {
        let root = root.join(name);
        Ok(OriginalCellQ24SourceJournalV1 {
            journal: file(&root, "source")?,
            witness: original_witness(&root, fixture.prepared.initial())?,
            signer: fixture.dataset.signers[1].clone(),
            key: SigningKey::from_bytes(&[2; 32]),
            maximum_signature_lifetime_seconds: 600,
        })
    };
    Ok(OriginalCellQ24SourceInputsV1::Files(
        OriginalCellQ24SourceFilesV1 {
            experience: journal("experience")?,
            dataset: journal("dataset")?,
        },
    ))
}

fn trainers(
    root: &Path,
    fixture: &Fixture,
    cut: &LearningIterationSnapshotV1,
) -> anyhow::Result<OriginalCellQ24TrainingInputsV1> {
    Ok(OriginalCellQ24TrainingInputsV1::Files(
        OriginalCellQ24TrainingFilesV1 {
            training: file(&root.join("native"), "training")?,
            training_witness: original_witness(&root.join("native"), cut)?,
            receipts: file(&root.join("generator"), "receipt")?,
            receipt_witness: original_witness(&root.join("generator"), cut)?,
            signer: fixture.dataset.signers[0].clone(),
            key: SigningKey::from_bytes(&[1; 32]),
            verifier: fixture.dataset.ledger.lock().unwrap().verifier().clone(),
            maximum_signature_lifetime_seconds: 600,
        },
    ))
}

fn initialize(root: &Path, fixture: &Fixture, mode: Mode) -> anyhow::Result<Initialized> {
    let inputs = sources(root, fixture)?;
    let verifier = fixture.dataset.ledger.lock().unwrap().verifier().clone();
    fixture
        .prepared
        .with_original_prepared_operation(|read| -> anyhow::Result<_> {
            let (mut experience, mut dataset) = inputs.open_original_source_pair_in_operation(
                Arc::clone(&fixture.prepared),
                verifier,
                mode,
                read,
            )?;
            let completion = match mode {
                Mode::Create => {
                    experience.attest_experience_in_operation(read)?;
                    dataset.attest_dataset_in_operation(&mut experience, read)?
                }
                Mode::Recover => dataset.read_dataset_in_operation(&mut experience, read)?,
            };
            let cut = completion.snapshot().clone();
            let (training, receipts) = trainers(root, fixture, &cut)?
                .open_original_training_pair_in_operation(
                    &fixture.prepared,
                    cut.clone(),
                    mode,
                    read,
                )?;
            let stage = OriginalCellQ24TrainingStageV1::from_original_owners_in_operation(
                training,
                receipts,
                &cut,
                fixture.prepared.scope(),
                read,
            )?;
            Ok(Initialized {
                _experience: experience,
                _dataset: dataset,
                cut,
                stage,
            })
        })?
}

fn bytes(root: &Path, groups: &[&str]) -> anyhow::Result<Vec<Vec<u8>>> {
    let mut result = Vec::new();
    for group in groups {
        let journal = match *group {
            "experience" | "dataset" => "source",
            "native" => "training",
            "generator" => "receipt",
            _ => anyhow::bail!("unknown original fixture file group"),
        };
        for name in [journal, "witness"] {
            result.push(fs::read(root.join(group).join(name))?);
        }
    }
    Ok(result)
}

#[tokio::test]
async fn q24_owner_initialization_creates_and_recovers_exact_original_journals()
-> anyhow::Result<()> {
    let mut fixture = Fixture::new("initialization-original-replay").await?;
    let root = tempfile::tempdir()?;
    directories(root.path())?;
    let initialized = initialize(root.path(), &fixture, Mode::Create)?;
    let completed = initialized
        .stage
        .execute_training(&initialized.cut, Arc::new(AtomicBool::new(/*val*/ false)))
        .await?;
    let original = bytes(
        root.path(),
        &["experience", "dataset", "native", "generator"],
    )?;
    let cut = initialized.cut.clone();
    drop(initialized);
    let recovered = initialize(root.path(), &fixture, Mode::Recover)?;
    assert_eq!(recovered.cut, cut);
    let read = recovered.stage.readback(&recovered.cut).await?;
    assert_eq!(
        (read.receipt, read.attestation),
        (completed.receipt, completed.attestation)
    );
    assert_eq!(
        bytes(
            root.path(),
            &["experience", "dataset", "native", "generator"]
        )?,
        original
    );
    fixture.session.stop().await?;
    Ok(())
}

#[tokio::test]
async fn q24_owner_initialization_rejects_another_prepared_before_file_mutation()
-> anyhow::Result<()> {
    let mut fixture = Fixture::new("initialization-original-source").await?;
    let mut other = Fixture::new("initialization-other-source").await?;
    let root = tempfile::tempdir()?;
    directories(root.path())?;
    let source = sources(root.path(), &fixture)?;
    let training = trainers(root.path(), &fixture, &fixture.dataset_cut)?;
    let before = bytes(
        root.path(),
        &["experience", "dataset", "native", "generator"],
    )?;
    let verifier = fixture.dataset.ledger.lock().unwrap().verifier().clone();
    let rejected = other.prepared.with_original_prepared_operation(|read| {
        source.open_original_source_pair_in_operation(
            Arc::clone(&fixture.prepared),
            verifier,
            Mode::Create,
            read,
        )
    })?;
    assert!(rejected.is_err());
    let rejected = other.prepared.with_original_prepared_operation(|read| {
        training.open_original_training_pair_in_operation(
            &fixture.prepared,
            fixture.dataset_cut.clone(),
            Mode::Create,
            read,
        )
    })?;
    assert!(rejected.is_err());
    assert_eq!(
        bytes(
            root.path(),
            &["experience", "dataset", "native", "generator"]
        )?,
        before
    );
    fixture.session.stop().await?;
    other.session.stop().await?;
    Ok(())
}

#[tokio::test]
async fn q24_owner_initialization_error_still_rechecks_the_actual_source() -> anyhow::Result<()> {
    let mut fixture = Fixture::new("initialization-error-source-postcheck").await?;
    let root = tempfile::tempdir()?;
    directories(root.path())?;
    let source = sources(root.path(), &fixture)?;
    let verifier = fixture.dataset.ledger.lock().unwrap().verifier().clone();
    let mut committed = None;
    let result = fixture
        .prepared
        .with_original_prepared_operation(|read| -> anyhow::Result<()> {
            let (mut experience, mut dataset) = source.open_original_source_pair_in_operation(
                Arc::clone(&fixture.prepared),
                verifier,
                Mode::Create,
                read,
            )?;
            experience.attest_experience_in_operation(read)?;
            let actual = dataset.attest_dataset_in_operation(&mut experience, read)?;
            assert_eq!(
                dataset.read_dataset_in_operation(&mut experience, read)?,
                actual
            );
            committed = Some(bytes(root.path(), &["experience", "dataset"])?);
            fixture
                .session
                .source
                .withdraw_for_dataset_test(&fixture.prepared.initial().request.source_run_id)?;
            anyhow::bail!("original owner work failed after Source withdrawal")
        });
    // An inner owner error alone would be Ok(Err(_)); the outer Err proves
    // the enclosing operation still observed the actual Source withdrawal.
    assert!(result.is_err());
    let original =
        committed.ok_or_else(|| anyhow::anyhow!("actual owner stage was not reached"))?;
    assert_eq!(bytes(root.path(), &["experience", "dataset"])?, original);
    fixture.session.stop().await?;
    Ok(())
}

#[tokio::test]
async fn q24_owner_initialization_recover_never_creates_missing_source_receipts()
-> anyhow::Result<()> {
    let mut fixture = Fixture::new("initialization-recover-missing").await?;
    let root = tempfile::tempdir()?;
    directories(root.path())?;
    let source = sources(root.path(), &fixture)?;
    let before = bytes(root.path(), &["experience", "dataset"])?;
    let verifier = fixture.dataset.ledger.lock().unwrap().verifier().clone();
    let rejected = fixture.prepared.with_original_prepared_operation(|read| {
        source.open_original_source_pair_in_operation(
            Arc::clone(&fixture.prepared),
            verifier,
            Mode::Recover,
            read,
        )
    })?;
    assert!(rejected.is_err());
    assert_eq!(bytes(root.path(), &["experience", "dataset"])?, before);
    fixture.session.stop().await?;
    Ok(())
}
