use std::sync::Arc;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;

use pretty_assertions::assert_eq;

use super::*;
use crate::DataflowTiming;
use crate::FailureDomainV1;
use crate::FallbackTerminal;
use crate::FeedbackProfileV1;
use crate::HostedOrganStateV1;
use crate::InputPort;
use crate::OrganDeliveryV1;
use crate::OrganHandlerFaultV1;
use crate::OrganNodeV1;
use crate::OutputPort;
use crate::RuntimeLinkV1;
use codex_hepta_types::AuthorityPosture;

fn id(value: &str) -> StableId {
    StableId::new(value).unwrap_or_else(|error| panic!("valid fixture identity: {error:?}"))
}

fn generation(value: u64) -> Generation {
    Generation::new(value).unwrap_or_else(|error| panic!("valid fixture generation: {error:?}"))
}

fn fixture() -> (BodyGraphBindingV1, OrganGraphsV1) {
    let evidence = Digest32::of_bytes(b"fixture evidence; no physical qualification");
    let graph = OrganGraphsV1 {
        generation: generation(/*value*/ 7),
        organs: (0..3)
            .map(|i| OrganNodeV1 {
                id: id(&format!("organ:{i}")),
                owner: id("owner"),
                role: OrganRole::Other,
                inputs: if i < 2 {
                    vec![id("message.v1")]
                } else {
                    vec![]
                },
                outputs: vec![id("message.v1")],
                effect_scope: BTreeSet::new(),
                terminal: if i == 2 {
                    FallbackTerminal::SafeState(evidence)
                } else {
                    FallbackTerminal::None
                },
            })
            .collect(),
        initialization: vec![OrganEdge { from: 0, to: 1 }],
        runtime: vec![
            RuntimeLinkV1 {
                output: OutputPort { organ: 0, port: 0 },
                input: InputPort { organ: 1, port: 0 },
                timing: DataflowTiming::Buffered,
            },
            RuntimeLinkV1 {
                output: OutputPort { organ: 1, port: 0 },
                input: InputPort { organ: 0, port: 0 },
                timing: DataflowTiming::Synchronous,
            },
        ],
        feedback: vec![FeedbackProfileV1 {
            members: BTreeSet::from([0, 1]),
            reference_generation: generation(/*value*/ 7),
            period_ns: 10_000,
            delay_ns: 100,
            jitter_ns: 20,
            queue_capacity: 4,
            max_gain_q24: 4 << 24,
            saturation_q24: 2 << 24,
            gains_and_saturation: evidence,
            operating_region: evidence,
            stability_analysis: evidence,
            perturbation_tests: evidence,
            exit_organ: 2,
        }],
        fallback: vec![OrganEdge { from: 0, to: 2 }, OrganEdge { from: 1, to: 2 }],
        failure_domains: (0..3)
            .map(|organ| FailureDomainV1 {
                organ,
                process: id("process"),
                host: id("host"),
            })
            .collect(),
    };
    let body = BodyGraphBindingV1 {
        generation: graph.generation,
        organ_manifests: graph
            .organs
            .iter()
            .map(|node| OrganManifestBindingV1 {
                organ_id: node.id.clone(),
                manifest_digest: Digest32::of_bytes(node.id.as_str().as_bytes()),
                organ_class: node.role,
                input_ports: node.inputs.clone(),
                output_ports: node.outputs.clone(),
            })
            .collect(),
        dependency_edges: graph.initialization.clone(),
        fallback_edges: graph.fallback.clone(),
        topological_order: graph
            .validate()
            .unwrap_or_else(|error| panic!("valid graph: {error:?}"))
            .initialization_order,
        snapshot_digest: Digest32::of_bytes(b"trusted V1 canonical source snapshot"),
    };
    (body, graph)
}

fn admission(bytes: &[u8]) -> CompiledOrganAdmissionV2 {
    CompiledOrganAdmissionV2 {
        expected_digest: compiled_body_graph_digest_v2(bytes)
            .unwrap_or_else(|error| panic!("bounded fixture: {error:?}")),
        generation: generation(/*value*/ 7),
        process: id("process"),
        host: id("host"),
    }
}

#[derive(Debug)]
struct Echo {
    id: StableId,
    callbacks: Arc<AtomicUsize>,
}

