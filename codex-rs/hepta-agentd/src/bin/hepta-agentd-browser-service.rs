//! Long-running Agentd-owned private host for `browser.servo`.
//!
//! The process owns one restartable `PersistentBrowserServoControl` for its
//! lifetime and exposes no network listener. Requests and responses use a
//! bounded, sequence-checked, length-prefixed JSON protocol over inherited
//! stdin/stdout. Final-use grants are accepted only for `navigate_or_act`.
//! Before startup, the complete JavaScript service dependency closure is
//! verified against an exact SHA-256 manifest.

use std::collections::{BTreeMap, BTreeSet};
use std::fs::{self, File};
use std::io::{BufReader, BufWriter, Read, Write};
use std::path::{Path, PathBuf};
use std::time::Instant;

use codex_hepta_agentd::BrowserFinalUseInvocation;
use codex_hepta_agentd::BrowserServoCall;
use codex_hepta_agentd::BrowserServoError;
use codex_hepta_agentd::BrowserServoHostConfig;
use codex_hepta_agentd::BrowserServoMethod;
use codex_hepta_agentd::open_browser_servo_port_from_file;
use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_contracts::SignedFinalUseGrant;
use serde::Deserialize;
use serde_json::Value;
use serde_json::json;
use sha2::{Digest, Sha256};

const REQUEST_SCHEMA: &str = "hepta.agentd.browser-service-request.v1";
const RESPONSE_SCHEMA: &str = "hepta.agentd.browser-service-response.v1";
const METRIC_SCHEMA: &str = "hepta.browser.agentd-metric.v1";
const CLOSURE_SCHEMA: &str = "hepta.browser.service-closure.v1";
const PROTOCOL_VERSION: u64 = 1;
const CLOSURE_VERSION: u64 = 1;
const MAX_FRAME_BYTES: usize = 1_048_576;
const MAX_ERROR_CHARS: usize = 512;
const MAX_CONFIG_BYTES: u64 = 65_536;
const MAX_CLOSURE_MANIFEST_BYTES: u64 = 131_072;
const MAX_CLOSURE_FILE_BYTES: u64 = 16 * 1024 * 1024;

const REQUIRED_CLOSURE: [(&str, &str); 16] = [
    ("agentd_service_main", "agentd-service-main.js"),
    ("agentd_service", "agentd-service.js"),
    ("agentd_protocol", "agentd-protocol.js"),
    ("action", "action.js"),
    ("effect_egress_gate", "effect-egress-gate.js"),
    ("effect_network_driver", "effect-network-driver.js"),
    ("egress_broker", "egress-broker.js"),
    ("journal", "journal.js"),
    ("observation_redactor", "observation-redactor.js"),
    ("persisted_reconciler", "persisted-reconciler.js"),
    ("runtime", "runtime.js"),
    ("runtime_host", "runtime-host.js"),
    ("runtime_contract", "runtime-contract.js"),
    ("runtime_boundary", "runtime-boundary.js"),
    ("worker_driver", "worker-driver.js"),
    ("worker_protocol", "worker-protocol.js"),
];

