//! In-process, read-only organ composition for a validated body graph.

use std::collections::BTreeMap;
use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use crate::FallbackTerminal;
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

/// The stable, in-process ABI exposed by a host for one organ generation.
///
/// This is intentionally a value projection of the validated graph. It gives
/// a dynamic coordinator stable identities and typed port names without
/// turning the coordinator into a code loader or an authority issuer.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct OrganAbiV1 {
    pub generation: Generation,
    pub id: StableId,
    pub role: crate::OrganRole,
    pub input_ports: Vec<StableId>,
    pub output_ports: Vec<StableId>,
    pub effect_scope: Vec<StableId>,
    pub fallback: FallbackTerminal,
}

/// A bounded state handoff callback. Implementations own the state store and
/// may use this hook to snapshot and migrate it; the read-only host never
/// opens files, databases, sockets or credentials itself.
pub trait OrganStateMigrationV1 {
    fn snapshot(&mut self, predecessor: Generation) -> Result<Vec<u8>, OrganMigrationError>;

    fn migrate(
        &mut self,
        snapshot: &[u8],
        predecessor: Generation,
        candidate: Generation,
    ) -> Result<(), OrganMigrationError>;

    fn rollback(
        &mut self,
        snapshot: &[u8],
        predecessor: Generation,
        candidate: Generation,
    ) -> Result<(), OrganMigrationError>;
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum OrganMigrationError {
    Rejected,
    SnapshotTooLarge { actual: usize },
    Callback(StableId),
}

impl fmt::Display for OrganMigrationError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for OrganMigrationError {}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct OrganFallbackStatusV1 {
    pub generation: Generation,
    pub organ: StableId,
    pub state: HostedOrganStateV1,
    pub terminal: FallbackTerminal,
    pub fallback_targets: Vec<StableId>,
    pub available: bool,
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
    MigrationReplacementStopFailed {
        predecessor_faults: Vec<OrganFaultRecordV1>,
        candidate_cleanup_faults: Vec<OrganFaultRecordV1>,
        rollback_error: Option<OrganMigrationError>,
    },
    MigrationSnapshotFailed {
        error: OrganMigrationError,
    },
    CandidateMigrationFailed {
        error: OrganMigrationError,
        rollback_error: Option<OrganMigrationError>,
        candidate_cleanup_faults: Vec<OrganFaultRecordV1>,
    },
    CandidateStartFailed {
        error: Box<OrganRuntimeError>,
        rollback_error: Option<OrganMigrationError>,
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

    /// Return the stable ABI projection for this exact host generation.
    pub fn abi(&self) -> Vec<OrganAbiV1> {
        self.graph
            .organs
            .iter()
            .map(|organ| OrganAbiV1 {
                generation: self.graph.generation,
                id: organ.id.clone(),
                role: organ.role,
                input_ports: organ.inputs.clone(),
                output_ports: organ.outputs.clone(),
                effect_scope: organ.effect_scope.iter().cloned().collect(),
                fallback: organ.terminal.clone(),
            })
            .collect()
    }

    /// Report local fallback availability without invoking a handler or
    /// crossing an external boundary. A fallback is available only when its
    /// target is currently ready; terminal safe-state/human-takeover paths are
    /// represented as available local endpoints when declared by the graph.
    pub fn local_fallback_status(&self) -> Vec<OrganFallbackStatusV1> {
        self.graph
            .organs
            .iter()
            .enumerate()
            .map(|(index, organ)| {
                let fallback_targets = self
                    .graph
                    .fallback
                    .iter()
                    .filter(|edge| edge.from == index)
                    .map(|edge| self.graph.organs[edge.to].id.clone())
                    .collect::<Vec<_>>();
                let target_ready = self
                    .graph
                    .fallback
                    .iter()
                    .filter(|edge| edge.from == index)
                    .any(|edge| self.slots[edge.to].state == HostedOrganStateV1::Ready);
                let terminal_available = !matches!(organ.terminal, FallbackTerminal::None);
                OrganFallbackStatusV1 {
                    generation: self.graph.generation,
                    organ: organ.id.clone(),
                    state: self.slots[index].state,
                    terminal: organ.terminal.clone(),
                    fallback_targets,
                    available: target_ready || terminal_available,
                }
            })
            .collect()
    }

    /// Alias with the shorter name used by local supervisors.
    pub fn fallback_status(&self) -> Vec<OrganFallbackStatusV1> {
        self.local_fallback_status()
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

    /// Replace a generation while making state transfer an explicit,
    /// owner-provided callback. Snapshot and migration happen before the
    /// predecessor is stopped. Failed rollback quarantines the predecessor;
    /// it must never keep serving state whose restoration is uncertain. These
    /// callbacks do not implement a durable writer handoff or runtime sandbox.
    pub fn replace_read_only_generation_with_migration<M: OrganStateMigrationV1>(
        &mut self,
        expected: Generation,
        graph: OrganGraphsV1,
        handlers: Vec<Box<dyn TrustedReadOnlyOrganV1>>,
        migration: &mut M,
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
        let snapshot = migration
            .snapshot(expected)
            .map_err(|error| OrganRuntimeError::MigrationSnapshotFailed { error })?;
        if snapshot.len() > MAX_ORGAN_MESSAGE_BYTES {
            return Err(OrganRuntimeError::MigrationSnapshotFailed {
                error: OrganMigrationError::SnapshotTooLarge {
                    actual: snapshot.len(),
                },
            });
        }
        if let Err(error) = candidate.start_all() {
            let rollback_error = migration
                .rollback(&snapshot, expected, candidate.generation())
                .err();
            if rollback_error.is_some() {
                for slot in &mut self.slots {
                    slot.state = HostedOrganStateV1::Quarantined;
                }
            }
            return Err(OrganRuntimeError::CandidateStartFailed {
                error: Box::new(error),
                rollback_error,
            });
        }
        if let Err(error) = migration.migrate(&snapshot, expected, candidate.generation()) {
            let rollback_error = migration
                .rollback(&snapshot, expected, candidate.generation())
                .err();
            if rollback_error.is_some() {
                for slot in &mut self.slots {
                    slot.state = HostedOrganStateV1::Quarantined;
                }
            }
            let candidate_cleanup_faults = candidate.stop_indices(
                candidate
                    .validated
                    .initialization_order
                    .clone()
                    .into_iter()
                    .rev(),
            );
            return Err(OrganRuntimeError::CandidateMigrationFailed {
                error,
                rollback_error,
                candidate_cleanup_faults,
            });
        }
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
            let rollback_error = migration
                .rollback(&snapshot, expected, candidate.generation())
                .err();
            return Err(OrganRuntimeError::MigrationReplacementStopFailed {
                predecessor_faults,
                candidate_cleanup_faults,
                rollback_error,
            });
        }
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