impl TrustedReadOnlyOrganV1 for Echo {
    fn id(&self) -> &StableId {
        &self.id
    }
    fn start(&mut self) -> Result<(), OrganHandlerFaultV1> {
        self.callbacks.fetch_add(/*val*/ 1, Ordering::SeqCst);
        Ok(())
    }
    fn handle(&mut self, _: usize, payload: &[u8]) -> Result<Vec<u8>, OrganHandlerFaultV1> {
        self.callbacks.fetch_add(/*val*/ 1, Ordering::SeqCst);
        Ok(payload.to_ascii_uppercase())
    }
    fn stop(&mut self) -> Result<(), OrganHandlerFaultV1> {
        Ok(())
    }
}

fn handlers(
    body: &BodyGraphBindingV1,
    callbacks: &Arc<AtomicUsize>,
) -> Vec<CompiledOrganHandlerV2> {
    body.organ_manifests
        .iter()
        .map(|manifest| CompiledOrganHandlerV2 {
            manifest_digest: manifest.manifest_digest,
            handler: Box::new(Echo {
                id: manifest.organ_id.clone(),
                callbacks: callbacks.clone(),
            }),
        })
        .collect()
}

#[test]
fn complete_graph_round_trip_reaches_real_host_without_granting_authority() {
    let (body, graph) = fixture();
    let bytes = encode_compiled_body_graph_v2(&body, &graph)
        .unwrap_or_else(|error| panic!("encode: {error:?}"));
    let verified = decode_compiled_body_graph_v2(&bytes, &admission(&bytes))
        .unwrap_or_else(|error| panic!("decode: {error:?}"));
    assert_eq!(
        verified,
        VerifiedCompiledBodyGraphV2 {
            body: body.clone(),
            graph
        }
    );
    let callbacks = Arc::new(AtomicUsize::new(/*v*/ 0));
    let mut host = verified
        .into_host(handlers(&body, &callbacks))
        .unwrap_or_else(|error| panic!("host: {error:?}"));
    assert!(
        host.statuses()
            .iter()
            .all(|status| status.state == HostedOrganStateV1::Registered)
    );
    assert_eq!(callbacks.load(Ordering::SeqCst), 0);
    host.start_all()
        .unwrap_or_else(|error| panic!("start: {error:?}"));
    let deliveries = host
        .dispatch_once(
            generation(/*value*/ 7),
            &id("organ:0"),
            /*output_port*/ 0,
            b"ping",
        )
        .unwrap_or_else(|error| panic!("dispatch: {error:?}"));
    assert_eq!(
        deliveries,
        vec![OrganDeliveryV1 {
            source: id("organ:0"),
            target: id("organ:1"),
            input_port: 0,
            output: b"PING".to_vec(),
            authority: AuthorityPosture::DENY_ALL,
        }]
    );
    assert_eq!(callbacks.load(Ordering::SeqCst), 4);
}

#[test]
fn every_payload_byte_is_bound_to_independent_host_digest() {
    let (body, graph) = fixture();
    let bytes = encode_compiled_body_graph_v2(&body, &graph)
        .unwrap_or_else(|error| panic!("encode: {error:?}"));
    let trusted = admission(&bytes);
    for offset in 0..bytes.len() {
        let mut changed = bytes.clone();
        changed[offset] ^= 1;
        assert_eq!(
            decode_compiled_body_graph_v2(&changed, &trusted),
            Err(OrganWireError::Digest)
        );
    }
    let mut stale = trusted.clone();
    stale.generation = generation(/*value*/ 8);
    assert_eq!(
        decode_compiled_body_graph_v2(&bytes, &stale),
        Err(OrganWireError::Generation)
    );
    let mut absent = trusted;
    absent.expected_digest = Digest32::ZERO;
    assert_eq!(
        decode_compiled_body_graph_v2(&bytes, &absent),
        Err(OrganWireError::Digest)
    );
}

#[test]
fn trusted_digest_does_not_excuse_invalid_wire_shape_or_execution_profile() {
    let (body, graph) = fixture();
    let bytes = encode_compiled_body_graph_v2(&body, &graph)
        .unwrap_or_else(|error| panic!("encode: {error:?}"));
    for end in 0..bytes.len() {
        let prefix = &bytes[..end];
        assert!(decode_compiled_body_graph_v2(prefix, &admission(prefix)).is_err());
    }
    for (offset, value, error) in [
        (9, 1, OrganWireError::UnsupportedVersion),
        (10, 1, OrganWireError::UnsupportedExecutionProfile),
        (11, 1, OrganWireError::Authority),
    ] {
        let mut malformed = bytes.clone();
        malformed[offset] = value;
        assert_eq!(
            decode_compiled_body_graph_v2(&malformed, &admission(&malformed)),
            Err(error)
        );
    }
    let mut extended = bytes;
    extended.extend_from_slice(b"unknown-field");
    assert_eq!(
        decode_compiled_body_graph_v2(&extended, &admission(&extended)),
        Err(OrganWireError::Encoding)
    );
}

