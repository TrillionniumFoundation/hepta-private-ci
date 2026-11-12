//! Actual original Version cold reads over complete NoUpdate evidence.
//! These mechanisms do not install startup owners or authorize real C work.

use super::*;
use crate::OriginalCircuitRetainedVersionErrorV1 as VersionError;
use pretty_assertions::assert_eq;

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn evaluated_version_cold_reads_exact_four_cut_without_publication_or_retry() -> anyhow::Result<()> {
    let mut f = Box::pin(PublicationFixture::ready()).await?;
    let (held, peers) = Box::pin(held_predecessors(&f)).await?;
    let (mut c, recovery) = Box::pin(publish_for_recovery(&mut f, &held.dataset_receipt)).await?;
    let intent = recovery.intent_digest;
    let before = f.publication_bytes()?;
    let upstream = (f.host.original.predecessor_bytes()?, f.host.upstream_files()?, f.host.original_files()?);
    let host = cold_version(&f, held, recovery)?;
    let read = Version::read_original_version_fixture(Arc::clone(&host)).await?;
    let published = read.publication().expect("actual original published retained C");
    assert_eq!(published.intent_digest(), intent);
    assert_eq!(published.bundle_digest(), f.bundle.digest()?);
    assert_eq!(published.run_id(), &f.source_c.scope.run_id);
    assert_eq!(published.authority(), codex_hepta_types::AuthorityPosture::DENY_ALL);
    assert!(matches!(Version::prepare_original_version_fixture(Arc::clone(&host)).await, Err(VersionError::ReadbackRequired)));
    assert!(matches!(Version::run_original_issuer_fixture(Arc::clone(&host)).await, Err(VersionError::ReadbackRequired)));
    assert_eq!(f.publication_bytes()?, before);
    assert_eq!((f.host.original.predecessor_bytes()?, f.host.upstream_files()?, f.host.original_files()?), upstream);
    assert_eq!(c.cell.snapshot(&f.source_c.scope)?.revision, 0);
    drop(host);
    let reads = peers.finish()?;
    assert!(reads.iter().all(|count| *count > 0));
    c.stop().await?;
    drop(c);
    f.finish().await
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn evaluated_version_cold_requires_current_original_evaluation() -> anyhow::Result<()> {
    let mut f = Box::pin(PublicationFixture::ready()).await?;
    let (held, peers) = Box::pin(held_predecessors(&f)).await?;
    let (mut c, recovery) = Box::pin(publish_for_recovery(&mut f, &held.dataset_receipt)).await?;
    let before = f.publication_bytes()?;
    let host = cold_version(&f, held, recovery)?;
    f.host.retention_b.withdraw_target()?;
    assert!(matches!(Version::read_original_version_fixture(Arc::clone(&host)).await,
        Err(VersionError::Evaluation(crate::OriginalCellEvaluationCommandErrorV1::CommitUncertain))));
    assert!(!host.fixture_original_selection_reader_installed()?);
    assert!(Version::prepare_original_version_fixture(Arc::clone(&host)).await.is_err());
    assert_eq!(f.publication_bytes()?, before);
    assert_eq!(c.cell.snapshot(&f.source_c.scope)?.revision, 0);
    drop(host);
    let reads = peers.finish()?;
    assert!(reads.iter().all(|count| *count > 0));
    c.stop().await?;
    drop(c);
    f.finish().await
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn evaluated_version_cold_later_b_withdrawal_removes_reader_for_new_connections() -> anyhow::Result<()> {
    let mut f = Box::pin(PublicationFixture::ready()).await?;
    let (held, peers) = Box::pin(held_predecessors(&f)).await?;
    let (mut c, recovery) = Box::pin(publish_for_recovery(&mut f, &held.dataset_receipt)).await?;
    let before = f.publication_bytes()?;
    let host = cold_version(&f, held, recovery)?;
    let read = Version::read_original_version_fixture(Arc::clone(&host)).await?;
    assert!(read.publication().is_some());
    assert!(host.fixture_original_selection_reader_installed()?);
    f.host.retention_b.withdraw_target()?;
    // This helper constructs the next actual request from the already bound
    // cut. The production command, not a fixture pre-read, observes B's loss.
    assert!(matches!(Version::fixture_read_bound_original_version(Arc::clone(&host)).await,
        Err(VersionError::CommitUncertain)));
    assert!(!host.fixture_original_selection_reader_installed()?);
    let context = crate::OriginalCircuitEvaluatedLearningReadContextV1::for_original_selection(f.readback_context()?)?;
    let (reader, channel) = crate::circuit_feature_current::original_learning_read_fixture::evaluated_client(context)?;
    let server = tokio::spawn(Version::fixture_serve_original_selection_channel(Arc::clone(&host), channel));
    assert!(reader.read_current().await.is_err());
    server.abort();
    assert!(server.await.expect_err("unready serving lane cancelled").is_cancelled());
    drop(reader);
    assert_eq!(f.publication_bytes()?, before);
    assert_eq!(c.cell.snapshot(&f.source_c.scope)?.revision, 0);
    drop(host);
    let reads = peers.finish()?;
    assert!(reads.iter().all(|count| *count > 0));
    c.stop().await?;
    drop(c);
    f.finish().await
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn evaluated_version_cold_artifact_failure_never_admits_selection_reader() -> anyhow::Result<()> {
    let mut f = Box::pin(PublicationFixture::ready()).await?;
    let (held, peers) = Box::pin(held_predecessors(&f)).await?;
    let (mut c, recovery) = Box::pin(publish_for_recovery(&mut f, &held.dataset_receipt)).await?;
    let before = f.publication_bytes()?;
    let host = cold_version(&f, held, recovery)?;
    assert!(!host.fixture_original_selection_reader_installed()?);
    // Original D/T/B remain valid; the actual Artifact owner changes after
    // recovery construction, before its first complete publication read.
    f.host.original.version.advance_artifact_current()?;
    assert!(matches!(Version::read_original_version_fixture(Arc::clone(&host)).await,
        Err(VersionError::CommitUncertain)));
    assert!(!host.fixture_original_selection_reader_installed()?);
    let context = crate::OriginalCircuitEvaluatedLearningReadContextV1::for_original_selection(f.readback_context()?)?;
    let (reader, channel) = crate::circuit_feature_current::original_learning_read_fixture::evaluated_client(context)?;
    let server = tokio::spawn(Version::fixture_serve_original_selection_channel(Arc::clone(&host), channel));
    // The real serving loop has no admitted reader. Its original client
    // timeout consumes the connection; the test then cancels the waiting lane.
    assert!(reader.read_current().await.is_err());
    server.abort();
    assert!(server.await.expect_err("unready serving lane cancelled").is_cancelled());
    drop(reader);
    assert_eq!(f.publication_bytes()?, before);
    assert_eq!(c.cell.snapshot(&f.source_c.scope)?.revision, 0);
    drop(host);
    let reads = peers.finish()?;
    assert!(reads.iter().all(|count| *count > 0));
    c.stop().await?;
    drop(c);
    f.finish().await
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn evaluated_version_cold_rejects_original_training_prefix_without_b() -> anyhow::Result<()> {
    let mut f = Box::pin(PublicationFixture::ready()).await?;
    let (held, peers) = Box::pin(held_predecessors(&f)).await?;
    let (mut c, mut recovery) = Box::pin(publish_for_recovery(&mut f, &held.dataset_receipt)).await?;
    let before = f.publication_bytes()?;
    // The actual signed three-cut T is intact, but does not contain original B.
    // This edits untrusted recovery metadata, never an opaque receipt or key.
    recovery.training = f.host.config.training.clone();
    recovery.attestations.pop();
    assert!(matches!(cold_version(&f, held, recovery), Err(VersionError::Binding("original retained recovery cut"))));
    assert_eq!(f.publication_bytes()?, before);
    assert_eq!(c.cell.snapshot(&f.source_c.scope)?.revision, 0);
    assert_eq!(peers.finish()?, [1, 0, 0]);
    c.stop().await?;
    drop(c);
    f.finish().await
}
