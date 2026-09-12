//! In-process, read-only organ composition for a validated body graph.

use std::collections::BTreeMap;
use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use crate::OrganGraphError;
use crate::OrganGraphsV1;
use crate::ValidatedOrganGraphsV1;

pub const MAX_ORGAN_MESSAGE_BYTES: usize = 64 * 1024;

/// A trusted, compiled-in handler for the read-only organ host.
///
/// This trait is not a sandbox. Implementations are reviewed product code and
/// must return promptly without performing I/O, holding capabilities, spawning
/// work, invoking models, or crossing an external effect boundary.
pub trait TrustedReadOnlyOrganV1: fmt::Debug + Send {
    fn id(&self) -> &StableId;
    fn start(&mut self) -> Result<(), OrganHandlerFaultV1>;
    fn handle(&mut self, input_port: usize, payload: &[u8])
    -> Result<Vec<u8>, OrganHandlerFaultV1>;
    fn stop(&mut self) -> Result<(), OrganHandlerFaultV1>;
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct OrganHandlerFaultV1 {
    pub code: StableId,
}

impl OrganHandlerFaultV1 {
    pub fn new(code: StableId) -> Self {
        Self { code }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum HostedOrganStateV1 {
    Registered,
    Ready,
    Quarantined,
    Stopped,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct HostedOrganStatusV1 {
    pub id: StableId,
    pub state: HostedOrganStateV1,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct OrganDeliveryV1 {
    pub source: StableId,
    pub target: StableId,
    pub input_port: usize,
    pub output: Vec<u8>,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct OrganFaultRecordV1 {
    pub organ: StableId,
    pub code: StableId,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum OrganRuntimeError {
    Graph(OrganGraphError),
    ReadOnlyEffectScope {
        organ: StableId,
    },
    HandlerCount {
        expected: usize,
        actual: usize,
    },
    DuplicateHandler {
        organ: StableId,
    },
    MissingHandler {
        organ: StableId,
    },
    GenerationMismatch {
        expected: Generation,
        actual: Generation,
    },
    NonSuccessorGeneration {
        current: Generation,
        proposed: Generation,
    },
    ReplacementStopFailed {
        predecessor_faults: Vec<OrganFaultRecordV1>,
        candidate_cleanup_faults: Vec<OrganFaultRecordV1>,
    },
    UnknownSource {
        organ: StableId,
    },
    InvalidOutputPort {
        organ: StableId,
        port: usize,
    },
    UnroutedOutput {
        organ: StableId,
        port: usize,
    },
    OrganNotReady {
        organ: StableId,
        state: HostedOrganStateV1,
    },
    InputTooLarge {
        actual: usize,
    },
    OutputTooLarge {
        organ: StableId,
        actual: usize,
        delivered: usize,
    },
    InvalidStartState {
        organ: StableId,
        state: HostedOrganStateV1,
    },
    StartFailed {
        fault: OrganFaultRecordV1,
        cleanup_faults: Vec<OrganFaultRecordV1>,
    },
    HandleFailed {
        fault: OrganFaultRecordV1,
        delivered: usize,
    },
    StopFailed {
        faults: Vec<OrganFaultRecordV1>,
    },
}

impl fmt::Display for OrganRuntimeError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for OrganRuntimeError {}

#[derive(Debug)]
struct OrganSlotV1 {
    id: StableId,
    state: HostedOrganStateV1,
    started: bool,
    handler: Box<dyn TrustedReadOnlyOrganV1>,
}

/// A bounded single-generation host. It routes only one graph hop per call.
#[derive(Debug)]
pub struct OrganHostV1 {
    graph: OrganGraphsV1,
    validated: ValidatedOrganGraphsV1,
    slots: Vec<OrganSlotV1>,
}

impl OrganHostV1 {
    pub fn new(
        graph: OrganGraphsV1,
        handlers: Vec<Box<dyn TrustedReadOnlyOrganV1>>,
    ) -> Result<Self, OrganRuntimeError> {
        let validated = graph.validate().map_err(OrganRuntimeError::Graph)?;
        if let Some(organ) = graph
            .organs
            .iter()
            .find(|organ| !organ.effect_scope.is_empty())
        {
            return Err(OrganRuntimeError::ReadOnlyEffectScope {
                organ: organ.id.clone(),
            });
        }
        if handlers.len() != graph.organs.len() {
            return Err(OrganRuntimeError::HandlerCount {
                expected: graph.organs.len(),
                actual: handlers.len(),
            });
        }

        let mut handlers_by_id = BTreeMap::new();
        for handler in handlers {
            let id = handler.id().clone();
            if handlers_by_id.insert(id.clone(), handler).is_some() {
                return Err(OrganRuntimeError::DuplicateHandler { organ: id });
            }
        }
        let mut slots = Vec::with_capacity(graph.organs.len());
        for organ in &graph.organs {
            let Some(handler) = handlers_by_id.remove(&organ.id) else {
                return Err(OrganRuntimeError::MissingHandler {
                    organ: organ.id.clone(),
                });
            };
            slots.push(OrganSlotV1 {
                id: organ.id.clone(),
                state: HostedOrganStateV1::Registered,
                started: false,
                handler,
            });
        }
        Ok(Self {
            graph,
            validated,
            slots,
        })
    }

    pub fn generation(&self) -> Generation {
        self.graph.generation
    }

    pub fn statuses(&self) -> Vec<HostedOrganStatusV1> {
        self.slots
            .iter()
            .map(|slot| HostedOrganStatusV1 {
                id: slot.id.clone(),
                state: slot.state,
            })
            .collect()
    }

    /// Replace one ready, compiled-in read-only composition with its successor.
    /// Construction/start failure leaves the predecessor untouched. Once old
    /// cleanup starts, any failure leaves its explicit stopped/quarantined
    /// state visible and stops the candidate; no successful cutover is reported.
    /// There is no durable state or effect owner to migrate through this trait.
    pub fn replace_read_only_generation(
        &mut self,
        expected: Generation,
        graph: OrganGraphsV1,
        handlers: Vec<Box<dyn TrustedReadOnlyOrganV1>>,
    ) -> Result<(), OrganRuntimeError> {
        if self.generation() != expected {
            return Err(OrganRuntimeError::GenerationMismatch {
                expected: self.generation(),
                actual: expected,
            });
        }
        if expected.next().ok() != Some(graph.generation) {
            return Err(OrganRuntimeError::NonSuccessorGeneration {
                current: expected,
                proposed: graph.generation,
            });
        }
        for index in 0..self.slots.len() {
            self.require_ready(index)?;
        }
        let mut candidate = Self::new(graph, handlers)?;
        candidate.start_all()?;
        let predecessor_faults = self.stop_indices(
            self.validated
                .initialization_order
                .clone()
                .into_iter()
                .rev(),
        );
        if !predecessor_faults.is_empty() {
            let candidate_cleanup_faults = candidate.stop_indices(
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
        // Exclusive &mut access prevents dispatch from mixing generations.
        // The replaced host's Drop only sees already-attempted stop operations.
        *self = candidate;
        Ok(())
    }

    pub fn start_all(&mut self) -> Result<(), OrganRuntimeError> {
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
            match slot.handler.start() {
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
                    let cleanup_faults = self.stop_indices(started.into_iter().rev());
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

    pub fn dispatch_once(
        &mut self,
        generation: Generation,
        source: &StableId,
        output_port: usize,
        payload: &[u8],
    ) -> Result<Vec<OrganDeliveryV1>, OrganRuntimeError> {
        if generation != self.graph.generation {
            return Err(OrganRuntimeError::GenerationMismatch {
                expected: self.graph.generation,
                actual: generation,
            });
        }
        if payload.len() > MAX_ORGAN_MESSAGE_BYTES {
            return Err(OrganRuntimeError::InputTooLarge {
                actual: payload.len(),
            });
        }
        let source_index = self
            .graph
            .organs
            .iter()
            .position(|organ| &organ.id == source)
            .ok_or_else(|| OrganRuntimeError::UnknownSource {
                organ: source.clone(),
            })?;
        self.require_ready(source_index)?;
        if output_port >= self.graph.organs[source_index].outputs.len() {
            return Err(OrganRuntimeError::InvalidOutputPort {
                organ: source.clone(),
                port: output_port,
            });
        }
        let routes = self
            .graph
            .runtime
            .iter()
            .filter(|link| link.output.organ == source_index && link.output.port == output_port)
            .map(|link| (link.input.organ, link.input.port))
            .collect::<Vec<_>>();
        if routes.is_empty() {
            return Err(OrganRuntimeError::UnroutedOutput {
                organ: source.clone(),
                port: output_port,
            });
        }
        for &(target, _) in &routes {
            self.require_ready(target)?;
        }

        let mut deliveries = Vec::with_capacity(routes.len());
        for (target, input_port) in routes {
            let slot = &mut self.slots[target];
            let output = match slot.handler.handle(input_port, payload) {
                Ok(output) => output,
                Err(error) => {
                    slot.state = HostedOrganStateV1::Quarantined;
                    return Err(OrganRuntimeError::HandleFailed {
                        fault: OrganFaultRecordV1 {
                            organ: slot.id.clone(),
                            code: error.code,
                        },
                        delivered: deliveries.len(),
                    });
                }
            };
            if output.len() > MAX_ORGAN_MESSAGE_BYTES {
                slot.state = HostedOrganStateV1::Quarantined;
                return Err(OrganRuntimeError::OutputTooLarge {
                    organ: slot.id.clone(),
                    actual: output.len(),
                    delivered: deliveries.len(),
                });
            }
            deliveries.push(OrganDeliveryV1 {
                source: source.clone(),
                target: slot.id.clone(),
                input_port,
                output,
                authority: AuthorityPosture::DENY_ALL,
            });
        }
        Ok(deliveries)
    }

    pub fn stop_all(&mut self) -> Result<(), OrganRuntimeError> {
        let order = self
            .validated
            .initialization_order
            .iter()
            .copied()
            .rev()
            .collect::<Vec<_>>();
        let faults = self.stop_indices(order);
        if faults.is_empty() {
            Ok(())
        } else {
            Err(OrganRuntimeError::StopFailed { faults })
        }
    }

    fn require_ready(&self, index: usize) -> Result<(), OrganRuntimeError> {
        let slot = &self.slots[index];
        if slot.state == HostedOrganStateV1::Ready {
            Ok(())
        } else {
            Err(OrganRuntimeError::OrganNotReady {
                organ: slot.id.clone(),
                state: slot.state,
            })
        }
    }

    fn stop_indices(
        &mut self,
        indices: impl IntoIterator<Item = usize>,
    ) -> Vec<OrganFaultRecordV1> {
        let mut faults = Vec::new();
        for index in indices {
            let slot = &mut self.slots[index];
            if slot.started {
                match slot.handler.stop() {
                    Ok(()) => {
                        slot.started = false;
                        slot.state = HostedOrganStateV1::Stopped;
                    }
                    Err(error) => {
                        slot.started = false;
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

impl Drop for OrganHostV1 {
    fn drop(&mut self) {
        let _ = self.stop_all();
    }
}

#[cfg(test)]
#[path = "organ_runtime_tests.rs"]
mod tests;
