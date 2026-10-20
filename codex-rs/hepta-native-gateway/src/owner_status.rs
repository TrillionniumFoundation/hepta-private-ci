//! Token-free, point-in-time observation. Host/Origin checks are not authentication.
//! A timed-out async inspection retains its single-flight permit until it ends.

use std::fmt;
use std::future::Future;
use std::pin::Pin;
use std::sync::Arc;
use std::sync::Weak;
use std::time::Duration;

use serde::Serialize;
use tokio::sync::Semaphore;

const OBSERVATION_TIMEOUT: Duration = Duration::from_secs(2);

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum OwnerLeaseDisposition {
    Missing,
    Active,
    ExpiredActive,
    Released,
    RolledBack,
}

/// Metadata only. This is neither a fencing token nor permission to write.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct OwnerLeaseObservation {
    pub generation: Option<u64>,
    pub disposition: OwnerLeaseDisposition,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum OwnerReadFailure {
    ReadFailed,
    IntegrityRejected,
    InvalidObservation,
    Busy,
    TimedOut,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize)]
#[serde(tag = "status", rename_all = "snake_case")]
enum Observation {
    NotAttached,
    Observed {
        generation: Option<u64>,
        disposition: OwnerLeaseDisposition,
    },
    Unavailable {
        reason: OwnerReadFailure,
    },
}

/// Future returned by a higher-level, read-only owner mapping on its existing runtime.
pub type OwnerObservationFuture<'a> =
    Pin<Box<dyn Future<Output = Result<OwnerLeaseObservation, OwnerReadFailure>> + Send + 'a>>;
type ObservationFuture = Pin<Box<dyn Future<Output = Observation> + Send>>;

/// An idle provider retains only a weak reader adapter. An in-flight read holds
/// a temporary strong upgrade, even after its HTTP deadline; it may delay owner
/// handoff until the underlying async read completes. Timeout is not SQL cancellation.
/// Higher-level composition supplies an existing host and a noncapturing,
/// read-only projection. No Agentd dependency or implicit owner reopen is needed.
#[derive(Clone)]
pub struct OwnerStatusProvider {
    read: Option<Arc<dyn Fn() -> ObservationFuture + Send + Sync>>,
    flight: Arc<Semaphore>,
}

impl fmt::Debug for OwnerStatusProvider {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("OwnerStatusProvider")
            .finish_non_exhaustive()
    }
}

impl Default for OwnerStatusProvider {
    fn default() -> Self {
        Self {
            read: None,
            flight: Arc::new(Semaphore::new(1)),
        }
    }
}

impl OwnerStatusProvider {
    /// The callback must inspect its supplied owner without reopening a store,
    /// obtaining authority, retaining the host, or returning private identifiers.
    pub fn from_weak<T>(
        owner: Weak<T>,
        inspect: for<'a> fn(&'a T) -> OwnerObservationFuture<'a>,
    ) -> Self
    where
        T: Send + Sync + 'static,
    {
        Self {
            read: Some(Arc::new(move || {
                let owner = owner.clone();
                Box::pin(async move {
                    let Some(owner) = owner.upgrade() else {
                        return Observation::NotAttached;
                    };
                    match inspect(&owner).await {
                        Ok(observed)
                            if (observed.disposition == OwnerLeaseDisposition::Missing)
                                == observed.generation.is_none() =>
                        {
                            Observation::Observed {
                                generation: observed.generation,
                                disposition: observed.disposition,
                            }
                        }
                        Ok(_) => Observation::Unavailable {
                            reason: OwnerReadFailure::InvalidObservation,
                        },
                        Err(reason) => Observation::Unavailable { reason },
                    }
                }) as ObservationFuture
            })),
            ..Self::default()
        }
    }

    async fn observe(&self, timeout: Duration) -> Observation {
        let Some(read) = self.read.clone() else {
            return Observation::NotAttached;
        };
        let Ok(permit) = Arc::clone(&self.flight).try_acquire_owned() else {
            return Observation::Unavailable {
                reason: OwnerReadFailure::Busy,
            };
        };
        let task = tokio::spawn(async move {
            let _permit = permit;
            read().await
        });
        match tokio::time::timeout(timeout, task).await {
            Ok(Ok(observation)) => observation,
            Ok(Err(_)) => Observation::Unavailable {
                reason: OwnerReadFailure::ReadFailed,
            },
            Err(_) => Observation::Unavailable {
                reason: OwnerReadFailure::TimedOut,
            },
        }
    }

    pub(crate) async fn json(&self) -> anyhow::Result<Vec<u8>> {
        #[derive(Serialize)]
        struct Document {
            schema: &'static str,
            observation: Observation,
        }
        // Numbers are serialized directly from u64; consumers must not round-trip
        // them through JS Number. The Rust UI parses the raw transport bytes.
        Ok(serde_json::to_vec(&Document {
            schema: "hepta.owner-lease-observation.v1",
            observation: self.observe(OBSERVATION_TIMEOUT).await,
        })?)
    }
}

#[cfg(test)]
#[path = "owner_status_tests.rs"]
mod tests;
