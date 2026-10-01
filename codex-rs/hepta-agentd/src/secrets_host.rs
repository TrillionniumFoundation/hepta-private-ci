//! One enrolled client, four owned physical workers, and no local secret authority.
use std::path::Path;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::Weak;
use std::thread::JoinHandle;
use std::time::Duration;
use std::time::Instant;

use codex_hepta_bao_adapter::SecretsRuntimeClient;
use codex_hepta_bao_adapter::SecretsRuntimeClientConfig;
use codex_hepta_bao_adapter::SecretsRuntimeResponse;
use codex_hepta_contracts::Sha256Digest;
use tokio::sync::OwnedSemaphorePermit;
use tokio::sync::Semaphore;
use tokio::sync::oneshot;

use crate::AgentdError;
use crate::AgentdMethod;
use crate::AgentdState;
use crate::SecretsOriginalObservation;

const MAX_WORKERS: usize = 4;
const MAX_ORIGINAL_BUDGET: Duration = Duration::from_secs(30);

struct PhysicalWorker {
    handle: JoinHandle<()>,
    // The owner releases this slot only after physical joining.
    _permit: OwnedSemaphorePermit,
}
struct PhysicalWorkers {
    closed: bool,
    handles: Vec<PhysicalWorker>,
}
impl PhysicalWorkers {
    fn reap_completed(&mut self) -> Result<(), AgentdError> {
        let mut index = 0;
        while index < self.handles.len() {
            if self.handles[index].handle.is_finished() {
                let worker = self.handles.swap_remove(index);
                if worker.handle.join().is_err() {
                    self.closed = true;
                    return Err(AgentdError::Protocol(
                        "physical secrets worker failed; original reconciliation is required"
                            .into(),
                    ));
                }
            } else {
                index += 1;
            }
        }
        Ok(())
    }
}

pub(crate) struct AgentdSecretsHost {
    client: Arc<SecretsRuntimeClient>,
    state: Weak<AgentdState>,
    slots: Arc<Semaphore>,
    workers: Mutex<PhysicalWorkers>,
}

impl AgentdSecretsHost {
    pub(crate) fn open(state: &Arc<AgentdState>, path: &Path) -> Result<Self, AgentdError> {
        let config = SecretsRuntimeClientConfig::load_root_owned(path).map_err(|_| {
            AgentdError::Invalid("secrets client needs protected Root enrollment".into())
        })?;
        let client = SecretsRuntimeClient::new(config, state.identity().agent_id.as_str())
            .map_err(|_| {
                AgentdError::GenerationFenced(
                    "secrets client differs from actual Agent UID/identity".into(),
                )
            })?;
        Ok(Self {
            client: Arc::new(client),
            state: Arc::downgrade(state),
            slots: Arc::new(Semaphore::new(MAX_WORKERS)),
            workers: Mutex::new(PhysicalWorkers {
                closed: false,
                handles: Vec::new(),
            }),
        })
    }

    pub(crate) fn closed(&self) -> bool {
        self.workers.lock().map_or(true, |workers| workers.closed)
    }

    pub(crate) fn pending_workers(&self) -> u32 {
        if let Ok(mut workers) = self.workers.lock() {
            // Drain observes a physically joined cut, including completed workers
            // whose control callers disappeared before collecting a response.
            let _ = workers.reap_completed();
        }
        (MAX_WORKERS - self.slots.available_permits()) as u32
    }

