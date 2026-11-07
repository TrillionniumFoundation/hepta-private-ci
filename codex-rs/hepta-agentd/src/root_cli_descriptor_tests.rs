//! Inherited FD ownership in the actual Root binary's parser.

use super::inherited_descriptor;
use pretty_assertions::assert_eq;
use std::collections::BTreeSet;
use std::ffi::OsStr;
use std::io::Read;
use std::os::fd::AsRawFd;
use std::os::fd::IntoRawFd;
use std::os::unix::net::UnixStream;
use std::time::Duration;

#[test]
fn root_cli_claims_one_original_fd_and_rejects_repeated_slots() {
    let (offered, mut peer) = UnixStream::pair().unwrap();
    let raw = offered.into_raw_fd();
    let number = raw.to_string();
    let mut claimed = BTreeSet::new();
    let owned = inherited_descriptor(OsStr::new(&number), &mut claimed).unwrap();
    assert_eq!(owned.as_raw_fd(), raw);
    assert!(inherited_descriptor(OsStr::new(&number), &mut claimed).is_err());
    // SAFETY: the descriptor remains owned and live until after the flags read.
    assert_ne!(
        unsafe { libc::fcntl(raw, libc::F_GETFD) } & libc::FD_CLOEXEC,
        0
    );
    drop(owned);
    peer.set_read_timeout(Some(Duration::from_secs(1))).unwrap();
    assert_eq!(
        peer.read(&mut [0]).unwrap(),
        0,
        "no unowned original endpoint remains open"
    );
}

#[test]
fn root_cli_rejects_standard_and_absent_descriptors_before_any_open() {
    for number in ["0", "1", "2", "2147483647"] {
        assert!(inherited_descriptor(OsStr::new(number), &mut BTreeSet::new()).is_err());
    }
}
