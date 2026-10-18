use super::*;
use pretty_assertions::assert_eq;
use std::collections::BTreeSet;
use std::io::Read;
use std::io::Write;
use std::os::unix::fs::PermissionsExt;
use std::os::unix::net::UnixListener;
use std::sync::mpsc;

use crate::final_use_authorizer::IssuerProcessIdentityConfig;
use codex_hepta_contracts::FinalUseFrontier;
use codex_hepta_contracts::FinalUseRevocations;
use sha2::Digest;
use sha2::Sha256;

type TestResult<T = ()> = std::result::Result<T, Box<dyn std::error::Error + Send + Sync>>;

fn port(path: &Path) -> TestResult<UnixFinalUseTrustPort> {
    let text_digest = |path: &str| -> TestResult<String> {
        Ok(format!(
            "{:x}",
            Sha256::digest(std::fs::read_to_string(path)?.trim_end().as_bytes())
        ))
    };
    let mut port = UnixFinalUseTrustPort {
        issuer_socket: path.join("issuer.sock"),
        issuer_uid: rustix::process::geteuid().as_raw(),
        signer_id: "startup-original-owner".into(),
        timeout: Duration::from_secs(2),
        process_identity: Some(IssuerProcessIdentityConfig {
            executable_sha256: format!(
                "{:x}",
                Sha256::digest(std::fs::read(std::env::current_exe()?)?)
            ),
            cgroup_sha256: text_digest("/proc/self/cgroup")?,
            boot_id_sha256: text_digest("/proc/sys/kernel/random/boot_id")?,
        }),
        process_attestation: None,
    };
    if port.issuer_uid == 0 {
        // Use the actual production Root-attested capture for deadline cases.
        // Hashing this large Cargo test executable on every manual peer check
        // would test a different, non-production transport configuration.
        let expected = port.process_identity.as_ref().ok_or("pin missing")?;
        let stat = std::fs::read_to_string("/proc/self/stat")?;
        let start_time_ticks = stat
            .rsplit_once(") ")
            .ok_or("stat malformed")?
            .1
            .split_whitespace()
            .nth(19)
            .ok_or("start time missing")?
            .parse()?;
        let record = codex_hepta_contracts::ModelIssuerProcessIdentity {
            schema_version: 1,
            pid: std::process::id(),
            start_time_ticks,
            executable_sha256: expected.executable_sha256.clone(),
            cgroup_sha256: expected.cgroup_sha256.clone(),
            boot_id_sha256: expected.boot_id_sha256.clone(),
        };
        let attestation = path.join("identity.json");
        std::fs::write(&attestation, serde_json::to_vec(&record)?)?;
        std::fs::set_permissions(&attestation, std::fs::Permissions::from_mode(0o640))?;
        port.process_attestation = Some(attestation);
    }
    Ok(port)
}

fn delegated_root_case(name: &str) -> TestResult<bool> {
    if rustix::process::geteuid().as_raw() == 0 {
        return Ok(false);
    }
    let result = std::process::Command::new("sudo")
        .arg("-n")
        .arg(std::env::current_exe()?)
        .args([
            "--exact",
            &format!("final_use_trust_port::startup::tests::{name}"),
            "--ignored",
            "--nocapture",
        ])
        .output()?;
    assert!(
        result.status.success(),
        "{} {}",
        String::from_utf8_lossy(&result.stdout),
        String::from_utf8_lossy(&result.stderr)
    );
    assert!(String::from_utf8_lossy(&result.stdout).contains("1 passed"));
    Ok(true)
}

fn directory() -> TestResult<tempfile::TempDir> {
    // Production attestation requires every ancestor to be Root protected;
    // Root's /tmp fixture would correctly fail its unchanged 1777 fence.
    let parent = if rustix::process::geteuid().as_raw() == 0 {
        "/var/lib"
    } else {
        "/tmp"
    };
    let d = tempfile::Builder::new()
        .prefix("hepta-startup-")
        .tempdir_in(parent)?;
    std::fs::set_permissions(d.path(), std::fs::Permissions::from_mode(0o700))?;
    Ok(d)
}