#[derive(Clone, Copy, Debug, Deserialize)]
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

    fn wire_name(self) -> &'static str {
        match self {
            Self::OpenProfile => "open_profile",
            Self::AdmitEffectGrant => "admit_effect_grant",
            Self::ObservePage => "observe_page",
            Self::NavigateOrAct => "navigate_or_act",
            Self::ReconcileOperation => "reconcile_operation",
            Self::ReconcilePersistedOperation => "reconcile_persisted_operation",
            Self::CloseProfile => "close_profile",
        }
    }
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct ServiceRequest {
    schema: String,
    protocol_version: u64,
    sequence: u64,
    method: HostMethod,
    input: Value,
    signed_grant: Option<SignedFinalUseGrant>,
    binding: Option<FinalUseBinding>,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct ServiceClosureManifest {
    schema: String,
    version: u64,
    entries: BTreeMap<String, ServiceClosureEntry>,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct ServiceClosureEntry {
    path: PathBuf,
    sha256: String,
}

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let mut args = std::env::args_os().skip(1);
    let config_path = PathBuf::from(
        args.next()
            .ok_or("usage: hepta-agentd-browser-service HOST_CONFIG.json SERVICE_CLOSURE.json")?,
    );
    let closure_path = PathBuf::from(
        args.next()
            .ok_or("usage: hepta-agentd-browser-service HOST_CONFIG.json SERVICE_CLOSURE.json")?,
    );
    if args.next().is_some() {
        return Err(
            "usage: hepta-agentd-browser-service HOST_CONFIG.json SERVICE_CLOSURE.json".into(),
        );
    }

    let config_bytes = read_bounded_regular(&config_path, MAX_CONFIG_BYTES, "Browser config")?;
    let config: BrowserServoHostConfig = serde_json::from_slice(&config_bytes)
        .map_err(|error| format!("Browser runtime config is invalid JSON: {error}"))?;
    verify_service_closure(&closure_path, &config.service_path)?;
    let control = open_browser_servo_port_from_file(&config_path)?;

    let stdin = std::io::stdin();
    let stdout = std::io::stdout();
    let mut reader = BufReader::new(stdin.lock());
    let mut writer = BufWriter::new(stdout.lock());
    let mut expected_sequence = 1_u64;
    let mut requests_total = 0_u64;
    let mut failures_total = 0_u64;

    while let Some(bytes) = read_frame(&mut reader)? {
        let started = Instant::now();
        let request: ServiceRequest = serde_json::from_slice(&bytes)
            .map_err(|error| format!("Browser service request is invalid JSON: {error}"))?;
        let ServiceRequest {
            schema,
            protocol_version,
            sequence,
            method,
            input,
            signed_grant,
            binding,
        } = request;
        if schema != REQUEST_SCHEMA || protocol_version != PROTOCOL_VERSION {
            return Err("Browser service request schema/version is unsupported".into());
        }
        if sequence != expected_sequence || sequence == 0 {
            return Err("Browser service request sequence is not monotonic".into());
        }
        expected_sequence = expected_sequence
            .checked_add(1)
            .ok_or("Browser service request sequence exhausted")?;
        if !input.is_object() {
            return Err("Browser service input must be a JSON object".into());
        }

        let method_name = method.wire_name();
        let method = method.module_method();
        let call = if matches!(method, BrowserServoMethod::NavigateOrAct) {
            match (signed_grant, binding) {
                (Some(signed_grant), Some(binding)) => BrowserServoCall::effect(
                    input,
                    BrowserFinalUseInvocation {
                        signed_grant,
                        binding,
                    },
                ),
                _ => Err(BrowserServoError::Invalid(
                    "navigate_or_act requires signed final-use grant and exact binding".into(),
                )),
            }
        } else if signed_grant.is_some() || binding.is_some() {
            Err(BrowserServoError::Invalid(
                "non-effect Browser calls must not carry final-use authority".into(),
            ))
        } else {
            BrowserServoCall::read(method, input)
        };

        let result = call.and_then(|call| control.call(call));
        let ok = result.is_ok();
        requests_total = requests_total.saturating_add(1);
        if !ok {
            failures_total = failures_total.saturating_add(1);
        }
        let response = match result {
            Ok(result) => json!({
                "schema": RESPONSE_SCHEMA,
                "protocolVersion": PROTOCOL_VERSION,
                "sequence": sequence,
                "ok": true,
                "result": result,
            }),
            Err(error) => json!({
                "schema": RESPONSE_SCHEMA,
                "protocolVersion": PROTOCOL_VERSION,
                "sequence": sequence,
                "ok": false,
                "error": error
                    .to_string()
                    .chars()
                    .take(MAX_ERROR_CHARS)
                    .collect::<String>(),
            }),
        };
        write_frame(&mut writer, &serde_json::to_vec(&response)?)?;

        let duration_ms = u64::try_from(started.elapsed().as_millis()).unwrap_or(u64::MAX);
        eprintln!(
            "{}",
            json!({
                "schema": METRIC_SCHEMA,
                "sequence": sequence,
                "method": method_name,
                "ok": ok,
                "durationMs": duration_ms,
                "requestsTotal": requests_total,
                "failuresTotal": failures_total,
            })
        );
    }
    Ok(())
}

fn verify_service_closure(
    manifest_path: &Path,
    configured_service_path: &Path,
) -> Result<(), Box<dyn std::error::Error>> {
    let bytes = read_bounded_regular(
        manifest_path,
        MAX_CLOSURE_MANIFEST_BYTES,
        "Browser service closure manifest",
    )?;
    let manifest: ServiceClosureManifest = serde_json::from_slice(&bytes)
        .map_err(|error| format!("Browser service closure manifest is invalid JSON: {error}"))?;
    if manifest.schema != CLOSURE_SCHEMA || manifest.version != CLOSURE_VERSION {
        return Err("Browser service closure schema/version is unsupported".into());
    }
    let required = REQUIRED_CLOSURE
        .iter()
        .map(|(role, _)| (*role).to_string())
        .collect::<BTreeSet<_>>();
    let actual = manifest.entries.keys().cloned().collect::<BTreeSet<_>>();
    if actual != required {
        return Err(
            "Browser service closure roles are incomplete or contain unknown entries".into(),
        );
    }

    for (role, expected_name) in REQUIRED_CLOSURE {
        let entry = manifest
            .entries
            .get(role)
            .ok_or("Browser service closure role is missing")?;
        if !entry.path.is_absolute()
            || entry.path.file_name().and_then(|value| value.to_str()) != Some(expected_name)
        {
            return Err(format!("Browser service closure role {role} has an invalid path").into());
        }
        verify_closure_file(&entry.path, &entry.sha256, role)?;
    }
    let service = &manifest
        .entries
        .get("agentd_service_main")
        .ok_or("Browser service main closure entry is missing")?
        .path;
    if service != configured_service_path {
        return Err("Browser config service_path is outside the verified service closure".into());
    }
    Ok(())
}

fn verify_closure_file(
    path: &Path,
    expected_sha256: &str,
    role: &str,
) -> Result<(), Box<dyn std::error::Error>> {
    if expected_sha256.len() != 64
        || !expected_sha256
            .bytes()
            .all(|byte| byte.is_ascii_hexdigit() && !byte.is_ascii_uppercase())
    {
        return Err(format!("Browser service closure digest for {role} is invalid").into());
    }
    if fs::canonicalize(path)? != path {
        return Err(format!("Browser service closure path for {role} is not canonical").into());
    }
    let before = fs::symlink_metadata(path)?;
    if !before.is_file()
        || before.file_type().is_symlink()
        || before.len() == 0
        || before.len() > MAX_CLOSURE_FILE_BYTES
    {
        return Err(
            format!("Browser service closure file for {role} is unsafe or unbounded").into(),
        );
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        if before.permissions().mode() & 0o022 != 0 {
            return Err(
                format!("Browser service closure file for {role} is group/world writable").into(),
            );
        }
    }

    let mut file = File::open(path)?;
    let opened = file.metadata()?;
    let after = fs::symlink_metadata(path)?;
    #[cfg(unix)]
    {
        use std::os::unix::fs::MetadataExt;
        if opened.dev() != before.dev()
            || opened.ino() != before.ino()
            || opened.dev() != after.dev()
            || opened.ino() != after.ino()
        {
            return Err(
                format!("Browser service closure file for {role} changed during open").into(),
            );
        }
    }
    let mut bytes = Vec::with_capacity(usize::try_from(opened.len()).unwrap_or(0));
    file.read_to_end(&mut bytes)?;
    let actual = format!("{:x}", Sha256::digest(&bytes));
    if actual != expected_sha256 {
        return Err(format!("Browser service closure digest mismatch for {role}").into());
    }
    Ok(())
}

fn read_bounded_regular(
    path: &Path,
    maximum: u64,
    label: &str,
) -> Result<Vec<u8>, Box<dyn std::error::Error>> {
    if !path.is_absolute() {
        return Err(format!("{label} path must be absolute").into());
    }
    let metadata = fs::symlink_metadata(path)?;
    if !metadata.is_file()
        || metadata.file_type().is_symlink()
        || metadata.len() == 0
        || metadata.len() > maximum
    {
        return Err(format!("{label} must be a bounded regular non-symlink file").into());
    }
    let mut file = File::open(path)?;
    let mut bytes = Vec::with_capacity(usize::try_from(metadata.len()).unwrap_or(0));
    file.read_to_end(&mut bytes)?;
    if bytes.is_empty() || bytes.len() as u64 > maximum {
        return Err(format!("{label} byte size is outside bounds").into());
    }
    Ok(bytes)
}

fn read_frame(reader: &mut impl Read) -> Result<Option<Vec<u8>>, Box<dyn std::error::Error>> {
    let mut prefix = [0_u8; 4];
    match reader.read(&mut prefix[..1])? {
        0 => return Ok(None),
        1 => {}
        _ => unreachable!("one-byte read returned more than one byte"),
    }
    reader.read_exact(&mut prefix[1..])?;
    let length = u32::from_be_bytes(prefix) as usize;
    if length == 0 || length > MAX_FRAME_BYTES {
        return Err("Browser service request frame length is outside bounds".into());
    }
    let mut body = vec![0_u8; length];
    reader.read_exact(&mut body)?;
    Ok(Some(body))
}

fn write_frame(writer: &mut impl Write, body: &[u8]) -> Result<(), Box<dyn std::error::Error>> {
    if body.is_empty() || body.len() > MAX_FRAME_BYTES {
        return Err("Browser service response frame length is outside bounds".into());
    }
    writer.write_all(&(body.len() as u32).to_be_bytes())?;
    writer.write_all(body)?;
    writer.flush()?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use std::io::Cursor;

    use super::*;

    #[test]
    fn private_frame_round_trip_is_exact() {
        let body = br#"{"schema":"test","sequence":1}"#;
        let mut bytes = Vec::new();
        write_frame(&mut bytes, body).expect("bounded frame writes");
        let mut input = Cursor::new(bytes);
        assert_eq!(
            read_frame(&mut input).expect("bounded frame reads"),
            Some(body.to_vec())
        );
        assert_eq!(read_frame(&mut input).expect("EOF is clean"), None);
    }

    #[test]
    fn zero_and_oversized_frames_fail_closed() {
        let mut zero = Cursor::new(0_u32.to_be_bytes().to_vec());
        assert!(read_frame(&mut zero).is_err());

        let announced = u32::try_from(MAX_FRAME_BYTES + 1).expect("frame bound fits u32");
        let mut oversized = Cursor::new(announced.to_be_bytes().to_vec());
        assert!(read_frame(&mut oversized).is_err());
        assert!(write_frame(&mut Vec::new(), &vec![0_u8; MAX_FRAME_BYTES + 1]).is_err());
    }
}
