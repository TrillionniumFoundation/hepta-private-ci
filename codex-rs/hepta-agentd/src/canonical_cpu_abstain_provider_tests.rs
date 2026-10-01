use super::*;
use crate::canonical_abstain_provider::tests::durable_record;
use crate::canonical_abstain_provider::tests::identity;
use crate::intelligence_product::tests::authority_verifier;
use crate::intelligence_product::tests::digest;
use crate::intelligence_product::tests::fixture;
use crate::intelligence_product::tests::write_authority_file;

#[test]
fn installed_cpu_provider_keeps_run_lifecycle_distinct_from_real_model_generation() {
    let value = fixture();
    let mut record = durable_record(&value);
    let mut native = value.inputs.neural_config.clone();
    native.generation = Generation::new(1).expect("initial model");
    record.snapshot.model_tuple_digest = native.model_digest;
    let runtime_digest = digest("actual-installed-runtime-config");
    let mut owners = value.owners.clone();
    let neuron = owners
        .iter_mut()
        .find(|row| row.owner_id.as_str() == "neuron.runtime")
        .expect("neuron");
    neuron.generation = native.generation;
    neuron.implementation_digest = runtime_digest;
    let directory = tempfile::tempdir().expect("directory");
    let authority = directory.path().join("authority.json");
    write_authority_file(
        &authority,
        &owners,
        value.request.snapshot.revocation_frontier_digest(),
    );
    let provider = AgentdDurableCpuAbstainInvocationProviderV2::new(
        authority,
        authority_verifier(),
        native.clone(),
        runtime_digest,
        record.runtime_body_digest,
    )
    .expect("provider");
    let original_lifecycle = record.snapshot.generation;
    let identity = identity(directory.path(), original_lifecycle - 1);
    let invocation = provider
        .build(&identity, &record)
        .expect("current installed invocation");
    invocation
        .validate(&identity, &record)
        .expect("original strong RunStart identity");
    assert_eq!(record.snapshot.generation, original_lifecycle);
    assert_ne!(original_lifecycle, 1);
    assert_eq!(
        invocation.request.snapshot.body_generation(),
        native.generation
    );
    assert_eq!(invocation.inputs.neural_config, native);
    assert_eq!(
        invocation.inputs.utility_contributions.generation,
        native.generation
    );
    assert!(invocation.inputs.neural_tick.drive_q24.is_empty());
    assert!(invocation.inputs.neural_tick.prediction_q24.is_empty());
    let mut wrong_body = record.clone();
    wrong_body.runtime_body_digest = digest("different-body");
    assert!(provider.build(&identity, &wrong_body).is_err());
    let mut wrong_model = record;
    wrong_model.snapshot.model_tuple_digest = digest("different-model");
    assert!(provider.build(&identity, &wrong_model).is_err());
}

#[test]
fn installed_cpu_provider_rejects_current_signed_owner_generation_or_implementation_drift() {
    let value = fixture();
    let mut record = durable_record(&value);
    let mut native = value.inputs.neural_config.clone();
    native.generation = Generation::new(1).expect("initial model");
    record.snapshot.model_tuple_digest = native.model_digest;
    let directory = tempfile::tempdir().expect("directory");
    let authority = directory.path().join("authority.json");
    let runtime_digest = digest("actual-installed-runtime-config");
    let provider = AgentdDurableCpuAbstainInvocationProviderV2::new(
        authority.clone(),
        authority_verifier(),
        native.clone(),
        runtime_digest,
        record.runtime_body_digest,
    )
    .expect("provider");
    let identity = identity(directory.path(), record.snapshot.generation - 1);
    for implementation in [runtime_digest, digest("different-runtime")] {
        let mut owners = value.owners.clone();
        let neuron = owners
            .iter_mut()
            .find(|row| row.owner_id.as_str() == "neuron.runtime")
            .expect("neuron");
        neuron.generation = if implementation == runtime_digest {
            Generation::new(2).expect("wrong generation")
        } else {
            native.generation
        };
        neuron.implementation_digest = implementation;
        write_authority_file(
            &authority,
            &owners,
            value.request.snapshot.revocation_frontier_digest(),
        );
        assert!(provider.build(&identity, &record).is_err());
    }
}
