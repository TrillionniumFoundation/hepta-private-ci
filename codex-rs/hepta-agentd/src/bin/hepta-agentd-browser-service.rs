//! Long-running Agentd-owned private host for `browser.servo`.
//!
//! The process owns one restartable `PersistentBrowserServoControl` for its
//! lifetime and exposes no network listener. Requests and responses use a
//! bounded, sequence-checked, length-prefixed JSON protocol over inherited
//! stdin/stdout. Final-use grants are accepted only for `navigate_or_act`.

use std::io::{BufReader, BufWriter, Read, Write};
use std::path::PathBuf;

use codex_hepta_agentd::BrowserFinalUseInvocation;
use codex_hepta_agentd::BrowserServoCall;
use codex_hepta_agentd::BrowserServoError;
use codex_hepta_agentd::BrowserServoMethod;
use codex_hepta_agentd::open_browser_servo_port_from_file;
use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_contracts::SignedFinalUseGrant;
use serde::Deserialize;
use serde_json::Value;
use serde_json::json;

const REQUEST_SCHEMA: &str = "hepta.agentd.browser-service-request.v1";
const RESPONSE_SCHEMA: &str = "hepta.agentd.browser-service-response.v1";
const PROTOCOL_VERSION: u64 = 1;
const MAX_FRAME_BYTES: usize = 1_048_576;
const MAX_ERROR_CHARS: usize = 512;

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

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let mut args = std::env::args_os().skip(1);
    let config_path = args
        .next()
        .ok_or("usage: hepta-agentd-browser-service HOST_CONFIG.json")?;
    if args.next().is_some() {
        return Err("usage: hepta-agentd-browser-service HOST_CONFIG.json".into());
    }

    let control = open_browser_servo_port_from_file(&PathBuf::from(config_path))?;
    let stdin = std::io::stdin();
    let stdout = std::io::stdout();
    let mut reader = BufReader::new(stdin.lock());
    let mut writer = BufWriter::new(stdout.lock());
    let mut expected_sequence = 1_u64;

    while let Some(bytes) = read_frame(&mut reader)? {
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

        let response = match call.and_then(|call| control.call(call)) {
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
    }
    Ok(())
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

fn write_frame(
    writer: &mut impl Write,
    body: &[u8],
) -> Result<(), Box<dyn std::error::Error>> {
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
