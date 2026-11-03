//! Opt-in namespace fixture. The transport executes unmodified runtime helper
//! source; it never constructs a launch, status, output, or terminal response.

use std::os::unix::fs::{OpenOptionsExt, PermissionsExt};
use std::process::Stdio;
use std::path::Path;
use std::time::Duration;

use anyhow::Context;
use anyhow::Result;
use anyhow::ensure;
use hepta_runtime::mcp::runtime::config::{RuntimeConfig, init_runtime};
use serde_json::json;

pub(super) const OPT_IN: &str = "HEPTA_NATIVE_REAL_PROCESS_ACCEPTANCE";
pub(super) const CHILD: &str = "HEPTA_NATIVE_REAL_PROCESS_CHILD";
const ARTIFACTS: &str = "HEPTA_NATIVE_ACCEPTANCE_ARTIFACTS_DIR";
const RETAIN_OWNERS: &str = "HEPTA_NATIVE_ACCEPTANCE_RETAIN_OWNERS";
pub(super) const ROOT: &str = "/acceptance";
pub(super) const CODEX_HELPER: &str = "/acceptance-codex";
const TEST: &str = "native_host::tests::runtime_acceptance_tests::controlled_native_process_acceptance";
const OBJECTIVE_TEST: &str = "native_host::tests::objective_native_tests::process_gate_tests::controlled_signed_objective_process_entry_gates";
const DAEMON_TEST: &str = "native_host::tests::objective_native_tests::owner_fixture::daemon_lifecycle_tests::controlled_embedded_daemon_lifecycle";
const CONTINUATION_TEST: &str = "native_host::tests::objective_native_tests::checkpoint_continuation_tests::terminal_continuation_tests::controlled_original_terminal_checkpoint_continuations";

pub(super) async fn initialize(root: &Path) -> Result<()> {
    ensure!(root == Path::new(ROOT), "acceptance child root must be the namespace mount");
    let config: RuntimeConfig = serde_json::from_value(json!({
        "state_dir": root.join("state"), "controller_workspace_roots": [root.join("work")],
        "hosts": {"controlled": {
            "ssh_target": "native-fixture-only", "platform": "linux", "execution_mode": "operator",
            "remote_state_dir": root.join("remote"), "allow_execute": true,
            "allow_write": false, "allow_pty": false, "allow_job_network": true,
            "allow_detached_fallback": true
        }}
    }))?;
    init_runtime(config)?;
    Ok(())
}

pub(super) async fn isolated_subprocess() -> Result<()> {
    isolated_test_subprocess(TEST).await
}

pub(super) async fn isolated_objective_subprocess() -> Result<()> {
    isolated_test_subprocess(OBJECTIVE_TEST).await
}

pub(super) async fn isolated_daemon_subprocess() -> Result<()> {
    isolated_test_subprocess(DAEMON_TEST).await
}

pub(super) async fn isolated_checkpoint_continuation_subprocess() -> Result<()> {
    isolated_test_subprocess(CONTINUATION_TEST).await
}

