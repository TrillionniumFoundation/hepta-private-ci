//! Named production composition root for hosted inference.
//!
//! Trust configuration is a protected host input. The independently signed
//! final-use grant is supplied separately and is never allowed to replace the
//! pinned signer, epoch, revocation head, Agent identity, model or journal.

#![forbid(unsafe_code)]

use std::collections::BTreeSet;
use std::fs;
use std::io::Read;
use std::path::{Path, PathBuf};
use std::time::Duration;

use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseRevocations;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_infer_core::durable_control::DurableInferenceControl;
use codex_hepta_infer_worker_host::native_app_server::NativeAdmission;
use codex_hepta_infer_worker_host::native_app_server::NativeWorkerConfig;
use codex_hepta_inferd::worker_port::NativeWorkerPort;
use serde::Deserialize;
use tokio::io::AsyncReadExt;
use tokio_util::sync::CancellationToken;

const MAX_HOST_CONFIG_BYTES: usize = 64 * 1024;
const MAX_GRANT_BYTES: usize = 32 * 1024;
const MAX_PROMPT_BYTES: u64 = 32 * 1024 + 1;
const JOURNAL_CAPACITY: usize = 16_384;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct HostConfig {
    agentd_socket: PathBuf,
    agent_id: String,
    generation: u64,
    model: String,
    timeout_ms: u64,
    journal: PathBuf,
    maximum_in_flight: usize,
    signer_id: String,
    verifying_key: [u8; 32],
    authority_state_dir: PathBuf,
    authority_epoch: u64,
    revocation_revision: u64,
    revoked_grant_ids: BTreeSet<String>,
}

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error + Send + Sync>> {
    let mut args = std::env::args().skip(1);
    let command = args.next().ok_or(usage())?;
    if command == "--help" || command == "help" {
        println!("{}", usage());
        return Ok(());
    }
    if command != "execute" {
        return Err(usage().into());
    }
    let host_path = args.next().ok_or(usage())?;
    let grant_path = args.next().ok_or(usage())?;
    let request_id = args.next().ok_or(usage())?;
    if args.next().is_some() {
        return Err(usage().into());
    }

    let host: HostConfig = serde_json::from_slice(&read_host_config(Path::new(&host_path))?)?;
    validate_host_config(&host)?;
    let grant: SignedFinalUseGrant =
        serde_json::from_slice(&bounded_regular_file(Path::new(&grant_path), MAX_GRANT_BYTES)?)?;

    let authority = FinalUseAuthority::open_state_dir(
        &host.authority_state_dir,
        host.signer_id,
        host.verifying_key,
        FinalUseRevocations {
            authority_epoch: host.authority_epoch,
            revision: host.revocation_revision,
            revoked_grant_ids: host.revoked_grant_ids,
        },
    )?;
    let port = NativeWorkerPort::new(NativeWorkerConfig {
        agentd_socket: host.agentd_socket,
        agent_id: AgentId::parse(host.agent_id)?,
        generation: host.generation,
        model: host.model,
        timeout: Duration::from_millis(host.timeout_ms),
    })?;
    let mut control = DurableInferenceControl::open(&host.journal, JOURNAL_CAPACITY)?;

    let mut prompt = String::new();
    tokio::io::stdin()
        .take(MAX_PROMPT_BYTES)
        .read_to_string(&mut prompt)
        .await?;
    if prompt.len() > MAX_PROMPT_BYTES as usize - 1 {
        return Err("prompt exceeds 32768 bytes".into());
    }

    let cancellation = CancellationToken::new();
    let signal = cancellation.clone();
    let signal_task = tokio::spawn(async move {
        if tokio::signal::ctrl_c().await.is_ok() {
            signal.cancel();
        }
    });
    let result = port
        .execute(
            &mut control,
            &authority,
            &grant,
            NativeAdmission {
                request_id,
                maximum_in_flight: host.maximum_in_flight,
            },
            prompt,
            &cancellation,
        )
        .await;
    signal_task.abort();

    let output = result?;
    println!("{}", serde_json::to_string(&output)?);
    if !output.terminal_observed {
        return Err("provider outcome remains indeterminate; no replacement dispatch was issued".into());
    }
    if !output.succeeded() {
        return Err("provider run did not complete under current owner authority".into());
    }
    Ok(())
}

