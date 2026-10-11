//! Operator-facing, one-effect-at-a-time CellSplit coordination.
//!
//! This command is a client of four separately pinned real effect owners.
//! Its configuration is not trusted by its location or by contents inside it:
//! an independently supplied SHA-256 of the exact configuration bytes is
//! mandatory. Server-side final-use and Selector/NDU checks remain required.
//! Even a completed transcript cannot issue production or promotion authority.

use std::fs::OpenOptions;
use std::io::Read;
use std::path::Path;
use std::path::PathBuf;
use std::time::Duration;

use ed25519_dalek::VerifyingKey;
use serde::Deserialize;
use serde::Serialize;
use sha2::Digest as _;
use sha2::Sha256;

use crate::CellSplitExecutionOwnerV1;
use crate::CellSplitExecutionPlanV1;
use crate::CellSplitExecutionReceiptV1;
use crate::CellSplitExecutionTranscriptV1;
use crate::CellSplitOwnerTrustV1;
use crate::CellSplitUnixEffectPortV1;

const CONFIG_SCHEMA: &str = "hepta.learning.cell-split.execution-cli.v1";
const OUTCOME_SCHEMA: &str = "hepta.learning.cell-split.execution-cli-result.v1";
const MAX_CONFIG_BYTES: u64 = 64 * 1024;

#[derive(Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct ExecutionConfigV1 {
    schema: String,
    plan: CellSplitExecutionPlanV1,
    execution_root: PathBuf,
    owner_socket_paths: [PathBuf; 4],
    owner_verifying_keys_hex: [String; 4],
    timeout_millis: u64,
}

/// Diagnostic/effect-coordinate output. Never a signed production acceptance.
#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct CellSplitExecutionCliOutcomeV1 {
    schema: &'static str,
    action: &'static str,
    completed_steps: usize,
    complete: bool,
    receipt: Option<CellSplitExecutionReceiptV1>,
    transcript: Option<CellSplitExecutionTranscriptV1>,
    production_activation_authorized: bool,
}

/// Advance one committed step, or perform read-only verification of all four.
/// The independent operator supplies the frozen configuration's exact SHA-256;
/// no digest asserted inside the JSON is treated as an external trust anchor.
pub fn run_pinned_cell_split_execution_v1(
    action: &str,
    config_path: &Path,
    externally_pinned_config_sha256: &str,
) -> Result<CellSplitExecutionCliOutcomeV1, String> {
    let selected_action = match action {
        "advance" => "advance",
        "transcript" => "transcript",
        _ => return Err("expected advance or transcript".to_string()),
    };

    let config_bytes = read_private_config(config_path)?;
    if !canonical_hex(externally_pinned_config_sha256)
        || format!("{:x}", Sha256::digest(&config_bytes)) != externally_pinned_config_sha256
    {
        return Err("execution configuration does not match the external SHA-256 pin".to_string());
    }
    let config: ExecutionConfigV1 = serde_json::from_slice(&config_bytes)
        .map_err(|error| format!("invalid execution configuration: {error}"))?;
    if config.schema != CONFIG_SCHEMA {
        return Err("unknown execution configuration schema".to_string());
    }
    if config.timeout_millis == 0 || config.timeout_millis > 30_000 {
        return Err("RPC timeout must be between 1 and 30000 ms".to_string());
    }
    let parsed_keys = config
        .owner_verifying_keys_hex
        .iter()
        .map(|key| parse_verifying_key(key))
        .collect::<Result<Vec<_>, _>>()?;
    let keys: [VerifyingKey; 4] = parsed_keys
        .try_into()
        .map_err(|_| "exactly four pinned owner keys are required".to_string())?;
    let trust = CellSplitOwnerTrustV1::new(&config.plan, keys.clone())
        .map_err(|error| error.to_string())?;
    let port = CellSplitUnixEffectPortV1::new(
        config.owner_socket_paths,
        keys,
        Duration::from_millis(config.timeout_millis),
    )
    .map_err(|error| error.to_string())?;
    let mut owner = CellSplitExecutionOwnerV1::open(
        &config.execution_root,
        config.plan,
        trust,
        port,
    )
    .map_err(|error| error.to_string())?;
    let (receipt, transcript) = match selected_action {
        "advance" => (
            owner.advance().map_err(|error| error.to_string())?,
            None,
        ),
        _ => (
            None,
            owner
                .verified_transcript()
                .map_err(|error| error.to_string())?,
        ),
    };
    Ok(CellSplitExecutionCliOutcomeV1 {
        schema: OUTCOME_SCHEMA,
        action: selected_action,
        completed_steps: owner.completed_steps(),
        complete: owner.is_complete(),
        receipt,
        transcript,
        production_activation_authorized: false,
    })
}

