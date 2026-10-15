use super::*;

#[test]
fn production_neuron_journals_must_be_distinct_provisioned_siblings() {
    let root = tempfile::tempdir().expect("protected root");
    let effect = root.path().join("effect-intent.wal");
    let metrics = root.path().join("neuron-metrics.wal");
    assert!(validate_production_paths(&effect, &metrics).is_ok());
    assert!(matches!(
        validate_production_paths(&effect, &effect),
        Err(NeuronProductionBootstrapErrorV1::InvalidPaths)
    ));
    assert!(matches!(
        validate_production_paths(&effect, &root.path().join("different").join("metrics")),
        Err(NeuronProductionBootstrapErrorV1::InvalidPaths)
    ));
    assert!(matches!(
        validate_production_paths(
            &effect,
            &root.path().join("nested").join("..").join("metrics")
        ),
        Err(NeuronProductionBootstrapErrorV1::InvalidPaths)
    ));
}

#[cfg(unix)]
#[test]
fn preprovisioned_evidence_sink_is_durable_and_replay_verified() {
    use codex_hepta_evidence::metrics_sink::DurablePhaseMetricSinkV1;
    use codex_hepta_types::Digest32;
    use codex_hepta_types::PhaseMetricEventV1;
    use codex_hepta_types::PhaseMetricKindV1;
    use codex_hepta_types::PhaseMetricSinkV1;

    let root = tempfile::tempdir().expect("protected root");
    let effect = root.path().join("effect-intent.wal");
    let metrics = root.path().join("neuron-metrics.wal");
    validate_production_paths(&effect, &metrics).expect("same protected parent");
    {
        let sink = DurablePhaseMetricSinkV1::open(
            &metrics, /* capacity */ 16, /* group_size */ 2,
            /* flush_interval_ms */ 100,
        )
        .expect("open real Evidence journal");
        sink.record(PhaseMetricEventV1 {
            scope_digest: Digest32::of_bytes(b"scope"),
            operation_digest: Digest32::of_bytes(b"tick"),
            phase: PhaseMetricKindV1::FinalUse,
            latency_micros: 7,
            succeeded: true,
        })
        .expect("record");
        sink.flush().expect("durable group commit");
        assert!(sink.healthy());
    }
    let reopened = DurablePhaseMetricSinkV1::open(
        &metrics, /* capacity */ 16, /* group_size */ 2, /* flush_interval_ms */ 100,
    )
    .expect("replay persisted group");
    assert!(reopened.healthy());
}

#[cfg(unix)]
#[test]
fn recovered_effect_wal_rejects_missing_or_zero_length_evidence() {
    let root = tempfile::tempdir().expect("protected root");
    let effect = root.path().join("effect.wal");
    let metrics = root.path().join("effect.metrics");
    require_existing_effect_metrics_v1(&effect, &metrics).expect("fresh deployment");
    std::fs::write(&effect, b"existing-effect-intent-history")
        .expect("simulate recovered nonempty intent");
    assert!(matches!(
        require_existing_effect_metrics_v1(&effect, &metrics),
        Err(NeuronProductionBootstrapErrorV1::NotReady)
    ));
    assert!(
        !metrics.exists(),
        "readiness cannot create lost Evidence history"
    );
    std::fs::write(&metrics, b"").expect("empty telemetry");
    assert!(matches!(
        require_existing_effect_metrics_v1(&effect, &metrics),
        Err(NeuronProductionBootstrapErrorV1::NotReady)
    ));
    std::fs::write(&metrics, b"nonempty evidence marker").expect("historical journal");
    require_existing_effect_metrics_v1(&effect, &metrics)
        .expect("presence gate only; real Evidence replay is checked separately");
}

#[cfg(unix)]
#[test]
fn recovered_evidence_denies_missing_or_empty_effect_ledger_before_creation() {
    let root = tempfile::tempdir().expect("private root");
    let effect = root.path().join("effect.wal");
    let metrics = root.path().join("evidence.wal");
    std::fs::write(&metrics, b"previous-original-evidence")
        .expect("existing original Evidence bytes");

    // A deleted business-effect WAL MUST NOT be recreated as an empty file,
    // even though the independent Metrics owner can reopen its own history.
    assert!(matches!(
        require_existing_effect_metrics_v1(&effect, &metrics),
        Err(NeuronProductionBootstrapErrorV1::NotReady)
    ));
    assert!(!effect.exists(), "preflight must be read-only");

    std::fs::write(&effect, b"").expect("truncated effect ledger");
    assert!(matches!(
        require_existing_effect_metrics_v1(&effect, &metrics),
        Err(NeuronProductionBootstrapErrorV1::NotReady)
    ));

    std::fs::write(&effect, b"previous-effect-intent").expect("restored previous intent bytes");
    require_existing_effect_metrics_v1(&effect, &metrics)
        .expect("presence only; BOTH original open/replay owners must validate bytes");
}

