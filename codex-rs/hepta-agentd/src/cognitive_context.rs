//! Connect the canonical SQLite owner to the newer bounded cognitive read port.

use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_cognitive_read::ReadRequest;
use codex_hepta_cognitive_read::ReadRequestV2;
use codex_hepta_contracts::AgentId;
use codex_hepta_memory::CognitiveAccess;
use codex_hepta_memory::CognitiveScope;
use codex_hepta_memory::CognitiveStore;
use codex_hepta_memory::CognitiveStoreError;
use codex_hepta_memory::RetrievalRequest;

use crate::CognitiveContextItem;
use crate::CognitiveContextSnapshot;

const MAX_CONTEXT_JSON_BYTES: usize = 24 * 1024;

pub(crate) async fn read(
    store: &CognitiveStore,
    owner: &AgentId,
    query: &str,
    limit: u16,
) -> Result<CognitiveContextSnapshot, CognitiveStoreError> {
    if query.is_empty() || query.len() > 2048 || !(1..=4).contains(&limit) {
        return Err(CognitiveStoreError::Invalid(
            "context requires a 1..2048 byte query and a 1..4 result limit".to_string(),
        ));
    }
    let access = CognitiveAccess::agent_private(owner.clone());
    let scope = CognitiveScope::AgentPrivate;
    let cut = store
        .lane_c_snapshot(&access, &scope, now_seconds()?)
        .await?;
    let read = cut
        .read(ReadRequestV2 {
            read_request: ReadRequest {
                snapshot_digest: cut.snapshot().snapshot_digest,
                allowed_kinds: Vec::new(),
                maximum_results: 1024,
                include_tombstones: false,
            },
            maximum_encoded_bytes: 1024 * 1024,
        })
        .map_err(|error| CognitiveStoreError::Corrupt(error.to_string()))?;
    let candidates = store
        .retrieve_memory_candidates(&access, &RetrievalRequest::new(query, now_seconds()?))
        .await?;
    let mut response = CognitiveContextSnapshot {
        snapshot_digest: read.snapshot_digest().to_string(),
        read_digest: read.receipt_digest().to_string(),
        omitted_records: read.omitted_count() as u64,
        items: Vec::new(),
    };
    for candidate in candidates.candidates {
        let memory = candidate.memory;
        // The legacy search ranks candidates; the new owner cut admits only
        // the exact verified revision and content bound by the read port.
        let accepted = read.records().iter().any(|record| {
            record.record_id.as_str() == memory.id.memory_id.as_str()
                && record.revision.get() == memory.id.revision
                && record.content_digest.to_string() == memory.content_sha256.as_str()
                && memory.scope == scope
        });
        if !accepted {
            continue;
        }
        let item = CognitiveContextItem {
            memory_id: memory.id.memory_id.as_str().to_string(),
            revision: memory.id.revision,
            content: memory.content,
            content_sha256: memory.content_sha256.as_str().to_string(),
        };
        response.items.push(item);
        // Bound the complete payload, including JSON escaping and envelope.
        let encoded_bytes = serde_json::to_vec(&response)
            .map_err(|error| CognitiveStoreError::Invalid(error.to_string()))?
            .len();
        if encoded_bytes > MAX_CONTEXT_JSON_BYTES {
            response.items.pop();
            continue;
        }
        if response.items.len() == usize::from(limit) {
            break;
        }
    }
    // A concurrent correction, deletion, changed citation, expiry or restored
    // older database must not leak a stale projection into the response.
    store
        .revalidate_lane_c_snapshot(&access, &scope, &cut, now_seconds()?)
        .await?;
    Ok(response)
}

fn now_seconds() -> Result<i64, CognitiveStoreError> {
    let seconds = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|error| CognitiveStoreError::Unavailable(error.to_string()))?
        .as_secs();
    i64::try_from(seconds).map_err(|error| CognitiveStoreError::Unavailable(error.to_string()))
}

#[cfg(test)]
#[path = "cognitive_context_tests.rs"]
mod tests;
