//! Receipt-preserving wrapper for the trusted in-process organ host.
//!
//! The lifecycle and one-hop handler implementation remains in
//! `organ_runtime_core.rs`. This wrapper retains the exact admitted route map so
//! every fanout attempt can return a complete per-target identity/status set,
//! including the successfully delivered prefix and targets not attempted after
//! a failure.

use std::collections::BTreeMap;

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
pub struct OrganHostV1 {
    inner: core::OrganHostV1,
    routes: BTreeMap<(StableId, usize), Vec<(StableId, usize)>>,
}

impl OrganHostV1 {
    pub fn new(
        graph: OrganGraphsV1,
        handlers: Vec<Box<dyn TrustedReadOnlyOrganV1>>,
    ) -> Result<Self, OrganRuntimeError> {
        let routes = route_map(&graph);
        let inner = core::OrganHostV1::new(graph, handlers)?;
        Ok(Self { inner, routes })
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
        self.inner
            .replace_read_only_generation(expected, graph, handlers)?;
        self.routes = routes;
        Ok(())
    }

    pub(crate) fn replace_admitted_read_only_generation(
        &mut self,
        expected: Generation,
        candidate: Self,
    ) -> Result<(), OrganRuntimeError> {
        let Self { inner, routes } = candidate;
        self.inner
            .replace_admitted_read_only_generation(expected, inner)?;
        self.routes = routes;
        Ok(())
    }

    pub(crate) fn recover_admitted_read_only_generation(
        &mut self,
        expected: Generation,
        candidate: Self,
    ) -> Result<(), OrganRuntimeError> {
        let Self { inner, routes } = candidate;
        self.inner
            .recover_admitted_read_only_generation(expected, inner)?;
        self.routes = routes;
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
        self.inner.replace_read_only_generation_with_migration(
            expected,
            graph,
            handlers,
            migration,
        )?;
        self.routes = routes;
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
        let Self { inner, routes } = candidate;
        self.inner
            .replace_admitted_read_only_generation_with_migration(
                expected,
                inner,
                migration,
            )?;
        self.routes = routes;
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
        let Self { inner, routes } = candidate;
        self.inner
            .recover_admitted_read_only_generation_with_migration(
                expected,
                inner,
                migration,
            )?;
        self.routes = routes;
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
        self.inner
            .dispatch_once(generation, source, output_port, payload)
    }

    /// Execute one bounded fanout and preserve an identity/status slot for
    /// every admitted target, even when a later target fails.
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

        let error = match self
            .inner
            .dispatch_once(generation, source, output_port, payload)
        {
            Ok(deliveries) => {
                for (target, delivery) in targets.iter_mut().zip(deliveries) {
                    target.disposition = OrganTargetDeliveryDispositionV1::Delivered;
                    target.output_digest = Some(Digest32::of_bytes(&delivery.output));
                }
                None
            }
            Err(error) => {
                match &error {
                    OrganRuntimeError::HandleFailed { fault, delivered } => {
                        mark_delivered_prefix(&mut targets, *delivered);
                        if let Some(target) = targets.get_mut(*delivered) {
                            target.disposition = OrganTargetDeliveryDispositionV1::Failed;
                            target.fault_code = Some(fault.code.clone());
                        }
                    }
                    OrganRuntimeError::OutputTooLarge {
                        organ, delivered, ..
                    } => {
                        mark_delivered_prefix(&mut targets, *delivered);
                        if let Some(target) = targets
                            .iter_mut()
                            .find(|target| &target.target == organ)
                        {
                            target.disposition = OrganTargetDeliveryDispositionV1::Failed;
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

fn mark_delivered_prefix(targets: &mut [OrganTargetDeliveryReceiptV1], delivered: usize) {
    for target in targets.iter_mut().take(delivered) {
        target.disposition = OrganTargetDeliveryDispositionV1::DeliveredOutputUnavailable;
    }
}

fn route_map(
    graph: &OrganGraphsV1,
) -> BTreeMap<(StableId, usize), Vec<(StableId, usize)>> {
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
