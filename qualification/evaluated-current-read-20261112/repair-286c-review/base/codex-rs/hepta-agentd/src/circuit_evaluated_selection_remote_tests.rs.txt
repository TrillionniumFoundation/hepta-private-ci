//! Same original A, actual Candidate/B, baseline publication and live T/B
//! command peers. Only same-process transport/enrollment are fixtures. These
//! tests prove receipt/read mechanisms, not ordinary Candidate dispatch.

use super::*;
use crate::OriginalCircuitEvaluatedLearningReadContextV1 as ReadContext;
use crate::OriginalCircuitEvaluatedSelectionRemoteSourcesV1;
use crate::OriginalCircuitLearningReadClientV1;
use crate::OriginalCircuitLearningReadContextV1 as LegacyReadContext;
use crate::OriginalCircuitLearningReadErrorV1 as ReadError;
use crate::OriginalCircuitLearningReadOwnerV1;
use crate::circuit_feature_current::original_learning_read_fixture as reads;
use pretty_assertions::assert_eq;
use pretty_assertions::assert_ne;
use std::sync::Arc;

type ReadOwner = OriginalCircuitLearningReadOwnerV1<FileAnchorWitnessStore, FileAnchorWitnessStore>;

fn task_reader(c: &support::Session, context: ReadContext) -> anyhow::Result<Arc<ReadOwner>> {
    // Existing Clone implementations share the actual sealed Cell and Source
    // journals. These are read-only views, never reopened writers or DTO tasks.
    Ok(Arc::new(ReadOwner::from_original_evaluated_owners(
        c.cell.clone(),
        c.source.as_ref().clone(),
        c.runtime.identity.clone(),
        context,
    )?))
}

