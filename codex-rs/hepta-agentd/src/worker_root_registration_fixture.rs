//! Actual Root factories and dedicated child processes for ignored qualification.
//! No injected clock/verifier, in-memory authority or synthetic pidfd is used.

use super::*;
use crate::HostAuthorityBindIdentity;
use crate::HostAuthorityBootstrap;
use crate::HostAuthorityRegisteredIdentity;
use crate::HostAuthorityRegistration;
use crate::HostAuthorityServiceConfig;
use crate::HostAuthoritySocketPaths;
use crate::HostAuthorityWriterRegistration;
use crate::HostIssuerRecordProfile;
use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::AuthorityClock;
use codex_hepta_contracts::authority_lease::AuthorityLease;
use codex_hepta_contracts::authority_lease::AuthorityLeaseBinding;
use codex_hepta_fleet::AgentLifecycle;
use codex_hepta_fleet::AgentManifest;
use codex_hepta_fleet::ResourceBudget;
use codex_hepta_fleet::WorkspaceBinding;
use codex_hepta_paths::HeptaFleetRoot;
use pretty_assertions::assert_eq;
use std::fs::OpenOptions;
use std::io::Write;
use std::os::fd::AsRawFd;
use std::os::unix::fs::MetadataExt;
use std::os::unix::fs::OpenOptionsExt;
use std::os::unix::fs::PermissionsExt;
use std::os::unix::process::CommandExt;
use std::path::Path;
use std::path::PathBuf;
use std::process::Command;
use std::process::Stdio;

pub(super) struct QualificationChild {
    pub(super) child: Child,
    pub(super) pidfd: OwnedFd,
}

/// Distinct real kernel principals; no payload-selected identity is trusted.
pub(super) enum ChildIdentity {
    Agentd,
    Worker,
    Root,
}

impl QualificationChild {
    pub(super) fn spawn(mode: &str, agent: &AgentId, generation: u64, socket: Option<UnixDatagram>, identity: ChildIdentity) -> Self {
        let program = PathBuf::from(std::env::var_os("HEPTA_WORKER_ROOT_QUALIFICATION_BIN").expect("explicit frozen qualification example required"));
        require_root_file(&program);
        let libraries = PathBuf::from(std::env::var_os("HEPTA_WORKER_ROOT_QUALIFICATION_LIBRARY_PATH").expect("explicit frozen Root-owned library directory required"));
        require_root_directory(&libraries);
        let library_files = std::fs::read_dir(&libraries).unwrap().collect::<Result<Vec<_>, _>>().unwrap();
        assert!((1..=64).contains(&library_files.len()));
        for entry in library_files { require_root_file(&entry.path()); }
        let mut command = match identity {
            ChildIdentity::Agentd | ChildIdentity::Worker => {
            let mut command = Command::new("/usr/bin/setpriv");
            let principal = match identity {
                ChildIdentity::Agentd => "60002",
                ChildIdentity::Worker => "60003",
                ChildIdentity::Root => unreachable!(),
            };
            command.args(["--reuid", principal, "--regid", principal, "--clear-groups", "--no-new-privs", "--inh-caps=-all", "--ambient-caps=-all", "--bounding-set=-all"]).arg(&program);
            command
            }
            ChildIdentity::Root => Command::new(&program),
        };
        command.arg(mode).arg(agent.as_str()).arg(generation.to_string())
            .env_clear().env("PATH", "/usr/bin:/bin")
            .env("LD_LIBRARY_PATH", &libraries)
            .stdin(Stdio::piped()).stdout(Stdio::piped()).stderr(Stdio::inherit());
        if let Some(socket) = socket.as_ref() {
            let raw = socket.as_raw_fd();
            // SAFETY: this closure uses only async-signal-safe FD operations
            // on the retained Root-created socket, before exec of the fixture.
            unsafe {
                command.pre_exec(move || {
                    if libc::dup2(raw, 198) < 0 || libc::fcntl(198, libc::F_SETFD, 0) < 0 {
                        return Err(io::Error::last_os_error());
                    }
                    Ok(())
                });
            }
        }
        let child = command.spawn().unwrap();
        let pidfd = process::pin(child.id()).unwrap();
        let mut result = Self { child, pidfd };
        let stdout = result.child.stdout.as_mut().unwrap();
        readable(stdout.as_raw_fd());
        let mut ready = [0];
        stdout.read_exact(&mut ready).unwrap();
        assert_eq!(ready, *b"R");
        result
    }