#[cfg(unix)]
#[test]
fn partial_zero_length_preprovisioned_journal_is_not_fresh_installation() {
    let root = tempfile::tempdir().expect("private root");
    let effect = root.path().join("effect.wal");
    let metrics = root.path().join("evidence.wal");
    std::fs::write(&metrics, b"").expect("zero-length Evidence placeholder");
    assert!(matches!(
        require_existing_effect_metrics_v1(&effect, &metrics),
        Err(NeuronProductionBootstrapErrorV1::NotReady)
    ));
    assert!(!effect.exists());
    std::fs::write(&effect, b"").expect("paired empty placeholder");
    require_existing_effect_metrics_v1(&effect, &metrics)
        .expect("paired empty files are only a preflight; original owners replay separately");
}

#[cfg(unix)]
#[test]
fn symlinked_parent_or_journal_is_refused_before_any_bootstrap_write() {
    use std::os::unix::fs::symlink;

    let root = tempfile::tempdir().expect("private root");
    let real = root.path().join("real");
    std::fs::create_dir(&real).expect("private directory");
    let alias = root.path().join("alias");
    symlink(&real, &alias).expect("ancestor namespace alias");

    let aliased_effect = alias.join("effect.wal");
    let aliased_metrics = alias.join("evidence.wal");
    assert!(matches!(
        require_existing_effect_metrics_v1(&aliased_effect, &aliased_metrics),
        Err(NeuronProductionBootstrapErrorV1::InvalidPaths)
    ));
    assert!(!real.join("effect.wal").exists());
    assert!(!real.join("evidence.wal").exists());

    let effect = real.join("effect.wal");
    let metrics = real.join("evidence.wal");
    std::fs::write(&effect, b"original-effect").expect("existing WAL");
    symlink(&effect, &metrics).expect("malicious journal alias");
    assert!(matches!(
        require_existing_effect_metrics_v1(&effect, &metrics),
        Err(NeuronProductionBootstrapErrorV1::InvalidPaths)
    ));
    assert_eq!(
        std::fs::read(&effect).expect("unchanged original bytes"),
        b"original-effect"
    );
}

#[cfg(unix)]
#[test]
fn original_wal_frontier_blocks_valid_empty_effect_header_against_evidence_history() {
    use codex_hepta_neuron::NeuronEffectIntentStatusV1;
    use codex_hepta_types::Digest32;

    let effect = NeuronEffectIntentStatusV1 {
        attempted_ticks: 0,
        durable_records: 0,
        unresolved_tick: None,
        poisoned: false,
    };
    let evidence = codex_hepta_evidence::metrics_group_commit::MetricsLocalFrontierV1 {
        sequence: 1,
        head_digest: Digest32::of_bytes(b"original evidence head"),
        committed_rows: 1,
        journal_bytes: 256,
        wal_device: 1,
        wal_inode: 2,
        marker_device: 1,
        marker_inode: 3,
    };
    assert!(matches!(
        require_recovered_effect_metrics_floor_v1(effect, evidence),
        Err(NeuronProductionBootstrapErrorV1::NotReady)
    ));
    assert!(matches!(
        require_recovered_effect_metrics_floor_v1(
            NeuronEffectIntentStatusV1 {
                attempted_ticks: 1,
                durable_records: 1,
                ..effect
            },
            codex_hepta_evidence::metrics_group_commit::MetricsLocalFrontierV1 {
                committed_rows: 0,
                ..evidence
            },
        ),
        Err(NeuronProductionBootstrapErrorV1::NotReady)
    ));
    // This deliberately proves only the conservative local floor. Positive
    // parity never grants serving without independent signed custody.
    require_recovered_effect_metrics_floor_v1(
        NeuronEffectIntentStatusV1 {
            attempted_ticks: 1,
            durable_records: 2,
            ..effect
        },
        evidence,
    )
    .expect("two nonempty owners only pass the local diagnostic floor");
}