    pub(crate) fn dispatch(
        &self,
        method: AgentdMethod,
    ) -> Result<oneshot::Receiver<SecretsOriginalObservation>, AgentdError> {
        let (original, budget) = match &method {
            AgentdMethod::SecretsConsumeOriginal {
                original_id,
                budget_ms,
            } => {
                if *budget_ms == 0 {
                    return Err(AgentdError::Invalid(
                        "secrets original budget must be positive".into(),
                    ));
                }
                (
                    original_id,
                    Duration::from_millis(*budget_ms).min(MAX_ORIGINAL_BUDGET),
                )
            }
            AgentdMethod::SecretsOriginalStatus { original_id }
            | AgentdMethod::SecretsRecoverOriginal { original_id } => {
                (original_id, MAX_ORIGINAL_BUDGET)
            }
            _ => return Err(AgentdError::Protocol("unsupported secrets command".into())),
        };
        let original_operation_id = self
            .client
            .original_operation_id(original)
            .map_err(|_| AgentdError::Invalid("invalid original secrets identity".into()))?;
        // Scheduling and generation refresh consume this original budget.
        let deadline = Instant::now() + budget;
        let mut workers = self.workers.lock().map_err(|_| {
            AgentdError::Protocol("physical secrets worker owner is poisoned".into())
        })?;
        if workers.closed {
            return Err(AgentdError::GenerationFenced(
                "secrets worker admission is closed".into(),
            ));
        }
        workers.reap_completed()?;
        if workers.closed {
            return Err(AgentdError::GenerationFenced(
                "secrets worker admission is closed".into(),
            ));
        }
        let permit = Arc::clone(&self.slots)
            .try_acquire_owned()
            .map_err(|_| AgentdError::Protocol("physical secrets worker bound exhausted".into()))?;
        let client = Arc::clone(&self.client);
        let state = self.state.clone();
        let (sender, receiver) = oneshot::channel();
        let handle = std::thread::Builder::new()
            .name("hepta-secret-original".into())
            .spawn(move || {
                let unknown = || SecretsOriginalObservation::Unknown {
                    original_operation_id: original_operation_id.clone(),
                };
                let response = (|| {
                    let state = state.upgrade()?;
                    state.refresh_generation().ok()?;
                    let response = match method {
                        AgentdMethod::SecretsConsumeOriginal { original_id, .. } => {
                            if !state.automation_admission_ready().ok()? {
                                return Some(SecretsOriginalObservation::Rejected {});
                            }
                            let remaining = deadline.checked_duration_since(Instant::now())?;
                            client.consume_original(&original_id, remaining).ok()?
                        }
                        AgentdMethod::SecretsOriginalStatus { original_id } => {
                            client.original_status(&original_id).ok()?
                        }
                        AgentdMethod::SecretsRecoverOriginal { original_id } => {
                            client.recover_original(&original_id).ok()?
                        }
                        _ => return None,
                    };
                    match response {
                        SecretsRuntimeResponse::Completed {
                            original_operation_id,
                            receipt,
                            reservation_id,
                            observed_cost,
                        } => Some(SecretsOriginalObservation::Completed {
                            original_operation_id,
                            reservation_id,
                            observed_cost,
                            receipt_digest: Sha256Digest::for_bytes(
                                &serde_json::to_vec(&receipt).ok()?,
                            )
                            .as_str()
                            .to_owned(),
                        }),
                        SecretsRuntimeResponse::Unknown {
                            original_operation_id,
                        } => Some(SecretsOriginalObservation::Unknown {
                            original_operation_id,
                        }),
                        SecretsRuntimeResponse::Rejected => {
                            Some(SecretsOriginalObservation::Rejected {})
                        }
                    }
                })()
                .unwrap_or_else(unknown);
                // The control response may have expired. The original durable
                // daemon/consumer record and physical worker ownership still stand.
                let _ = sender.send(response);
            })
            .map_err(|_| AgentdError::Protocol("physical secrets worker could not start".into()))?;
        workers.handles.push(PhysicalWorker {
            handle,
            _permit: permit,
        });
        Ok(receiver)
    }

    pub(crate) async fn shutdown(&self) -> Result<(), AgentdError> {
        let (handles, poisoned) = {
            let (mut workers, poisoned) = match self.workers.lock() {
                Ok(workers) => (workers, false),
                Err(poisoned) => (poisoned.into_inner(), true),
            };
            workers.closed = true;
            (std::mem::take(&mut workers.handles), poisoned)
        };
        // Called after task/control shutdown, while the original Agent writer
        // lock is still held. No timeout/abort can impersonate physical joining.
        tokio::task::spawn_blocking(move || {
            let mut failed = poisoned;
            for worker in handles {
                failed |= worker.handle.join().is_err();
            }
            if failed {
                Err(AgentdError::Protocol(
                    "physical secrets worker failed; retain original Unknown".into(),
                ))
            } else {
                Ok(())
            }
        })
        .await
        .map_err(|_| AgentdError::Protocol("physical secrets worker join did not finish".into()))?
    }
}

#[cfg(test)]
#[path = "secrets_host_tests.rs"]
pub(crate) mod tests;
