//! Actual cross-UID constructor coverage using pre-signed fixture records.
//! This qualifies transport custody only, not independent evaluation or keys.

use super::*;
use pretty_assertions::assert_eq;
use std::io::Write;
use std::os::unix::fs::PermissionsExt;
use std::os::unix::net::UnixListener;
use std::process::Command;
use std::process::Stdio;

#[tokio::test]
#[ignore = "explicit actual-Root external evidence UID 60001 qualification"]
async fn original_external_uid_returns_a_verified_receipt_through_held_pidfd() -> anyhow::Result<()>
{
    // SAFETY: observe credentials; this test must be explicitly run as Root.
    assert_eq!(unsafe { libc::geteuid() }, 0);
    let fixture = Fixture::new()?;
    let directory = tempfile::tempdir()?;
    std::fs::set_permissions(directory.path(), std::fs::Permissions::from_mode(0o711))?;
    let socket_path = directory.path().join("evidence.sock");
    let listener = UnixListener::bind(&socket_path)?;
    std::fs::set_permissions(&socket_path, std::fs::Permissions::from_mode(0o666))?;
    listener.set_nonblocking(true)?;
    let listener = tokio::net::UnixListener::from_std(listener)?;
    let script = r#"
import json,os,socket,struct,sys
evidence=json.loads(sys.stdin.buffer.readline())
assert os.getuid()==60001 and os.geteuid()==60001
s=socket.socket(socket.AF_UNIX);s.settimeout(5);s.connect(sys.argv[1])
def take(n):
    b=b''
    while len(b)<n:
        p=s.recv(n-len(b))
        if not p:raise RuntimeError('eof')
        b+=p
    return b
n=struct.unpack('>I',take(4))[0]
assert 0<n<=16384
r=json.loads(take(n))
assert r['operation']=='runtime.learning.evidence.readback.v1'
assert 'payload' not in r and 'signature' not in r
v={k:r[k] for k in ('schema','operation','request_id','binding','snapshot_head','receipt_digest')}
v['evidence']=evidence
b=json.dumps(v).encode();s.sendall(struct.pack('>I',len(b))+b)
assert sys.stdin.buffer.read(1)==b'X'
print('LEARNING_EVIDENCE_OWNER actual_uid=60001 signed_fixture=true',flush=True)
"#;
    let mut child = Command::new("/usr/bin/setpriv")
        .args([
            "--reuid=60001",
            "--regid=60001",
            "--clear-groups",
            "--no-new-privs",
            "--inh-caps=-all",
            "--ambient-caps=-all",
            "--bounding-set=-all",
            "python3",
            "-I",
            "-B",
            "-c",
            script,
        ])
        .arg(&socket_path)
        .env_clear()
        .env("PATH", "/usr/bin:/bin")
        .current_dir("/")
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()?;
    let pin = pidfd(child.id())?;
    let original = identity(child.id())?;
    let input = child.stdin.as_mut().expect("piped stdin");
    serde_json::to_writer(&mut *input, &fixture.evidence())?;
    input.write_all(b"\n")?;
    let (stream, _) = tokio::time::timeout(Duration::from_secs(5), listener.accept()).await??;
    let client = LearningIterationEvidenceClientV1::from_owner_stream(
        stream.into_std()?,
        LearningIterationEvidencePeerV1 {
            pid: original.pid,
            uid: 60001,
            boot_id: original.boot_id,
            process_start_ticks: original.process_start_ticks,
            actor_id: fixture.receipt.actor_id.clone(),
        },
        pin,
        fixture.initial.clone(),
        fixture.verifier.clone(),
        Duration::from_millis(500),
        Duration::from_secs(5),
    )?;
    assert_eq!(
        client.readback(&fixture.initial, &fixture.receipt).await?,
        fixture.signature
    );
    child.stdin.take().expect("piped stdin").write_all(b"X")?;
    let output = child.wait_with_output()?;
    anyhow::ensure!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    println!("{}", String::from_utf8(output.stdout)?);
    Ok(())
}
