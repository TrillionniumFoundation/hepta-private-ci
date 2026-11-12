//! Actual A/T/Ineligible B, published baseline C, original S and remote C.
//! Same-process transports and enrolled test keys are explicit fixtures; these
//! cases do not qualify the ordinary startup or independent real task inputs.

use super::*;
use crate::OriginalCircuitEvaluatedLearningReadContextV1 as ReadContext;
use crate::OriginalCircuitEvaluatedNextUseRemoteSourcesV1;
use crate::OriginalCircuitLearningReadClientV1;
use crate::OriginalCircuitLearningReadOwnerV1;
use crate::circuit_feature_current::original_evaluated_readiness_fixture as evaluated_ready;
use crate::circuit_feature_current::original_learning_read_fixture as reads;
use crate::circuit_feature_current::original_readiness_fixture as readiness;
use pretty_assertions::assert_eq;
use pretty_assertions::assert_ne;

type ReadOwner = OriginalCircuitLearningReadOwnerV1<FileAnchorWitnessStore, FileAnchorWitnessStore>;

fn actual_reader(c: &support::Session, selection: &OriginalCircuitEvaluatedSelectionReceiptV1)
    -> anyhow::Result<(Arc<ReadOwner>, ReadContext)> {
    let context = ReadContext::for_original_next_use(selection.clone())?;
    let owner = ReadOwner::from_original_evaluated_owners(
        c.cell.clone(), c.source.as_ref().clone(), c.runtime.identity.clone(), context.clone(),
    )?;
    Ok((Arc::new(owner), context))
}

