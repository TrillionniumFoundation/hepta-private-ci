//! Retained, single-attempt OS children for the MEM15 fixture, not a sandbox.

use std::error::Error;
use std::ffi::OsString;
use std::fs::File;
use std::fs::OpenOptions;
use std::io::Read;
use std::io::Write;
use std::os::unix::fs::OpenOptionsExt;
use std::os::unix::fs::PermissionsExt;
use std::path::Path;
use std::process::Command;
use std::process::Stdio;
use std::time::Duration;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::Sha256Digest;
use serde_json::Value;
use sha2::Digest;
use sha2::Sha256;

type Result<T> = std::result::Result<T, Box<dyn Error>>;
const ACK: &str = "mem15-import-ack:";

pub(super) struct ObservedChild {
    pub(super) receipt: Value,
    pub(super) stdout: String,
    pub(super) stderr: String,
}

impl ObservedChild {
    pub(super) fn success(&self) -> bool {
        self.receipt["exit_code"] == 0 && self.receipt["timed_out"] == false
    }

    pub(super) fn import_ack(&self, snapshot: &str) -> Result<Value> {
        let replies = self.stdout.lines().filter_map(|line| line.strip_prefix(ACK)).collect::<Vec<_>>();
        if !self.success() || replies.len() != 1 {
            return Err("A import acknowledgement/OS exit unresolved; do not reimport".into());
        }
        let reply: Value = serde_json::from_str(replies[0])?;
        if reply["schema"] != "hepta.mem15.import-ack.v1"
            || reply["pid"] != self.receipt["pid"]
            || reply["snapshot_sha256"] != Sha256Digest::for_bytes(snapshot.as_bytes()).as_str()
            || reply["imported"]["active_records"] != 1
        {
            return Err("A acknowledgement does not bind the exact original import".into());
        }
        Ok(reply)
    }
}

fn now() -> Result<u64> {
    Ok(u64::try_from(SystemTime::now().duration_since(UNIX_EPOCH)?.as_nanos())?)
}

pub(super) fn pin(path: &Path) -> Result<Value> {
    let mut file = File::open(path)?;
    let mut hash = Sha256::new();
    let mut buffer = [0_u8; 64 * 1024];
    let mut bytes = 0_usize;
    loop {
        let read = file.read(&mut buffer)?;
        if read == 0 { break; }
        hash.update(&buffer[..read]);
        bytes += read;
    }
    Ok(serde_json::json!({"sha256": format!("{:x}", hash.finalize()), "bytes": bytes}))
}

fn private_file(path: &Path) -> Result<File> {
    Ok(OpenOptions::new().create_new(true).write(true).mode(0o600).open(path)?)
}

