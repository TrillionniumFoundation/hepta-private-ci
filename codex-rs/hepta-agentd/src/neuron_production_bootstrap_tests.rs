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
