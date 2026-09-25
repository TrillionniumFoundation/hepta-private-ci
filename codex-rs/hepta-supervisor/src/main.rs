use std::path::PathBuf;

use codex_hepta_memory::H7ArtifactVerifier;
use codex_hepta_paths::HeptaFleetRoot;
use tokio_util::sync::CancellationToken;

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    let options = parse_options()?;
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

fn parse_options() -> anyhow::Result<Options> {
    let mut arguments = std::env::args_os().skip(1);
    let mut fleet_root = None;
    let mut key_path = None;
    let mut signer_id = None;
    let mut signer_epoch = None;
    let mut h7_key_path = None;
    let mut h7_signer_id = None;
    let mut h7_signer_epoch = None;
    while let Some(flag) = arguments.next() {
        let value = arguments
            .next()
            .ok_or_else(|| anyhow::anyhow!("missing value for {flag:?}"))?;
        match flag.to_str() {
            Some("--fleet-root") if fleet_root.is_none() => fleet_root = Some(value),
            Some("--grant-verifier-key") if key_path.is_none() => key_path = Some(value),
            Some("--grant-signer-id") if signer_id.is_none() => signer_id = Some(value),
            Some("--grant-signer-epoch") if signer_epoch.is_none() => signer_epoch = Some(value),
            Some("--h7-verifier-key") if h7_key_path.is_none() => h7_key_path = Some(value),
            Some("--h7-signer-id") if h7_signer_id.is_none() => h7_signer_id = Some(value),
            Some("--h7-signer-epoch") if h7_signer_epoch.is_none() => h7_signer_epoch = Some(value),
            _ => anyhow::bail!(
                "usage: hepta-supervisord --fleet-root ABSOLUTE_PATH [--grant-verifier-key ABSOLUTE_PATH --grant-signer-id ID --grant-signer-epoch N --h7-verifier-key ABSOLUTE_PATH --h7-signer-id ID --h7-signer-epoch N]"
            ),
        }
    }
    let fleet_root = HeptaFleetRoot::parse(PathBuf::from(
        fleet_root.ok_or_else(|| anyhow::anyhow!("--fleet-root is required"))?,
    ))?;
    let grant_verifier = match (
        key_path,
        signer_id,
        signer_epoch,
        h7_key_path,
        h7_signer_id,
        h7_signer_epoch,
    ) {
        (None, None, None, None, None, None) => None,
        (
            Some(key_path),
            Some(signer_id),
            Some(signer_epoch),
            Some(h7_key_path),
            Some(h7_signer_id),
            Some(h7_signer_epoch),
        ) => {
            let grant_epoch = parse_epoch(signer_epoch, "grant signer epoch")?;
            let h7_epoch = parse_epoch(h7_signer_epoch, "H7 signer epoch")?;
            let h7_signer_id = h7_signer_id
                .into_string()
                .map_err(|_| anyhow::anyhow!("H7 signer id is not UTF-8"))?;
            let h7_key = load_public_key(PathBuf::from(h7_key_path), "H7 verifier key")?;
            let h7_verifier = H7ArtifactVerifier::from_bytes(h7_signer_id, h7_epoch, h7_key)?;
            Some(load_grant_verifier(
                PathBuf::from(key_path),
                signer_id
                    .into_string()
                    .map_err(|_| anyhow::anyhow!("signer id is not UTF-8"))?,
                grant_epoch,
                h7_verifier,
            )?)
        }
        _ => anyhow::bail!("grant and H7 verifier key/id/epoch triplets must be supplied together"),
    };
    Ok(Options {
        fleet_root,
        grant_verifier,
    })
}

fn load_grant_verifier(
    path: PathBuf,
    signer_id: String,
    signer_epoch: u64,
    h7_verifier: H7ArtifactVerifier,
) -> anyhow::Result<codex_hepta_supervisor::H7H89ProductionGrantVerifier> {
    let key = load_public_key(path, "grant verifier key")?;
    Ok(
        codex_hepta_supervisor::H7H89ProductionGrantVerifier::from_bytes_with_h7_verifier(
            signer_id,
            signer_epoch,
            key,
            h7_verifier,
        )?,
    )
}

fn load_public_key(path: PathBuf, label: &str) -> anyhow::Result<[u8; 32]> {
    let metadata = std::fs::symlink_metadata(&path)?;
    if !metadata.file_type().is_file() {
        anyhow::bail!("{label} must be a regular, non-symlink file");
    }
    let bytes = std::fs::read(&path)?;
    let key = if bytes.len() == 32 {
        let mut key = [0_u8; 32];
        key.copy_from_slice(&bytes);
        key
    } else {
        let text = std::str::from_utf8(&bytes)?.trim();
        if text.len() != 64 {
            anyhow::bail!("{label} must be exactly 32 raw bytes or 64 hex characters");
        }
        let mut key = [0_u8; 32];
        for (index, pair) in text.as_bytes().chunks_exact(2).enumerate() {
            key[index] = (hex_value(pair[0])? << 4) | hex_value(pair[1])?;
        }
        key
    };
    Ok(key)
}

fn parse_epoch(value: std::ffi::OsString, label: &str) -> anyhow::Result<u64> {
    value
        .to_str()
        .ok_or_else(|| anyhow::anyhow!("{label} is not UTF-8"))?
        .parse::<u64>()
        .map_err(|error| anyhow::anyhow!("{label} is invalid: {error}"))
}

fn hex_value(value: u8) -> anyhow::Result<u8> {
    match value {
        b'0'..=b'9' => Ok(value - b'0'),
        b'a'..=b'f' => Ok(value - b'a' + 10),
        b'A'..=b'F' => Ok(value - b'A' + 10),
        _ => anyhow::bail!("grant verifier key contains non-hex data"),
    }
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
