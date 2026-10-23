//! Real original Notes descriptor/ACK handoff with qualification-only inputs.

use super::fixture::AckFailure;
use super::fixture::Fixture;
use super::*;
use pretty_assertions::assert_eq;
use std::error::Error;
use std::io::Read;
use std::mem;
use std::net::Shutdown;
use std::os::fd::AsRawFd;
use std::sync::atomic::Ordering;

fn identity() -> NotesTargetIdentity {
    NotesTargetIdentity {
        session_instance: "1".repeat(32),
        task_id: 1,
        incarnation: "2".repeat(32),
    }
}

fn send_offer(
    session: &UnixDatagram,
    with_descriptors: bool,
    wrong_destination: bool,
) -> Result<(UnixStream, UnixDatagram), Box<dyn Error>> {
    let target = identity();
    let destination = if wrong_destination {
        "wrong-destination".to_string()
    } else {
        target.destination_id()
    };
    let offer = serde_json::to_vec(&serde_json::json!({
        "schema_version": 2, "action": "offer_notes_target", "target": target,
        "destination_id": destination
    }))?;
    let (owner_effect, application) = UnixStream::pair()?;
    let (owner_recovery, recovery_peer) = UnixDatagram::pair()?;
    let mut vector = libc::iovec {
        iov_base: offer.as_ptr().cast_mut().cast(),
        iov_len: offer.len(),
    };
    let mut control = [0_usize; 8];
    // SAFETY: bounded JSON and two live borrowed socket descriptors remain
    // valid through sendmsg; the aligned ancillary buffer holds both FDs.
    let sent = unsafe {
        let mut message: libc::msghdr = mem::zeroed();
        message.msg_iov = &mut vector;
        message.msg_iovlen = 1;
        if with_descriptors {
            message.msg_control = control.as_mut_ptr().cast();
            message.msg_controllen =
                libc::CMSG_SPACE((2 * mem::size_of::<libc::c_int>()) as u32) as usize;
            let header = libc::CMSG_FIRSTHDR(&message);
            (*header).cmsg_level = libc::SOL_SOCKET;
            (*header).cmsg_type = libc::SCM_RIGHTS;
            (*header).cmsg_len =
                libc::CMSG_LEN((2 * mem::size_of::<libc::c_int>()) as u32) as usize;
            let descriptors = libc::CMSG_DATA(header).cast::<libc::c_int>();
            descriptors.write(owner_effect.as_raw_fd());
            descriptors.add(1).write(owner_recovery.as_raw_fd());
        }
        libc::sendmsg(session.as_raw_fd(), &message, libc::MSG_NOSIGNAL)
    };
    if sent != offer.len() as isize {
        return Err(std::io::Error::last_os_error().into());
    }
    Ok((application, recovery_peer))
}

fn assert_empty_stream(mut peer: UnixStream) -> Result<(), Box<dyn Error>> {
    peer.set_nonblocking(true)?;
    match peer.read(&mut [0; 1]) {
        Ok(0) => Ok(()),
        Err(error) if error.kind() == std::io::ErrorKind::WouldBlock => Ok(()),
        result => {
            Err(format!("bootstrap unexpectedly wrote effect/issuer bytes: {result:?}").into())
        }
    }
}

fn assert_uninstalled(config: &mut AgentdConfig) {
    assert!(config.production_writer_host().is_none());
    assert!(config.take_production_operations().is_none());
}

#[tokio::test]
async fn original_notes_offer_ack_returns_identity_only_after_both_handles_install()
-> Result<(), Box<dyn Error>> {
    let (mut config, fixture) = Fixture::new().await?;
    let (mut inputs, probes, issuer_peer) = fixture.inputs()?;
    let (notes_inputs, notes_probes, _unused_issuer_peer) = fixture.inputs()?;
    let (owner, session) = UnixDatagram::pair()?;
    let (application, _recovery_peer) = send_offer(&session, true, false)?;
    inputs.notes = Some(AgentdProductionNotesInputs {
        bootstrap: owner,
        final_use: notes_inputs.final_use,
    });
    let registered = attach_production_operation_host(&mut config, inputs).await?;
    assert_eq!(registered, Some(identity()));
    let original_host = config.production_writer_host().unwrap();
    let operations = config.take_production_operations().unwrap();
    let (runtime_host, _) = operations.attach(original_host.clone()).await?;
    assert!(Arc::ptr_eq(&original_host.writer(), &runtime_host.writer()));
    assert_eq!(runtime_host.destination_count(), 2);
    session.set_nonblocking(true)?;
    let mut bytes = [0_u8; 1024];
    let length = session.recv(&mut bytes)?;
    let ack: serde_json::Value = serde_json::from_slice(&bytes[..length])?;
    assert_eq!(
        ack,
        serde_json::json!({
            "schema_version": 2, "action": "notes_target_registration", "target": identity(),
            "destination_id": identity().destination_id(), "status": "attached"
        })
    );
    assert_eq!(notes_probes.frontier.loads.load(Ordering::SeqCst), 1);
    assert_eq!(probes.target.effects.load(Ordering::SeqCst), 0);
    assert_empty_stream(application)?;
    assert_empty_stream(issuer_peer)
}