#[cfg(unix)]
#[test]
fn real_reopened_evidence_wal_rejects_clean_reset_effect_intent_header() {
    use codex_hepta_evidence::metrics_sink::DurablePhaseMetricSinkV1;
    use codex_hepta_types::Digest32;
    use codex_hepta_types::Generation;
    use codex_hepta_types::PhaseMetricEventV1;
    use codex_hepta_types::PhaseMetricKindV1;
    use codex_hepta_types::PhaseMetricSinkV1;
    use std::os::unix::fs::PermissionsExt;

    let root = tempfile::tempdir().expect("private original owner");
    std::fs::set_permissions(root.path(), std::fs::Permissions::from_mode(0o700))
        .expect("owner-only root");
    let intent_path = root.path().join("effect-intent.wal");
    let evidence_path = root.path().join("original-evidence.wal");
    let scope = JournalScope {
        scope_digest: Digest32::of_bytes(b"original-scope"),
        objective_digest: Digest32::of_bytes(b"original-objective"),
    };
    let generation = Generation::new(1).expect("valid generation");

    // Only an original, real, fsynced Evidence sample exists. A newly
    // recreated business-effect WAL is syntactically valid but has no
    // recovered effect history; it cannot claim a positive restart gate.
    {
        let intent = crate::neuron_effect_bootstrap::bootstrap_durable_neuron_effect_intent_v1(
            &intent_path,
            scope,
            generation,
            32,
        )
        .expect("real original empty intent WAL");
        assert_eq!(intent.status().durable_records, 0);
        let sink = DurablePhaseMetricSinkV1::open(&evidence_path, 8, 2, 100)
            .expect("real original Evidence writer");
        sink.record(PhaseMetricEventV1 {
            scope_digest: scope.scope_digest,
            operation_digest: Digest32::of_bytes(b"one-durable-original-operation"),
            phase: PhaseMetricKindV1::NeuronFeature,
            latency_micros: 7,
            succeeded: false,
        })
        .expect("admit original Evidence record");
        sink.flush().expect("fsynced group");
        let observed = sink.read_local_frontier().expect("original WAL readback");
        assert_eq!(observed.committed_rows, 1);
        assert!(matches!(
            require_recovered_effect_metrics_floor_v1(intent.status(), observed),
            Err(NeuronProductionBootstrapErrorV1::NotReady)
        ));
    }

    // This is a REAL cold reopen of both original protected owners, not an
    // invented frontier object. The negative gate must survive process-like
    // owner teardown and exact same-inode WAL replay without writing a new
    // Final-use nonce or invoking a model backend.
    require_existing_effect_metrics_v1(&intent_path, &evidence_path)
        .expect("both original journals remain present");
    let before_intent = std::fs::read(&intent_path).expect("original intent bytes");
    let before_evidence = std::fs::read(&evidence_path).expect("original Evidence bytes");
    {
        let recovered = crate::neuron_effect_bootstrap::bootstrap_durable_neuron_effect_intent_v1(
            &intent_path,
            scope,
            generation,
            32,
        )
        .expect("cold original intent replay");
        let reopened = DurablePhaseMetricSinkV1::open(&evidence_path, 8, 2, 100)
            .expect("cold original Evidence replay");
        let recovered_frontier = reopened
            .read_local_frontier()
            .expect("fully replayed original frontier");
        assert_eq!(recovered.status().durable_records, 0);
        assert_eq!(recovered_frontier.committed_rows, 1);
        assert!(matches!(
            require_recovered_effect_metrics_floor_v1(recovered.status(), recovered_frontier),
            Err(NeuronProductionBootstrapErrorV1::NotReady)
        ));
    }
    assert_eq!(
        std::fs::read(&intent_path).expect("immutable original intent"),
        before_intent
    );
    assert_eq!(
        std::fs::read(&evidence_path).expect("immutable original evidence"),
        before_evidence
    );
}

