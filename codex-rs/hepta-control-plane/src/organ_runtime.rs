//! Receipt-preserving wrapper for the trusted in-process organ host.
//!
//! The lifecycle and one-hop handler implementation remains in
//! `organ_runtime_core.rs`. This wrapper retains the exact admitted route map
//! and records each synchronous handler result so every fanout attempt can
//! return a complete per-target identity/status set, including exact output
//! digests for the successfully delivered prefix before a later target fails.

use std::collections::BTreeMap;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::MutexGuard;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use crate::OrganFanoutReceiptV1;
use crate::OrganGraphsV1;
use crate::OrganTargetDeliveryDispositionV1;
use crate::OrganTargetDeliveryReceiptV1;

#[path = "organ_runtime_core.rs"]
mod core;

pub use core::HostedOrganStateV1;
pub use core::HostedOrganStatusV1;
pub use core::MAX_ORGAN_MESSAGE_BYTES;
pub use core::OrganAbiV1;
pub use core::OrganDeliveryV1;
pub use core::OrganFallbackStatusV1;
pub use core::OrganFaultRecordV1;
pub use core::OrganHandlerFaultV1;
pub use core::OrganMigrationError;
pub use core::OrganRuntimeError;
pub use core::OrganStateMigrationV1;
pub use core::TrustedReadOnlyOrganV1;

#[derive(Debug)]
struct OrganHandlerObservationV1 {
    target: StableId,
    input_port: usize,
    result: Result<Option<Digest32>, StableId>,
}

#[derive(Debug, Default)]
struct OrganObservationStateV1 {
    enabled: bool,
    entries: Vec<OrganHandlerObservationV1>,
}

type OrganObservationLogV1 = Arc<Mutex<OrganObservationStateV1>>;

/// Transparent recording adapter used only to preserve synchronous fanout
/// evidence. It delegates lifecycle and handler calls to the exact admitted
/// implementation and neither grants authority nor changes dispatch order.
#[derive(Debug)]
struct ReceiptRecordingOrganV1 {
    inner: Box<dyn TrustedReadOnlyOrganV1>,
    observations: OrganObservationLogV1,
}

impl TrustedReadOnlyOrganV1 for ReceiptRecordingOrganV1 {
    fn id(&self) -> &StableId {
        self.inner.id()
    }

    fn start(&mut self) -> Result<(), OrganHandlerFaultV1> {
        self.inner.start()
    }

    fn handle(
        &mut self,
        input_port: usize,
        payload: &[u8],
    ) -> Result<Vec<u8>, OrganHandlerFaultV1> {
        let target = self.inner.id().clone();
        let result = self.inner.handle(input_port, payload);
        let mut observations = observation_state(&self.observations);
        if observations.enabled {
            let recorded = match &result {
                Ok(output) if output.len() <= MAX_ORGAN_MESSAGE_BYTES => {
                    Ok(Some(Digest32::of_bytes(output)))
                }
                Ok(_) => Ok(None),
                Err(error) => Err(error.code.clone()),
            };
            observations.entries.push(OrganHandlerObservationV1 {
                target,
                input_port,
                result: recorded,
            });
        }
        result
    }

    fn stop(&mut self) -> Result<(), OrganHandlerFaultV1> {
        self.inner.stop()
    }
}

#[derive(Debug)]
pub struct OrganHostV1 {
    inner: core::OrganHostV1,
    routes: BTreeMap<(StableId, usize), Vec<(StableId, usize)>>,
    observations: OrganObservationLogV1,
}

impl OrganHostV1 {
    pub fn new(
        graph: OrganGraphsV1,
        handlers: Vec<Box<dyn TrustedReadOnlyOrganV1>>,
    ) -> Result<Self, OrganRuntimeError> {
        let routes = route_map(&graph);
        let (handlers, observations) = wrap_handlers(handlers);
        let inner = core::OrganHostV1::new(graph, handlers)?;
        Ok(Self {
            inner,
            routes,
            observations,
        })
    }

    pub fn generation(&self) -> Generation {
        self.inner.generation()
    }

    pub fn statuses(&self) -> Vec<HostedOrganStatusV1> {
        self.inner.statuses()
    }

    pub fn abi(&self) -> Vec<OrganAbiV1> {
        self.inner.abi()
    }

    pub fn local_fallback_status(&self) -> Vec<OrganFallbackStatusV1> {
        self.inner.local_fallback_status()
    }

    pub fn fallback_status(&self) -> Vec<OrganFallbackStatusV1> {
        self.inner.fallback_status()
    }

