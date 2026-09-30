use std::collections::BTreeSet;
use std::fmt::Debug;

use codex_hepta_control_plane::DataflowTiming;
use codex_hepta_control_plane::FailureDomainV1;
use codex_hepta_control_plane::FallbackTerminal;
use codex_hepta_control_plane::InputPort;
use codex_hepta_control_plane::OrganEdge;
use codex_hepta_control_plane::OrganFanoutRecoveryErrorV1;
use codex_hepta_control_plane::OrganGraphsV1;
use codex_hepta_control_plane::OrganHandlerFaultV1;
use codex_hepta_control_plane::OrganHostV1;
use codex_hepta_control_plane::OrganNodeV1;
use codex_hepta_control_plane::OrganRole;
use codex_hepta_control_plane::OrganRuntimeError;
use codex_hepta_control_plane::OrganTargetDeliveryDispositionV1;
use codex_hepta_control_plane::OutputPort;
use codex_hepta_control_plane::RuntimeLinkV1;
use codex_hepta_control_plane::TrustedReadOnlyOrganV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

fn must<T, E: Debug>(result: Result<T, E>) -> T {
    match result {
        Ok(value) => value,
        Err(error) => panic!("unexpected fixture error: {error:?}"),
    }
}

fn id(value: &str) -> StableId {
    must(StableId::new(value))
}

fn generation(value: u64) -> Generation {
    must(Generation::new(value))
}

fn graph() -> OrganGraphsV1 {
    let port = id("message.v1");
    OrganGraphsV1 {
        generation: generation(7),
        organs: vec![
            OrganNodeV1 {
                id: id("source"),
                owner: id("owner"),
                role: OrganRole::Other,
                inputs: vec![],
                outputs: vec![port.clone()],
                effect_scope: BTreeSet::new(),
                terminal: FallbackTerminal::None,
            },
            OrganNodeV1 {
                id: id("target.a"),
                owner: id("owner"),
                role: OrganRole::Other,
                inputs: vec![port.clone()],
                outputs: vec![],
                effect_scope: BTreeSet::new(),
                terminal: FallbackTerminal::None,
            },
            OrganNodeV1 {
                id: id("target.b"),
                owner: id("owner"),
                role: OrganRole::Other,
                inputs: vec![port],
                outputs: vec![],
                effect_scope: BTreeSet::new(),
                terminal: FallbackTerminal::SafeState(Digest32::of_bytes(b"safe")),
            },
        ],
        initialization: vec![OrganEdge { from: 0, to: 1 }, OrganEdge { from: 1, to: 2 }],
        runtime: vec![
            RuntimeLinkV1 {
                output: OutputPort { organ: 0, port: 0 },
                input: InputPort { organ: 1, port: 0 },
                timing: DataflowTiming::Buffered,
            },
            RuntimeLinkV1 {
                output: OutputPort { organ: 0, port: 0 },
                input: InputPort { organ: 2, port: 0 },
                timing: DataflowTiming::Buffered,
            },
        ],
        feedback: vec![],
        fallback: vec![OrganEdge { from: 0, to: 2 }, OrganEdge { from: 1, to: 2 }],
        failure_domains: (0..3)
            .map(|organ| FailureDomainV1 {
                organ,
                process: id(&format!("process.{organ}")),
                host: id("host"),
            })
            .collect(),
    }
}

#[derive(Debug)]
struct FixtureOrgan {
    id: StableId,
    output: Vec<u8>,
    fail: bool,
}

impl TrustedReadOnlyOrganV1 for FixtureOrgan {
    fn id(&self) -> &StableId {
        &self.id
    }

    fn start(&mut self) -> Result<(), OrganHandlerFaultV1> {
        Ok(())
    }

    fn handle(
        &mut self,
        _input_port: usize,
        _payload: &[u8],
    ) -> Result<Vec<u8>, OrganHandlerFaultV1> {
        if self.fail {
            Err(OrganHandlerFaultV1::new(id("handle.failed")))
        } else {
            Ok(self.output.clone())
        }
    }

