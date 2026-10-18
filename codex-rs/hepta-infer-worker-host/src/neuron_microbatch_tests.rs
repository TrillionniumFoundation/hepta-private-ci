use super::*;

use std::collections::BTreeSet;
use std::fs::OpenOptions;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseGrant;
use codex_hepta_contracts::FinalUseRevocations;
use codex_hepta_contracts::SignedFinalUseGrant;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

static NEXT: AtomicU64 = AtomicU64::new(0);

struct Fixture(std::path::PathBuf);

impl Fixture {
    fn new() -> Self {
        let serial = NEXT.fetch_add(1, Ordering::Relaxed);
        Self(std::env::temp_dir().join(format!(
            "hepta-neuron-worker-microbatch-{}-{serial}",
            std::process::id()
        )))
    }

    fn open(&self) -> std::fs::File {
        OpenOptions::new()
            .read(true)
            .write(true)
            .create(true)
            .truncate(false)
            .open(&self.0)
            .expect("file")
    }
}

impl Drop for Fixture {
    fn drop(&mut self) {
        let _ = std::fs::remove_file(&self.0);
    }
}

fn id(s: &str) -> StableId {
    StableId::new(s).expect("id")
}

fn generation() -> Generation {
    Generation::new(1).expect("generation")
}

fn scope() -> Digest32 {
    Digest32::of_bytes(b"scope")
}

fn snapshot() -> Arc<NeuronFrozenFeatureV1> {
    Arc::new(
        NeuronFrozenFeatureV1::freeze(
            NeuronSnapshotIdentityV1 {
                subject_id: id("test.neuron"),
                scope_digest: scope(),
                ndu_snapshot_digest: Digest32::of_bytes(b"ndu"),
                generation: generation(),
                authority_epoch: 1,
                encoder_digest: Digest32::of_bytes(b"encoder"),
                tokenizer_digest: Digest32::of_bytes(b"tokenizer"),
                normalizer_digest: Digest32::of_bytes(b"normalizer"),
                source_digest: Digest32::of_bytes(b"source"),
            },
            vec![11, 22, 33],
        )
        .expect("snapshot"),
    )
}

fn heads() -> Vec<NeuronBatchHeadV1> {
    (0..4)
        .map(|i| NeuronBatchHeadV1 {
            request_id: id(&format!("request.{i}")),
            reservation_id: id(&format!("reservation.{i}")),
            head_digest: Digest32::of_bytes(&[i]),
            expected_width: 3,
        })
        .collect()
}

fn plan() -> NeuronMicrobatchPlanV1 {
    NeuronMicrobatchPlanV1::freeze(id("worker.1"), snapshot(), 2_000, heads()).expect("plan")
}

fn make_worker(fixture: &Fixture) -> NeuronMicrobatchWorkerV1 {
    NeuronMicrobatchWorkerV1::new(
        id("worker.1"),
        generation(),
        scope(),
        NeuronMetricsGroupCommitWriterV1::open(fixture.open(), scope(), generation())
            .expect("metrics"),
    )
    .expect("worker")
}

fn make_authorized_worker(
    fixture: &Fixture,
    authority: FinalUseAuthority,
) -> NeuronMicrobatchWorkerV1 {
    NeuronMicrobatchWorkerV1::new_authorized(
        id("worker.1"),
        generation(),
        scope(),
        NeuronMetricsGroupCommitWriterV1::open(fixture.open(), scope(), generation())
            .expect("metrics"),
        authority,
    )
    .expect("trusted worker construction")
}

#[test]
fn reference_worker_executes_exactly_one_batch_and_commits_metrics() {
    let fixture = Fixture::new();
    let mut worker = make_worker(&fixture);
    let mut backend = ReferenceNeuronBatchBackendV1::default();
    let plan = plan();
    let result = worker
        .run_reference(
            1_000,
            &plan,
            &mut backend,
            NeuronHostResourceSampleV1::default(),
        )
        .expect("execute");
    assert_eq!(backend.batch_invocations, 1);
    assert_eq!(result.results.len(), 4);
    assert_eq!(result.metric_sequence, 1);
    assert!(!result.authority.grants_any());
    assert!(matches!(
        worker.run_reference(
            1_000,
            &plan,
            &mut backend,
            NeuronHostResourceSampleV1::default()
        ),
        Err(NeuronMicrobatchErrorV1::PlanReplayed)
    ));
    assert_eq!(backend.batch_invocations, 1);
    drop(worker);
    let mut reopened = make_worker(&fixture);
    let mut after_restart_backend = ReferenceNeuronBatchBackendV1::default();
    assert!(matches!(
        reopened.run_reference(
            1_000,
            &plan,
            &mut after_restart_backend,
            NeuronHostResourceSampleV1::default()
        ),
        Err(NeuronMicrobatchErrorV1::PlanReplayed)
    ));
    assert_eq!(after_restart_backend.batch_invocations, 0);
}

