//! Ordinary-process composition from an explicitly pinned host descriptor.
//! No key generation, local-frontier substitute, authority or default rollout.

#[cfg(unix)]
use std::fs::File;
#[cfg(unix)]
use std::io::Read;
use std::net::SocketAddr;
use std::path::Path;
use std::path::PathBuf;
use std::sync::Arc;
use std::time::Duration;

use codex_hepta_contracts::AgentId;
use codex_hepta_memory::RetrievalExecutionContextV1;
use codex_hepta_types::Digest32;
use serde::Deserialize;

use super::LeasedMemoryRetrievalProviderV1;
use super::SignedMemoryRetrievalContextV1;
use crate::AgentdIdentity;
use crate::CurrentMemoryRetrievalContext;

#[path = "cognitive_retrieval_context_codec.rs"]
mod codec;

const MAX_DESCRIPTOR_BYTES: usize = 16 * 1024;
// JSON string escaping may expand context_json. Both envelope and decoded
// context have independent bounds; neither limit is inferred from file size.
const MAX_PUBLICATION_BYTES: usize = 2 * codec::MAX_CONTEXT_BYTES;

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
    // Keep nested JSON as original text. Parsing it into Value here would
    // silently discard duplicate keys before the strict context decoder runs.
    context_json: String,
    signature_hex: String,
}

struct FilePublicationProvider {
    inner: LeasedMemoryRetrievalProviderV1,
    publication_path: PathBuf,
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
    if descriptor.schema != "hepta.agentd.retrieval-bootstrap.v1"
        || descriptor.owner_id != identity.agent_id.as_str()
        || descriptor.body_generation != identity.spawn_generation
    {
        return Err("retrieval bootstrap schema/owner/body mismatch".to_string());
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
    });
    // Startup is a real signature + fresh challenged-owner observation, not
    // merely a successful configuration parse. Any failure rejects startup.
    provider.acquire_context(&identity.agent_id, identity.spawn_generation)?;
    Ok(provider)
}

impl CurrentMemoryRetrievalContext for FilePublicationProvider {
    fn current(
        &self,
        owner: &AgentId,
        body_generation: u64,
    ) -> Result<RetrievalExecutionContextV1, String> {
        self.acquire_context(owner, body_generation).map(|(context, _, _)| context)
    }

    fn acquire_context(
        &self,
        owner: &AgentId,
        body_generation: u64,
    ) -> Result<(RetrievalExecutionContextV1, Digest32, Option<u64>), String> {
        let bytes = read_host_file(&self.publication_path, MAX_PUBLICATION_BYTES)?;
        let publication = decode_publication(&bytes)?;
        if &publication.owner != owner || publication.body_generation != body_generation {
            return Err("retrieval publication requested for another owner/body".to_string());
        }
        // Re-install is idempotent and cannot extend the monotonic lease.
        // A rotation requires both a signed publication and the independently
        // current signed frontier. No cached-context fallback on any error.
        self.inner.install(publication)?;
        self.inner.acquire_context(owner, body_generation)
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
    Ok(SignedMemoryRetrievalContextV1 {
        owner: AgentId::parse(wire.owner_id).map_err(|error| error.to_string())?,
        body_generation: wire.body_generation,
        sequence: wire.sequence,
        not_before_unix_ms: wire.not_before_unix_ms,
        expires_unix_ms: wire.expires_unix_ms,
        context: codec::decode(wire.context_json.as_bytes())?,
        signature: hex_array(&wire.signature_hex)?,
    })
}

fn hex_array<const N: usize>(text: &str) -> Result<[u8; N], String> {
    if text.len() != 2 * N || !text.bytes().all(|byte| {
        byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte)
    }) {
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
    // The host publisher owns these directories. It must publish regular files
    // atomically; this is not a general-purpose reader for agent-chosen paths.
    if !path.is_absolute() || path.canonicalize().map_err(|error| error.to_string())? != path {
        return Err("retrieval host file must have an absolute canonical non-symlink path".to_string());
    }
    let parent = path.parent().ok_or_else(|| "retrieval host file has no parent".to_string())?;
    use std::os::unix::fs::PermissionsExt;
    for ancestor in parent.ancestors() {
        let metadata = ancestor.metadata().map_err(|error| error.to_string())?;
        let mode = metadata.permissions().mode();
        // Sticky shared ancestors (e.g. /tmp) may contain a private directory,
        // but the immediate publication directory must not itself be shared.
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
    file.take(maximum as u64 + 1).read_to_end(&mut bytes)
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
#[path = "cognitive_retrieval_bootstrap_tests.rs"]
mod tests;
