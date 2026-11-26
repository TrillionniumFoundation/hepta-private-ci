use std::process::Command;

use anyhow::Context;
use anyhow::Result;
use tokio::net::UnixListener;

use super::*;

pub(crate) struct RootCgroup(pub(crate) PathBuf);

impl RootCgroup {
    pub(crate) fn new() -> Result<Self> {
        let path = Path::new("/sys/fs/cgroup").join(format!(
            "hepta-controller-qualification-{}",
            uuid::Uuid::new_v4()
        ));
        let status = Command::new("sudo")
            .args(["-n", "/usr/bin/python3", "-c"])
            .arg("import os,sys; os.mkdir(sys.argv[1])")
            .arg(&path)
            .status()?;
        anyhow::ensure!(
            status.success(),
            "independent protected cgroup fixture unavailable"
        );
        Ok(Self(path))
    }

    pub(crate) fn relative(&self) -> String {
        format!(
            "/{}",
            self.0.file_name().expect("fixture name").to_string_lossy()
        )
    }
}

impl Drop for RootCgroup {
    fn drop(&mut self) {
        let _ = Command::new("sudo")
            .args(["-n", "/usr/bin/python3", "-c"])
            .arg("import os,sys; os.rmdir(sys.argv[1])")
            .arg(&self.0)
            .status();
    }
}

const PEER: &str = r#"
import ctypes,os,socket,sys
if sys.argv[2] != '-':
    with open(sys.argv[2]+'/cgroup.procs','w') as membership: membership.write(str(os.getpid()))
os.setgroups([]); os.setgid(int(sys.argv[4])); os.setuid(int(sys.argv[3]))
assert ctypes.CDLL(None).prctl(4,1)==0
print(os.getpid(), flush=True)
s=socket.socket(socket.AF_UNIX); s.connect(sys.argv[1]); s.sendall(b'identity\n')
try: s.recv(1)
except ConnectionResetError: pass
"#;

fn child(
    path: &Path,
    cgroup: Option<&RootCgroup>,
    uid: u32,
    gid: u32,
) -> Result<std::process::Child> {
    Ok(Command::new("sudo")
        .args(["-n", "/usr/bin/python3", "-c", PEER])
        .arg(path)
        .arg(
            cgroup
                .map(|group| group.0.as_os_str())
                .unwrap_or("-".as_ref()),
        )
        .arg(uid.to_string())
        .arg(gid.to_string())
        .stdout(std::process::Stdio::piped())
        .spawn()?)
}

pub(crate) fn principal(cgroup: &RootCgroup) -> Result<ControllerPrincipal> {
    Ok(ControllerPrincipal {
        uid: unsafe { libc::geteuid() },
        gid: unsafe { libc::getegid() },
        desktop_uid: unsafe { libc::geteuid() },
        gateway_executable: Path::new("/usr/bin/python3").canonicalize()?,
        gateway_cgroup: cgroup.relative(),
    })
}

#[tokio::test]
#[ignore = "requires sudo and an independent root-owned Linux cgroup"]
async fn controller_peer_actual_kernel_executable_cgroup_and_uid() -> Result<()> {
    use tokio::io::AsyncReadExt;
    let root = RootCgroup::new()?;
    let temp = tempfile::tempdir()?;
    let path = temp.path().join("ctl");
    let listener = UnixListener::bind(&path)?;
    use std::os::unix::fs::PermissionsExt;
    std::fs::set_permissions(temp.path(), std::fs::Permissions::from_mode(0o755))?;
    std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o666))?;
    let gate = ControllerPeerGate::open(principal(&root)?, "hepta-fleet-test")?;
    let mut peer = child(&path, Some(&root), gate.principal.uid, gate.principal.gid)?;
    let (mut stream, _) =
        tokio::time::timeout(std::time::Duration::from_secs(5), listener.accept()).await??;
    let kernel_pid = stream.peer_cred()?.pid().context("Linux peer PID")?;
    use std::io::BufRead;
    let mut child_pid = String::new();
    std::io::BufReader::new(peer.stdout.take().context("peer stdout")?)
        .read_line(&mut child_pid)?;
    assert_eq!(u32::try_from(kernel_pid)?, child_pid.trim().parse::<u32>()?);
    gate.verify(&stream)?;
    let mut bytes = [0; 9];
    stream.read_exact(&mut bytes).await?;
    assert_eq!(&bytes, b"identity\n");
    drop(stream);
    assert!(peer.wait()?.success());

    // The same UID and same trusted executable in the delegated workload
    // location cannot borrow the dedicated service's enrollment.
    let mut peer = child(&path, None, gate.principal.uid, gate.principal.gid)?;
    let (stream, _) = listener.accept().await?;
    assert!(gate.verify(&stream).is_err());
    drop(stream);
    assert!(peer.wait()?.success());

    // A real same-UID socket from this test executable is also denied.
    let client = UnixStream::connect(&path).await?;
    let (stream, _) = listener.accept().await?;
    assert!(gate.verify(&stream).is_err());
    drop(stream);
    drop(client);

    let mut peer = child(
        &path,
        Some(&root),
        gate.principal.uid + 1,
        gate.principal.gid,
    )?;
    let (stream, _) = listener.accept().await?;
    assert!(gate.verify(&stream).is_err());
    drop(stream);
    assert!(peer.wait()?.success());
    Ok(())
}

#[test]
fn controller_peer_enrollment_rejects_delegated_and_fleet_cgroups() -> Result<()> {
    let cgroup = std::fs::read_to_string("/proc/self/cgroup")?
        .trim()
        .strip_prefix("0::")
        .context("unified Linux cgroup")?
        .to_owned();
    let principal = ControllerPrincipal {
        uid: unsafe { libc::geteuid() },
        gid: unsafe { libc::getegid() },
        desktop_uid: unsafe { libc::geteuid() },
        gateway_executable: Path::new("/usr/bin/python3").canonicalize()?,
        gateway_cgroup: cgroup,
    };
    assert!(ControllerPeerGate::open(principal.clone(), "hepta-fleet-test").is_err());
    let mut workload = principal;
    workload.gateway_cgroup = "/hepta-fleet-test/agent-x/agentd-1".into();
    assert!(ControllerPeerGate::open(workload, "hepta-fleet-test").is_err());
    Ok(())
}

#[test]
fn controller_peer_stat_parser_preserves_process_name_parentheses() -> Result<()> {
    assert!(start_ticks(Path::new("/proc/self"))? > 0);
    assert!(within("/hepta-fleet/agent-a", "/hepta-fleet"));
    assert!(!within("/hepta-fleet-other", "/hepta-fleet"));
    Ok(())
}