#[test]
fn rejects_generation_deadline_and_duplicate_reservations_before_backend() {
    let fixture = Fixture::new();
    let mut worker = make_worker(&fixture);
    let mut backend = ReferenceNeuronBatchBackendV1::default();
    let p = plan();
    assert!(matches!(
        worker.run_reference(
            2_000,
            &p,
            &mut backend,
            NeuronHostResourceSampleV1::default()
        ),
        Err(NeuronMicrobatchErrorV1::DeadlineExpired)
    ));
    assert_eq!(backend.batch_invocations, 0);
    let mut duplicate = heads();
    duplicate[1].reservation_id = duplicate[0].reservation_id.clone();
    assert!(matches!(
        NeuronMicrobatchPlanV1::freeze(id("worker.1"), snapshot(), 3_000, duplicate),
        Err(NeuronMicrobatchErrorV1::DuplicateReservation)
    ));
    let mut other_identity = snapshot().identity().clone();
    other_identity.generation = Generation::new(2).expect("gen2");
    let different = NeuronFrozenFeatureV1::freeze(other_identity, vec![11, 22, 33])
        .expect("new generation snapshot");
    let alternate =
        NeuronMicrobatchPlanV1::freeze(id("worker.1"), Arc::new(different), 3_000, heads())
            .expect("plan");
    assert!(matches!(
        worker.run_reference(
            1_000,
            &alternate,
            &mut backend,
            NeuronHostResourceSampleV1::default()
        ),
        Err(NeuronMicrobatchErrorV1::GenerationMismatch)
    ));
}

struct BadBackend {
    invocations: usize,
}

impl NeuronMicrobatchBackendV1 for BadBackend {
    fn execute_batch(
        &mut self,
        _snapshot: &NeuronFrozenFeatureV1,
        heads: &[NeuronBatchHeadV1],
    ) -> Result<Vec<NeuronBatchHeadResultV1>, NeuronMicrobatchErrorV1> {
        self.invocations += 1;
        let mut results = heads
            .iter()
            .map(|head| NeuronBatchHeadResultV1 {
                request_id: head.request_id.clone(),
                head_digest: head.head_digest,
                drive_q24: vec![0; head.expected_width],
                prediction_q24: vec![0; head.expected_width],
                elapsed_micros: 1,
            })
            .collect::<Vec<_>>();
        results.swap(0, 1);
        Ok(results)
    }
}

#[test]
fn adversarial_backend_reordering_fails_closed_and_never_commits_metric() {
    let fixture = Fixture::new();
    let mut worker = make_worker(&fixture);
    let mut backend = BadBackend { invocations: 0 };
    let p = plan();
    assert!(matches!(
        worker.execute(
            1_000,
            &p,
            &mut backend,
            NeuronHostResourceSampleV1::default()
        ),
        Err(NeuronMicrobatchErrorV1::BackendOutputMismatch)
    ));
    assert_eq!(backend.invocations, 1);
    assert!(matches!(
        worker.execute(
            1_000,
            &p,
            &mut backend,
            NeuronHostResourceSampleV1::default()
        ),
        Err(NeuronMicrobatchErrorV1::PlanReplayed)
    ));
    drop(worker);
    let mut reopened = make_worker(&fixture);
    let mut fixture_backend = ReferenceNeuronBatchBackendV1::default();
    assert_eq!(
        reopened
            .run_reference(
                1_000,
                &p,
                &mut fixture_backend,
                NeuronHostResourceSampleV1::default()
            )
            .expect("metric not acknowledged")
            .metric_sequence,
        1
    );
}

