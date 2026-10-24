//! Actual Linux Root process tests. The installed sleep ELF is a process/FD
//! probe, not a Hepta role, native kernel grant, writer or recovery qualification.
use super::*;
use crate::ROOT_NOTES_HOST_CONFIG_OPERATION_V1;
use crate::RootNotesAgentPathsV1;
use crate::RootNotesAuthBusPathsV1;
use crate::RootNotesInstalledBindingsV1;
use crate::RootNotesInstalledBundleV1;
use crate::RootNotesLaunchEndpointV1;
use codex_hepta_contracts::AgentId;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use pretty_assertions::assert_eq;
use std::collections::BTreeSet;
use std::os::fd::AsRawFd;
use std::os::fd::FromRawFd;
use std::os::unix::fs::PermissionsExt;
use std::os::unix::net::UnixDatagram;
use std::os::unix::process::ExitStatusExt;

struct Fixture {
    root: tempfile::TempDir,
    executable: PathBuf,
    config: RootNotesHostConfigV1,
}

fn private_directory(path: &Path, uid: u32) {
    std::fs::create_dir(path).unwrap();
    std::fs::set_permissions(path, std::fs::Permissions::from_mode(0o700)).unwrap();
    let name = CString::new(path.as_os_str().as_bytes()).unwrap();
    // SAFETY: this test owns the freshly created directory and is actual Root.
    assert_eq!(unsafe { libc::chown(name.as_ptr(), uid, uid) }, 0);
}

impl Fixture {
    fn new() -> Self {
        require_root().expect("this ignored parent must run under actual Root");
        // Runtime sockets may live on noexec /run; the actual installed ELF
        // belongs in the separately provisioned Root-owned exec namespace.
        let installed = PathBuf::from(
            std::env::var_os("HEPTA_TEST_ROOT_OWNER_INSTALL_DESTINATION")
                .expect("Root0:0 mode0711 executable installation parent is required"),
        );
        require_path(&installed).expect("normalized absolute Root installation parent");
        let metadata = std::fs::symlink_metadata(&installed).unwrap();
        assert!(metadata.is_dir());
        assert_eq!(
            (metadata.uid(), metadata.gid(), metadata.mode() & 0o7777),
            (0, 0, 0o711)
        );
        for ancestor in installed.ancestors() {
            let entry = std::fs::symlink_metadata(ancestor).unwrap();
            assert!(
                entry.is_dir()
                    && entry.uid() == 0
                    && entry.mode() & 0o022 == 0
                    && entry.mode() & 0o001 != 0,
                "installed role ancestor must be Root-owned, non-writable and searchable: {}",
                ancestor.display()
            );
        }
        let root = tempfile::Builder::new()
            .prefix("hepta-role-launch-")
            .tempdir_in(&installed)
            .unwrap();
        std::fs::set_permissions(root.path(), std::fs::Permissions::from_mode(0o755)).unwrap();
        let home = root.path().join("home");
        private_directory(&home, /*uid*/ 60001);
        let executable = root.path().join("installed-role");
        std::fs::copy("/usr/bin/sleep", &executable).unwrap();
        std::fs::set_permissions(&executable, std::fs::Permissions::from_mode(0o555)).unwrap();
        let digest = Digest32::of_bytes(b"explicit launch fixture, no installed Hepta authority");
        let config = RootNotesHostConfigV1 {
            schema_version: 1,
            operation: ROOT_NOTES_HOST_CONFIG_OPERATION_V1.into(),
            root: process::capture(std::process::id() as i32, /*uid*/ 0).unwrap(),
            launch: RootNotesLaunchEndpointV1 {
                socket_path: root.path().join("launch"),
                wait_lifetime_ms: 10_000,
            },
            agent: RootNotesAgentPathsV1 {
                fleet_root: root.path().join("fleet"),
                agent_id: AgentId::parse("01234567-89ab-4cde-8fab-0123456789ab").unwrap(),
                spawn_generation: 1,
                home_root: home.clone(),
                run_root: root.path().join("run"),
                codex_home: home.clone(),
                workspace: root.path().join("workspace"),
            },
            authbus: RootNotesAuthBusPathsV1 {
                trust_file: home.join("trust.json"),
                checkpoint_file: root.path().join("checkpoint.json"),
                objective_profile_file: home.join("objective.json"),
            },
            session_peer_config_path: root.path().join("peer.json"),
            installed_bundle: RootNotesInstalledBundleV1 {
                manifest_path: root.path().join("bundle.json"),
                manifest_sha256: digest,
                bindings: RootNotesInstalledBindingsV1 {
                    principal_scope_digest: digest,
                    policy_generation: Generation::new(1).unwrap(),
                    locale: "zh-CN".into(),
                    runtime_body_digest: digest,
                    preference_state_digest: digest,
                    model_tuple_digest: digest,
                    prompt_registry_digest: digest,
                    artifact_set_digest: digest,
                },
            },
            deployment: RootNotesDeploymentV1::NotesOnly {},
        };
        Self {
            root,
            executable,
            config,
        }
    }

