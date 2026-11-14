//! Contained callbacks for healthy, registry-mediated read-only replacement.
//!
//! This deliberately keeps a small copy of the start/drain bookkeeping rather
//! than changing shared lifecycle helpers: owner migration and recovery must
//! retain their existing panic and rollback semantics. No policy is stored in
//! the host or handlers, and only the registry calls this replacement method.

use std::panic::AssertUnwindSafe;

use codex_hepta_types::StableId;

use super::HostedOrganStateV1;
use super::OrganFaultRecordV1;
use super::OrganHandlerFaultV1;
use super::OrganHostV1;
use super::OrganRuntimeError;

fn callback_panic_fault(code: &str, fallback: &StableId) -> OrganHandlerFaultV1 {
    let code = match StableId::new(code) {
        Ok(code) => code,
        Err(_) => fallback.clone(),
    };
    OrganHandlerFaultV1::new(code)
}

impl OrganHostV1 {
    pub(crate) fn activate_healthy_registry_successor(
        &mut self,
        mut candidate: Self,
    ) -> Result<(), OrganRuntimeError> {
        self.validate_read_only_successor(self.generation(), candidate.generation())?;
        candidate.start_registry_candidate()?;
        let predecessor_faults = self.stop_registry_indices(
            self.validated
                .initialization_order
                .clone()
                .into_iter()
                .rev(),
        );
        if !predecessor_faults.is_empty() {
            let candidate_cleanup_faults = candidate.stop_registry_indices(
                candidate
                    .validated
                    .initialization_order
                    .clone()
                    .into_iter()
                    .rev(),
            );
            return Err(OrganRuntimeError::ReplacementStopFailed {
                predecessor_faults,
                candidate_cleanup_faults,
            });
        }
        *self = candidate;
        Ok(())
    }

    fn start_registry_candidate(&mut self) -> Result<(), OrganRuntimeError> {
        let order = self.validated.initialization_order.clone();
        for &index in &order {
            let slot = &self.slots[index];
            if slot.state != HostedOrganStateV1::Registered {
                return Err(OrganRuntimeError::InvalidStartState {
                    organ: slot.id.clone(),
                    state: slot.state,
                });
            }
        }
        let mut started = Vec::new();
        for index in order {
            let slot = &mut self.slots[index];
            slot.started = true;
            let result = std::panic::catch_unwind(AssertUnwindSafe(|| slot.handler.start()));
            let result = match result {
                Ok(result) => result,
                Err(_) => Err(callback_panic_fault("organ.callback.start-panic", &slot.id)),
            };
            match result {
                Ok(()) => {
                    slot.state = HostedOrganStateV1::Ready;
                    started.push(index);
                }
                Err(error) => {
                    slot.state = HostedOrganStateV1::Quarantined;
                    let fault = OrganFaultRecordV1 {
                        organ: slot.id.clone(),
                        code: error.code,
                    };
                    started.push(index);
                    let cleanup_faults = self.stop_registry_indices(started.into_iter().rev());
                    self.slots[index].state = HostedOrganStateV1::Quarantined;
                    return Err(OrganRuntimeError::StartFailed {
                        fault,
                        cleanup_faults,
                    });
                }
            }
        }
        Ok(())
    }

    fn stop_registry_indices(
        &mut self,
        indices: impl IntoIterator<Item = usize>,
    ) -> Vec<OrganFaultRecordV1> {
        let mut faults = Vec::new();
        for index in indices {
            let slot = &mut self.slots[index];
            if slot.started {
                // Consume the one stop attempt before the callback. The original
                // Drop path then sees false and cannot retry a panicking hook.
                slot.started = false;
                let result = std::panic::catch_unwind(AssertUnwindSafe(|| slot.handler.stop()));
                let result = match result {
                    Ok(result) => result,
                    Err(_) => Err(callback_panic_fault("organ.callback.stop-panic", &slot.id)),
                };
                match result {
                    Ok(()) => slot.state = HostedOrganStateV1::Stopped,
                    Err(error) => {
                        slot.state = HostedOrganStateV1::Quarantined;
                        faults.push(OrganFaultRecordV1 {
                            organ: slot.id.clone(),
                            code: error.code,
                        });
                    }
                }
            } else if slot.state != HostedOrganStateV1::Quarantined {
                slot.state = HostedOrganStateV1::Stopped;
            }
        }
        faults
    }
}
