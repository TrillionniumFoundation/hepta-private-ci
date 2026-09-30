use super::*;

#[test]
fn forty_generations_release_old_physical_owners_and_recover_cold_full_receipts() {
    let directory = super::super::super::super::durable_state_tests::private_state_directory();
    let path = directory.path().join("control.json");
    let mut fixtures = Vec::new();
    let mut clones = Vec::new();
    let mut commits = Vec::new();
    fixtures.push(generation_fixture(1));
    let first = fixtures[0].owner();
    clones.push(first.clone());
    let controller = checked(AgentdNeuronGenerationControllerV2::new_with_state_path(
        first, &path,
    ));
    checked(controller.start());
    for generation in 1..=40 {
        if generation > 1 {
            checked(controller.begin_quiesce());
            checked(controller.seal());
            fixtures.push(generation_fixture(generation));
            let next = fixtures.last().expect("fixture").owner();
            clones.push(next.clone());
            checked(controller.reload(next));
        }
        let fixture = fixtures.last().expect("fixture");
        let prepared = fixture.prepared(&controller);
        commits.push(checked(
            prepared.execute(&fixture.input(), &mut fixture.allow()),
        ));
        assert!(
            checked(controller.retained_generations()).len()
                <= MAX_RETAINED_NEURON_GENERATION_OWNERS_V2
        );
    }
    let state = checked(controller.generation_state());
    assert_eq!(state.retained_generations, vec![38, 39]);
    assert!(std::fs::metadata(&path).expect("state metadata").len() < 1024);
    let fixture = &fixtures[0];
    let old = checked(controller.query_operation(
        1,
        &fixture.tick.tick_id,
        commits[0].key.input_semantic_digest,
    ));
    assert_eq!(
        old,
        NeuronOperationStatusV2::Committed {
            commit: Box::new(commits[0].clone()),
            witness_acknowledged: true
        }
    );
    assert!(matches!(
        clones[0].operational_snapshot(),
        Err(AgentdNeuronControlErrorV2::NotServing)
    ));
    // A fenced external handle clone still exists; its old file locks and model
    // owner have been released by canonical retirement rather than Arc drop.
    drop(fixture.owner());
    checked(controller.shutdown());
    drop(controller);
    drop(clones);
    let recovered = checked(
        AgentdNeuronGenerationControllerV2::from_recovered_generations_with_state_path(
            fixtures[39].owner(),
            [fixtures[37].owner(), fixtures[38].owner()],
            &path,
        ),
    );
    checked(recovered.restart_stopped());
    assert_eq!(
        checked(recovered.query_operation(
            1,
            &fixture.tick.tick_id,
            commits[0].key.input_semantic_digest
        )),
        old
    );
    assert_eq!(fixture.calls.load(Ordering::SeqCst), 1);
    let blob = directory
        .path()
        .join("neuron-generation-archives/1.archive");
    let mut bytes = std::fs::read(&blob).expect("archive");
    bytes[20] ^= 1;
    std::fs::write(&blob, bytes).expect("corrupt archive");
    assert!(
        recovered
            .query_operation(
                1,
                &fixture.tick.tick_id,
                commits[0].key.input_semantic_digest
            )
            .is_err()
    );
}

#[test]
fn frontier_commit_before_hot_removal_recovers_the_archive_and_excludes_it_from_live_topology() {
    let directory = super::super::super::super::durable_state_tests::private_state_directory();
    let path = directory.path().join("control.json");
    let first = generation_fixture(1);
    let next = generation_fixture(2);
    let first_handle = first.owner();
    let controller = checked(AgentdNeuronGenerationControllerV2::new_with_state_path(
        first_handle.clone(),
        &path,
    ));
    checked(controller.start());
    let committed = checked(
        first
            .prepared(&controller)
            .execute(&first.input(), &mut first.allow()),
    );
    checked(controller.begin_quiesce());
    checked(controller.seal());
    checked(controller.reload(next.owner()));
    {
        let mut state = checked(controller.lock_state());
        let archive = checked(first_handle.owner.export_archive_control());
        checked(
            state
                .archives
                .as_mut()
                .expect("durable archive owner")
                .commit(&archive),
        );
        // Simulate process death after archive publication, before hot removal.
    }
    drop(controller);
    drop(first_handle);
    assert_eq!(
        checked(read_agentd_neuron_generation_state_v2(&path)).retained_generations,
        vec![1]
    );
    assert!(
        checked(read_agentd_neuron_live_generation_state_v2(&path))
            .retained_generations
            .is_empty()
    );
    let recovered = checked(
        AgentdNeuronGenerationControllerV2::from_recovered_generations_with_state_path(
            next.owner(),
            [],
            &path,
        ),
    );
    checked(recovered.start());
    let truth = checked(recovered.query_operation(
        1,
        &first.tick.tick_id,
        committed.key.input_semantic_digest,
    ));
    assert!(matches!(
        truth,
        NeuronOperationStatusV2::Committed {
            witness_acknowledged: true,
            ..
        }
    ));
}