#[cfg(unix)]
#[test]
fn original_wal_floor_refuses_unresolved_and_poisoned_effects_with_evidence() {
    use codex_hepta_neuron::NeuronEffectIntentStatusV1;
    use codex_hepta_types::Digest32;

    let evidence = MetricsLocalFrontierV1 {
        sequence: 1,
        head_digest: Digest32::of_bytes(b"committed-evidence"),
        committed_rows: 1,
        journal_bytes: 256,
        wal_device: 1,
        wal_inode: 2,
        marker_device: 1,
        marker_inode: 3,
    };
    let complete = NeuronEffectIntentStatusV1 {
        attempted_ticks: 1,
        durable_records: 2,
        unresolved_tick: None,
        poisoned: false,
    };
    require_recovered_effect_metrics_floor_v1(complete, evidence)
        .expect("this local floor is not independent serving authorization");
    assert!(matches!(
        require_recovered_effect_metrics_floor_v1(
            NeuronEffectIntentStatusV1 {
                durable_records: 3,
                attempted_ticks: 2,
                unresolved_tick: Some(Digest32::of_bytes(b"orphan-prepare")),
                ..complete
            },
            evidence
        ),
        Err(NeuronProductionBootstrapErrorV1::NotReady)
    ));
    assert!(matches!(
        require_recovered_effect_metrics_floor_v1(
            NeuronEffectIntentStatusV1 {
                poisoned: true,
                ..complete
            },
            evidence
        ),
        Err(NeuronProductionBootstrapErrorV1::NotReady)
    ));
}

#[cfg(unix)]
#[test]
fn actual_pending_original_prepare_stays_quarantined_after_cold_replay() {
    use codex_hepta_evidence::metrics_sink::DurablePhaseMetricSinkV1;
    use codex_hepta_types::Digest32;
    use codex_hepta_types::Generation;
    use codex_hepta_types::PhaseMetricEventV1;
    use codex_hepta_types::PhaseMetricKindV1;
    use codex_hepta_types::PhaseMetricSinkV1;
    use std::os::unix::fs::PermissionsExt;

    let root = tempfile::tempdir().expect("private original root");
    std::fs::set_permissions(root.path(), std::fs::Permissions::from_mode(0o700))
        .expect("private root permissions");
    let intent_path = root.path().join("effect-intent.wal");
    let evidence_path = root.path().join("original-evidence.wal");
    let scope = JournalScope {
        scope_digest: Digest32::of_bytes(b"scope"),
        objective_digest: Digest32::of_bytes(b"objective"),
    };
    let generation = Generation::new(1).expect("valid generation");
    let operation = Digest32::of_bytes(b"durably-prepared-tick");
    {
        let mut intent = crate::neuron_effect_bootstrap::bootstrap_durable_neuron_effect_intent_v1(
            &intent_path, scope, generation, 32,
        )
        .expect("protected business WAL");
        intent
            .prepare(operation, Digest32::ZERO)
            .expect("durable original Prepare without Resolve");
        let sink = DurablePhaseMetricSinkV1::open(&evidence_path, 8, 2, 100)
            .expect("original Evidence owner");
        sink.record(PhaseMetricEventV1 {
            scope_digest: scope.scope_digest,
            operation_digest: operation,
            phase: PhaseMetricKindV1::NeuronFeature,
            latency_micros: 17,
            succeeded: false,
        })
        .expect("original observer record");
        sink.flush().expect("original fsync");
    }
    let original_intent = std::fs::read(&intent_path).expect("durable intent bytes");
    let original_evidence = std::fs::read(&evidence_path).expect("durable Evidence bytes");
    require_existing_effect_metrics_v1(&intent_path, &evidence_path)
        .expect("both original journals remain present");

    {
        let recovered = crate::neuron_effect_bootstrap::bootstrap_durable_neuron_effect_intent_v1(
            &intent_path, scope, generation, 32,
        )
        .expect("real original intent replay");
        let evidence = DurablePhaseMetricSinkV1::open(&evidence_path, 8, 2, 100)
            .expect("real original Evidence replay");
        let frontier = evidence.read_local_frontier().expect("verified Evidence frontier");
        assert_eq!(frontier.committed_rows, 1);
        assert_eq!(recovered.status().unresolved_tick, Some(operation));
        assert_eq!(recovered.status().durable_records, 1);
        assert!(matches!(
            require_recovered_effect_metrics_floor_v1(recovered.status(), frontier),
            Err(NeuronProductionBootstrapErrorV1::NotReady)
        ));
    }
    assert_eq!(
        std::fs::read(&intent_path).expect("original bytes survive denial"),
        original_intent
    );
    assert_eq!(
        std::fs::read(&evidence_path).expect("original Evidence survives denial"),
        original_evidence
    );
}

