//! Direct recovered Observer calls use real journals, witnesses and ordinary C.
//! Original Training/Selection signatures and peer transport remain explicit
//! mechanism fixtures. These tests do not qualify a native training run.

use pretty_assertions::assert_eq;

use super::*;
use codex_hepta_intelligence_eval::ProductEvaluationExecutionStoreErrorV1;
use codex_hepta_neuron::AnchorWitnessStore;
use codex_hepta_neuron::JournalAnchor;
use codex_hepta_neuron::WitnessStoreError;

use crate::OriginalCircuitNextUseReceiptErrorV1;
use crate::learning_iteration_evidence_client::fixture_original_receipt_client_until_close;
use crate::learning_owner_journal::LearningOriginalOwnerErrorV1 as OwnerError;

type EvidenceThread = std::thread::JoinHandle<anyhow::Result<usize>>;

struct ReadbackPeers {
    trainer: LearningIterationEvidenceClientV1,
    selector: LearningIterationEvidenceClientV1,
    trainer_thread: EvidenceThread,
    selector_thread: EvidenceThread,
}

impl ReadbackPeers {
    fn new(f: &ObserverFixture) -> anyhow::Result<Self> {
        let (trainer, trainer_thread) = fixture_original_receipt_client_until_close(
            f.initial.clone(),
            f.training.clone(),
            f.config.verifier.clone(),
            f.training_signature.clone(),
        )?;
        let (selector, selector_thread) = fixture_original_receipt_client_until_close(
            f.initial.clone(),
            f.selection.clone(),
            f.config.verifier.clone(),
            f.selection_signature.clone(),
        )?;
        Ok(Self {
            trainer,
            selector,
            trainer_thread,
            selector_thread,
        })
    }

    fn sources<'a>(
        &'a self,
        f: &'a ObserverFixture,
    ) -> OriginalCircuitNextUseReceiptSourcesV1<'a, FileAnchorWitnessStore, FileAnchorWitnessStore>
    {
        OriginalCircuitNextUseReceiptSourcesV1 {
            snapshot: &f.config.selection,
            cell: &f.session.cell,
            source: f.session.source.as_ref(),
            identity: &f.session.runtime.identity,
            trainer: &self.trainer,
            selector: &self.selector,
        }
    }

    fn finish(self) -> anyhow::Result<(usize, usize)> {
        drop(self.trainer);
        drop(self.selector);
        let trainer = self
            .trainer_thread
            .join()
            .map_err(|_| anyhow::anyhow!("recovered Observer Trainer fixture panicked"))??;
        let selector = self
            .selector_thread
            .join()
            .map_err(|_| anyhow::anyhow!("recovered Observer Selector fixture panicked"))??;
        Ok((trainer, selector))
    }
}

async fn completed_fixture() -> anyhow::Result<ObserverFixture> {
    let f = ObserverFixture::ready().await?;
    let publication = execute(&f.session, 1).await?;
    let actual = read_receipt(&f.session, &f.definition, &publication)?;
    assert_eq!(actual.bundle_digest, f.previous_decision.bundle_digest);
    assert_ne!(
        publication.input().scope.run_id,
        f.previous.input().scope.run_id
    );
    let selected = LearningIterationCoordinatorV1::from_snapshot(f.config.selection.clone())?;
    assert!(matches!(
        f.session.cell.read_learning_next_use(
            &selected,
            f.session.source.as_ref(),
            &f.session.runtime.identity,
        )?,
        LearningIterationObservationV1::RetainedModelNextUse { .. }
    ));
    Ok(f)
}

