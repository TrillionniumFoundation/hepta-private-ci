use std::ffi::OsString;
use std::path::PathBuf;

use codex_hepta_contracts::Sha256Digest;
use codex_hepta_paths::HeptaFleetRoot;
use tokio_util::sync::CancellationToken;

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    let options = parse_options_from(std::env::args_os().skip(1))?;
    let cancellation = CancellationToken::new();
    spawn_shutdown_signal(cancellation.clone());
    match options.grant_verifier {
        Some(verifier) => {
            codex_hepta_supervisor::run_supervisord_with_grant_verifier(
                options.fleet_root,
                cancellation,
                verifier,
            )
            .await?;
        }
        None => codex_hepta_supervisor::run_supervisord(options.fleet_root, cancellation).await?,
    }
    Ok(())
}

struct Options {
    fleet_root: HeptaFleetRoot,
    grant_verifier: Option<codex_hepta_supervisor::H7H89ProductionGrantVerifier>,
}

fn parse_options_from(arguments: impl IntoIterator<Item = OsString>) -> anyhow::Result<Options> {
    let mut arguments = arguments.into_iter();
    let mut fleet_root = None;
    let mut authority_bundle = None;
    let mut authority_bundle_sha256 = None;
    while let Some(flag) = arguments.next() {
        let value = arguments
            .next()
            .ok_or_else(|| anyhow::anyhow!("missing value for {flag:?}; {}", usage()))?;
        match flag.to_str() {
            Some("--fleet-root") if fleet_root.is_none() => fleet_root = Some(value),
            Some("--authority-bundle") if authority_bundle.is_none() => {
                authority_bundle = Some(value)
            }
            Some("--authority-bundle-sha256") if authority_bundle_sha256.is_none() => {
                authority_bundle_sha256 = Some(value)
            }
            _ => anyhow::bail!(usage()),
        }
    }
    let fleet_root = HeptaFleetRoot::parse(PathBuf::from(
        fleet_root.ok_or_else(|| anyhow::anyhow!("--fleet-root is required; {}", usage()))?,
    ))?;
    let grant_verifier = match (authority_bundle, authority_bundle_sha256) {
        (None, None) => None,
        (Some(bundle_path), Some(expected)) => {
            let expected = expected
                .into_string()
                .map_err(|_| anyhow::anyhow!("authority bundle digest is not UTF-8"))?;
            let expected = Sha256Digest::parse(expected)
                .map_err(|error| anyhow::anyhow!("authority bundle digest is invalid: {error}"))?;
            let (_, verifier) = codex_hepta_supervisor::ProductionAuthorityBundle::load_pinned(
                &PathBuf::from(bundle_path),
                &expected,
            )?;
            Some(verifier)
        }
        _ => anyhow::bail!(
            "--authority-bundle and --authority-bundle-sha256 must be supplied together; {}",
            usage()
        ),
    };
    Ok(Options {
        fleet_root,
        grant_verifier,
    })
}

fn usage() -> &'static str {
    "usage: hepta-supervisord --fleet-root ABSOLUTE_PATH [--authority-bundle ABSOLUTE_PATH --authority-bundle-sha256 SHA256]"
}

fn spawn_shutdown_signal(cancellation: CancellationToken) {
    tokio::spawn(async move {
        wait_for_shutdown_signal().await;
        cancellation.cancel();
    });
}

#[cfg(unix)]
async fn wait_for_shutdown_signal() {
    let terminate = tokio::signal::unix::signal(tokio::signal::unix::SignalKind::terminate());
    let interrupt = tokio::signal::unix::signal(tokio::signal::unix::SignalKind::interrupt());
    let (Ok(mut terminate), Ok(mut interrupt)) = (terminate, interrupt) else {
        let _ = tokio::signal::ctrl_c().await;
        return;
    };
    tokio::select! {
        _ = terminate.recv() => {}
        _ = interrupt.recv() => {}
    }
}

#[cfg(not(unix))]
async fn wait_for_shutdown_signal() {
    let _ = tokio::signal::ctrl_c().await;
}

#[cfg(all(test, unix))]
#[path = "main_key_tests.rs"]
mod key_tests;
