//! Admit bounded metadata before decoding records or reading payload extents.

use super::DurableRegistryError;
use super::STORE_SCHEMA;
use super::StoredV2;
use codex_hepta_types::Revision;

pub(super) fn metadata_bounds(
    stored: &StoredV2,
    maximum_records: usize,
) -> Result<Revision, DurableRegistryError> {
    if stored.schema != STORE_SCHEMA || stored.maximum_records == 0 || maximum_records == 0 {
        return Err(DurableRegistryError::Corrupt);
    }
    let revision = Revision::new(stored.revision).map_err(|_| DurableRegistryError::Corrupt)?;
    let configured_maximum = maximum_records.min(crate::MAX_RECORDS);
    if stored.maximum_records != configured_maximum {
        return Err(DurableRegistryError::ConfigurationMismatch);
    }
    if stored
        .factors
        .len()
        .saturating_add(stored.realizations.len())
        > configured_maximum
    {
        return Err(DurableRegistryError::CapacityExceeded);
    }
    if stored.bindings.len() > stored.realizations.len()
        || stored.payloads.len() > stored.realizations.len()
        || stored.supersessions.len() > stored.realizations.len()
        || stored.lifecycle_events.len() > stored.factors.len().saturating_mul(4)
    {
        return Err(DurableRegistryError::Corrupt);
    }
    Ok(revision)
}
