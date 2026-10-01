use super::*;
use crate::intelligence_product::evaluation_tests::evidence_fixture;
use codex_hepta_intelligence::build_legal_candidates;

pub(super) fn signed_fixture() -> (
    Fixture,
    codex_hepta_learning_ledger::ActivatedLearningTrustV1,
) {
    let mut value = fixture();
    let key = SigningKey::from_bytes(&[47; 32]);
    for owner in &mut value.owners {
        if owner.owner_id.as_str() == "learning.eval" {
            owner.key_digest = Digest32::of_bytes(&key.verifying_key().to_bytes());
        }
    }
    let snapshot = &value.request.snapshot;
    value.request.snapshot = CanonicalIntelligenceSnapshotV1::admit(CanonicalSnapshotRequestV1 {
        objective_digest: snapshot.objective_digest(),
        authority_epoch: snapshot.authority_epoch(),
        body_generation: snapshot.body_generation(),
        configuration_digest: snapshot.configuration_digest(),
        revocation_frontier_digest: snapshot.revocation_frontier_digest(),
        owner_bindings: value.owners.clone(),
    })
    .expect("snapshot with real test evaluator key");
    value.inputs.context_request.run_snapshot_digest = value.request.snapshot.digest();
    let context = compile(value.inputs.context_request.clone()).expect("context compilation");
    let legal = build_legal_candidates(value.request.legal_candidates.clone()).expect("legal set");
    let binding = AgentdEvaluationBindingV1 {
        run_id: value.request.run_id.clone(),
        objective_digest: value.request.snapshot.objective_digest(),
        snapshot_digest: value.request.snapshot.digest(),
        context_receipt_digest: context.context_digest,
        candidate_set_digest: legal.candidate_set_digest,
        selected_candidate_id: id("action.read"),
    };
    let (trust, signed) = evidence_fixture(&binding, wall_clock_ms().expect("clock"));
    value.inputs.signed_evaluation = Some(signed);
    (value, trust)
}

