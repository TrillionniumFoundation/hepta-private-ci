//! Console input preflight stops before durable state, updater recovery, or session admission.
use super::*;
use hepta_native::ui::{StartupFailure, StartupStage};

pub(super) struct StartupInputs {
    pub(super) raw_args: Vec<String>,
    pub(super) config: AppConfig,
    pub(super) trusted_keys: TrustedKeySet,
    pub(super) manifest: EndpointManifest,
    pub(super) backend: LoopbackGatewayBackend,
}

pub(super) fn interactive_launch(raw: &[String]) -> bool {
    !raw.iter().any(|arg| {
        matches!(
            arg.as_str(),
            "--check-connection"
                | "--update-handoff"
                | "--self-test"
                | "--qualification-e2e"
                | "--qualification-journal-child"
                | "--qualification-updater-child"
                | "--native-picker-helper"
                | "--native-notification-helper"
                | "--register-notification-identity"
                | "--help"
                | "-h"
        )
    })
}

pub(super) fn load(raw: &[String]) -> Result<StartupInputs, StartupFailure> {
    let raw_args = hepta_native::launch_config::expand_launch_arguments(raw)
        .map_err(|error| StartupFailure::new(StartupStage::Configuration, error))?;
    let config = AppConfig::parse(&raw_args)
        .map_err(|error| StartupFailure::new(StartupStage::Configuration, error))?;
    let trusted_keys = TrustedKeySet::from_path(&config.trusted_keys).map_err(|error| {
        StartupFailure::new(
            StartupStage::Trust,
            format!("{}: {error}", config.trusted_keys.display()),
        )
    })?;
    let signed: SignedEndpointManifestV1 =
        hepta_native::file_input::read_json_file(&config.endpoint_manifest, 64 * 1024).map_err(
            |error| {
                StartupFailure::new(
                    StartupStage::Endpoint,
                    format!("{}: {error}", config.endpoint_manifest.display()),
                )
            },
        )?;
    let verified = signed.verify(&trusted_keys).map_err(|error| {
        StartupFailure::new(
            StartupStage::Endpoint,
            format!("{}: {error}", config.endpoint_manifest.display()),
        )
    })?;
    let address: SocketAddr = verified
        .manifest
        .address
        .parse()
        .map_err(|error| StartupFailure::new(StartupStage::Backend, error))?;
    let credential = GatewayCredentialStore::default()
        .load(&verified.gateway_credential_account)
        .map_err(|error| StartupFailure::new(StartupStage::Credential, error))?;
    let backend = LoopbackGatewayBackend::new(address, credential)
        .map_err(|error| StartupFailure::new(StartupStage::Backend, error))?;
    Ok(StartupInputs {
        raw_args,
        config,
        trusted_keys,
        manifest: verified.manifest,
        backend,
    })
}

/// Only connection-level I/O unavailability permits late chat-only fallback.
/// Authentication, integrity, update and indeterminate failures remain fatal.
#[derive(Debug)]
pub(super) struct ConsoleUnavailable(String);
impl std::fmt::Display for ConsoleUnavailable {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        self.0.fmt(formatter)
    }
}
impl std::error::Error for ConsoleUnavailable {}

pub(super) fn classify_console_connection_error(
    error: hepta_native::ui::NativeAppStartupError,
) -> Box<dyn std::error::Error> {
    use std::io::ErrorKind;
    if matches!(&error, hepta_native::ui::NativeAppStartupError::Connection(hepta_native::error::ShellError::Io(io)) if matches!(io.kind(), ErrorKind::ConnectionRefused | ErrorKind::ConnectionReset | ErrorKind::ConnectionAborted | ErrorKind::NotConnected | ErrorKind::TimedOut | ErrorKind::AddrNotAvailable))
    {
        Box::new(ConsoleUnavailable(error.to_string()))
    } else {
        Box::new(error)
    }
}

#[cfg(test)]
#[path = "main_bootstrap_tests.rs"]
mod tests;
