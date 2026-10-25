use super::*;
use pretty_assertions::assert_eq;
use std::os::fd::FromRawFd;

#[test]
fn ordinary_file_cannot_be_a_pending_root_deployment() {
    assert!(validate_empty_deployment(&tempfile::tempfile().unwrap()).is_err());
}

#[test]
#[ignore = "requires actual Root; execute the user-built test ELF in the isolated Root runner"]
fn original_root_seals_only_empty_private_deployment_and_readonly_consumer_observes_it() {
    // SAFETY: geteuid reads the current process's actual UID.
    assert_eq!(unsafe { libc::geteuid() }, 0);
    // SAFETY: the static name is NUL terminated and success returns a new FD.
    let raw = unsafe { libc::memfd_create(c"hepta-notes-startup-test".as_ptr(),
        libc::MFD_CLOEXEC | libc::MFD_ALLOW_SEALING) };
    assert!(raw >= 0);
    // SAFETY: this adopts exactly the fresh owned descriptor above.
    let file = unsafe { File::from_raw_fd(raw) };
    assert_eq!(unsafe { libc::fchmod(raw, 0o600) }, 0);
    let mut consumer = File::open(format!("/proc/self/fd/{raw}")).unwrap();
    assert!(validate_empty_deployment(&consumer).is_err(), "a read-only consumer cannot be a producer");
    let producer = file.try_clone().unwrap();
    seal_deployment(producer, b"actual sealed payload").unwrap();
    crate::authority_host_bootstrap_seal::validate_sealed(&consumer, 21).unwrap();
    let mut actual = Vec::new();
    consumer.read_to_end(&mut actual).unwrap();
    assert_eq!(actual, b"actual sealed payload");
    assert!(seal_deployment(file, b"replacement").is_err(), "a previous sealed deployment is never reset");
}