async fn isolated_test_subprocess(test_name: &str) -> Result<()> {
    ensure!(matches!(test_name, TEST | OBJECTIVE_TEST | DAEMON_TEST | CONTINUATION_TEST), "acceptance child test must be explicitly registered");
    ensure!(std::env::var(OPT_IN).as_deref() == Ok("1"), "held: explicitly set {OPT_IN}=1 to run real owned processes");
    let artifact_parent = std::env::var_os(ARTIFACTS).map(std::path::PathBuf::from);
    let retained = artifact_parent.is_some();
    let mut temporary = if let Some(parent) = &artifact_parent {
        ensure!(parent.is_absolute(), "acceptance artifacts root must be absolute");
        tokio::fs::create_dir_all(parent).await?;
        let metadata = tokio::fs::symlink_metadata(parent).await?;
        ensure!(metadata.is_dir() && !metadata.file_type().is_symlink(), "acceptance artifacts root must be a real directory");
        let prefix = format!("{}-", test_name.rsplit("::").next().context("registered test name")?);
        tempfile::Builder::new().prefix(&prefix).tempdir_in(parent)?
    } else { tempfile::tempdir()? };
    // Keep the original directories, including failure evidence. No live
    // SQLite/WAL, operation journal or runtime output is copied to an export.
    temporary.disable_cleanup(retained);
    let root = tokio::fs::canonicalize(temporary.path()).await?;
    if retained { println!("HEPTA_NATIVE_ACCEPTANCE_ARTIFACTS={}", root.display()); }
    tokio::fs::set_permissions(&root, std::fs::Permissions::from_mode(0o700)).await?;
    for name in ["bin", "state", "remote", "work", "authority", "owners"] {
        let directory = root.join(name);
        tokio::fs::create_dir(&directory).await?;
        tokio::fs::set_permissions(directory, std::fs::Permissions::from_mode(0o700)).await?;
    }
    let owner = serde_json::to_vec(&json!({
        "schema":"hepta-effect-owner-fence-v1", "owner":"v4", "epoch":1, "phase":"admitting",
        "state_root":format!("{ROOT}/state"), "predecessor_state_root":null
    }))?;
    for (name, bytes, mode) in [
        ("authority/.owner.lock", Vec::new(), 0o600),
        ("authority/.owner.json", owner, 0o600),
        ("bin/ssh", SSH_TRANSPORT.as_bytes().to_vec(), 0o700),
        ("work/worker.py", WORKER.as_bytes().to_vec(), 0o600),
    ] {
        let path = root.join(name);
        tokio::fs::write(&path, bytes).await?;
        tokio::fs::set_permissions(path, std::fs::Permissions::from_mode(mode)).await?;
    }
    let binary = tokio::fs::canonicalize(std::env::current_exe()?).await?;
    let invocation = json!({
        "schema":"hepta.native.acceptance-invocation.v1", "test":test_name,
        "test_binary":binary, "namespace_root":ROOT, "artifact_root":root,
        "retained":retained, "owner_roots":"owners", "runtime_owner":"state",
        "runtime_jobs":"remote/jobs", "transport_trace":"transport.jsonl",
        "child_stdout":"child.stdout", "child_stderr":"child.stderr",
    });
    tokio::fs::write(root.join("invocation.json"), serde_json::to_vec_pretty(&invocation)?).await?;
    let mut command = tokio::process::Command::new("/usr/bin/bwrap");
    command.env_clear().kill_on_drop(true)
        .args(["--unshare-all", "--new-session", "--die-with-parent", "--cap-drop", "ALL"]);
    // Only public system executables/libraries and this compiled test binary.
    // No home, private keys, production configuration, or service socket mount.
    for path in ["/usr", "/bin", "/lib", "/lib64"] {
        if tokio::fs::try_exists(path).await? {
            command.args(["--ro-bind", path, path]);
        }
    }
    if test_name == DAEMON_TEST {
        // The real App Server receives the compiled Codex helper, never the
        // test harness as codex_self_exe. No workspace/home directory is bound.
        let helper = tokio::fs::canonicalize(codex_utils_cargo_bin::cargo_bin("codex")?).await
            .context("held: embedded daemon requires the already compiled Codex helper")?;
        command.arg("--ro-bind").arg(helper).arg(CODEX_HELPER);
    }
    command.args(["--dir", "/etc"]);
    for path in ["/etc/passwd", "/etc/group"] {
        if tokio::fs::try_exists(path).await? {
            command.args(["--ro-bind", path, path]);
        }
    }
    command.args(["--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp", "--tmpfs", "/run",
        "--bind"]).arg(&root).arg(ROOT)
        .arg("--ro-bind").arg(binary).arg("/acceptance-test")
        .args(["--chdir", ROOT, "--setenv", "PATH", "/acceptance/bin:/usr/bin:/bin",
            "--setenv", "RUST_MIN_STACK", "8388608",
            "--setenv", OPT_IN, "1", "--setenv", CHILD, "1",
            "--setenv", "HEPTA_EFFECT_OWNER_FENCE_DIR", "/acceptance/authority",
            "--setenv", "HEPTA_EFFECT_OWNER_SELF", "v4",
            "--setenv", "HEPTA_EFFECT_OWNER_FENCE_REQUIRED", "1"]);
    if retained { command.args(["--setenv", RETAIN_OWNERS, "1"]); }
    command.args(["--", "/acceptance-test", "--exact", test_name, "--ignored", "--nocapture"]);
    let stdout = std::fs::OpenOptions::new().write(true).create_new(true).mode(0o600)
        .open(root.join("child.stdout"))?;
    let stderr = std::fs::OpenOptions::new().write(true).create_new(true).mode(0o600)
        .open(root.join("child.stderr"))?;
    let mut child = command.stdin(Stdio::null()).stdout(Stdio::from(stdout)).stderr(Stdio::from(stderr))
        .spawn().context("held: could not start the required namespace; no isolation fallback is allowed")?;
    let status = match tokio::time::timeout(Duration::from_secs(90), child.wait()).await {
        Ok(status) => status.context("held: isolated real-process acceptance wait failed")?,
        Err(_) => {
            // This is the exact bwrap child we just spawned. Its private PID
            // namespace owns every fixture child; metadata PIDs are never used.
            let _ = child.kill().await;
            let _ = child.wait().await;
            anyhow::bail!("held: isolated real-process acceptance exceeded its deadline; artifacts: {}", root.display());
        }
    };
    let summary = json!({ "schema":"hepta.native.acceptance-process-exit.v1",
        "test":test_name, "success":status.success(), "code":status.code(), "retained":retained });
    tokio::fs::write(root.join("process-exit.json"), serde_json::to_vec_pretty(&summary)?).await?;
    if !status.success() {
        let stdout = tokio::fs::read_to_string(root.join("child.stdout")).await?;
        let stderr = tokio::fs::read_to_string(root.join("child.stderr")).await?;
        anyhow::bail!("controlled real runtime failed (no silent skip); artifacts: {}\n{}\n{}",
            root.display(), stdout, stderr);
    }
    if retained {
        let mut owners = tokio::fs::read_dir(root.join("owners")).await?;
        ensure!(owners.next_entry().await?.is_some(), "acceptance omitted retained original owner evidence");
    }
    let report = tokio::fs::read_to_string(root.join("report.json")).await.context("acceptance result missing")?;
    println!("{report}");
    Ok(())
}

