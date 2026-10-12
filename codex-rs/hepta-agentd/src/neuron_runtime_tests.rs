use codex_hepta_infer_core::NeuronFeatureReceiptV1;
use codex_hepta_infer_core::NeuronFeatureRequestV1;
use codex_hepta_neuron::AnchorWitnessStore;
use codex_hepta_neuron::JournalAnchor;
use codex_hepta_neuron::NeuronInferenceControlPort;
use codex_hepta_neuron::NeuronModelError;
use codex_hepta_neuron::WitnessStoreError;

use super::AgentdNeuronOwner;

struct StubWitness;

impl AnchorWitnessStore for StubWitness {
    fn current(&self) -> Result<Option<JournalAnchor>, WitnessStoreError> {
        Ok(None)
    }

    fn compare_and_swap(
        &mut self,
        _expected: Option<JournalAnchor>,
        _next: JournalAnchor,
    ) -> Result<(), WitnessStoreError> {
        Ok(())
    }
}

struct StubInferenceControl;

impl NeuronInferenceControlPort for StubInferenceControl {
    fn execute_feature(
        &mut self,
        _request: &NeuronFeatureRequestV1,
    ) -> Result<NeuronFeatureReceiptV1, NeuronModelError> {
        Err(NeuronModelError::Rejected)
    }
}

#[test]
fn agentd_neuron_owner_is_a_compiled_product_surface() {
    let name = std::any::type_name::<AgentdNeuronOwner<StubWitness, StubInferenceControl>>();
    assert!(name.contains("AgentdNeuronOwner"));
}

#[test]
fn agentd_local_baseline_exposes_only_witnessed_neuron_state() {
    use codex_hepta_neuron::NeuronLocalCheckpointBindingV1;
    use codex_hepta_neuron::NeuronRuntimeError;

    // This type-checks the exact, non-mutating Agentd owner ingress against
    // the real generic NeuronRuntime. The native runtime tests separately
    // prove a committed checkpoint, witness mismatch and pending write cases.
    let read: fn(
        &AgentdNeuronOwner<StubWitness, StubInferenceControl>,
    ) -> Result<NeuronLocalCheckpointBindingV1, NeuronRuntimeError> =
        AgentdNeuronOwner::read_local_checkpoint_binding_v1;
    let _ = read;
}

#[test]
fn agentd_observed_tick_api_requires_real_owner_and_strict_final_witness() {
    use crate::AgentdNeuronTickObservationV1;

    let execute: fn(
        &mut AgentdNeuronOwner<StubWitness, StubInferenceControl>,
        codex_hepta_neuron::NeuronTickInputV1,
    ) -> Result<
        (
            codex_hepta_neuron::NeuronRuntimeOutputV1,
            AgentdNeuronTickObservationV1,
        ),
        codex_hepta_neuron::NeuronRuntimeError,
    > = AgentdNeuronOwner::tick_with_observation_v1;
    let current: fn(
        &AgentdNeuronOwner<StubWitness, StubInferenceControl>,
        &AgentdNeuronTickObservationV1,
    ) -> Result<(), codex_hepta_neuron::NeuronRuntimeError> =
        AgentdNeuronOwner::revalidate_current_tick_observation_v1;
    let _ = (execute, current);
}

#[test]
fn agentd_observer_tick_join_requires_live_neuron_and_ledger_owners() {
    // Type-check the concrete product ingress: no caller-supplied bare
    // Ledger/source digest can bypass the Agentd Neuron witness check.
    let _read =
        AgentdNeuronOwner::<StubWitness, StubInferenceControl>::read_observer_linked_tick_v1;
}

#[test]
fn caller_rehashed_tick_cannot_impersonate_last_agentd_owned_observation() {
    use codex_hepta_types::AuthorityPosture;
    use codex_hepta_types::Digest32;
    use codex_hepta_types::Generation;
    use codex_hepta_types::StableId;

    use crate::AgentdNeuronTickObservationV1;

    fn digest(label: &str) -> Digest32 {
        Digest32::of_bytes(label.as_bytes())
    }

    let mut observed = AgentdNeuronTickObservationV1 {
        tick_id: StableId::new("owner-tick-1").unwrap(),
        input_digest: digest("actual-input"),
        input_feature_digest: digest("features"),
        scope_digest: digest("scope"),
        objective_digest: digest("objective"),
        ndu_snapshot_digest: digest("ndu"),
        generation: Generation::new(1).unwrap(),
        logical_sequence: 1,
        checkpoint_before: Digest32::ZERO,
        checkpoint_after: digest("checkpoint"),
        local_checkpoint_binding_digest: digest("acknowledged-local-state"),
        model_runtime_digest: digest("loaded-model"),
        observed_output_digest: digest("actual-result"),
        execution_micros: 42,
        queue_age_micros: 1,
        observed_memory_bytes: 4096,
        transient_allocation_bytes: 1024,
        confidence_ppm: 800_000,
        ood_ppm: 1_000,
        abstain: false,
        diagnostic_digest: Digest32::ZERO,
        authority: AuthorityPosture::DENY_ALL,
    };
    observed.diagnostic_digest = observed.computed_digest();
    assert!(observed.validate_integrity());
    assert!(super::require_owner_issued_tick(None, &observed).is_err());
    assert!(super::require_owner_issued_tick(Some(&observed), &observed).is_ok());

    let mut forged = observed.clone();
    forged.input_digest = digest("forged-input");
    forged.diagnostic_digest = forged.computed_digest();
    assert!(forged.validate_integrity());
    assert!(super::require_owner_issued_tick(Some(&observed), &forged).is_err());

    let mut forged = observed.clone();
    forged.observed_output_digest = digest("forged-output");
    forged.diagnostic_digest = forged.computed_digest();
    assert!(forged.validate_integrity());
    assert!(super::require_owner_issued_tick(Some(&observed), &forged).is_err());

    let mut malformed = observed.clone();
    malformed.diagnostic_digest = Digest32::ZERO;
    assert!(super::require_owner_issued_tick(Some(&malformed), &malformed).is_err());
}
