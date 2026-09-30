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
mod tests {
    use super::*;
    use std::panic::AssertUnwindSafe;
    use std::panic::catch_unwind;
    use std::sync::Arc;
    use std::sync::mpsc;
    use std::thread;
    use std::time::Duration;

    #[test]
    fn callback_runs_outside_lock_and_restores_exact_candidate() {
        let cache = Mutex::new(Some(7_u64));
        let result = with_exclusive_candidate(&cache, |candidate| {
            let slot = cache.try_lock().expect("callback must not hold cache lock");
            assert!(slot.is_none());
            *candidate += 1;
            Ok(*candidate)
        });
        assert_eq!(result, Ok(8));
        assert_eq!(*cache.lock().unwrap(), Some(8));
    }

    #[test]
    fn concurrent_call_rejects_without_entering_callback_or_blocking_owner() {
        let cache = Arc::new(Mutex::new(Some(7_u64)));
        let (entered_tx, entered_rx) = mpsc::channel();
        let (release_tx, release_rx) = mpsc::channel();
        let worker_cache = Arc::clone(&cache);
        let worker = thread::spawn(move || {
            with_exclusive_candidate(&worker_cache, |candidate| {
                entered_tx.send(()).unwrap();
                release_rx.recv_timeout(Duration::from_secs(5)).unwrap();
                *candidate += 1;
                Ok(())
            })
        });
        entered_rx.recv_timeout(Duration::from_secs(5)).unwrap();
        let (result_tx, result_rx) = mpsc::channel();
        let contender_cache = Arc::clone(&cache);
        let contender = thread::spawn(move || {
            let result: Result<(), String> = with_exclusive_candidate(&contender_cache, |_| {
                panic!("a concurrent callback must never be entered")
            });
            result_tx.send(result).unwrap();
        });
        // Release the owner even when the timeout assertion below fails, so
        // a regressed implementation cannot strand a blocked test thread.
        let concurrent = result_rx.recv_timeout(Duration::from_secs(2));
        release_tx.send(()).unwrap();
        assert!(
            concurrent
                .expect("contender must fail without waiting")
                .is_err()
        );
        contender.join().unwrap();
        assert_eq!(worker.join().unwrap(), Ok(()));
        assert_eq!(*cache.lock().unwrap(), Some(8));
    }

    #[test]
    fn witness_failure_is_terminal_until_explicit_owner_reload() {
        let cache = Mutex::new(Some(7_u64));
        let failed: Result<(), String> =
            with_exclusive_candidate(&cache, |_| Err("witness revoked".to_string()));
        assert_eq!(failed, Err("witness revoked".to_string()));
        assert!(cache.lock().unwrap().is_none());
        assert!(with_exclusive_candidate(&cache, |_| Ok(())).is_err());
    }

    #[test]
    fn panic_drops_candidate_without_poisoning_mutex_or_resurrection() {
        let cache = Mutex::new(Some(7_u64));
        let panic = catch_unwind(AssertUnwindSafe(|| {
            let _: Result<(), String> =
                with_exclusive_candidate(&cache, |_| panic!("simulated registry-provider panic"));
        }));
        assert!(panic.is_err());
        assert!(!cache.is_poisoned());
        assert!(cache.lock().unwrap().is_none());
        assert!(with_exclusive_candidate(&cache, |_| Ok(())).is_err());
    }

    #[test]
    fn unexpected_slot_replacement_closes_both_candidates() {
        let cache = Mutex::new(Some(7_u64));
        let result = with_exclusive_candidate(&cache, |_| {
            *cache.lock().unwrap() = Some(99);
            Ok(())
        });
        assert!(result.is_err());
        assert!(cache.lock().unwrap().is_none());
    }
}
