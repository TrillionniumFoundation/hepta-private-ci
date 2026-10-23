//! These tests use the real Fleet, recovery, SQLite writer and Agentd config.
//! They must run in the original Agentd package; the authority-only harness
//! does not compile or execute this composition or its persistent owner.

use super::*;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_memory::CognitiveStore;
use pretty_assertions::assert_eq;
use std::error::Error;
use std::io::Read;
use std::sync::atomic::Ordering;

use super::fixture::CheckpointMode;
use super::fixture::EXPIRES;
use super::fixture::Fixture;
use super::fixture::LIVE_MS;

fn assert_uninstalled(config: &mut AgentdConfig) {
    assert!(config.production_writer_host().is_none());
    assert!(config.take_production_operations().is_none());
}

fn assert_no_issuer_request(mut peer: UnixStream) -> Result<(), Box<dyn Error>> {
    peer.set_nonblocking(true)?;
    match peer.read(&mut [0; 1]) {
        Ok(0) => Ok(()),
        Err(error) if error.kind() == std::io::ErrorKind::WouldBlock => Ok(()),
        result => Err(format!("bootstrap unexpectedly wrote to issuer: {result:?}").into()),
    }
}

#[tokio::test]
async fn issuer_peer_refusal_leaves_neither_host_registered() -> Result<(), Box<dyn Error>> {
    let (mut config, fixture) = Fixture::new().await?;
    let (mut inputs, probes, peer) = fixture.inputs()?;
    inputs.issuer_peer.pid += 1;
    let error = attach_production_operation_host(&mut config, inputs)
        .await
        .err()
        .expect("issuer peer refusal");
    assert!(error.to_string().contains("PeerDenied"));
    assert_uninstalled(&mut config);
    assert_eq!(probes.frontier.loads.load(Ordering::SeqCst), 0);
    assert_eq!(probes.target.effects.load(Ordering::SeqCst), 0);
    assert!(probes.checkpoint.seen.lock().unwrap().is_empty());
    assert_no_issuer_request(peer)
}

#[tokio::test]
async fn frontier_and_current_cut_refusals_leave_neither_host_registered()
-> Result<(), Box<dyn Error>> {
    for deny_frontier in [true, false] {
        let (mut config, fixture) = Fixture::new().await?;
        let mut wrong_cut = fixture.cut.clone();
        wrong_cut.state_digest = Sha256Digest::for_bytes(b"not-the-independently-retained-cut");
        let (mut inputs, probes, peer) = fixture.inputs()?;
        if deny_frontier {
            probes.frontier.denied.store(true, Ordering::SeqCst);
        } else {
            inputs.current_cut = CognitiveRecoveryRequirement::ExactCurrentCut(&wrong_cut);
        }
        assert!(
            attach_production_operation_host(&mut config, inputs)
                .await
                .is_err()
        );
        assert_uninstalled(&mut config);
        assert_eq!(probes.frontier.loads.load(Ordering::SeqCst), 1);
        assert_eq!(probes.target.effects.load(Ordering::SeqCst), 0);
        assert!(probes.checkpoint.seen.lock().unwrap().is_empty());
        assert_no_issuer_request(peer)?;
        // Refusal does not create an alternative writer or rewrite the source.
        let store = CognitiveStore::open(&config.identity().layout).await?;
        assert_eq!(store.recovery_anchor().await?, fixture.cut);
        store.close().await;
    }
    Ok(())
}

#[tokio::test]
async fn revoked_cut_and_initial_expiry_do_not_open_the_protected_owner()
-> Result<(), Box<dyn Error>> {
    for revoked_cut in [true, false] {
        let (mut config, fixture) = Fixture::new().await?;
        let (mut inputs, probes, peer) = fixture.inputs()?;
        if revoked_cut {
            inputs.current_cut = CognitiveRecoveryRequirement::Revoked;
        } else {
            probes.clock.now_ms.store(EXPIRES * 1_000, Ordering::SeqCst);
        }
        assert!(
            attach_production_operation_host(&mut config, inputs)
                .await
                .is_err()
        );
        assert_uninstalled(&mut config);
        assert_eq!(probes.frontier.loads.load(Ordering::SeqCst), 0);
        assert_eq!(probes.verifier.calls.load(Ordering::SeqCst), 0);
        assert_eq!(probes.target.effects.load(Ordering::SeqCst), 0);
        assert!(probes.checkpoint.seen.lock().unwrap().is_empty());
        assert_no_issuer_request(peer)?;
    }
    Ok(())
}

