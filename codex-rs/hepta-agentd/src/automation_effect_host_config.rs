//! Attested active and lookup-only historical profiles for the existing effect host.
use super::*;

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct AutomationEffectHostFileV1 {
    pub(super) schema_version: u32,
    pub(super) provider_scope: String,
    pub(super) destination_id: String,
    pub(super) final_use_scope_sha256: String,
    pub(super) dispatch_url: String,
    pub(super) lookup_url_template: String,
    #[serde(default)]
    pub(super) headers: BTreeMap<String, String>,
    pub(super) timeout_ms: u64,
    pub(super) contract_id: String,
    pub(super) contract_sha256: String,
    pub(super) contract_authority_epoch: u64,
    pub(super) contract_signature_hex: String,
    pub(super) contract_verifying_key_hex: String,
    pub(super) final_use_signer_id: String,
    pub(super) final_use_verifying_key_hex: String,
    pub(super) final_use_revocations_file: PathBuf,
    #[serde(default)]
    pub(super) recovery_profiles: Vec<AutomationEffectProviderProfileFileV1>,
}

#[derive(Clone, Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct AutomationEffectProviderProfileFileV1 {
    pub(super) provider_scope: String,
    pub(super) destination_id: String,
    pub(super) final_use_scope_sha256: String,
    pub(super) dispatch_url: String,
    pub(super) lookup_url_template: String,
    #[serde(default)]
    pub(super) headers: BTreeMap<String, String>,
    pub(super) timeout_ms: u64,
    pub(super) contract_id: String,
    pub(super) contract_sha256: String,
    pub(super) contract_authority_epoch: u64,
    pub(super) contract_signature_hex: String,
    pub(super) contract_verifying_key_hex: String,
}

#[derive(Clone)]
pub(super) struct AutomationEffectRecoveryProfile {
    pub(super) destination_id: String,
    pub(super) final_use_scope_digest: Sha256Digest,
    pub(super) adapter: HttpProviderEffectAdapter,
}

pub(super) struct AutomationEffectProviderProfileView<'a> {
    pub(super) provider_scope: &'a str,
    pub(super) destination_id: &'a str,
    pub(super) final_use_scope_sha256: &'a str,
    pub(super) dispatch_url: &'a str,
    pub(super) lookup_url_template: &'a str,
    pub(super) headers: &'a BTreeMap<String, String>,
    pub(super) timeout_ms: u64,
    pub(super) contract_id: &'a str,
    pub(super) contract_sha256: &'a str,
    pub(super) contract_authority_epoch: u64,
    pub(super) contract_signature_hex: &'a str,
    pub(super) contract_verifying_key_hex: &'a str,
}

impl AutomationEffectHostFileV1 {
    pub(super) fn active_profile(&self) -> AutomationEffectProviderProfileView<'_> {
        AutomationEffectProviderProfileView {
            provider_scope: &self.provider_scope,
            destination_id: &self.destination_id,
            final_use_scope_sha256: &self.final_use_scope_sha256,
            dispatch_url: &self.dispatch_url,
            lookup_url_template: &self.lookup_url_template,
            headers: &self.headers,
            timeout_ms: self.timeout_ms,
            contract_id: &self.contract_id,
            contract_sha256: &self.contract_sha256,
            contract_authority_epoch: self.contract_authority_epoch,
            contract_signature_hex: &self.contract_signature_hex,
            contract_verifying_key_hex: &self.contract_verifying_key_hex,
        }
    }
}

impl AutomationEffectProviderProfileFileV1 {
    pub(super) fn view(&self) -> AutomationEffectProviderProfileView<'_> {
        AutomationEffectProviderProfileView {
            provider_scope: &self.provider_scope,
            destination_id: &self.destination_id,
            final_use_scope_sha256: &self.final_use_scope_sha256,
            dispatch_url: &self.dispatch_url,
            lookup_url_template: &self.lookup_url_template,
            headers: &self.headers,
            timeout_ms: self.timeout_ms,
            contract_id: &self.contract_id,
            contract_sha256: &self.contract_sha256,
            contract_authority_epoch: self.contract_authority_epoch,
            contract_signature_hex: &self.contract_signature_hex,
            contract_verifying_key_hex: &self.contract_verifying_key_hex,
        }
    }
}

pub(super) struct OpenedProviderProfile {
    pub(super) provider_scope: String,
    pub(super) destination_id: String,
    pub(super) final_use_scope_digest: Sha256Digest,
    pub(super) profile_digest: Sha256Digest,
    pub(super) adapter: HttpProviderEffectAdapter,
}

