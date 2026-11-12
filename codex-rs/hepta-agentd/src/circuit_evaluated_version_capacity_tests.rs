//! Real original command, Candidate page and B evidence purposes all take the
//! same Trainer semaphore. This is an explicit same-process transport fixture,
//! not a fifth permit, second Trainer, or ordinary deployment proof.
use super::*;
use pretty_assertions::assert_eq;

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn evaluated_version_mixed_trainer_purposes_share_four_sessions_and_refuse_fifth()
-> anyhow::Result<()> {
    let f = Box::pin(PublicationFixture::ready()).await?;
    let original = Box::pin(original_dataset(&f)).await?;
    let material = &original.config;
    let (root_connection, root_peer) = commands::original_version_training_readback_connection(
        material.clone(),
        Arc::clone(&f.trainer),
    )?;
    let root = root_connection.bind_original_dataset(original.receipt.clone())?;
    let (candidate_connection, candidate_peer) =
        commands::original_version_candidate_peer(material.clone(), Arc::clone(&f.trainer))?;
    let candidate = candidate_connection.bind_original_candidate_material(
        original.receipt.clone(),
        f.training.clone(),
        Arc::clone(&f.host.original.baseline),
    )?;
    let (version_connection, version_peer) =
        commands::original_version_training_readback_connection(
            material.clone(),
            Arc::clone(&f.trainer),
        )?;
    let version = version_connection.bind_original_dataset(original.receipt.clone())?;
    // Start the strict 500ms evidence peer last. It still runs the actual
    // evidence server and actual Stage read, with no timeout or lifetime change.
    let (evidence, evidence_peer) =
        commands::original_version_evidence_peer(Arc::clone(&f.trainer))?;
    commands::original_version_fifth_connection_refuses(Arc::clone(&f.trainer)).await?;
    assert_eq!(
        evidence
            .readback(f.evaluation.snapshot(), f.training.receipt())
            .await?,
        *f.training.attestation()
    );
    assert_eq!(root.readback().await?, f.training);
    let candidate_material = candidate.readback().await?;
    assert_eq!(candidate_material.receipt(), f.training.receipt());
    assert_eq!(candidate_material.attestation(), f.training.attestation());
    assert_eq!(version.readback().await?, f.training);
    commands::original_version_fifth_connection_refuses(Arc::clone(&f.trainer)).await?;
    drop(evidence);
    assert_eq!(evidence_peer.join().expect("same B evidence purpose")?, 1);
    drop(candidate);
    let pages = candidate_peer
        .join()
        .expect("same actual Candidate page purpose")?;
    assert!(
        (1..=17).contains(&pages),
        "actual bounded original candidate pages"
    );
    drop(root);
    assert_eq!(root_peer.join().expect("same Root command purpose")?, 1);
    drop(version);
    assert_eq!(
        version_peer.join().expect("same Version command purpose")?,
        1
    );
    finish_dataset(original)?;
    f.finish().await
}
