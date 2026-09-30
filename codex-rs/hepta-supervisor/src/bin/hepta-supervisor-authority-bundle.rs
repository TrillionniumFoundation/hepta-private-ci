use std::io::Write;
use std::path::Path;
use std::path::PathBuf;

use codex_hepta_supervisor::ProductionAuthorityBundle;
use ed25519_dalek::VerifyingKey;

fn main() -> anyhow::Result<()> {
    let options = parse_options()?;
    let grant_key = load_public_key(&options.grant_key, "grant verifier key")?;
    let h7_key = load_public_key(&options.h7_key, "H7 verifier key")?;
    let bundle = ProductionAuthorityBundle::new(
        options.grant_signer_id,
        options.grant_signer_epoch,
        VerifyingKey::from_bytes(&grant_key)
            .map_err(|_| anyhow::anyhow!("grant verifier key is malformed"))?,
        options.h7_signer_id,
        options.h7_signer_epoch,
        VerifyingKey::from_bytes(&h7_key)
            .map_err(|_| anyhow::anyhow!("H7 verifier key is malformed"))?,
    )?;
    write_new_file(&options.output, &bundle.to_json_bytes()?)?;
    println!("{}", bundle.bundle_sha256);
    Ok(())
}

struct Options {
    grant_key: PathBuf,
    grant_signer_id: String,
    grant_signer_epoch: u64,
    h7_key: PathBuf,
    h7_signer_id: String,
    h7_signer_epoch: u64,
    output: PathBuf,
}

fn parse_options() -> anyhow::Result<Options> {
    let mut args = std::env::args_os().skip(1);
    let mut grant_key = None;
    let mut grant_signer_id = None;
    let mut grant_signer_epoch = None;
    let mut h7_key = None;
    let mut h7_signer_id = None;
    let mut h7_signer_epoch = None;
    let mut output = None;
    while let Some(flag) = args.next() {
        let value = args
            .next()
            .ok_or_else(|| anyhow::anyhow!("missing value for {flag:?}"))?;
        match flag.to_str() {
            Some("--grant-verifier-key") if grant_key.is_none() => {
                grant_key = Some(PathBuf::from(value))
            }
            Some("--grant-signer-id") if grant_signer_id.is_none() => {
                grant_signer_id = Some(to_utf8(value, "grant signer id")?)
            }
            Some("--grant-signer-epoch") if grant_signer_epoch.is_none() => {
                grant_signer_epoch = Some(parse_epoch(value, "grant signer epoch")?)
            }
            Some("--h7-verifier-key") if h7_key.is_none() => h7_key = Some(PathBuf::from(value)),
            Some("--h7-signer-id") if h7_signer_id.is_none() => {
                h7_signer_id = Some(to_utf8(value, "H7 signer id")?)
            }
            Some("--h7-signer-epoch") if h7_signer_epoch.is_none() => {
                h7_signer_epoch = Some(parse_epoch(value, "H7 signer epoch")?)
            }
            Some("--output") if output.is_none() => output = Some(PathBuf::from(value)),
            _ => anyhow::bail!(usage()),
        }
    }
    let output = output.ok_or_else(|| anyhow::anyhow!(usage()))?;
    if !output.is_absolute() {
        anyhow::bail!("authority bundle output path must be absolute");
    }
    Ok(Options {
        grant_key: grant_key.ok_or_else(|| anyhow::anyhow!(usage()))?,
        grant_signer_id: grant_signer_id.ok_or_else(|| anyhow::anyhow!(usage()))?,
        grant_signer_epoch: grant_signer_epoch.ok_or_else(|| anyhow::anyhow!(usage()))?,
        h7_key: h7_key.ok_or_else(|| anyhow::anyhow!(usage()))?,
        h7_signer_id: h7_signer_id.ok_or_else(|| anyhow::anyhow!(usage()))?,
        h7_signer_epoch: h7_signer_epoch.ok_or_else(|| anyhow::anyhow!(usage()))?,
        output,
    })
}

fn load_public_key(path: &Path, label: &str) -> anyhow::Result<[u8; 32]> {
    if !path.is_absolute() {
        anyhow::bail!("{label} path must be absolute");
    }
    let metadata = std::fs::symlink_metadata(path)?;
    if !metadata.file_type().is_file() || metadata.file_type().is_symlink() {
        anyhow::bail!("{label} must be a regular non-symlink file");
    }
    let bytes = std::fs::read(path)?;
    if bytes.len() == 32 {
        return bytes
            .try_into()
            .map_err(|_| anyhow::anyhow!("{label} must be 32 bytes"));
    }
    let text = std::str::from_utf8(&bytes)?.trim();
    if text.len() != 64 {
        anyhow::bail!("{label} must be exactly 32 raw bytes or 64 hex characters");
    }
    let mut key = [0_u8; 32];
    for (index, pair) in text.as_bytes().chunks_exact(2).enumerate() {
        key[index] = (hex_value(pair[0])? << 4) | hex_value(pair[1])?;
    }
    Ok(key)
}

fn write_new_file(path: &Path, bytes: &[u8]) -> anyhow::Result<()> {
    let parent = path
        .parent()
        .ok_or_else(|| anyhow::anyhow!("authority bundle output has no parent"))?;
    std::fs::create_dir_all(parent)?;
    let mut options = std::fs::OpenOptions::new();
    options.write(true).create_new(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.mode(0o600);
    }
    let mut file = options.open(path)?;
    file.write_all(bytes)?;
    file.write_all(b"\n")?;
    file.sync_all()?;
    drop(file);
    #[cfg(unix)]
    std::fs::File::open(parent)?.sync_all()?;
    Ok(())
}

fn parse_epoch(value: std::ffi::OsString, label: &str) -> anyhow::Result<u64> {
    let epoch = to_utf8(value, label)?
        .parse::<u64>()
        .map_err(|error| anyhow::anyhow!("{label} is invalid: {error}"))?;
    if epoch == 0 {
        anyhow::bail!("{label} must be non-zero");
    }
    Ok(epoch)
}

fn to_utf8(value: std::ffi::OsString, label: &str) -> anyhow::Result<String> {
    value
        .into_string()
        .map_err(|_| anyhow::anyhow!("{label} is not UTF-8"))
}

fn hex_value(value: u8) -> anyhow::Result<u8> {
    match value {
        b'0'..=b'9' => Ok(value - b'0'),
        b'a'..=b'f' => Ok(value - b'a' + 10),
        b'A'..=b'F' => Ok(value - b'A' + 10),
        _ => anyhow::bail!("public key contains non-hex data"),
    }
}

fn usage() -> &'static str {
    "usage: hepta-supervisor-authority-bundle --grant-verifier-key ABSOLUTE_PATH --grant-signer-id ID --grant-signer-epoch N --h7-verifier-key ABSOLUTE_PATH --h7-signer-id ID --h7-signer-epoch N --output ABSOLUTE_PATH"
}
