//! Exclusive candidate handoff without holding a mutex across external code.
//!
//! An empty slot means either an in-flight operation or a permanently closed
//! candidate. Concurrent callers fail closed instead of waiting inside owner
//! callbacks. Only the successful holder can restore the same candidate.

use std::sync::Mutex;

pub(super) fn with_exclusive_candidate<T, R>(
    cache: &Mutex<Option<T>>,
    consume: impl FnOnce(&mut T) -> Result<R, String>,
) -> Result<R, String> {
    let mut candidate = {
        let mut slot = cache
            .lock()
            .map_err(|_| "ranker lock poisoned".to_string())?;
        slot.take().ok_or_else(|| {
            "ranker unavailable; operation in flight or explicit reload required".to_string()
        })?
    };

    // No lock guard survives this boundary. An error or an unwind drops the
    // detached candidate and leaves the slot closed; there is no Drop-based
    // restoration that could accidentally resurrect unvalidated state.
    let result = consume(&mut candidate)?;

    let mut slot = cache
        .lock()
        .map_err(|_| "ranker lock poisoned".to_string())?;
    if slot.is_some() {
        // The private owner never writes while a candidate is detached. Keep
        // a future violating implementation from silently replacing state.
        *slot = None;
        return Err("ranker candidate ownership conflict; explicit reload required".to_string());
    }
    *slot = Some(candidate);
    Ok(result)
}

#[cfg(test)]
#[path = "cognitive_ranker_cache_tests.rs"]
mod tests;