fn canonical_hex(value: &str) -> bool {
    value.len() == 64
        && value.bytes().all(|ch| ch.is_ascii_hexdigit() && !ch.is_ascii_uppercase())
}

fn parse_verifying_key(value: &str) -> Result<VerifyingKey, String> {
    if !canonical_hex(value) {
        return Err("owner verification key must be 32 bytes of lowercase hex".to_string());
    }
    let mut bytes = [0_u8; 32];
    for (index, target) in bytes.iter_mut().enumerate() {
        *target = u8::from_str_radix(&value[index * 2..index * 2 + 2], 16)
            .map_err(|_| "malformed owner verification key".to_string())?;
    }
    VerifyingKey::from_bytes(&bytes).map_err(|_| "invalid owner verification key".to_string())
}

fn read_private_config(path: &Path) -> Result<Vec<u8>, String> {
    if !path.is_absolute() || path.canonicalize().map_err(|e| e.to_string())? != path {
        return Err("configuration path must be canonical, absolute and symlink-free".to_string());
    }
    let mut options = OpenOptions::new();
    options.read(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt as _;
        options.custom_flags(libc::O_NOFOLLOW | libc::O_CLOEXEC);
    }
    let mut file = options.open(path).map_err(|error| error.to_string())?;
    let before = file.metadata().map_err(|error| error.to_string())?;
    if !before.is_file() || before.len() > MAX_CONFIG_BYTES {
        return Err("configuration must be a bounded regular file".to_string());
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::MetadataExt as _;
        if before.mode() & 0o077 != 0 {
            return Err("configuration file must not be accessible by group or others".to_string());
        }
    }
    let mut bytes = Vec::new();
    (&mut file)
        .take(MAX_CONFIG_BYTES + 1)
        .read_to_end(&mut bytes)
        .map_err(|error| error.to_string())?;
    if bytes.is_empty() || bytes.len() as u64 > MAX_CONFIG_BYTES {
        return Err("empty or oversized configuration".to_string());
    }
    let after_fd = file.metadata().map_err(|error| error.to_string())?;
    let after_path = std::fs::symlink_metadata(path).map_err(|error| error.to_string())?;
    #[cfg(unix)]
    {
        use std::os::unix::fs::MetadataExt as _;
        if !after_path.is_file()
            || before.dev() != after_fd.dev()
            || before.ino() != after_fd.ino()
            || before.len() != after_fd.len()
            || before.dev() != after_path.dev()
            || before.ino() != after_path.ino()
            || before.len() != after_path.len()
            || after_path.mode() & 0o077 != 0
        {
            return Err("configuration changed while being read".to_string());
        }
    }
    Ok(bytes)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn requires_external_config_pin_before_opening_any_owner() {
        let dir = tempfile::tempdir().expect("tempdir");
        let file = dir.path().join("config.json");
        std::fs::write(&file, b"{}").expect("fixture");
        use std::os::unix::fs::PermissionsExt as _;
        std::fs::set_permissions(&file, std::fs::Permissions::from_mode(0o600))
            .expect("private config");
        let error = run_pinned_cell_split_execution_v1(
            "advance",
            &file,
            &format!("{:x}", Sha256::digest(b"different configuration")),
        )
        .expect_err("untrusted config must fail");
        assert!(error.contains("external SHA-256 pin"));
    }

    #[test]
    fn rejects_malformed_and_shared_owner_keys() {
        assert!(parse_verifying_key(&"GG".repeat(32)).is_err());
        assert!(parse_verifying_key(&"00".repeat(31)).is_err());
        assert!(canonical_hex(&"00".repeat(32)));
        assert!(!canonical_hex(&"AA".repeat(32)));
    }

    #[test]
    fn rejects_unknown_action_before_any_disk_or_network_access() {
        let error = run_pinned_cell_split_execution_v1(
            "promote",
            Path::new("/nonexistent-cell-split-config"),
            &"00".repeat(32),
        )
        .expect_err("no promotion action");
        assert!(error.contains("advance or transcript"));
    }
}