#[test]
fn configured_disk_pressure_keeps_the_predecessor_and_every_hot_owner() {
    let directory = super::super::super::super::durable_state_tests::private_state_directory();
    let path = directory.path().join("control.json");
    let first = generation_fixture(1);
    let second = generation_fixture(2);
    let third = generation_fixture(3);
    let fourth = generation_fixture(4);
    let old_clone = first.owner();
    let controller = checked(
        AgentdNeuronGenerationControllerV2::from_recovered_generations_with_archive_policy(
            old_clone.clone(),
            [],
            &path,
            AgentdNeuronArchivePolicyV1 {
                maximum_total_bytes: 1,
            },
        ),
    );
    checked(controller.start());
    for next in [second.owner(), third.owner()] {
        checked(controller.begin_quiesce());
        checked(controller.seal());
        checked(controller.reload(next));
    }
    checked(controller.begin_quiesce());
    checked(controller.seal());
    assert!(matches!(
        controller.reload(fourth.owner()),
        Err(AgentdNeuronControlErrorV2::StoragePressure)
    ));
    assert_eq!(checked(controller.active_generation()), 3);
    assert_eq!(checked(controller.retained_generations()), vec![1, 2]);
    assert_eq!(
        checked(controller.state()),
        AgentdNeuronLifecycleStateV2::Sealed
    );
    checked(old_clone.operational_snapshot());
    assert!(
        !directory
            .path()
            .join("neuron-generation-archives/1.archive")
            .exists()
    );
    assert!(matches!(
        read_agentd_neuron_live_generation_state_v2(&path),
        Err(AgentdNeuronControlErrorV2::ControllerBusy)
    ));
}

#[test]
fn incomplete_frontier_publication_preserves_immutable_bytes_and_retry_obligation() {
    let directory = super::super::super::super::durable_state_tests::private_state_directory();
    let path = directory.path().join("control.json");
    let fixture = generation_fixture(1);
    let handle = fixture.owner();
    let archive = checked(handle.owner.export_archive_control());
    let mut store = checked(archive_store::GenerationArchiveStore::open(
        &path,
        64 * 1024 * 1024,
    ));
    let blob = directory
        .path()
        .join("neuron-generation-archives/1.archive");
    let mut options = std::fs::OpenOptions::new();
    options.write(true).create_new(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.mode(0o600);
    }
    options
        .open(&blob)
        .expect("incomplete publication")
        .write_all(archive.bytes())
        .expect("original immutable blob");
    let original = std::fs::read(&blob).expect("original");
    checked(store.commit(&archive));
    assert_eq!(std::fs::read(&blob).expect("after exact retry"), original);
    drop(store);
    let recovered = checked(archive_store::GenerationArchiveStore::open(
        &path,
        64 * 1024 * 1024,
    ));
    assert!(checked(recovered.contains(1)));
    let frontier: serde_json::Value = serde_json::from_slice(
        &std::fs::read(
            directory
                .path()
                .join("neuron-generation-archives/frontier.json"),
        )
        .expect("frontier"),
    )
    .expect("frontier JSON");
    let receipt_bytes = std::fs::metadata(
        directory
            .path()
            .join("neuron-generation-archives/1.receipt.json"),
    )
    .expect("receipt size")
    .len();
    assert_eq!(
        frontier["total_bytes"].as_u64(),
        Some(archive.bytes().len() as u64 + receipt_bytes)
    );
}
