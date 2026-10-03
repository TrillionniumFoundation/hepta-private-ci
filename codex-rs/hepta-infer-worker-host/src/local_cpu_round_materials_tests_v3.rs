use super::*;
use codex_hepta_agent_components::intelligence::encode_parameter_plasticity_request_v1;
use codex_hepta_neuron::encode_neuron_generation_material_v2;
#[cfg(feature = "root-frozen-generator")]
#[path = "root_round_current_manifest_projection_tests.rs"]
mod current_manifest_projection;
#[path = "local_cpu_round_materials_test_fixture_v3.rs"]
mod fixture;
type TestResult = Result<(), Box<dyn std::error::Error>>;

#[cfg(feature = "root-frozen-generator")]
#[test]
#[ignore = "requires actual Root and isolated protected /run custody"]
fn actual_root_retains_complete_pure_recipe_and_refuses_context_substitution() -> TestResult {
    use crate::initial_cpu_anchor::InstalledCpuSourceV1;
    use crate::root_frozen_generator::recipe;
    use std::os::unix::fs::PermissionsExt;
    assert_eq!(rustix::process::geteuid().as_raw(), 0);
    let directory = tempfile::Builder::new()
        .prefix("hepta-round-recipe-")
        .tempdir_in("/run")?;
    let fixture = fixture::Fixture::new(directory.path().join("physical"))?;
    let round = fixture.round("actual.goal.one", 1)?;
    let materials = fixture.derive(&round)?;
    let context_bytes = br#"{"original_context":"pure-publication-vector"}"#;
    let context_path = directory.path().join("context.json");
    std::fs::write(&context_path, context_bytes)?;
    std::fs::set_permissions(&context_path, std::fs::Permissions::from_mode(0o444))?;
    let context = InstalledCpuSourceV1 {
        path: context_path,
        digest: Digest32::of_bytes(context_bytes).to_string(),
    };
    // Only pure publication is tested. These unverified inputs cannot pass the
    // original Root material reader, create a worker or confer signed authority.
    let worker = InstalledCpuSourceV1 {
        path: directory.path().join("unverified-worker-vector"),
        digest: Digest32::of_bytes(b"unverified worker vector").to_string(),
    };
    let published = recipe::publish(directory.path(), &materials, &worker, &context)?;
    let repeated = recipe::publish(directory.path(), &materials, &worker, &context)?;
    assert_eq!(
        serde_json::to_value(&published)?,
        serde_json::to_value(&repeated)?
    );
    let bytes = std::fs::read(&published.path)?;
    assert_eq!(Digest32::of_bytes(&bytes).to_string(), published.digest);
    let recipe: recipe::PublishedRoundRecipeV3 = serde_json::from_slice(&bytes)?;
    assert_eq!(recipe.round, round);
    let retained = recipe::retained(directory.path(), &round)?;
    assert_eq!(
        serde_json::to_value(&retained)?,
        serde_json::to_value(&recipe)?
    );
    assert!(recipe::retained(directory.path(), &fixture.round("actual.goal.two", 1)?).is_err());
    assert_eq!(
        serde_json::to_value(&recipe.plasticity_context)?,
        serde_json::to_value(&context)?
    );
    let descriptor: serde_json::Value =
        serde_json::from_slice(&std::fs::read(&recipe.materials.path)?)?;
    let read = |field: &str| -> Result<Vec<u8>, Box<dyn std::error::Error>> {
        let input: InstalledCpuSourceV1 = serde_json::from_value(descriptor[field].clone())?;
        let bytes = std::fs::read(&input.path)?;
        assert_eq!(Digest32::of_bytes(&bytes).to_string(), input.digest);
        Ok(bytes)
    };
    assert_eq!(
        read("baseline")?,
        encode_neuron_generation_material_v2(materials.baseline())?
    );
    assert_eq!(
        read("parameter_request")?,
        encode_parameter_plasticity_request_v1(materials.request())?
    );
    assert_eq!(
        read("rollback")?,
        encode_neuron_generation_material_v2(materials.rollback())?
    );
    let other_path = directory.path().join("other-context.json");
    std::fs::write(&other_path, context_bytes)?;
    std::fs::set_permissions(&other_path, std::fs::Permissions::from_mode(0o444))?;
    let other = InstalledCpuSourceV1 {
        path: other_path,
        digest: context.digest,
    };
    assert!(recipe::publish(directory.path(), &materials, &worker, &other).is_err());
    assert_eq!(std::fs::read(&published.path)?, bytes);
    assert!(!directory.path().join("physical").exists());
    Ok(())
}

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

#[test]
fn genuine_no_change_frontier_reaches_preparation_without_fabricated_e_or_physical_stores()
-> TestResult {
    use codex_hepta_agent_components::plasticity::generate_parameter_candidates_v3;
    use codex_hepta_types::FixedQ32;
    let directory = tempfile::tempdir()?;
    let mut fixture = fixture::Fixture::new(directory.path().join("enrolled-rounds"))?;
    fixture.request.generator_profile.signals[0].eligibility = FixedQ32::ZERO;
    fixture.request.generated =
        generate_parameter_candidates_v3(fixture.request.generator_profile.clone())?;
    fixture.request.admission.generator_digest = fixture.request.generated.generator_digest;
    fixture.execution.maximum_candidates =
        u16::try_from(fixture.request.generated.candidates.len())?;
    let round = fixture.round("actual.no.update.goal", 1)?;
    let before = encode_parameter_plasticity_request_v1(&fixture.request)?;
    let materials = fixture.derive(&round)?;
    assert_eq!(materials.request().generated.candidates.len(), 1);
    assert_eq!(
        materials.request().generated.candidates[0].kind,
        ParameterCandidateKindV2::NoChange
    );
    assert!(materials.candidates().is_empty());
    assert_eq!(
        encode_parameter_plasticity_request_v1(materials.request())?,
        before
    );
    assert!(materials.request().no_change_attestation.is_none());
    assert!(materials.request().evaluations.is_empty());
    materials.with_plan(validate_cpu_neuron_parameter_materials_v2)?;
    assert_eq!(std::fs::read_dir(directory.path())?.count(), 0);
    Ok(())
}

#[test]
fn generated_update_cannot_be_hidden_behind_an_empty_preparation_frontier() -> TestResult {
    let fixture = fixture::Fixture::new("/protected/original-rounds".into())?;
    let materials = fixture.derive(&fixture.round("actual.update.goal", 1)?)?;
    assert_eq!(materials.candidates().len(), 1);
    assert!(
        materials
            .with_plan(|plan| {
                let incomplete = CpuNeuronParameterMaterialPlanV2 {
                    candidates: &[],
                    ..*plan
                };
                validate_cpu_neuron_parameter_materials_v2(&incomplete)
            })
            .is_err()
    );
    let mut altered = fixture;
    altered
        .request
        .generated
        .candidates
        .retain(|candidate| candidate.kind == ParameterCandidateKindV2::NoChange);
    assert!(
        altered
            .derive(&altered.round("actual.update.goal", 1)?)
            .is_err()
    );
    Ok(())
}

#[cfg(feature = "fixed-initial-cpu-host")]
#[path = "local_cpu_round_final_admission_tests_v3.rs"]
mod final_admission_tests;
