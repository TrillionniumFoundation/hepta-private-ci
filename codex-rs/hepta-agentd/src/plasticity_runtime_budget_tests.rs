//! Saturate the real owner channel before polling its receiver. This checks
//! refusal through AgentdState without scheduling a trainer or proposal writer.

use std::future::Future;
use std::pin::Pin;
use std::task::Context;
use std::task::Poll;
use std::task::Waker;

use pretty_assertions::assert_eq;

use super::*;
use crate::PlasticityRuntimeCallErrorV1;
use crate::plasticity_runtime::PlasticityRuntimeCommandV1;

fn poll_once<F: Future>(future: Pin<&mut F>) -> Poll<F::Output> {
    future.poll(&mut Context::from_waker(Waker::noop()))
}

#[test]
fn saturated_proposal_queue_refuses_both_callers_without_waiting_or_owner_mutation() {
    let daemon = AgentdFixture::new();
    let root = tempfile::tempdir().expect("private owner fixtures");
    let files = runtime_files(root.path());
    let mut ledger = DurableLedger::create(new_file(&files.ledger), digest("ledger:binding"), /*max_records*/ 32)
        .expect("durable learning owner");
    ledger.append_qualification(Digest32::ZERO, ledger_decision(digest("plasticity-objective")))
        .expect("fixed owner evidence");
    let sources = build_owner_sources(root.path(), &ledger, digest("plasticity-objective"), digest("selected-artifact:lifetime"));
    let signing = SigningFixture::new();
    let verifier = signing.verifier(sources.objective_digest);
    let parameter = signed_request(&sources, &ledger, &signing, &verifier);
    let topology = signed_topology_request(&sources, &ledger, &signing, &verifier);
    let (parameter_writer, parameter_anchor) = bootstrap_agentd_plasticity_writer_v1(
        new_file(&files.parameter_registry), new_file(&files.parameter_anchor), digest("parameter-registry:scope"), /*maximum_records*/ 32,
    ).expect("parameter writer");
    let (topology_writer, topology_anchor) = bootstrap_agentd_topology_writer_v1(
        new_file(&files.topology_registry), new_file(&files.topology_anchor), digest("topology-registry:scope"), /*maximum_records*/ 32,
    ).expect("topology writer");
    let bootstrap = PlasticityRuntimeBootstrapV1::new(
        /*capacity*/ 1, sources.artifacts.clone(), ledger, Box::new(resolver(&sources)),
        sources.owner_policy.clone(), verifier, parameter_writer, parameter_anchor, topology_writer, topology_anchor,
    ).expect("one-slot owner");
    let state = daemon.state();
    let mut owner = crate::plasticity_runtime::compose_plasticity_runtime_v1(&state, Some(bootstrap))
        .expect("actual Agentd composition").expect("opt-in owner");
    let owner_heads = |owner: &crate::PlasticityRuntimeOwnerV1| {
        (
            owner.ledger.snapshot().expect("learning head").head_digest,
            owner.artifacts.snapshot().head_digest,
            owner.parameter_writer.current_anchor().expect("parameter registry head"),
            owner.parameter_anchor_store.anchor(), owner.parameter_anchor_store.fence(),
            owner.topology_writer.current_anchor().expect("topology registry head"),
            owner.topology_anchor_store.anchor(), owner.topology_anchor_store.fence(),
        )
    };
    let before = owner_heads(&owner);

    // Poll once: the first request is queued and waits only for its result.
    let mut first = Box::pin(state.submit_parameter_plasticity_v1(parameter.clone(), /*now*/ 50));
    assert!(poll_once(first.as_mut()).is_pending());
    assert_eq!(owner.receiver.len(), 1);
    let mut rejected_parameter = parameter.clone();
    rejected_parameter.proposal_id = id("proposal:queue-full-parameter");
    let mut rejected_topology = topology.clone();
    rejected_topology.proposal_id = id("proposal:queue-full-topology");
    let mut parameter_call = Box::pin(state.submit_parameter_plasticity_v1(rejected_parameter, /*now*/ 50));
    let mut topology_call = Box::pin(state.submit_topology_plasticity_v1(rejected_topology, /*now*/ 50));
    assert!(matches!(poll_once(parameter_call.as_mut()), Poll::Ready(Err(PlasticityRuntimeCallErrorV1::QueueFull))));
    assert!(matches!(poll_once(topology_call.as_mut()), Poll::Ready(Err(PlasticityRuntimeCallErrorV1::QueueFull))));
    assert_eq!(owner.receiver.len(), 1);
    assert_eq!(owner_heads(&owner), before);
    assert_eq!(owner.parameter_writer.record_count().expect("proposal count"), 0);
    assert_eq!(owner.topology_writer.current_anchor().expect("topology head"), None);

    match owner.receiver.try_recv().expect("only original request survived") {
        PlasticityRuntimeCommandV1::Parameter { request, now, response } => {
            assert_eq!((*request, now), (parameter.clone(), 50));
            response.send(Err(PlasticityRuntimeCallErrorV1::Unavailable)).expect("original response channel");
        }
        PlasticityRuntimeCommandV1::Topology { .. } => panic!("rejected topology must not replace queued work"),
    }
    assert!(matches!(poll_once(first.as_mut()), Poll::Ready(Err(PlasticityRuntimeCallErrorV1::Unavailable))));
    assert!(matches!(owner.receiver.try_recv(), Err(tokio::sync::mpsc::error::TryRecvError::Empty)));

    // Freed capacity accepts a new explicit submission, never an implicit retry
    // of either rejected request or a new identity generated by the queue.
    let mut next = Box::pin(state.submit_topology_plasticity_v1(topology.clone(), /*now*/ 50));
    assert!(poll_once(next.as_mut()).is_pending());
    match owner.receiver.try_recv().expect("explicit topology submission") {
        PlasticityRuntimeCommandV1::Topology { request, now, response } => {
            assert_eq!((*request, now), (topology.clone(), 50));
            response.send(Err(PlasticityRuntimeCallErrorV1::Unavailable)).expect("topology response channel");
        }
        PlasticityRuntimeCommandV1::Parameter { .. } => panic!("rejected parameter must not become a waiter"),
    }
    assert!(matches!(poll_once(next.as_mut()), Poll::Ready(Err(PlasticityRuntimeCallErrorV1::Unavailable))));
    assert_eq!(owner_heads(&owner), before);
    drop(owner);
    let mut closed_parameter = Box::pin(state.submit_parameter_plasticity_v1(parameter, /*now*/ 50));
    let mut closed_topology = Box::pin(state.submit_topology_plasticity_v1(topology, /*now*/ 50));
    assert!(matches!(poll_once(closed_parameter.as_mut()), Poll::Ready(Err(PlasticityRuntimeCallErrorV1::Closed))));
    assert!(matches!(poll_once(closed_topology.as_mut()), Poll::Ready(Err(PlasticityRuntimeCallErrorV1::Closed))));
}
