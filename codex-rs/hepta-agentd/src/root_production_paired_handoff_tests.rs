//! Real anonymous descriptor transport; positive checks exercise framing and
//! custody of open objects, not actual Root provenance or human enrollment.
use super::*;
use pretty_assertions::assert_eq;
use std::io::Read;
use std::io::Write;
use std::os::unix::fs::MetadataExt;
use std::os::unix::net::UnixStream;

#[test]
fn paired_handoff_preserves_ordered_open_objects_and_cloexec() -> anyhow::Result<()> {
    let (sender, receiver) = UnixDatagram::pair()?;
    let mut first = tempfile::tempfile()?;
    let mut second = tempfile::tempfile()?;
    first.write_all(b"paired-scope")?;
    second.write_all(b"separate-root-pin-slot")?;
    send_packet(
        &sender,
        PAIRED_TRAINING_FRAME,
        &[first.as_raw_fd(), second.as_raw_fd()],
        Duration::from_secs(1),
    )?;
    let (received_first, received_second) =
        receive_paired_training_packet(&receiver, Duration::from_secs(1))?;
    let received_second = File::from(received_second);
    assert_eq!(received_first.metadata()?.ino(), first.metadata()?.ino());
    assert_eq!(received_second.metadata()?.ino(), second.metadata()?.ino());
    for descriptor in [&received_first, &received_second] {
        // SAFETY: F_GETFD only observes the live received file descriptor.
        assert_ne!(
            unsafe { libc::fcntl(descriptor.as_raw_fd(), libc::F_GETFD) } & libc::FD_CLOEXEC,
            0
        );
    }
    assert!(validate_bootstrap(&received_first).is_err());
    Ok(())
}

#[test]
fn paired_and_original_v1_handoffs_refuse_each_others_purpose() -> anyhow::Result<()> {
    for paired_receiver in [false, true] {
        let (sender, receiver) = UnixDatagram::pair()?;
        let (first, mut first_peer) = UnixStream::pair()?;
        let (second, mut second_peer) = UnixStream::pair()?;
        send_packet(
            &sender,
            if paired_receiver {
                FRAME
            } else {
                PAIRED_TRAINING_FRAME
            },
            &[first.as_raw_fd(), second.as_raw_fd()],
            Duration::from_secs(1),
        )?;
        drop((first, second));
        let result = if paired_receiver {
            receive_paired_training_packet(&receiver, Duration::from_secs(1))
        } else {
            receive_packet(&receiver, Duration::from_secs(1))
        };
        assert!(result.is_err());
        for peer in [&mut first_peer, &mut second_peer] {
            peer.set_read_timeout(Some(Duration::from_secs(1)))?;
            assert_eq!(peer.read(&mut [0])?, 0);
        }
    }
    Ok(())
}

#[test]
fn paired_handoff_rejects_missing_or_extra_rights_and_closes_every_received_right()
-> anyhow::Result<()> {
    for count in [0, 1, 3] {
        let (sender, receiver) = UnixDatagram::pair()?;
        let pairs = (0..count)
            .map(|_| UnixStream::pair())
            .collect::<io::Result<Vec<_>>>()?;
        let (sent, mut peers): (Vec<_>, Vec<_>) = pairs.into_iter().unzip();
        let rights = sent.iter().map(AsRawFd::as_raw_fd).collect::<Vec<_>>();
        if rights.is_empty() {
            sender.send(PAIRED_TRAINING_FRAME)?;
        } else {
            send_packet(
                &sender,
                PAIRED_TRAINING_FRAME,
                &rights,
                Duration::from_secs(1),
            )?;
        }
        drop(sent);
        assert!(receive_paired_training_packet(&receiver, Duration::from_secs(1)).is_err());
        for peer in &mut peers {
            peer.set_read_timeout(Some(Duration::from_secs(1)))?;
            assert_eq!(peer.read(&mut [0])?, 0);
        }
    }
    Ok(())
}
