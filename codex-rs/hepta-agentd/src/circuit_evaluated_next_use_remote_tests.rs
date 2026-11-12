//! Actual remote S evidence and C receipt effects over the same original
//! A/T/B/publication/task owners. Process/role enrollment remains a fixture;
//! these six-cut mechanisms confer no ordinary Candidate/daemon qualification.

use super::*;
use crate::OriginalCircuitEvaluatedLearningReadContextV1 as ReadContext;
use crate::OriginalCircuitEvaluatedSelectionRemoteSourcesV1;
use crate::OriginalCircuitLearningReadErrorV1 as ReadError;
use pretty_assertions::assert_eq;
use pretty_assertions::assert_ne;
use std::sync::Arc;

#[path = "circuit_evaluated_next_use_remote_support_tests.rs"]
mod fixture;
use fixture::RemoteSelector;
use fixture::remote_sources;
use fixture::task_peer;

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn evaluated_remote_c_reads_original_s_and_recovers_exact_six_cut() -> anyhow::Result<()> {
    let mut f = Box::pin(PublicationFixture::ready()).await?;
    let (mut c, trainer, evaluator, peers) = Box::pin(published(&mut f)).await?;
    let trainer = Arc::new(trainer);
    let evaluator = Arc::new(evaluator);
    let original = Box::pin(RemoteSelector::from_original(
        &f, &c, &trainer, &evaluator, None,
    ))
    .await?;
    let original_s = original.files.bytes()?;
    let actual_publication = execute(&c, 1).await?;
    let actual = read_receipt(&c, &f.definition, &actual_publication)?;
    assert_eq!(actual.bundle_digest, f.bundle.digest()?);
    assert_ne!(actual.bundle_digest, f.host.original.candidate.digest()?);
    assert_eq!(
        actual.representation.prediction_q24,
        vec![Q / 4, Q, 0, 0, 0]
    );
    let publication = f.publication_bytes()?;
    let upstream = (
        f.host.original.predecessor_bytes()?,
        f.host.upstream_files()?,
        f.host.original_files()?,
    );
    let (task_host, live, task_thread) = task_peer(
        &c,
        ReadContext::for_original_next_use(original.selected.clone())?,
    )?;
    let files = SelectorFiles::new()?;
    let mut owner = observer(&files, &f, &original.selected, OpenReceipt::Fresh)?;
    let empty = files.bytes()?;
    // The original four-cut S reader cannot become a five-cut C reader.
    assert!(matches!(
        owner
            .attest_original_evaluated_remote_completion(remote_sources(
                original.selected.snapshot(),
                &original.live,
                &trainer,
                &evaluator,
                &original.client,
            ))
            .await,
        Err(NextUseError::PublishedRead(ReadError::Binding(
            "evaluated NextUse-only read purpose"
        )))
    ));
    assert_eq!(files.bytes()?, empty);
    let completed = owner
        .attest_original_evaluated_remote_completion(remote_sources(
            original.selected.snapshot(),
            &live,
            &trainer,
            &evaluator,
            &original.client,
        ))
        .await?;
    assert_eq!(completed.snapshot().receipts.len(), 6);
    assert_eq!(
        &completed.snapshot().receipts[..5],
        &original.selected.snapshot().receipts
    );
    assert!(completed.snapshot().training_no_update_v2().is_none());
    assert_eq!(
        LearningIterationCoordinatorV1::from_snapshot(completed.snapshot().clone())?.next_stage(),
        None
    );
    assert!(matches!(completed.receipt().observation,
        LearningIterationObservationV1::RetainedModelNextUse { retained_bundle, .. }
        if retained_bundle == f.bundle.digest()?));
    let committed = files.bytes()?;
    assert_ne!(committed, empty);
    let read = owner
        .readback_evaluated_remote_completion(remote_sources(
            completed.snapshot(),
            &live,
            &trainer,
            &evaluator,
            &original.client,
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

    // Valid coordinator metadata extending a different S is adversarial input,
    // never another original signed receipt or a second qualified generation.
    let mut other = LearningIterationCoordinatorV1::from_snapshot(f.evaluation.snapshot().clone())?;
    let mut changed_s = original.selected.receipt().clone();
    changed_s.evidence_digest = Digest32::of_bytes(b"different original S prefix");
    other.record(changed_s.clone(), changed_s.observed_unix_seconds)?;
    let mut changed_c = completed.receipt().clone();
    changed_c.predecessor = other.snapshot().head_digest;
    other.record(changed_c.clone(), changed_c.observed_unix_seconds)?;
    assert!(matches!(
        owner
            .readback_evaluated_remote_completion(remote_sources(
                other.snapshot(),
                &live,
                &trainer,
                &evaluator,
                &original.client,
            ))
            .await,
        Err(NextUseError::Owner(OwnerError::Binding(
            "original Selection prefix"
        )))
    ));
    assert_eq!(files.bytes()?, committed);
    drop(owner);
    let mut recovered = observer(&files, &f, &original.selected, OpenReceipt::Readback)?;
    let read = recovered
        .attest_original_evaluated_remote_completion(remote_sources(
            completed.snapshot(),
            &live,
            &trainer,
            &evaluator,
            &original.client,
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
    assert_eq!(original.files.bytes()?, original_s);
    assert_eq!(f.publication_bytes()?, publication);
    assert_eq!(
        (
            f.host.original.predecessor_bytes()?,
            f.host.upstream_files()?,
            f.host.original_files()?
        ),
        upstream
    );
    assert_eq!(c.cell.snapshot(&f.source_c.scope)?.revision, 1);
    drop(recovered);
    drop(live);
    assert_eq!(task_thread.join().expect("actual five-cut task reads")?, 7);
    drop(task_host);
    drop(original.client);
    assert_eq!(
        original
            .thread
            .join()
            .expect("six actual original remote S reads")?,
        6
    );
    drop(original.host);

    // Only after releasing the old S custody, recover the same files. The
    // still-held original 4cut channel is reused; no owner or clock is renewed.
    let mut recovered_s = original.files.owner(&f, OpenReceipt::Readback)?;
    let cold_s = recovered_s
        .readback_evaluated_remote_selection(OriginalCircuitEvaluatedSelectionRemoteSourcesV1 {
            snapshot: original.selected.snapshot(),
            live: &original.live,
            trainer: &trainer,
            evaluator: &evaluator,
        })
        .await?;
    let cold_files = SelectorFiles::new()?;
    let (journal, witness) = cold_files.files(&f, &OpenReceipt::Fresh)?;
    let untouched = cold_files.bytes()?;
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
    assert_eq!(cold_files.bytes()?, untouched);
    assert_eq!(original.files.bytes()?, original_s);
    drop(recovered_s);
    drop(original.live);
    assert_eq!(
        original
            .task_thread
            .join()
            .expect("original four-cut task reads")?,
        17
    );
    drop(original.task_host);
    drop(trainer);
    drop(evaluator);
    assert_eq!(peers.finish()?, [26, 26]);
    c.stop().await?;
    drop(c);
    f.finish().await
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn evaluated_remote_c_cold_missing_reads_originals_without_claiming() -> anyhow::Result<()> {
    let mut f = Box::pin(PublicationFixture::ready()).await?;
    let (mut c, trainer, evaluator, peers) = Box::pin(published(&mut f)).await?;
    let trainer = Arc::new(trainer);
    let evaluator = Arc::new(evaluator);
    let original = Box::pin(RemoteSelector::from_original(
        &f, &c, &trainer, &evaluator, None,
    ))
    .await?;
    execute(&c, 1).await?;
    let publication = f.publication_bytes()?;
    let original_s = original.files.bytes()?;
    let (task_host, live, task_thread) = task_peer(
        &c,
        ReadContext::for_original_next_use(original.selected.clone())?,
    )?;
    let files = SelectorFiles::new()?;
    drop(observer(
        &files,
        &f,
        &original.selected,
        OpenReceipt::Fresh,
    )?);
    let empty = files.bytes()?;
    let mut recovered = observer(&files, &f, &original.selected, OpenReceipt::Readback)?;
    assert!(matches!(
        recovered
            .attest_original_evaluated_remote_completion(remote_sources(
                original.selected.snapshot(),
                &live,
                &trainer,
                &evaluator,
                &original.client,
            ))
            .await,
        Err(NextUseError::Owner(OwnerError::Store(
            ProductEvaluationExecutionStoreErrorV1::Missing
        )))
    ));
    assert_eq!(files.bytes()?, empty);
    assert_eq!(original.files.bytes()?, original_s);
    assert_eq!(f.publication_bytes()?, publication);
    assert_eq!(c.cell.snapshot(&f.source_c.scope)?.revision, 1);
    drop(recovered);
    drop(live);
    assert_eq!(task_thread.join().expect("one actual C source read")?, 1);
    drop(task_host);
    drop(original.client);
    assert_eq!(
        original
            .thread
            .join()
            .expect("one actual original S read")?,
        1
    );
    drop(original.host);
    drop(original.live);
    assert_eq!(
        original.task_thread.join().expect("actual S task reads")?,
        5
    );
    drop(original.task_host);
    drop(trainer);
    drop(evaluator);
    assert_eq!(peers.finish()?, [9, 9]);
    c.stop().await?;
    drop(c);
    f.finish().await
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn evaluated_remote_c_fences_after_last_s_reply_withdraws_actual_source() -> anyhow::Result<()>
{
    let mut f = Box::pin(PublicationFixture::ready()).await?;
    let (mut c, trainer, evaluator, peers) = Box::pin(published(&mut f)).await?;
    let trainer = Arc::new(trainer);
    let evaluator = Arc::new(evaluator);
    let source_path = c.runtime.identity.home_root.join("q24-source.journal");
    let source_file = OpenOptions::new().write(true).open(&source_path)?;
    let original = Box::pin(RemoteSelector::from_original(
        &f,
        &c,
        &trainer,
        &evaluator,
        Some((2, source_file)),
    ))
    .await?;
    execute(&c, 1).await?;
    let publication = f.publication_bytes()?;
    let original_s = original.files.bytes()?;
    let (task_host, live, task_thread) = task_peer(
        &c,
        ReadContext::for_original_next_use(original.selected.clone())?,
    )?;
    let files = SelectorFiles::new()?;
    let mut owner = observer(&files, &f, &original.selected, OpenReceipt::Fresh)?;
    let empty = files.bytes()?;
    assert!(matches!(
        owner
            .attest_original_evaluated_remote_completion(remote_sources(
                original.selected.snapshot(),
                &live,
                &trainer,
                &evaluator,
                &original.client,
            ))
            .await,
        Err(NextUseError::PublishedRead(ReadError::Transport(_)))
    ));
    let committed = files.bytes()?;
    assert_ne!(committed, empty);
    assert_eq!(std::fs::metadata(&source_path)?.len(), 0);
    assert_eq!(original.files.bytes()?, original_s);
    assert_eq!(f.publication_bytes()?, publication);
    assert!(matches!(
        owner
            .readback_evaluated_remote_completion(remote_sources(
                original.selected.snapshot(),
                &live,
                &trainer,
                &evaluator,
                &original.client,
            ))
            .await,
        Err(NextUseError::Owner(OwnerError::CommitUncertain))
    ));
    assert!(matches!(
        live.read_current().await,
        Err(ReadError::Unavailable)
    ));
    assert_eq!(files.bytes()?, committed);
    drop(owner);
    drop(live);
    assert!(matches!(
        task_thread.join().expect("actual final Source refusal"),
        Err(ReadError::Source(_))
    ));
    drop(task_host);
    drop(original.client);
    assert_eq!(
        original
            .thread
            .join()
            .expect("both original S readbacks completed")?,
        2
    );
    drop(original.host);
    drop(original.live);
    assert_eq!(
        original
            .task_thread
            .join()
            .expect("actual original S task reads")?,
        7
    );
    drop(original.task_host);
    drop(trainer);
    drop(evaluator);
    assert_eq!(peers.finish()?, [12, 12]);
    c.stop().await?;
    drop(c);
    f.finish().await
}
