use std::io::Read;
use std::path::PathBuf;

use codex_hepta_contracts::Sha256Digest;
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
    let mut authority_bundle = None;
    let mut authority_bundle_sha256 = None;
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
        fleet_root.ok_or_else(|| anyhow::anyhow!("--fleet-root is required"))?,
    ))?;
    let legacy_authority_supplied = key_path.is_some()
        || signer_id.is_some()
        || signer_epoch.is_some()
        || h7_key_path.is_some()
        || h7_signer_id.is_some()
        || h7_signer_epoch.is_some();
    let bundle_authority_supplied =
        authority_bundle.is_some() || authority_bundle_sha256.is_some();
    anyhow::ensure!(
        !(legacy_authority_supplied && bundle_authority_supplied),
        "authority bundle and legacy verifier tuples are mutually exclusive"
    );

    let grant_verifier = if bundle_authority_supplied {
        let bundle_path = authority_bundle
            .ok_or_else(|| anyhow::anyhow!("--authority-bundle is required with its digest"))?;
        let expected = authority_bundle_sha256
            .ok_or_else(|| anyhow::anyhow!("--authority-bundle-sha256 is required with the bundle"))?
            .into_string()
            .map_err(|_| anyhow::anyhow!("authority bundle digest is not UTF-8"))?;
        let expected = Sha256Digest::parse(expected)
            .map_err(|error| anyhow::anyhow!("authority bundle digest is invalid: {error}"))?;
        let (_, verifier) = codex_hepta_supervisor::ProductionAuthorityBundle::load_pinned(
            &PathBuf::from(bundle_path),
            &expected,
        )?;
        Some(verifier)
    } else {
        match (
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
            _ => anyhow::bail!(
                "grant and H7 verifier key/id/epoch triplets must be supplied together"
            ),
        }
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
    // Public keys are not secrets, but their integrity is an authority boundary.
    // The operator must protect parent directories; this pins the opened file.
    anyhow::ensure!(path.is_absolute(), "{label} path must be absolute");
    let before = std::fs::symlink_metadata(&path)?;
    anyhow::ensure!(
        before.is_file(),
        "{label} must be a regular, non-symlink file"
    );
    let mut options = std::fs::OpenOptions::new();
    options.read(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.custom_flags(libc::O_NOFOLLOW | libc::O_CLOEXEC | libc::O_NONBLOCK);
    }
    let file = options.open(&path)?;
    let opened = file.metadata()?;
    anyhow::ensure!(opened.is_file(), "{label} opened file must be regular");
    #[cfg(unix)]
    {
        use std::os::unix::fs::MetadataExt;
        // SAFETY: geteuid takes no arguments and has no memory-safety preconditions.
        let uid = unsafe { libc::geteuid() };
        anyhow::ensure!(
            (opened.uid() == uid || opened.uid() == 0)
                && opened.mode() & 0o022 == 0
                && opened.nlink() == 1,
            "{label} must be root/effective-user owned, single-link, and not writable by others"
        );
        anyhow::ensure!(
            opened.dev() == before.dev() && opened.ino() == before.ino(),
            "{label} file identity changed during open"
        );
    }
    // 32 raw bytes or 64 hex characters with bounded surrounding whitespace.
    // Read at most one byte beyond the limit, even for a growing/sparse file.
    const MAX_KEY_BYTES: u64 = 128;
    let mut bytes = Vec::new();
    (&file).take(MAX_KEY_BYTES + 1).read_to_end(&mut bytes)?;
    anyhow::ensure!(
        bytes.len() as u64 <= MAX_KEY_BYTES,
        "{label} exceeds key byte limit"
    );
    #[cfg(unix)]
    {
        use std::os::unix::fs::MetadataExt;
        let after = file.metadata()?;
        anyhow::ensure!(
            after.dev() == opened.dev()
                && after.ino() == opened.ino()
                && after.uid() == opened.uid()
                && after.mode() == opened.mode()
                && after.nlink() == opened.nlink()
                && after.len() == opened.len()
                && after.mtime() == opened.mtime()
                && after.mtime_nsec() == opened.mtime_nsec()
                && after.ctime() == opened.ctime()
                && after.ctime_nsec() == opened.ctime_nsec(),
            "{label} file changed while being read"
        );
    }
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

fn usage() -> &'static str {
    "usage: hepta-supervisord --fleet-root ABSOLUTE_PATH [--authority-bundle ABSOLUTE_PATH --authority-bundle-sha256 SHA256 | --grant-verifier-key ABSOLUTE_PATH --grant-signer-id ID --grant-signer-epoch N --h7-verifier-key ABSOLUTE_PATH --h7-signer-id ID --h7-signer-epoch N]"
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

#[cfg(all(test, unix))]
#[path = "main_key_tests.rs"]
mod key_tests;