pub(super) async fn observe(
    root: &Path,
    executable: &Path,
    args: &[OsString],
    extra_env: &[(String, OsString)],
    input: &[u8],
    timeout: Duration,
) -> Result<ObservedChild> {
    // Exclusive role directory is the no-reissue fence, including lost exit or ack.
    std::fs::create_dir(root)?;
    std::fs::set_permissions(root, std::fs::Permissions::from_mode(0o700))?;
    for name in ["work", "home", "cache"] { std::fs::create_dir(root.join(name))?; }
    let input_path = root.join("stdin.bin");
    let mut retained_input = private_file(&input_path)?;
    retained_input.write_all(input)?;
    retained_input.sync_all()?;
    drop(retained_input);
    let executable_before = pin(executable)?;
    let mut command = Command::new(executable);
    command.args(args).env_clear().current_dir(root.join("work"));
    command.env("HOME", root.join("home")).env("XDG_CACHE_HOME", root.join("cache"));
    command.env("PATH", "/usr/bin:/bin").env("LANG", "C.UTF-8");
    command.envs(extra_env.iter().map(|(key, value)| (key, value)));
    command.stdin(Stdio::from(File::open(&input_path)?));
    command.stdout(Stdio::from(private_file(&root.join("stdout.bin"))?));
    command.stderr(Stdio::from(private_file(&root.join("stderr.bin"))?));
    let intent = serde_json::json!({
        "executable": executable, "executable_pin": executable_before,
        "argv": args, "extra_environment": extra_env, "stdin": pin(&input_path)?,
        "home": root.join("home"), "cache": root.join("cache"), "cwd": root.join("work"),
        "environment_cleared": true, "namespace_isolated": false,
        "timeout_ms": timeout.as_millis(), "maximum_attempts": 1,
    });
    super::write_receipt(root, "INTENT.json", &intent)?;
    let started = now()?;
    let mut child = command.spawn()?;
    let pid = child.id();
    let process_identity = std::fs::read_to_string(format!("/proc/{pid}/stat")).ok();
    super::write_receipt(root, "STARTED.json", &serde_json::json!({
        "pid": pid, "started_at_unix_ns": started, "proc_stat": process_identity,
    }))?;
    let deadline = tokio::time::Instant::now() + timeout;
    let (status, timed_out) = loop {
        if let Some(status) = child.try_wait()? { break (status, false); }
        if tokio::time::Instant::now() >= deadline {
            // Only this owned child handle is stopped. The owner may have committed:
            // killing A is not rollback; a missing ack remains UNKNOWN forever here.
            child.kill()?;
            break (child.wait()?, true);
        }
        tokio::time::sleep(Duration::from_millis(10)).await;
    };
    let exited = now()?;
    let executable_after = pin(executable)?;
    let input_after = pin(&input_path)?;
    let receipt = serde_json::json!({
        "schema": "hepta.mem15.os-child.v1", "pid": pid, "parent_pid": std::process::id(),
        "started_at_unix_ns": started, "exited_at_unix_ns": exited,
        "exit_code": status.code(), "timed_out": timed_out,
        "executable_before": executable_before, "executable_after": executable_after,
        "stdin": input_after, "stdout": pin(&root.join("stdout.bin"))?,
        "stderr": pin(&root.join("stderr.bin"))?, "proc_stat": process_identity,
        "no_reissue": true, "namespace_isolated": false,
    });
    super::write_receipt(root, "EXIT.json", &receipt)?;
    if executable_before != executable_after || input_after != intent["stdin"] {
        return Err("child executable/input changed; retained outcome is not admitted".into());
    }
    let read_output = |name: &str| -> Result<String> {
        let path = root.join(name);
        if std::fs::metadata(&path)?.len() > 1024 * 1024 {
            return Err("child output exceeded admission bound; original retained".into());
        }
        Ok(std::fs::read_to_string(path)?)
    };
    Ok(ObservedChild { receipt, stdout: read_output("stdout.bin")?, stderr: read_output("stderr.bin")? })
}

pub(super) fn importer_test_name() -> String {
    format!("{}::episodic_mem15_import_child", module_path!().split_once("::").expect("crate prefix").1)
}

#[tokio::test]
#[ignore = "MEM15 parent-owned child only: imports one bounded stdin snapshot, then exits; no model"]
async fn episodic_mem15_import_child() -> Result<()> {
    if std::env::var("HEPTA_MEM15_IMPORT_CHILD")?.as_str() != "one-native-import-v1" {
        return Err("MEM15 parent child-role required".into());
    }
    let mut snapshot = String::new();
    std::io::stdin().take(20 * 1024 + 1).read_to_string(&mut snapshot)?;
    if snapshot.is_empty() || snapshot.len() > 20 * 1024 {
        return Err("bounded original snapshot required".into());
    }
    let client = crate::AgentdClient::new(
        std::env::var_os("HEPTA_MEM15_AGENTD_SOCKET").ok_or("socket required")?.into(),
        AgentId::parse(std::env::var("HEPTA_MEM15_AGENT_ID")?)?,
        std::env::var("HEPTA_MEM15_GENERATION")?.parse()?,
    )?;
    let snapshot_sha256 = Sha256Digest::for_bytes(snapshot.as_bytes());
    let imported = client.import_episodic_snapshot(snapshot).await?;
    println!("\n{ACK}{}", serde_json::to_string(&serde_json::json!({
        "schema": "hepta.mem15.import-ack.v1", "pid": std::process::id(),
        "snapshot_sha256": snapshot_sha256.as_str(), "imported": imported,
    }))?);
    std::io::stdout().flush()?;
    Ok(())
}

#[path = "production_episodic_process_child_tests.rs"]
mod tests;
