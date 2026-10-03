//! Fresh completion uses real original file descriptors and cold recovery.
use super::*;
use std::io::Write;
use std::os::unix::fs::PermissionsExt;
fn fresh_plan(fixture: &Fixture) -> crate::NeuronGenerationMaterialV2 {
    let native = native_config();
    let runtime = runtime_config(&native);
    let mut body = body_bundle(native.generation);
    body.effective_parameter_digest = checked(runtime.execution_profile_digest_v1());
    let (store_context, index_context) = contexts(&native, &runtime, &body);
    crate::NeuronGenerationMaterialV2 {
        model_manifest: fixture.0.join("model.manifest"),
        model_manifest_digest: runtime.model_manifest_digest,
        generation_store: fixture.store(),
        runtime_index: fixture.index(),
        witness: fixture.0.join("witness.hptnwv02"),
        native,
        scope: scope(),
        runtime,
        body,
        store_context,
        index_context,
        witness_context: crate::NeuronWitnessContextV2 {
            generation: Generation::new(1).expect("generation"),
            scope: scope(),
            key_epoch: 1,
            deletion_epoch: 1,
            max_records: 32,
        },
    }
}
fn open(
    f: &Fixture,
    p: &crate::NeuronGenerationMaterialV2,
) -> NeuronRuntimeV2<crate::FileNeuronWitnessStoreV2> {
    let witness = checked(crate::FileNeuronWitnessStoreV2::create(
        &p.witness,
        p.witness_context.clone(),
    ));
    let runtime = checked(NeuronRuntimeV2::bootstrap(
        &f.store(),
        &f.index(),
        p.native.clone(),
        p.scope,
        p.runtime.clone(),
        p.body.clone(),
        p.store_context.clone(),
        p.index_context.clone(),
        witness,
    ));
    for path in [&p.generation_store, &p.runtime_index, &p.witness] {
        checked(fs::set_permissions(path, fs::Permissions::from_mode(0o600)));
    }
    runtime
}
#[test]
fn prepared_whole_three_actual_headers_survive_cold_reopen_without_writes_or_model() {
    let f = Fixture::new();
    let plan = fresh_plan(&f);
    let runtime = open(&f, &plan);
    let before: [Vec<u8>; 3] = [
        checked(fs::read(&plan.generation_store)),
        checked(fs::read(&plan.runtime_index)),
        checked(fs::read(&plan.witness)),
    ];
    let packet = checked(runtime.export_prepared_generation_v2(&plan));
    checked(packet.validate_against(&plan));
    for (file, expected) in packet.files().iter().zip(&before) {
        assert_eq!(&file.header, expected);
        assert_eq!(file.length, expected.len() as u64);
    }
    let bytes = packet.bytes().to_vec();
    let raw = checked(crate::NeuronPreparedGenerationV2::from_bytes(
        bytes.clone(),
        Digest32::of_bytes(&bytes),
    ));
    checked(raw.validate_against(&plan));
    let mut foreign = plan.clone();
    foreign.witness_context.key_epoch += 1;
    assert!(raw.validate_against(&foreign).is_err());
    let mut changed = bytes.clone();
    changed[8] ^= 1;
    let pin = Digest32::of_bytes(&changed);
    assert!(crate::NeuronPreparedGenerationV2::from_bytes(changed, pin).is_err());
    drop(runtime);
    let witness = checked(crate::FileNeuronWitnessStoreV2::open_existing(
        &plan.witness,
        plan.witness_context.clone(),
    ));
    let runtime = checked(NeuronRuntimeV2::recover(
        &f.store(),
        &f.index(),
        plan.native.clone(),
        plan.scope,
        plan.runtime.clone(),
        plan.body.clone(),
        plan.store_context.clone(),
        plan.index_context.clone(),
        witness,
    ));
    assert_eq!(
        checked(runtime.export_prepared_generation_v2(&plan)).bytes(),
        bytes
    );
    for (path, expected) in [&plan.generation_store, &plan.runtime_index, &plan.witness]
        .into_iter()
        .zip(before)
    {
        assert_eq!(checked(fs::read(path)), expected);
    }
}
#[test]
fn prepared_rejects_real_tick_rows_changed_headers_and_replaced_descriptor_path() {
    let f = Fixture::new();
    let plan = fresh_plan(&f);
    let mut runtime = open(&f, &plan);
    let calls = Arc::new(AtomicUsize::new(0));
    let mut model = FakeDurableModel::new(calls.clone());
    checked(runtime.tick_guarded(&mut model, input(1, Digest32::ZERO), &mut Allow));
    assert!(runtime.export_prepared_generation_v2(&plan).is_err());
    assert_eq!(calls.load(Ordering::SeqCst), 1);
    let f = Fixture::new();
    let plan = fresh_plan(&f);
    let runtime = open(&f, &plan);
    let mut file = checked(fs::OpenOptions::new().write(true).open(&plan.runtime_index));
    checked(file.write_all(b"changed!"));
    checked(file.sync_all());
    assert!(runtime.export_prepared_generation_v2(&plan).is_err());
    let f = Fixture::new();
    let plan = fresh_plan(&f);
    let runtime = open(&f, &plan);
    checked(fs::rename(&plan.witness, f.0.join("retained-witness")));
    checked(fs::write(&plan.witness, b"replacement"));
    assert!(runtime.export_prepared_generation_v2(&plan).is_err());
}

#[test]
fn prepared_rejects_partial_three_file_completion_and_a_seeded_original_witness() {
    for which in 0..3 {
        let f = Fixture::new();
        let plan = fresh_plan(&f);
        let runtime = open(&f, &plan);
        let path = [&plan.generation_store, &plan.runtime_index, &plan.witness][which];
        let mut external = checked(fs::OpenOptions::new().append(true).open(path));
        checked(external.write_all(b"partial"));
        checked(external.sync_all());
        let before = checked(fs::read(path));
        assert!(runtime.export_prepared_generation_v2(&plan).is_err());
        assert_eq!(checked(fs::read(path)), before);
    }
    let f = Fixture::new();
    let plan = fresh_plan(&f);
    let witness = checked(crate::FileNeuronWitnessStoreV2::create_successor(
        &plan.witness,
        plan.witness_context.clone(),
        JournalAnchor {
            sequence: 1,
            checkpoint_digest: digest("real seeded predecessor"),
        },
    ));
    checked(fs::set_permissions(
        &plan.witness,
        fs::Permissions::from_mode(0o600),
    ));
    let before = checked(fs::read(&plan.witness));
    assert!(witness.observe_fresh_prepared_v2().is_err());
    assert_eq!(checked(fs::read(&plan.witness)), before);
}
