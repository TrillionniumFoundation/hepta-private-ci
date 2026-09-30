use std::collections::BTreeMap;
use std::error::Error as StdError;
use std::fmt;
use std::panic::AssertUnwindSafe;
use std::panic::catch_unwind;
use std::time::Instant;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use crate::DataflowTiming;
use crate::OrganGraphsV1;
use crate::OrganHostV1;
use crate::OrganRuntimeError;
use crate::TrustedReadOnlyOrganV1;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct OrganDispatchBudgetV1 {
    pub max_targets: usize,
    pub max_single_output_bytes: usize,
    pub max_aggregate_output_bytes: usize,
    pub max_dispatch_micros: u64,
}

impl OrganDispatchBudgetV1 {
    pub fn validate(&self) -> Result<(), ProductionOrganAdmissionErrorV1> {
        if self.max_targets == 0
            || self.max_single_output_bytes == 0
            || self.max_aggregate_output_bytes == 0
            || self.max_dispatch_micros == 0
            || self.max_aggregate_output_bytes < self.max_single_output_bytes
        {
            return Err(ProductionOrganAdmissionErrorV1::InvalidBudget);
        }
        Ok(())
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ProductionOrganAdmissionErrorV1 {
    InvalidBudget,
    FeedbackSchedulerUnavailable,
    BufferedSchedulerUnavailable,
    FanoutExceedsBudget,
}

impl fmt::Display for ProductionOrganAdmissionErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for ProductionOrganAdmissionErrorV1 {}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum OrganTargetDispositionV1 {
    Delivered,
    DeliveredOutputUnavailable,
    HandlerFailed,
    OutputTooLarge,
    NotAttempted,
    UnknownAfterPanic,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct OrganTargetReceiptV1 {
    pub target: StableId,
    pub input_port: usize,
    pub disposition: OrganTargetDispositionV1,
    pub output_digest: Option<Digest32>,
    pub output_bytes: usize,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum OrganDispatchTerminalV1 {
    Completed,
    RuntimeFailure,
    PanicContained,
    DeadlineExceededAfterReturn,
    SingleOutputBudgetExceeded,
    AggregateOutputBudgetExceeded,
    HostPoisoned,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct OrganDispatchReceiptV1 {
    pub generation: Generation,
    pub source: StableId,
    pub output_port: usize,
    pub payload_digest: Digest32,
    pub elapsed_micros: u64,
    pub terminal: OrganDispatchTerminalV1,
    pub targets: Vec<OrganTargetReceiptV1>,
    pub runtime_error: Option<OrganRuntimeError>,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ProductionOrganHostErrorV1 {
    Admission(ProductionOrganAdmissionErrorV1),
    Runtime(OrganRuntimeError),
}

impl fmt::Display for ProductionOrganHostErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for ProductionOrganHostErrorV1 {}

impl From<OrganRuntimeError> for ProductionOrganHostErrorV1 {
    fn from(error: OrganRuntimeError) -> Self {
        Self::Runtime(error)
    }
}

pub struct ProductionOrganHostV1 {
    host: OrganHostV1,
    budget: OrganDispatchBudgetV1,
    routes: BTreeMap<(StableId, usize), Vec<(StableId, usize)>>,
    poisoned: bool,
}

impl ProductionOrganHostV1 {
    pub fn admit(
        graph: OrganGraphsV1,
        handlers: Vec<Box<dyn TrustedReadOnlyOrganV1>>,
        budget: OrganDispatchBudgetV1,
    ) -> Result<Self, ProductionOrganHostErrorV1> {
        budget
            .validate()
            .map_err(ProductionOrganHostErrorV1::Admission)?;
        if !graph.feedback.is_empty() {
            return Err(ProductionOrganHostErrorV1::Admission(
                ProductionOrganAdmissionErrorV1::FeedbackSchedulerUnavailable,
            ));
        }
        if graph
            .runtime
            .iter()
            .any(|link| link.timing == DataflowTiming::Buffered)
        {
            return Err(ProductionOrganHostErrorV1::Admission(
                ProductionOrganAdmissionErrorV1::BufferedSchedulerUnavailable,
            ));
        }

        let mut routes: BTreeMap<(StableId, usize), Vec<(StableId, usize)>> = BTreeMap::new();
        for link in &graph.runtime {
            let source = graph.organs[link.output.organ].id.clone();
            let target = graph.organs[link.input.organ].id.clone();
            routes
                .entry((source, link.output.port))
                .or_default()
                .push((target, link.input.port));
        }
        if routes.values().any(|targets| targets.len() > budget.max_targets) {
            return Err(ProductionOrganHostErrorV1::Admission(
                ProductionOrganAdmissionErrorV1::FanoutExceedsBudget,
            ));
        }
        let host = OrganHostV1::new(graph, handlers)?;
        Ok(Self {
            host,
            budget,
            routes,
            poisoned: false,
        })
    }

    #[must_use]
    pub fn generation(&self) -> Generation {
        self.host.generation()
    }

    pub fn start_all(&mut self) -> Result<(), ProductionOrganHostErrorV1> {
        Ok(self.host.start_all()?)
    }

    pub fn stop_all(&mut self) -> Result<(), ProductionOrganHostErrorV1> {
        Ok(self.host.stop_all()?)
    }

    pub fn dispatch_once(
        &mut self,
        generation: Generation,
        source: &StableId,
        output_port: usize,
        payload: &[u8],
    ) -> OrganDispatchReceiptV1 {
        let route_template = self
            .routes
            .get(&(source.clone(), output_port))
            .cloned()
            .unwrap_or_default();
        if self.poisoned {
            return receipt(
                generation,
                source,
                output_port,
                payload,
                0,
                OrganDispatchTerminalV1::HostPoisoned,
                not_attempted_targets(&route_template),
                None,
            );
        }

        let started = Instant::now();
        let result = catch_unwind(AssertUnwindSafe(|| {
            self.host
                .dispatch_once(generation, source, output_port, payload)
        }));
        let elapsed_micros = u64::try_from(started.elapsed().as_micros()).unwrap_or(u64::MAX);

        let Ok(result) = result else {
            self.poisoned = true;
            return receipt(
                generation,
                source,
                output_port,
                payload,
                elapsed_micros,
                OrganDispatchTerminalV1::PanicContained,
                route_template
                    .iter()
                    .map(|(target, input_port)| OrganTargetReceiptV1 {
                        target: target.clone(),
                        input_port: *input_port,
                        disposition: OrganTargetDispositionV1::UnknownAfterPanic,
                        output_digest: None,
                        output_bytes: 0,
                    })
                    .collect(),
                None,
            );
        };

        match result {
            Ok(deliveries) => {
                let mut targets = Vec::with_capacity(deliveries.len());
                let mut aggregate = 0_usize;
                let mut single_output_exceeded = false;
                for delivery in deliveries {
                    single_output_exceeded |=
                        delivery.output.len() > self.budget.max_single_output_bytes;
                    aggregate = aggregate.saturating_add(delivery.output.len());
                    targets.push(OrganTargetReceiptV1 {
                        target: delivery.target,
                        input_port: delivery.input_port,
                        disposition: OrganTargetDispositionV1::Delivered,
                        output_digest: Some(Digest32::of_bytes(&delivery.output)),
                        output_bytes: delivery.output.len(),
                    });
                }
                let terminal = if elapsed_micros >= self.budget.max_dispatch_micros {
                    self.poisoned = true;
                    OrganDispatchTerminalV1::DeadlineExceededAfterReturn
                } else if single_output_exceeded {
                    self.poisoned = true;
                    OrganDispatchTerminalV1::SingleOutputBudgetExceeded
                } else if aggregate > self.budget.max_aggregate_output_bytes {
                    self.poisoned = true;
                    OrganDispatchTerminalV1::AggregateOutputBudgetExceeded
                } else {
                    OrganDispatchTerminalV1::Completed
                };
                receipt(
                    generation,
                    source,
                    output_port,
                    payload,
                    elapsed_micros,
                    terminal,
                    targets,
                    None,
                )
            }
            Err(error) => {
                let targets = targets_for_runtime_error(&route_template, &error);
                receipt(
                    generation,
                    source,
                    output_port,
                    payload,
                    elapsed_micros,
                    OrganDispatchTerminalV1::RuntimeFailure,
                    targets,
                    Some(error),
                )
            }
        }
    }
}

fn targets_for_runtime_error(
    route_template: &[(StableId, usize)],
    error: &OrganRuntimeError,
) -> Vec<OrganTargetReceiptV1> {
    let (delivered, failed_organ, failed_disposition) = match error {
        OrganRuntimeError::HandleFailed { fault, delivered } => (
            *delivered,
            Some(&fault.organ),
            OrganTargetDispositionV1::HandlerFailed,
        ),
        OrganRuntimeError::OutputTooLarge {
            organ, delivered, ..
        } => (
            *delivered,
            Some(organ),
            OrganTargetDispositionV1::OutputTooLarge,
        ),
        _ => (0, None, OrganTargetDispositionV1::NotAttempted),
    };
    route_template
        .iter()
        .enumerate()
        .map(|(index, (target, input_port))| {
            let disposition = if index < delivered {
                OrganTargetDispositionV1::DeliveredOutputUnavailable
            } else if failed_organ == Some(target) {
                failed_disposition
            } else {
                OrganTargetDispositionV1::NotAttempted
            };
            OrganTargetReceiptV1 {
                target: target.clone(),
                input_port: *input_port,
                disposition,
                output_digest: None,
                output_bytes: 0,
            }
        })
        .collect()
}

fn not_attempted_targets(
    route_template: &[(StableId, usize)],
) -> Vec<OrganTargetReceiptV1> {
    route_template
        .iter()
        .map(|(target, input_port)| OrganTargetReceiptV1 {
            target: target.clone(),
            input_port: *input_port,
            disposition: OrganTargetDispositionV1::NotAttempted,
            output_digest: None,
            output_bytes: 0,
        })
        .collect()
}

#[allow(clippy::too_many_arguments)]
fn receipt(
    generation: Generation,
    source: &StableId,
    output_port: usize,
    payload: &[u8],
    elapsed_micros: u64,
    terminal: OrganDispatchTerminalV1,
    targets: Vec<OrganTargetReceiptV1>,
    runtime_error: Option<OrganRuntimeError>,
) -> OrganDispatchReceiptV1 {
    OrganDispatchReceiptV1 {
        generation,
        source: source.clone(),
        output_port,
        payload_digest: Digest32::of_bytes(payload),
        elapsed_micros,
        terminal,
        targets,
        runtime_error,
        authority: AuthorityPosture::DENY_ALL,
    }
}

#[cfg(test)]
mod tests {
    use std::collections::BTreeSet;

    use super::*;
    use crate::FailureDomainV1;
    use crate::FallbackTerminal;
    use crate::InputPort;
    use crate::OrganEdge;
    use crate::OrganHandlerFaultV1;
    use crate::OrganNodeV1;
    use crate::OrganRole;
    use crate::OutputPort;
    use crate::RuntimeLinkV1;

    #[derive(Debug)]
    struct Handler {
        id: StableId,
        panic_on_handle: bool,
    }

    impl TrustedReadOnlyOrganV1 for Handler {
        fn id(&self) -> &StableId {
            &self.id
        }

        fn start(&mut self) -> Result<(), OrganHandlerFaultV1> {
            Ok(())
        }

        fn handle(
            &mut self,
            _input_port: usize,
            payload: &[u8],
        ) -> Result<Vec<u8>, OrganHandlerFaultV1> {
            assert!(!self.panic_on_handle, "injected handler panic");
            Ok(payload.to_vec())
        }

        fn stop(&mut self) -> Result<(), OrganHandlerFaultV1> {
            Ok(())
        }
    }

    fn id(value: &str) -> StableId {
        StableId::new(value).expect("id")
    }

    fn graph(timing: DataflowTiming) -> OrganGraphsV1 {
        OrganGraphsV1 {
            generation: Generation::new(1).expect("generation"),
            organs: vec![
                OrganNodeV1 {
                    id: id("source"),
                    owner: id("owner"),
                    role: OrganRole::Other,
                    inputs: Vec::new(),
                    outputs: vec![id("message")],
                    effect_scope: BTreeSet::new(),
                    terminal: FallbackTerminal::None,
                },
                OrganNodeV1 {
                    id: id("target"),
                    owner: id("owner"),
                    role: OrganRole::Other,
                    inputs: vec![id("message")],
                    outputs: Vec::new(),
                    effect_scope: BTreeSet::new(),
                    terminal: FallbackTerminal::SafeState(Digest32::of_bytes(b"safe")),
                },
            ],
            initialization: vec![OrganEdge { from: 0, to: 1 }],
            runtime: vec![RuntimeLinkV1 {
                output: OutputPort { organ: 0, port: 0 },
                input: InputPort { organ: 1, port: 0 },
                timing,
            }],
            feedback: Vec::new(),
            fallback: vec![OrganEdge { from: 0, to: 1 }],
            failure_domains: vec![
                FailureDomainV1 {
                    organ: 0,
                    process: id("process-source"),
                    host: id("host-source"),
                },
                FailureDomainV1 {
                    organ: 1,
                    process: id("process-target"),
                    host: id("host-target"),
                },
            ],
        }
    }

    fn handlers(panic_on_target: bool) -> Vec<Box<dyn TrustedReadOnlyOrganV1>> {
        vec![
            Box::new(Handler {
                id: id("source"),
                panic_on_handle: false,
            }),
            Box::new(Handler {
                id: id("target"),
                panic_on_handle: panic_on_target,
            }),
        ]
    }

    fn budget() -> OrganDispatchBudgetV1 {
        OrganDispatchBudgetV1 {
            max_targets: 4,
            max_single_output_bytes: 1024,
            max_aggregate_output_bytes: 4096,
            max_dispatch_micros: 1_000_000,
        }
    }

    #[test]
    fn production_admission_rejects_unimplemented_buffering() {
        assert!(matches!(
            ProductionOrganHostV1::admit(
                graph(DataflowTiming::Buffered),
                handlers(false),
                budget(),
            ),
            Err(ProductionOrganHostErrorV1::Admission(
                ProductionOrganAdmissionErrorV1::BufferedSchedulerUnavailable
            ))
        ));
    }

    #[test]
    fn panic_is_contained_and_poisoned_host_does_not_retry() {
        let mut host = ProductionOrganHostV1::admit(
            graph(DataflowTiming::Synchronous),
            handlers(true),
            budget(),
        )
        .expect("admit");
        host.start_all().expect("start");
        let first = host.dispatch_once(host.generation(), &id("source"), 0, b"message");
        assert_eq!(first.terminal, OrganDispatchTerminalV1::PanicContained);
        assert_eq!(
            first.targets[0].disposition,
            OrganTargetDispositionV1::UnknownAfterPanic
        );
        let second = host.dispatch_once(host.generation(), &id("source"), 0, b"message");
        assert_eq!(second.terminal, OrganDispatchTerminalV1::HostPoisoned);
    }

    #[test]
    fn successful_dispatch_has_per_target_receipts() {
        let mut host = ProductionOrganHostV1::admit(
            graph(DataflowTiming::Synchronous),
            handlers(false),
            budget(),
        )
        .expect("admit");
        host.start_all().expect("start");
        let receipt = host.dispatch_once(host.generation(), &id("source"), 0, b"message");
        assert_eq!(receipt.terminal, OrganDispatchTerminalV1::Completed);
        assert_eq!(receipt.targets.len(), 1);
        assert_eq!(
            receipt.targets[0].disposition,
            OrganTargetDispositionV1::Delivered
        );
        assert_eq!(receipt.targets[0].output_bytes, 7);
    }
}
