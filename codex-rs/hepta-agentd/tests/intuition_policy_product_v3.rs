// Shared signed policy/ledger material; behavioral tests remain in this target.
include!("support/intuition_policy_fixture.rs");

#[test]
#[allow(
    clippy::expect_used,
    reason = "Test setup and success assertions intentionally fail the test on unexpected errors."
)]
fn v3_product_host_commits_once_replays_idempotently_and_reopens() {
    for candidate_count in [1, codex_hepta_agentd::MAX_PRODUCT_INTUITION_CANDIDATES] {
        let agent_id = AgentId::parse("019153a4-3088-7e03-a56a-9b1964f75dde").expect("agent id");
        let (mut request, profile) = request_and_profile();
        let candidate = request.candidates[0].clone();
        request.candidates = (0..candidate_count)
            .map(|index| {
                let mut candidate = candidate.clone();
                candidate.candidate_id = id(&format!("candidate:{index:03}"));
                candidate
            })
            .collect();
        request.completeness.candidate_count = candidate_count as u32;
        request.completeness.candidate_set_digest =
            canonical_candidate_set_digest_v1(&request.candidates).expect("candidate set");
        request.completeness.canonical_order_digest =
            canonical_candidate_order_digest_v1(&request.candidates).expect("candidate order");
        let (scoring, assignment) = commitments(&request, &profile);
        let (activated, verifier, keys, principals) = trust_material();

        let directory = tempdir().expect("ledger directory");
        let ledger_path = directory.path().join("ledger");
        let witness_path = directory.path().join("witness");
        File::create(&ledger_path).expect("ledger file");
        File::create(&witness_path).expect("witness file");
        let binding = digest("binding:intuition-product-v3");
        let ledger = DurableLedger::create(open_rw(&ledger_path), binding, 64).expect("ledger");
        let witness = LedgerWitnessStore::create(open_rw(&witness_path), binding).expect("witness");
        let ledger_directory = File::open(directory.path()).expect("ledger parent");
        let witness_directory = File::open(directory.path()).expect("witness parent");
        let writer = LedgerWriter::from_durable(
            ledger,
            witness,
            activated,
            &ledger_directory,
            &witness_directory,
        )
        .expect("product ledger writer");
        let clock = Arc::new(TestIntuitionClock::new(NOW));
        let learning = Arc::new(IntuitionPolicyLearningSink::new_with_clock(
            writer,
            clock.clone(),
        ));
        let pins = AgentdIntuitionPolicyPinsV2 {
            policy_profile_digest: canonical_policy_profile_digest_v1(&profile)
                .expect("profile digest"),
            policy_digest: profile.policy_digest,
            policy_generation: PolicyGeneration::new(GENERATION).expect("generation"),
            objective_class_digest: profile.objective_class_digest,
            model_artifact_digest: profile.scorer.model_digest,
            scorer_contract_digest: profile.scorer.scorer_contract_digest,
            calibration_artifact_digest: profile.calibration_artifact_digest,
            ood_artifact_digest: profile.ood_artifact_digest,
            risk_rule_digest: intuition_risk_rule_digest_v1(profile.risk_rule),
            rng_owner_digest: None,
        };
        let host = AgentdIntuitionPolicyHostV1::new_product(
            agent_id.clone(),
            SPAWN_GENERATION,
            verifier.clone(),
            pins,
            learning.clone(),
        )
        .expect("product host");

        let completeness_payload =
            canonical_completeness_evidence_payload_v1(&request).expect("completeness payload");
        let profile_payload =
            canonical_profile_qualification_payload_v1(&profile).expect("profile payload");
        let runtime_payload =
            canonical_runtime_commitment_payload_v2(&request, &profile, &scoring, &assignment)
                .expect("runtime payload");
        let completeness = sign_evidence(
            &verifier,
            &principals[0],
            &keys[0],
            LearningEvidenceRoleV1::Generator,
            "evidence:completeness:v3",
            &completeness_payload,
        );
        let profile_evidence = sign_evidence(
            &verifier,
            &principals[1],
            &keys[1],
            LearningEvidenceRoleV1::Evaluator,
            "evidence:profile:v3",
            &profile_payload,
        );
        let runtime_evidence = sign_evidence(
            &verifier,
            &principals[2],
            &keys[2],
            LearningEvidenceRoleV1::Observer,
            "evidence:runtime:v3",
            &runtime_payload,
        );

        let qualification = || IntuitionQualificationEvidenceV2 {
            completeness: &completeness,
            profile_qualification: &profile_evidence,
            runtime: &runtime_evidence,
        };

        if candidate_count == codex_hepta_agentd::MAX_PRODUCT_INTUITION_CANDIDATES {
            let mut oversized = request.clone();
            let mut extra = oversized.candidates[0].clone();
            extra.candidate_id = id("candidate:overflow");
            oversized.candidates.push(extra);
            // Deliberately stale commitments and an invalid profile prove rejection
            // precedes cloning, pin hashing and qualification cryptography.
            let mut invalid_profile = profile.clone();
            invalid_profile.policy_digest = Digest32::ZERO;
            assert!(matches!(
                host.prepare_v3(
                    &agent_id,
                    SPAWN_GENERATION,
                    oversized,
                    invalid_profile,
                    scoring.clone(),
                    assignment.clone(),
                    qualification(),
                    id("episode:intuition-product-v3"),
                    digest("run-snapshot:intuition-product-v3"),
                    NOW,
                ),
                Err(AgentdIntuitionPolicyError::ProductCandidateLimit)
            ));
        }

        let mut drifted_profile = profile.clone();
        drifted_profile.calibration_dataset_digest = digest("calibration-data:drifted");
        assert!(matches!(
            host.prepare_v3(
                &agent_id,
                SPAWN_GENERATION,
                request.clone(),
                drifted_profile,
                scoring.clone(),
                assignment.clone(),
                qualification(),
                id("episode:intuition-product-v3"),
                digest("run-snapshot:intuition-product-v3"),
                NOW,
            ),
            Err(AgentdIntuitionPolicyError::ProfilePinMismatch)
        ));
        assert!(matches!(
            host.prepare_v3(
                &agent_id,
                SPAWN_GENERATION + 1,
                request.clone(),
                profile.clone(),
                scoring.clone(),
                assignment.clone(),
                qualification(),
                id("episode:intuition-product-v3"),
                digest("run-snapshot:intuition-product-v3"),
                NOW,
            ),
            Err(AgentdIntuitionPolicyError::GenerationFence)
        ));

        let prepared = host
            .prepare_v3(
                &agent_id,
                SPAWN_GENERATION,
                request,
                profile,
                scoring,
                assignment,
                qualification(),
                id("episode:intuition-product-v3"),
                digest("run-snapshot:intuition-product-v3"),
                NOW,
            )
            .expect("prepared V3 decision");
        assert!(matches!(
            prepared.decision().decision.disposition,
            ProductionDispositionV1::Selected(_)
        ));
        let production = prepared
            .production_decision()
            .expect("selected decision has a durable ledger projection");
        assert_eq!(
            production.completeness.candidate_count,
            candidate_count as u32 + 1
        );
        assert!(
            production
                .candidate_ids
                .iter()
                .any(|candidate| candidate.as_str() == "abstain")
        );
        let decision_payload = prepared
            .decision_signing_payload()
            .expect("decision payload result")
            .expect("selected decision payload");
        let decision_evidence = sign_evidence(
            &verifier,
            &principals[0],
            &keys[0],
            LearningEvidenceRoleV1::Generator,
            "evidence:durable-decision:v3",
            &decision_payload,
        );
        let replay_prepared = prepared.clone();
        let first = host
            .commit_v4(
                &agent_id,
                SPAWN_GENERATION,
                prepared,
                Digest32::ZERO,
                Some(decision_evidence.clone()),
            )
            .expect("first durable commit");
        clock.set(NOW + 1);
        let replay = host
            .commit_v4(
                &agent_id,
                SPAWN_GENERATION,
                replay_prepared,
                Digest32::ZERO,
                Some(decision_evidence),
            )
            .expect("idempotent durable replay");
        let first_append = first.learning.as_ref().expect("first append receipt");
        let replay_append = replay.learning.as_ref().expect("replay append receipt");
        assert_eq!(first_append.disposition, AppendDisposition::Appended);
        assert_eq!(
            replay_append.disposition,
            AppendDisposition::IdempotentReplay
        );
        assert_eq!(first_append.event_digest, replay_append.event_digest);
        assert_eq!(first_append.chain_digest, replay_append.chain_digest);
        assert_eq!(first_append.sequence, replay_append.sequence);
        assert_eq!(first.production_record_id, replay.production_record_id);

        let anchor = LedgerAnchor {
            sequence: first_append.sequence.get(),
            chain_digest: first_append.chain_digest,
        };
        drop(host);
        drop(learning);

        let recovered_ledger = DurableLedger::recover(
            open_rw(&ledger_path),
            binding,
            64,
            LedgerRecovery::Acknowledged(anchor),
        )
        .expect("recovered ledger");
        let recovered_witness = LedgerWitnessStore::recover(open_rw(&witness_path), binding)
            .expect("recovered witness");
        let (recovered_trust, _, _, _) = trust_material();
        let ledger_directory = File::open(directory.path()).expect("recovered ledger parent");
        let witness_directory = File::open(directory.path()).expect("recovered witness parent");
        let reopened = LedgerWriter::from_durable(
            recovered_ledger,
            recovered_witness,
            recovered_trust,
            &ledger_directory,
            &witness_directory,
        )
        .expect("reopened writer");
        let records = reopened.records().expect("reopened records");
        assert_eq!(records.len(), 1, "idempotent replay appended a duplicate");
        assert_eq!(reopened.snapshot().expect("snapshot").records().len(), 1);
    }
}

