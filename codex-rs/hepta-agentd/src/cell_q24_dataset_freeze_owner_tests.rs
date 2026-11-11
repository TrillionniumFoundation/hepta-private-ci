//! Actual owner journals and original source reads, with explicit fixture trust
//! and role keys. Reopening these owners is not a daemon/Root restart claim.

use pretty_assertions::assert_eq;

use super::*;
use crate::CellQ24DatasetFreezePreparationV1 as Phase;
use crate::LearningOriginalOwnerErrorV1;
use crate::OriginalCellQ24DatasetFreezeErrorV1 as Error;
use crate::OriginalCellQ24DatasetFreezeOwnerV1 as Owner;
use crate::OriginalCellQ24DatasetFreezeSigningConfigV1 as SigningConfig;
use codex_hepta_neuron::AnchorWitnessStore;
use codex_hepta_neuron::WitnessStoreError;

fn signing(dataset: &Dataset) -> SigningConfig {
    SigningConfig {
        signer: dataset.signers[2].clone(),
        verifier: dataset.ledger.lock().unwrap().verifier().clone(),
        maximum_signature_lifetime_seconds: 60,
    }
}

fn freeze_witness(
    root: &Path,
    phase: &Phase,
    objective: Digest32,
) -> anyhow::Result<FileAnchorWitnessStore> {
    Ok(FileAnchorWitnessStore::open(
        file(root, "freeze.witness")?,
        JournalScope {
            scope_digest: phase.identity()?,
            objective_digest: objective,
        },
        Generation::new(1)?,
        /*max_records*/ 16,
    )?)
}

#[tokio::test]
async fn q24_freeze_owner_authorizes_once_and_cold_reopens_original_signature() -> anyhow::Result<()>
{
    let root = tempfile::tempdir()?;
    let (mut session, baseline, bundle, _current) =
        ordinary(root.path(), "freeze-once", /*source_envelope*/ None).await?;
    let publication = execute(&session, /*request_id*/ 1).await?;
    let files = tempfile::tempdir()?;
    let dataset = Dataset::new(
        files.path(),
        &[(&session, &publication, Some(0))],
        OutcomeTerminalityV1::Terminal,
    )?;
    let config = preparation::config(&dataset, &publication, baseline, bundle)?;
    let phase = Phase::capture_original(
        config.clone(),
        Arc::clone(&dataset.ledger),
        session.source.as_ref().clone(),
        &session.cell,
        session.runtime.identity.clone(),
    )?;
    let mut owner = Owner::create(
        file(files.path(), "freeze")?,
        freeze_witness(files.path(), &phase, publication.input().objective_digest)?,
        &phase,
        signing(&dataset),
        SigningKey::from_bytes(&[3; 32]),
    )?;
    let prepared = phase.authorize_and_materialize(&mut owner)?;
    let original = prepared.frozen_dataset().authorization.clone();
    let phase = Phase::recover(
        config.clone(),
        Arc::clone(&dataset.ledger),
        dataset.tasks.clone(),
        prepared.frozen_dataset().snapshot.clone(),
    )?;
    assert_eq!(owner.authorize_or_readback(&phase)?, original);
    let saved = fs::read(files.path().join("freeze"))?;
    let acknowledged = fs::read(files.path().join("freeze.witness"))?;
    drop(owner);
    let mut owner = Owner::recover(
        file(files.path(), "freeze")?,
        freeze_witness(files.path(), &phase, publication.input().objective_digest)?,
        &phase,
        signing(&dataset),
        SigningKey::from_bytes(&[3; 32]),
    )?;
    assert_eq!(owner.readback(&phase)?, original);
    assert_eq!(owner.authorize_or_readback(&phase)?, original);
    assert_eq!(fs::read(files.path().join("freeze"))?, saved);
    assert_eq!(fs::read(files.path().join("freeze.witness"))?, acknowledged);
    dataset.correct()?;
    assert!(owner.readback(&phase).is_err());
    assert!(owner.authorize_or_readback(&phase).is_err());
    assert_eq!(fs::read(files.path().join("freeze"))?, saved);
    session.stop().await?;
    Ok(())
}

