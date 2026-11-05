//! Real Unix rights on the original peer-pinned transport. No issuer, Root
//! bootstrap, native role or authority qualification is created by these tests.

use super::*;
use crate::HostAuthorityPeerPolicy;
use crate::HostIssuerPeer;
use pretty_assertions::assert_eq;
use std::fs::File;
use std::io::Read;
use std::io::Seek;
use std::io::Write;
use std::os::unix::fs::MetadataExt;
use std::os::unix::net::UnixStream;
use std::time::Duration;

fn pinned(stream: UnixStream) -> HostAuthorityPeerChannel {
    let pid = rustix::process::getpid();
    HostAuthorityPeerChannel::from_stream(
        stream,
        HostAuthorityPeerPolicy {
            peer: HostIssuerPeer {
                uid: rustix::process::getuid().as_raw(),
                pid: pid.as_raw_nonzero().get() as u32,
            },
            timeout: Duration::from_millis(100),
            lifetime: Duration::from_secs(3),
            request_bound: 32,
            response_bound: 32,
        },
        rustix::process::pidfd_open(pid, rustix::process::PidfdFlags::empty()).unwrap(),
    )
    .unwrap()
}

#[test]
fn terminal_descriptor_preserves_actual_object_and_closes_control_stream() {
    let (left, right) = UnixStream::pair().unwrap();
    let sender = pinned(left);
    let receiver = pinned(right);
    let mut file = tempfile::tempfile().unwrap();
    file.write_all(b"the original held object").unwrap();
    file.rewind().unwrap();
    let original = file.metadata().unwrap();
    let sent = std::thread::spawn(move || sender.send_one_descriptor(file.into()));
    let mut received = File::from(receiver.receive_one_descriptor().unwrap());
    assert_eq!(sent.join().unwrap(), Ok(()));
    assert_eq!(
        (
            received.metadata().unwrap().dev(),
            received.metadata().unwrap().ino()
        ),
        (original.dev(), original.ino())
    );
    assert!(
        rustix::io::fcntl_getfd(&received)
            .unwrap()
            .contains(rustix::io::FdFlags::CLOEXEC)
    );
    let mut bytes = Vec::new();
    received.read_to_end(&mut bytes).unwrap();
    assert_eq!(bytes, b"the original held object");
}

#[test]
fn malformed_truncated_extra_or_unfinished_transfer_closes_every_received_right() {
    for (bytes, count, close_sender) in [
        (vec![MARKER ^ 1], 1, true),
        (vec![MARKER, 0], 1, true),
        (vec![MARKER], 0, true),
        (vec![MARKER], 2, true),
        (vec![MARKER], 9, true),
        (vec![MARKER], 1, false),
    ] {
        let (left, right) = UnixStream::pair().unwrap();
        let receiver = pinned(left);
        let mut offered = Vec::new();
        let mut peers = Vec::new();
        for _ in 0..count {
            let (one, peer) = UnixStream::pair().unwrap();
            offered.push(one);
            peers.push(peer);
        }
        let descriptors = offered.iter().map(AsFd::as_fd).collect::<Vec<_>>();
        let mut space = [MaybeUninit::uninit(); rustix::cmsg_space!(ScmRights(9))];
        let mut control = SendAncillaryBuffer::new(&mut space);
        if count != 0 {
            assert!(control.push(SendAncillaryMessage::ScmRights(&descriptors)));
        }
        assert_eq!(
            rustix::net::sendmsg(
                &right,
                &[IoSlice::new(&bytes)],
                &mut control,
                SendFlags::NOSIGNAL
            )
            .unwrap(),
            bytes.len()
        );
        drop(control);
        drop(descriptors);
        drop(offered);
        if close_sender {
            right.shutdown(Shutdown::Write).unwrap();
        }
        assert!(
            receiver.receive_one_descriptor().is_err(),
            "malformed case count={count}, close={close_sender}"
        );
        for mut peer in peers {
            peer.set_read_timeout(Some(Duration::from_secs(1))).unwrap();
            assert_eq!(peer.read(&mut [0]).unwrap(), 0, "all rejected rights close");
        }
    }
}

#[test]
fn sender_failure_consumes_the_original_descriptor_without_sigpipe_or_retry() {
    let (left, right) = UnixStream::pair().unwrap();
    let sender = pinned(left);
    drop(right);
    let (offered, mut peer) = UnixStream::pair().unwrap();
    assert!(sender.send_one_descriptor(offered.into()).is_err());
    peer.set_read_timeout(Some(Duration::from_secs(1))).unwrap();
    assert_eq!(peer.read(&mut [0]).unwrap(), 0);
}
