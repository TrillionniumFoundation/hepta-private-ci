//! Same-A evaluated retention with an actual completed baseline C and original
//! read-only Selector service. Enrollment/measurement/transport are fixtures;
//! these mechanisms do not qualify an ordinary daemon/Root loop.

use super::*;
use pretty_assertions::assert_eq;
use pretty_assertions::assert_ne;
use std::sync::Arc;

use crate::OriginalCircuitEvaluatedNextUseReceiptConfigV1;
use crate::OriginalCircuitEvaluatedNextUseReceiptSourcesV1;
use crate::OriginalCircuitEvaluatedSelectionReadbackErrorV1;
use crate::OriginalCircuitEvaluatedSelectionReadbackOwnerV1;
use crate::OriginalCircuitEvaluatedSelectionReceiptV1;
use crate::OriginalCircuitNextUseReceiptErrorV1 as NextUseError;
use crate::OriginalCircuitNextUseReceiptOwnerV1;
use crate::OriginalCircuitRetainedPublicationErrorV1 as PublicationError;

type Observer = OriginalCircuitNextUseReceiptOwnerV1<FileAnchorWitnessStore>;
type SelectorHost = OriginalCircuitEvaluatedSelectionReadbackOwnerV1<
    FileAnchorWitnessStore,
    FileAnchorWitnessStore,
>;
type SelectorPeer =
    std::thread::JoinHandle<Result<u64, OriginalCircuitEvaluatedSelectionReadbackErrorV1>>;

fn observer(
    files: &SelectorFiles,
    f: &PublicationFixture,
    selection: &OriginalCircuitEvaluatedSelectionReceiptV1,
    mode: OpenReceipt,
) -> anyhow::Result<Observer> {
    let (journal, witness) = files.files(f, &mode)?;
    let config = OriginalCircuitEvaluatedNextUseReceiptConfigV1 {
        // Supply the fresh original S even during recovery; the recovered C's
        // output must permanently attenuate those pins to readback.
        selection: selection.clone(),
        signer: f.host.original.credentials.observer.clone(),
        maximum_signature_lifetime_seconds: 300,
    };
    let key = ed25519_dalek::SigningKey::from_bytes(&[43; 32]);
    Ok(match mode {
        OpenReceipt::Fresh => Observer::create_evaluated(journal, witness, config, key)?,
        OpenReceipt::Readback => Observer::recover_evaluated(journal, witness, config, key)?,
    })
}

fn next_sources<'a>(
    snapshot: &'a LearningIterationSnapshotV1,
    c: &'a support::Session,
    trainer: &'a OriginalCellQ24TrainingCommandClientV1,
    evaluator: &'a OriginalCellEvaluationCommandClientV1,
    selector: &'a crate::LearningIterationEvidenceClientV1,
) -> OriginalCircuitEvaluatedNextUseReceiptSourcesV1<
    'a,
    FileAnchorWitnessStore,
    FileAnchorWitnessStore,
> {
    OriginalCircuitEvaluatedNextUseReceiptSourcesV1 {
        snapshot,
        cell: &c.cell,
        source: c.source.as_ref(),
        identity: &c.runtime.identity,
        trainer,
        evaluator,
        selector,
    }
}

