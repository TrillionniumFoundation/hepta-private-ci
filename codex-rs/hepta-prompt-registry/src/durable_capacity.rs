//! Preserve metadata headroom for retiring/revoking every accepted live factor.
//! This is logical capacity admission, not a promise against physical ENOSPC.
use super::DurableRegistryError;
use crate::Lifecycle;
use crate::PromptRegistry;

// StableIds are ASCII and <=128 bytes. A native retirement/revocation event has
// two IDs, at most three 32-byte digest arrays, bounded u64 fields and fixed JSON
// keys. 2 KiB bounds the entire event, including its array separator.
const TERMINAL_EVENT_BYTES: u64 = 2048;
const GLOBAL_COUNTER_AND_DIGEST_GROWTH: u64 = 128;

pub(super) fn reserved_bytes(registry: &PromptRegistry) -> u64 {
    let events: u64 = registry
        .factors
        .values()
        .map(|factor| match factor.lifecycle {
            Lifecycle::Admitted => 2,
            Lifecycle::Draft | Lifecycle::Retired => 1,
            Lifecycle::Revoked => 0,
        })
        .sum();
    // JSON true -> false grows by one byte for each disabled realization.
    let active = registry
        .realizations
        .values()
        .filter(|value| value.active)
        .count() as u64;
    events
        .saturating_mul(TERMINAL_EVENT_BYTES)
        .saturating_add(active)
        .saturating_add(GLOBAL_COUNTER_AND_DIGEST_GROWTH)
}

pub(super) fn admit(
    registry: &PromptRegistry,
    bytes: usize,
    limit: u64,
) -> Result<(), DurableRegistryError> {
    if (bytes as u64)
        .checked_add(reserved_bytes(registry))
        .is_none_or(|total| total > limit)
    {
        return Err(DurableRegistryError::CapacityExceeded);
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::TestMust;
    #[test]
    fn worst_native_terminal_event_fits_reserved_slot() {
        let event = super::super::StoredLifecycleEvent {
            revision: u64::MAX,
            factor_id: "f".repeat(128),
            kind: 3,
            from: Some(2),
            to: 3,
            actor_id: "a".repeat(128),
            admission_grant_id: None,
            evidence_digest: [255; 32],
            scope_digest: None,
            reason_digest: Some([255; 32]),
            cutoff_unix_ms: Some(u64::MAX),
            event_digest: [255; 32],
        };
        assert!(serde_json::to_vec(&event).must("event").len() as u64 + 1 < TERMINAL_EVENT_BYTES);
    }
}
