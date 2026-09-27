#!/usr/bin/env python3
"""One-shot exact-source issuer process-instance hardening for runtime.codex."""
from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXPECTED = {
    "codex-rs/hepta-infer-worker-host/src/final_use_authorizer.rs": "c7dc77e1d5f9b1bbbf782ec38ea7ab3528b7745a",
    "codex-rs/hepta-infer-worker-host/src/final_use_authorizer_tests.rs": "9b1bb255c443cdca02546a54f42cd06583f0493e",
    "codex-rs/hepta-agentd/tests/runtime_codex_product_e2e.rs": "bd41d2a22e4b78bd9b465d9928f7623366ed215a",
}


def read(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


def write(name: str, text: str) -> None:
    (ROOT / name).write_text(text, encoding="utf-8")


def verify(name: str, expected: str) -> None:
    actual = subprocess.check_output(["git", "hash-object", "--", name], cwd=ROOT, text=True).strip()
    if actual != expected:
        raise SystemExit(f"{name}: expected {expected}, got {actual}")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one match, found {count}")
    return text.replace(old, new, 1)


def replace_between(text: str, start: str, end: str, replacement: str, label: str) -> str:
    first = text.find(start)
    if first < 0 or text.find(start, first + 1) >= 0:
        raise SystemExit(f"{label}: missing or ambiguous start marker")
    stop = text.find(end, first + len(start))
    if stop < 0:
        raise SystemExit(f"{label}: end marker not found")
    return text[:first] + replacement + text[stop:]


def patch_authorizer() -> None:
    name = "codex-rs/hepta-infer-worker-host/src/final_use_authorizer.rs"
    text = read(name)
    text = replace_once(
        text,
        "use serde::Serialize;\n",
        "use serde::Serialize;\n#[cfg(target_os = \"linux\")]\nuse sha2::Digest;\n#[cfg(target_os = \"linux\")]\nuse sha2::Sha256;\n",
        "Linux hashing imports",
    )
    text = replace_once(
        text,
        "const MAX_FORWARD_CLOCK_DRIFT: Duration = Duration::from_secs(300);\n",
        "const MAX_FORWARD_CLOCK_DRIFT: Duration = Duration::from_secs(300);\n"
        "#[cfg(target_os = \"linux\")]\nconst MAX_PROC_TEXT_BYTES: usize = 64 * 1024;\n"
        "#[cfg(target_os = \"linux\")]\nconst MAX_ISSUER_EXECUTABLE_BYTES: u64 = 512 * 1024 * 1024;\n",
        "process identity constants",
    )
    anchor = """/// Protected host configuration for the independent final-use authority port.
///
/// `verifying_key` is public. The private signing key is intentionally absent.
#[derive(Clone, Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct FinalUseAuthorizerConfig {"""
    replacement = """/// Exact Linux process instance expected behind the authority socket.
///
/// PID and start time prevent a same-binary peer from replacing the configured
/// issuer instance. Executable, cgroup and boot digests bind its code, service
/// placement and host boot. The connected process is sampled before and after
/// every grant exchange.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct IssuerProcessIdentityConfig {
    pub expected_pid: u32,
    pub expected_start_time_ticks: u64,
    pub executable_sha256: String,
    pub cgroup_sha256: String,
    pub boot_id_sha256: String,
}

/// Protected host configuration for the independent final-use authority port.
///
/// `verifying_key` is public. The private signing key is intentionally absent.
#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct FinalUseAuthorizerConfig {"""
    text = replace_once(text, anchor, replacement, "process identity config")
    text = replace_once(
        text,
        "    pub issuer_timeout_ms: u64,\n}",
        "    pub issuer_timeout_ms: u64,\n    #[serde(default)]\n    pub issuer_process_identity: Option<IssuerProcessIdentityConfig>,\n}",
        "authorizer config field",
    )
    text = replace_once(
        text,
        "    issuer_timeout: Duration,\n    authority: FinalUseAuthority,",
        "    issuer_timeout: Duration,\n    issuer_process_identity: Option<IssuerProcessIdentityConfig>,\n    authority: FinalUseAuthority,",
        "authorizer identity field",
    )
    old = """    pub fn open(config_path: &Path) -> Result<Self> {
        let config: FinalUseAuthorizerConfig =
            serde_json::from_slice(&read_private_config(config_path)?)?;
        Self::from_config(config)
    }

    pub fn from_config(config: FinalUseAuthorizerConfig) -> Result<Self> {
        if !config.issuer_socket.is_absolute() || !config.authority_state_dir.is_absolute() {
            return Err("final-use authority socket and state directory must be absolute".into());
        }
        let issuer_timeout = Duration::from_millis(config.issuer_timeout_ms);
        if issuer_timeout.is_zero() || issuer_timeout > MAX_ISSUER_TIMEOUT {
            return Err("final-use issuer timeout must be 1..=30000 ms".into());
        }
        let clock = MonotonicWallClock::capture()?;"""
    new = """    pub fn open(config_path: &Path) -> Result<Self> {
        let config: FinalUseAuthorizerConfig =
            serde_json::from_slice(&read_private_config(config_path)?)?;
        Self::from_config_inner(config, cfg!(target_os = "linux"))
    }

    /// Test/composition constructor. Production configuration is opened through
    /// `open`, which requires exact Linux process-instance identity.
    pub fn from_config(config: FinalUseAuthorizerConfig) -> Result<Self> {
        Self::from_config_inner(config, false)
    }

    fn from_config_inner(
        config: FinalUseAuthorizerConfig,
        require_process_identity: bool,
    ) -> Result<Self> {
        if !config.issuer_socket.is_absolute() || !config.authority_state_dir.is_absolute() {
            return Err("final-use authority socket and state directory must be absolute".into());
        }
        let issuer_timeout = Duration::from_millis(config.issuer_timeout_ms);
        if issuer_timeout.is_zero() || issuer_timeout > MAX_ISSUER_TIMEOUT {
            return Err("final-use issuer timeout must be 1..=30000 ms".into());
        }
        if let Some(expected) = config.issuer_process_identity.as_ref() {
            validate_process_identity_config(expected)?;
        } else if require_process_identity {
            return Err(
                "Linux production final-use authority requires exact issuer process identity"
                    .into(),
            );
        }
        #[cfg(not(target_os = "linux"))]
        if config.issuer_process_identity.is_some() {
            return Err("issuer process identity is currently supported only on Linux".into());
        }
        let clock = MonotonicWallClock::capture()?;"""
    text = replace_once(text, old, new, "constructor hardening")
    text = replace_once(
        text,
        "            issuer_uid: config.issuer_uid,\n            issuer_timeout,\n            authority,",
        "            issuer_uid: config.issuer_uid,\n            issuer_timeout,\n            issuer_process_identity: config.issuer_process_identity,\n            authority,",
        "constructor field assignment",
    )
    old = """            let peer = stream.peer_cred()?;
            validate_issuer_peer_uid(peer.uid(), self.issuer_uid)?;
            #[cfg(target_os = "linux")]
            validate_issuer_peer_process(
                peer.pid()
                    .ok_or("final-use authority peer omitted its process identity")?,
                self.issuer_uid,
            )?;
            stream.write_all(&request_len.to_be_bytes()).await?;"""
    new = """            let peer = stream.peer_cred()?;
            validate_issuer_peer_uid(peer.uid(), self.issuer_uid)?;
            #[cfg(target_os = "linux")]
            let process_guard = validate_connected_issuer_process(
                peer.pid(),
                self.issuer_process_identity.as_ref(),
            )?;
            #[cfg(not(target_os = "linux"))]
            debug_assert!(self.issuer_process_identity.is_none());
            stream.write_all(&request_len.to_be_bytes()).await?;"""
    text = replace_once(text, old, new, "connected process guard")
    text = replace_once(
        text,
        """            let mut response = vec![0_u8; response_len];
            stream.read_exact(&mut response).await?;
            Ok(response)""",
        """            let mut response = vec![0_u8; response_len];
            stream.read_exact(&mut response).await?;
            #[cfg(target_os = "linux")]
            if let Some(process_guard) = process_guard {
                process_guard.revalidate()?;
            }
            Ok(response)""",
        "post-exchange process revalidation",
    )

    start = """#[cfg(target_os = "linux")]
fn validate_issuer_peer_process(pid: u32, issuer_uid: u32) -> Result<()> {"""
    end = """#[cfg(unix)]
fn validate_issuer_socket(path: &Path, issuer_uid: u32) -> Result<()> {"""
    process_code = r'''fn validate_process_identity_config(expected: &IssuerProcessIdentityConfig) -> Result<()> {
    if expected.expected_pid == 0 || expected.expected_start_time_ticks == 0 {
        return Err("issuer PID/start-time identity must be nonzero".into());
    }
    for (value, field) in [
        (&expected.executable_sha256, "issuer executable"),
        (&expected.cgroup_sha256, "issuer cgroup"),
        (&expected.boot_id_sha256, "host boot id"),
    ] {
        if value.len() != 64
            || value.bytes().all(|byte| byte == b'0')
            || !value
                .bytes()
                .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
        {
            return Err(format!("invalid {field} SHA-256 digest").into());
        }
    }
    Ok(())
}

#[cfg(target_os = "linux")]
#[derive(Clone, Debug, Eq, PartialEq)]
struct IssuerProcessSnapshot {
    pid: u32,
    start_time_ticks: u64,
    executable_sha256: String,
    cgroup_sha256: String,
    boot_id_sha256: String,
}

#[cfg(target_os = "linux")]
struct IssuerProcessGuard {
    initial: IssuerProcessSnapshot,
    expected: IssuerProcessIdentityConfig,
}

#[cfg(target_os = "linux")]
impl IssuerProcessGuard {
    fn revalidate(&self) -> Result<()> {
        let current = capture_issuer_process_identity(self.initial.pid)?;
        if current != self.initial {
            return Err("final-use authority process identity changed during exchange".into());
        }
        validate_issuer_process_snapshot(&current, &self.expected)
    }
}

#[cfg(target_os = "linux")]
fn validate_connected_issuer_process(
    pid: Option<u32>,
    expected: Option<&IssuerProcessIdentityConfig>,
) -> Result<Option<IssuerProcessGuard>> {
    let Some(expected) = expected else {
        return Ok(None);
    };
    let pid = pid.ok_or("connected final-use authority peer omitted its Linux PID")?;
    if pid != expected.expected_pid {
        return Err("connected final-use authority PID differs from configured issuer".into());
    }
    let initial = capture_issuer_process_identity(pid)?;
    validate_issuer_process_snapshot(&initial, expected)?;
    Ok(Some(IssuerProcessGuard {
        initial,
        expected: expected.clone(),
    }))
}

#[cfg(target_os = "linux")]
fn validate_issuer_process_snapshot(
    actual: &IssuerProcessSnapshot,
    expected: &IssuerProcessIdentityConfig,
) -> Result<()> {
    validate_process_identity_config(expected)?;
    if actual.pid != expected.expected_pid
        || actual.start_time_ticks != expected.expected_start_time_ticks
        || actual.executable_sha256 != expected.executable_sha256
        || actual.cgroup_sha256 != expected.cgroup_sha256
        || actual.boot_id_sha256 != expected.boot_id_sha256
    {
        return Err("connected final-use authority process identity mismatch".into());
    }
    Ok(())
}

#[cfg(target_os = "linux")]
fn capture_issuer_process_identity(pid: u32) -> Result<IssuerProcessSnapshot> {
    if pid == 0 {
        return Err("connected final-use authority peer PID is invalid".into());
    }
    let proc_root = PathBuf::from(format!("/proc/{pid}"));
    let stat = read_bounded(&proc_root.join("stat"), MAX_PROC_TEXT_BYTES)?;
    let start_time_ticks = parse_proc_start_time_ticks(std::str::from_utf8(&stat)?)?;

    let executable = std::fs::File::open(proc_root.join("exe"))?;
    let metadata = executable.metadata()?;
    if !metadata.is_file() || metadata.len() > MAX_ISSUER_EXECUTABLE_BYTES {
        return Err("final-use authority executable is not a bounded regular file".into());
    }
    let executable_sha256 = sha256_reader(executable, MAX_ISSUER_EXECUTABLE_BYTES)?;
    let cgroup_sha256 = sha256_bytes(&canonical_proc_text(read_bounded(
        &proc_root.join("cgroup"),
        MAX_PROC_TEXT_BYTES,
    )?));
    let boot_id_sha256 = sha256_bytes(&canonical_proc_text(read_bounded(
        Path::new("/proc/sys/kernel/random/boot_id"),
        256,
    )?));
    Ok(IssuerProcessSnapshot {
        pid,
        start_time_ticks,
        executable_sha256,
        cgroup_sha256,
        boot_id_sha256,
    })
}

#[cfg(target_os = "linux")]
fn parse_proc_start_time_ticks(stat: &str) -> Result<u64> {
    let close = stat
        .rfind(')')
        .ok_or("issuer /proc stat omitted process command terminator")?;
    let fields: Vec<&str> = stat[close + 1..].split_whitespace().collect();
    let value = fields
        .get(19)
        .ok_or("issuer /proc stat omitted process start time")?
        .parse::<u64>()?;
    if value == 0 {
        return Err("issuer process start time is invalid".into());
    }
    Ok(value)
}

#[cfg(target_os = "linux")]
fn read_bounded(path: &Path, maximum: usize) -> Result<Vec<u8>> {
    let mut file = std::fs::File::open(path)?;
    let mut value = Vec::new();
    file.by_ref()
        .take(u64::try_from(maximum.checked_add(1).ok_or("read bound overflow")?)?)
        .read_to_end(&mut value)?;
    if value.len() > maximum {
        return Err(format!("{} exceeds its identity bound", path.display()).into());
    }
    Ok(value)
}

#[cfg(target_os = "linux")]
fn canonical_proc_text(mut value: Vec<u8>) -> Vec<u8> {
    while value.last().is_some_and(|byte| byte.is_ascii_whitespace()) {
        value.pop();
    }
    value
}

#[cfg(target_os = "linux")]
fn sha256_reader(mut reader: impl Read, maximum: u64) -> Result<String> {
    let mut hasher = Sha256::new();
    let mut buffer = [0_u8; 64 * 1024];
    let mut total = 0_u64;
    loop {
        let read = reader.read(&mut buffer)?;
        if read == 0 {
            break;
        }
        total = total
            .checked_add(u64::try_from(read)?)
            .ok_or("issuer executable length overflow")?;
        if total > maximum {
            return Err("issuer executable exceeds its identity bound".into());
        }
        hasher.update(&buffer[..read]);
    }
    Ok(format!("{:x}", hasher.finalize()))
}

#[cfg(target_os = "linux")]
fn sha256_bytes(value: &[u8]) -> String {
    format!("{:x}", Sha256::digest(value))
}

#[cfg(unix)]
fn validate_issuer_socket(path: &Path, issuer_uid: u32) -> Result<()> {'''
    text = replace_between(text, start, end, process_code, "replace process shape check")

    old_test = """    #[cfg(target_os = "linux")]
    #[test]
    fn current_process_has_a_valid_linux_process_identity() {
        let uid = rustix::process::geteuid().as_raw();
        validate_issuer_peer_process(std::process::id(), uid).unwrap();
    }
"""
    new_test = """    #[cfg(target_os = "linux")]
    #[test]
    fn current_process_has_a_stable_linux_process_identity() {
        let snapshot = capture_issuer_process_identity(std::process::id()).unwrap();
        let expected = IssuerProcessIdentityConfig {
            expected_pid: snapshot.pid,
            expected_start_time_ticks: snapshot.start_time_ticks,
            executable_sha256: snapshot.executable_sha256.clone(),
            cgroup_sha256: snapshot.cgroup_sha256.clone(),
            boot_id_sha256: snapshot.boot_id_sha256.clone(),
        };
        validate_issuer_process_snapshot(&snapshot, &expected).unwrap();
    }
"""
    text = replace_once(text, old_test, new_test, "hardening process test")
    write(name, text)


def patch_tests() -> None:
    name = "codex-rs/hepta-infer-worker-host/src/final_use_authorizer_tests.rs"
    text = read(name)
    text = replace_once(
        text,
        "        issuer_timeout_ms: 2_000,\n    }",
        "        issuer_timeout_ms: 2_000,\n        issuer_process_identity: None,\n    }",
        "test config identity field",
    )
    anchor = """/// Bounded test issuer over the production Unix protocol. Only this separate
/// test task holds the signing key; the worker receives the verifier-only port."""
    addition = r'''#[cfg(target_os = "linux")]
fn current_process_identity() -> Result<IssuerProcessIdentityConfig> {
    let snapshot = capture_issuer_process_identity(std::process::id())?;
    Ok(IssuerProcessIdentityConfig {
        expected_pid: snapshot.pid,
        expected_start_time_ticks: snapshot.start_time_ticks,
        executable_sha256: snapshot.executable_sha256,
        cgroup_sha256: snapshot.cgroup_sha256,
        boot_id_sha256: snapshot.boot_id_sha256,
    })
}

#[cfg(target_os = "linux")]
#[test]
fn linux_issuer_identity_rejects_same_uid_instance_substitution() -> Result<()> {
    let expected = current_process_identity()?;
    let guard = validate_connected_issuer_process(Some(expected.expected_pid), Some(&expected))?
        .ok_or("expected process guard")?;
    guard.revalidate()?;

    let mut wrong = expected.clone();
    wrong.expected_pid = wrong.expected_pid.checked_add(1).unwrap_or(1);
    assert!(validate_connected_issuer_process(Some(expected.expected_pid), Some(&wrong)).is_err());
    wrong = expected.clone();
    wrong.expected_start_time_ticks = wrong.expected_start_time_ticks.saturating_add(1);
    assert!(validate_connected_issuer_process(Some(expected.expected_pid), Some(&wrong)).is_err());
    wrong = expected.clone();
    wrong.executable_sha256 = "1".repeat(64);
    assert!(validate_connected_issuer_process(Some(expected.expected_pid), Some(&wrong)).is_err());
    wrong = expected.clone();
    wrong.cgroup_sha256 = "2".repeat(64);
    assert!(validate_connected_issuer_process(Some(expected.expected_pid), Some(&wrong)).is_err());
    wrong = expected.clone();
    wrong.boot_id_sha256 = "3".repeat(64);
    assert!(validate_connected_issuer_process(Some(expected.expected_pid), Some(&wrong)).is_err());
    assert!(validate_connected_issuer_process(None, Some(&expected)).is_err());
    Ok(())
}

#[cfg(target_os = "linux")]
#[tokio::test]
async fn linux_peer_identity_is_rechecked_after_grant_exchange() -> Result<()> {
    let directory = tempfile::tempdir()?;
    let (listener, socket) = listener(directory.path(), "process-bound.sock").await?;
    let signer = SigningKey::from_bytes(&[45; 32]);
    let mut value = config(directory.path(), socket, signer.verifying_key().to_bytes());
    value.issuer_process_identity = Some(current_process_identity()?);
    let authorizer = UnixFinalUseAuthorizer::from_config(value)?;
    let server_signer = signer.clone();
    let server = tokio::spawn(async move {
        serve_once(&listener, Some(&server_signer), revocations(1, &[]), 11, None).await
    });
    let expected = binding(41);
    let token = authorizer.claim(expected.clone()).await?;
    if !token.enter(&expected)?.matches(&expected) {
        return Err("process-bound token lost its exact binding".into());
    }
    server.await??;
    Ok(())
}

#[cfg(target_os = "linux")]
#[test]
fn linux_production_open_requires_process_identity() -> Result<()> {
    let directory = tempfile::tempdir()?;
    std::fs::set_permissions(directory.path(), std::fs::Permissions::from_mode(0o700))?;
    let signer = SigningKey::from_bytes(&[46; 32]);
    let config_path = directory.path().join("authority.json");
    let value = config(
        directory.path(),
        directory.path().join("unused.sock"),
        signer.verifying_key().to_bytes(),
    );
    std::fs::write(&config_path, serde_json::to_vec(&value)?)?;
    std::fs::set_permissions(&config_path, std::fs::Permissions::from_mode(0o600))?;
    assert!(UnixFinalUseAuthorizer::open(&config_path).is_err());
    Ok(())
}

'''
    text = replace_once(text, anchor, addition + anchor, "process instance tests")
    write(name, text)


def patch_product() -> None:
    name = "codex-rs/hepta-agentd/tests/runtime_codex_product_e2e.rs"
    text = read(name)
    text = replace_once(
        text,
        "        issuer_timeout_ms: 2_000,\n    })",
        "        issuer_timeout_ms: 2_000,\n        // Test-only constructor. Production `open` requires exact Linux\n        // PID/start-time/executable/cgroup/boot identity.\n        issuer_process_identity: None,\n    })",
        "product test config identity field",
    )
    write(name, text)


def main() -> None:
    for name, expected in EXPECTED.items():
        verify(name, expected)
    patch_authorizer()
    patch_tests()
    patch_product()
    (ROOT / ".github/workflows/runtime-codex-stage2-identity-bootstrap.yml").unlink(missing_ok=True)
    Path(__file__).unlink(missing_ok=True)


if __name__ == "__main__":
    main()