#[derive(Clone, Copy)]
enum LostAck {
    BeforeWrite,
    AfterWrite,
}
struct FaultWitness {
    inner: FileAnchorWitnessStore,
    sequence: u64,
    fault: LostAck,
}
impl AnchorWitnessStore for FaultWitness {
    fn current(&self) -> Result<Option<JournalAnchor>, WitnessStoreError> {
        self.inner.current()
    }
    fn compare_and_swap(
        &mut self,
        expected: Option<JournalAnchor>,
        next: JournalAnchor,
    ) -> Result<(), WitnessStoreError> {
        if next.sequence == self.sequence {
            if matches!(self.fault, LostAck::AfterWrite) {
                self.inner.compare_and_swap(expected, next)?;
            }
            return Err(WitnessStoreError::Indeterminate);
        }
        self.inner.compare_and_swap(expected, next)
    }
}

#[tokio::test]
async fn q24_freeze_owner_lost_ack_keeps_pending_or_original_completed_window() -> anyhow::Result<()>
{
    let root = tempfile::tempdir()?;
    let (mut session, baseline, bundle, _current) = ordinary(
        root.path(),
        "freeze-lost-ack",
        /*source_envelope*/ None,
    )
    .await?;
    let publication = execute(&session, /*request_id*/ 1).await?;
    let dataset_root = tempfile::tempdir()?;
    let dataset = Dataset::new(
        dataset_root.path(),
        &[(&session, &publication, Some(0))],
        OutcomeTerminalityV1::Terminal,
    )?;
    let config = preparation::config(&dataset, &publication, baseline, bundle)?;
    for sequence in [2, 3] {
        for fault in [LostAck::BeforeWrite, LostAck::AfterWrite] {
            let files = tempfile::tempdir()?;
            let phase = Phase::capture(
                config.clone(),
                Arc::clone(&dataset.ledger),
                dataset.tasks.clone(),
            )?;
            let original_snapshot = phase.original_snapshot().clone();
            let mut owner = Owner::create(
                file(files.path(), "freeze")?,
                FaultWitness {
                    inner: freeze_witness(
                        files.path(),
                        &phase,
                        publication.input().objective_digest,
                    )?,
                    sequence,
                    fault,
                },
                &phase,
                signing(&dataset),
                SigningKey::from_bytes(&[3; 32]),
            )?;
            assert!(matches!(
                owner.authorize_or_readback(&phase),
                Err(Error::Owner(LearningOriginalOwnerErrorV1::CommitUncertain))
            ));
            drop(owner);
            let recovered = Phase::recover(
                config.clone(),
                Arc::clone(&dataset.ledger),
                dataset.tasks.clone(),
                original_snapshot,
            )?;
            let mut owner = Owner::recover(
                file(files.path(), "freeze")?,
                freeze_witness(
                    files.path(),
                    &recovered,
                    publication.input().objective_digest,
                )?,
                &recovered,
                signing(&dataset),
                SigningKey::from_bytes(&[3; 32]),
            )?;
            let saved = fs::read(files.path().join("freeze"))?;
            if sequence == 2 {
                assert!(matches!(
                    owner.readback(&recovered),
                    Err(Error::Owner(LearningOriginalOwnerErrorV1::Pending))
                ));
                assert!(matches!(
                    owner.authorize_or_readback(&recovered),
                    Err(Error::Owner(LearningOriginalOwnerErrorV1::Pending))
                ));
            } else {
                let signed = owner.readback(&recovered)?;
                assert_eq!(owner.authorize_or_readback(&recovered)?, signed);
                assert_eq!(
                    recovered
                        .materialize_retained(signed.clone())?
                        .frozen_dataset()
                        .authorization,
                    signed
                );
            }
            assert_eq!(fs::read(files.path().join("freeze"))?, saved);
        }
    }
    session.stop().await?;
    Ok(())
}

