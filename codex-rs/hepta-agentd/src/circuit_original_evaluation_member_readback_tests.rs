//! Actual independent original member peers; their budgets are not replaced.
use std::sync::Arc;

use pretty_assertions::assert_eq;
use pretty_assertions::assert_ne;

use super::CommandError;
use super::HostFixture;
use super::finish;

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn original_evaluation_member_readback_keeps_full_original_bytes_below_peer_bound()
-> anyhow::Result<()> {
    let fixture = Box::pin(HostFixture::new(/*pending_claim*/ false)).await?;
    let upstream = fixture.upstream_files()?;
    let (client, peer) = fixture.commands(
        /*readback_only*/ false, /*expected*/ None, "original",
    )?;
    let original = client.execute_evaluation().await?;
    let completed = fixture.original_files()?;
    // The original individual path needed 2 + 10 + 14*9 = 138 primary
    // requests. These are fourteen full calls on the very same original peer.
    for _ in 0..14 {
        assert_eq!(client.readback().await?, original);
        assert_eq!(fixture.original_files()?, completed);
        assert_eq!(fixture.upstream_files()?, upstream);
    }
    assert!(matches!(
        client.execute_evaluation().await,
        Err(CommandError::ReadbackRequired)
    ));
    assert_eq!(finish(client, peer)?, 15);
    assert_eq!(fixture.finish().await?, [54, 38]);
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn original_evaluation_member_proof_refuses_partial_cross_call_source_and_extra_slots()
-> anyhow::Result<()> {
    let fixture = Box::pin(HostFixture::new(/*pending_claim*/ false)).await?;
    let upstream = fixture.upstream_files()?;
    let original = fixture.original_files()?;
    let host = Arc::clone(
        fixture
            .host
            .as_ref()
            .ok_or_else(|| anyhow::anyhow!("original host"))?,
    );
    tokio::task::spawn_blocking(move || host.fixture_member_readback_proof_lifecycle()).await??;
    assert_eq!(fixture.original_files()?, original);
    assert_eq!(fixture.upstream_files()?, upstream);
    // Setup2, one partial call1, then two complete calls2 each. Wrong member
    // and changed Qualification pins are both refused before Trainer I/O.
    assert_eq!(fixture.finish().await?, [7, 7]);
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn original_evaluation_member_readback_refuses_actual_source_withdrawal_inside_call()
-> anyhow::Result<()> {
    let fixture = Box::pin(HostFixture::new(/*pending_claim*/ false)).await?;
    let upstream = fixture.upstream_files()?;
    let original = fixture.original_files()?;
    let host = Arc::clone(
        fixture
            .host
            .as_ref()
            .ok_or_else(|| anyhow::anyhow!("original host"))?,
    );
    let (entered, reached) = tokio::sync::oneshot::channel();
    let (resume, proceed) = std::sync::mpsc::channel();
    let task = tokio::task::spawn_blocking(move || {
        host.fixture_member_readback_source_withdrawal(entered, proceed)
    });
    reached.await?;
    let withdrawal = fixture.retention_b.withdraw_target();
    resume.send(())?;
    withdrawal?;
    task.await??;
    assert_ne!(fixture.upstream_files()?, upstream);
    assert_eq!(fixture.original_files()?, original);
    for expected_first in [true, false] {
        let (client, peer) = fixture.commands(
            /*readback_only*/ true, /*expected*/ None, "original",
        )?;
        let result = client.readback().await;
        if expected_first {
            assert!(matches!(result, Err(CommandError::PredecessorUnavailable)));
        } else {
            assert!(matches!(result, Err(CommandError::CommitUncertain)));
        }
        assert_eq!(finish(client, peer)?, 1);
        assert_eq!(fixture.original_files()?, original);
    }
    assert_eq!(fixture.finish().await?, [3, 3]);
    Ok(())
}
