//! Original Root administration observations used by the two-boot transcript.
//! No saved value enters an issuer, checkpoint, clock or registry constructor.
use super::*;
use codex_hepta_contracts::Sha256Digest;

#[derive(Deserialize, Serialize, Eq, PartialEq)]
#[serde(deny_unknown_fields)]
pub(super) struct PinObservation {
    path: PathBuf,
    device: u64,
    inode: u64,
    bytes: u64,
    sha256: Sha256Digest,
    expected_verifying_key: [u8; 32],
}

pub(super) fn pin(config: &HostAuthorityServiceConfig) -> io::Result<PinObservation> {
    let path = Path::new(STATE).join("protected/installation.json");
    let file = std::fs::OpenOptions::new()
        .read(true)
        .custom_flags(libc::O_NOFOLLOW | libc::O_CLOEXEC)
        .open(&path)?;
    let actual = file.metadata()?;
    if !actual.is_file()
        || actual.uid() != 0
        || actual.gid() != 0
        || actual.mode() & 0o7777 != 0o600
        || actual.nlink() != 1
        || actual.len() > 32768
    {
        return Err(invalid("original independently installed pin is unsafe"));
    }
    let mut bytes = Vec::new();
    (&file).take(32769).read_to_end(&mut bytes)?;
    let current = std::fs::symlink_metadata(&path)?;
    if bytes.len() as u64 != actual.len()
        || current.dev() != actual.dev()
        || current.ino() != actual.ino()
        || current.mode() != actual.mode()
    {
        return Err(invalid(
            "installed pin inode changed while observing its bytes",
        ));
    }
    let value: serde_json::Value = serde_json::from_slice(&bytes).map_err(error)?;
    if value["config"]["expected_verifying_key"]
        != serde_json::to_value(config.expected_verifying_key).map_err(error)?
        || value["config"]["signer_id"].as_str() != Some(config.signer_id.as_str())
    {
        return Err(invalid(
            "installed pin differs from original protected issuer opening",
        ));
    }
    Ok(PinObservation {
        path,
        device: actual.dev(),
        inode: actual.ino(),
        bytes: actual.len(),
        sha256: Sha256Digest::for_bytes(&bytes),
        expected_verifying_key: config.expected_verifying_key,
    })
}

pub(super) fn authority(original: &Installation) -> io::Result<serde_json::Value> {
    let clock = original.clock.refresh_projection().map_err(error)?;
    let canonical = original.issuer.retained_writer_state_for_root()?;
    let registry = original
        .leases
        .read_unretired_for_principal(
            AGENT,
            codex_hepta_contracts::authority_lease::MAX_AUTHORITY_LEASES,
        )
        .map_err(error)?;
    Ok(serde_json::json!({"issuer_sequence":canonical.sequence,
        "writer_proof_sha256":canonical.proof.sha256().map_err(error)?,
        "writer":canonical.registration,"revocations":canonical.revocations,"registry":registry,
        "clock":{"projection":clock.projection,"observed_unix_ms":clock.observed_unix_ms}}))
}

pub(super) fn observation_id(boot: &str, nonce: &str) -> String {
    format!("native-boot-cut.{boot}.{nonce}")
}

pub(super) fn observation_path(config: &HostAuthorityServiceConfig, id: &str) -> PathBuf {
    let digest = Sha256Digest::for_bytes(id.as_bytes());
    config
        .state_dir
        .join("native-launch-observations")
        .join(format!("observation-v1-{}.json", digest.as_str()))
}

pub(super) fn require_zero_calls(value: &serde_json::Value) -> io::Result<()> {
    if value["install_ioctl_count"].as_u64() != Some(0)
        || value["query_ioctl_count"].as_u64() != Some(0)
    {
        return Err(invalid(
            "original new descriptor already entered Install or Query",
        ));
    }
    Ok(())
}

pub(super) fn require_unknown(value: &serde_json::Value, cut: &SavedCut) -> io::Result<()> {
    let state: LocalOutcomeState =
        serde_json::from_value(value["before"]["state"].clone()).map_err(error)?;
    if value["occurrence_key"].as_str() != Some(cut.occurrence_key.as_str())
        || value["request_json"].as_str() != Some(cut.payload_json.as_str())
        || value["before"]["topic"].as_str() != Some(codex_hepta_memory::HOS2_INSTALL_TOPIC_V1)
        || value["before"]["payload_json"].as_str() != Some(cut.payload_json.as_str())
        || state != LocalOutcomeState::Indeterminate
        || value["before"] != value["after"]
        || value["calls_before"] != value["calls_after"]
        || value["refusal"].as_str() != Some("native boot changed; the old D remains unknown")
        || value["drain_blockers"].as_u64() != Some(1)
    {
        return Err(invalid(
            "old K/D did not remain unresolved after its actual boot refusal",
        ));
    }
    Ok(())
}
