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
    assert_eq!(sizes, SCOPE_MATRIX_V1);
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