#[tokio::test]
async fn q24_freeze_owner_rejects_wrong_key_role_identity_and_withdrawn_source()
-> anyhow::Result<()> {
    let root = tempfile::tempdir()?;
    let (mut session, baseline, bundle, _current) =
        ordinary(root.path(), "freeze-refusal", /*source_envelope*/ None).await?;
    let publication = execute(&session, /*request_id*/ 1).await?;
    let files = tempfile::tempdir()?;
    let dataset = Dataset::new(
        files.path(),
        &[(&session, &publication, Some(0))],
        OutcomeTerminalityV1::Terminal,
    )?;
    let config = preparation::config(&dataset, &publication, baseline, bundle)?;
    let phase = Phase::capture(
        config.clone(),
        Arc::clone(&dataset.ledger),
        dataset.tasks.clone(),
    )?;
    for case in ["key", "role"] {
        let attempt = tempfile::tempdir()?;
        let mut signing = signing(&dataset);
        let key = if case == "key" {
            SigningKey::from_bytes(&[8; 32])
        } else {
            signing.signer = dataset.signers[1].clone();
            SigningKey::from_bytes(&[2; 32])
        };
        assert!(
            Owner::create(
                file(attempt.path(), "freeze")?,
                freeze_witness(attempt.path(), &phase, publication.input().objective_digest)?,
                &phase,
                signing,
                key
            )
            .is_err()
        );
        assert!(fs::read(attempt.path().join("freeze"))?.is_empty());
    }
    let mut owner = Owner::create(
        file(files.path(), "freeze")?,
        freeze_witness(files.path(), &phase, publication.input().objective_digest)?,
        &phase,
        signing(&dataset),
        SigningKey::from_bytes(&[3; 32]),
    )?;
    let mut changed = config;
    changed.rule.epochs += 1;
    let wrong = Phase::capture(changed, Arc::clone(&dataset.ledger), dataset.tasks.clone())?;
    let saved = fs::read(files.path().join("freeze"))?;
    assert!(matches!(
        owner.authorize_or_readback(&wrong),
        Err(Error::Owner(LearningOriginalOwnerErrorV1::Binding(
            "original preparation identity"
        )))
    ));
    session
        .source
        .withdraw_for_dataset_test(&publication.input().scope.run_id)?;
    assert!(owner.authorize_or_readback(&phase).is_err());
    assert_eq!(fs::read(files.path().join("freeze"))?, saved);
    session.stop().await?;
    Ok(())
}

#[tokio::test]
async fn q24_freeze_owner_expired_signature_is_not_renewed() -> anyhow::Result<()> {
    let root = tempfile::tempdir()?;
    let (mut session, baseline, bundle, _current) =
        ordinary(root.path(), "freeze-expiry", /*source_envelope*/ None).await?;
    let publication = execute(&session, /*request_id*/ 1).await?;
    let files = tempfile::tempdir()?;
    let dataset = Dataset::new(
        files.path(),
        &[(&session, &publication, Some(0))],
        OutcomeTerminalityV1::Terminal,
    )?;
    let config = preparation::config(&dataset, &publication, baseline, bundle)?;
    let phase = Phase::capture(config, Arc::clone(&dataset.ledger), dataset.tasks.clone())?;
    let mut signing = signing(&dataset);
    signing.maximum_signature_lifetime_seconds = 1;
    let mut owner = Owner::create(
        file(files.path(), "freeze")?,
        freeze_witness(files.path(), &phase, publication.input().objective_digest)?,
        &phase,
        signing,
        SigningKey::from_bytes(&[3; 32]),
    )?;
    owner.authorize_or_readback(&phase)?;
    let saved = fs::read(files.path().join("freeze"))?;
    tokio::time::sleep(std::time::Duration::from_secs(2)).await;
    assert!(matches!(
        owner.readback(&phase),
        Err(Error::Evidence(SignedEvidenceError::ValidityWindow))
    ));
    assert!(matches!(
        owner.authorize_or_readback(&phase),
        Err(Error::Evidence(SignedEvidenceError::ValidityWindow))
    ));
    assert_eq!(fs::read(files.path().join("freeze"))?, saved);
    session.stop().await?;
    Ok(())
}
