//! Read-only owner observation. Run locally on each authorized host; transport
//! and independently attest the exact result through existing evidence owners.
//! No SSH credentials, remote host assumptions, signing keys or mutation APIs.

use std::fs::OpenOptions;
use std::io::Read;
use std::io::Write;
use std::path::PathBuf;

use anyhow::Result;
use anyhow::ensure;
use codex_hepta_supervisor::SupervisordClient;
use codex_hepta_supervisor::SupervisordControlFence;
use sha2::Digest;
use sha2::Sha256;
use tokio_util::sync::CancellationToken;

#[tokio::main]
async fn main() -> Result<()> {
    let args: Vec<_> = std::env::args_os().skip(1).collect();
    ensure!(
        args.len() == 3,
        "usage: observe_memory_owner SOCKET EXPECTED_FENCE.json NEW_OUTPUT.json"
    );
    let expectation = PathBuf::from(&args[1]);
    let output = PathBuf::from(&args[2]);
    ensure!(
        expectation.is_absolute() && output.is_absolute(),
        "absolute paths required"
    );
    ensure!(
        !std::fs::symlink_metadata(&expectation)?
            .file_type()
            .is_symlink(),
        "symlink fence rejected"
    );
    let mut bytes = Vec::new();
    std::fs::File::open(&expectation)?
        .take(65_537)
        .read_to_end(&mut bytes)?;
    ensure!(bytes.len() <= 65_536, "fence exceeds byte bound");
    let fence: SupervisordControlFence = serde_json::from_slice(&bytes)?;
    let client = SupervisordClient::new(PathBuf::from(&args[0]))?;
    let stop = CancellationToken::new();
    let result = client.observe_current(&fence, &stop).await?;
    let envelope = serde_json::json!({
        "expected_fence_file_sha256": format!("{:x}", Sha256::digest(&bytes)),
        "observation": result,
        "authority": "unsigned-owner-local-read-not-independent-acceptance",
        "production_accepted": false,
    });
    let mut serialized = serde_json::to_vec_pretty(&envelope)?;
    serialized.push(b'\n');
    ensure!(
        serialized.len() <= 262_144,
        "observation output exceeds byte bound"
    );
    let mut options = OpenOptions::new();
    options.create_new(true).write(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.mode(0o600);
    }
    let mut file = options.open(&output)?;
    file.write_all(&serialized)?;
    file.sync_all()?;
    println!("observation_sha256={:x}", Sha256::digest(&serialized));
    Ok(())
}
