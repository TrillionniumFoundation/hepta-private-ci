//! Ordinary signed A/C, actual same-model publication and real sealed Cell
//! completion. TrainingNoUpdate, peer credentials and FinalUse issuer keys are
//! explicit engineering fixtures, not original training or production custody.

use codex_hepta_learning_artifacts::LearningIterationCoordinatorV1;
use codex_hepta_learning_artifacts::LearningIterationDispositionV1;
use codex_hepta_learning_artifacts::LearningIterationObservationV1;
use pretty_assertions::assert_eq;

use super::*;
use crate::OriginalCircuitNextUseReceiptErrorV1;

#[path = "circuit_q24_next_use_observer_support_tests.rs"]
mod observer_support;

use observer_support::ObserverFixture;

#[tokio::test]
async fn q24_ordinary_original_observer_attests_and_recovers_exact_completed_next_use()
-> anyhow::Result<()> {
    let mut f = ObserverFixture::ready().await?;
    let publication = execute(&f.session, 1).await?;
    let actual = read_receipt(&f.session, &f.definition, &publication)?;
    assert_ne!(
        publication.input().scope.run_id,
        f.previous.input().scope.run_id
    );
    assert_ne!(
        publication.input().observation,
        f.previous.input().observation
    );
    assert_eq!(actual.bundle_digest, f.previous_decision.bundle_digest);
    assert_ne!(
        actual.checkpoint_after,
        f.previous_decision.checkpoint_after
    );
    let selected = LearningIterationCoordinatorV1::from_snapshot(f.config.selection.clone())?;
    let expected = f.session.cell.read_learning_next_use(
        &selected,
        f.session.source.as_ref(),
        &f.session.runtime.identity,
    )?;
    assert!(matches!(
        &expected,
        LearningIterationObservationV1::RetainedModelNextUse { .. }
    ));

    // Exactly two original reads per peer for attestation, then one for each
    // of the two readbacks. A saved receipt never invokes another signer.
    let peers = f.peers(4)?;
    let mut owner = f.create_owner()?;
    let saved = owner
        .attest_original_completion(f.sources(&f.config.selection, &peers))
        .await?;
    assert_eq!(saved.0.observation, expected);
    assert_eq!(saved.0.observed_unix_seconds, saved.1.issued_at);
    assert!(saved.1.expires_at > saved.1.issued_at);
    assert!(saved.1.expires_at - saved.1.issued_at <= 300);
    let bytes = f.bytes()?;
    assert_eq!(
        owner
            .readback(f.sources(&f.config.selection, &peers))
            .await?,
        saved
    );
    assert_eq!(f.bytes()?, bytes);
    let mut completed = LearningIterationCoordinatorV1::from_snapshot(f.config.selection.clone())?;
    completed.record(saved.0.clone(), saved.0.observed_unix_seconds)?;
    assert_eq!(
        completed.disposition(),
        LearningIterationDispositionV1::UsedByNextTask
    );
    assert_eq!(completed.next_stage(), None);

    // Drop only this Observer owner, then recover its same files, witness,
    // identity and original signature window. This is not a daemon restart.
    drop(owner);
    let mut recovered = f.recover_owner()?;
    assert_eq!(f.bytes()?, bytes);
    assert_eq!(
        recovered
            .readback(f.sources(completed.snapshot(), &peers))
            .await?,
        saved
    );
    assert_eq!(f.bytes()?, bytes);

    // The original artifact owner withdraws the retained selection. Historical
    // Observer bytes cannot make the live sealed Cell current again.
    f.version.withdraw()?;
    let rejected = recovered
        .readback(f.sources(completed.snapshot(), &peers))
        .await;
    assert!(matches!(
        rejected,
        Err(OriginalCircuitNextUseReceiptErrorV1::Observation(_))
    ));
    assert_eq!(f.bytes()?, bytes);
    drop(recovered);
    peers.finish()?;
    f.session.stop().await?;
    Ok(())
}

#[tokio::test]
async fn q24_ordinary_original_observer_refuses_uncommitted_or_withdrawn_next_use()
-> anyhow::Result<()> {
    for change in ["uncommitted", "withdrawn"] {
        let mut f = ObserverFixture::ready().await?;
        if change == "withdrawn" {
            let publication = execute(&f.session, 1).await?;
            read_receipt(&f.session, &f.definition, &publication)?;
            f.version.withdraw()?;
        }
        let peers = f.peers(0)?;
        let mut owner = f.create_owner()?;
        let before = f.bytes()?;
        let rejected = owner
            .attest_original_completion(f.sources(&f.config.selection, &peers))
            .await;
        // A mistaken peer request would produce Connection, not Observation:
        // this checks the actual missing/stale sealed completion before claim.
        assert!(
            matches!(
                rejected,
                Err(OriginalCircuitNextUseReceiptErrorV1::Observation(_))
            ),
            "{change}"
        );
        assert_eq!(f.bytes()?, before, "{change}");
        drop(owner);
        let mut recovered = f.recover_owner()?;
        assert_eq!(f.bytes()?, before, "{change}");
        let rejected = recovered
            .readback(f.sources(&f.config.selection, &peers))
            .await;
        assert!(
            matches!(
                rejected,
                Err(OriginalCircuitNextUseReceiptErrorV1::Observation(_))
            ),
            "{change}"
        );
        assert_eq!(f.bytes()?, before, "{change}");
        drop(recovered);
        peers.finish()?;
        f.session.stop().await?;
    }
    Ok(())
}