#[tokio::test]
async fn original_live_verifier_and_protected_clock_failures_during_recovery_do_not_install()
-> Result<(), Box<dyn Error>> {
    for failure in 0..3 {
        let (mut config, fixture) = Fixture::new().await?;
        let (inputs, probes, peer) = fixture.inputs()?;
        // Call 1 is the composition preflight. The next original verifier
        // invocation belongs to recovery, after protected FinalUse opened.
        match failure {
            0 => probes.verifier.expire_at_call.store(2, Ordering::SeqCst),
            1 => probes
                .verifier
                .unavailable_at_call
                .store(2, Ordering::SeqCst),
            _ => probes.verifier.reject_at_call.store(2, Ordering::SeqCst),
        }
        assert!(
            attach_production_operation_host(&mut config, inputs)
                .await
                .is_err()
        );
        assert_uninstalled(&mut config);
        assert_eq!(probes.verifier.calls.load(Ordering::SeqCst), 2);
        assert_eq!(probes.frontier.loads.load(Ordering::SeqCst), 1);
        assert_eq!(probes.target.effects.load(Ordering::SeqCst), 0);
        assert!(probes.checkpoint.seen.lock().unwrap().is_empty());
        assert_no_issuer_request(peer)?;
    }
    Ok(())
}

#[tokio::test]
async fn final_metadata_callback_cannot_expire_authority_before_atomic_install()
-> Result<(), Box<dyn Error>> {
    for fault in [1, 2] {
        let (mut config, fixture) = Fixture::new().await?;
        let (inputs, probes, peer) = fixture.inputs()?;
        probes
            .target
            .late_clock_fault
            .store(fault, Ordering::SeqCst);
        let error = attach_production_operation_host(&mut config, inputs)
            .await
            .err()
            .expect("final protected-clock refusal");
        let expected = if fault == 1 {
            "expired on the protected clock"
        } else {
            "protected authority clock is unavailable"
        };
        assert!(error.to_string().contains(expected));
        assert!(probes.verifier.calls.load(Ordering::SeqCst) > 2);
        assert_uninstalled(&mut config);
        assert_eq!(probes.target.effects.load(Ordering::SeqCst), 0);
        assert_no_issuer_request(peer)?;
    }
    Ok(())
}

#[tokio::test]
async fn success_keeps_one_original_writer_and_repeat_assembly_touches_no_inputs()
-> Result<(), Box<dyn Error>> {
    let (mut config, fixture) = Fixture::new().await?;
    let (inputs, probes, peer) = fixture.inputs()?;
    let attachment = attach_production_operation_host(&mut config, inputs).await?;
    assert_eq!(attachment.notes_identity, None);
    let first_host = config.production_writer_host().unwrap();
    first_host.writer().verify_current_authority().await?;
    let current = first_host.writer().recovery_anchor().await?;
    assert_ne!(current, fixture.cut);
    let seen = probes.checkpoint.seen.lock().unwrap().clone();
    assert_eq!(seen.len(), 1);
    assert_eq!(seen[0].0, current);
    assert_eq!(seen[0].1.owner_agent_id, config.identity().agent_id);
    assert_eq!(seen[0].1.lease_id, "composition-fixture-lease");
    assert_eq!(seen[0].1.generation, config.identity().spawn_generation);
    assert!(
        CognitiveStore::open(&config.identity().layout)
            .await
            .is_err()
    );
    assert_eq!(probes.target.effects.load(Ordering::SeqCst), 0);
    assert_no_issuer_request(peer)?;

    let (mut inputs, second, peer) = fixture.inputs()?;
    inputs.current_cut = CognitiveRecoveryRequirement::Revoked;
    inputs.issuer_peer.pid += 1;
    let error = attach_production_operation_host(&mut config, inputs)
        .await
        .err()
        .expect("duplicate composition refusal");
    assert!(error.to_string().contains("already configured"));
    assert_eq!(second.clock.calls.load(Ordering::SeqCst), 0);
    assert_eq!(second.verifier.calls.load(Ordering::SeqCst), 0);
    assert_eq!(second.frontier.loads.load(Ordering::SeqCst), 0);
    assert_eq!(second.target.metadata_calls.load(Ordering::SeqCst), 0);
    assert_eq!(second.target.effects.load(Ordering::SeqCst), 0);
    assert!(second.checkpoint.seen.lock().unwrap().is_empty());
    assert!(Arc::ptr_eq(
        &first_host,
        &config.production_writer_host().unwrap()
    ));
    assert!(config.take_production_operations().is_some());
    assert_no_issuer_request(peer)
}