fn remote<'a>(
    snapshot: &'a LearningIterationSnapshotV1,
    selection: &'a OriginalCircuitEvaluatedSelectionReceiptV1,
    live: &'a OriginalCircuitLearningReadClientV1,
    trainer: &'a OriginalCellQ24TrainingCommandClientV1,
    evaluator: &'a OriginalCellEvaluationCommandClientV1,
    selector: &'a crate::LearningIterationEvidenceClientV1,
) -> OriginalCircuitEvaluatedNextUseRemoteSourcesV1<'a> {
    OriginalCircuitEvaluatedNextUseRemoteSourcesV1 {
        snapshot, selection, live, trainer, evaluator, selector,
    }
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn evaluated_remote_c_requires_actual_completion_and_recovers_six_cut() -> anyhow::Result<()> {
    let mut f = Box::pin(PublicationFixture::ready()).await?;
    let (mut c, trainer, evaluator, peers) = Box::pin(published(&mut f)).await?;
    let trainer = Arc::new(trainer);
    let evaluator = Arc::new(evaluator);
    let s_files = SelectorFiles::new()?;
    let mut original_s = s_files.owner(&f, OpenReceipt::Fresh)?;
    let selected = original_s.attest_original_evaluated_selection(sources(
        f.evaluation.snapshot(), &c, &trainer, &evaluator,
    )).await?;
    let s_bytes = s_files.bytes()?;
    let (s_host, selector, s_peer) = selector_peer(original_s, &selected, &c, &trainer, &evaluator, None)?;
    let (host, context) = actual_reader(&c, &selected)?;
    evaluated_ready::reject_legacy_purpose(&host, context.clone())?;
    let (ready, ready_channel) = evaluated_ready::client(context.clone())?;
    let ready_peer = readiness::serve(Arc::clone(&host), ready_channel);
    let files = SelectorFiles::new()?;
    let mut owner = observer(&files, &f, &selected, OpenReceipt::Fresh)?;
    let empty = files.bytes()?;
    assert!(ready.read_current().await?.is_none());
    assert_eq!(files.bytes()?, empty);
    assert_eq!(c.cell.snapshot(&f.source_c.scope)?.revision, 0);

    let publication = execute(&c, 1).await?;
    let actual = read_receipt(&c, &f.definition, &publication)?;
    assert_eq!(actual.bundle_digest, f.bundle.digest()?);
    assert_ne!(actual.bundle_digest, f.host.original.candidate.digest()?);
    let observed = ready.read_current().await?.expect("actual original C completed");
    let (live, channel) = reads::evaluated_client(context)?;
    let peer = reads::serve(Arc::clone(&host), channel);
    let completed = owner.attest_original_evaluated_remote_completion(remote(
        selected.snapshot(), &selected, &live, &trainer, &evaluator, &selector,
    )).await?;
    assert_eq!(completed.snapshot().receipts.len(), 6);
    assert_eq!(&completed.snapshot().receipts[..5], &selected.snapshot().receipts);
    assert_eq!(&completed.receipt().observation, observed.observation());
    assert_eq!(LearningIterationCoordinatorV1::from_snapshot(completed.snapshot().clone())?.next_stage(), None);
    assert!(matches!(completed.receipt().observation,
        LearningIterationObservationV1::RetainedModelNextUse { retained_bundle, .. }
        if retained_bundle == f.bundle.digest()?));
    let committed = files.bytes()?;
    assert_ne!(committed, empty);
    drop(owner);
    let mut cold = observer(&files, &f, &selected, OpenReceipt::Readback)?;
    let read = cold.attest_original_evaluated_remote_completion(remote(
        completed.snapshot(), &selected, &live, &trainer, &evaluator, &selector,
    )).await?;
    assert_eq!((read.snapshot(), read.receipt(), read.attestation()),
        (completed.snapshot(), completed.receipt(), completed.attestation()));
    assert!(matches!(read.original_selection().original_context().require_new_original_receipt(now()?),
        Err(PublicationError::Binding("recovered evaluated retention is read-only"))));
    assert_eq!(files.bytes()?, committed);
    assert_eq!(s_files.bytes()?, s_bytes);
    drop(cold);
    drop(live);
    assert!(peer.join().expect("original remote C source")? > 0);
    drop(ready);
    assert_eq!(ready_peer.join().expect("original C readiness")?, 2);
    drop(host);
    drop(selector);
    assert!(s_peer.join().expect("same original S")? > 0);
    drop(s_host);
    drop(trainer);
    drop(evaluator);
    let counts = peers.finish()?;
    assert!(counts[0] > 0 && counts[1] > 0);
    c.stop().await?;
    drop(c);
    f.finish().await
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn evaluated_remote_c_refuses_actual_evaluator_withdrawal_without_claim() -> anyhow::Result<()> {
    let mut f = Box::pin(PublicationFixture::ready()).await?;
    let (mut c, trainer, evaluator, peers) = Box::pin(published(&mut f)).await?;
    let trainer = Arc::new(trainer);
    let evaluator = Arc::new(evaluator);
    let s_files = SelectorFiles::new()?;
    let mut original_s = s_files.owner(&f, OpenReceipt::Fresh)?;
    let selected = original_s.attest_original_evaluated_selection(sources(
        f.evaluation.snapshot(), &c, &trainer, &evaluator,
    )).await?;
    let (s_host, selector, s_peer) = selector_peer(original_s, &selected, &c, &trainer, &evaluator, None)?;
    execute(&c, 1).await?;
    let (host, context) = actual_reader(&c, &selected)?;
    let (live, channel) = reads::evaluated_client(context)?;
    let peer = reads::serve(Arc::clone(&host), channel);
    let files = SelectorFiles::new()?;
    let mut owner = observer(&files, &f, &selected, OpenReceipt::Fresh)?;
    let before = files.bytes()?;
    let publication = f.publication_bytes()?;
    f.host.retention_b.withdraw_target()?;
    assert!(matches!(owner.attest_original_evaluated_remote_completion(remote(
        selected.snapshot(), &selected, &live, &trainer, &evaluator, &selector,
    )).await, Err(NextUseError::Evaluated(PublicationError::Evaluation(
        crate::OriginalCellEvaluationCommandErrorV1::CommitUncertain)))));
    assert_eq!(files.bytes()?, before);
    assert_eq!(f.publication_bytes()?, publication);
    drop(owner);
    drop(live);
    let _ = peer.join().expect("original C source")?;
    drop(host);
    drop(selector);
    assert_eq!(s_peer.join().expect("S not used after original B refusal")?, 0);
    drop(s_host);
    drop(trainer);
    drop(evaluator);
    peers.finish()?;
    c.stop().await?;
    drop(c);
    f.finish().await
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn evaluated_readiness_consumes_channel_if_original_completed_becomes_pending() -> anyhow::Result<()> {
    let mut f = Box::pin(PublicationFixture::ready()).await?;
    let (mut c, trainer, evaluator, peers) = Box::pin(published(&mut f)).await?;
    let files = SelectorFiles::new()?;
    let mut selector = files.owner(&f, OpenReceipt::Fresh)?;
    let selected = selector.attest_original_evaluated_selection(sources(
        f.evaluation.snapshot(), &c, &trainer, &evaluator,
    )).await?;
    execute(&c, 1).await?;
    let (host, context) = actual_reader(&c, &selected)?;
    let (ready, channel) = evaluated_ready::client(context)?;
    let peer = readiness::changed_reply(Arc::clone(&host), channel, readiness::Change::PendingAfterReady);
    assert!(ready.read_current().await?.is_some());
    assert!(matches!(ready.read_current().await,
        Err(crate::OriginalCircuitLearningReadErrorV1::Binding("completed original C cannot change or become pending"))));
    assert!(matches!(ready.read_current().await, Err(crate::OriginalCircuitLearningReadErrorV1::Unavailable)));
    drop(ready);
    assert_eq!(peer.join().expect("actual C response before named mutation")?, 2);
    drop(host);
    drop(selector);
    drop(trainer);
    drop(evaluator);
    peers.finish()?;
    c.stop().await?;
    drop(c);
    f.finish().await
}
