//! Explicit Agentd-owned product caller for `browser.servo`.
//!
//! This one-shot host deliberately has no Browser listener. It opens the real
//! persistent final-use authority, verifies the selected Browser service and
//! Servo worker artifacts, starts the private Browser child, performs one
//! bounded module-port call, and exits. The ordinary host requires explicit
//! ML-DSA issuer/feed trust and authenticated external clock/frontier services.
//! Classic compatibility fixtures are not available from this binary.

use std::io::Read;
use std::path::PathBuf;

use codex_hepta_agentd::BrowserFinalUseInvocation;
use codex_hepta_agentd::BrowserServoCall;
use codex_hepta_agentd::BrowserServoHost;
use codex_hepta_agentd::BrowserServoMethod;
use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_contracts::SignedFinalUseGrant;
use serde::Deserialize;
use serde_json::Value;

const MAX_CALL_BYTES: u64 = 65_536;

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
    let host = BrowserServoHost::open(&PathBuf::from(config_path))?;
    let call: HostCall = serde_json::from_slice(&bounded_stdin(MAX_CALL_BYTES)?)?;
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
    let result = host.spawn()?.call(request)?;
    serde_json::to_writer(std::io::stdout(), &result)?;
    println!();
    Ok(())
}

fn bounded_stdin(maximum: u64) -> Result<Vec<u8>, Box<dyn std::error::Error>> {
    let mut bytes = Vec::new();
    std::io::stdin().take(maximum + 1).read_to_end(&mut bytes)?;
    if bytes.len() as u64 > maximum {
        return Err(format!("Browser call exceeds {maximum} bytes").into());
    }
    Ok(bytes)
}
