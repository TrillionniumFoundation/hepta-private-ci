//! Ordinary-process composition from an explicitly pinned host descriptor.
//! Parsing is cached by raw publication bytes, never by a freshness lease.

use super::LeasedMemoryRetrievalProviderV1;
use super::SignedMemoryRetrievalContextV1;
use crate::AgentdIdentity;
use crate::CurrentMemoryRetrievalContext;
use codex_hepta_agent_components::contracts::AgentId;
use codex_hepta_agent_components::memory::RetrievalExecutionContextV1;
use codex_hepta_agent_components::memory_retrieval::MAX_ENGRAM_NODES;
use codex_hepta_agent_components::memory_retrieval::MAX_ENGRAM_SETTLING_STEPS;
use codex_hepta_agent_components::memory_retrieval::MAX_ENGRAM_SYNAPSES;
use codex_hepta_agent_components::memory_retrieval::MAX_GENERATION_BOUND_CANDIDATES;
use codex_hepta_agent_components::memory_retrieval::RetrievalChannelV1;
use codex_hepta_agent_components::memory_retrieval::RetrievalPolicyV1;
use codex_hepta_agent_components::types::Digest32;
use codex_hepta_agent_components::types::FixedQ32;
use serde::Deserialize;
#[cfg(unix)]
use std::fs::File;
#[cfg(unix)]
use std::io::Read;
use std::net::SocketAddr;
use std::path::Path;
use std::path::PathBuf;
use std::sync::Arc;
use std::time::Duration;

#[path = "cognitive_retrieval_context_codec.rs"]
mod codec;
#[path = "cognitive_retrieval_present_field.rs"]
mod present_field;
#[path = "cognitive_retrieval_publication_cache.rs"]
mod publication_cache;
use present_field::present_value;
use publication_cache::PublicationCache;

