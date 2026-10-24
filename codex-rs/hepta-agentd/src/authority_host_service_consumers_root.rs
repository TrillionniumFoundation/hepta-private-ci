//! Explicit root-only fixture bootstrap of the two original frontiers.
use super::*;
use pretty_assertions::assert_eq;
use std::os::fd::AsRawFd;
use std::os::unix::process::CommandExt;

pub(super) fn root_peer_fd(command: &mut Command) -> std::os::fd::OwnedFd {
    // SAFETY: pidfd_open has no borrowed memory and pins this actual root
    // process before the dedicated child exists or receives a stream.
    let raw = unsafe { libc::syscall(libc::SYS_pidfd_open, std::process::id(), 0) };
    assert!(raw >= 0);
    // SAFETY: successful pidfd_open returns one fresh owned descriptor.
    let fd = unsafe { std::os::fd::OwnedFd::from_raw_fd(raw as i32) };
    let raw = fd.as_raw_fd();
    command.env("HEPTA_SERVICE_ROOT_PIDFD", "198");
    // SAFETY: the post-fork closure only duplicates one already held pidfd and
    // adjusts its descriptor flag with async-signal-safe libc operations.
    unsafe {
        command.pre_exec(move || {
            if libc::dup2(raw, 198) < 0 || libc::fcntl(198, libc::F_SETFD, 0) < 0 {
                return Err(std::io::Error::last_os_error());
            }
            Ok(())
        });
    }
    fd
}

pub(super) fn configure(config: &mut HostAuthorityServiceConfig) {
    let device = HostAuthorityConsumerConfig {
        state_dir: config.state_dir.join("device-consumer"),
        owner_id: config.signer_id.clone(),
    };
    let notes = HostAuthorityConsumerConfig {
        state_dir: config.state_dir.join("notes-consumer"),
        owner_id: config.signer_id.clone(),
    };
    let runtime = config.sockets.observation.parent().unwrap();
    config.sockets.device_frontier = Some(runtime.join("device-frontier.sock"));
    config.sockets.notes_frontier = Some(runtime.join("notes-frontier.sock"));
    config.consumers = Some(HostAuthorityConsumersConfig { device, notes });
}

pub(super) fn create_local(runtime: &Path) {
    let local = runtime.join("consumer-local");
    std::fs::DirBuilder::new()
        .mode(0o700)
        .create(&local)
        .unwrap();
    let path = std::ffi::CString::new(local.as_os_str().as_encoded_bytes()).unwrap();
    // SAFETY: root-created, NUL-free fixture directory; no caller pointer remains.
    assert_eq!(unsafe { libc::chown(path.as_ptr(), 60001, 60001) }, 0);
}