#[test]
fn native_batch_authority_claims_exact_ndu_and_prevents_unauthorized_backend_use() {
    let root = tempfile::tempdir().expect("authority directory");
    let fixture = Fixture::new();
    let signing = SigningKey::from_bytes(&[12_u8; 32]);
    let authority = FinalUseAuthority::open_state_dir(
        &root.path().join("authority"),
        "neuron.batch.issuer".to_owned(),
        signing.verifying_key().to_bytes(),
        FinalUseRevocations {
            authority_epoch: 1,
            revision: 1,
            revoked_grant_ids: BTreeSet::new(),
        },
    )
    .expect("trusted verifier");
    let now = u64::try_from(
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .expect("epoch")
            .as_millis(),
    )
    .expect("millis");
    let plan = NeuronMicrobatchPlanV1::freeze(id("worker.1"), snapshot(), now + 60_000, heads())
        .expect("plan");
    let grant = FinalUseGrant {
        schema_version: 1,
        signer_id: "neuron.batch.issuer".into(),
        authority_epoch: 1,
        grant_id: "neuron.batch.grant.1".into(),
        nonce: [27; 32],
        binding: plan.final_use_binding(),
        not_before_unix_ms: now.saturating_sub(1_000),
        expires_at_unix_ms: now + 30_000,
    };
    let signed = SignedFinalUseGrant {
        signature: signing
            .sign(&grant.signing_bytes().expect("bytes"))
            .to_bytes()
            .to_vec(),
        grant,
    };
    let mut owner = make_authorized_worker(&fixture, authority.clone());
    let mut backend = ReferenceNeuronBatchBackendV1::default();

    let mut altered = snapshot().identity().clone();
    altered.ndu_snapshot_digest = Digest32::of_bytes(b"ndu.tampered");
    let altered_snapshot =
        NeuronFrozenFeatureV1::freeze(altered, vec![11, 22, 33]).expect("altered snapshot");
    let tampered = NeuronMicrobatchPlanV1::freeze(
        id("worker.1"),
        Arc::new(altered_snapshot),
        now + 60_000,
        heads(),
    )
    .expect("altered plan");
    assert!(
        owner
            .run_authorized(
                now,
                &tampered,
                &signed,
                &mut backend,
                NeuronHostResourceSampleV1::default()
            )
            .is_err()
    );
    assert_eq!(backend.batch_invocations, 0);

    let output = owner
        .run_authorized(
            now,
            &plan,
            &signed,
            &mut backend,
            NeuronHostResourceSampleV1::default(),
        )
        .expect("signed final-use");
    assert_eq!(backend.batch_invocations, 1);
    assert_eq!(output.metric_sequence, 2);
    assert!(!output.authority.grants_any());

    assert!(
        owner
            .run_authorized(
                now,
                &plan,
                &signed,
                &mut backend,
                NeuronHostResourceSampleV1::default()
            )
            .is_err()
    );
    assert_eq!(backend.batch_invocations, 1);
}

#[test]
fn signed_batch_expiry_must_not_outlive_plan_deadline() {
    let root = tempfile::tempdir().expect("authority");
    let fixture = Fixture::new();
    let signing = SigningKey::from_bytes(&[13_u8; 32]);
    let authority = FinalUseAuthority::open_state_dir(
        &root.path().join("authority"),
        "neuron.batch.issuer".to_owned(),
        signing.verifying_key().to_bytes(),
        FinalUseRevocations {
            authority_epoch: 1,
            revision: 1,
            revoked_grant_ids: BTreeSet::new(),
        },
    )
    .expect("verifier");
    let now = u64::try_from(
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .expect("epoch")
            .as_millis(),
    )
    .expect("millis");
    let plan = NeuronMicrobatchPlanV1::freeze(id("worker.1"), snapshot(), now + 10_000, heads())
        .expect("plan");
    let grant = FinalUseGrant {
        schema_version: 1,
        signer_id: "neuron.batch.issuer".into(),
        authority_epoch: 1,
        grant_id: "neuron.batch.late".into(),
        nonce: [28; 32],
        binding: plan.final_use_binding(),
        not_before_unix_ms: now.saturating_sub(1_000),
        expires_at_unix_ms: now + 20_000,
    };
    let signed = SignedFinalUseGrant {
        signature: signing
            .sign(&grant.signing_bytes().expect("bytes"))
            .to_bytes()
            .to_vec(),
        grant,
    };
    let mut owner = make_authorized_worker(&fixture, authority.clone());
    let mut backend = ReferenceNeuronBatchBackendV1::default();
    assert!(matches!(
        owner.run_authorized(
            now,
            &plan,
            &signed,
            &mut backend,
            NeuronHostResourceSampleV1::default()
        ),
        Err(NeuronMicrobatchErrorV1::InvalidPlan)
    ));
    assert_eq!(backend.batch_invocations, 0);
}