pub(super) fn open_provider_profile(
    config: AutomationEffectProviderProfileView<'_>,
) -> Result<OpenedProviderProfile, AgentdError> {
    validate_host_identifier("provider_scope", config.provider_scope)?;
    validate_host_identifier("destination_id", config.destination_id)?;
    if config.timeout_ms == 0
        || config.timeout_ms > 30_000
        || config.headers.len() > MAX_PROVIDER_HEADERS
    {
        return Err(AgentdError::Invalid(
            "provider timeout/header bound exceeded".to_string(),
        ));
    }
    let final_use_scope_digest = Sha256Digest::parse(config.final_use_scope_sha256.to_string())
        .map_err(AgentdError::Invalid)?;
    let contract_digest =
        Sha256Digest::parse(config.contract_sha256.to_string()).map_err(AgentdError::Invalid)?;
    let signature =
        decode_hex_array::<64>(config.contract_signature_hex, "contract_signature_hex")?;
    let key = decode_hex_array::<32>(
        config.contract_verifying_key_hex,
        "contract_verifying_key_hex",
    )?;
    let attestation = HttpProviderEffectContractAttestation::verify_signed(
        config.contract_id.to_string(),
        contract_digest.clone(),
        config.contract_authority_epoch,
        &signature,
        &key,
    )
    .map_err(AgentdError::Invalid)?;
    let profile_digest = automation_effect_profile_digest(&config, &contract_digest);
    let mut headers = HeaderMap::new();
    for (name, value) in config.headers {
        let name = HeaderName::from_bytes(name.as_bytes())
            .map_err(|error| AgentdError::Invalid(format!("invalid provider header: {error}")))?;
        let value = HeaderValue::from_bytes(value.as_bytes())
            .map_err(|error| AgentdError::Invalid(format!("invalid provider header: {error}")))?;
        headers.append(name, value);
    }
    let adapter = HttpProviderEffectAdapter::new(HttpProviderEffectConfig {
        dispatch_url: config.dispatch_url.to_string(),
        lookup_url_template: config.lookup_url_template.to_string(),
        headers,
        timeout: Duration::from_millis(config.timeout_ms),
        contract_id: config.contract_id.to_string(),
        attestation: Some(attestation),
    })
    .map_err(AgentdError::Invalid)?;
    Ok(OpenedProviderProfile {
        provider_scope: config.provider_scope.to_string(),
        destination_id: config.destination_id.to_string(),
        final_use_scope_digest,
        profile_digest,
        adapter,
    })
}

fn automation_effect_profile_digest(
    config: &AutomationEffectProviderProfileView<'_>,
    contract_digest: &Sha256Digest,
) -> Sha256Digest {
    let mut bytes = b"hepta.agentd.automation-effect-profile.v1\0".to_vec();
    for value in [
        config.provider_scope,
        config.destination_id,
        config.final_use_scope_sha256,
        config.dispatch_url,
        config.lookup_url_template,
        config.contract_id,
        contract_digest.as_str(),
        config.contract_verifying_key_hex,
    ] {
        push_profile_text(&mut bytes, value);
    }
    bytes.extend_from_slice(&config.timeout_ms.to_be_bytes());
    bytes.extend_from_slice(&config.contract_authority_epoch.to_be_bytes());
    for (name, value) in config.headers {
        push_profile_text(&mut bytes, name);
        push_profile_text(
            &mut bytes,
            Sha256Digest::for_bytes(value.as_bytes()).as_str(),
        );
    }
    Sha256Digest::for_bytes(&bytes)
}

pub(super) fn read_host_file(path: &Path) -> Result<AutomationEffectHostFileV1, AgentdError> {
    let bytes = read_protected_file(
        path,
        MAX_AUTOMATION_EFFECT_HOST_FILE_BYTES,
        "automation effect host file",
    )?;
    Ok(serde_json::from_slice(&bytes)?)
}

pub(super) fn read_revocations_file(path: &Path) -> Result<FinalUseRevocations, AgentdError> {
    let bytes = read_protected_file(
        path,
        MAX_AUTOMATION_EFFECT_REVOCATIONS_FILE_BYTES,
        "automation effect revocations file",
    )?;
    Ok(serde_json::from_slice(&bytes)?)
}

fn read_protected_file(path: &Path, max_bytes: u64, label: &str) -> Result<Vec<u8>, AgentdError> {
    if !path.is_absolute() {
        return Err(AgentdError::Invalid(format!("{label} must be absolute")));
    }
    let canonical = path.canonicalize()?;
    if canonical != path {
        return Err(AgentdError::Invalid(format!(
            "{label} must be canonical and symlink-free"
        )));
    }
    let metadata = fs::symlink_metadata(path)?;
    if metadata.file_type().is_symlink() || !metadata.is_file() {
        return Err(AgentdError::Invalid(format!(
            "{label} must be a regular non-symlink file"
        )));
    }
    if metadata.len() == 0 || metadata.len() > max_bytes {
        return Err(AgentdError::Invalid(format!(
            "{label} is empty or too large"
        )));
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        if metadata.permissions().mode() & 0o077 != 0 {
            return Err(AgentdError::Invalid(format!(
                "{label} must not be group/world accessible"
            )));
        }
    }
    Ok(fs::read(path)?)
}

pub(super) fn validate_host_identifier(label: &str, value: &str) -> Result<(), AgentdError> {
    if value.is_empty()
        || value.len() > 128
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || b"_-.:/".contains(&byte))
    {
        return Err(AgentdError::Invalid(format!(
            "{label} must be a bounded identifier"
        )));
    }
    Ok(())
}

pub(super) fn decode_hex_array<const N: usize>(
    value: &str,
    label: &str,
) -> Result<[u8; N], AgentdError> {
    if value.len() != N * 2 {
        return Err(AgentdError::Invalid(format!(
            "{label} must contain exactly {} hex characters",
            N * 2
        )));
    }
    let bytes = value.as_bytes();
    let mut output = [0_u8; N];
    for (index, slot) in output.iter_mut().enumerate() {
        let offset = index * 2;
        let high = hex_nibble(bytes[offset])
            .ok_or_else(|| AgentdError::Invalid(format!("{label} contains non-hex data")))?;
        let low = hex_nibble(bytes[offset + 1])
            .ok_or_else(|| AgentdError::Invalid(format!("{label} contains non-hex data")))?;
        *slot = (high << 4) | low;
    }
    Ok(output)
}

fn hex_nibble(value: u8) -> Option<u8> {
    match value {
        b'0'..=b'9' => Some(value - b'0'),
        b'a'..=b'f' => Some(value - b'a' + 10),
        b'A'..=b'F' => Some(value - b'A' + 10),
        _ => None,
    }
}

pub(super) fn push_profile_text(bytes: &mut Vec<u8>, value: &str) {
    bytes.extend_from_slice(&(value.len() as u64).to_be_bytes());
    bytes.extend_from_slice(value.as_bytes());
}
