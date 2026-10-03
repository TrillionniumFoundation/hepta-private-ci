//! Publication time is sampled by the store after writer admission. It is a
//! fallible host wall clock, not independent time attestation or rollback proof.

use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use crate::EvidenceError;
use crate::HeptaEvidenceStore;

pub(crate) fn now_millis(store: &HeptaEvidenceStore) -> Result<u64, EvidenceError> {
    #[cfg(test)]
    if let Some(clock) = &store.publication_test_time_ms {
        return validate_millis(u128::from(clock.load(std::sync::atomic::Ordering::SeqCst)));
    }
    #[cfg(not(test))]
    let _ = store;
    let millis = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|error| EvidenceError::Unavailable(format!("publication clock: {error}")))?
        .as_millis();
    validate_millis(millis)
}

fn validate_millis(millis: u128) -> Result<u64, EvidenceError> {
    let millis = i64::try_from(millis)
        .ok()
        .filter(|millis| *millis > 0)
        .ok_or_else(|| {
            EvidenceError::Unavailable(
                "publication clock is outside its supported range".to_string(),
            )
        })?;
    Ok(millis as u64)
}

pub(crate) fn require_time_floor(now: u64, persisted: u64) -> Result<(), EvidenceError> {
    if now < persisted {
        return Err(EvidenceError::Unavailable(
            "publication clock regressed behind persisted publication time".to_string(),
        ));
    }
    Ok(())
}