fn signed_authority_profile(
    directory: &tempfile::TempDir,
    value: &Fixture,
) -> (PathBuf, Arc<crate::IntelligenceAuthorityRollbackGuardV1>) {
    // Resolve the OS temporary-directory alias while provisioning the fixture.
    // The production reader must still reject every symlink at final use.
    let root = directory
        .path()
        .canonicalize()
        .expect("canonical test root");
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        std::fs::set_permissions(&root, std::fs::Permissions::from_mode(0o700))
            .expect("private rollback test root");
    }
    let path = root.join("authority.json");
    write_authority_file(
        &path,
        &value.owners,
        value.request.snapshot.revocation_frontier_digest(),
    );
    let manifest: IntelligenceAuthorityFileV1 =
        serde_json::from_slice(&std::fs::read(&path).expect("manifest bytes")).expect("manifest");
    let guard = crate::IntelligenceAuthorityRollbackGuardV1::open(
        &root.join("authority-floor.json"),
        manifest.authority_epoch,
        intelligence_authority_manifest_digest_v1(&manifest).expect("manifest identity"),
    )
    .expect("independently provisioned test floor");
    (path, Arc::new(guard))
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn signed_evaluation_completes_existing_owner_preparation_and_run_admission() {
    let (value, trust) = signed_fixture();
    let directory = tempfile::tempdir().expect("directory");
    let (path, guard) = signed_authority_profile(&directory, &value);
    let runner = AgentdIntelligenceProductRunnerV1::new(path, authority_verifier())
        .expect("runner")
        .with_authority_rollback_guard(guard)
        .expect("host rollback witness")
        .with_hard_timeout_process_exit(Duration::from_secs(5))
        .expect("hard timeout process fence")
        .with_evaluation_trust(trust)
        .expect("host-root trust");
    assert!(runner.canonical_profile_ready());
    let mut coordinator = product_test_coordinator();
    let outcome = runner
        .prepare_and_admit(&mut coordinator, value.request, value.inputs)
        .await
        .expect("signed preparation");
    let AgentdIntelligenceAdmittedOutcomeV1::Ready {
        prepared,
        run_receipt,
    } = outcome
    else {
        panic!("expected the signed existing path to reach ready");
    };
    assert!(!prepared.envelope.evaluation_receipt_digest.is_zero());
    assert!(!prepared.envelope.authority.grants_any());
    assert_eq!(run_receipt.run_id, prepared.run_snapshot().run_id);
    assert_eq!(run_receipt.phase, crate::RunPhase::ContextAttached);
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn signed_input_cannot_install_host_trust_or_change_actual_context() {
    let (value, _) = signed_fixture();
    let directory = tempfile::tempdir().expect("directory");
    let (path, guard) = signed_authority_profile(&directory, &value);
    let runner = AgentdIntelligenceProductRunnerV1::new(path.clone(), authority_verifier())
        .expect("runner")
        .with_authority_rollback_guard(Arc::clone(&guard))
        .expect("host rollback witness");
    assert!(matches!(
        runner
            .prepare(&product_test_coordinator(), value.request, value.inputs)
            .await,
        Err(AgentdIntelligenceProductError::Canonical(
            CanonicalIntelligenceError::FreshnessUnavailable(_)
        ))
    ));

    let (mut value, trust) = signed_fixture();
    value.inputs.context_request.items[0].content_digest = digest("substituted-context");
    let runner = AgentdIntelligenceProductRunnerV1::new(path, authority_verifier())
        .expect("runner")
        .with_authority_rollback_guard(guard)
        .expect("host rollback witness")
        .with_evaluation_trust(trust)
        .expect("trust");
    assert!(matches!(
        runner
            .prepare(&product_test_coordinator(), value.request, value.inputs)
            .await,
        Err(AgentdIntelligenceProductError::Canonical(
            CanonicalIntelligenceError::PortFailure {
                stage: CanonicalStageV1::EvaluationAdmitted,
                ..
            }
        ))
    ));
}

#[test]
#[ignore = "qualification-host timing probe"]
fn qualification_authority_signature_verification_profile() {
    const ITERATIONS_ENV: &str = "HEPTA_INTELLIGENCE_SIGNATURE_PROFILE_ITERATIONS";
    const OUTPUT_ENV: &str = "HEPTA_INTELLIGENCE_SIGNATURE_PROFILE_OUTPUT";

    let (value, _) = signed_fixture();
    let directory = tempfile::tempdir().expect("directory");
    let (path, _guard) = signed_authority_profile(&directory, &value);
    let manifest: IntelligenceAuthorityFileV1 =
        serde_json::from_slice(&std::fs::read(path).expect("manifest bytes")).expect("manifest");
    let verifier = authority_verifier();
    let requested = id("objective.compiler");
    let iterations = std::env::var(ITERATIONS_ENV)
        .ok()
        .and_then(|value| value.parse::<usize>().ok())
        .unwrap_or(1_000)
        .clamp(1, 100_000);
    let mut samples_nanos = Vec::with_capacity(iterations);
    for _ in 0..iterations {
        let started = std::time::Instant::now();
        verify_authority_file(&manifest, &verifier, &requested).expect("strict verification");
        samples_nanos.push(
            u64::try_from(started.elapsed().as_nanos()).expect("verification duration fits u64"),
        );
    }
    assert_eq!(samples_nanos.len(), iterations);
    if let Some(path) = std::env::var_os(OUTPUT_ENV) {
        let record = serde_json::json!({
            "schema": "hepta.intelligence-control.signature-profile.v1",
            "iterations": iterations,
            "samplesNanos": samples_nanos,
        });
        std::fs::write(
            path,
            serde_json::to_vec_pretty(&record).expect("encode signature profile"),
        )
        .expect("write signature profile");
    }
}
