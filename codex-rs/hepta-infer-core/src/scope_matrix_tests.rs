use super::*;

fn d(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn sample(scopes: usize) -> ScopeMatrixSampleV1 {
    let distribution = LatencyDistributionV1 {
        p50_micros: 10,
        p95_micros: 20,
        p99_micros: 30,
    };
    ScopeMatrixSampleV1 {
        scope_count: scopes,
        evidence_class: ScopeMatrixEvidenceClassV1::SourceFixture,
        source_head_digest: d("head"),
        runtime_manifest_digest: d("runtime"),
        target_host_digest: None,
        independent_observer_digest: None,
        total_requests: scopes as u64,
        terminal_requests: scopes as u64,
        indeterminate_requests: 0,
        model_latency: distribution,
        end_to_end_latency: distribution,
        journal_fsync_latency: distribution,
        witness_fsync_latency: distribution,
        queue_age_latency: distribution,
        cas_latency: None,
        signature_latency: None,
        cns_latency: None,
        lock_wait_latency: None,
        cpu_time_micros: 0,
        gpu_time_micros: None,
        npu_time_micros: None,
        write_amplification_ppm: 0,
        bytes_written: 500,
        journal_bytes: 300,
        communication_bytes: 100,
        peak_resident_bytes: 1_024,
        maximum_queue_depth: 1,
        replay_frames_per_second: 1,
    }
}

struct FixtureHost;

impl ScopeMatrixTargetV1 for FixtureHost {
    type Error = ();

    fn run_scope_count(&mut self, count: usize) -> Result<ScopeMatrixSampleV1, Self::Error> {
        Ok(sample(count))
    }
}

#[test]
fn requires_all_four_exact_scope_counts() {
    let samples = run_scope_matrix_v1(&mut FixtureHost).expect("fixture");
    let sizes: Vec<_> = samples.iter().map(|s| s.scope_count).collect();
    assert_eq!(sizes.as_slice(), SCOPE_MATRIX_V1.as_slice());
    assert!(samples.iter().all(|s| s.evidence_class == ScopeMatrixEvidenceClassV1::SourceFixture));
}

#[test]
fn cannot_mint_target_host_evidence_from_a_fixture() {
    let mut observation = sample(256);
    observation.evidence_class = ScopeMatrixEvidenceClassV1::TargetHost;
    assert_eq!(observation.validate(), Err(ScopeMatrixErrorV1::MissingHostEvidence));
    observation.target_host_digest = Some(d("host"));
    observation.independent_observer_digest = Some(d("host"));
    assert_eq!(observation.validate(), Err(ScopeMatrixErrorV1::MissingHostEvidence));
    observation.independent_observer_digest = Some(d("independent-observer"));
    observation.cpu_time_micros = 100;
    observation.write_amplification_ppm = 1_100_000;
    observation.cas_latency = Some(observation.model_latency);
    observation.signature_latency = Some(observation.model_latency);
    observation.cns_latency = Some(observation.model_latency);
    observation.lock_wait_latency = Some(observation.model_latency);
    assert!(observation.validate().is_ok());
}

#[test]
fn rejects_invalid_quantiles_and_unaccounted_requests() {
    let mut observation = sample(64);
    observation.model_latency.p99_micros = 1;
    assert_eq!(observation.validate(), Err(ScopeMatrixErrorV1::InvalidSample));
    let mut observation = sample(64);
    observation.indeterminate_requests = 1;
    assert_eq!(observation.validate(), Err(ScopeMatrixErrorV1::InvalidSample));
}

struct UnverifiedHost;

impl ScopeMatrixTargetV1 for UnverifiedHost {
    type Error = ();

    fn run_scope_count(&mut self, count: usize) -> Result<ScopeMatrixSampleV1, Self::Error> {
        let mut s = sample(count);
        s.evidence_class = ScopeMatrixEvidenceClassV1::TargetHost;
        s.target_host_digest = Some(d("host"));
        s.independent_observer_digest = Some(d("observer"));
        Ok(s)
    }
}

#[test]
fn self_asserted_host_digests_are_not_host_qualification() {
    assert!(matches!(
        run_scope_matrix_v1(&mut UnverifiedHost),
        Err(ScopeMatrixRunErrorV1::Contract(
            ScopeMatrixErrorV1::MissingHostEvidence
        ))
    ));
}

#[test]
fn untrusted_overflowed_counts_cannot_panic_or_pass() {
    let mut observation = sample(64);
    observation.terminal_requests = u64::MAX;
    observation.indeterminate_requests = 5;
    assert_eq!(
        observation.validate(),
        Err(ScopeMatrixErrorV1::InvalidSample)
    );
}
