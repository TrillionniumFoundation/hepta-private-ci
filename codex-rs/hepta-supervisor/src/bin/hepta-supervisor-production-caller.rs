use std::io::Read;
use std::path::PathBuf;

use anyhow::Context;
use anyhow::Result;
use anyhow::bail;
use codex_hepta_supervisor::ProductionCallerRequest;
use codex_hepta_supervisor::execute_production_caller;

const MAX_REQUEST_BYTES: u64 = 65_536;

#[tokio::main]
async fn main() -> Result<()> {
    let mut args = std::env::args_os().skip(1);
    let mut socket = None;
    let mut request_path = None;
    while let Some(flag) = args.next() {
        let value = args.next().context("every option requires a value")?;
        match flag.to_str() {
            Some("--socket") if socket.is_none() => socket = Some(PathBuf::from(value)),
            Some("--request") if request_path.is_none() => {
                request_path = Some(PathBuf::from(value))
            }
            _ => bail!(
                "usage: hepta-supervisor-production-caller --socket ABSOLUTE_SOCKET --request SIGNED_REQUEST_JSON"
            ),
        }
    }
    let socket = socket.context("--socket is required")?;
    let request_path = request_path.context("--request is required")?;
    if !socket.is_absolute() || !request_path.is_absolute() {
        bail!("socket and request paths must be absolute");
    }
    let metadata = std::fs::symlink_metadata(&request_path)?;
    if !metadata.file_type().is_file()
        || metadata.file_type().is_symlink()
        || metadata.len() > MAX_REQUEST_BYTES
    {
        bail!("production caller request must be a bounded regular non-symlink file");
    }
    let mut bytes = Vec::new();
    std::fs::File::open(&request_path)?
        .take(MAX_REQUEST_BYTES + 1)
        .read_to_end(&mut bytes)?;
    if bytes.len() as u64 > MAX_REQUEST_BYTES {
        bail!("production caller request exceeds its bound");
    }
    let request: ProductionCallerRequest =
        serde_json::from_slice(&bytes).context("decode production caller request")?;
    let accepted = execute_production_caller(socket, request).await?;
    println!("{}", serde_json::to_string_pretty(&accepted.agent)?);
    if let Some(receipt) = accepted.production_receipt {
        eprintln!("{}", serde_json::to_string_pretty(&receipt)?);
    }
    Ok(())
}
