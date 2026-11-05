use std::path::PathBuf;

use codex_hepta_paths::HeptaFleetRoot;
use tokio_util::sync::CancellationToken;

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    let options = parse_options()?;
    let cancellation = CancellationToken::new();
    spawn_shutdown_signal(cancellation.clone());
    if options.release_intent_recovery {
        let verifier = options.grant_verifier.ok_or_else(|| {
            anyhow::anyhow!("--release-intent-recovery requires --production-authority-policy")
        })?;
        codex_hepta_supervisor::run_supervisord_intent_reconciliation(
            options.fleet_root,
            options.release_trust,
            cancellation,
            verifier,
        )
        .await?;
        return Ok(());
    }
    match options.grant_verifier {
        Some(verifier) => {
            codex_hepta_supervisor::run_supervisord_with_grant_verifier(
                options.fleet_root,
                options.release_trust,
                cancellation,
                verifier,
            )
            .await?;
        }
        None => {
            codex_hepta_supervisor::run_supervisord(
                options.fleet_root,
                options.release_trust,
                cancellation,
            )
            .await?
        }
    }
    Ok(())
}

struct Options {
    fleet_root: HeptaFleetRoot,
    release_trust: codex_hepta_fleet::FleetReleaseTrustConfig,
    grant_verifier: Option<codex_hepta_supervisor::H7H89ProductionGrantVerifier>,
    release_intent_recovery: bool,
}

fn parse_options() -> anyhow::Result<Options> {
    let mut arguments = std::env::args_os().skip(1);
    let mut fleet_root = None;
    let mut release_trust_path = None;
    let mut authority_policy_path = None;
    let mut release_intent_recovery = false;
    while let Some(flag) = arguments.next() {
        if flag == "--release-intent-recovery" {
            if release_intent_recovery {
                anyhow::bail!("--release-intent-recovery may be supplied only once");
            }
            release_intent_recovery = true;
            continue;
        }
        let value = arguments
            .next()
            .ok_or_else(|| anyhow::anyhow!("missing value for {flag:?}"))?;
        match flag.to_str() {
            Some("--fleet-root") if fleet_root.is_none() => fleet_root = Some(value),
            Some("--release-trust-config") if release_trust_path.is_none() => {
                release_trust_path = Some(value)
            }
            Some("--production-authority-policy") if authority_policy_path.is_none() => {
                authority_policy_path = Some(value)
            }
            _ => anyhow::bail!(
                "usage: hepta-supervisord --fleet-root ABSOLUTE_PATH --release-trust-config ABSOLUTE_PATH [--production-authority-policy ABSOLUTE_PATH] [--release-intent-recovery]"
            ),
        }
    }
    let fleet_root = HeptaFleetRoot::parse(PathBuf::from(
        fleet_root.ok_or_else(|| anyhow::anyhow!("--fleet-root is required"))?,
    ))?;
    let release_trust = codex_hepta_fleet::FleetReleaseTrustConfig::read(&PathBuf::from(
        release_trust_path.ok_or_else(|| anyhow::anyhow!("--release-trust-config is required"))?,
    ))?;
    let grant_verifier = authority_policy_path
        .map(|path| {
            let path = PathBuf::from(path);
            if !path.is_absolute() {
                anyhow::bail!("--production-authority-policy must be absolute");
            }
            Ok(codex_hepta_supervisor::H7H89ProductionGrantVerifier::read_pq_policy(&path)?)
        })
        .transpose()?;
    Ok(Options {
        fleet_root,
        release_trust,
        grant_verifier,
        release_intent_recovery,
    })
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