#[cfg(unix)]
#[test]
fn resolved_original_tick_requires_exact_fsynchronized_neuron_evidence_membership() {
    use codex_hepta_evidence::metrics_sink::DurablePhaseMetricSinkV1;
    use codex_hepta_types::Digest32;
    use codex_hepta_types::Generation;
    use codex_hepta_types::PhaseMetricEventV1;
    use codex_hepta_types::PhaseMetricKindV1;
    use codex_hepta_types::PhaseMetricSinkV1;
    use std::os::unix::fs::PermissionsExt;

    let root = tempfile::tempdir().expect("private original journal root");
    std::fs::set_permissions(root.path(), std::fs::Permissions::from_mode(0o700))
        .expect("private permissions");
    let intent_path = root.path().join("effect-intent.wal");
    let evidence_path = root.path().join("original-evidence.wal");
    let scope = JournalScope {
        scope_digest: Digest32::of_bytes(b"original-scope"),
        objective_digest: Digest32::of_bytes(b"original-objective"),
    };
    let generation = Generation::new(1).expect("generation");
    let operation = Digest32::of_bytes(b"actually-resolved-business-tick");
    {
        let mut intent = crate::neuron_effect_bootstrap::bootstrap_durable_neuron_effect_intent_v1(
            &intent_path,
            scope,
            generation,
            32,
        )
        .expect("protected original Intent owner");
        intent
            .prepare(operation, Digest32::ZERO)
            .expect("durable original Prepare");
        intent
            .resolve(operation, Digest32::of_bytes(b"real-next-checkpoint"))
            .expect("durable original Resolve");
        let completed = intent
            .completed_tick_digests_v1()
            .expect("only fully resolved original identities");
        assert_eq!(completed, vec![operation]);
        let sink = DurablePhaseMetricSinkV1::open(&evidence_path, 8, 2, 100)
            .expect("original WAL group-commit owner");
        sink.record(PhaseMetricEventV1 {
            scope_digest: scope.scope_digest,
            operation_digest: Digest32::of_bytes(b"unrelated-metric-tick"),
            phase: PhaseMetricKindV1::NeuronFeature,
            latency_micros: 7,
            succeeded: true,
        })
        .expect("unrelated original observation");
        sink.flush().expect("original Evidence fsync");
        let unrelated_frontier = sink.read_local_frontier().expect("original frontier");
        assert!(matches!(
            require_completed_effect_evidence_membership_v1(
                &sink,
                scope,
                unrelated_frontier,
                &completed
            ),
            Err(NeuronProductionBootstrapErrorV1::NotReady)
        ));

        sink.record(PhaseMetricEventV1 {
            scope_digest: scope.scope_digest,
            operation_digest: operation,
            phase: PhaseMetricKindV1::NeuronFeature,
            latency_micros: 8,
            succeeded: true,
        })
        .expect("exact original tick observation");
        sink.flush().expect("fsynced exact original Evidence");
        let complete_frontier = sink.read_local_frontier().expect("complete frontier");
        require_completed_effect_evidence_membership_v1(
            &sink,
            scope,
            complete_frontier,
            &completed,
        )
        .expect("one exact resolved original operation has a matching group-committed sample");
    }

    // The same exact operation identity must be verified again after BOTH
    // separate original WAL owners close and replay their real bytes.
    let recovered = crate::neuron_effect_bootstrap::bootstrap_durable_neuron_effect_intent_v1(
        &intent_path,
        scope,
        generation,
        32,
    )
    .expect("real original Effect recovery");
    let evidence = DurablePhaseMetricSinkV1::open(&evidence_path, 8, 2, 100)
        .expect("real original Evidence recovery");
    let identities = recovered
        .completed_tick_digests_v1()
        .expect("read-only completed ID replay");
    let frontier = evidence.read_local_frontier().expect("original marker readback");
    require_completed_effect_evidence_membership_v1(&evidence, scope, frontier, &identities)
        .expect("exact membership survives actual cold reopening");

    // Two matching rows for one already-resolved tick are ambiguous.
    evidence
        .record(PhaseMetricEventV1 {
            scope_digest: scope.scope_digest,
            operation_digest: operation,
            phase: PhaseMetricKindV1::NeuronFeature,
            latency_micros: 9,
            succeeded: true,
        })
        .expect("duplicate original observation in test fixture");
    evidence.flush().expect("fsynced duplicate fixture");
    let duplicated = evidence.read_local_frontier().expect("new frontier");
    assert!(matches!(
        require_completed_effect_evidence_membership_v1(
            &evidence,
            scope,
            duplicated,
            &identities
        ),
        Err(NeuronProductionBootstrapErrorV1::NotReady)
    ));
}