    fn stop(&mut self) -> Result<(), OrganHandlerFaultV1> {
        Ok(())
    }
}

fn handler(name: &str, output: &[u8], fail: bool) -> Box<dyn TrustedReadOnlyOrganV1> {
    Box::new(FixtureOrgan {
        id: id(name),
        output: output.to_vec(),
        fail,
    })
}

#[test]
fn failed_fanout_preserves_the_exact_successful_prefix_digest() {
    let handlers = vec![
        handler("source", b"source-unused", false),
        handler("target.a", b"target-a-output", false),
        handler("target.b", b"target-b-output", true),
    ];
    let mut host = OrganHostV1::new(graph(), handlers).expect("valid host");
    host.start_all().expect("start host");

    let receipt = host.dispatch_once_with_receipt(generation(7), &id("source"), 0, b"request");

    assert!(matches!(
        receipt.error,
        Some(OrganRuntimeError::HandleFailed { delivered: 1, .. })
    ));
    assert_eq!(receipt.targets.len(), 2);
    assert_eq!(receipt.targets[0].target, id("target.a"));
    assert_eq!(
        receipt.targets[0].disposition,
        OrganTargetDeliveryDispositionV1::Delivered
    );
    assert_eq!(
        receipt.targets[0].output_digest,
        Some(Digest32::of_bytes(b"target-a-output"))
    );
    assert_eq!(receipt.targets[0].fault_code, None);

    assert_eq!(receipt.targets[1].target, id("target.b"));
    assert_eq!(
        receipt.targets[1].disposition,
        OrganTargetDeliveryDispositionV1::Failed
    );
    assert_eq!(receipt.targets[1].output_digest, None);
    assert_eq!(receipt.targets[1].fault_code, Some(id("handle.failed")));
    assert!(!receipt.authority.grants_any());

    let evidence_digest = receipt.evidence_digest().expect("canonical evidence");
    let continuation = receipt
        .continuation(evidence_digest)
        .expect("receipt integrity")
        .expect("failed target continuation");
    assert_eq!(continuation.receipt_evidence_digest, evidence_digest);
    assert_eq!(continuation.next_route_index, 1);
    assert_eq!(continuation.next_target, id("target.b"));
    assert_eq!(continuation.next_input_port, 0);
    assert!(!continuation.authority.grants_any());

    let mut tampered = receipt.clone();
    tampered.targets[0].output_digest = Some(Digest32::of_bytes(b"tampered"));
    assert_eq!(
        tampered.continuation(evidence_digest),
        Err(OrganFanoutRecoveryErrorV1::ReceiptEvidenceMismatch),
    );

    let mut wrong_failure_boundary = receipt.clone();
    if let Some(OrganRuntimeError::HandleFailed { delivered, .. }) =
        wrong_failure_boundary.error.as_mut()
    {
        *delivered = 0;
    } else {
        panic!("fixture must retain the handler failure");
    }
    let wrong_failure_digest = wrong_failure_boundary
        .evidence_digest()
        .expect("canonical tampered evidence");
    assert_eq!(
        wrong_failure_boundary.continuation(wrong_failure_digest),
        Err(OrganFanoutRecoveryErrorV1::ErrorDispositionMismatch),
    );

    let mut incomplete_delivered = receipt;
    incomplete_delivered.targets[0].disposition =
        OrganTargetDeliveryDispositionV1::DeliveredOutputUnavailable;
    incomplete_delivered.targets[0].output_digest = None;
    let incomplete_digest = incomplete_delivered
        .evidence_digest()
        .expect("canonical incomplete evidence");
    assert_eq!(
        incomplete_delivered.continuation(incomplete_digest),
        Err(OrganFanoutRecoveryErrorV1::IncompleteDeliveredEvidence { route_index: 0 }),
    );
}
