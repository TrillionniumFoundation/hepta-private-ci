//! Exact lifecycle equivalence at the canonical/durable receipt bridge.

use codex_hepta_cognitive_types::hnmf::MemoryLifecycleV1;
use codex_hepta_types::Digest32;

use crate::durable::MemoryLifecycleState;

use super::CognitiveStoreV2Error;

pub(super) fn validate_lifecycle_binding(
    durable: &MemoryLifecycleState,
    canonical: &MemoryLifecycleV1,
) -> Result<(), CognitiveStoreV2Error> {
    // The durable forget writer binds source.content to reason.as_bytes().
    // Match that exact UTF-8 SHA-256 encoding rather than only the enum tag.
    let matches = match (durable, canonical) {
        (MemoryLifecycleState::Active, MemoryLifecycleV1::Active) => true,
        (
            MemoryLifecycleState::Tombstoned { reason },
            MemoryLifecycleV1::Tombstoned { reason_sha256 },
        ) => reason_sha256.digest() == Digest32::of_bytes(reason.as_bytes()),
        (MemoryLifecycleState::Active, MemoryLifecycleV1::Superseded { .. })
        | (MemoryLifecycleState::Active, MemoryLifecycleV1::Tombstoned { .. })
        | (MemoryLifecycleState::Tombstoned { .. }, MemoryLifecycleV1::Active)
        | (MemoryLifecycleState::Tombstoned { .. }, MemoryLifecycleV1::Superseded { .. }) => false,
    };
    if !matches {
        return Err(CognitiveStoreV2Error::CanonicalDurableStateMismatch);
    }
    Ok(())
}

#[cfg(test)]
#[path = "canonical_lifecycle_tests.rs"]
mod tests;
