//! Fixed ordinary Child boundary; no model, cgroup or resource-release claim.

use crate::OrdinaryCpuRegistration;
use crate::ordinary_cpu_owner::CAPACITY;
use crate::ordinary_cpu_owner::Entry;
use crate::ordinary_cpu_owner::OrdinaryCpuOwner;
use crate::ordinary_cpu_registration::DESTINATION;
use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_memory::FinalUseProductionOutboxTarget;
use codex_hepta_memory::ProductionDispatchFuture;
use codex_hepta_memory::ProductionDispatchRequest;
use codex_hepta_memory::ProductionOutboxTarget;
use codex_hepta_memory::ProductionTargetOutcome;
use codex_hepta_memory::ProductionTerminalObservation;
use codex_hepta_memory::ProductionTerminalObservationFuture;
use codex_hepta_memory::ProductionVerifiedDispatch;
use codex_hepta_memory::ProductionVerifiedDispatchFuture;
use codex_hepta_types::Digest32;
use sqlx::SqlitePool;
use std::process::Child;
use std::process::Command;
use std::process::ExitStatus;
use std::process::Stdio;
use std::sync::Mutex;
use std::time::Instant;

struct CapturedExit {
    status: ExitStatus,
    observed_at: Instant,
}

struct OwnedChild {
    child: Child,
    semantic: Digest32,
    started_at: Instant,
    exit: Option<CapturedExit>,
}

/// A trusted migrated pool, original FinalUse owner and fixed deployment.
/// Child slots stay permanent; owner loss never proves resource release.
pub struct OrdinaryCpuTarget {
    registration: OrdinaryCpuRegistration,
    authority: FinalUseAuthority,
    owner: OrdinaryCpuOwner,
    children: Mutex<[Option<OwnedChild>; CAPACITY]>,
}

impl OrdinaryCpuTarget {
    pub async fn from_migrated_pool(
        registration: OrdinaryCpuRegistration,
        authority: FinalUseAuthority,
        pool: SqlitePool,
    ) -> Result<Self, String> {
        Ok(Self {
            registration,
            authority,
            owner: OrdinaryCpuOwner::from_migrated_pool(pool).await?,
            children: Mutex::new(std::array::from_fn(|_| None)),
        })
    }
}

impl ProductionOutboxTarget for OrdinaryCpuTarget {
    fn dispatch<'a>(&'a self, _request: ProductionDispatchRequest) -> ProductionDispatchFuture<'a> {
        Box::pin(async {
            ProductionTargetOutcome::Rejected {
                reason: "ordinary CPU target requires the original sealed FinalUse dispatch"
                    .to_owned(),
            }
        })
    }
}

impl FinalUseProductionOutboxTarget for OrdinaryCpuTarget {
    fn destination_id(&self) -> &str {
        DESTINATION
    }

    fn dispatch_verified<'a>(
        &'a self,
        dispatch: ProductionVerifiedDispatch,
    ) -> ProductionVerifiedDispatchFuture<'a> {
        Box::pin(async move {
            dispatch.verify_target_authority(&self.authority)?;
            let intent = match self.registration.validate(dispatch.request()) {
                Ok(intent) => intent,
                Err(_) => {
                    return Ok(ProductionTargetOutcome::Rejected {
                        reason: "ordinary CPU request differs from its fixed registration"
                            .to_owned(),
                    });
                }
            };
            let slot = match self.owner.enter(&intent).await {
                Ok(Entry::New(slot)) => slot,
                Ok(Entry::Retained) | Err(_) => {
                    return Ok(dispatch_unknown(
                        "ordinary CPU admission is retained or unknown; no relaunch",
                    ));
                }
            };
            let Ok(mut children) = self.children.lock() else {
                return Ok(dispatch_unknown("ordinary child owner is unavailable"));
            };
            let Some(child_slot) = children.get_mut(slot) else {
                return Ok(dispatch_unknown("ordinary child slot is unavailable"));
            };
            if child_slot.is_some() {
                return Ok(dispatch_unknown("ordinary child slot is retained"));
            }
            dispatch.with_dispatch_boundary(&self.authority, |_| {
                let started_at = Instant::now();
                let child = Command::new(&self.registration.program)
                    .args(&self.registration.arguments)
                    .current_dir(&self.registration.binding.working_directory)
                    .env_clear()
                    .stdin(Stdio::null())
                    .stdout(Stdio::null())
                    .stderr(Stdio::null())
                    .spawn();
                if let Ok(child) = child {
                    *child_slot = Some(OwnedChild {
                        child,
                        semantic: intent.semantic_digest(),
                        started_at,
                        exit: None,
                    });
                }
                dispatch_unknown(
                    "ordinary child dispatch entered; original owner must observe terminality",
                )
            })
        })
    }

    fn observe_terminal<'a>(
        &'a self,
        request: &'a ProductionDispatchRequest,
    ) -> ProductionTerminalObservationFuture<'a> {
        Box::pin(async move {
            let intent = match self.registration.validate(request) {
                Ok(intent) => intent,
                Err(_) => {
                    return ProductionTerminalObservation::Unavailable {
                        reason: "ordinary child request binding differs".to_owned(),
                    };
                }
            };
            let slot = match self.owner.entry(&intent).await {
                Ok(Some((slot, _))) => slot,
                Ok(None) | Err(_) => {
                    return observation_unknown("ordinary child entry is absent or unknown");
                }
            };
            let receipt = {
                let Ok(mut children) = self.children.lock() else {
                    return observation_unknown("ordinary child owner is unavailable");
                };
                let Some(owned) = children.get_mut(slot).and_then(Option::as_mut) else {
                    return observation_unknown(
                        "no retained original Child; disk state cannot reconstruct one",
                    );
                };
                if owned.semantic != intent.semantic_digest() {
                    return observation_unknown("ordinary Child semantic identity conflicts");
                }
                if owned.exit.is_none() {
                    match owned.child.try_wait() {
                        Ok(Some(status)) => {
                            owned.exit = Some(CapturedExit {
                                status,
                                observed_at: Instant::now(),
                            })
                        }
                        Ok(None) | Err(_) => {
                            return observation_unknown("ordinary child exit is not observed");
                        }
                    }
                }
                let Some(exit) = &owned.exit else {
                    return observation_unknown("ordinary child exit is unavailable");
                };
                if exit.observed_at.duration_since(owned.started_at)
                    > self.registration.binding.observer_deadline
                {
                    return observation_unknown("ordinary child observer deadline elapsed");
                }
                if !exit.status.success() {
                    return observation_unknown("ordinary child exited unsuccessfully");
                }
                format!("ordinary-child-exit-v1:{}:exit0", intent.semantic_digest())
            };
            if self.owner.record_terminal(&intent, &receipt).await.is_err() {
                return observation_unknown("ordinary child terminal durability is unknown");
            }
            ProductionTerminalObservation::Applied { receipt }
        })
    }
}

fn dispatch_unknown(reason: &str) -> ProductionTargetOutcome {
    ProductionTargetOutcome::Indeterminate {
        reason: reason.to_owned(),
    }
}

fn observation_unknown(reason: &str) -> ProductionTerminalObservation {
    ProductionTerminalObservation::Indeterminate {
        reason: reason.to_owned(),
    }
}

#[cfg(test)]
#[path = "ordinary_cpu_target_tests.rs"]
mod tests;