const SSH_TRANSPORT: &str = r#"#!/usr/bin/python3
import json, os, pathlib, shlex, subprocess, sys, time
expected = ['-T','-o','BatchMode=yes','-o','ConnectTimeout=8','-o','StrictHostKeyChecking=yes','-o','ForwardAgent=no','native-fixture-only']
health = ['-T','-o','BatchMode=yes','-o','ConnectTimeout=8','-o','StrictHostKeyChecking=yes','-o','ForwardAgent=no','-o','ClearAllForwardings=yes','-o','PermitLocalCommand=no','-o','RemoteCommand=none','-o','RequestTTY=no','--','native-fixture-only']
if sys.argv[1:-1] == health:
    if sys.argv[-1] != "printf 'hepta-host-health-v1\\n'" or sys.stdin.buffer.read(1):
        raise SystemExit('fixture refuses another health command or input')
    # Delegate the exact original fixed command to a real isolated shell.
    # This exercises runtime's probe process/output checks; SSH credentials and
    # network authentication remain outside this controlled transport fixture.
    result = subprocess.run(['/bin/sh','-c',sys.argv[-1]], stdin=subprocess.DEVNULL, capture_output=True, timeout=5)
    with pathlib.Path('/acceptance/transport.jsonl').open('a') as stream:
        stream.write(json.dumps({'health': True, 'command': sys.argv[-1], 'exit_code': result.returncode}) + '\n')
        stream.flush(); os.fsync(stream.fileno())
    sys.stdout.buffer.write(result.stdout)
    sys.stderr.buffer.write(result.stderr)
    raise SystemExit(result.returncode)