#[test]
fn hostile_lengths_fail_before_collection_or_string_allocation() {
    let (body, graph) = fixture();
    let bytes = encode_compiled_body_graph_v2(&body, &graph)
        .unwrap_or_else(|error| panic!("encode: {error:?}"));
    // Header 12 + generation 8 + source digest 32, then manifest count and ID length.
    for offset in [52, 54] {
        let mut malformed = bytes.clone();
        malformed[offset..offset + 2].copy_from_slice(&u16::MAX.to_be_bytes());
        assert_eq!(
            decode_compiled_body_graph_v2(&malformed, &admission(&malformed)),
            Err(OrganWireError::Bounds)
        );
    }
    let oversized = vec![0; MAX_COMPILED_BODY_GRAPH_BYTES + 1];
    assert_eq!(
        decode_compiled_body_graph_v2(&oversized, &admission(&bytes)),
        Err(OrganWireError::Bounds)
    );
}

#[test]
fn overlapping_v1_and_native_fields_must_agree_even_with_approved_digest() {
    let (body, graph) = fixture();
    let mut mutations = Vec::new();
    let mut changed = body.clone();
    changed.generation = generation(/*value*/ 8);
    mutations.push(changed);
    let mut changed = body.clone();
    changed.organ_manifests[0].organ_id = id("wrong");
    mutations.push(changed);
    let mut changed = body.clone();
    changed.organ_manifests[0].organ_class = OrganRole::Cognitive;
    mutations.push(changed);
    let mut changed = body.clone();
    changed.organ_manifests[0].input_ports[0] = id("wrong.port");
    mutations.push(changed);
    let mut changed = body.clone();
    changed.organ_manifests[0].output_ports.clear();
    mutations.push(changed);
    let mut changed = body.clone();
    changed.dependency_edges.clear();
    mutations.push(changed);
    let mut changed = body.clone();
    changed.fallback_edges.reverse();
    mutations.push(changed);
    let mut changed = body;
    changed.topological_order.swap(/*a*/ 0, /*b*/ 1);
    mutations.push(changed);
    for changed in mutations {
        // Bypass producer validation to model malicious wire with matching pin.
        let bytes = codec::encode(&changed, &graph)
            .unwrap_or_else(|error| panic!("bounded malformed fixture: {error:?}"));
        assert_eq!(
            decode_compiled_body_graph_v2(&bytes, &admission(&bytes)),
            Err(OrganWireError::Projection)
        );
    }
}

#[test]
fn native_feedback_ports_and_placement_cannot_be_inferred_or_forged() {
    let (body, graph) = fixture();
    let mut wrong_port = graph.clone();
    wrong_port.runtime[0].input.port = 31;
    let mut missing_feedback = graph.clone();
    missing_feedback.feedback.clear();
    let mut wrong_timing = graph.clone();
    wrong_timing.feedback[0].delay_ns = u64::MAX;
    let mut missing_domain = graph.clone();
    missing_domain.failure_domains.pop();
    for (changed, error) in [
        (wrong_port, OrganGraphError::PortMismatch),
        (missing_feedback, OrganGraphError::FeedbackProfile),
        (wrong_timing, OrganGraphError::FeedbackProfile),
        (missing_domain, OrganGraphError::Bounds),
    ] {
        let bytes = codec::encode(&body, &changed)
            .unwrap_or_else(|error| panic!("bounded malformed fixture: {error:?}"));
        assert_eq!(
            decode_compiled_body_graph_v2(&bytes, &admission(&bytes)),
            Err(OrganWireError::Graph(error))
        );
    }
    for domain in [id("remote.process"), id("another.process")] {
        let mut changed = graph.clone();
        changed.failure_domains[0].process = domain;
        let bytes = encode_compiled_body_graph_v2(&body, &changed)
            .unwrap_or_else(|error| panic!("structurally valid: {error:?}"));
        assert_eq!(
            decode_compiled_body_graph_v2(&bytes, &admission(&bytes)),
            Err(OrganWireError::Placement)
        );
    }
    let bytes = encode_compiled_body_graph_v2(&body, &graph)
        .unwrap_or_else(|error| panic!("encode: {error:?}"));
    let mut wrong_host = admission(&bytes);
    wrong_host.host = id("another.host");
    assert_eq!(
        decode_compiled_body_graph_v2(&bytes, &wrong_host),
        Err(OrganWireError::Placement)
    );
}