fn bind(path: &Path) -> TestResult<UnixListener> {
    let listener = UnixListener::bind(path)?;
    std::fs::set_permissions(path, std::fs::Permissions::from_mode(0o660))?;
    Ok(listener)
}

fn serve_one(listener: &UnixListener) -> TestResult {
    let (mut stream, _) = listener.accept()?;
    stream.set_read_timeout(Some(Duration::from_secs(3)))?;
    let mut header = [0; 4];
    stream.read_exact(&mut header)?;
    let mut bytes = vec![0; u32::from_be_bytes(header) as usize];
    stream.read_exact(&mut bytes)?;
    let request: ModelTrustRequest = serde_json::from_slice(&bytes)?;
    assert_eq!(
        (request.operation.as_str(), request.expected, request.next),
        (MODEL_TRUST_LOAD, None, None)
    );
    let revocations = FinalUseRevocations {
        authority_epoch: 3,
        revision: 7,
        revoked_grant_ids: BTreeSet::new(),
    };
    let response = ModelTrustResponse {
        schema_version: MODEL_ISSUER_SCHEMA_VERSION,
        frontier: FinalUseFrontier::for_initial_head(&revocations)?,
        revocations,
        now_unix_ms: 12345,
    };
    let bytes = serde_json::to_vec(&response)?;
    stream.write_all(&(bytes.len() as u32).to_be_bytes())?;
    stream.write_all(&bytes)?;
    listener.set_nonblocking(true)?;
    assert!(matches!(listener.accept(), Err(e) if e.kind() == std::io::ErrorKind::WouldBlock));
    Ok(())
}

#[test]
#[ignore = "requires sudo: original deadline with production Root attestation"]
fn delayed_socket_publishes_one_original_load() -> TestResult {
    if delegated_root_case("delayed_socket_publishes_one_original_load")? {
        return Ok(());
    }
    let d = directory()?;
    let port = port(d.path())?;
    let socket = port.issuer_socket.clone();
    let server = std::thread::spawn(move || -> TestResult {
        std::thread::sleep(Duration::from_millis(80));
        let listener = bind(&socket)?;
        serve_one(&listener)
    });
    assert_eq!(port.load_startup_snapshot()?.now_unix_ms, 12345);
    server.join().map_err(|_| "startup server panicked")??;
    Ok(())
}

#[test]
#[ignore = "requires sudo: original deadline with production Root attestation"]
fn stale_refused_socket_waits_for_the_new_listener() -> TestResult {
    if delegated_root_case("stale_refused_socket_waits_for_the_new_listener")? {
        return Ok(());
    }
    let d = directory()?;
    let port = port(d.path())?;
    drop(bind(&port.issuer_socket)?);
    let socket = port.issuer_socket.clone();
    let server = std::thread::spawn(move || -> TestResult {
        std::thread::sleep(Duration::from_millis(80));
        std::fs::remove_file(&socket)?;
        let listener = bind(&socket)?;
        serve_one(&listener)
    });
    assert_eq!(port.load_startup_snapshot()?.now_unix_ms, 12345);
    server.join().map_err(|_| "startup server panicked")??;
    Ok(())
}

#[test]
fn unsafe_missing_parent_fails_before_waiting() -> TestResult {
    let d = directory()?;
    let mut port = port(d.path())?;
    std::fs::set_permissions(d.path(), std::fs::Permissions::from_mode(0o777))?;
    port.issuer_socket = d.path().join("not-published/issuer.sock");
    assert!(matches!(
        port.load_startup_snapshot(),
        Err(AuthorityTrustError::Invalid)
    ));
    Ok(())
}

#[test]
fn wrong_live_process_pin_receives_no_frame() -> TestResult {
    let d = directory()?;
    let mut port = port(d.path())?;
    port.process_identity
        .as_mut()
        .ok_or("missing fixture identity")?
        .cgroup_sha256 = "1".repeat(64);
    let listener = bind(&port.issuer_socket)?;
    let server = std::thread::spawn(move || -> TestResult {
        let (mut stream, _) = listener.accept()?;
        let mut byte = [0];
        assert_eq!(stream.read(&mut byte)?, 0);
        Ok(())
    });
    assert!(matches!(
        port.load_startup_snapshot(),
        Err(AuthorityTrustError::Invalid)
    ));
    server.join().map_err(|_| "startup server panicked")??;
    Ok(())
}