    pub(super) fn message(&mut self) -> serde_json::Value {
        let stdout = self.child.stdout.as_mut().unwrap();
        readable(stdout.as_raw_fd());
        let mut length = [0; 4];
        stdout.read_exact(&mut length).unwrap();
        let length = u32::from_be_bytes(length) as usize;
        assert!((1..=64 * 1024).contains(&length));
        let mut bytes = vec![0; length];
        stdout.read_exact(&mut bytes).unwrap();
        serde_json::from_slice(&bytes).unwrap()
    }

    pub(super) fn finish(&mut self) {
        self.child.stdin.take().unwrap().write_all(&[1]).unwrap();
        assert!(self.child.wait().unwrap().success());
    }

    pub(super) fn wait_for_exit(&mut self) {
        assert!(self.child.wait().unwrap().success());
    }
}

fn require_root_directory(path: &Path) {
    assert!(path.is_absolute());
    assert_eq!(path.canonicalize().unwrap(), path);
    for ancestor in path.ancestors() {
        let metadata = std::fs::symlink_metadata(ancestor).unwrap();
        assert!(metadata.is_dir());
        assert_eq!(metadata.uid(), 0);
        assert_eq!(metadata.mode() & 0o022, 0);
    }
}

fn require_root_file(path: &Path) {
    require_root_directory(path.parent().unwrap());
    let metadata = std::fs::symlink_metadata(path).unwrap();
    assert!(metadata.is_file());
    assert_eq!(metadata.uid(), 0);
    assert_eq!(metadata.mode() & 0o022, 0);
    assert_eq!(metadata.nlink(), 1);
}

impl Drop for QualificationChild {
    fn drop(&mut self) {
        if self.child.try_wait().ok().flatten().is_none() {
            // SAFETY: the pidfd was opened while retaining this exact Child.
            // This only kills a still-live owned fixture, never a numeric PID.
            unsafe {
                libc::syscall(libc::SYS_pidfd_send_signal, self.pidfd.as_raw_fd(), libc::SIGKILL, std::ptr::null::<libc::siginfo_t>(), 0);
            }
            let _ = self.child.wait();
        }
    }
}

fn readable(fd: i32) {
    let mut descriptor = libc::pollfd { fd, events: libc::POLLIN, revents: 0 };
    // SAFETY: one initialized descriptor is borrowed only for this bounded poll.
    assert!(unsafe { libc::poll(&mut descriptor, 1, 10_000) } > 0);
}

pub(super) struct Fixture {
    pub(super) registry: FleetRegistry,
    pub(super) identity: HostAuthorityRegisteredIdentity,
    pub(super) session: Option<PreparedHostAuthoritySession>,
    pub(super) config: HostAuthorityServiceConfig,
    pub(super) config_path: PathBuf,
    pub(super) registration_path: PathBuf,
    pub(super) daemon: QualificationChild,
    _directory: tempfile::TempDir,
}

