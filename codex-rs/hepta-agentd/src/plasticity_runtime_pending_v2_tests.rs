//! Composition guard against substituting an original legacy test owner for V2.
//! This fixture proves rejection, not admission or physical V2 execution.
use super::*;

#[test]
fn pending_startup_cannot_attach_to_a_daemon_without_the_real_held_v2_host() {
    let fixture = clock_fixture(|| Ok(50));
    assert!(fixture.state.neuron_runtime_v2.get().is_none());
    let before = persistent_bytes(&fixture.files);
    let owner = fixture.owner;
    let mut bootstrap = PlasticityRuntimeBootstrapV1::new(
        8,
        owner.artifacts,
        owner.ledger,
        owner.owner_evidence_resolver,
        owner.owner_evidence_policy,
        owner.verifier,
        owner.parameter_writer,
        owner.parameter_anchor_store,
        owner.topology_writer,
        owner.topology_anchor_store,
    )
    .expect("existing original native writer envelope");
    bootstrap.requires_neuron_v2 = true;
    let result =
        crate::plasticity_runtime::compose_plasticity_runtime_v1(&fixture.state, Some(bootstrap));
    assert!(matches!(result, Err(AgentdError::Invalid(_))));
    assert_eq!(persistent_bytes(&fixture.files), before);
    assert!(fixture.state.neuron_runtime_v2.get().is_none());
}