fn selector_peer(
    owner: Selector,
    selection: &OriginalCircuitEvaluatedSelectionReceiptV1,
    c: &support::Session,
    trainer: &Arc<OriginalCellQ24TrainingCommandClientV1>,
    evaluator: &Arc<OriginalCellEvaluationCommandClientV1>,
    invalidate_source_after_read: Option<(u64, File)>,
) -> anyhow::Result<(
    Arc<SelectorHost>,
    crate::LearningIterationEvidenceClientV1,
    SelectorPeer,
)> {
    // This existing Clone shares the same original Cell journal and sealed
    // task. It is a read-only view, not a reopened owner or private writer.
    let host = Arc::new(owner.into_evaluated_readback_owner(
        selection.clone(),
        c.cell.clone(),
        Arc::clone(trainer),
        Arc::clone(evaluator),
    )?);
    let (client, peer) = host.fixture_original_client(invalidate_source_after_read)?;
    Ok((host, client, peer))
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn evaluated_c_reads_original_t_b_s_and_recovers_exact_baseline_completion()
-> anyhow::Result<()> {
    let mut f = Box::pin(PublicationFixture::ready()).await?;
    let (mut c, trainer, evaluator, peers) = Box::pin(published(&mut f)).await?;
    let trainer = Arc::new(trainer);
    let evaluator = Arc::new(evaluator);
    let selection_files = SelectorFiles::new()?;
    let mut selector = selection_files.owner(&f, OpenReceipt::Fresh)?;
    let selected = selector
        .attest_original_evaluated_selection(sources(
            f.evaluation.snapshot(),
            &c,
            &trainer,
            &evaluator,
        ))
        .await?;
    let original_s = selection_files.bytes()?;
    let (host, selector, selector_thread) =
        selector_peer(selector, &selected, &c, &trainer, &evaluator, None)?;
    host.fixture_reject_wrong_requests()?;
    let files = SelectorFiles::new()?;
    let mut owner = observer(&files, &f, &selected, OpenReceipt::Fresh)?;
    let empty = files.bytes()?;
    // S alone and an unused C publication cannot stand in for a completed C.
    assert!(matches!(
        owner
            .attest_original_evaluated_completion(next_sources(
                selected.snapshot(),
                &c,
                &trainer,
                &evaluator,
                &selector,
            ))
            .await,
        Err(NextUseError::Observation(_))
    ));
    assert_eq!(files.bytes()?, empty);
    let publication = execute(&c, 1).await?;
    let actual = read_receipt(&c, &f.definition, &publication)?;
    assert_eq!(actual.bundle_digest, f.bundle.digest()?);
    assert_ne!(actual.bundle_digest, f.host.original.candidate.digest()?);
    assert_eq!(
        actual.representation.prediction_q24,
        vec![Q / 4, Q, 0, 0, 0]
    );
    let completed = owner
        .attest_original_evaluated_completion(next_sources(
            selected.snapshot(),
            &c,
            &trainer,
            &evaluator,
            &selector,
        ))
        .await
        .map_err(|error| anyhow::anyhow!("first original completed C attestation: {error:?}"))?;
    assert_eq!(completed.snapshot().receipts.len(), 6);
    assert_eq!(
        &completed.snapshot().receipts[..5],
        &selected.snapshot().receipts
    );
    assert_eq!(
        LearningIterationCoordinatorV1::from_snapshot(completed.snapshot().clone())?.next_stage(),
        None
    );
    assert!(matches!(
        completed.receipt().observation,
        LearningIterationObservationV1::RetainedModelNextUse { retained_bundle, .. }
        if retained_bundle == f.bundle.digest()?
    ));
    let committed = files.bytes()?;
    assert_ne!(committed, empty);
    let read = owner
        .readback_evaluated_completion(next_sources(
            completed.snapshot(),
            &c,
            &trainer,
            &evaluator,
            &selector,
        ))
        .await?;
    assert_eq!(
        (read.snapshot(), read.receipt(), read.attestation()),
        (
            completed.snapshot(),
            completed.receipt(),
            completed.attestation()
        )
    );

    // A structurally valid completed snapshot with another Selection prefix
    // is an adversarial metadata input, never an original signed receipt.
    let mut other = LearningIterationCoordinatorV1::from_snapshot(f.evaluation.snapshot().clone())?;
    let mut other_selection = selected.receipt().clone();
    other_selection.evidence_digest = Digest32::of_bytes(b"changed Selection prefix");
    other.record(
        other_selection.clone(),
        other_selection.observed_unix_seconds,
    )?;
    let mut other_completion = completed.receipt().clone();
    other_completion.predecessor = other.snapshot().head_digest;
    other.record(
        other_completion.clone(),
        other_completion.observed_unix_seconds,
    )?;
    assert!(matches!(
        owner
            .readback_evaluated_completion(next_sources(
                other.snapshot(),
                &c,
                &trainer,
                &evaluator,
                &selector,
            ))
            .await,
        Err(NextUseError::Owner(OwnerError::Binding(
            "original Selection prefix"
        )))
    ));
    assert_eq!(files.bytes()?, committed);
    drop(owner);
    let mut recovered = observer(&files, &f, &selected, OpenReceipt::Readback)?;
    let read = recovered
        .attest_original_evaluated_completion(next_sources(
            completed.snapshot(),
            &c,
            &trainer,
            &evaluator,
            &selector,
        ))
        .await?;
    assert_eq!(
        (read.snapshot(), read.receipt(), read.attestation()),
        (
            completed.snapshot(),
            completed.receipt(),
            completed.attestation()
        )
    );
    assert!(matches!(
        read.original_selection()
            .original_context()
            .require_new_original_receipt(now()?),
        Err(PublicationError::Binding(
            "recovered evaluated retention is read-only"
        ))
    ));
    assert_eq!(files.bytes()?, committed);
    assert_eq!(selection_files.bytes()?, original_s);
    assert_eq!(c.cell.snapshot(&f.source_c.scope)?.revision, 1);
    drop(recovered);
    drop(selector);
    assert_eq!(selector_thread.join().expect("original read-only S")?, 6);
    drop(host);

    // Reopen S only after its original host has been released. A fresh caller
    // supplied context cannot promote this recovered S into new C work.
    let mut recovered_s = selection_files.owner(&f, OpenReceipt::Readback)?;
    let cold_s = recovered_s
        .readback_evaluated_selection(sources(selected.snapshot(), &c, &trainer, &evaluator))
        .await?;
    let cold_files = SelectorFiles::new()?;
    let (journal, witness) = cold_files.files(&f, &OpenReceipt::Fresh)?;
    let unchanged = cold_files.bytes()?;
    assert!(matches!(
        Observer::create_evaluated(
            journal,
            witness,
            OriginalCircuitEvaluatedNextUseReceiptConfigV1 {
                selection: cold_s,
                signer: f.host.original.credentials.observer.clone(),
                maximum_signature_lifetime_seconds: 300,
            },
            ed25519_dalek::SigningKey::from_bytes(&[43; 32]),
        ),
        Err(NextUseError::Evaluated(PublicationError::Binding(
            "recovered evaluated retention is read-only"
        )))
    ));
    assert_eq!(cold_files.bytes()?, unchanged);
    assert_eq!(selection_files.bytes()?, original_s);
    drop(recovered_s);
    drop(trainer);
    drop(evaluator);
    assert_eq!(peers.finish()?, [26, 26]);
    c.stop().await?;
    drop(c);
    f.finish().await
}

// Each fault retains its own fresh original owners and the original test timeout.
// The pre-existing test name covers Trainer; the two siblings complete the roster.
#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn evaluated_c_refuses_each_actual_original_predecessor_without_claim() -> anyhow::Result<()>
{
    Box::pin(refuses_original_predecessor(OriginalPredecessorFault::Trainer)).await
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn evaluated_c_refuses_original_evaluator_without_claim() -> anyhow::Result<()> {
    Box::pin(refuses_original_predecessor(OriginalPredecessorFault::Evaluator)).await
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn evaluated_c_refuses_original_selector_without_claim() -> anyhow::Result<()> {
    Box::pin(refuses_original_predecessor(OriginalPredecessorFault::Selector)).await
}

#[derive(Clone, Copy, Eq, PartialEq)]
enum OriginalPredecessorFault {
    Trainer,
    Evaluator,
    Selector,
}

async fn refuses_original_predecessor(predecessor: OriginalPredecessorFault) -> anyhow::Result<()> {
    let mut f = Box::pin(PublicationFixture::ready()).await?;
    let (mut c, trainer, evaluator, peers) = Box::pin(published(&mut f)).await?;
    let trainer = Arc::new(trainer);
    let evaluator = Arc::new(evaluator);
    let selection_files = SelectorFiles::new()?;
    let mut original_s = selection_files.owner(&f, OpenReceipt::Fresh)?;
    let selected = original_s
        .attest_original_evaluated_selection(sources(
            f.evaluation.snapshot(),
            &c,
            &trainer,
            &evaluator,
        ))
        .await?;
    let (host, selector, selector_thread) =
        selector_peer(original_s, &selected, &c, &trainer, &evaluator, None)?;
    execute(&c, 1).await?;
    let files = SelectorFiles::new()?;
    let mut owner = observer(&files, &f, &selected, OpenReceipt::Fresh)?;
    let before = files.bytes()?;
    let published_before = f.publication_bytes()?;
    match predecessor {
        OriginalPredecessorFault::Trainer => f.host.original.withdraw_original_dataset()?,
        OriginalPredecessorFault::Evaluator => f.host.retention_b.withdraw_target()?,
        OriginalPredecessorFault::Selector => {
            OpenOptions::new()
                .write(true)
                .open(selection_files.0.path().join("journal"))?
                .set_len(0)?;
        }
    }
    let result = owner
        .attest_original_evaluated_completion(next_sources(
            selected.snapshot(),
            &c,
            &trainer,
            &evaluator,
            &selector,
        ))
        .await;
    match predecessor {
        OriginalPredecessorFault::Trainer => assert!(matches!(
            result,
            Err(NextUseError::Evaluated(PublicationError::Training(
                crate::OriginalCellQ24TrainingCommandErrorV1::CommitUncertain
            )))
        )),
        OriginalPredecessorFault::Evaluator => assert!(matches!(
            result,
            Err(NextUseError::Evaluated(PublicationError::Evaluation(
                crate::OriginalCellEvaluationCommandErrorV1::PredecessorUnavailable
            )))
        )),
        OriginalPredecessorFault::Selector => assert!(matches!(
            result,
            Err(NextUseError::Connection(
                crate::LearningIterationRuntimeErrorV1::OwnerUnavailable(_)
            ))
        )),
    }
    assert_eq!(files.bytes()?, before);
    assert_eq!(f.publication_bytes()?, published_before);
    drop(owner);
    drop(selector);
    let served = selector_thread
        .join()
        .expect("same original S evidence service");
    if predecessor == OriginalPredecessorFault::Selector {
        assert!(matches!(
            served,
            Err(OriginalCircuitEvaluatedSelectionReadbackErrorV1::Transport(
                codex_hepta_contracts::HostIssuerTransportError::InvalidRequest
            ))
        ));
    } else {
        assert_eq!(served?, 0);
    }
    drop(host);
    drop(trainer);
    drop(evaluator);
    assert_eq!(
        peers.finish()?,
        match predecessor {
            OriginalPredecessorFault::Trainer => [7, 6],
            OriginalPredecessorFault::Evaluator => [7, 7],
            OriginalPredecessorFault::Selector => [8, 8],
        }
    );
    c.stop().await?;
    drop(c);
    f.finish().await?;
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn evaluated_c_rereads_actual_source_after_the_final_s_response() -> anyhow::Result<()> {
    let mut f = Box::pin(PublicationFixture::ready()).await?;
    let (mut c, trainer, evaluator, peers) = Box::pin(published(&mut f)).await?;
    let trainer = Arc::new(trainer);
    let evaluator = Arc::new(evaluator);
    let selection_files = SelectorFiles::new()?;
    let mut original_s = selection_files.owner(&f, OpenReceipt::Fresh)?;
    let selected = original_s
        .attest_original_evaluated_selection(sources(
            f.evaluation.snapshot(),
            &c,
            &trainer,
            &evaluator,
        ))
        .await?;
    let original_s_bytes = selection_files.bytes()?;
    let source_path = c.runtime.identity.home_root.join("q24-source.journal");
    let original_source = OpenOptions::new().write(true).open(&source_path)?;
    let (host, selector, selector_thread) = selector_peer(
        original_s,
        &selected,
        &c,
        &trainer,
        &evaluator,
        Some((2, original_source)),
    )?;
    execute(&c, 1).await?;
    let files = SelectorFiles::new()?;
    let mut owner = observer(&files, &f, &selected, OpenReceipt::Fresh)?;
    let before = files.bytes()?;
    let result = owner
        .attest_original_evaluated_completion(next_sources(
            selected.snapshot(),
            &c,
            &trainer,
            &evaluator,
            &selector,
        ))
        .await;
    assert!(
        matches!(&result, Err(NextUseError::Observation(_))),
        "after the final actual S response: {:?}",
        result.as_ref().err()
    );
    // The actual C claim/signature exists, but no successful response may use
    // the pre-await source observation after the original source changed.
    assert_ne!(files.bytes()?, before);
    assert_eq!(std::fs::metadata(&source_path)?.len(), 0);
    assert_eq!(selection_files.bytes()?, original_s_bytes);
    assert!(matches!(
        owner
            .readback_evaluated_completion(next_sources(
                selected.snapshot(),
                &c,
                &trainer,
                &evaluator,
                &selector,
            ))
            .await,
        Err(NextUseError::Owner(OwnerError::CommitUncertain))
    ));
    drop(owner);
    drop(selector);
    assert_eq!(selector_thread.join().expect("two actual S readbacks")?, 2);
    drop(host);
    drop(trainer);
    drop(evaluator);
    assert_eq!(peers.finish()?, [12, 12]);
    c.stop().await?;
    drop(c);
    f.finish().await
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn evaluated_c_recovery_of_missing_receipt_never_claims_or_signs() -> anyhow::Result<()> {
    let mut f = Box::pin(PublicationFixture::ready()).await?;
    let (mut c, trainer, evaluator, peers) = Box::pin(published(&mut f)).await?;
    let trainer = Arc::new(trainer);
    let evaluator = Arc::new(evaluator);
    let selection_files = SelectorFiles::new()?;
    let mut original_selector = selection_files.owner(&f, OpenReceipt::Fresh)?;
    let selected = original_selector
        .attest_original_evaluated_selection(sources(
            f.evaluation.snapshot(),
            &c,
            &trainer,
            &evaluator,
        ))
        .await?;
    let original_s_bytes = selection_files.bytes()?;
    let (host, selector, selector_thread) =
        selector_peer(original_selector, &selected, &c, &trainer, &evaluator, None)?;
    let publication = execute(&c, 1).await?;
    assert_eq!(
        read_receipt(&c, &f.definition, &publication)?.bundle_digest,
        f.bundle.digest()?
    );

    // The original C and its current T/B/S predecessors are all present, but
    // this independently witnessed Observer journal has no C claim/receipt.
    let files = SelectorFiles::new()?;
    drop(observer(&files, &f, &selected, OpenReceipt::Fresh)?);
    let untouched = files.bytes()?;
    // Deliberately supply Fresh S pins: recover must attenuate them and must
    // not reinterpret Missing as permission to make a new Observer claim.
    let mut recovered = observer(&files, &f, &selected, OpenReceipt::Readback)?;
    let result = recovered
        .attest_original_evaluated_completion(next_sources(
            selected.snapshot(),
            &c,
            &trainer,
            &evaluator,
            &selector,
        ))
        .await;
    assert!(
        matches!(
            &result,
            Err(NextUseError::Owner(OwnerError::Store(
                ProductEvaluationExecutionStoreErrorV1::Missing
            )))
        ),
        "original recovered missing C: {:?}",
        result.as_ref().err()
    );
    assert_eq!(files.bytes()?, untouched);
    assert!(matches!(
        recovered
            .readback_evaluated_completion(next_sources(
                selected.snapshot(),
                &c,
                &trainer,
                &evaluator,
                &selector,
            ))
            .await,
        Err(NextUseError::Owner(OwnerError::Store(
            ProductEvaluationExecutionStoreErrorV1::Missing
        )))
    ));
    assert_eq!(files.bytes()?, untouched);
    assert_eq!(selection_files.bytes()?, original_s_bytes);
    drop(recovered);
    drop(selector);
    assert_eq!(selector_thread.join().expect("two actual S readbacks")?, 2);
    drop(host);
    drop(trainer);
    drop(evaluator);
    assert_eq!(peers.finish()?, [12, 12]);
    c.stop().await?;
    drop(c);
    f.finish().await
}