if sys.argv[1:-1] != expected:
    raise SystemExit('fixture refuses another SSH destination or transport shape')
command = shlex.split(sys.argv[-1])
if len(command) != 3 or command[:2] != ['python3', '-c']:
    raise SystemExit('fixture permits only the existing runtime Python helper')
raw = sys.stdin.buffer.read(131073)
if len(raw) > 131072:
    raise SystemExit('bounded fixture request exceeded')
request = json.loads(raw)
root = pathlib.Path('/acceptance')
with (root / 'transport.jsonl').open('a') as stream:
    stream.write(json.dumps({'job_id': request.get('job_id'), 'launch': 'executable' in request}) + '\n')
    stream.flush(); os.fsync(stream.fileno())
# Source, stdin, stdout, stderr, and exit status remain the original helper's.
# /run is an empty namespace mount, so no existing user systemd bus is reachable.
barrier = False
if 'wait_seconds' in request:
    job = root / 'remote/jobs' / request['job_id']
    bound = json.loads((job / 'request.json').read_text())
    if bound.get('args', [])[-1:] == ['terminal-race']:
        try:
            claim = os.open(root / 'work/terminal-race.barrier', os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            pass
        else:
            os.close(claim)
            barrier = True
            deadline = time.monotonic() + 5
            while not (root / 'work/terminal-race.marker').exists():
                if time.monotonic() >= deadline:
                    raise SystemExit('real terminal-race child did not start')
                time.sleep(.01)
result = subprocess.run(['/usr/bin/python3','-I','-S','-c',command[2]], input=raw, capture_output=True, timeout=25)
if barrier:
    observed = json.loads(result.stdout)
    if result.returncode != 0 or observed.get('job_id') != request['job_id'] or observed.get('state') != 'running':
        raise SystemExit('terminal-race barrier requires the original running status')
    with (root / 'work/terminal-race.first-status.json').open('xb') as stream:
        stream.write(result.stdout); stream.flush(); os.fsync(stream.fileno())
    with (root / 'work/terminal-race.release').open('xb') as stream:
        stream.write(b'release same original child'); stream.flush(); os.fsync(stream.fileno())
    deadline = time.monotonic() + 5
    while not (job / 'exit.witness.json').exists():
        if time.monotonic() >= deadline:
            raise SystemExit('real terminal-race child did not publish its terminal witness')
        time.sleep(.01)
    # Return exactly the real nonterminal bytes captured BEFORE the child was
    # released. The next runtime observation reads the real terminal files.
sys.stdout.buffer.write(result.stdout)
sys.stderr.buffer.write(result.stderr)
raise SystemExit(result.returncode)
"#;

const WORKER: &str = r#"import os, pathlib, sys, time
root = pathlib.Path(sys.argv[1]); kind = sys.argv[2]
with (root / (kind + '.attempts')).open('a') as stream:
    stream.write(str(os.getpid()) + '\n'); stream.flush(); os.fsync(stream.fileno())
print('BEGIN ' + kind, flush=True)
print('stderr ' + kind, file=sys.stderr, flush=True)
if kind == 'continuation-raw':
    sys.stdout.buffer.write(b'original raw bytes: \xff\xfe\x80\n'); sys.stdout.buffer.flush()
    sys.stderr.buffer.write(b'original raw stderr: \x81\n'); sys.stderr.buffer.flush()
with (root / (kind + '.marker')).open('x') as stream:
    stream.write('one original child\n'); stream.flush(); os.fsync(stream.fileno())
deadline = time.monotonic() + 25
while not (root / (kind + '.release')).exists():
    if time.monotonic() > deadline:
        raise SystemExit(42)
    time.sleep(.02)
print('END ' + kind, flush=True)
"#;
