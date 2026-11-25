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
        .unwrap_err();
    assert!(error.to_string().contains("PeerDenied"));
    assert_uninstalled(&mut config);
    assert_eq!(probes.frontier.loads.load(Ordering::SeqCst), 0);
    assert_eq!(probes.target.effects.load(Ordering::SeqCst), 0);
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
            .unwrap_err();
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
    assert_eq!(
        attach_production_operation_host(&mut config, inputs).await?,
        None
    );
    let first_host = config.production_writer_host().unwrap();
    first_host.writer().verify_current_authority().await?;
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
        .unwrap_err();
    assert!(error.to_string().contains("already configured"));
    assert_eq!(second.clock.calls.load(Ordering::SeqCst), 0);
    assert_eq!(second.verifier.calls.load(Ordering::SeqCst), 0);
    assert_eq!(second.frontier.loads.load(Ordering::SeqCst), 0);
    assert_eq!(second.target.metadata_calls.load(Ordering::SeqCst), 0);
    assert_eq!(second.target.effects.load(Ordering::SeqCst), 0);
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