#[test]
fn fsynced_dispatch_intent_rejects_replay_after_worker_restart() {
    let fixture = Fixture::new();
    let pending = plan();
    let mut metrics = NeuronMetricsGroupCommitWriterV1::open(fixture.open(), scope(), generation())
        .expect("metrics");
    let receipt = metrics
        .record_dispatch_intent(pending.digest(), pending.size() as u32)
        .expect("durable pre-dispatch intent");
    assert_eq!(receipt.final_sequence, 1);
    drop(metrics);

    let mut restarted = make_worker(&fixture);
    let mut backend = ReferenceNeuronBatchBackendV1::default();
    assert!(matches!(
        restarted.run_reference(
            1_000,
            &pending,
            &mut backend,
            NeuronHostResourceSampleV1::default()
        ),
        Err(NeuronMicrobatchErrorV1::PlanReplayed)
    ));
    assert_eq!(backend.batch_invocations, 0);
}

#[test]
fn reference_worker_rejects_native_dispatch_without_pinned_verifier() {
    let fixture = Fixture::new();
    let mut owner = make_worker(&fixture);
    let mut custom_backend = BadBackend { invocations: 0 };
    let frozen = plan();
    let signed = SignedFinalUseGrant {
        grant: FinalUseGrant {
            schema_version: 1,
            signer_id: "neuron.batch.issuer".into(),
            authority_epoch: 1,
            grant_id: "neuron.batch.untrusted".into(),
            nonce: [46_u8; 32],
            binding: frozen.final_use_binding(),
            not_before_unix_ms: 100,
            expires_at_unix_ms: 1_000,
        },
        signature: vec![0; 64],
    };
    let error = owner.run_authorized(
        100,
        &frozen,
        &signed,
        &mut custom_backend,
        NeuronHostResourceSampleV1::default(),
    );
    assert!(matches!(
        error,
        Err(NeuronMicrobatchErrorV1::MissingAuthority)
    ));
    assert_eq!(custom_backend.invocations, 0);
}

#[test]
fn failed_signed_native_batch_leaves_durable_pending_intent_and_poisoned_owner() {
    let root = tempfile::tempdir().expect("authority directory");
    let fixture = Fixture::new();
    let signing = SigningKey::from_bytes(&[66_u8; 32]);
    let authority = FinalUseAuthority::open_state_dir(
        &root.path().join("authority"),
        "neuron.batch.issuer".to_owned(),
        signing.verifying_key().to_bytes(),
        FinalUseRevocations {
            authority_epoch: 1,
            revision: 1,
            revoked_grant_ids: BTreeSet::new(),
        },
    )
    .expect("verifier");
    let now = u64::try_from(
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .expect("epoch")
            .as_millis(),
    )
    .expect("millis");
    let frozen = NeuronMicrobatchPlanV1::freeze(id("worker.1"), snapshot(), now + 60_000, heads())
        .expect("plan");
    let grant = FinalUseGrant {
        schema_version: 1,
        signer_id: "neuron.batch.issuer".into(),
        authority_epoch: 1,
        grant_id: "neuron.batch.indeterminate".into(),
        nonce: [67_u8; 32],
        binding: frozen.final_use_binding(),
        not_before_unix_ms: now.saturating_sub(1_000),
        expires_at_unix_ms: now + 20_000,
    };
    let signed = SignedFinalUseGrant {
        signature: signing
            .sign(&grant.signing_bytes().expect("signing bytes"))
            .to_bytes()
            .to_vec(),
        grant,
    };
    let mut owner = make_authorized_worker(&fixture, authority);
    let mut malformed = BadBackend { invocations: 0 };
    assert!(matches!(
        owner.run_authorized(
            now,
            &frozen,
            &signed,
            &mut malformed,
            NeuronHostResourceSampleV1::default(),
        ),
        Err(NeuronMicrobatchErrorV1::BackendOutputMismatch)
    ));
    assert_eq!(malformed.invocations, 1);

    // A failed native outcome poisons this process owner.
    let mut reference = ReferenceNeuronBatchBackendV1::default();
    assert!(matches!(
        owner.run_reference(
            now,
            &frozen,
            &mut reference,
            NeuronHostResourceSampleV1::default(),
        ),
        Err(NeuronMicrobatchErrorV1::Poisoned)
    ));
    drop(owner);

    // The pre-dispatch intent was synced before invocation and survived
    // restart, so a new process cannot silently repeat unknown work.
    let mut recovered = make_worker(&fixture);
    assert!(matches!(
        recovered.run_reference(
            now,
            &frozen,
            &mut reference,
            NeuronHostResourceSampleV1::default(),
        ),
        Err(NeuronMicrobatchErrorV1::PlanReplayed)
    ));
    assert_eq!(reference.batch_invocations, 0);
}

