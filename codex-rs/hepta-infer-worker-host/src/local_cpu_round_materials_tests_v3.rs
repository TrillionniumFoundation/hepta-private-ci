use super::*;
use codex_hepta_agent_components::intelligence::encode_parameter_plasticity_request_v1;
use codex_hepta_neuron::encode_neuron_generation_material_v2;
#[path = "local_cpu_round_materials_test_fixture_v3.rs"]
mod fixture;
type TestResult = Result<(), Box<dyn std::error::Error>>;

#[test]
fn identical_original_round_retains_every_signed_request_byte_and_writes_no_physical_store()
-> TestResult {
    let directory = tempfile::tempdir()?;
    let fixture = fixture::Fixture::new(directory.path().join("enrolled-rounds"))?;
    let round = fixture.round("actual.goal.one", 1)?;
    let before = encode_parameter_plasticity_request_v1(&fixture.request)?;
    let first = fixture.derive(&round)?;
    let second = fixture.derive(&round)?;
    assert_eq!(
        encode_parameter_plasticity_request_v1(first.request())?,
        before
    );
    assert_eq!(first.round().canonical_bytes()?, round.canonical_bytes()?);
    assert_eq!(
        first.canonical_envelope().canonical_bytes(),
        fixture.canonical.canonical_bytes()
    );
    assert_eq!(first.candidates().len(), 1);
    for (left, right) in first.candidates().iter().zip(second.candidates()) {
        assert_eq!(
            encode_neuron_generation_material_v2(&left.generation)?,
            encode_neuron_generation_material_v2(&right.generation)?
        );
        assert_eq!(left.canary_tick, right.canary_tick);
        assert_eq!(left.canary_port, right.canary_port);
        assert_eq!(left.canary_tick.tick_id, left.canary_port.run_id);
        assert_eq!(
            left.canary_tick.ndu_snapshot_digest,
            left.canary_port.predecessor_digest
        );
        assert_eq!(
            left.canary_port.candidate_set_digest,
            fixture.request.generated.generator_digest
        );
    }
    first.with_plan(validate_cpu_neuron_parameter_materials_v2)?;
    assert_eq!(std::fs::read_dir(directory.path())?.count(), 0);
    Ok(())
}

#[test]
fn next_round_on_unchanged_baseline_has_new_full_store_and_canary_identities() -> TestResult {
    let directory = tempfile::tempdir()?;
    let fixture = fixture::Fixture::new(directory.path().join("enrolled-rounds"))?;
    let old = fixture.derive(&fixture.round("actual.goal.one", 1)?)?;
    let next = fixture.derive(&fixture.round("actual.goal.two", 2)?)?;
    let old_candidate = &old.candidates()[0];
    let new_candidate = &next.candidates()[0];
    assert_eq!(old.baseline().native, next.baseline().native);
    assert_eq!(
        old_candidate.generation.native,
        new_candidate.generation.native
    );
    assert_ne!(
        old_candidate.generation.generation_store,
        new_candidate.generation.generation_store
    );
    assert_ne!(
        old_candidate.generation.runtime_index,
        new_candidate.generation.runtime_index
    );
    assert_ne!(
        old_candidate.generation.witness,
        new_candidate.generation.witness
    );
    assert_ne!(
        old.rollback().generation_store,
        next.rollback().generation_store
    );
    assert_ne!(
        old_candidate.canary_tick.tick_id,
        new_candidate.canary_tick.tick_id
    );
    assert_ne!(
        old_candidate.canary_tick.semantic_digest()?,
        new_candidate.canary_tick.semantic_digest()?
    );
    assert_ne!(
        old_candidate.canary_port.run_id,
        new_candidate.canary_port.run_id
    );
    assert_ne!(
        old_candidate.canary_port.snapshot_digest,
        new_candidate.canary_port.snapshot_digest
    );
    assert_eq!(new_candidate.canary_tick.logical_sequence, 1);
    assert!(new_candidate.canary_tick.checkpoint_digest.is_zero());
    assert_eq!(new_candidate.generation.runtime.generation.get(), 2);
    assert_eq!(next.rollback().runtime.generation.get(), 3);
    next.with_plan(validate_cpu_neuron_parameter_materials_v2)?;
    assert_eq!(std::fs::read_dir(directory.path())?.count(), 0);
    Ok(())
}

#[test]
fn foreign_round_scope_quota_or_nonfresh_input_cannot_derive_a_recipe() -> TestResult {
    let directory = tempfile::tempdir()?;
    let mut fixture = fixture::Fixture::new(directory.path().join("enrolled-rounds"))?;
    let round = fixture.round("actual.goal.one", 1)?;
    fixture.blueprint.canary_tick.checkpoint_digest = Digest32::of_bytes(b"old committed store");
    assert!(fixture.derive(&round).is_err());
    fixture.blueprint.canary_tick.checkpoint_digest = Digest32::ZERO;
    fixture.blueprint.canary_tick.subject_id = StableId::new("foreign.subject")?;
    assert!(fixture.derive(&round).is_err());
    fixture.blueprint.canary_tick.subject_id = StableId::new("actual.agent")?;
    fixture.execution.maximum_candidates += 1;
    assert!(fixture.derive(&round).is_err());
    fixture.execution.maximum_candidates -= 1;
    fixture.request.admission.baseline_generation = fixture.baseline.runtime.generation.next()?;
    assert!(
        fixture.derive(&round).is_err(),
        "old signature is not rebound to a new baseline"
    );
    assert_eq!(std::fs::read_dir(directory.path())?.count(), 0);
    Ok(())
}