fn validate_host_config(config: &HostConfig) -> Result<(), Box<dyn std::error::Error + Send + Sync>> {
    if !config.agentd_socket.is_absolute()
        || !config.journal.is_absolute()
        || !config.authority_state_dir.is_absolute()
    {
        return Err("host-owned socket, journal and authority state paths must be absolute".into());
    }
    if config.maximum_in_flight == 0 || config.maximum_in_flight > JOURNAL_CAPACITY {
        return Err("maximum_in_flight is outside the journal capacity".into());
    }
    if config.authority_epoch == 0 || config.revocation_revision == 0 {
        return Err("authority epoch/revision must be nonzero".into());
    }
    Ok(())
}

fn read_host_config(path: &Path) -> Result<Vec<u8>, Box<dyn std::error::Error + Send + Sync>> {
    if !path.is_absolute() {
        return Err("host config path must be absolute".into());
    }
    let metadata = fs::symlink_metadata(path)?;
    if metadata.file_type().is_symlink() || !metadata.is_file() {
        return Err("host config must be a regular non-symlink file".into());
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        if metadata.permissions().mode() & 0o077 != 0 {
            return Err("host config must not be group/world accessible".into());
        }
    }
    bounded_regular_file(path, MAX_HOST_CONFIG_BYTES)
}

fn bounded_regular_file(
    path: &Path,
    maximum: usize,
) -> Result<Vec<u8>, Box<dyn std::error::Error + Send + Sync>> {
    let metadata = fs::symlink_metadata(path)?;
    if metadata.file_type().is_symlink() || !metadata.is_file() {
        return Err("input must be a regular non-symlink file".into());
    }
    let mut bytes = Vec::new();
    fs::File::open(path)?
        .take((maximum + 1) as u64)
        .read_to_end(&mut bytes)?;
    if bytes.len() > maximum {
        return Err("input exceeds its bound".into());
    }
    Ok(bytes)
}

fn usage() -> &'static str {
    "usage: hepta-inference-runtime-host execute ABS_HOST_CONFIG.json SIGNED_GRANT.json REQUEST_ID < PROMPT"
}

#[cfg(test)]
mod tests {
    use super::*;

    fn config() -> HostConfig {
        HostConfig {
            agentd_socket: PathBuf::from("/run/hepta/agentd.sock"),
            agent_id: "018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12".to_string(),
            generation: 7,
            model: "model.exact".to_string(),
            timeout_ms: 30_000,
            journal: PathBuf::from("/var/lib/hepta/inference.journal"),
            maximum_in_flight: 8,
            signer_id: "inference-authority".to_string(),
            verifying_key: [7; 32],
            authority_state_dir: PathBuf::from("/var/lib/hepta/final-use"),
            authority_epoch: 9,
            revocation_revision: 11,
            revoked_grant_ids: BTreeSet::new(),
        }
    }

    #[test]
    fn production_host_rejects_relative_trust_or_state_paths() {
        let mut value = config();
        assert!(validate_host_config(&value).is_ok());
        value.journal = PathBuf::from("relative.journal");
        assert!(validate_host_config(&value).is_err());
    }

    #[test]
    fn production_host_rejects_zero_or_unbounded_local_admission() {
        let mut value = config();
        value.maximum_in_flight = 0;
        assert!(validate_host_config(&value).is_err());
        value.maximum_in_flight = JOURNAL_CAPACITY + 1;
        assert!(validate_host_config(&value).is_err());
    }
}