#[test]
fn snapshot_freeze_rejects_non_q24_features_and_accepts_exact_boundaries() {
    let identity = snapshot().identity().clone();
    for invalid in [
        i64::MIN,
        -Q24_STATE_LIMIT - 1,
        Q24_STATE_LIMIT + 1,
        i64::MAX,
    ] {
        assert!(matches!(
            NeuronFrozenFeatureV1::freeze(identity.clone(), vec![invalid]),
            Err(NeuronMicrobatchErrorV1::InvalidSnapshot)
        ));
    }
    assert!(
        NeuronFrozenFeatureV1::freeze(identity, vec![-Q24_STATE_LIMIT, 0, Q24_STATE_LIMIT],)
            .is_ok()
    );
}

struct ExtremeOutputBackend {
    value: i64,
    corrupt_prediction: bool,
    invocations: u32,
}

impl NeuronMicrobatchBackendV1 for ExtremeOutputBackend {
    fn execute_batch(
        &mut self,
        _snapshot: &NeuronFrozenFeatureV1,
        heads: &[NeuronBatchHeadV1],
    ) -> Result<Vec<NeuronBatchHeadResultV1>, NeuronMicrobatchErrorV1> {
        self.invocations += 1;
        let mut outputs = heads
            .iter()
            .map(|head| NeuronBatchHeadResultV1 {
                request_id: head.request_id.clone(),
                head_digest: head.head_digest,
                drive_q24: vec![0; head.expected_width],
                prediction_q24: vec![0; head.expected_width],
                elapsed_micros: 1,
            })
            .collect::<Vec<_>>();
        if self.corrupt_prediction {
            outputs[0].prediction_q24[0] = self.value;
        } else {
            outputs[0].drive_q24[0] = self.value;
        }
        Ok(outputs)
    }
}

#[test]
fn backend_output_extremes_fail_closed_without_metrics_ack() {
    for (value, prediction) in [
        (i64::MIN, false),
        (-Q24_STATE_LIMIT - 1, true),
        (Q24_STATE_LIMIT + 1, false),
        (i64::MAX, true),
    ] {
        let fixture = Fixture::new();
        let mut worker = make_worker(&fixture);
        let mut backend = ExtremeOutputBackend {
            value,
            corrupt_prediction: prediction,
            invocations: 0,
        };
        let frozen = plan();
        assert!(matches!(
            worker.execute(
                1_000,
                &frozen,
                &mut backend,
                NeuronHostResourceSampleV1::default(),
            ),
            Err(NeuronMicrobatchErrorV1::BackendOutputMismatch)
        ));
        assert_eq!(backend.invocations, 1);
        assert_eq!(worker.metrics.recorded_sequence(), 0);
        assert!(matches!(
            worker.execute(
                1_000,
                &frozen,
                &mut backend,
                NeuronHostResourceSampleV1::default(),
            ),
            Err(NeuronMicrobatchErrorV1::PlanReplayed)
        ));
        assert_eq!(backend.invocations, 1);
    }
}
