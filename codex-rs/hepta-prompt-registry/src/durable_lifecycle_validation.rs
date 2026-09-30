//! Reject lifecycle images that could not have been emitted by a registry owner.
//!
//! Checksums detect changed bytes; replay and these event shapes independently
//! enforce historical review and migration invariants after decoding.

use super::DurableRegistryError;
use super::MIGRATION_REASON_DOMAIN;
use crate::FactorSource;
use crate::Lifecycle;
use crate::LifecycleEvent;
use crate::LifecycleEventKind;
use crate::PromptFactor;
use codex_hepta_types::Digest32;

pub(super) fn validate_event(
    event: &LifecycleEvent,
    factor: &PromptFactor,
) -> Result<(), DurableRegistryError> {
    let valid = match event.kind {
        LifecycleEventKind::Registered => {
            event.actor_id == factor.proposer_id
                && event.evidence_digest == factor.content_digest
                && event.admission_grant_id.is_none()
                && event.scope_digest.is_none()
                && event.reason_digest.is_none()
                && event.cutoff_unix_ms.is_none()
        }
        LifecycleEventKind::Imported => {
            event.actor_id.as_str() == "migration:v1"
                && event.evidence_digest == factor.content_digest
                && event.admission_grant_id.is_none()
                && event.scope_digest.is_none()
                && event.reason_digest == Some(Digest32::of_bytes(MIGRATION_REASON_DOMAIN))
                && event.cutoff_unix_ms.is_none()
                && (factor.source == FactorSource::GovernedInternal
                    || matches!(event.to, Lifecycle::Draft | Lifecycle::Revoked))
        }
        LifecycleEventKind::Admitted => {
            factor.source == FactorSource::GovernedInternal
                && event.actor_id != factor.proposer_id
                && !event.evidence_digest.is_zero()
                && event.admission_grant_id.is_some() == event.scope_digest.is_some()
                && !event.scope_digest.is_some_and(Digest32::is_zero)
                && event.reason_digest.is_none()
                && event.cutoff_unix_ms.is_none()
        }
        LifecycleEventKind::Retired => {
            event.evidence_digest == factor.content_digest
                && event.admission_grant_id.is_none()
                && event.scope_digest.is_none()
                && !event.reason_digest.is_some_and(Digest32::is_zero)
                && event.cutoff_unix_ms.is_none()
        }
        LifecycleEventKind::Revoked => {
            event.evidence_digest == factor.content_digest
                && event.admission_grant_id.is_none()
                && event.scope_digest.is_none()
                && event.reason_digest.is_some() == event.cutoff_unix_ms.is_some()
                && !event.reason_digest.is_some_and(Digest32::is_zero)
                && event.cutoff_unix_ms != Some(0)
        }
    };
    if !valid {
        return Err(DurableRegistryError::Corrupt);
    }
    Ok(())
}
