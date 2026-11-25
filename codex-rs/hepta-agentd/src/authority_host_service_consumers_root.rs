//! Explicit root-only fixture bootstrap of the two original frontiers.
use super::*;
use pretty_assertions::assert_eq;
use std::os::fd::AsRawFd;
use std::os::unix::process::CommandExt;

#[path = "authority_host_service_bootstrap_root.rs"]
mod bootstrap;

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

pub(super) fn initialize(config: &mut HostAuthorityServiceConfig) {
    let (clock, _leases, issuer) = open_registered_issuer(config).unwrap();
    initialize_with_owner(config, clock, issuer.as_ref());
}

/// Reuse the fixture's already-held canonical owner. A second registry open
/// must keep failing its exclusive lock; initialization is not a lock reset.
pub(super) fn initialize_with_owner(
    config: &mut HostAuthorityServiceConfig,
    clock: Arc<codex_hepta_contracts::HostAuthorityClock>,
    issuer: &crate::DeploymentFinalUseIssuer,
) {
    let key = issuer.trust_key().unwrap();
    assert_eq!(key.key_id, config.signer_id);
    assert_eq!(key.verifying_key, config.expected_verifying_key);
    let writer = config.writer.as_ref().unwrap();
    let head = issuer.revocations().unwrap();
    let device = HostAuthorityConsumerConfig {
        state_dir: config.state_dir.join("device-consumer"),
        owner_id: config.signer_id.clone(),
    };
    let notes = HostAuthorityConsumerConfig {
        state_dir: config.state_dir.join("notes-consumer"),
        owner_id: config.signer_id.clone(),
    };
    for slot in [&device, &notes] {
        std::fs::DirBuilder::new()
            .mode(0o700)
            .create(&slot.state_dir)
            .unwrap();
    }
    std::fs::File::open(&config.state_dir)
        .unwrap()
        .sync_all()
        .unwrap();
    for slot in [&device, &notes] {
        crate::HostConsumerFrontier::initialize_fresh(
            RootAuthorityDirectory::open(&slot.state_dir).unwrap(),
            slot.owner_id.clone(),
            &head,
            clock.clone(),
            writer.authority_lease.expires_at_unix_ms,
        )
        .unwrap();
    }
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
    // The mode02710 runtime passes SGID to subdirectories even with mode0700.
    // Directory chown preserves it; satisfy the original exact-mode contract.
    std::fs::set_permissions(&local, std::fs::Permissions::from_mode(0o700)).unwrap();
}

pub(super) fn release(
    child: &mut std::process::Child,
    config: &HostAuthorityServiceConfig,
    registration: &HostAuthorityRegistration,
    preheld_host_pidfd: &std::os::fd::OwnedFd,
) -> Option<HostAuthorityService> {
    let captured = config.consumers.as_ref().map(|_| {
        let (service, bundle) = bootstrap::capture(
            config,
            registration,
            preheld_host_pidfd.try_clone().unwrap(),
        );
        let mut sealed = crate::seal_host_authority_bootstrap(&bundle).unwrap();
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
        (service, bytes)
    });
    let mut stdin = child.stdin.take().unwrap();
    stdin.write_all(&[1]).unwrap();
    if let Some((_, bytes)) = &captured {
        // Component fixture only: copy the actual producer's sealed bytes to
        // stdin. Production transfers the sealed File itself, never this pipe.
        stdin
            .write_all(&(bytes.len() as u32).to_be_bytes())
            .unwrap();
        stdin.write_all(bytes).unwrap();
    }
    captured.map(|(service, _)| service)
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
