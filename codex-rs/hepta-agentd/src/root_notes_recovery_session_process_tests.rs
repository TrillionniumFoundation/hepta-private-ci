//! Owned companion processes for the explicit Root/Session component tests.
//! No activation, application descriptor receipt, input or effect is sent.
use super::*;
use pretty_assertions::assert_eq;
use std::os::unix::process::CommandExt;

pub(super) struct ActualSession {
    child: Child,
    pub(super) pidfd: OwnedFd,
    pub(super) channel: UnixDatagram,
    pub(super) reserved: serde_json::Value,
    pub(super) birth: serde_json::Value,
    pub(super) binaries: serde_json::Value,
    pub(super) app_pid: u32,
    app_pidfd: Option<OwnedFd>,
    _runtime: tempfile::TempDir,
}

pub(super) fn pidfd(child: &Child) -> OwnedFd {
    // SAFETY: this PID comes from the still-retained child created by this test.
    let raw = unsafe { libc::syscall(libc::SYS_pidfd_open, child.id(), 0) };
    assert!(raw >= 0);
    // SAFETY: successful pidfd_open returned one new owned descriptor.
    unsafe { OwnedFd::from_raw_fd(raw as i32) }
}

pub(super) fn peer_directory(path: &Path) {
    std::fs::create_dir(path).unwrap();
    let file = File::open(path).unwrap();
    // SAFETY: the descriptor pins only this newly created test directory.
    assert_eq!(unsafe { libc::fchown(file.as_raw_fd(), 60001, 60001) }, 0);
    std::fs::set_permissions(path, std::fs::Permissions::from_mode(0o700)).unwrap();
}

impl ActualSession {
    pub(super) fn spawn(label: &str) -> Self {
        assert_eq!(
            std::env::var("HEPTA_NOTES_SESSION_ISOLATED").as_deref(),
            Ok("1")
        );
        let binary = PathBuf::from(std::env::var_os("HEPTA_NOTES_SESSION_BIN").unwrap());
        assert!(binary.is_absolute());
        assert_eq!(binary.canonicalize().unwrap(), binary);
        let app = binary.with_file_name("trill-app-window");
        let mut binaries = serde_json::Map::new();
        for (path, pin) in [
            (&binary, "HEPTA_NOTES_SESSION_SHA256"),
            (&app, "HEPTA_NOTES_APP_SHA256"),
        ] {
            let metadata = std::fs::symlink_metadata(path).unwrap();
            assert!(metadata.is_file());
            assert_eq!(
                (metadata.uid(), metadata.nlink(), metadata.mode() & 0o7777),
                (0, 1, 0o555)
            );
            let digest = Sha256Digest::for_bytes(&std::fs::read(path).unwrap());
            assert_eq!(digest.as_str(), std::env::var(pin).unwrap());
            binaries.insert(
                path.file_name().unwrap().to_str().unwrap().into(),
                serde_json::json!({"sha256":digest.as_str(),"bytes":metadata.len()}),
            );
        }
        let parent = PathBuf::from(std::env::var_os("HEPTA_NOTES_SESSION_RUNTIME_ROOT").unwrap());
        assert_eq!(parent.canonicalize().unwrap(), parent);
        let metadata = std::fs::symlink_metadata(&parent).unwrap();
        assert_eq!((metadata.uid(), metadata.mode() & 0o7777), (0, 0o711));
        let runtime = tempfile::tempdir_in(parent).unwrap();
        let file = File::open(runtime.path()).unwrap();
        // SAFETY: only this newly created private fixture directory is changed.
        assert_eq!(unsafe { libc::fchown(file.as_raw_fd(), 60001, 60001) }, 0);
        std::fs::set_permissions(runtime.path(), std::fs::Permissions::from_mode(0o700)).unwrap();
        let state = runtime.path().join("state");
        peer_directory(&state);
        let log = std::fs::OpenOptions::new()
            .create_new(true)
            .write(true)
            .mode(0o600)
            .open(output().join(format!("{label}.session.log")))
            .unwrap();
        let (channel, child_channel) = UnixDatagram::pair().unwrap();
        let enabled: libc::c_int = 1;
        // SAFETY: the live Root-created pair and correctly sized option remain
        // retained, and credentials are enabled before any child can send.
        assert_eq!(
            unsafe {
                libc::setsockopt(
                    channel.as_raw_fd(),
                    libc::SOL_SOCKET,
                    libc::SO_PASSCRED,
                    std::ptr::from_ref(&enabled).cast(),
                    std::mem::size_of_val(&enabled) as libc::socklen_t,
                )
            },
            0
        );
        let mut command = Command::new("/usr/bin/setpriv");
        command
            .args([
                "--reuid=60001",
                "--regid=60001",
                "--clear-groups",
                "--bounding-set=-all",
                "--inh-caps=-all",
                "--ambient-caps=-all",
                "--no-new-privs",
            ])
            .arg(&binary)
            .arg("--notes-root-bootstrap-stdin")
            .stdin(Stdio::from(OwnedFd::from(child_channel)))
            .stdout(Stdio::from(log.try_clone().unwrap()))
            .stderr(Stdio::from(log))
            .env_clear()
            .env("PATH", "/usr/bin:/bin")
            .env("HOME", runtime.path())
            .env("XDG_RUNTIME_DIR", runtime.path())
            .env("XDG_STATE_HOME", &state)
            .env("LANG", "C.UTF-8")
            .env("DISPLAY", std::env::var_os("DISPLAY").unwrap())
            .env("XAUTHORITY", std::env::var_os("XAUTHORITY").unwrap())
            .env("LIBGL_ALWAYS_SOFTWARE", "1")
            .process_group(0);
        let child = command.spawn().unwrap();
        let held = pidfd(&child);
        let mut value = Self {
            child,
            pidfd: held,
            channel,
            reserved: serde_json::Value::Null,
            birth: serde_json::Value::Null,
            binaries: binaries.into(),
            app_pid: 0,
            app_pidfd: None,
            _runtime: runtime,
        };
        let end = Instant::now() + Duration::from_secs(10);
        loop {
            assert!(value.child.try_wait().unwrap().is_none());
            let pid = value.child.id();
            if crate::authority_host_runtime::verify_process_credentials(pid, 60001, 60001).is_ok()
                && std::fs::read_link(format!("/proc/{pid}/exe")).unwrap() == binary
            {
                let stat = std::fs::read_to_string(format!("/proc/{pid}/stat")).unwrap();
                let ticks: u64 = stat
                    .rsplit_once(") ")
                    .unwrap()
                    .1
                    .split_whitespace()
                    .nth(19)
                    .unwrap()
                    .parse()
                    .unwrap();
                value.birth = serde_json::json!({"uid":60001,"pid":pid,
                    "boot_id":std::fs::read_to_string("/proc/sys/kernel/random/boot_id").unwrap().trim(),
                    "process_start_ticks":ticks});
                break;
            }
            assert!(
                Instant::now() < end,
                "actual Session did not exec under its owner"
            );
            std::thread::sleep(Duration::from_millis(5));
        }
        value
            .channel
            .set_read_timeout(Some(Duration::from_secs(10)))
            .unwrap();
        let mut raw = [0_u8; 1_025];
        // SAFETY: peek observes the queued real Session bytes without consuming
        // them or sending a replacement; the public loader receives them once.
        let count = unsafe {
            libc::recv(
                value.channel.as_raw_fd(),
                raw.as_mut_ptr().cast(),
                raw.len(),
                libc::MSG_PEEK,
            )
        };
        assert!((1..=1_024).contains(&count));
        value.reserved = serde_json::from_slice(&raw[..count as usize]).unwrap();
        assert_eq!(value.reserved["action"], "notes_target_reserved");
        let end = Instant::now() + Duration::from_secs(5);
        loop {
            assert!(value.child.try_wait().unwrap().is_none());
            let pid = value.child.id();
            let children =
                std::fs::read_to_string(format!("/proc/{pid}/task/{pid}/children")).unwrap();
            let children: Vec<u32> = children
                .split_whitespace()
                .map(|pid| pid.parse().unwrap())
                .collect();
            assert_eq!(
                children.len(),
                1,
                "the actual staged Session must own only its initial App"
            );
            let child = children[0];
            if std::fs::read_link(format!("/proc/{child}/exe")).is_ok_and(|path| path == app)
                && crate::authority_host_runtime::verify_process_credentials(child, 60001, 60001)
                    .is_ok()
            {
                // SAFETY: this PID is the sole child of our retained, blocked
                // Session; it cannot be reaped/reused before its staged wait ends.
                let raw = unsafe { libc::syscall(libc::SYS_pidfd_open, child, 0) };
                assert!(raw >= 0);
                // SAFETY: successful pidfd_open returned one new descriptor.
                value.app_pidfd = Some(unsafe { OwnedFd::from_raw_fd(raw as i32) });
                value.app_pid = child;
                break;
            }
            assert!(Instant::now() < end, "the actual initial App did not exec");
            std::thread::sleep(Duration::from_millis(5));
        }
        value
    }

