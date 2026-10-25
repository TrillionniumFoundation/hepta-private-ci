//! Real anonymous descriptor transport; no Root authority or native role exists.

use super::*;
use pretty_assertions::assert_eq;
use std::io::Read;
use std::io::Write;
use std::os::unix::net::UnixStream;

#[test]
fn ordered_descriptor_frame_preserves_open_objects_and_sets_cloexec() {
    let (parent, child) = UnixDatagram::pair().unwrap();
    let mut first = tempfile::tempfile().unwrap();
    let mut second = tempfile::tempfile().unwrap();
    first.write_all(b"first").unwrap();
    second.write_all(b"second").unwrap();
    send_packet(&parent, FRAME, &[first.as_raw_fd(), second.as_raw_fd()], Duration::from_secs(1)).unwrap();
    let (first_received, second_received) = receive_packet(&child, Duration::from_secs(1)).unwrap();
    use std::os::unix::fs::MetadataExt;
    assert_eq!(first_received.metadata().unwrap().ino(), first.metadata().unwrap().ino());
    assert_eq!(File::from(second_received.try_clone().unwrap()).metadata().unwrap().ino(), second.metadata().unwrap().ino());
    for fd in [first_received.as_raw_fd(), second_received.as_raw_fd()] {
        // SAFETY: the two received descriptors are still owned and live.
        assert_ne!(unsafe { libc::fcntl(fd, libc::F_GETFD) } & libc::FD_CLOEXEC, 0);
    }
    assert!(validate_bootstrap(&first_received).is_err(), "transport shape cannot substitute sealed Root provenance");
    assert!(require_root_pin(&second_received, std::process::id()).is_err());
}

#[test]
fn malformed_marker_or_extra_right_closes_all_received_streams() {
    for extra in [false, true] {
        let (parent, child) = UnixDatagram::pair().unwrap();
        let mut peers = Vec::new();
        let mut offered = Vec::new();
        for _ in 0..if extra { 3 } else { 2 } {
            let (one, peer) = UnixStream::pair().unwrap();
            offered.push(one);
            peers.push(peer);
        }
        let fds = offered.iter().map(AsRawFd::as_raw_fd).collect::<Vec<_>>();
        send_packet(&parent, if extra { FRAME } else { b"wrong marker" }, &fds, Duration::from_secs(1)).unwrap();
        drop(offered);
        assert!(receive_packet(&child, Duration::from_secs(1)).is_err());
        for mut peer in peers {
            peer.set_read_timeout(Some(Duration::from_secs(1))).unwrap();
            assert_eq!(peer.read(&mut [0]).unwrap(), 0, "all received rights must close on refusal");
        }
    }
}

#[test]
fn named_socket_or_invalid_deadline_is_not_an_inherited_root_handoff() {
    let directory = tempfile::tempdir().unwrap();
    let one = UnixDatagram::bind(directory.path().join("one")).unwrap();
    let two = UnixDatagram::bind(directory.path().join("two")).unwrap();
    one.connect(directory.path().join("two")).unwrap();
    two.connect(directory.path().join("one")).unwrap();
    assert!(root_pair(&one, Duration::from_secs(1)).is_err());
    let (one, _two) = UnixDatagram::pair().unwrap();
    assert!(root_pair(&one, Duration::ZERO).is_err());
    assert!(root_pair(&one, Duration::from_secs(31)).is_err());
}