#[test]
fn compiled_catalog_must_match_manifests_before_any_callback() {
    let (body, graph) = fixture();
    let bytes = encode_compiled_body_graph_v2(&body, &graph)
        .unwrap_or_else(|error| panic!("encode: {error:?}"));
    let callbacks = Arc::new(AtomicUsize::new(/*v*/ 0));
    let mut wrong = handlers(&body, &callbacks);
    wrong[0].manifest_digest = Digest32::of_bytes(b"different compiled version");
    let verified = decode_compiled_body_graph_v2(&bytes, &admission(&bytes))
        .unwrap_or_else(|error| panic!("decode: {error:?}"));
    assert!(matches!(
        verified.into_host(wrong),
        Err(OrganWireError::HandlerManifest)
    ));
    let mut duplicate = handlers(&body, &callbacks);
    duplicate[0] = handlers(&body, &callbacks).remove(/*index*/ 1);
    let verified = decode_compiled_body_graph_v2(&bytes, &admission(&bytes))
        .unwrap_or_else(|error| panic!("decode: {error:?}"));
    assert!(matches!(
        verified.into_host(duplicate),
        Err(OrganWireError::Runtime(
            OrganRuntimeError::DuplicateHandler { .. }
        ))
    ));
    assert_eq!(callbacks.load(Ordering::SeqCst), 0);
}

#[test]
fn producer_rejects_positive_effect_scope_and_ambiguous_port_identities() {
    let (mut body, mut graph) = fixture();
    graph.organs[0].effect_scope.insert(id("effect"));
    assert_eq!(
        encode_compiled_body_graph_v2(&body, &graph),
        Err(OrganWireError::Authority)
    );
    graph.organs[0].effect_scope.clear();
    graph.organs[2].outputs.push(id("message.v1"));
    body.organ_manifests[2].output_ports = graph.organs[2].outputs.clone();
    assert_eq!(
        encode_compiled_body_graph_v2(&body, &graph),
        Err(OrganWireError::Projection)
    );
}

#[test]
fn registry_admission_is_required_before_native_handoff_host_construction()
-> Result<(), OrganWireError> {
    let (body, graph) = fixture();
    let bytes = encode_compiled_body_graph_v2(&body, &graph)
        .unwrap_or_else(|error| panic!("encode: {error:?}"));
    let host_admission = admission(&bytes);
    let registry = NativeHandoffProtocolRegistryV1::canonical()?;
    let protocol = NativeHandoffProtocolAdmissionV1::canonical()?;
    let (verified, receipt) =
        admit_compiled_body_graph_v2(&bytes, &host_admission, &protocol, &registry)
            .unwrap_or_else(|error| panic!("registry admission: {error:?}"));
    assert_eq!(receipt.protocol_id, registry.protocol_id().clone());
    assert_eq!(receipt.profile_id, registry.profile_id().clone());
    assert_eq!(receipt.profile_version, registry.profile_version());
    assert_eq!(receipt.schema_digest, registry.schema_digest());
    assert_eq!(
        receipt.payload_digest,
        compiled_body_graph_digest_v2(&bytes).unwrap()
    );
    assert_eq!(receipt.generation, generation(7));
    assert_eq!(receipt.authority, AuthorityPosture::DENY_ALL);
    let callbacks = Arc::new(AtomicUsize::new(0));
    let mut host = verified
        .into_host(handlers(&body, &callbacks))
        .unwrap_or_else(|error| panic!("host: {error:?}"));
    host.start_all()
        .unwrap_or_else(|error| panic!("start: {error:?}"));
    let deliveries = host
        .dispatch_once(generation(7), &id("organ:0"), 0, b"ping")
        .unwrap_or_else(|error| panic!("dispatch: {error:?}"));
    assert_eq!(deliveries[0].authority, AuthorityPosture::DENY_ALL);

    let mut wrong = protocol;
    wrong.profile_version = 1;
    assert_eq!(
        admit_compiled_body_graph_v2(&bytes, &host_admission, &wrong, &registry),
        Err(OrganWireError::ProtocolVersion)
    );
    Ok(())
}