    fn launch(&self, seconds: &str) -> io::Result<RootRoleChild> {
        let executable = RootRoleExecutable::open(&self.executable)?;
        // SAFETY: opens the pidfd of this current, live Root test parent.
        let raw = unsafe { libc::syscall(libc::SYS_pidfd_open, std::process::id(), 0) };
        assert!(raw >= 0, "{}", io::Error::last_os_error());
        // SAFETY: successful pidfd_open returned a new descriptor owned here.
        let root_pidfd = unsafe { OwnedFd::from_raw_fd(raw as i32) };
        spawn_root_notes_host(
            &executable,
            &[seconds.into()],
            seal_root_notes_host_config(&self.config)?,
            root_pidfd,
            process::now()? + 10_000_000_000,
        )
    }
}

fn children() -> BTreeSet<u32> {
    // SAFETY: gettid reads only the calling test thread's kernel identity.
    let tid = unsafe { libc::syscall(libc::SYS_gettid) };
    std::fs::read_to_string(format!("/proc/self/task/{tid}/children"))
        .unwrap()
        .split_whitespace()
        .map(|value| value.parse().unwrap())
        .collect()
}

fn assert_reaped(pid: u32) {
    let mut status = 0;
    // SAFETY: WNOHANG cannot wait indefinitely; the launcher should have reaped.
    assert_eq!(
        unsafe { libc::waitpid(pid as i32, &mut status, libc::WNOHANG) },
        -1
    );
    assert_eq!(
        io::Error::last_os_error().raw_os_error(),
        Some(libc::ECHILD)
    );
}

#[test]
#[ignore = "actual Root fixed UID exec, descriptor isolation and child reaping"]
fn root_host_exec_keeps_only_fixed_descriptors_and_reaps_normal_exit() {
    let fixture = Fixture::new();
    let before = children();
    let source = File::open("/dev/null").unwrap();
    // Deliberately open a non-CLOEXEC descriptor above the role's entire map.
    // SAFETY: F_DUPFD returns a fresh descriptor owned only by this test.
    let raw = unsafe { libc::fcntl(source.as_raw_fd(), libc::F_DUPFD, 80) };
    assert!(raw >= 80);
    let _inheritable = unsafe { OwnedFd::from_raw_fd(raw) };
    let mut child = fixture.launch("2").unwrap();
    let pid = child.peer().pid;
    assert_eq!(child.peer().uid, 60001);
    child.check_alive().unwrap();
    let deadline = std::time::Instant::now() + Duration::from_secs(1);
    loop {
        let fds: BTreeSet<u32> = std::fs::read_dir(format!("/proc/{pid}/fd"))
            .unwrap()
            .map(|entry| {
                entry
                    .unwrap()
                    .file_name()
                    .to_str()
                    .unwrap()
                    .parse()
                    .unwrap()
            })
            .collect();
        if fds == BTreeSet::from([0, 1, 2, 3]) {
            break;
        }
        assert!(
            std::time::Instant::now() < deadline,
            "unexpected inherited descriptors {fds:?}"
        );
        std::thread::sleep(Duration::from_millis(5));
    }
    for fd in [1, 2] {
        assert_eq!(
            std::fs::read_link(format!("/proc/{pid}/fd/{fd}")).unwrap(),
            PathBuf::from("/dev/null")
        );
    }
    assert_eq!(
        std::fs::read_link(format!("/proc/{pid}/fd/3")).unwrap(),
        PathBuf::from("anon_inode:[pidfd]")
    );
    let actual = std::fs::read(format!("/proc/{pid}/fd/0")).unwrap();
    assert_eq!(actual, serde_json::to_vec(&fixture.config).unwrap());
    let environment = std::fs::read(format!("/proc/{pid}/environ")).unwrap();
    let mut environment = environment
        .split(|byte| *byte == 0)
        .filter(|entry| !entry.is_empty())
        .map(|entry| String::from_utf8(entry.to_vec()).unwrap())
        .collect::<Vec<_>>();
    environment.sort();
    assert_eq!(
        environment,
        vec![
            format!("CODEX_HOME={}", fixture.config.agent.home_root.display()),
            format!("HOME={}", fixture.config.agent.home_root.display()),
            "PATH=/usr/bin:/bin".into(),
        ]
    );
    assert!(
        child
            .wait_until(process::now().unwrap() + 5_000_000_000)
            .unwrap()
            .success()
    );
    assert_reaped(pid);
    assert_eq!(children(), before);
}