#[tokio::test]
async fn malformed_notes_descriptors_or_identity_publish_neither_host() -> Result<(), Box<dyn Error>>
{
    for (descriptors, wrong_destination) in [(false, false), (true, true)] {
        let (mut config, fixture) = Fixture::new().await?;
        let (mut inputs, probes, issuer_peer) = fixture.inputs()?;
        let (notes_inputs, notes_probes, _unused_peer) = fixture.inputs()?;
        let (owner, session) = UnixDatagram::pair()?;
        let (application, _recovery_peer) = send_offer(&session, descriptors, wrong_destination)?;
        inputs.notes = Some(AgentdProductionNotesInputs {
            bootstrap: owner,
            final_use: notes_inputs.final_use,
        });
        assert!(
            attach_production_operation_host(&mut config, inputs)
                .await
                .is_err()
        );
        assert_uninstalled(&mut config);
        assert_eq!(notes_probes.frontier.loads.load(Ordering::SeqCst), 1);
        assert_eq!(probes.target.effects.load(Ordering::SeqCst), 0);
        assert_empty_stream(application)?;
        assert_empty_stream(issuer_peer)?;
    }
    Ok(())
}

#[tokio::test]
async fn unavailable_original_notes_ack_does_not_publish_or_return_identity()
-> Result<(), Box<dyn Error>> {
    let (mut config, fixture) = Fixture::new().await?;
    let (mut inputs, probes, issuer_peer) = fixture.inputs()?;
    let (notes_inputs, notes_probes, _unused_peer) = fixture.inputs()?;
    let (owner, session) = UnixDatagram::pair()?;
    let (application, _recovery_peer) = send_offer(&session, true, false)?;
    // Keep the original connected peer and its queued offer, but prevent it
    // from accepting the original receiver's registration acknowledgement.
    session.shutdown(Shutdown::Read)?;
    inputs.notes = Some(AgentdProductionNotesInputs {
        bootstrap: owner,
        final_use: notes_inputs.final_use,
    });
    assert!(
        attach_production_operation_host(&mut config, inputs)
            .await
            .is_err()
    );
    assert_uninstalled(&mut config);
    assert_eq!(notes_probes.frontier.loads.load(Ordering::SeqCst), 1);
    assert_eq!(probes.target.effects.load(Ordering::SeqCst), 0);
    assert_empty_stream(application)?;
    assert_empty_stream(issuer_peer)
}

#[tokio::test]
async fn attached_ack_followed_by_live_refusal_returns_no_identity_and_closes_target()
-> Result<(), Box<dyn Error>> {
    for fault in [1, 2, 3] {
        let (mut config, fixture) = Fixture::new().await?;
        let (mut inputs, probes, issuer_peer) = fixture.inputs()?;
        let (notes_inputs, _notes_probes, _unused_peer) = fixture.inputs()?;
        let (owner, session) = UnixDatagram::pair()?;
        let (mut application, _recovery_peer) = send_offer(&session, true, false)?;
        session.set_nonblocking(true)?;
        *probes.target.ack_failure.lock().unwrap() = Some(AckFailure {
            socket: session.try_clone()?,
            observed: None,
            fault,
        });
        inputs.notes = Some(AgentdProductionNotesInputs {
            bootstrap: owner,
            final_use: notes_inputs.final_use,
        });
        assert!(
            attach_production_operation_host(&mut config, inputs)
                .await
                .is_err()
        );
        assert_uninstalled(&mut config);
        let ack = probes
            .target
            .ack_failure
            .lock()
            .unwrap()
            .as_mut()
            .unwrap()
            .observed
            .take()
            .unwrap();
        assert_eq!(ack["status"], "attached");
        assert_eq!(ack["target"], serde_json::to_value(identity())?);
        assert_eq!(probes.target.effects.load(Ordering::SeqCst), 0);
        application.set_nonblocking(true)?;
        assert_eq!(application.read(&mut [0; 1])?, 0);
        assert_empty_stream(issuer_peer)?;
    }
    Ok(())
}

#[tokio::test]
async fn notes_independent_frontier_refusal_does_not_publish_or_read_handoff()
-> Result<(), Box<dyn Error>> {
    let (mut config, fixture) = Fixture::new().await?;
    let (mut inputs, probes, issuer_peer) = fixture.inputs()?;
    let (notes_inputs, notes_probes, _unused_peer) = fixture.inputs()?;
    notes_probes.frontier.denied.store(true, Ordering::SeqCst);
    let (owner, session) = UnixDatagram::pair()?;
    let owner_probe = owner.try_clone()?;
    let (application, _recovery_peer) = send_offer(&session, true, false)?;
    inputs.notes = Some(AgentdProductionNotesInputs {
        bootstrap: owner,
        final_use: notes_inputs.final_use,
    });
    assert!(
        attach_production_operation_host(&mut config, inputs)
            .await
            .is_err()
    );
    assert_uninstalled(&mut config);
    owner_probe.set_nonblocking(true)?;
    let mut remaining_offer = [0_u8; 1024];
    assert!(owner_probe.recv(&mut remaining_offer)? > 0);
    assert_eq!(notes_probes.frontier.loads.load(Ordering::SeqCst), 1);
    assert_eq!(probes.target.effects.load(Ordering::SeqCst), 0);
    assert_empty_stream(application)?;
    assert_empty_stream(issuer_peer)
}