    pub fn replace_read_only_generation(
        &mut self,
        expected: Generation,
        graph: OrganGraphsV1,
        handlers: Vec<Box<dyn TrustedReadOnlyOrganV1>>,
    ) -> Result<(), OrganRuntimeError> {
        let routes = route_map(&graph);
        let (handlers, observations) = wrap_handlers(handlers);
        self.inner
            .replace_read_only_generation(expected, graph, handlers)?;
        self.routes = routes;
        self.observations = observations;
        Ok(())
    }

    pub(crate) fn replace_admitted_read_only_generation(
        &mut self,
        expected: Generation,
        candidate: Self,
    ) -> Result<(), OrganRuntimeError> {
        let Self {
            inner,
            routes,
            observations,
        } = candidate;
        self.inner
            .replace_admitted_read_only_generation(expected, inner)?;
        self.routes = routes;
        self.observations = observations;
        Ok(())
    }

    pub(crate) fn recover_admitted_read_only_generation(
        &mut self,
        expected: Generation,
        candidate: Self,
    ) -> Result<(), OrganRuntimeError> {
        let Self {
            inner,
            routes,
            observations,
        } = candidate;
        self.inner
            .recover_admitted_read_only_generation(expected, inner)?;
        self.routes = routes;
        self.observations = observations;
        Ok(())
    }

    pub fn replace_read_only_generation_with_migration<M: OrganStateMigrationV1 + ?Sized>(
        &mut self,
        expected: Generation,
        graph: OrganGraphsV1,
        handlers: Vec<Box<dyn TrustedReadOnlyOrganV1>>,
        migration: &mut M,
    ) -> Result<(), OrganRuntimeError> {
        let routes = route_map(&graph);
        let (handlers, observations) = wrap_handlers(handlers);
        self.inner
            .replace_read_only_generation_with_migration(expected, graph, handlers, migration)?;
        self.routes = routes;
        self.observations = observations;
        Ok(())
    }

    pub(crate) fn replace_admitted_read_only_generation_with_migration<
        M: OrganStateMigrationV1 + ?Sized,
    >(
        &mut self,
        expected: Generation,
        candidate: Self,
        migration: &mut M,
    ) -> Result<(), OrganRuntimeError> {
        let Self {
            inner,
            routes,
            observations,
        } = candidate;
        self.inner
            .replace_admitted_read_only_generation_with_migration(expected, inner, migration)?;
        self.routes = routes;
        self.observations = observations;
        Ok(())
    }

    pub(crate) fn recover_admitted_read_only_generation_with_migration<
        M: OrganStateMigrationV1 + ?Sized,
    >(
        &mut self,
        expected: Generation,
        candidate: Self,
        migration: &mut M,
    ) -> Result<(), OrganRuntimeError> {
        let Self {
            inner,
            routes,
            observations,
        } = candidate;
        self.inner
            .recover_admitted_read_only_generation_with_migration(expected, inner, migration)?;
        self.routes = routes;
        self.observations = observations;
        Ok(())
    }

    pub fn start_all(&mut self) -> Result<(), OrganRuntimeError> {
        self.inner.start_all()
    }

    pub fn dispatch_once(
        &mut self,
        generation: Generation,
        source: &StableId,
        output_port: usize,
        payload: &[u8],
    ) -> Result<Vec<OrganDeliveryV1>, OrganRuntimeError> {
        cancel_observation(&self.observations);
        let result = self
            .inner
            .dispatch_once(generation, source, output_port, payload);
        cancel_observation(&self.observations);
        result
    }

    /// Execute one bounded fanout and preserve an identity/status slot for
    /// every admitted target. Successful targets keep exact output digests even
    /// when a later handler fails; unattempted suffixes remain explicit.
    #[must_use]
    pub fn dispatch_once_with_receipt(
        &mut self,
        generation: Generation,
        source: &StableId,
        output_port: usize,
        payload: &[u8],
    ) -> OrganFanoutReceiptV1 {
        let admitted_targets = self
            .routes
            .get(&(source.clone(), output_port))
            .cloned()
            .unwrap_or_default();
        let mut targets = admitted_targets
            .iter()
            .map(|(target, input_port)| OrganTargetDeliveryReceiptV1 {
                target: target.clone(),
                input_port: *input_port,
                disposition: OrganTargetDeliveryDispositionV1::NotAttempted,
                output_digest: None,
                fault_code: None,
            })
            .collect::<Vec<_>>();

        begin_observation(&self.observations);
        let dispatch = self
            .inner
            .dispatch_once(generation, source, output_port, payload);
        let observations = finish_observation(&self.observations);
        apply_observations(&mut targets, &observations);

        let error = match dispatch {
            Ok(deliveries) => {
                for (target, delivery) in targets.iter_mut().zip(deliveries) {
                    target.disposition = OrganTargetDeliveryDispositionV1::Delivered;
                    target.output_digest = Some(Digest32::of_bytes(&delivery.output));
                    target.fault_code = None;
                }
                None
            }
            Err(error) => {
                match &error {
                    OrganRuntimeError::HandleFailed { fault, delivered } => {
                        mark_unrecorded_delivered_prefix(&mut targets, *delivered);
                        if let Some(target) = targets.get_mut(*delivered) {
                            target.disposition = OrganTargetDeliveryDispositionV1::Failed;
                            target.output_digest = None;
                            target.fault_code = Some(fault.code.clone());
                        }
                    }
                    OrganRuntimeError::OutputTooLarge {
                        organ, delivered, ..
                    } => {
                        mark_unrecorded_delivered_prefix(&mut targets, *delivered);
                        let failed_index = if targets
                            .get(*delivered)
                            .is_some_and(|target| &target.target == organ)
                        {
                            Some(*delivered)
                        } else {
                            targets.iter().position(|target| &target.target == organ)
                        };
                        if let Some(index) = failed_index {
                            let target = &mut targets[index];
                            target.disposition = OrganTargetDeliveryDispositionV1::Failed;
                            target.output_digest = None;
                            target.fault_code = None;
                        }
                    }
                    _ => {}
                }
                Some(error)
            }
        };

        OrganFanoutReceiptV1 {
            generation,
            source: source.clone(),
            output_port,
            payload_digest: Digest32::of_bytes(payload),
            targets,
            error,
            authority: AuthorityPosture::DENY_ALL,
        }
    }

