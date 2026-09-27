//! Host-only adapter from a canonical exact-ID read to native planning.
//!
//! There is no caller-supplied item count or separately supplied serialized
//! payload. The adapter verifies the returned records against the exact response
//! and computes both the count and canonical bytes itself. Planner time uses an
//! explicit request-local monotonic origin; owner-store Unix timestamps retain
//! their separate authority semantics.

use std::collections::BTreeMap;
use std::time::Duration;
use std::time::Instant;

use codex_hepta_cognitive_read::ReadIdsResultV1;
use codex_hepta_contracts::AgentId;
use codex_hepta_control_plane::ObservedContextPlanV1;
use codex_hepta_control_plane::ObservedContextV1;
use codex_hepta_control_plane::plan_observed_context;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use crate::CognitiveContextSnapshot;

const LEASE: Duration = Duration::from_secs(1);

pub(super) fn plan_authenticated_context(
    owner: &AgentId,
    generation: u64,
    read: &ReadIdsResultV1,
    bound_read_digest: Digest32,
    response: &CognitiveContextSnapshot,
    request_origin: Instant,
    maximum_context_bytes: usize,
) -> Result<ObservedContextPlanV1, String> {
    if response.plan.is_some()
        || response.items.len() > 4
        || maximum_context_bytes > 24 * 1024
        || read.snapshot_digest().to_string() != response.snapshot_digest
        || bound_read_digest.to_string() != response.read_digest
        || !read.missing_ids().is_empty()
        || read.records().len() != response.items.len()
    {
        return Err("context does not match the canonical selected read".to_string());
    }
    let mut records = read.records().iter()
        .map(|record| (record.record_id.as_str(), record))
        .collect::<BTreeMap<_, _>>();
    if records.len() != read.records().len() {
        return Err("canonical selected read contains duplicate identities".to_string());
    }
    for item in &response.items {
        let record = records.remove(item.memory_id.as_str())
            .ok_or_else(|| "context item is not uniquely attested by the selected read".to_string())?;
        let content = Digest32::of_bytes(item.content.as_bytes());
        if !record.is_live()
            || record.revision.get() != item.revision
            || record.content_digest != Some(content)
            || item.content_sha256 != content.to_string()
        {
            return Err("context content or revision differs from the canonical read".to_string());
        }
    }
    if !records.is_empty() {
        return Err("canonical read has undelivered record identities".to_string());
    }
    let bytes = serde_json::to_vec(response).map_err(|error| error.to_string())?;
    let now = Instant::now().checked_duration_since(request_origin)
        .ok_or_else(|| "monotonic context clock regressed".to_string())?;
    if now >= LEASE {
        return Err("canonical context read exceeded its monotonic lease".to_string());
    }
    let now_micros = u64::try_from(now.as_micros()).map_err(|error| error.to_string())?;
    let expiry = u64::try_from(LEASE.as_micros()).map_err(|error| error.to_string())?;
    let count = u32::try_from(read.records().len()).map_err(|error| error.to_string())?;
    plan_observed_context(ObservedContextV1 {
        owner_id: StableId::new(owner.as_str()).map_err(|error| error.to_string())?,
        body_generation: Generation::new(generation).map_err(|error| error.to_string())?,
        source_snapshot_digest: read.snapshot_digest(),
        read_digest: bound_read_digest,
        verified_item_count: count,
        encoded_context: &bytes,
        maximum_context_bytes: u32::try_from(maximum_context_bytes).map_err(|error| error.to_string())?,
        observed_at_micros: now_micros,
        expires_at_micros: expiry,
    }).map_err(|error| error.to_string())
}
