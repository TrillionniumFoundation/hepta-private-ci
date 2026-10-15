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

    std::fs::write(&effect, b"previous-effect-intent")
        .expect("restored previous intent bytes");
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
