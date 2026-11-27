//! Original owner compatibility and real journal release. Fixture role keys
//! authorize only this component test, not Root enrollment or independent B.

use pretty_assertions::assert_eq;

use super::*;
use crate::CellQ24DatasetFreezePreparationV1;
use crate::OriginalCellQ24DatasetFreezeOwnerV1;
use crate::OriginalCellQ24DatasetFreezeSigningConfigV1;
use crate::original_q24_dataset_freeze_execution_key_v1;
use crate::original_q24_dataset_preparation_identity_v1;

#[tokio::test]
async fn q24_freeze_pure_identities_match_actual_signature_and_owner_release() -> anyhow::Result<()>
{
    let root = tempfile::tempdir()?;
    let (mut session, baseline, bundle, _current) = ordinary(
        root.path(),
        "pure-freeze-identity",
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
    let config = preparation::config(&dataset, &publication, baseline, bundle)?;
    let phase = CellQ24DatasetFreezePreparationV1::capture(
        config.clone(),
        Arc::clone(&dataset.ledger),
        dataset.tasks.clone(),
    )?;
    let (binding, verifier) = {
        let owner = dataset
            .ledger
            .lock()
            .map_err(|_| anyhow::anyhow!("ledger lock"))?;
        (owner.binding_digest(), owner.verifier().clone())
    };
    let initial =
        LearningIterationCoordinatorV1::new(config.request.clone(), config.owners.clone())?;
    let payload = phase.signing_payload()?;
    let identity = original_q24_dataset_preparation_identity_v1(
        initial.snapshot().head_digest,
        binding,
        &payload,
        config.baseline.effective_weights_digest(),
        config.head,
        config.rule,
    );
    assert_eq!(identity, phase.identity()?);
    let signing = OriginalCellQ24DatasetFreezeSigningConfigV1 {
        signer: dataset.signers[2].clone(),
        verifier,
        maximum_signature_lifetime_seconds: 60,
    };
    let key = original_q24_dataset_freeze_execution_key_v1(
        &config.request.operation_id,
        identity,
        signing.verifier.trust_digest(),
        &signing.signer,
        signing.maximum_signature_lifetime_seconds,
    );
    let mut owner = OriginalCellQ24DatasetFreezeOwnerV1::create(
        file(files.path(), "freeze")?,
        FileAnchorWitnessStore::open(
            file(files.path(), "freeze.witness")?,
            JournalScope {
                scope_digest: identity,
                objective_digest: publication.input().objective_digest,
            },
            Generation::new(1)?,
            /*max_records*/ 16,
        )?,
        &phase,
        signing.clone(),
        SigningKey::from_bytes(&[3; 32]),
    )?;
    let signed = owner.authorize_or_readback(&phase)?;
    assert_eq!(
        signed.evidence_id,
        StableId::new(format!("original-dataset-freeze:{}", key.binding_digest))?
    );
    let journal = File::open(files.path().join("freeze"))?;
    assert!(journal.try_lock_shared().is_err());
    drop(owner);
    journal.try_lock_shared()?;
    let witness = File::open(files.path().join("freeze.witness"))?;
    witness.try_lock_shared()?;
    let mut changed = payload;
    changed.push(0);
    assert_ne!(
        identity,
        original_q24_dataset_preparation_identity_v1(
            initial.snapshot().head_digest,
            binding,
            &changed,
            config.baseline.effective_weights_digest(),
            config.head,
            config.rule,
        )
    );
    assert_ne!(
        key,
        original_q24_dataset_freeze_execution_key_v1(
            &config.request.operation_id,
            identity,
            signing.verifier.trust_digest(),
            &signing.signer,
            signing.maximum_signature_lifetime_seconds + 1,
        )
    );
    session.stop().await?;
    Ok(())
}