#[test]
#[ignore = "actual Root timeout must kill and reap the owned UID60001 process"]
fn root_host_deadline_kills_and_reaps_before_returning_timeout() {
    let fixture = Fixture::new();
    let before = children();
    let mut child = fixture.launch("60").unwrap();
    let pid = child.peer().pid;
    let error = child
        .wait_until(process::now().unwrap() + 100_000_000)
        .unwrap_err();
    assert_eq!(error.kind(), io::ErrorKind::TimedOut);
    assert_eq!(
        child.try_wait().unwrap().unwrap().signal(),
        Some(libc::SIGKILL)
    );
    assert_reaped(pid);
    assert_eq!(children(), before);
}

#[test]
#[ignore = "actual Root guard drop must kill and reap its owned process"]
fn root_host_guard_drop_does_not_leave_a_running_child() {
    let fixture = Fixture::new();
    let before = children();
    let child = fixture.launch("60").unwrap();
    let pid = child.peer().pid;
    drop(child);
    assert_reaped(pid);
    assert_eq!(children(), before);
}

#[test]
#[ignore = "actual Root execveat failure after fixed descriptor remapping"]
fn root_exec_error_pipe_survives_role_fd_mapping_and_reaps_failed_child() {
    let fixture = Fixture::new();
    let before = children();
    let mut bytes = std::fs::read(&fixture.executable).unwrap();
    let table = u64::from_le_bytes(bytes[32..40].try_into().unwrap()) as usize;
    let count = u16::from_le_bytes(bytes[56..58].try_into().unwrap()) as usize;
    let mut changed = false;
    for index in 0..count {
        let offset = table + index * 56;
        if u32::from_le_bytes(bytes[offset..offset + 4].try_into().unwrap()) != 3 {
            continue;
        }
        let start = u64::from_le_bytes(bytes[offset + 8..offset + 16].try_into().unwrap()) as usize;
        let size = u64::from_le_bytes(bytes[offset + 32..offset + 40].try_into().unwrap()) as usize;
        let absent = b"/hepta-no-such-loader\0";
        assert!(size >= absent.len());
        bytes[start..start + size].fill(0);
        bytes[start..start + absent.len()].copy_from_slice(absent);
        changed = true;
    }
    assert!(
        changed,
        "the installed Linux probe must have its actual dynamic interpreter"
    );
    std::fs::write(&fixture.executable, bytes).unwrap();
    let error = fixture
        .launch("60")
        .err()
        .expect("the actual loader must be absent");
    assert_eq!(error.raw_os_error(), Some(libc::ENOENT));
    assert_eq!(children(), before);
}

#[test]
#[ignore = "actual Root rejects Session descriptors created by the wrong process"]
fn root_session_refuses_foreign_socket_peers_without_spawning() {
    let fixture = Fixture::new();
    let host = fixture.launch("60").unwrap();
    let before = children();
    let home = fixture.root.path().join("session-home");
    let runtime = fixture.root.path().join("session-run");
    private_directory(&home, /*uid*/ 1000);
    private_directory(&runtime, /*uid*/ 1000);
    let (first, _first_peer) = UnixDatagram::pair().unwrap();
    let (second, _second_peer) = UnixDatagram::pair().unwrap();
    let executable = RootRoleExecutable::open(&fixture.executable).unwrap();
    let error = spawn_root_notes_session(
        &executable,
        &["60".into()],
        &host,
        [first.into(), second.into()],
        RootSessionEnvironment {
            home,
            runtime_dir: runtime,
            display: None,
            wayland_display: None,
            xauthority: None,
            dbus_session_bus_address: None,
        },
        process::now().unwrap() + 5_000_000_000,
    )
    .err()
    .expect("Root-created sockets do not belong to the actual Host");
    assert!(
        error
            .to_string()
            .contains("Session channels must originate")
    );
    assert_eq!(children(), before);
    host.check_alive().unwrap();
}
