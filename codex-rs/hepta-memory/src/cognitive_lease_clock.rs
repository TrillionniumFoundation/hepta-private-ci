//! Per-owner time for local lease checks; persisted audit timestamps stay real.

use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use super::CognitiveStore;

#[cfg(any(test, feature = "qualification-lease-clock"))]
use std::sync::Arc;
#[cfg(any(test, feature = "qualification-lease-clock"))]
use std::sync::Weak;
#[cfg(any(test, feature = "qualification-lease-clock"))]
use std::sync::atomic::AtomicU64;
#[cfg(any(test, feature = "qualification-lease-clock"))]
use std::sync::atomic::Ordering;

#[derive(Clone, Default)]
pub(super) enum LocalLeaseClock {
    #[default]
    Real,
    #[cfg(any(test, feature = "qualification-lease-clock"))]
    Qualification(Arc<AtomicU64>),
}

impl CognitiveStore {
    pub(crate) fn local_lease_now_unix_i64(&self) -> Result<i64, String> {
        i64::try_from(self.local_lease_now_unix_seconds()?)
            .map_err(|_| "timestamp overflow".to_string())
    }

    pub(crate) fn local_lease_now_unix_seconds(&self) -> Result<u64, String> {
        match &self.local_lease_clock {
            LocalLeaseClock::Real => SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .map(|duration| duration.as_secs())
                .map_err(|error| error.to_string()),
            #[cfg(any(test, feature = "qualification-lease-clock"))]
            LocalLeaseClock::Qualification(now) => Ok(now.load(Ordering::Acquire)),
        }
    }
}

/// Advances only the fresh qualification owner's lease checks. It cannot
/// replace an existing owner's clock, move backwards, or retain the owner.
#[cfg(any(test, feature = "qualification-lease-clock"))]
pub struct QualificationLeaseClock {
    now: Weak<AtomicU64>,
}

#[cfg(any(test, feature = "qualification-lease-clock"))]
impl QualificationLeaseClock {
    pub fn now_unix_seconds(&self) -> Result<u64, super::CognitiveStoreError> {
        Ok(self.owner_clock()?.load(Ordering::Acquire))
    }

    pub fn advance_to(&self, target: u64) -> Result<(), super::CognitiveStoreError> {
        if i64::try_from(target).is_err() {
            return Err(super::CognitiveStoreError::Invalid(
                "qualification lease time overflows SQLite INTEGER".to_string(),
            ));
        }
        self.owner_clock()?
            .fetch_update(Ordering::AcqRel, Ordering::Acquire, |current| {
                (target >= current).then_some(target)
            })
            .map(|_| ())
            .map_err(|_| {
                super::CognitiveStoreError::Invalid(
                    "qualification lease time cannot move backwards".to_string(),
                )
            })
    }

    fn owner_clock(&self) -> Result<Arc<AtomicU64>, super::CognitiveStoreError> {
        self.now.upgrade().ok_or_else(|| {
            super::CognitiveStoreError::Unavailable(
                "qualification clock owner has been dropped".to_string(),
            )
        })
    }
}

#[cfg(any(test, feature = "qualification-lease-clock"))]
impl CognitiveStore {
    /// Create an empty qualification owner under the original exclusive store
    /// fence. Existing databases, recovery pointers and live owners are refused.
    /// Ordinary open, recovery and read-only construction always use real time.
    pub async fn open_new_with_qualification_lease_clock(
        layout: &codex_hepta_paths::HeptaAgentLayout,
    ) -> Result<(Self, QualificationLeaseClock), super::CognitiveStoreError> {
        let root = super::create_private_directory(layout.cognitive_root())?;
        let guard = super::CognitiveStoreOpenGuard::acquire_exclusive(&root)?;
        for entry in std::fs::read_dir(&root).map_err(super::unavailable)? {
            if entry.map_err(super::unavailable)?.file_name()
                != std::ffi::OsStr::new(super::COGNITIVE_STORE_LOCK_FILENAME)
            {
                return Err(super::CognitiveStoreError::Invalid(
                    "qualification clock requires a new empty cognitive store".to_string(),
                ));
            }
        }
        let mut store = Self::open_guarded(layout, root, Arc::new(guard)).await?;
        let initial = store
            .local_lease_now_unix_seconds()
            .map_err(super::CognitiveStoreError::Unavailable)?;
        i64::try_from(initial).map_err(super::unavailable)?;
        let now = Arc::new(AtomicU64::new(initial));
        let control = QualificationLeaseClock {
            now: Arc::downgrade(&now),
        };
        // Bind before any store, clone, lease or executor escapes this constructor.
        store.local_lease_clock = LocalLeaseClock::Qualification(now);
        Ok((store, control))
    }
}

#[cfg(test)]
#[path = "cognitive_lease_clock_tests.rs"]
mod tests;