    pub(super) fn assert_waiting(&mut self) {
        assert!(self.child.try_wait().unwrap().is_none());
        let mut event = libc::pollfd {
            fd: self.channel.as_raw_fd(),
            events: libc::POLLIN,
            revents: 0,
        };
        // SAFETY: the retained descriptor and one initialized pollfd remain live.
        assert_eq!(unsafe { libc::poll(&mut event, 1, 0) }, 0);
        event.fd = self.app_pidfd.as_ref().unwrap().as_raw_fd();
        // SAFETY: the retained actual App pidfd remains owned by this fixture.
        assert_eq!(unsafe { libc::poll(&mut event, 1, 0) }, 0);
    }

    pub(super) fn stop(&mut self) {
        if let Some(app) = &self.app_pidfd {
            // SAFETY: the held kernel handle targets only this Session's actual
            // App, even if Session already exited. No ambient PID is rediscovered.
            let result = unsafe {
                libc::syscall(
                    libc::SYS_pidfd_send_signal,
                    app.as_raw_fd(),
                    libc::SIGKILL,
                    std::ptr::null::<libc::siginfo_t>(),
                    0,
                )
            };
            assert!(
                result == 0 || std::io::Error::last_os_error().raw_os_error() == Some(libc::ESRCH)
            );
            let mut event = libc::pollfd {
                fd: app.as_raw_fd(),
                events: libc::POLLIN,
                revents: 0,
            };
            // SAFETY: the exact retained pidfd and one poll buffer remain live.
            assert_eq!(unsafe { libc::poll(&mut event, 1, 2_000) }, 1);
            assert_ne!(event.revents & libc::POLLIN, 0);
        }
        if self.child.try_wait().unwrap().is_none() {
            let group = i32::try_from(self.child.id()).unwrap();
            // SAFETY: this is the fresh retained child's private process group;
            // no ambient PID/group or other display process can be targeted.
            assert_eq!(unsafe { libc::kill(-group, libc::SIGKILL) }, 0);
            assert!(!self.child.wait().unwrap().success());
        }
    }
}

impl Drop for ActualSession {
    fn drop(&mut self) {
        self.stop();
    }
}
