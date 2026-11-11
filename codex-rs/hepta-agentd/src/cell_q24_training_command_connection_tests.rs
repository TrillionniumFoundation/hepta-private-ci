//! Actual opaque Material cuts on an original prebound Trainer descriptor.
//! No response, Dataset DTO, future head or production credential is invented.
use pretty_assertions::assert_eq;
use pretty_assertions::assert_ne;

use super::*;
use crate::OriginalCellQ24TrainingCommandConnectionErrorV1 as ConnectionError;
use crate::OriginalCellQ24TrainingCommandConnectionV1 as Connection;

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn deferred_training_connection_rejects_experience_and_valid_other_freeze_context()
-> anyhow::Result<()> {
    let fixture = MaterialCommandFixture::new().await?;
    let (owner, peers) = support::owner(&fixture, Origin::Fresh)?;
    let before = fixture.training_bytes()?;
    let (first, server) = prebound(
        Arc::clone(&owner),
        fixture.config.clone(),
        Origin::Fresh,
        None,
        Duration::from_secs(300),
    )?;
    let (experience, original_e) = material::commands(&fixture, Role::Experience)?;
    let experience = {
        let cut = experience.execute().await?;
        drop(experience);
        assert_eq!(material::finish(original_e)?, 1);
        cut
    };
    assert!(matches!(
        first.bind_original_dataset(experience),
        Err(ConnectionError::Command(CommandError::Binding(
            "exact original Dataset context"
        )))
    ));
    assert_eq!(
        server.join().expect("unactivated original Trainer peer")?,
        0
    );
    assert_eq!(fixture.training_bytes()?, before);

    let (dataset, original_d) = material::commands(&fixture, Role::Dataset)?;
    let cut = dataset.execute().await?;
    drop(dataset);
    assert_eq!(material::finish(original_d)?, 1);
    let changed = fixture.renewed_material_configuration()?;
    assert_ne!(changed.freeze_evidence, fixture.config.freeze_evidence);
    let (other, server) = prebound(
        Arc::clone(&owner),
        changed,
        Origin::Fresh,
        None,
        Duration::from_secs(300),
    )?;
    assert!(matches!(
        other.bind_original_dataset(cut.clone()),
        Err(ConnectionError::Material(MaterialError::Binding(
            "same originally authenticated Material context"
        )))
    ));
    assert_eq!(server.join().expect("different valid freeze context")?, 0);
    assert_eq!(fixture.training_bytes()?, before);

    let (same, server) = prebound(
        Arc::clone(&owner),
        fixture.config.clone(),
        Origin::Fresh,
        None,
        Duration::from_secs(300),
    )?;
    let client = same.bind_original_dataset(cut)?;
    assert_eq!(finish(client, server)?, 0);
    assert_eq!(fixture.training_bytes()?, before);
    assert!(matches!(
        &*owner.state.lock().expect("same original bootstrap state"),
        State::Awaiting(_)
    ));
    drop(owner);
    assert_eq!(finish_material(peers)?, [0, 0, 0, 0]);
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn deferred_training_connection_preserves_expiry_and_readonly_cold_original_signature()
-> anyhow::Result<()> {
    let fixture = MaterialCommandFixture::new().await?;
    let (owner, peers) = support::owner(&fixture, Origin::Fresh)?;
    let (first, server) = prebound(
        Arc::clone(&owner),
        fixture.config.clone(),
        Origin::Fresh,
        None,
        Duration::from_secs(300),
    )?;
    let cut = complete_material(&fixture).await?;
    let client = first.bind_original_dataset(cut.clone())?;
    let original = client
        .execute_training(Arc::new(AtomicBool::new(false)))
        .await?;
    assert_eq!(finish(client, server)?, 1);
    let held = fixture.training_bytes()?;
    drop(owner);
    finish_material(peers)?;

    let retained = (original.receipt().clone(), original.attestation().clone());
    let (owner, peers) = support::owner(&fixture, Origin::Recovered)?;
    // Cold Root state supplies saved receipt and full signature bytes. No opaque
    // Training result survives, and actual D has not yet been read back.
    // The original connection starts before the actual Dataset readback.
    let (cold, server) = prebound(
        Arc::clone(&owner),
        fixture.config.clone(),
        Origin::Recovered,
        Some(retained.clone()),
        Duration::from_secs(300),
    )?;
    let mut changed = retained.clone();
    changed.1.issued_at += 1;
    let (invalid, invalid_server) = prebound(
        Arc::clone(&owner),
        fixture.config.clone(),
        Origin::Recovered,
        Some(changed),
        Duration::from_secs(300),
    )?;
    let (dataset, original_d) = material::commands(&fixture, Role::Dataset)?;
    let reread = dataset.readback().await?;
    drop(dataset);
    assert_eq!(material::finish(original_d)?, 1);
    assert_eq!(reread, cut);
    assert!(matches!(
        invalid.bind_original_dataset(reread.clone()),
        Err(ConnectionError::Command(CommandError::Binding(
            "original Training actor and time"
        )))
    ));
    assert_eq!(invalid_server.join().expect("invalid retained Training")?, 0);
    assert_eq!(fixture.training_bytes()?, held);
    let client = cold.bind_original_dataset(reread.clone())?;
    assert!(matches!(
        client
            .execute_training(Arc::new(AtomicBool::new(false)))
            .await,
        Err(CommandError::ReadbackRequired)
    ));
    assert_eq!(client.readback().await?, original);
    assert_eq!(fixture.training_bytes()?, held);
    assert_eq!(finish(client, server)?, 1);

    let (expired, server) = prebound(
        Arc::clone(&owner),
        fixture.config.clone(),
        Origin::Recovered,
        Some(retained),
        Duration::from_millis(40),
    )?;
    tokio::time::sleep(Duration::from_millis(80)).await;
    assert!(matches!(
        expired.bind_original_dataset(reread),
        Err(ConnectionError::Command(CommandError::Transport(
            codex_hepta_contracts::HostIssuerTransportError::DeadlineElapsed
        )))
    ));
    assert!(server.join().expect("expired held Trainer peer").is_err());
    assert_eq!(fixture.training_bytes()?, held);

    let peer = transport::identity()?;
    let (stream, _server) = std::os::unix::net::UnixStream::pair()?;
    let result = Connection::from_original_stream(
        stream,
        crate::LearningIterationEvidencePeerV1 {
            pid: peer.pid,
            // SAFETY: test rejection of same UID and process, no external host.
            uid: unsafe { libc::geteuid() },
            boot_id: peer.boot_id,
            process_start_ticks: peer.process_start_ticks,
            actor_id: fixture.config.initial.owners.trainer.clone(),
        },
        transport::pidfd()?,
        fixture.config.clone(),
        Duration::from_secs(30),
        Duration::from_secs(300),
    );
    assert!(matches!(
        result,
        Err(ConnectionError::Command(CommandError::Transport(
            codex_hepta_contracts::HostIssuerTransportError::PeerDenied
        )))
    ));
    drop(owner);
    finish_material(peers)?;
    assert_eq!(fixture.training_bytes()?, held);
    Ok(())
}