const MAX_DESCRIPTOR_BYTES: usize = 16 * 1024;
const MAX_PUBLICATION_BYTES: usize = 2 * codec::MAX_CONTEXT_BYTES;
const PPM_SCALE: u32 = 1_000_000;
const LEGACY_CANARY_THRESHOLD_PPM: u32 = 50_000;
const LEGACY_CANARY_COHORT_DOMAIN: &[u8] = b"hepta.retrieval.default-canary-cohort.v1";
const MAX_PROVIDER_REQUEST_TIMEOUT_MS: u64 = 800;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct BootstrapDescriptor {
    schema: String,
    owner_id: String,
    body_generation: u64,
    context_public_key_hex: String,
    frontier_public_key_hex: String,
    frontier_endpoint: SocketAddr,
    request_timeout_ms: u64,
    maximum_lease_ms: u64,
    publication_path: PathBuf,
    // Present null is invalid, not an omitted v2 field under v1.
    #[serde(default, deserialize_with = "present_value")]
    canary_threshold_ppm: Option<u32>,
    #[serde(default, deserialize_with = "present_value")]
    canary_cohort_salt_hex: Option<String>,
    #[serde(default, deserialize_with = "present_value")]
    shadow_maximum_channel_candidates: Option<u32>,
    #[serde(default, deserialize_with = "present_value")]
    shadow_maximum_nodes: Option<u32>,
    #[serde(default, deserialize_with = "present_value")]
    shadow_maximum_synapses: Option<u32>,
    #[serde(default, deserialize_with = "present_value")]
    shadow_maximum_settling_steps: Option<u8>,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct PublicationFile {
    schema: String,
    owner_id: String,
    body_generation: u64,
    sequence: u64,
    not_before_unix_ms: u64,
    expires_unix_ms: u64,
    context_json: String,
    signature_hex: String,
}
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
struct DeliverySettings {
    canary_policy_version: u8,
    canary_threshold_ppm: u32,
    canary_cohort_salt: Digest32,
    shadow_maximum_channel_candidates: u32,
    shadow_maximum_nodes: usize,
    shadow_maximum_synapses: usize,
    shadow_maximum_settling_steps: u8,
}
impl DeliverySettings {
    fn legacy_default() -> Self {
        Self {
            canary_policy_version: 1,
            canary_threshold_ppm: LEGACY_CANARY_THRESHOLD_PPM,
            canary_cohort_salt: Digest32::of_bytes(LEGACY_CANARY_COHORT_DOMAIN),
            shadow_maximum_channel_candidates: u32::try_from(MAX_GENERATION_BOUND_CANDIDATES)
                .unwrap_or(u32::MAX),
            shadow_maximum_nodes: MAX_ENGRAM_NODES,
            shadow_maximum_synapses: MAX_ENGRAM_SYNAPSES,
            shadow_maximum_settling_steps: MAX_ENGRAM_SETTLING_STEPS,
        }
    }
    fn from_descriptor(descriptor: &BootstrapDescriptor) -> Result<Self, String> {
        let has_v2_field = descriptor.canary_threshold_ppm.is_some()
            || descriptor.canary_cohort_salt_hex.is_some()
            || descriptor.shadow_maximum_channel_candidates.is_some()
            || descriptor.shadow_maximum_nodes.is_some()
            || descriptor.shadow_maximum_synapses.is_some()
            || descriptor.shadow_maximum_settling_steps.is_some();
        match descriptor.schema.as_str() {
            "hepta.agentd.retrieval-bootstrap.v1" => {
                if has_v2_field {
                    return Err(
                        "retrieval bootstrap v1 cannot carry rollout or shadow-budget fields"
                            .to_string(),
                    );
                }
                Ok(Self::legacy_default())
            }
            "hepta.agentd.retrieval-bootstrap.v2" => {
                let salt = descriptor
                    .canary_cohort_salt_hex
                    .as_deref()
                    .ok_or_else(|| {
                        "retrieval bootstrap v2 requires canary_cohort_salt_hex".to_string()
                    })?;
                // Use the same exact-width lowercase representation as keys.
                let canary_cohort_salt = Digest32::of_bytes(&hex_array::<32>(salt)?);
                // The salt is the supplied digest, not the hash of its bytes.
                let parsed_salt = salt
                    .parse::<Digest32>()
                    .map_err(|error| format!("invalid retrieval canary cohort salt: {error}"))?;
                let _ = canary_cohort_salt;
                let value = Self {
                    canary_policy_version: 2,
                    canary_threshold_ppm: descriptor.canary_threshold_ppm.ok_or_else(|| {
                        "retrieval bootstrap v2 requires canary_threshold_ppm".to_string()
                    })?,
                    canary_cohort_salt: parsed_salt,
                    shadow_maximum_channel_candidates: descriptor
                        .shadow_maximum_channel_candidates
                        .ok_or_else(|| {
                            "retrieval bootstrap v2 requires shadow_maximum_channel_candidates"
                                .to_string()
                        })?,
                    shadow_maximum_nodes: usize::try_from(
                        descriptor.shadow_maximum_nodes.ok_or_else(|| {
                            "retrieval bootstrap v2 requires shadow_maximum_nodes".to_string()
                        })?,
                    )
                    .map_err(|error| error.to_string())?,
                    shadow_maximum_synapses: usize::try_from(
                        descriptor.shadow_maximum_synapses.ok_or_else(|| {
                            "retrieval bootstrap v2 requires shadow_maximum_synapses".to_string()
                        })?,
                    )
                    .map_err(|error| error.to_string())?,
                    shadow_maximum_settling_steps: descriptor
                        .shadow_maximum_settling_steps
                        .ok_or_else(|| {
                            "retrieval bootstrap v2 requires shadow_maximum_settling_steps"
                                .to_string()
                        })?,
                };
                value.validate()?;
                Ok(value)
            }
            _ => Err("unsupported retrieval bootstrap descriptor schema".to_string()),
        }
    }
    fn validate(&self) -> Result<(), String> {
        if self.canary_threshold_ppm > PPM_SCALE {
            return Err("retrieval canary threshold exceeds one million ppm".to_string());
        }
        if self.canary_cohort_salt.is_zero() {
            return Err("retrieval canary cohort salt must be nonzero".to_string());
        }
        let maximum = u32::try_from(MAX_GENERATION_BOUND_CANDIDATES).unwrap_or(u32::MAX);
        if self.shadow_maximum_channel_candidates == 0
            || self.shadow_maximum_channel_candidates > maximum
        {
            return Err("retrieval shadow candidate budget is outside product bounds".to_string());
        }
        if self.shadow_maximum_nodes == 0 || self.shadow_maximum_nodes > MAX_ENGRAM_NODES {
            return Err("retrieval shadow node budget is outside product bounds".to_string());
        }
        if self.shadow_maximum_synapses == 0 || self.shadow_maximum_synapses > MAX_ENGRAM_SYNAPSES {
            return Err("retrieval shadow synapse budget is outside product bounds".to_string());
        }
        if self.shadow_maximum_settling_steps == 0
            || self.shadow_maximum_settling_steps > MAX_ENGRAM_SETTLING_STEPS
        {
            return Err(
                "retrieval shadow settling-step budget is outside product bounds".to_string(),
            );
        }
        Ok(())
    }
}
struct FilePublicationProvider {
    inner: LeasedMemoryRetrievalProviderV1,
    publication_path: PathBuf,
    delivery: DeliverySettings,
    parsed: PublicationCache<SignedMemoryRetrievalContextV1>,
}
pub(super) fn load(
    descriptor_path: &Path,
    expected_digest: Digest32,
    identity: &AgentdIdentity,
) -> Result<Arc<dyn CurrentMemoryRetrievalContext>, String> {
    if expected_digest.is_zero() {
        return Err("retrieval bootstrap requires a nonzero descriptor pin".to_string());
    }
    let descriptor_bytes = read_host_file(descriptor_path, MAX_DESCRIPTOR_BYTES)?;
    if Digest32::of_bytes(&descriptor_bytes) != expected_digest {
        return Err("retrieval bootstrap descriptor digest mismatch".to_string());
    }
    let descriptor: BootstrapDescriptor = serde_json::from_slice(&descriptor_bytes)
        .map_err(|error| format!("invalid retrieval bootstrap descriptor: {error}"))?;
    let delivery = DeliverySettings::from_descriptor(&descriptor)?;
    if descriptor.request_timeout_ms == 0
        || descriptor.request_timeout_ms > MAX_PROVIDER_REQUEST_TIMEOUT_MS
    {
        return Err(
            "retrieval frontier timeout must fit the 1..=800ms host delivery budget".to_string(),
        );
    }
    if descriptor.owner_id != identity.agent_id.as_str()
        || descriptor.body_generation != identity.spawn_generation
    {
        return Err("retrieval bootstrap owner/body mismatch".to_string());
    }
    if descriptor_path.starts_with(&identity.home_root)
        || descriptor.publication_path.starts_with(&identity.home_root)
    {
        return Err("retrieval bootstrap files must be outside the Agent home".to_string());
    }
    let inner = LeasedMemoryRetrievalProviderV1::from_loopback_frontier(
        identity.agent_id.clone(),
        identity.spawn_generation,
        hex_array(&descriptor.context_public_key_hex)?,
        hex_array(&descriptor.frontier_public_key_hex)?,
        descriptor.frontier_endpoint,
        Duration::from_millis(descriptor.request_timeout_ms),
        descriptor.maximum_lease_ms,
    )?;
    let provider: Arc<dyn CurrentMemoryRetrievalContext> = Arc::new(FilePublicationProvider {
        inner,
        publication_path: descriptor.publication_path,
        delivery,
        parsed: PublicationCache::new(),
    });
    provider.acquire_context(&identity.agent_id, identity.spawn_generation)?;
    Ok(provider)
}
impl CurrentMemoryRetrievalContext for FilePublicationProvider {
    fn acquire_context_before(
        &self,
        owner: &AgentId,
        body_generation: u64,
        deadline: std::time::Instant,
    ) -> Result<(RetrievalExecutionContextV1, Digest32, Option<u64>), String> {
        crate::cognitive_retrieval_context::check_retrieval_deadline(deadline)?;
        let bytes = read_host_file(&self.publication_path, MAX_PUBLICATION_BYTES)?;
        let publication = self
            .parsed
            .decode(&bytes, MAX_PUBLICATION_BYTES, decode_publication)?;
        self.inner
            .install_and_acquire_before(publication, owner, body_generation, deadline)
    }

    fn canary_policy_version(&self) -> u8 {
        self.delivery.canary_policy_version
    }
    fn canary_threshold_ppm(&self) -> u32 {
        self.delivery.canary_threshold_ppm
    }
    fn canary_cohort_salt(&self) -> Digest32 {
        self.delivery.canary_cohort_salt
    }
    fn shadow_maximum_channel_candidates(&self) -> u32 {
        self.delivery.shadow_maximum_channel_candidates
    }
    fn shadow_maximum_nodes(&self) -> usize {
        self.delivery.shadow_maximum_nodes
    }
    fn shadow_maximum_synapses(&self) -> usize {
        self.delivery.shadow_maximum_synapses
    }
    fn shadow_maximum_settling_steps(&self) -> u8 {
        self.delivery.shadow_maximum_settling_steps
    }
    fn current(
        &self,
        owner: &AgentId,
        body_generation: u64,
    ) -> Result<RetrievalExecutionContextV1, String> {
        self.acquire_context(owner, body_generation)
            .map(|(context, _, _)| context)
    }
    fn acquire_context(
        &self,
        owner: &AgentId,
        body_generation: u64,
    ) -> Result<(RetrievalExecutionContextV1, Digest32, Option<u64>), String> {
        let bytes = read_host_file(&self.publication_path, MAX_PUBLICATION_BYTES)?;
        let publication = self
            .parsed
            .decode(&bytes, MAX_PUBLICATION_BYTES, decode_publication)?;
        // Cache hits do not skip signature/lease validation or a fresh frontier
        // challenge. Changed or invalid bytes cannot reuse a previous payload.
        self.inner
            .install_and_acquire(publication, owner, body_generation)
    }
}
fn decode_publication(bytes: &[u8]) -> Result<SignedMemoryRetrievalContextV1, String> {
    if bytes.is_empty() || bytes.len() > MAX_PUBLICATION_BYTES {
        return Err("retrieval publication byte limit".to_string());
    }
    let wire: PublicationFile = serde_json::from_slice(bytes).map_err(|error| error.to_string())?;
    if wire.schema != "hepta.agentd.retrieval-publication-file.v1" {
        return Err("unsupported retrieval publication file schema".to_string());
    }
    let context = codec::decode(wire.context_json.as_bytes())?;
    ensure_bootstrap_supported_policy(&context.retrieval_policy)?;
    Ok(SignedMemoryRetrievalContextV1 {
        owner: AgentId::parse(wire.owner_id).map_err(|error| error.to_string())?,
        body_generation: wire.body_generation,
        sequence: wire.sequence,
        not_before_unix_ms: wire.not_before_unix_ms,
        expires_unix_ms: wire.expires_unix_ms,
        context,
        signature: hex_array(&wire.signature_hex)?,
    })
}

fn ensure_bootstrap_supported_policy(policy: &RetrievalPolicyV1) -> Result<(), String> {
    if policy
        .channel_weights
        .iter()
        .any(|row| row.channel == RetrievalChannelV1::Vector && row.weight > FixedQ32::ZERO)
    {
        return Err(
            "ordinary retrieval bootstrap cannot enable Vector without an authenticated generation-bound encoder/index owner"
                .to_string(),
        );
    }
    Ok(())
}

fn hex_array<const N: usize>(text: &str) -> Result<[u8; N], String> {
    if text.len() != 2 * N
        || !text
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
    {
        return Err("retrieval key/signature requires fixed-width lowercase hex".to_string());
    }
    let mut bytes = [0; N];
    for (index, byte) in bytes.iter_mut().enumerate() {
        *byte = u8::from_str_radix(&text[2 * index..2 * index + 2], 16)
            .map_err(|error| error.to_string())?;
    }
    Ok(bytes)
}
#[cfg(unix)]
fn read_host_file(path: &Path, maximum: usize) -> Result<Vec<u8>, String> {
    if !path.is_absolute() || path.canonicalize().map_err(|error| error.to_string())? != path {
        return Err(
            "retrieval host file must have an absolute canonical non-symlink path".to_string(),
        );
    }
    let parent = path
        .parent()
        .ok_or_else(|| "retrieval host file has no parent".to_string())?;
    use std::os::unix::fs::PermissionsExt;
    for ancestor in parent.ancestors() {
        let metadata = ancestor.metadata().map_err(|error| error.to_string())?;
        let mode = metadata.permissions().mode();
        if mode & 0o022 != 0 && (ancestor == parent || mode & 0o1000 == 0) {
            return Err("retrieval host path has an unprotected directory".to_string());
        }
    }
    let metadata = std::fs::symlink_metadata(path).map_err(|error| error.to_string())?;
    if !metadata.is_file() || metadata.len() > maximum as u64 {
        return Err("retrieval host file is not a bounded regular file".to_string());
    }
    let file = File::open(path).map_err(|error| error.to_string())?;
    let opened = file.metadata().map_err(|error| error.to_string())?;
    if !opened.is_file() || opened.len() > maximum as u64 {
        return Err("retrieval host file changed to an invalid file".to_string());
    }
    let mut bytes = Vec::new();
    file.take(maximum as u64 + 1)
        .read_to_end(&mut bytes)
        .map_err(|error| error.to_string())?;
    if bytes.is_empty() || bytes.len() > maximum {
        return Err("retrieval host file exceeded byte limit".to_string());
    }
    Ok(bytes)
}
#[cfg(not(unix))]
fn read_host_file(_path: &Path, _maximum: usize) -> Result<Vec<u8>, String> {
    Err("retrieval bootstrap requires a qualified Unix host".to_string())
}
#[cfg(test)]
mod delivery_policy_tests {
    use super::*;
    fn descriptor(schema: &str) -> BootstrapDescriptor {
        BootstrapDescriptor {
            schema: schema.to_string(),
            owner_id: "00000000-0000-4000-8000-000000000001".to_string(),
            body_generation: 1,
            context_public_key_hex: "00".repeat(32),
            frontier_public_key_hex: "11".repeat(32),
            frontier_endpoint: "127.0.0.1:1".parse().expect("endpoint"),
            request_timeout_ms: 100,
            maximum_lease_ms: 1_000,
            publication_path: PathBuf::from("/protected/retrieval.json"),
            canary_threshold_ppm: None,
            canary_cohort_salt_hex: None,
            shadow_maximum_channel_candidates: None,
            shadow_maximum_nodes: None,
            shadow_maximum_synapses: None,
            shadow_maximum_settling_steps: None,
        }
    }
    fn v2_descriptor() -> BootstrapDescriptor {
        let mut value = descriptor("hepta.agentd.retrieval-bootstrap.v2");
        value.canary_threshold_ppm = Some(125_000);
        value.canary_cohort_salt_hex = Some(Digest32::of_bytes(b"qualified-rollout").to_string());
        value.shadow_maximum_channel_candidates = Some(128);
        value.shadow_maximum_nodes = Some(512);
        value.shadow_maximum_synapses = Some(4_096);
        value.shadow_maximum_settling_steps = Some(2);
        value
    }
    #[test]
    fn v1_preserves_legacy_policy_and_rejects_v2_fields() {
        let descriptor = descriptor("hepta.agentd.retrieval-bootstrap.v1");
        assert_eq!(
            DeliverySettings::from_descriptor(&descriptor).expect("v1"),
            DeliverySettings::legacy_default()
        );
        let mut smuggled = descriptor;
        smuggled.canary_threshold_ppm = Some(1);
        assert!(DeliverySettings::from_descriptor(&smuggled).is_err());
    }
    #[test]
    fn v2_requires_complete_bounded_rollout_policy() {
        let descriptor = v2_descriptor();
        let policy = DeliverySettings::from_descriptor(&descriptor).expect("v2");
        assert_eq!(policy.canary_policy_version, 2);
        assert_eq!(policy.canary_threshold_ppm, 125_000);
        assert_eq!(policy.shadow_maximum_nodes, 512);
        let mut missing = v2_descriptor();
        missing.canary_cohort_salt_hex = None;
        assert!(DeliverySettings::from_descriptor(&missing).is_err());
        let mut excessive = v2_descriptor();
        excessive.canary_threshold_ppm = Some(PPM_SCALE + 1);
        assert!(DeliverySettings::from_descriptor(&excessive).is_err());
        let mut zero = v2_descriptor();
        zero.shadow_maximum_nodes = Some(0);
        assert!(DeliverySettings::from_descriptor(&zero).is_err());
    }
    #[test]
    fn explicit_null_is_not_an_absent_v2_field() {
        let common = r#""schema":"hepta.agentd.retrieval-bootstrap.v1","owner_id":"x","body_generation":1,"context_public_key_hex":"x","frontier_public_key_hex":"x","frontier_endpoint":"127.0.0.1:1","request_timeout_ms":100,"maximum_lease_ms":1000,"publication_path":"/protected/context""#;
        for field in [
            "canary_threshold_ppm",
            "canary_cohort_salt_hex",
            "shadow_maximum_channel_candidates",
            "shadow_maximum_nodes",
            "shadow_maximum_synapses",
            "shadow_maximum_settling_steps",
        ] {
            let wire = format!("{{{common},\"{field}\":null}}");
            assert!(
                serde_json::from_str::<BootstrapDescriptor>(&wire).is_err(),
                "{field}"
            );
        }
    }
}
#[cfg(test)]
#[path = "cognitive_retrieval_bootstrap_tests.rs"]
mod tests;