#[tokio::test]
async fn recovered_observer_direct_attest_does_not_claim_missing_operation() -> anyhow::Result<()> {
    let mut f = completed_fixture().await?;
    drop(f.create_owner()?);
    let mut recovered = f.recover_owner()?;
    let before = f.bytes()?;
    let peers = ReadbackPeers::new(&f)?;

    // Both real predecessor peers can answer any request within their original
    // 128-frame bound. Missing cannot be manufactured by an exhausted fixture.
    let result = recovered
        .attest_original_completion(peers.sources(&f))
        .await;
    let after = f.bytes()?;
    drop(recovered);
    let reads = peers.finish()?;
    f.session.stop().await?;

    assert!(matches!(
        result,
        Err(OriginalCircuitNextUseReceiptErrorV1::Owner(
            OwnerError::Store(ProductEvaluationExecutionStoreErrorV1::Missing)
        ))
    ));
    assert_eq!(after, before);
    assert_eq!(reads, (0, 0));
    Ok(())
}

struct RefuseClaimWitness {
    original: FileAnchorWitnessStore,
    calls: usize,
}

impl AnchorWitnessStore for RefuseClaimWitness {
    fn current(&self) -> Result<Option<JournalAnchor>, WitnessStoreError> {
        self.original.current()
    }

    fn compare_and_swap(
        &mut self,
        expected: Option<JournalAnchor>,
        next: JournalAnchor,
    ) -> Result<(), WitnessStoreError> {
        self.calls += 1;
        // Create is witnessed normally. The durable claim is real, but its
        // witness ACK is indeterminate before any signature can be completed.
        if self.calls == 2 {
            return Err(WitnessStoreError::Indeterminate);
        }
        self.original.compare_and_swap(expected, next)
    }
}

#[tokio::test]
async fn recovered_observer_direct_attest_keeps_real_pending_unresolved() -> anyhow::Result<()> {
    let mut f = completed_fixture().await?;
    let peers = ReadbackPeers::new(&f)?;
    let mut original = OriginalCircuitNextUseReceiptOwnerV1::create(
        f.file("observer.journal", true)?,
        RefuseClaimWitness {
            original: f.witness(true)?,
            calls: 0,
        },
        f.config.clone(),
        SigningKey::from_bytes(&[103; 32]),
    )?;
    let first = original.attest_original_completion(peers.sources(&f)).await;
    drop(original);

    // Recovery may perform the journal's existing witnessed suffix catch-up.
    // The direct attest call below must not perform another claim or append.
    let mut recovered = f.recover_owner()?;
    let before = f.bytes()?;
    let result = recovered
        .attest_original_completion(peers.sources(&f))
        .await;
    let readback = recovered.readback(peers.sources(&f)).await;
    let after = f.bytes()?;
    drop(recovered);
    let reads = peers.finish()?;
    f.session.stop().await?;

    assert!(matches!(
        first,
        Err(OriginalCircuitNextUseReceiptErrorV1::Owner(
            OwnerError::CommitUncertain
        ))
    ));
    assert!(matches!(
        result,
        Err(OriginalCircuitNextUseReceiptErrorV1::Owner(
            OwnerError::Pending
        ))
    ));
    assert!(matches!(
        readback,
        Err(OriginalCircuitNextUseReceiptErrorV1::Owner(
            OwnerError::Pending
        ))
    ));
    assert_eq!(after, before);
    assert_eq!(reads, (1, 1));
    Ok(())
}

#[tokio::test]
async fn recovered_observer_direct_attest_returns_exact_completed_signature() -> anyhow::Result<()>
{
    let mut f = completed_fixture().await?;
    let peers = ReadbackPeers::new(&f)?;
    let mut original = f.create_owner()?;
    let saved = original
        .attest_original_completion(peers.sources(&f))
        .await?;
    let before = f.bytes()?;
    drop(original);

    let mut recovered = f.recover_owner()?;
    let result = recovered
        .attest_original_completion(peers.sources(&f))
        .await;
    let after = f.bytes()?;
    drop(recovered);
    let reads = peers.finish()?;
    f.session.stop().await?;

    assert_eq!(result?, saved);
    assert_eq!(after, before);
    // Fresh signing brackets the effect with two reads; the recovered call
    // performs the existing single local readback protocol without a claim.
    assert_eq!(reads, (3, 3));
    Ok(())
}
