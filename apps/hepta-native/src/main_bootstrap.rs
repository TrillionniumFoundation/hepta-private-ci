//! Input reload stops before durable state, updater recovery, or session admission.
use super::*;
use hepta_native::ui::{StartupDecision, StartupFailure, StartupRetry, StartupStage};

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

pub(super) fn load_ordinary(raw: &[String]) -> Result<Option<StartupInputs>, eframe::Error> {
    retry_inputs(
        || load(raw),
        |failure| {
            eprintln!("hepta-native: {failure}");
            hepta_native::ui::show_startup_recovery(failure, StartupRetry::InputsOnly)
        },
    )
}

// Success consumes this input-only loop. The caller invokes durable/native
// initialization afterwards; that stage is never captured by the retry closure.
fn retry_inputs<T>(
    mut load: impl FnMut() -> Result<T, StartupFailure>,
    mut recover: impl FnMut(StartupFailure) -> Result<StartupDecision, eframe::Error>,
) -> Result<Option<T>, eframe::Error> {
    loop {
        match load() {
            Ok(inputs) => return Ok(Some(inputs)),
            Err(failure) => match recover(failure)? {
                StartupDecision::RetryInputs => {}
                StartupDecision::Exit => return Ok(None),
            },
        }
    }
}

#[cfg(test)]
#[path = "main_bootstrap_tests.rs"]
mod tests;
