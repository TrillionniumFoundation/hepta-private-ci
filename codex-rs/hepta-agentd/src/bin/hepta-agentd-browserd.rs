//! Long-running Agentd-owned product service for `browser.servo`.
//!
//! The service has no discovery or network listener. A trusted parent starts it
//! with one owner-private host configuration and exchanges bounded newline JSON
//! requests over inherited stdin/stdout. The Browser child, profile-affine Servo
//! worker pool, durable journal and monotonic revocation watcher remain owned for
//! the lifetime of this process.

use std::io::BufRead;
use std::io::BufReader;
use std::io::Write;
use std::path::PathBuf;

use codex_hepta_agentd::BrowserFinalUseInvocation;
use codex_hepta_agentd::BrowserServoCall;
use codex_hepta_agentd::BrowserServoMethod;
use codex_hepta_agentd::PersistentBrowserServoControl;
use codex_hepta_agentd::open_browser_servo_port_from_file;
use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_contracts::SignedFinalUseGrant;
use serde::Deserialize;
use serde::Serialize;
use serde_json::Value;

const MAX_REQUEST_BYTES: usize = 1_048_576;
const MAX_RESPONSE_BYTES: usize = 1_048_576;
const MAX_ERROR_BYTES: usize = 1024;

#[derive(Clone, Copy, Debug, Deserialize)]
#[serde(rename_all = "snake_case")]
enum BrowserdMethod {
    OpenProfile,
    AdmitEffectGrant,
    ObservePage,
    NavigateOrAct,
    ReconcileOperation,
    ReconcilePersistedOperation,
    CloseProfile,
}

impl BrowserdMethod {
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
struct BrowserdRequest {
    request_id: u64,
    method: BrowserdMethod,
    input: Value,
    signed_grant: Option<SignedFinalUseGrant>,
    binding: Option<FinalUseBinding>,
}

#[derive(Debug, Serialize)]
#[serde(deny_unknown_fields)]
struct BrowserdResponse {
    request_id: u64,
    ok: bool,
    #[serde(skip_serializing_if = "Option::is_none")]
    result: Option<Value>,
    #[serde(skip_serializing_if = "Option::is_none")]
    error: Option<String>,
}

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let mut args = std::env::args_os().skip(1);
    let config_path = args
        .next()
        .ok_or("usage: hepta-agentd-browserd HOST_CONFIG.json")?;
    if args.next().is_some() {
        return Err("usage: hepta-agentd-browserd HOST_CONFIG.json".into());
    }

    let owner = open_browser_servo_port_from_file(&PathBuf::from(config_path))?;
    serve(
        &owner,
        BufReader::new(std::io::stdin().lock()),
        std::io::stdout().lock(),
    )?;
    Ok(())
}

fn serve(
    owner: &PersistentBrowserServoControl,
    mut input: impl BufRead,
    mut output: impl Write,
) -> Result<(), Box<dyn std::error::Error>> {
    loop {
        let mut line = Vec::new();
        let count = input
            .by_ref()
            .take((MAX_REQUEST_BYTES + 1) as u64)
            .read_until(b'\n', &mut line)?;
        if count == 0 {
            return Ok(());
        }
        if line.len() > MAX_REQUEST_BYTES || !line.ends_with(b"\n") {
            return Err("Browserd request must be one bounded newline JSON frame".into());
        }
        line.pop();
        if line.is_empty() {
            return Err("Browserd request frame is empty".into());
        }

        let request: BrowserdRequest = serde_json::from_slice(&line)?;
        let response = dispatch(owner, request);
        let mut bytes = serde_json::to_vec(&response)?;
        if bytes.len() + 1 > MAX_RESPONSE_BYTES {
            return Err("Browserd response exceeded the hard byte bound".into());
        }
        bytes.push(b'\n');
        output.write_all(&bytes)?;
        output.flush()?;
    }
}

fn dispatch(
    owner: &PersistentBrowserServoControl,
    request: BrowserdRequest,
) -> BrowserdResponse {
    let request_id = request.request_id;
    let result = make_call(request).and_then(|call| owner.call(call).map_err(|error| error.to_string()));
    match result {
        Ok(result) => BrowserdResponse {
            request_id,
            ok: true,
            result: Some(result),
            error: None,
        },
        Err(error) => BrowserdResponse {
            request_id,
            ok: false,
            result: None,
            error: Some(bound_error(error)),
        },
    }
}

fn make_call(request: BrowserdRequest) -> Result<BrowserServoCall, String> {
    if request.request_id == 0 {
        return Err("request_id must be non-zero".to_string());
    }
    if !request.input.is_object() {
        return Err("Browserd input must be a JSON object".to_string());
    }
    let method = request.method.module_method();
    if matches!(method, BrowserServoMethod::NavigateOrAct) {
        let signed_grant = request
            .signed_grant
            .ok_or_else(|| "navigate_or_act requires an independently signed grant".to_string())?;
        let binding = request
            .binding
            .ok_or_else(|| "navigate_or_act requires an exact FinalUseBinding".to_string())?;
        BrowserServoCall::effect(
            request.input,
            BrowserFinalUseInvocation {
                signed_grant,
                binding,
            },
        )
        .map_err(|error| error.to_string())
    } else {
        if request.signed_grant.is_some() || request.binding.is_some() {
            return Err("non-effect Browserd requests must not carry final-use authority".to_string());
        }
        BrowserServoCall::read(method, request.input).map_err(|error| error.to_string())
    }
}

fn bound_error(error: String) -> String {
    let mut output = String::new();
    for character in error.chars() {
        if output.len() + character.len_utf8() > MAX_ERROR_BYTES {
            break;
        }
        output.push(character);
    }
    if output.is_empty() {
        "browser.servo request rejected".to_string()
    } else {
        output
    }
}