pub(super) fn release(
    child: &mut std::process::Child,
    config: &HostAuthorityServiceConfig,
    config_path: &Path,
    registration_path: &Path,
    owner_pidfd: &OwnedFd,
    prepared: &crate::PreparedHostAuthoritySession,
    expected: Option<crate::HostAuthorityPublicBootstrapV1>,
) {
    let bytes = config.consumers.as_ref().map(|_| {
        let local = config
            .sockets
            .observation
            .parent()
            .unwrap()
            .join("consumer-local");
        // Keep the test-only capture as a readback oracle, never as input to
        // the production capture API or the descriptor delivered below.
        let bundle = expected
            .as_ref()
            .expect("independent prior readback required");
        let mut wrong = config.clone();
        wrong.peer_gid += 1;
        let wrong_path = config_path.with_extension("bootstrap-wrong-gid.json");
        write_json(&wrong_path, &wrong);
        assert!(
            crate::PreparedHostAuthoritySession::open(
                &wrong_path,
                registration_path,
                owner_pidfd.try_clone().unwrap()
            )
            .err()
            .expect("same UID with different expected GID must be refused")
            .to_string()
            .contains("UID/GID")
        );
        // SAFETY: this pins the actual Root solely as a deliberately wrong
        // daemon descriptor. It never changes credentials or selects a peer.
        let raw = unsafe { libc::syscall(libc::SYS_pidfd_open, std::process::id(), 0) };
        assert!(raw >= 0);
        // SAFETY: successful pidfd_open transfers one fresh owned descriptor.
        let wrong_pidfd = unsafe { OwnedFd::from_raw_fd(raw as i32) };
        assert!(
            crate::PreparedHostAuthoritySession::open(config_path, registration_path, wrong_pidfd)
                .err()
                .expect("wrong original pidfd must be refused")
                .to_string()
                .contains("pidfd does not pin")
        );
        // These exercise the retained capture directly, so a second owner's
        // StateLocked error cannot mask the exact runtime-custody refusal.
        let runtime = config.sockets.observation.parent().unwrap();
        std::fs::set_permissions(runtime, std::fs::Permissions::from_mode(0o2730)).unwrap();
        let invalid_mode = prepared.seal_bootstrap(&local);
        std::fs::set_permissions(runtime, std::fs::Permissions::from_mode(0o2710)).unwrap();
        assert_eq!(
            invalid_mode.unwrap_err().to_string(),
            "private runtime parent must be root:peer-gid mode02710"
        );
        let runtime_c = std::ffi::CString::new(runtime.as_os_str().as_encoded_bytes()).unwrap();
        // SAFETY: the test owns this actual Root-created runtime directory.
        assert_eq!(
            unsafe {
                libc::chown(runtime_c.as_ptr(), /*owner*/ 0, config.peer_gid + 1)
            },
            0
        );
        let invalid_group = prepared.seal_bootstrap(&local);
        // SAFETY: restore the original group before any assertion can unwind.
        assert_eq!(
            unsafe {
                libc::chown(runtime_c.as_ptr(), /*owner*/ 0, config.peer_gid)
            },
            0
        );
        std::fs::set_permissions(runtime, std::fs::Permissions::from_mode(0o2710)).unwrap();
        assert_eq!(
            invalid_group.unwrap_err().to_string(),
            "private runtime parent must be root:peer-gid mode02710"
        );
        let ancestor = runtime.parent().unwrap();
        std::fs::set_permissions(ancestor, std::fs::Permissions::from_mode(0o775)).unwrap();
        let invalid_ancestor = prepared.seal_bootstrap(&local);
        std::fs::set_permissions(ancestor, std::fs::Permissions::from_mode(0o755)).unwrap();
        assert_eq!(
            invalid_ancestor.unwrap_err().to_string(),
            "unsafe runtime ancestor"
        );
        let mut sealed = prepared.seal_bootstrap(&local).unwrap();
        let mut bytes = Vec::new();
        std::io::Read::read_to_end(&mut sealed, &mut bytes).unwrap();
        assert_eq!(bytes, serde_json::to_vec(&bundle).unwrap());
        assert!(bytes.len() <= crate::HOST_AUTHORITY_BOOTSTRAP_BOUND);
        if let Some(path) = std::env::var_os("HEPTA_SERVICE_PUBLIC_BUNDLE_OUT") {
            let mut file = std::fs::OpenOptions::new()
                .write(true)
                .create_new(true)
                .mode(0o600)
                .custom_flags(libc::O_NOFOLLOW | libc::O_CLOEXEC)
                .open(path)
                .unwrap();
            file.write_all(&bytes).unwrap();
        }
        bytes
    });
    let mut stdin = child.stdin.take().unwrap();
    stdin.write_all(&[1]).unwrap();
    if let Some(bytes) = bytes {
        // Component fixture only: copy the actual producer's sealed bytes to
        // stdin. Production transfers the sealed File itself, never this pipe.
        stdin
            .write_all(&(bytes.len() as u32).to_be_bytes())
            .unwrap();
        stdin.write_all(&bytes).unwrap();
    }
}

pub(super) fn assert_final(config: &HostAuthorityServiceConfig, runtime: &Path) {
    let (_, _leases, issuer) = open_registered_issuer(config).unwrap();
    let initial =
        codex_hepta_contracts::FinalUseFrontier::for_initial_head(&issuer.revocations().unwrap())
            .unwrap();
    let expected: [codex_hepta_contracts::FinalUseFrontier; 2] = if expiry_qualification() {
        [initial; 2]
    } else {
        // A source-bound qualification oracle only, never an authority input
        // or recovery witness. Each actual original owner reported frontier().
        let values: [codex_hepta_contracts::FinalUseFrontier; 2] = serde_json::from_slice(
            &std::fs::read(runtime.join("consumer-local/qualified-frontiers.json")).unwrap(),
        )
        .unwrap();
        assert_ne!(values[0], initial);
        assert_ne!(values[1], initial);
        assert_ne!(values[0], values[1]);
        values
    };
    let slots = config.consumers.as_ref().unwrap();
    for (slot, expected) in [&slots.device, &slots.notes].into_iter().zip(expected) {
        let store = codex_hepta_contracts::HostAuthorityFrontierStore::<
            codex_hepta_contracts::FinalUseFrontier,
        >::open(
            RootAuthorityDirectory::open(&slot.state_dir).unwrap(),
            slot.owner_id.clone(),
        )
        .unwrap();
        assert_eq!(store.load(&slot.owner_id).unwrap(), expected);
    }
}
