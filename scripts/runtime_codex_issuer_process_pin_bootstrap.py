#!/usr/bin/env python3
"""Pin the Linux final-use issuer to an exact protected process instance."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(name: str) -> str:
    return (ROOT / name).read_text()


def write(name: str, value: str) -> None:
    (ROOT / name).write_text(value)


def once(value: str, old: str, new: str, label: str) -> str:
    count = value.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one marker, found {count}")
    return value.replace(old, new, 1)


def patch_authorizer() -> None:
    name = "codex-rs/hepta-infer-worker-host/src/final_use_authorizer.rs"
    value = read(name)
    value = once(
        value,
        "type Result<T> = std::result::Result<T, Box<dyn StdError + Send + Sync>>;\n",
        """type Result<T> = std::result::Result<T, Box<dyn StdError + Send + Sync>>;

/// Exact Linux process identity pinned by the protected authority configuration.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct IssuerProcessIdentity {
    pub executable: PathBuf,
    pub boot_id: String,
    pub start_time_ticks: u64,
}
""",
        "issuer identity type",
    )
    value = once(
        value,
        """    pub issuer_socket: PathBuf,
    pub issuer_uid: u32,
    pub signer_id: String,""",
        """    pub issuer_socket: PathBuf,
    pub issuer_uid: u32,
    /// Required on Linux. Binds the peer credential to one executable instance
    /// in one host boot, preventing a same-UID replacement from being accepted.
    #[serde(default)]
    pub issuer_process: Option<IssuerProcessIdentity>,
    pub signer_id: String,""",
        "config identity field",
    )
    value = once(
        value,
        """    issuer_socket: PathBuf,
    issuer_uid: u32,
    issuer_timeout: Duration,""",
        """    issuer_socket: PathBuf,
    issuer_uid: u32,
    issuer_process: Option<IssuerProcessIdentity>,
    issuer_timeout: Duration,""",
        "authorizer identity field",
    )
    value = once(
        value,
        """        if issuer_timeout.is_zero() || issuer_timeout > MAX_ISSUER_TIMEOUT {
            return Err("final-use issuer timeout must be 1..=30000 ms".into());
        }
        let clock = MonotonicWallClock::capture()?;""",
        """        if issuer_timeout.is_zero() || issuer_timeout > MAX_ISSUER_TIMEOUT {
            return Err("final-use issuer timeout must be 1..=30000 ms".into());
        }
        #[cfg(target_os = "linux")]
        {
            let identity = config
                .issuer_process
                .as_ref()
                .ok_or("Linux final-use authority requires a pinned issuer process")?;
            validate_configured_issuer_process(identity, config.issuer_uid)?;
        }
        let clock = MonotonicWallClock::capture()?;""",
        "validate configured identity",
    )
    value = once(
        value,
        """            issuer_socket: config.issuer_socket,
            issuer_uid: config.issuer_uid,
            issuer_timeout,""",
        """            issuer_socket: config.issuer_socket,
            issuer_uid: config.issuer_uid,
            issuer_process: config.issuer_process,
            issuer_timeout,""",
        "store configured identity",
    )
    value = once(
        value,
        """            #[cfg(target_os = "linux")]
            validate_issuer_peer_process(
                peer.pid()
                    .ok_or("final-use authority peer omitted its process identity")?,
                self.issuer_uid,
            )?;""",
        """            #[cfg(target_os = "linux")]
            {
                let observed = capture_issuer_process_identity(
                    peer.pid()
                        .ok_or("final-use authority peer omitted its process identity")?,
                    self.issuer_uid,
                )?;
                if self.issuer_process.as_ref() != Some(&observed) {
                    return Err::<Vec<u8>, Box<dyn StdError + Send + Sync>>(
                        "connected final-use authority process does not match the pinned instance"
                            .into(),
                    );
                }
            }""",
        "compare exact peer process",
    )
    start = value.index('#[cfg(target_os = "linux")]\nfn validate_issuer_peer_process')
    end = value.index('\n#[cfg(unix)]\nfn validate_issuer_socket', start)
    replacement = r'''#[cfg(target_os = "linux")]
pub fn capture_issuer_process_identity(
    pid: u32,
    issuer_uid: u32,
) -> std::result::Result<IssuerProcessIdentity, Box<dyn StdError + Send + Sync>> {
    use std::os::unix::fs::MetadataExt;

    if pid == 0 {
        return Err("final-use authority peer process id is invalid".into());
    }
    let process_root = PathBuf::from(format!("/proc/{pid}"));
    let process_metadata = std::fs::metadata(&process_root)?;
    if process_metadata.uid() != issuer_uid {
        return Err("final-use authority process owner differs from its peer credential".into());
    }
    let executable = std::fs::read_link(process_root.join("exe"))?;
    validate_issuer_executable(&executable, issuer_uid)?;
    let stat = std::fs::read_to_string(process_root.join("stat"))?;
    let tail = stat
        .rsplit_once(") ")
        .map(|(_, tail)| tail)
        .ok_or("final-use authority process stat is malformed")?;
    let start_time_ticks = tail
        .split_whitespace()
        .nth(19)
        .ok_or("final-use authority process start identity is missing")?
        .parse::<u64>()?;
    if start_time_ticks == 0 {
        return Err("final-use authority process start identity is invalid".into());
    }
    let boot_id = std::fs::read_to_string("/proc/sys/kernel/random/boot_id")?
        .trim()
        .to_string();
    validate_boot_id(&boot_id)?;
    Ok(IssuerProcessIdentity {
        executable,
        boot_id,
        start_time_ticks,
    })
}

#[cfg(not(target_os = "linux"))]
pub fn capture_issuer_process_identity(
    _pid: u32,
    _issuer_uid: u32,
) -> std::result::Result<IssuerProcessIdentity, Box<dyn StdError + Send + Sync>> {
    Err("exact final-use issuer process identity requires Linux".into())
}

#[cfg(target_os = "linux")]
fn validate_configured_issuer_process(
    identity: &IssuerProcessIdentity,
    issuer_uid: u32,
) -> Result<()> {
    validate_issuer_executable(&identity.executable, issuer_uid)?;
    validate_boot_id(&identity.boot_id)?;
    if identity.start_time_ticks == 0 {
        return Err("configured final-use authority process start identity is invalid".into());
    }
    Ok(())
}

#[cfg(target_os = "linux")]
fn validate_issuer_executable(path: &Path, issuer_uid: u32) -> Result<()> {
    use std::os::unix::fs::MetadataExt;

    if !path.is_absolute() {
        return Err("final-use authority executable identity is not absolute".into());
    }
    let metadata = std::fs::metadata(path)?;
    if !metadata.is_file()
        || metadata.mode() & 0o022 != 0
        || (metadata.uid() != 0 && metadata.uid() != issuer_uid)
    {
        return Err("final-use authority executable identity or permissions are unsafe".into());
    }
    Ok(())
}

#[cfg(target_os = "linux")]
fn validate_boot_id(value: &str) -> Result<()> {
    if value.len() != 36
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_hexdigit() || byte == b'-')
    {
        return Err("target-host boot identity is malformed".into());
    }
    Ok(())
}
'''
    value = value[:start] + replacement + value[end:]
    value = once(
        value,
        """    fn current_process_has_a_valid_linux_process_identity() {
        let uid = rustix::process::geteuid().as_raw();
        validate_issuer_peer_process(std::process::id(), uid).unwrap();
    }""",
        """    fn current_process_has_a_valid_linux_process_identity() {
        let uid = rustix::process::geteuid().as_raw();
        let identity = capture_issuer_process_identity(std::process::id(), uid).unwrap();
        validate_configured_issuer_process(&identity, uid).unwrap();
        let mut replacement = identity.clone();
        replacement.start_time_ticks += 1;
        assert_ne!(identity, replacement);
    }""",
        "process identity test",
    )
    write(name, value)


def patch_test_config() -> None:
    name = "codex-rs/hepta-infer-worker-host/src/final_use_authorizer_tests.rs"
    value = read(name)
    value = once(
        value,
        """    FinalUseAuthorizerConfig {
        issuer_socket: socket,
        issuer_uid: rustix::process::geteuid().as_raw(),
        signer_id:""",
        """    let issuer_uid = rustix::process::geteuid().as_raw();
    #[cfg(target_os = "linux")]
    let issuer_process = Some(
        capture_issuer_process_identity(std::process::id(), issuer_uid)
            .expect("capture test issuer process"),
    );
    #[cfg(not(target_os = "linux"))]
    let issuer_process = None;
    FinalUseAuthorizerConfig {
        issuer_socket: socket,
        issuer_uid,
        issuer_process,
        signer_id:""",
        "unit-test config",
    )
    write(name, value)


def patch_product_e2e() -> None:
    name = "codex-rs/hepta-agentd/tests/runtime_codex_product_e2e.rs"
    value = read(name)
    value = once(value, "#![cfg(unix)]", "#![cfg(target_os = \"linux\")]", "Linux e2e")
    value = once(
        value,
        """        issuer_socket: authority_socket,
        issuer_uid,
        signer_id:""",
        """        issuer_socket: authority_socket,
        issuer_uid,
        issuer_process: Some(
            codex_hepta_infer_worker_host::final_use_authorizer::capture_issuer_process_identity(
                std::process::id(),
                issuer_uid,
            )?,
        ),
        signer_id:""",
        "product e2e config",
    )
    write(name, value)


def main() -> None:
    patch_authorizer()
    patch_test_config()
    patch_product_e2e()
    Path(__file__).unlink()


if __name__ == "__main__":
    main()