impl Fixture {
    pub(super) fn open() -> Self {
        // SAFETY: read actual kernel identity; this fixture never fakes Root.
        assert_eq!(unsafe { libc::geteuid() }, 0);
        let parent = PathBuf::from(std::env::var_os("HEPTA_HOST_AUTHORITY_QUALIFICATION_STATE_PARENT").unwrap());
        let source = PathBuf::from(std::env::var_os("HEPTA_HOST_AUTHORITY_QUALIFICATION_SOURCE").unwrap());
        let directory = tempfile::Builder::new().prefix("worker-registration-").tempdir_in(&parent).unwrap();
        std::fs::set_permissions(directory.path(), std::fs::Permissions::from_mode(0o700)).unwrap();
        let workspace = directory.path().join("workspace");
        std::fs::create_dir(&workspace).unwrap();
        let fleet = HeptaFleetRoot::parse(directory.path().join("fleet")).unwrap();
        let registry = FleetRegistry::initialize(fleet.clone()).unwrap();
        let agent = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12").unwrap();
        registry.register(AgentManifest::new(agent.clone(), WorkspaceBinding::new(workspace.clone(), &fleet).unwrap(), ResourceBudget::local_default()).unwrap()).unwrap();
        let starting = registry.compare_and_transition(&agent, 0, AgentLifecycle::Starting).unwrap();
        let identity = HostAuthorityRegisteredIdentity { agent_id: agent.clone(), spawn_generation: starting.generation, fleet_root: fleet.as_path().to_owned(), workspace, resources: ResourceBudget::local_default() };
        let meta = std::fs::metadata(&parent).unwrap();
        let bind = HostAuthorityBindIdentity { mountpoint: parent, source_path: source, device: meta.dev(), inode: meta.ino() };
        let bootstrap_path = directory.path().join("bootstrap.json");
        write_json(&bootstrap_path, &HostAuthorityBootstrap {
            schema_version: 1, required_bind: bind.clone(), signer_id: "worker-registration-root-qualification".into(),
            policies: vec![crate::DeploymentGrantPolicy { subject_id: agent.to_string(), destination_id: "qualification.worker.no-effect".into(), scope_sha256: [2; 32], lifetime_ms: 1000 }],
            lease_id: "worker-registration-issuer".into(),
            lease_binding: AuthorityLeaseBinding { principal_id: agent.to_string(), operation_class: "runtime.agentd.production_operation".into(), destination_id: "qualification.worker.no-effect".into(), scope_sha256: [2; 32], payload_sha256: [3; 32] },
            lease_lifetime_ms: 60000,
        });
        let state = directory.path().join("authority");
        let initialized = crate::initialize_host_authority(&state, &bootstrap_path).unwrap();
        assert!(!initialized.production_ready);
        let daemon = QualificationChild::spawn("owner", &agent, starting.generation, /*socket*/ None, ChildIdentity::Agentd);
        let actual = process::observe(daemon.child.id()).unwrap();
        let registration = HostAuthorityRegistration { schema_version: 1, peer_pid: actual.pid, boot_id: actual.boot_id, process_start_ticks: actual.process_start_ticks, registered_identity: identity.clone(), checkpoint_owner_agent_id: agent.clone(), publisher_epoch: 1 };
        let mut config = HostAuthorityServiceConfig {
            schema_version: 1, state_dir: state, required_bind: bind, signer_id: initialized.signer_id, expected_verifying_key: initialized.verifying_key,
            lease_id: initialized.lease_id, lease_revision: initialized.lease_revision, writer: None, checkpoint_state_dir: None, consumers: None,
            sockets: HostAuthoritySocketPaths { observation: directory.path().join("unused-observation"), issuer: directory.path().join("unused-issuer"), checkpoint: directory.path().join("unused-checkpoint"), device_frontier: None, notes_frontier: None },
            peer_uid: actual.uid, peer_gid: actual.gid, timeout_ms: 10000, lifetime_ms: 20000, issuer_record_profile: HostIssuerRecordProfile::Standard,
        };
        let now = {
            let (clock, _leases, _issuer) = crate::authority_host_runtime::open_registered_issuer(&config).unwrap();
            clock.now_unix_ms().unwrap()
        };
        config.writer = Some(HostAuthorityWriterRegistration {
            registered_agent_id: agent.clone(), spawn_generation: starting.generation, owner_epoch: 1, local_lease_id: "worker-registration-original-writer".into(), local_lease_generation: 1,
            authority_lease: AuthorityLease { schema_version: 1, lease_id: "worker-registration-writer".into(), authority_epoch: 1, revision: 1,
                binding: AuthorityLeaseBinding { principal_id: agent.to_string(), operation_class: "runtime.agentd.production_writer".into(), destination_id: "qualification.worker.original-cognitive-owner".into(), scope_sha256: [6; 32], payload_sha256: [7; 32] },
                issued_at_unix_ms: now, expires_at_unix_ms: now + 60000 },
        });
        let config_path = directory.path().join("service.json");
        let registration_path = directory.path().join("registered-daemon.json");
        write_json(&config_path, &config);
        write_json(&registration_path, &registration);
        crate::register_host_writer_authorization(&config_path).unwrap();
        let session = PreparedHostAuthoritySession::open(&config_path, &registration_path, daemon.pidfd.try_clone().unwrap()).unwrap();
        Self { registry, identity, session: Some(session), config, config_path, registration_path, daemon, _directory: directory }
    }
}

fn write_json(path: &Path, value: &impl serde::Serialize) {
    let mut file = OpenOptions::new().write(true).create_new(true).mode(0o600).custom_flags(libc::O_NOFOLLOW | libc::O_CLOEXEC).open(path).unwrap();
    serde_json::to_writer(&mut file, value).unwrap();
    file.flush().unwrap();
    file.sync_all().unwrap();
    File::open(path.parent().unwrap()).unwrap().sync_all().unwrap();
}