fn remote<'a>(
    snapshot: &'a LearningIterationSnapshotV1,
    live: &'a OriginalCircuitLearningReadClientV1,
    trainer: &'a OriginalCellQ24TrainingCommandClientV1,
    evaluator: &'a OriginalCellEvaluationCommandClientV1,
) -> OriginalCircuitEvaluatedSelectionRemoteSourcesV1<'a> {
    OriginalCircuitEvaluatedSelectionRemoteSourcesV1 {
        snapshot,
        live,
        trainer,
        evaluator,
    }
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn evaluated_remote_s_reads_original_task_and_recovers_exact_five_cut() -> anyhow::Result<()>
{
    let mut f = Box::pin(PublicationFixture::ready()).await?;
    let (mut c, trainer, evaluator, peers) = Box::pin(published(&mut f)).await?;
    let context = ReadContext::for_original_selection(f.context()?)?;
    let host = task_reader(&c, context.clone())?;
    reads::reject_evaluated_request_substitutions(&host, &context)?;
    let (live, channel) = reads::evaluated_client(context)?;
    let peer = reads::serve(Arc::clone(&host), channel);
    let files = SelectorFiles::new()?;
    let mut owner = files.owner(&f, OpenReceipt::Fresh)?;
    let empty = files.bytes()?;
    let publication = f.publication_bytes()?;
    let upstream = (
        f.host.original.predecessor_bytes()?,
        f.host.upstream_files()?,
        f.host.original_files()?,
    );
    let selected = owner
        .attest_original_evaluated_remote_selection(remote(
            f.evaluation.snapshot(),
            &live,
            &trainer,
            &evaluator,
        ))
        .await?;
    assert_ne!(files.bytes()?, empty);
    assert_eq!(
        &selected.snapshot().receipts[..4],
        &f.evaluation.snapshot().receipts
    );
    assert!(selected.snapshot().training_no_update_v2().is_none());
    assert_eq!(selected.snapshot().receipts.len(), 5);
    assert_eq!(
        LearningIterationCoordinatorV1::from_snapshot(selected.snapshot().clone())?
            .next_task_bundle(),
        Some(&f.bundle)
    );
    assert_eq!(c.cell.snapshot(&f.source_c.scope)?.revision, 0);
    let completed = files.bytes()?;
    let read = owner
        .readback_evaluated_remote_selection(remote(
            selected.snapshot(),
            &live,
            &trainer,
            &evaluator,
        ))
        .await?;
    assert_eq!(
        (read.snapshot(), read.receipt(), read.attestation()),
        (
            selected.snapshot(),
            selected.receipt(),
            selected.attestation()
        )
    );
    drop(owner);
    let mut recovered = files.owner(&f, OpenReceipt::Readback)?;
    let read = recovered
        .attest_original_evaluated_remote_selection(remote(
            selected.snapshot(),
            &live,
            &trainer,
            &evaluator,
        ))
        .await?;
    assert_eq!(
        (read.snapshot(), read.receipt(), read.attestation()),
        (
            selected.snapshot(),
            selected.receipt(),
            selected.attestation()
        )
    );
    assert!(matches!(
        read.original_context().require_new_original_receipt(now()?),
        Err(crate::OriginalCircuitRetainedPublicationErrorV1::Binding(
            "recovered evaluated retention is read-only"
        ))
    ));
    assert_eq!(files.bytes()?, completed);
    assert_eq!(f.publication_bytes()?, publication);
    assert_eq!(
        (
            f.host.original.predecessor_bytes()?,
            f.host.upstream_files()?,
            f.host.original_files()?,
        ),
        upstream
    );
    drop(recovered);
    drop(live);
    assert_eq!(peer.join().expect("same original task reader")?, 7);
    drop(host);

    // The five-cut capability is a distinct actual C read purpose. It cannot
    // feed S, and it does not confer a remote C receipt/command capability.
    let context = ReadContext::for_original_next_use(selected.clone())?;
    let host = task_reader(&c, context.clone())?;
    reads::reject_evaluated_request_substitutions(&host, &context)?;
    let (next, channel) = reads::evaluated_client(context)?;
    let mut recovered = files.owner(&f, OpenReceipt::Readback)?;
    assert!(matches!(
        recovered
            .readback_evaluated_remote_selection(remote(
                selected.snapshot(),
                &next,
                &trainer,
                &evaluator,
            ))
            .await,
        Err(SelectionError::PublishedRead(ReadError::Binding(
            "evaluated Selection-only read purpose"
        )))
    ));
    assert_eq!(files.bytes()?, completed);
    drop(recovered);
    drop(trainer);
    drop(evaluator);
    assert_eq!(peers.finish()?, [10, 10]);
    let actual_publication = execute(&c, 1).await?;
    let actual = read_receipt(&c, &f.definition, &actual_publication)?;
    assert_eq!(actual.bundle_digest, f.bundle.digest()?);
    assert_ne!(actual.bundle_digest, f.host.original.candidate.digest()?);
    let peer = reads::serve(Arc::clone(&host), channel);
    let read = next.read_current().await?;
    let coordinator = LearningIterationCoordinatorV1::from_snapshot(selected.snapshot().clone())?;
    assert_eq!(
        read.observation(),
        &c.cell
            .read_learning_next_use(&coordinator, c.source.as_ref(), &c.runtime.identity,)?
    );
    assert!(matches!(read.observation(),
        LearningIterationObservationV1::RetainedModelNextUse { retained_bundle, .. }
        if *retained_bundle == f.bundle.digest()?));
    assert_eq!(files.bytes()?, completed);
    drop(next);
    assert_eq!(
        peer.join().expect("same original completed task reader")?,
        1
    );
    drop(host);
    c.stop().await?;
    drop(c);
    f.finish().await
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn evaluated_remote_s_cold_missing_cannot_claim_or_reinterpret_legacy() -> anyhow::Result<()>
{
    let mut f = Box::pin(PublicationFixture::ready()).await?;
    let (mut c, trainer, evaluator, peers) = Box::pin(published(&mut f)).await?;
    assert!(matches!(
        ReadOwner::from_original_owners(
            c.cell.clone(),
            c.source.as_ref().clone(),
            c.runtime.identity.clone(),
            LegacyReadContext {
                prefix: f.evaluation.snapshot().clone(),
                scope: f.host.config.scope.clone(),
                verifier: f.host.config.signing.verifier.clone(),
                training_evidence: f.training.attestation().clone(),
                selection_evidence: None,
            },
        ),
        Err(ReadError::Binding(
            "only original TrainingNoUpdate read profile"
        ))
    ));
    let context = ReadContext::for_original_selection(f.readback_context()?)?;
    let host = task_reader(&c, context.clone())?;
    let (live, channel) = reads::evaluated_client(context)?;
    let peer = reads::serve(Arc::clone(&host), channel);
    let files = SelectorFiles::new()?;
    drop(files.owner(&f, OpenReceipt::Fresh)?);
    let empty = files.bytes()?;
    let mut recovered = files.owner(&f, OpenReceipt::Readback)?;
    // This is the actual same-A three-cut Training result, not an invented
    // malformed receipt. It cannot omit original B at the S boundary.
    assert_eq!(
        f.host.config.training.receipts.last(),
        Some(f.training.receipt())
    );
    assert!(matches!(
        recovered
            .attest_original_evaluated_remote_selection(remote(
                &f.host.config.training,
                &live,
                &trainer,
                &evaluator,
            ))
            .await,
        Err(SelectionError::Owner(OwnerError::Binding(
            "original TrainingNoUpdate prefix"
        )))
    ));
    assert_eq!(files.bytes()?, empty);
    assert!(matches!(
        recovered
            .attest_original_evaluated_remote_selection(remote(
                f.evaluation.snapshot(),
                &live,
                &trainer,
                &evaluator,
            ))
            .await,
        Err(SelectionError::Owner(OwnerError::Store(
            ProductEvaluationExecutionStoreErrorV1::Missing
        )))
    ));
    assert_eq!(files.bytes()?, empty);
    assert_eq!(c.cell.snapshot(&f.source_c.scope)?.revision, 0);
    drop(recovered);
    drop(live);
    assert_eq!(peer.join().expect("same cold original task reader")?, 1);
    drop(host);
    drop(trainer);
    drop(evaluator);
    assert_eq!(peers.finish()?, [5, 5]);
    c.stop().await?;
    drop(c);
    f.finish().await
}

#[derive(Clone, Copy)]
enum WithdrawOriginal {
    Trainer,
    Evaluator,
}

async fn original_predecessor_withdrawal(which: WithdrawOriginal) -> anyhow::Result<()> {
    let mut f = Box::pin(PublicationFixture::ready()).await?;
    let (mut c, trainer, evaluator, peers) = Box::pin(published(&mut f)).await?;
    let context = ReadContext::for_original_selection(f.context()?)?;
    let host = task_reader(&c, context.clone())?;
    let (live, channel) = reads::evaluated_client(context)?;
    let peer = reads::serve(Arc::clone(&host), channel);
    let files = SelectorFiles::new()?;
    let mut owner = files.owner(&f, OpenReceipt::Fresh)?;
    let selected = owner
        .attest_original_evaluated_remote_selection(remote(
            f.evaluation.snapshot(),
            &live,
            &trainer,
            &evaluator,
        ))
        .await?;
    let completed = files.bytes()?;
    let publication = f.publication_bytes()?;
    match which {
        WithdrawOriginal::Trainer => f.host.original.withdraw_original_dataset()?,
        WithdrawOriginal::Evaluator => f.host.retention_b.withdraw_target()?,
    }
    let result = owner
        .readback_evaluated_remote_selection(remote(
            selected.snapshot(),
            &live,
            &trainer,
            &evaluator,
        ))
        .await;
    let expected = match which {
        WithdrawOriginal::Trainer => {
            assert!(matches!(
                result,
                Err(SelectionError::Evaluated(
                    crate::OriginalCircuitRetainedPublicationErrorV1::Training(
                        crate::OriginalCellQ24TrainingCommandErrorV1::CommitUncertain
                    )
                ))
            ));
            [7, 6]
        }
        WithdrawOriginal::Evaluator => {
            assert!(matches!(
                result,
                Err(SelectionError::Evaluated(
                    crate::OriginalCircuitRetainedPublicationErrorV1::Evaluation(
                        crate::OriginalCellEvaluationCommandErrorV1::CommitUncertain
                    )
                ))
            ));
            [7, 7]
        }
    };
    assert_eq!(files.bytes()?, completed);
    assert_eq!(f.publication_bytes()?, publication);
    drop(owner);
    drop(live);
    assert_eq!(
        peer.join()
            .expect("same original task reader after T/B withdrawal")?,
        4
    );
    drop(host);
    drop(trainer);
    drop(evaluator);
    assert_eq!(peers.finish()?, expected);
    c.stop().await?;
    drop(c);
    f.finish().await
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn evaluated_remote_s_refuses_withdrawn_original_training() -> anyhow::Result<()> {
    Box::pin(original_predecessor_withdrawal(WithdrawOriginal::Trainer)).await
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn evaluated_remote_s_refuses_withdrawn_original_evaluation() -> anyhow::Result<()> {
    Box::pin(original_predecessor_withdrawal(WithdrawOriginal::Evaluator)).await
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn evaluated_remote_s_fences_committed_journal_if_final_source_read_fails()
-> anyhow::Result<()> {
    let mut f = Box::pin(PublicationFixture::ready()).await?;
    let (mut c, trainer, evaluator, peers) = Box::pin(published(&mut f)).await?;
    let context = ReadContext::for_original_selection(f.context()?)?;
    let host = task_reader(&c, context.clone())?;
    let (live, channel) = reads::evaluated_client(context)?;
    let source_file = OpenOptions::new()
        .write(true)
        .open(c.runtime.identity.home_root.join("q24-source.journal"))?;
    let peer =
        reads::withdraw_source_before_final_selection_read(Arc::clone(&host), channel, source_file);
    let files = SelectorFiles::new()?;
    let mut owner = files.owner(&f, OpenReceipt::Fresh)?;
    let empty = files.bytes()?;
    let publication = f.publication_bytes()?;
    assert!(matches!(
        owner
            .attest_original_evaluated_remote_selection(remote(
                f.evaluation.snapshot(),
                &live,
                &trainer,
                &evaluator,
            ))
            .await,
        Err(SelectionError::PublishedRead(ReadError::Transport(_)))
    ));
    let committed = files.bytes()?;
    assert_ne!(committed, empty);
    assert!(matches!(
        owner
            .readback_evaluated_remote_selection(remote(
                f.evaluation.snapshot(),
                &live,
                &trainer,
                &evaluator,
            ))
            .await,
        Err(SelectionError::Owner(OwnerError::CommitUncertain))
    ));
    assert!(matches!(
        live.read_current().await,
        Err(ReadError::Unavailable)
    ));
    assert_eq!(files.bytes()?, committed);
    assert_eq!(f.publication_bytes()?, publication);
    drop(owner);
    drop(live);
    assert_eq!(peer.join().expect("physical source withdrawal")?, 3);
    drop(host);
    drop(trainer);
    drop(evaluator);
    assert_eq!(peers.finish()?, [6, 6]);
    c.stop().await?;
    drop(c);
    f.finish().await
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn evaluated_read_corruption_and_cancellation_consume_original_connections()
-> anyhow::Result<()> {
    let mut f = Box::pin(PublicationFixture::ready()).await?;
    let (mut c, trainer, evaluator, peers) = Box::pin(published(&mut f)).await?;
    let context = ReadContext::for_original_selection(f.context()?)?;
    let host = task_reader(&c, context.clone())?;
    // These are two already-held fixture channels, not reconnects after failure.
    let (corrupt, corrupt_channel) = reads::evaluated_client(context.clone())?;
    let (live, channel) = reads::evaluated_client(context)?;
    drop(trainer);
    drop(evaluator);
    assert_eq!(peers.finish()?, [4, 4]);
    let peer = reads::changed_nonce(Arc::clone(&host), corrupt_channel);
    assert!(matches!(
        corrupt.read_current().await,
        Err(ReadError::Binding("original fixed read response"))
    ));
    assert!(matches!(
        corrupt.read_current().await,
        Err(ReadError::Unavailable)
    ));
    peer.join()
        .expect("actual original read before changed nonce")?;
    drop(corrupt);
    let peer = reads::delayed_response(Arc::clone(&host), channel);
    let publication = f.publication_bytes()?;
    assert!(
        tokio::time::timeout(std::time::Duration::from_millis(50), live.read_current(),)
            .await
            .is_err()
    );
    assert!(matches!(
        live.read_current().await,
        Err(ReadError::Unavailable)
    ));
    peer.join()
        .expect("actual original read before delayed reply")?;
    assert!(matches!(
        live.read_current().await,
        Err(ReadError::Unavailable)
    ));
    assert_eq!(f.publication_bytes()?, publication);
    drop(live);
    drop(host);
    c.stop().await?;
    drop(c);
    f.finish().await
}
