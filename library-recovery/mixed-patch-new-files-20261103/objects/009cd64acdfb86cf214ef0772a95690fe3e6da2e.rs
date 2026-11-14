//! Real authenticated processes whose foreign parent deliberately retains zombies.

use std::io::Write;
use std::path::Path;
use std::process::Child;
use std::process::Command;
use std::process::Stdio;
use std::time::Duration;
use std::time::Instant;

use anyhow::Result;
use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_fleet::ReleaseId;

use super::*;

struct ForeignPeer {
    parent: Child,
    pid: u32,
}

impl ForeignPeer {
    fn start(root: &Path, response: serde_json::Value) -> Result<Self> {
        let socket = root.join("control.sock");
        let ready = root.join("ready");
        let parent = Command::new("python3")
            .args(["-c", FOREIGN_PARENT])
            .arg(&socket)
            .arg(&ready)
            .arg(serde_json::to_string(&response)?)
            .stdin(Stdio::piped())
            .stdout(Stdio::null())
            .spawn()?;
        let mut fixture = Self { parent, pid: 0 };
        let deadline = Instant::now() + Duration::from_secs(5);
        loop {
            if let Ok(bytes) = std::fs::read_to_string(&ready)
                && let Ok(pid) = bytes.parse()
            {
                fixture.pid = pid;
                return Ok(fixture);
            }
            anyhow::ensure!(fixture.parent.try_wait()?.is_none(), "peer parent exited");
            anyhow::ensure!(Instant::now() < deadline, "peer did not become ready");
            std::thread::sleep(Duration::from_millis(5));
        }
    }

    fn wait_for_zombie(&self) -> Result<()> {
        let deadline = Instant::now() + Duration::from_secs(5);
        loop {
            let stat = std::fs::read_to_string(format!("/proc/{}/stat", self.pid))?;
            if stat
                .rsplit_once(')')
                .is_some_and(|(_, tail)| tail.trim_start().starts_with('Z'))
            {
                return Ok(());
            }
            anyhow::ensure!(Instant::now() < deadline, "peer never exited");
            std::thread::sleep(Duration::from_millis(5));
        }
    }
}

impl Drop for ForeignPeer {
    fn drop(&mut self) {
        if let Some(mut input) = self.parent.stdin.take() {
            let _ = input.write_all(b"x");
        }
        let _ = self.parent.wait();
    }
}

const FOREIGN_PARENT: &str = r#"
import json, os, pathlib, subprocess, sys, time
worker = r'''
import json, os, socket, sys
path, encoded = sys.argv[1:]
response = json.loads(encoded)
def set_pid(value):
    if isinstance(value, dict):
        for key, child in value.items():
            if key == "process_id": value[key] = os.getpid()
            else: set_pid(child)
    elif isinstance(value, list):
        for child in value: set_pid(child)
set_pid(response)
with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
    listener.bind(path)
    listener.listen(32)
    while True:
        stream, _ = listener.accept()
        with stream, stream.makefile("rb") as reader:
            request = json.loads(reader.readline())
            response["request_id"] = request["request_id"]
            stream.sendall(json.dumps(response).encode() + b"\n")
'''
socket_path, ready_path, encoded = sys.argv[1:]
child = subprocess.Popen([sys.executable, "-c", worker, socket_path, encoded])
try:
    deadline = time.monotonic() + 4
    while not pathlib.Path(socket_path).exists():
        if child.poll() is not None: raise RuntimeError("peer exited during setup")
        if time.monotonic() >= deadline: raise RuntimeError("peer setup timed out")
        time.sleep(.005)
    pathlib.Path(ready_path).write_text(str(child.pid))
    # No poll/wait here: retain the actual zombie until fixture cleanup.
    sys.stdin.buffer.read(1)
finally:
    try: child.kill()
    except ProcessLookupError: pass
    child.wait()
"#;

fn assert_terminal(mut process: UnixManagedProcess, peer: ForeignPeer) -> Result<()> {
    process.kill().map_err(anyhow::Error::msg)?;
    peer.wait_for_zombie()?;
    let observed = process.poll(/*max_logs*/ 64).map_err(anyhow::Error::msg)?;
    assert!(
        matches!(observed.state, ProcessState::Exited(_)),
        "a kernel-terminated authenticated peer is not Running while its foreign parent retains a zombie: {observed:?}"
    );
    drop(peer);
    process.request_stop().map_err(anyhow::Error::msg)?;
    process.kill().map_err(anyhow::Error::msg)?;
    let again = process.poll(/*max_logs*/ 64).map_err(anyhow::Error::msg)?;
    assert_eq!(
        again.state, observed.state,
        "reaping cannot resurrect the adopted peer"
    );
    Ok(())
}

