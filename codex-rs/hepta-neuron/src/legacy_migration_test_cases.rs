#[test]
fn full_archive_adopts_acknowledged_legacy_history_and_reopens_exact_result() {
    let fixture = Fixture::new();
    let (native, config, journal, witness, record) = acknowledged_legacy(&fixture);
    let receipt = checked(migrate_legacy_v1_operation_history(
        fixture.file("operations"),
        &native,
        &journal,
        &witness,
        scope(),
        8,
        &config,
        std::slice::from_ref(&record),
        trusted_archive_digest(&native, &config, &record),
    ));
    assert_eq!(receipt.imported_operations, 1);
    assert_eq!(receipt.frontier, Some(record.next_anchor));
    assert!(!receipt.receipt_digest.is_zero());

    let reopened = checked(FileNeuronOperationStore::open_existing(
        fixture.file("operations"),
        checked(config.semantic_digest()),
        scope(),
        generation(),
        5,
        8,
    ));
    assert_eq!(
        checked(reopened.find_tick(&record.tick_id))
            .expect("migrated operation")
            .output,
        record.output
    );
}

#[test]
fn missing_or_forged_archive_never_initializes_a_sidecar() {
    let fixture = Fixture::new();
    let (native, config, journal, witness, mut record) = acknowledged_legacy(&fixture);
    let operations = fixture.path("operations");
    assert!(
        migrate_legacy_v1_operation_history(
            fixture.file("operations"),
            &native,
            &journal,
            &witness,
            scope(),
            8,
            &config,
            &[],
            trusted_archive_digest(&native, &config, &record),
        )
        .is_err()
    );
    assert_eq!(checked(fs::metadata(&operations)).len(), 0);

    let trusted = trusted_archive_digest(&native, &config, &record);
    record.output.tick.confidence_ppm = record.output.tick.confidence_ppm.saturating_sub(1);
    assert!(
        migrate_legacy_v1_operation_history(
            fixture.file("operations"),
            &native,
            &journal,
            &witness,
            scope(),
            8,
            &config,
            &[record],
            trusted,
        )
        .is_err()
    );
    assert_eq!(checked(fs::metadata(&operations)).len(), 0);
}

#[test]
fn untrusted_archive_digest_never_initializes_a_sidecar() {
    let fixture = Fixture::new();
    let (native, config, journal, witness, record) = acknowledged_legacy(&fixture);
    let operations = fixture.path("operations");
    assert!(
        migrate_legacy_v1_operation_history(
            fixture.file("operations"),
            &native,
            &journal,
            &witness,
            scope(),
            8,
            &config,
            std::slice::from_ref(&record),
            digest("untrusted-archive"),
        )
        .is_err()
    );
    assert_eq!(checked(fs::metadata(&operations)).len(), 0);
}

#[test]
fn exact_prepared_prefix_resumes_without_duplicate_history() {
    let fixture = Fixture::new();
    let (native, config, journal, witness, record) = acknowledged_legacy(&fixture);
    let prepared = checked(PreparedNeuronOperationV1::new(
        record.input_digest,
        record.tick_id.clone(),
        record.expected_anchor,
        record.next_anchor,
        record.sparse_tick.clone(),
        record.output.clone(),
    ));
    {
        let mut store = checked(FileNeuronOperationStore::open(
            fixture.file("operations"),
            checked(config.semantic_digest()),
            scope(),
            generation(),
            5,
            8,
        ));
        checked(store.prepare(prepared));
    }
    let receipt = checked(migrate_legacy_v1_operation_history(
        fixture.file("operations"),
        &native,
        &journal,
        &witness,
        scope(),
        8,
        &config,
        std::slice::from_ref(&record),
        trusted_archive_digest(&native, &config, &record),
    ));
    assert_eq!(receipt.imported_operations, 1);
    let store = checked(FileNeuronOperationStore::open_existing(
        fixture.file("operations"),
        checked(config.semantic_digest()),
        scope(),
        generation(),
        5,
        8,
    ));
    assert!(checked(store.pending()).is_none());
    assert_eq!(checked(store.frontier()), receipt.frontier);
}