#[test]
#[allow(
    clippy::expect_used,
    reason = "Test setup and success assertions intentionally fail the test on unexpected errors."
)]
fn v3_product_rejects_evaluator_observer_controller_collision_despite_distinct_keys() {
    let (_, verifier, keys, principals) = trust_material_with_options(
        "controller:evaluator",
        /*generator_revoked_at*/ None,
        /*distribution_expires_at*/ 900,
    );
    let (request, profile) = request_and_profile();
    let (scoring, assignment) = commitments(&request, &profile);
    let completeness = sign_evidence(
        &verifier,
        &principals[0],
        &keys[0],
        LearningEvidenceRoleV1::Generator,
        "completeness:controller-collision",
        &canonical_completeness_evidence_payload_v1(&request).expect("completeness"),
    );
    let qualification = sign_evidence(
        &verifier,
        &principals[1],
        &keys[1],
        LearningEvidenceRoleV1::Evaluator,
        "qualification:controller-collision",
        &canonical_profile_qualification_payload_v1(&profile).expect("profile"),
    );
    let runtime = sign_evidence(
        &verifier,
        &principals[2],
        &keys[2],
        LearningEvidenceRoleV1::Observer,
        "runtime:controller-collision",
        &canonical_runtime_commitment_payload_v2(&request, &profile, &scoring, &assignment)
            .expect("runtime"),
    );
    let error = codex_hepta_intelligence::decide_authenticated_intuition_v3(
        request,
        profile,
        scoring,
        assignment,
        IntuitionQualificationEvidenceV2 {
            completeness: &completeness,
            profile_qualification: &qualification,
            runtime: &runtime,
        },
        &verifier,
        NOW,
    )
    .expect_err("same controller must not self-qualify independent runtime evidence");
    assert!(matches!(
        error,
        codex_hepta_intelligence::IntuitionQualificationErrorV3::Evidence(
            codex_hepta_learning_ledger::SignedEvidenceError::ControllerCollision
        )
    ));
}
