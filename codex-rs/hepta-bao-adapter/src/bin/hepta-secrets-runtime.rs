//! Configuration and description CLI for the durable secrets.heptabao runtime.
//!
//! Product hosts import `compose_hepta_secrets_runtime` from the adapter library.
//! This binary validates deployment inputs and describes the intended runtime;
//! it does not construct authority or activate a consumer effect.

use std::env;
use std::path::Path;

const BINARY_TARGET: &str = "hepta-secrets-runtime";

fn required_environment() -> [&'static str; 5] {
    [
        "HEPTA_SECRETS_DB_PATH",
        "HEPTA_SECRETS_PROVIDER_ENDPOINT",
        "HEPTA_SECRETS_PROVIDER_TOKEN_FILE",
        "HEPTA_SECRETS_AUTHORITY_STATE_DIR",
        "HEPTA_SECRETS_CHECKPOINT_PATH",
    ]
}

fn validate_environment() -> Result<(), String> {
    for name in required_environment() {
        let value = env::var(name).map_err(|_| format!("missing required environment: {name}"))?;
        if value.trim().is_empty() {
            return Err(format!("empty required environment: {name}"));
        }
    }
    let database = env::var("HEPTA_SECRETS_DB_PATH").map_err(|error| error.to_string())?;
    if !Path::new(&database).is_absolute() {
        return Err("HEPTA_SECRETS_DB_PATH must be absolute".to_owned());
    }
    let token_file =
        env::var("HEPTA_SECRETS_PROVIDER_TOKEN_FILE").map_err(|error| error.to_string())?;
    if !Path::new(&token_file).is_absolute() {
        return Err("HEPTA_SECRETS_PROVIDER_TOKEN_FILE must be absolute".to_owned());
    }
    let endpoint =
        env::var("HEPTA_SECRETS_PROVIDER_ENDPOINT").map_err(|error| error.to_string())?;
    let parsed = url::Url::parse(&endpoint).map_err(|_| "invalid provider endpoint".to_owned())?;
    if parsed.scheme() != "https" || parsed.host_str().is_none() {
        return Err("provider endpoint must be an absolute https URL".to_owned());
    }
    Ok(())
}

fn describe() {
    println!(
        "{{\"binaryTarget\":\"{BINARY_TARGET}\",\"claimMode\":\"just_in_time\",\"activationClaim\":false,\"storageQualificationRequired\":true,\"targetHostQualificationRequired\":true}}"
    );
}

fn main() {
    let argument = env::args().nth(1);
    match argument.as_deref() {
        Some("--describe") => describe(),
        Some("--validate-config") => match validate_environment() {
            Ok(()) => describe(),
            Err(error) => {
                eprintln!("configuration rejected: {error}");
                std::process::exit(78);
            }
        },
        _ => {
            eprintln!(
                "{BINARY_TARGET} is a host-composed runtime; use --describe or --validate-config"
            );
            std::process::exit(64);
        }
    }
}
