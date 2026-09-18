//! Explicit Agentd-owned product caller for `browser.servo`.
//!
//! This one-shot host deliberately has no Browser listener. It opens the real
//! persistent final-use authority, verifies the selected Browser service and
//! Servo worker artifacts, starts the private Browser child, performs one
//! bounded module-port call, and exits. Production daemon activation can reuse
//! the same port once a live revocation owner is composed; it must not invent a
//! permissive default authority.

use std::collections::BTreeSet;
use std::io::Read;
use std::path::PathBuf;

use codex_hepta_agentd::BrowserFinalUseInvocation;
use codex_hepta_agentd::BrowserServoCall;
use codex_hepta_agentd::BrowserServoMethod;
use codex_hepta_agentd::BrowserServoPort;
use codex_hepta_agentd::BrowserServoProcessConfig;
use codex_hepta_agentd::ChildBrowserTransport;
use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_contracts::FinalUseRevocations;
use codex_hepta_contracts::SignedFinalUseGrant;
use serde::Deserialize;
use serde_json::Value;

const MAX_HOST_CONFIG_BYTES: u64 = 65_536;
const MAX_CALL_BYTES: u64 = 65_536;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct HostConfig {
    signer_id: String,
    verifying_key: [u8; 32],
    authority_state_dir: PathBuf,
    authority_epoch: u64,
    revocation_revision: u64,
    revoked_grant_ids: BTreeSet<String>,
    node_path: PathBuf,
    service_path: PathBuf,
    service_sha256: String,
    worker_path: PathBuf,
    worker_sha256: String,
    profile_root: PathBuf,
    journal_path: PathBuf,
    bwrap_path: PathBuf,
    bwrap_sha256: String,
    prlimit_path: PathBuf,
    prlimit_sha256: String,
    max_address_space_bytes: u64,
    max_cpu_seconds: u64,
    max_open_files: u64,
    max_processes: u64,
    driver_timeout_ms: u64,
}

#[derive(Clone, Copy, Deserialize)]
#[serde(rename_all = "snake_case")]
enum HostMethod {
    OpenProfile,
    AdmitEffectGrant,
    ObservePage,
    NavigateOrAct,
    ReconcileOperation,
    ReconcilePersistedOperation,
    CloseProfile,
}

impl HostMethod {
    fn module_method(self) -> BrowserServoMethod {
        match self {
            Self::OpenProfile => BrowserServoMethod::OpenProfile,
            Self::AdmitEffectGrant => BrowserServoMethod::AdmitEffectGrant,
            Self::ObservePage => BrowserServoMethod::ObservePage,
            Self::NavigateOrAct => BrowserServoMethod::NavigateOrAct,
            Self::ReconcileOperation => BrowserServoMethod::ReconcileOperation,
            Self::ReconcilePersistedOperation => BrowserServoMethod::ReconcilePersistedOperation,
            Self::CloseProfile => BrowserServoMethod::CloseProfile,
        }
    }
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct HostCall {
    method: HostMethod,
    input: Value,
    signed_grant: Option<SignedFinalUseGrant>,
    binding: Option<FinalUseBinding>,
}

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let mut args = std::env::args_os().skip(1);
    let config_path = args
        .next()
        .ok_or("usage: hepta-agentd-browser HOST_CONFIG.json < CALL.json")?;
    if args.next().is_some() {
        return Err("usage: hepta-agentd-browser HOST_CONFIG.json < CALL.json".into());
    }
    let config: HostConfig = serde_json::from_slice(&bounded_file(
        PathBuf::from(config_path),
        MAX_HOST_CONFIG_BYTES,
    )?)?;
    let call: HostCall = serde_json::from_slice(&bounded_stdin(MAX_CALL_BYTES)?)?;

    let authority = FinalUseAuthority::open_state_dir(
        &config.authority_state_dir,
        config.signer_id,
        config.verifying_key,
        FinalUseRevocations {
            authority_epoch: config.authority_epoch,
            revision: config.revocation_revision,
            revoked_grant_ids: config.revoked_grant_ids,
        },
    )?;
    let process = BrowserServoProcessConfig {
        node_path: config.node_path,
        service_path: config.service_path,
        service_sha256: parse_digest(&config.service_sha256, "service_sha256")?,
        worker_path: config.worker_path,
        worker_sha256: parse_digest(&config.worker_sha256, "worker_sha256")?,
        profile_root: config.profile_root,
        journal_path: config.journal_path,
        bwrap_path: config.bwrap_path,
        bwrap_sha256: parse_digest(&config.bwrap_sha256, "bwrap_sha256")?,
        prlimit_path: config.prlimit_path,
        prlimit_sha256: parse_digest(&config.prlimit_sha256, "prlimit_sha256")?,
        max_address_space_bytes: config.max_address_space_bytes,
        max_cpu_seconds: config.max_cpu_seconds,
        max_open_files: config.max_open_files,
        max_processes: config.max_processes,
        driver_timeout_ms: config.driver_timeout_ms,
    };
    let transport = ChildBrowserTransport::spawn(&process)?;
    let port = BrowserServoPort::new(authority, transport);
    let module_method = call.method.module_method();
    let request = if matches!(module_method, BrowserServoMethod::NavigateOrAct) {
        let signed_grant = call
            .signed_grant
            .ok_or("navigate_or_act requires independently signed final-use grant")?;
        let binding = call
            .binding
            .ok_or("navigate_or_act requires exact FinalUseBinding")?;
        BrowserServoCall::effect(
            call.input,
            BrowserFinalUseInvocation {
                signed_grant,
                binding,
            },
        )?
    } else {
        if call.signed_grant.is_some() || call.binding.is_some() {
            return Err("non-effect Browser calls must not carry final-use authority".into());
        }
        BrowserServoCall::read(module_method, call.input)?
    };
    let result = port.call(request)?;
    serde_json::to_writer(std::io::stdout(), &result)?;
    println!();
    Ok(())
}

fn bounded_file(path: PathBuf, maximum: u64) -> Result<Vec<u8>, Box<dyn std::error::Error>> {
    let mut bytes = Vec::new();
    std::fs::File::open(&path)?
        .take(maximum + 1)
        .read_to_end(&mut bytes)?;
    if bytes.len() as u64 > maximum {
        return Err(format!("{} exceeds {maximum} bytes", path.display()).into());
    }
    Ok(bytes)
}

fn bounded_stdin(maximum: u64) -> Result<Vec<u8>, Box<dyn std::error::Error>> {
    let mut bytes = Vec::new();
    std::io::stdin().take(maximum + 1).read_to_end(&mut bytes)?;
    if bytes.len() as u64 > maximum {
        return Err(format!("Browser call exceeds {maximum} bytes").into());
    }
    Ok(bytes)
}

fn parse_digest(value: &str, name: &str) -> Result<[u8; 32], Box<dyn std::error::Error>> {
    if value.len() != 64
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_hexdigit() && !byte.is_ascii_uppercase())
    {
        return Err(format!("{name} must be lowercase SHA-256 hex").into());
    }
    let mut output = [0u8; 32];
    for (index, slot) in output.iter_mut().enumerate() {
        let start = index * 2;
        *slot = u8::from_str_radix(&value[start..start + 2], 16)?;
    }
    Ok(output)
}