    pub fn stop_all(&mut self) -> Result<(), OrganRuntimeError> {
        self.inner.stop_all()
    }
}

fn wrap_handlers(
    handlers: Vec<Box<dyn TrustedReadOnlyOrganV1>>,
) -> (Vec<Box<dyn TrustedReadOnlyOrganV1>>, OrganObservationLogV1) {
    let observations = Arc::new(Mutex::new(OrganObservationStateV1::default()));
    let wrapped = handlers
        .into_iter()
        .map(|inner| {
            Box::new(ReceiptRecordingOrganV1 {
                inner,
                observations: Arc::clone(&observations),
            }) as Box<dyn TrustedReadOnlyOrganV1>
        })
        .collect();
    (wrapped, observations)
}

fn observation_state(
    observations: &OrganObservationLogV1,
) -> MutexGuard<'_, OrganObservationStateV1> {
    match observations.lock() {
        Ok(guard) => guard,
        Err(poisoned) => poisoned.into_inner(),
    }
}

fn begin_observation(observations: &OrganObservationLogV1) {
    let mut state = observation_state(observations);
    state.entries.clear();
    state.enabled = true;
}

fn finish_observation(observations: &OrganObservationLogV1) -> Vec<OrganHandlerObservationV1> {
    let mut state = observation_state(observations);
    state.enabled = false;
    std::mem::take(&mut state.entries)
}

fn cancel_observation(observations: &OrganObservationLogV1) {
    let mut state = observation_state(observations);
    state.enabled = false;
    state.entries.clear();
}

fn apply_observations(
    targets: &mut [OrganTargetDeliveryReceiptV1],
    observations: &[OrganHandlerObservationV1],
) {
    for (target, observation) in targets.iter_mut().zip(observations) {
        if target.target != observation.target || target.input_port != observation.input_port {
            continue;
        }
        match &observation.result {
            Ok(Some(output_digest)) => {
                target.disposition = OrganTargetDeliveryDispositionV1::Delivered;
                target.output_digest = Some(*output_digest);
                target.fault_code = None;
            }
            Ok(None) => {}
            Err(code) => {
                target.disposition = OrganTargetDeliveryDispositionV1::Failed;
                target.output_digest = None;
                target.fault_code = Some(code.clone());
            }
        }
    }
}

fn mark_unrecorded_delivered_prefix(
    targets: &mut [OrganTargetDeliveryReceiptV1],
    delivered: usize,
) {
    for target in targets.iter_mut().take(delivered) {
        if target.disposition == OrganTargetDeliveryDispositionV1::NotAttempted {
            target.disposition = OrganTargetDeliveryDispositionV1::DeliveredOutputUnavailable;
        }
    }
}

fn route_map(graph: &OrganGraphsV1) -> BTreeMap<(StableId, usize), Vec<(StableId, usize)>> {
    let mut routes: BTreeMap<_, Vec<_>> = BTreeMap::new();
    for link in &graph.runtime {
        let (Some(source), Some(target)) = (
            graph.organs.get(link.output.organ),
            graph.organs.get(link.input.organ),
        ) else {
            // The canonical core returns the typed graph-validation error. This
            // projection must not panic before that validator runs.
            continue;
        };
        routes
            .entry((source.id.clone(), link.output.port))
            .or_default()
            .push((target.id.clone(), link.input.port));
    }
    routes
}

#[cfg(test)]
#[path = "organ_runtime_tests.rs"]
mod tests;
