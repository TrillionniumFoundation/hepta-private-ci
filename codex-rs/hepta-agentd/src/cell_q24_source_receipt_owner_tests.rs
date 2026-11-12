//! Component checks with the existing real task/Dataset mechanisms and
//! explicit fixture issuers, role keys and CURRENT; no ordinary-loop claim.

use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;

use codex_hepta_neuron::AnchorWitnessStore;
use codex_hepta_neuron::JournalAnchor;
use codex_hepta_neuron::WitnessStoreError;
use codex_hepta_types::AuthorityPosture;

use pretty_assertions::assert_eq;

use super::*;
use crate::CellQ24PreparedLearningV1;
use crate::OriginalCellQ24SourceFilesV1;
use crate::OriginalCellQ24SourceJournalV1;
use crate::OriginalCellQ24SourceReceiptErrorV1 as Error;
use crate::OriginalCellQ24SourceReceiptOwnerV1 as Owner;
use crate::OriginalCellQ24SourceSigningConfigV1 as SigningConfig;
use crate::OriginalCellQ24SourceStageV1 as Stage;
use crate::learning_owner_journal::LearningOriginalOwnerErrorV1;

#[path = "cell_q24_source_receipt_operation_tests.rs"]
mod operation;

async fn source_fixture(
    root: &Path,
    run: &str,
) -> anyhow::Result<(
    support::Session,
    Dataset,
    Arc<CellQ24PreparedLearningV1>,
    VersionFixture,
)> {
    let (session, baseline, bundle, current) =
        ordinary(root, run, /*source_envelope*/ None).await?;
    let publication = execute(&session, /*request_id*/ 1).await?;
    let ledger_root = root.join("source-ledger");
    fs::create_dir(&ledger_root)?;
    let dataset = Dataset::new(
        &ledger_root,
        &[(&session, &publication, Some(2_i64 << 32))],
        OutcomeTerminalityV1::Terminal,
    )?;
    let mut config = preparation::config(&dataset, &publication, baseline, bundle)?;
    config.owners.evidence_trust_digest = dataset.ledger.lock().unwrap().verifier().trust_digest();
    config.owners.experience = dataset.signers[1].principal.principal_id.clone();
    config.owners.dataset = dataset.signers[1].principal.principal_id.clone();
    let prepared = Arc::new(preparation::prepare(config, &dataset)?);
    Ok((session, dataset, prepared, current))
}

fn signing(dataset: &Dataset, stage: Stage) -> SigningConfig {
    SigningConfig {
        stage,
        signer: dataset.signers[1].clone(),
        verifier: dataset.ledger.lock().unwrap().verifier().clone(),
        maximum_signature_lifetime_seconds: 3_600,
    }
}

fn owner(
    root: &Path,
    prepared: &Arc<CellQ24PreparedLearningV1>,
    dataset: &Dataset,
    stage: Stage,
) -> anyhow::Result<Owner<FileAnchorWitnessStore>> {
    Ok(Owner::create(
        file(root, "source")?,
        witness(root, prepared.initial())?,
        Arc::clone(prepared),
        signing(dataset, stage),
        SigningKey::from_bytes(&[2; 32]),
    )?)
}

fn source_files(
    experience: &Path,
    dataset: &Path,
    prepared: &CellQ24PreparedLearningV1,
    sources: &Dataset,
) -> anyhow::Result<OriginalCellQ24SourceFilesV1> {
    let journal = |root: &Path| -> anyhow::Result<OriginalCellQ24SourceJournalV1> {
        Ok(OriginalCellQ24SourceJournalV1 {
            journal: file(root, "source")?,
            witness: witness(root, prepared.initial())?,
            signer: sources.signers[1].clone(),
            key: SigningKey::from_bytes(&[2; 32]),
            maximum_signature_lifetime_seconds: 3_600,
        })
    };
    Ok(OriginalCellQ24SourceFilesV1 {
        experience: journal(experience)?,
        dataset: journal(dataset)?,
    })
}

