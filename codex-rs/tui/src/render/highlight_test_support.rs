//! Excludes concurrent theme writes during synchronous rendering assertions.

use std::sync::Mutex;
use std::sync::MutexGuard;

static THEME_MUTATION_LOCK: Mutex<()> = Mutex::new(());

/// Keep the current theme and its revision stable across a rendering comparison.
///
/// The test-only branch of `set_syntax_theme` takes this same lock before the
/// theme write lock. Do not call that setter or await while holding this guard:
/// this mutex is not reentrant. The guard does not retain a theme read lock, so
/// the renderer can take its ordinary read locks without recursive locking.
pub(crate) fn lock_theme_for_test() -> MutexGuard<'static, ()> {
    let guard = match THEME_MUTATION_LOCK.lock() {
        Ok(guard) => guard,
        // Only the exclusion token is poisoned; no theme value is stored here.
        Err(poisoned) => poisoned.into_inner(),
    };
    // Initialize once before the protected interval, without holding a read lock.
    let _ = super::theme_lock();
    guard
}
