//! Real Fresh A/Material/T/B/Version/S, with explicit fixture credentials and a
//! genuine UID-0 issuer socket. This case deliberately leaves C unstarted; the
//! dual-process daemon/Root case must dispatch its retained signed RunStart.
use super::*;
use super::publication::FreshPublication;
use super::stages::FreshStages;
use anyhow::Context as _;
use std::os::unix::net::UnixStream;
use crate::OriginalCircuitRetainedVersionHostV1 as Version;
use crate::OriginalCircuitSelectionCommandOwnerV1 as SelectionHost;
use crate::learning_iteration_evidence_client::command_test_support as commands;

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
#[ignore = "requires the original UID-0 issuer fixture"]
async fn fresh_original_no_update_publishes_same_a_and_s_without_inventing_c() -> anyhow::Result<()> {
    anyhow::ensure!(unsafe { libc::geteuid() } == 0, "actual UID-0 original issuer fixture");
    let (issuer, reply) = UnixStream::pair()?;
    let issuer = crate::AgentdUnixFinalUseGrantProvider::from_root_stream(
        issuer, std::process::id(), commands::pidfd()?,
        Duration::from_secs(30), Duration::from_secs(300),
    )?;
    let mut stages = Box::pin(FreshStages::new()).await?;
    let completed: anyhow::Result<()> = async {
        Box::pin(stages.complete_training()).await?;
        Box::pin(stages.complete_b_and_evaluation()).await?;
        Ok(())
    }.await;
    if let Err(error) = completed {
        return super::stages::finish_case(Err(error), stages).await;
    }
    let mut fixture = Box::pin(FreshPublication::new(stages, issuer)).await?;
    let result: anyhow::Result<()> = async {
        Box::pin(fixture.publish_with_original_fixture_root(reply)).await?;
        Box::pin(fixture.complete_original_selection()).await?;
        Box::pin(fixture.hold_original_completion_readiness()).await?;
        anyhow::ensure!(fixture.c_request.is_some(), "publication did not consume C's separate RunStart");
        let original = fixture.original_bytes()?;
        let selected = fixture.selection.as_ref().context("actual original S")?.clone();
        let read = SelectionHost::read_original_evaluated_receipt(Arc::clone(
            fixture.selector_host.as_ref().context("same original S host")?,
        )).await?;
        anyhow::ensure!((read.snapshot(), read.receipt(), read.attestation())
            == (selected.snapshot(), selected.receipt(), selected.attestation()));
        let host = fixture.host()?;
        anyhow::ensure!(matches!(Version::prepare_original_version_fixture(host).await,
            Err(crate::OriginalCircuitRetainedVersionErrorV1::ReadbackRequired)),
            "the original prepared publication cannot be replayed");
        anyhow::ensure!(!fixture.read_original_c_completion_once().await?,
            "real C remains unresolved before its original daemon/control dispatch");
        anyhow::ensure!(fixture.original_bytes()? == original,
            "readonly S/current/readiness preserve all original evidence bytes");
        Ok(())
    }.await;
    let cleanup = fixture.finish().await;
    match (result, cleanup) {
        (Ok(()), Ok(())) => Ok(()),
        (Err(error), Ok(())) | (Ok(()), Err(error)) => Err(error),
        (Err(error), Err(cleanup)) => Err(error.context(format!("original Fresh cleanup: {cleanup:#}"))),
    }
}
