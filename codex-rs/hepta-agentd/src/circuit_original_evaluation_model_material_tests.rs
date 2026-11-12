//! Actual Source/Ledger B, nonempty retention, Runner, execution, Qualification
//! and Evaluator. All credentials, declared Product metadata and future B clock
//! are explicit mechanism fixtures. Ineligible is preserved, never promoted.
use pretty_assertions::assert_eq;
use pretty_assertions::assert_ne;

use super::*;
use crate::OriginalCellEvaluationModelMaterialClientV1;

fn close(client: OriginalCellEvaluationModelMaterialClientV1, peer: fixture::Peer) -> anyhow::Result<u64> {
    drop(client);
    peer.join().map_err(|_| anyhow::anyhow!("original material peer panicked"))?
}

async fn complete(fixture: &HostFixture) -> anyhow::Result<crate::OriginalCellEvaluationCommandReceiptV1> {
    let (client, peer) = fixture.commands(/*readback_only*/ false, /*expected*/ None, "original")?;
    let evaluation = client.execute_evaluation().await?;
    assert_eq!(finish(client, peer)?, 1);
    Ok(evaluation)
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn original_evaluation_model_material_reads_actual_panel_and_identical_local_digest() -> anyhow::Result<()> {
    let mut fixture = HostFixture::new(/*pending_claim*/ false).await?;
    let evaluation = complete(&fixture).await?;
    let original_files = fixture.original_files()?;
    let upstream = fixture.upstream_files()?;
    let (client, peer) = fixture.host.as_ref().unwrap().fixture_model_material_commands(
        /*expected*/ None, "original", /*pause*/ None,
    )?;
    let material = client.fixture_read_current_at(fixture.at).await?;
    assert_eq!(material.authority(), AuthorityPosture::DENY_ALL);
    assert_eq!(material.original_evaluation(), &evaluation);
    material.fixture_original_material_preimages(fixture.at)?;
    let frames = material.fixture_original_material_pages() as u64 + 1;
    assert_eq!(close(client, peer)?, frames);
    assert_eq!(fixture.original_files()?, original_files);
    assert_eq!(fixture.upstream_files()?, upstream);
    crate::OriginalCellEvaluationHostV1::fixture_model_material_format_bounds()?;
    fixture.recover()?;
    let (client, peer) = fixture.host.as_ref().unwrap().fixture_model_material_commands(
        Some(evaluation.clone()), "original", /*pause*/ None,
    )?;
    let recovered = client.fixture_read_current_at(fixture.at).await?;
    assert_eq!(recovered.binding(), material.binding());
    assert_eq!(recovered.original_evaluation(), &evaluation);
    assert_eq!(close(client, peer)?, frames);
    assert_eq!(fixture.original_files()?, original_files);
    assert_eq!(fixture.upstream_files()?, upstream);
    assert!(fixture.finish().await?.into_iter().all(|reads| reads > 2));
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn original_evaluation_model_material_rejects_pages_renewal_and_completed_regression() -> anyhow::Result<()> {
    let fixture = HostFixture::new(/*pending_claim*/ false).await?;
    let evaluation = complete(&fixture).await?;
    let original_files = fixture.original_files()?;
    let upstream = fixture.upstream_files()?;
    for fault in ["wrong-order", "wrong-total", "wrong-offset", "wrong-last", "lose-finish"] {
        let (client, peer) = fixture.host.as_ref().unwrap().fixture_model_material_commands(
            Some(evaluation.clone()), fault, /*pause*/ None,
        )?;
        assert!(client.fixture_read_current_at(fixture.at).await.is_err(), "wire fault {fault}");
        assert!(matches!(client.read_current().await, Err(CommandError::Unavailable)));
        assert!(close(client, peer)? > 0);
    }
    assert_eq!(fixture.original_files()?, original_files);
    assert_eq!(fixture.upstream_files()?, upstream);
    assert!(fixture.finish().await?.into_iter().all(|reads| reads > 2));
    // Each real Trainer peer retains its original 128-frame budget. Independent
    // negative mechanisms use independent original fixtures, never reconnect
    // or splice an unfinished material transfer to extend that budget.
    for (fault, cold_fault) in [("after-missing", "cold-missing"), ("after-pending", "cold-pending")] {
        let fixture = HostFixture::new(/*pending_claim*/ false).await?;
        let evaluation = complete(&fixture).await?;
        let original_files = fixture.original_files()?;
        let upstream = fixture.upstream_files()?;
        let (client, peer) = fixture.host.as_ref().unwrap().fixture_model_material_commands(
            /*expected*/ None, fault, /*pause*/ None,
        )?;
        let material = client.fixture_read_current_at(fixture.at).await?;
        assert_eq!(material.original_evaluation(), &evaluation);
        assert!(matches!(client.fixture_read_current_at(fixture.at).await, Err(CommandError::CommitUncertain)));
        assert!(matches!(client.read_current().await, Err(CommandError::Unavailable)));
        assert_eq!(close(client, peer)?, material.fixture_original_material_pages() as u64 + 2);
        let (client, peer) = fixture.host.as_ref().unwrap().fixture_model_material_commands(
            Some(evaluation.clone()), cold_fault, /*pause*/ None,
        )?;
        assert!(matches!(client.fixture_read_current_at(fixture.at).await, Err(CommandError::CommitUncertain)));
        assert!(matches!(client.read_current().await, Err(CommandError::Unavailable)));
        assert_eq!(close(client, peer)?, 1);
        assert_eq!(fixture.original_files()?, original_files);
        assert_eq!(fixture.upstream_files()?, upstream);
        assert!(fixture.finish().await?.into_iter().all(|reads| reads > 2));
    }
    let fixture = HostFixture::new(/*pending_claim*/ false).await?;
    let evaluation = complete(&fixture).await?;
    let original_files = fixture.original_files()?;
    let upstream = fixture.upstream_files()?;
    let renewed = fixture.host.as_ref().unwrap().fixture_model_material_renewed_evaluation(&evaluation, fixture.at)?;
    let (client, peer) = fixture.host.as_ref().unwrap().fixture_model_material_commands(
        Some(renewed), "original", /*pause*/ None,
    )?;
    assert!(matches!(client.fixture_read_current_at(fixture.at).await,
        Err(CommandError::Binding("unchanged full original Evaluation in material"))));
    assert!(matches!(client.read_current().await, Err(CommandError::Unavailable)));
    assert!(close(client, peer)? > 1);
    let (client, peer) = fixture.host.as_ref().unwrap().fixture_model_material_commands(
        Some(evaluation.clone()), "original", /*pause*/ None,
    )?;
    assert!(client.fixture_read_current_at(evaluation.attestation().expires_at).await.is_err());
    assert!(matches!(client.read_current().await, Err(CommandError::Unavailable)));
    assert_eq!(close(client, peer)?, 0);
    assert_eq!(fixture.original_files()?, original_files);
    assert_eq!(fixture.upstream_files()?, upstream);
    assert!(fixture.finish().await?.into_iter().all(|reads| reads > 2));
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn original_evaluation_model_material_pending_cancel_and_withdrawal_never_execute() -> anyhow::Result<()> {
    for pending_claim in [false, true] {
        let mut fixture = HostFixture::new(pending_claim).await?;
        let original_files = fixture.original_files()?;
        let dispatch_before = fixture.host.as_ref().unwrap().fixture_dispatch_consumed();
        fixture.host.as_ref().unwrap().fixture_model_material_cancel_queued().await?;
        let (client, peer) = fixture.host.as_ref().unwrap().fixture_model_material_commands(
            /*expected*/ None, "original", /*pause*/ None,
        )?;
        let result = client.fixture_read_current_at(fixture.at).await;
        if pending_claim { assert!(matches!(result, Err(CommandError::Pending))); }
        else { assert!(matches!(result, Err(CommandError::Missing))); }
        assert!(matches!(client.read_current().await, Err(CommandError::Unavailable)));
        assert_eq!(close(client, peer)?, 1);
        assert_eq!(fixture.host.as_ref().unwrap().fixture_dispatch_consumed(), dispatch_before);
        fixture.recover()?;
        let (client, peer) = fixture.host.as_ref().unwrap().fixture_model_material_commands(
            /*expected*/ None, "original", /*pause*/ None,
        )?;
        client.fixture_exhaust_original_material_session()?;
        assert!(matches!(client.fixture_read_current_at(fixture.at).await, Err(CommandError::Unavailable)));
        assert_eq!(close(client, peer)?, 0);
        assert_eq!(fixture.original_files()?, original_files);
        assert!(fixture.finish().await?.into_iter().all(|reads| reads > 2));
    }
    for change in ["withdrawn-outcome", "original-cell-current"] {
        let fixture = HostFixture::new(/*pending_claim*/ false).await?;
        let evaluation = complete(&fixture).await?;
        let original_files = fixture.original_files()?;
        let upstream = fixture.upstream_files()?;
        let (ready, observed) = std::sync::mpsc::channel();
        let (release, resume) = std::sync::mpsc::channel();
        let (client, peer) = fixture.host.as_ref().unwrap().fixture_model_material_commands(
            Some(evaluation), "original", Some((ready, resume)),
        )?;
        let at = fixture.at;
        let task = tokio::spawn(async move {
            let result = client.fixture_read_current_at(at).await;
            (client, result)
        });
        tokio::task::spawn_blocking(move || observed.recv_timeout(std::time::Duration::from_secs(/*secs*/ 30))).await??;
        if change == "withdrawn-outcome" {
            fixture.retention_b.withdraw_target()?;
        } else {
            fixture.host.as_ref().unwrap().fixture_model_material_advance_original_cell()?;
            assert_ne!(fixture.upstream_files()?, upstream);
        }
        release.send(())?;
        let (client, result) = task.await?;
        assert!(result.is_err(), "the actual second CURRENT rejects {change}");
        assert!(matches!(client.read_current().await, Err(CommandError::Unavailable)));
        assert!(close(client, peer).is_err());
        assert_eq!(fixture.original_files()?, original_files);
        let (client, peer) = fixture.host.as_ref().unwrap().fixture_model_material_commands(
            /*expected*/ None, "original", /*pause*/ None,
        )?;
        assert!(matches!(client.fixture_read_current_at(fixture.at).await, Err(CommandError::CommitUncertain)));
        assert_eq!(close(client, peer)?, 1);
        assert_eq!(fixture.original_files()?, original_files);
        assert!(fixture.finish().await?.into_iter().all(|reads| reads > 2));
    }
    Ok(())
}