#[tokio::test]
async fn original_source_receipts_reopen_exact_bytes_and_dataset_uses_original_experience()
-> anyhow::Result<()> {
    let root = tempfile::tempdir()?;
    let (mut session, dataset, prepared, _current) =
        source_fixture(root.path(), "source-observer-once").await?;
    let e_root = tempfile::tempdir()?;
    let d_root = tempfile::tempdir()?;
    let verifier = dataset.ledger.lock().unwrap().verifier().clone();
    let (mut experience, mut dataset_owner) =
        source_files(e_root.path(), d_root.path(), &prepared, &dataset)?
            .create(Arc::clone(&prepared), verifier.clone())?;
    prepared.with_original_prepared_operation(|read| -> anyhow::Result<()> {
        experience.require_prepared_in_operation(&prepared, Stage::Experience, read)?;
        dataset_owner.require_prepared_in_operation(&prepared, Stage::Dataset, read)?;
        assert!(
            experience
                .require_prepared_in_operation(&prepared, Stage::Dataset, read)
                .is_err()
        );
        Ok(())
    })??;
    let e = experience.attest_experience()?;
    let d = dataset_owner.attest_dataset(&mut experience)?;
    assert_eq!(e.attestation().role, LearningEvidenceRoleV1::Observer);
    assert_eq!(d.attestation().role, LearningEvidenceRoleV1::Observer);
    let facts = prepared.read_validated_facts()?;
    assert_eq!(e.receipt().observation, *facts.experience());
    assert_eq!(d.receipt().observation, *facts.dataset());
    assert_eq!(
        d.snapshot().receipts,
        vec![e.receipt().clone(), d.receipt().clone()]
    );
    assert_eq!(e.authority(), AuthorityPosture::DENY_ALL);
    assert_eq!(d.authority(), AuthorityPosture::DENY_ALL);
    let e_bytes = fs::read(e_root.path().join("source"))?;
    let d_bytes = fs::read(d_root.path().join("source"))?;
    assert_eq!(experience.attest_experience()?, e);
    assert_eq!(dataset_owner.attest_dataset(&mut experience)?, d);
    assert_eq!(fs::read(e_root.path().join("source"))?, e_bytes);
    assert_eq!(fs::read(d_root.path().join("source"))?, d_bytes);
    drop(dataset_owner);
    drop(experience);
    let (mut experience, mut dataset_owner) =
        source_files(e_root.path(), d_root.path(), &prepared, &dataset)?
            .recover(Arc::clone(&prepared), verifier)?;
    assert_eq!(experience.read_experience()?, e);
    assert_eq!(dataset_owner.read_dataset(&mut experience)?, d);
    assert_eq!(fs::read(e_root.path().join("source"))?, e_bytes);
    assert_eq!(fs::read(d_root.path().join("source"))?, d_bytes);
    session
        .source
        .withdraw_for_dataset_test(&prepared.initial().request.source_run_id)?;
    assert!(experience.read_experience().is_err());
    assert!(dataset_owner.read_dataset(&mut experience).is_err());
    assert_eq!(fs::read(d_root.path().join("source"))?, d_bytes);
    session.stop().await?;
    Ok(())
}

struct ControlledWitness {
    inner: FileAnchorWitnessStore,
    unavailable: Arc<AtomicBool>,
    fail_at_sequence: Option<u64>,
}

impl AnchorWitnessStore for ControlledWitness {
    fn current(&self) -> Result<Option<JournalAnchor>, WitnessStoreError> {
        if self.unavailable.load(Ordering::SeqCst) {
            return Err(WitnessStoreError::Unavailable);
        }
        self.inner.current()
    }

    fn compare_and_swap(
        &mut self,
        expected: Option<JournalAnchor>,
        next: JournalAnchor,
    ) -> Result<(), WitnessStoreError> {
        if self.fail_at_sequence == Some(next.sequence) {
            return Err(WitnessStoreError::Indeterminate);
        }
        self.inner.compare_and_swap(expected, next)
    }
}

#[tokio::test]
async fn source_dataset_requires_live_experience_witness_before_claiming() -> anyhow::Result<()> {
    let root = tempfile::tempdir()?;
    let (mut session, dataset, prepared, _current) =
        source_fixture(root.path(), "source-observer-witness").await?;
    let e_root = tempfile::tempdir()?;
    let d_root = tempfile::tempdir()?;
    let unavailable = Arc::new(AtomicBool::new(/*v*/ false));
    let mut experience = Owner::create(
        file(e_root.path(), "source")?,
        ControlledWitness {
            inner: witness(e_root.path(), prepared.initial())?,
            unavailable: Arc::clone(&unavailable),
            fail_at_sequence: None,
        },
        Arc::clone(&prepared),
        signing(&dataset, Stage::Experience),
        SigningKey::from_bytes(&[2; 32]),
    )?;
    let mut dataset_owner = owner(d_root.path(), &prepared, &dataset, Stage::Dataset)?;
    let before = fs::read(d_root.path().join("source"))?;
    assert!(matches!(
        dataset_owner.attest_dataset(&mut experience),
        Err(Error::Owner(LearningOriginalOwnerErrorV1::Store(_)))
    ));
    assert_eq!(fs::read(d_root.path().join("source"))?, before);
    experience.attest_experience()?;
    unavailable.store(/*val*/ true, Ordering::SeqCst);
    assert!(dataset_owner.attest_dataset(&mut experience).is_err());
    assert_eq!(fs::read(d_root.path().join("source"))?, before);
    unavailable.store(/*val*/ false, Ordering::SeqCst);
    dataset_owner.attest_dataset(&mut experience)?;
    session.stop().await?;
    Ok(())
}

