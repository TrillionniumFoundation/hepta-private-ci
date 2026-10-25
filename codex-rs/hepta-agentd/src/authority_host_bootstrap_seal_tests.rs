use super::*;
use pretty_assertions::assert_eq;
use std::os::unix::fs::FileExt;

#[test]
fn non_root_cannot_create_the_bootstrap_descriptor() {
    // SAFETY: geteuid takes no arguments.
    assert_ne!(unsafe { libc::geteuid() }, 0);
    assert_eq!(
        seal_bytes(b"custody-only-test").unwrap_err().kind(),
        io::ErrorKind::PermissionDenied
    );
}

#[test]
fn bounded_encoder_does_not_append_an_oversized_fragment() {
    let mut bytes = BoundedBytes(Vec::new());
    bytes.write_all(b"retained").unwrap();
    let before = bytes.0.clone();
    assert_eq!(
        bytes
            .write_all(&vec![0; HOST_AUTHORITY_BOOTSTRAP_BOUND])
            .unwrap_err()
            .kind(),
        io::ErrorKind::InvalidInput
    );
    assert_eq!(bytes.0, before);
    bytes
        .write_all(&vec![0; HOST_AUTHORITY_BOOTSTRAP_BOUND - before.len()])
        .unwrap();
    assert_eq!(
        bytes.write(b"x").unwrap_err().kind(),
        io::ErrorKind::InvalidInput
    );
    assert_eq!(bytes.0.len(), HOST_AUTHORITY_BOOTSTRAP_BOUND);
}

#[test]
#[ignore = "explicit actual root sealed-memfd custody qualification"]
fn root_descriptor_is_unlinked_sealed_and_never_mutable() {
    // This is descriptor custody only, not a fabricated issuer/proof/cut.
    let bytes = b"custody-only-test";
    let mut file = seal_bytes(bytes).unwrap();
    validate_sealed(&file, bytes.len() as u64).unwrap();
    let mut observed = Vec::new();
    file.read_to_end(&mut observed).unwrap();
    assert_eq!(observed, bytes);
    assert_eq!(
        file.write_at(b"x", 0).unwrap_err().raw_os_error(),
        Some(libc::EPERM)
    );
    assert_eq!(
        file.set_len(0).unwrap_err().raw_os_error(),
        Some(libc::EPERM)
    );
    assert_eq!(
        file.set_len(bytes.len() as u64 + 1)
            .unwrap_err()
            .raw_os_error(),
        Some(libc::EPERM)
    );
    // SAFETY: this is our live sealed descriptor; adding even an empty seal set
    // must fail once F_SEAL_SEAL has irrevocably closed the seal operation.
    assert_eq!(
        unsafe { libc::fcntl(file.as_raw_fd(), libc::F_ADD_SEALS, 0) },
        -1
    );
    assert_eq!(io::Error::last_os_error().raw_os_error(), Some(libc::EPERM));
    file.rewind().unwrap();
    observed.clear();
    file.read_to_end(&mut observed).unwrap();
    assert_eq!(observed, bytes);
    assert_eq!(
        seal_bytes(&vec![0; HOST_AUTHORITY_BOOTSTRAP_BOUND + 1])
            .unwrap_err()
            .kind(),
        io::ErrorKind::InvalidInput
    );
}