#[tokio::test]
async fn installed_original_writer_keeps_the_protected_clock_and_original_verifier_live()
-> Result<(), Box<dyn Error>> {
    let (mut config, fixture) = Fixture::new().await?;
    let (inputs, probes, peer) = fixture.inputs()?;
    attach_production_operation_host(&mut config, inputs).await?;
    let writer = config.production_writer_host().unwrap().writer();
    writer.admit("before-expiry", "fixture", "{}").await?;
    let before = writer.recovery_anchor().await?;
    probes.clock.now_ms.store(EXPIRES * 1_000, Ordering::SeqCst);
    assert!(writer.admit("expired", "fixture", "{}").await.is_err());
    probes.clock.now_ms.store(LIVE_MS, Ordering::SeqCst);
    probes.clock.unavailable.store(true, Ordering::SeqCst);
    assert!(
        writer
            .admit("clock-unavailable", "fixture", "{}")
            .await
            .is_err()
    );
    probes.clock.unavailable.store(false, Ordering::SeqCst);
    let next_call = probes.verifier.calls.load(Ordering::SeqCst) + 1;
    probes
        .verifier
        .reject_at_call
        .store(next_call, Ordering::SeqCst);
    assert!(writer.admit("revoked", "fixture", "{}").await.is_err());
    assert_eq!(writer.recovery_anchor().await?, before);
    assert_eq!(probes.target.effects.load(Ordering::SeqCst), 0);
    assert_no_issuer_request(peer)
}

#[tokio::test]
async fn invalid_checkpoint_deadline_refuses_before_consulting_external_inputs()
-> Result<(), Box<dyn Error>> {
    for deadline in [Duration::ZERO, Duration::from_millis(5_001)] {
        let (mut config, fixture) = Fixture::new().await?;
        let (mut inputs, probes, peer) = fixture.inputs()?;
        inputs.checkpoint_deadline = deadline;
        assert!(
            attach_production_operation_host(&mut config, inputs)
                .await
                .is_err()
        );
        assert_uninstalled(&mut config);
        assert!(probes.checkpoint.seen.lock().unwrap().is_empty());
        assert_eq!(probes.clock.calls.load(Ordering::SeqCst), 0);
        assert_eq!(probes.verifier.calls.load(Ordering::SeqCst), 0);
        assert_eq!(probes.frontier.loads.load(Ordering::SeqCst), 0);
        assert_eq!(probes.target.metadata_calls.load(Ordering::SeqCst), 0);
        assert_eq!(probes.target.effects.load(Ordering::SeqCst), 0);
        assert_no_issuer_request(peer)?;
    }
    Ok(())
}

#[tokio::test]
async fn checkpoint_failures_and_post_ack_live_refusals_never_install_recovered_hosts()
-> Result<(), Box<dyn Error>> {
    for mode in [
        CheckpointMode::Refuse,
        CheckpointMode::Hold,
        CheckpointMode::Mismatch,
        CheckpointMode::ExpireAfterAck,
        CheckpointMode::UnavailableAfterAck,
        CheckpointMode::RevokeAfterAck,
    ] {
        let (mut config, fixture) = Fixture::new().await?;
        let (mut inputs, probes, peer) = fixture.inputs()?;
        *probes.checkpoint.mode.lock().unwrap() = mode;
        inputs.checkpoint_deadline = Duration::from_millis(5);
        assert!(
            attach_production_operation_host(&mut config, inputs)
                .await
                .is_err()
        );
        assert_uninstalled(&mut config);
        let seen = probes.checkpoint.seen.lock().unwrap().clone();
        assert_eq!(seen.len(), 1);
        // Recovery acquired the original lease before the callback. The old
        // independent recovery input cannot stand in for this changed cut.
        assert_ne!(seen[0].0, fixture.cut);
        assert_eq!(seen[0].1.owner_agent_id, config.identity().agent_id);
        assert_eq!(seen[0].1.generation, config.identity().spawn_generation);
        assert_eq!(probes.frontier.loads.load(Ordering::SeqCst), 1);
        assert_eq!(probes.target.effects.load(Ordering::SeqCst), 0);
        assert_no_issuer_request(peer)?;
    }
    Ok(())
}