#[tokio::test]
async fn original_source_lost_witness_ack_preserves_pending_and_completed_records()
-> anyhow::Result<()> {
    let root = tempfile::tempdir()?;
    let (mut session, dataset, prepared, _current) =
        source_fixture(root.path(), "source-observer-reconcile").await?;
    for fail_at_sequence in [2, 3] {
        let files = tempfile::tempdir()?;
        let mut original = Owner::create(
            file(files.path(), "source")?,
            ControlledWitness {
                inner: witness(files.path(), prepared.initial())?,
                unavailable: Arc::new(AtomicBool::new(/*v*/ false)),
                fail_at_sequence: Some(fail_at_sequence),
            },
            Arc::clone(&prepared),
            signing(&dataset, Stage::Experience),
            SigningKey::from_bytes(&[2; 32]),
        )?;
        assert!(matches!(
            original.attest_experience(),
            Err(Error::Owner(LearningOriginalOwnerErrorV1::CommitUncertain))
        ));
        let persisted = fs::read(files.path().join("source"))?;
        drop(original);
        let mut recovered = Owner::recover(
            file(files.path(), "source")?,
            witness(files.path(), prepared.initial())?,
            Arc::clone(&prepared),
            signing(&dataset, Stage::Experience),
            SigningKey::from_bytes(&[2; 32]),
        )?;
        if fail_at_sequence == 2 {
            assert!(matches!(
                recovered.read_experience(),
                Err(Error::Owner(LearningOriginalOwnerErrorV1::Pending))
            ));
            assert!(matches!(
                recovered.attest_experience(),
                Err(Error::Owner(LearningOriginalOwnerErrorV1::Pending))
            ));
        } else {
            let completed = recovered.read_experience()?;
            assert_eq!(recovered.attest_experience()?, completed);
        }
        assert_eq!(fs::read(files.path().join("source"))?, persisted);
    }
    session.stop().await?;
    Ok(())
}

#[tokio::test]
async fn original_source_rejects_wrong_key_role_and_foreign_predecessor_without_writing()
-> anyhow::Result<()> {
    let root = tempfile::tempdir()?;
    let (mut session, dataset, prepared, _current) =
        source_fixture(root.path(), "source-observer-context").await?;
    let bad_key = tempfile::tempdir()?;
    assert!(
        Owner::create(
            file(bad_key.path(), "source")?,
            witness(bad_key.path(), prepared.initial())?,
            Arc::clone(&prepared),
            signing(&dataset, Stage::Experience),
            SigningKey::from_bytes(&[9; 32]),
        )
        .is_err()
    );
    assert!(fs::read(bad_key.path().join("source"))?.is_empty());
    let bad_role = tempfile::tempdir()?;
    let mut invalid = signing(&dataset, Stage::Experience);
    invalid.signer.roles = vec![LearningEvidenceRoleV1::Evaluator];
    assert!(
        Owner::create(
            file(bad_role.path(), "source")?,
            witness(bad_role.path(), prepared.initial())?,
            Arc::clone(&prepared),
            invalid,
            SigningKey::from_bytes(&[2; 32]),
        )
        .is_err()
    );
    assert!(fs::read(bad_role.path().join("source"))?.is_empty());
    let pair_e = tempfile::tempdir()?;
    let pair_d = tempfile::tempdir()?;
    let mut pair = source_files(pair_e.path(), pair_d.path(), &prepared, &dataset)?;
    pair.dataset.key = SigningKey::from_bytes(&[9; 32]);
    let verifier = dataset.ledger.lock().unwrap().verifier().clone();
    assert!(pair.create(Arc::clone(&prepared), verifier).is_err());
    assert!(fs::read(pair_e.path().join("source"))?.is_empty());
    assert!(fs::read(pair_d.path().join("source"))?.is_empty());
    let other_root = tempfile::tempdir()?;
    let (mut other_session, other_dataset, other_prepared, _other_current) =
        source_fixture(other_root.path(), "source-observer-foreign").await?;
    let e_root = tempfile::tempdir()?;
    let d_root = tempfile::tempdir()?;
    let mut experience = owner(
        e_root.path(),
        &other_prepared,
        &other_dataset,
        Stage::Experience,
    )?;
    assert!(
        prepared
            .with_original_prepared_operation(|read| {
                experience.require_prepared_in_operation(&prepared, Stage::Experience, read)
            })?
            .is_err()
    );
    experience.attest_experience()?;
    let mut dataset_owner = owner(d_root.path(), &prepared, &dataset, Stage::Dataset)?;
    let before = fs::read(d_root.path().join("source"))?;
    assert!(dataset_owner.attest_dataset(&mut experience).is_err());
    assert_eq!(fs::read(d_root.path().join("source"))?, before);
    session.stop().await?;
    other_session.stop().await?;
    Ok(())
}