#[test]
fn adopted_agent_exit_does_not_wait_for_foreign_parent_reaping() -> Result<()> {
    let root = tempfile::tempdir()?;
    let agent_id = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12")?;
    let response = AgentdResponse {
        schema_version: AGENTD_CONTROL_SCHEMA_VERSION,
        request_id: 1,
        agent_id: agent_id.clone(),
        spawn_generation: 1,
        current_generation: 2,
        payload: AgentdPayload::Health(codex_hepta_agent_protocol::HealthSnapshot {
            promotion_ready: true,
            ready: true,
            fenced: false,
            lifecycle: AgentLifecycle::Running,
            process_id: 0,
            workspace: root.path().join("workspace"),
            home_root: root.path().join("home"),
            run_root: root.path().join("run"),
        }),
    };
    let peer = ForeignPeer::start(root.path(), serde_json::to_value(response)?)?;
    let mut driver =
        UnixProcessDriver::new(/*log_channel_capacity*/ 64).map_err(anyhow::Error::msg)?;
    let adopted = driver
        .adopt(&AdoptSpec {
            agent_id,
            registry_generation: 2,
            spawn_generation: 1,
            workspace: root.path().join("workspace"),
            home_root: root.path().join("home"),
            run_root: root.path().join("run"),
            control_socket: root.path().join("control.sock"),
            identity: ProcessIdentity::new(u64::from(peer.pid), "fixture-agent")?,
        })
        .map_err(anyhow::Error::msg)?;
    let Adoption::Adopted(process) = adopted else {
        anyhow::bail!("expected actual authenticated Agentd adoption");
    };
    assert_terminal(process, peer)
}

#[test]
fn adopted_matrix_exit_does_not_wait_for_foreign_parent_reaping() -> Result<()> {
    let root = tempfile::tempdir()?;
    let agent_id = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12")?;
    let binding_digest = Sha256Digest::parse("1".repeat(64)).map_err(anyhow::Error::msg)?;
    let release_id = ReleaseId::parse("lifetime-fixture")?;
    let response = MatrixdResponse {
        schema_version: MATRIXD_CONTROL_SCHEMA_VERSION,
        request_id: 1,
        agent_id: agent_id.clone(),
        release_id: release_id.to_string(),
        binding_revision: 1,
        binding_digest: binding_digest.clone(),
        attached_agent_generation: 1,
        process_incarnation: "lifetime-fixture".to_string(),
        plane_epoch: 1,
        payload: MatrixdPayload::Health(MatrixdHealth {
            lifecycle: MatrixdLifecycle::Ready,
            process_id: 0,
            agentd_connected: true,
            matrix_sync_connected: true,
            fenced: false,
        }),
    };
    let peer = ForeignPeer::start(root.path(), serde_json::to_value(response)?)?;
    let mut driver =
        UnixProcessDriver::new(/*log_channel_capacity*/ 64).map_err(anyhow::Error::msg)?;
    let adopted = driver
        .adopt_matrixd(&MatrixAdoptSpec {
            agent_id,
            agent_generation: 1,
            binding_revision: 1,
            binding_digest,
            release_id,
            process_incarnation: "lifetime-fixture".to_string(),
            plane_epoch: 1,
            control_socket: root.path().join("control.sock"),
            identity: ProcessIdentity::new(u64::from(peer.pid), "fixture-matrix")?,
        })
        .map_err(anyhow::Error::msg)?;
    let Adoption::Adopted(process) = adopted else {
        anyhow::bail!("expected actual authenticated Matrixd adoption");
    };
    assert_terminal(process, peer)
}

#[test]
fn pinned_child_exit_code_is_retained_after_reaping() -> Result<()> {
    for code in [0, 23] {
        let mut child = Command::new("/bin/sh")
            .args(["-c", &format!("read release; exit {code}")])
            .stdin(Stdio::piped())
            .stdout(Stdio::null())
            .spawn()?;
        let mut pin = pidfd::PinnedProcess::open(child.id())?
            .ok_or_else(|| anyhow::anyhow!("live child has no pidfd"))?;
        let result = (|| -> Result<()> {
            anyhow::ensure!(pin.poll()?.is_none(), "blocked child was not alive");
            drop(child.stdin.take());
            let deadline = Instant::now() + Duration::from_secs(5);
            let observed = loop {
                if let Some(exit) = pin.poll()? {
                    break exit;
                }
                anyhow::ensure!(Instant::now() < deadline, "child exit was not observed");
                std::thread::sleep(Duration::from_millis(5));
            };
            let expected = ProcessExit {
                success: code == 0,
                code: Some(code),
            };
            anyhow::ensure!(observed == expected, "actual child exit code changed");
            anyhow::ensure!(
                pin.poll()? == Some(expected),
                "terminal observation was lost"
            );
            pin.signal(Signal::TERM)?;
            pin.signal(Signal::KILL)?;
            anyhow::ensure!(
                pin.poll()? == Some(expected),
                "repeated stop changed terminal state"
            );
            Ok(())
        })();
        // Signals target only the retained descriptor, even when waitid already
        // consumed the child exit and the numeric PID is no longer reserved.
        let _ = pin.signal(Signal::KILL);
        let _ = child.wait();
        result?;
    }
    Ok(())
}

#[test]
fn reaped_pin_does_not_signal_a_later_live_process() -> Result<()> {
    let mut original = Command::new("/bin/sleep").arg("30").spawn()?;
    let pin = pidfd::PinnedProcess::open(original.id())?
        .ok_or_else(|| anyhow::anyhow!("live child has no pidfd"))?;
    pin.signal(Signal::KILL)?;
    original.wait()?;
    let mut later = Command::new("/bin/sleep").arg("30").spawn()?;
    let result = (|| -> Result<()> {
        pin.signal(Signal::TERM)?;
        pin.signal(Signal::KILL)?;
        anyhow::ensure!(
            later.try_wait()?.is_none(),
            "expired pin affected a later process"
        );
        Ok(())
    })();
    let _ = later.kill();
    let _ = later.wait();
    result
}