#[test]
#[ignore = "requires sudo: original deadline with production Root attestation"]
fn response_timeout_spends_the_original_startup_deadline_without_retry() -> TestResult {
    if delegated_root_case("response_timeout_spends_the_original_startup_deadline_without_retry")? {
        return Ok(());
    }
    let d = directory()?;
    let mut port = port(d.path())?;
    port.timeout = Duration::from_secs(1);
    let socket = port.issuer_socket.clone();
    let (sent, received) = mpsc::channel();
    let server = std::thread::spawn(move || -> TestResult {
        std::thread::sleep(Duration::from_millis(500));
        let listener = bind(&socket)?;
        let (mut stream, _) = listener.accept()?;
        stream.set_read_timeout(Some(Duration::from_secs(2)))?;
        let mut header = [0; 4];
        stream.read_exact(&mut header)?;
        let mut request = vec![0; u32::from_be_bytes(header) as usize];
        stream.read_exact(&mut request)?;
        sent.send(serde_json::from_slice::<ModelTrustRequest>(&request)?.operation)?;
        std::thread::sleep(Duration::from_secs(1));
        listener.set_nonblocking(true)?;
        assert!(matches!(listener.accept(), Err(e) if e.kind() == std::io::ErrorKind::WouldBlock));
        Ok(())
    });
    let started = Instant::now();
    assert!(matches!(
        port.load_startup_snapshot(),
        Err(AuthorityTrustError::Unavailable)
    ));
    assert!(started.elapsed() < Duration::from_millis(1400));
    assert_eq!(received.recv()?, MODEL_TRUST_LOAD);
    server.join().map_err(|_| "startup server panicked")??;
    Ok(())
}

#[test]
#[ignore = "requires sudo: actual Root publication and peer metadata"]
fn root_missing_publication_waits_but_dead_or_wrong_identity_is_closed() -> TestResult {
    if delegated_root_case("root_missing_publication_waits_but_dead_or_wrong_identity_is_closed")? {
        return Ok(());
    }
    let d = tempfile::Builder::new()
        .prefix("hepta-model-startup-q-")
        .tempdir_in("/var/lib")?;
    let mut port = port(d.path())?;
    port.process_attestation = Some(d.path().join("identity.json"));
    let listener = bind(&port.issuer_socket)?;
    let identity_path = port.process_attestation.clone().ok_or("identity missing")?;
    let bytes = std::fs::read(&identity_path)?;
    let record: codex_hepta_contracts::ModelIssuerProcessIdentity = serde_json::from_slice(&bytes)?;
    std::fs::remove_file(&identity_path)?;
    let published = bytes;
    let server = std::thread::spawn(move || -> TestResult {
        let (mut unready, _) = listener.accept()?;
        let mut byte = [0];
        assert_eq!(unready.read(&mut byte)?, 0);
        std::fs::write(&identity_path, published)?;
        std::fs::set_permissions(&identity_path, std::fs::Permissions::from_mode(0o640))?;
        serve_one(&listener)
    });
    assert_eq!(port.load_startup_snapshot()?.now_unix_ms, 12345);
    server.join().map_err(|_| "startup server panicked")??;
    std::fs::remove_file(&port.issuer_socket)?;
    let listener = bind(&port.issuer_socket)?;
    let mut dead = std::process::Command::new("/usr/bin/true").spawn()?;
    let dead_pid = dead.id();
    assert!(dead.wait()?.success());
    let mut wrong = record;
    wrong.pid = dead_pid;
    std::fs::write(
        port.process_attestation
            .as_ref()
            .ok_or("identity missing")?,
        serde_json::to_vec(&wrong)?,
    )?;
    let server = std::thread::spawn(move || -> TestResult {
        let (mut stream, _) = listener.accept()?;
        let mut byte = [0];
        assert_eq!(stream.read(&mut byte)?, 0);
        Ok(())
    });
    assert!(matches!(
        port.load_startup_snapshot(),
        Err(AuthorityTrustError::Invalid)
    ));
    server.join().map_err(|_| "startup server panicked")??;
    Ok(())
}
