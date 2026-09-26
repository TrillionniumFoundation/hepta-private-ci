//! Long-lived Agentd-owned product service for `browser.servo`.
//!
//! The service owns one persistent Browser control for the Agentd generation,
//! accepts only bounded length-prefixed JSON over inherited stdin/stdout, keeps
//! the live revocation feed active, and never exposes a discovery, TCP, UDS,
//! WebDriver, or CDP listener. A semantic call is executed at most once; an
//! indeterminate result is returned to the parent for explicit reconciliation.

use std::io::{self, Read, Write};
use std::path::Path;

use codex_hepta_contracts::{FinalUseBinding, SignedFinalUseGrant};
use serde::Deserialize;
use serde_json::{Value, json};

#[path = "../browser_revocation_feed.rs"]
mod browser_revocation_feed;
#[path = "../browser_servo_persistent.rs"]
mod browser_servo;

use browser_servo::{
    BrowserFinalUseInvocation, BrowserServoCall, BrowserServoMethod,
    open_browser_servo_port_from_file,
};

const MAX_FRAME_BYTES: usize = 1_048_576;
const MAX_ERROR_CHARS: usize = 512;

#[derive(Clone, Copy, Debug, Deserialize)]
#[serde(rename_all = "snake_case")]
enum ServiceMethod {
    OpenProfile,
    AdmitEffectGrant,
    ObservePage,
    NavigateOrAct,
    ReconcileOperation,
    ReconcilePersistedOperation,
    CloseProfile,
}

impl ServiceMethod {
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
#[serde(deny_unknown_fields)]
struct ServiceCall {
    request_id: String,
    method: ServiceMethod,
    input: Value,
    signed_grant: Option<SignedFinalUseGrant>,
    binding: Option<FinalUseBinding>,
}

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let mut args = std::env::args_os().skip(1);
    let config_path = args.next().ok_or(
        "usage: hepta-agentd-browser-service BROWSER_HOST_CONFIG.json",
    )?;
    if args.next().is_some() {
        return Err(
            "usage: hepta-agentd-browser-service BROWSER_HOST_CONFIG.json".into(),
        );
    }

    let owner = open_browser_servo_port_from_file(Path::new(&config_path))?;
    let stdin = io::stdin();
    let stdout = io::stdout();
    let mut input = stdin.lock();
    let mut output = stdout.lock();

    while let Some(frame) = read_frame(&mut input)? {
        let call: ServiceCall = match serde_json::from_slice(&frame) {
            Ok(call) => call,
            Err(error) => {
                write_response(
                    &mut output,
                    json!({
                        "requestId": null,
                        "ok": false,
                        "error": bounded_error(format!("invalid Browser service request: {error}")),
                    }),
                )?;
                continue;
            }
        };
        let request_id = match validate_request_id(&call.request_id) {
            Ok(value) => value,
            Err(error) => {
                write_response(
                    &mut output,
                    json!({
                        "requestId": call.request_id,
                        "ok": false,
                        "error": bounded_error(error),
                    }),
                )?;
                continue;
            }
        };
        let method = call.method.module_method();
        let request = if matches!(method, BrowserServoMethod::NavigateOrAct) {
            match (call.signed_grant, call.binding) {
                (Some(signed_grant), Some(binding)) => BrowserServoCall::effect(
                    call.input,
                    BrowserFinalUseInvocation {
                        signed_grant,
                        binding,
                    },
                ),
                _ => Err(browser_servo::BrowserServoError::Invalid(
                    "navigate_or_act requires signed final-use grant and exact binding".into(),
                )),
            }
        } else if call.signed_grant.is_some() || call.binding.is_some() {
            Err(browser_servo::BrowserServoError::Invalid(
                "non-effect Browser calls must not carry final-use authority".into(),
            ))
        } else {
            BrowserServoCall::read(method, call.input)
        };

        let response = match request.and_then(|request| owner.call(request)) {
            Ok(result) => json!({
                "requestId": request_id,
                "ok": true,
                "result": result,
            }),
            Err(error) => json!({
                "requestId": request_id,
                "ok": false,
                "error": bounded_error(error.to_string()),
            }),
        };
        write_response(&mut output, response)?;
    }

    Ok(())
}

fn validate_request_id(value: &str) -> Result<String, String> {
    if value.is_empty()
        || value.len() > 128
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || b"._:-".contains(&byte))
    {
        return Err("request_id must be a bounded stable identifier".into());
    }
    Ok(value.to_string())
}

fn read_frame(input: &mut impl Read) -> Result<Option<Vec<u8>>, Box<dyn std::error::Error>> {
    let mut prefix = [0_u8; 4];
    let mut read = 0;
    while read < prefix.len() {
        match input.read(&mut prefix[read..])? {
            0 if read == 0 => return Ok(None),
            0 => return Err("Browser service input ended with a partial frame prefix".into()),
            count => read += count,
        }
    }
    let length = u32::from_be_bytes(prefix) as usize;
    if length == 0 || length > MAX_FRAME_BYTES {
        return Err("Browser service frame length is outside the hard bound".into());
    }
    let mut body = vec![0_u8; length];
    input.read_exact(&mut body)?;
    Ok(Some(body))
}

fn write_response(
    output: &mut impl Write,
    value: Value,
) -> Result<(), Box<dyn std::error::Error>> {
    let body = serde_json::to_vec(&value)?;
    if body.is_empty() || body.len() > MAX_FRAME_BYTES {
        return Err("Browser service response exceeds the hard bound".into());
    }
    output.write_all(&(body.len() as u32).to_be_bytes())?;
    output.write_all(&body)?;
    output.flush()?;
    Ok(())
}

fn bounded_error(value: impl AsRef<str>) -> String {
    value.as_ref().chars().take(MAX_ERROR_CHARS).collect()
}
