//! Adversarial prepare/commit tests using the existing signed, durable fixture.
//! These exercise the product host, not a live Agentd process or operator approval.
// Reuse the exact trust/ledger fixture and retain its crash/reopen regression.
include!("intuition_policy_product_v3.rs");

#[test]
fn prepared_decision_rejects_every_changed_host_pin_before_writing() {
    let agent_id = AgentId::parse("019153a4-3088-7e03-a56a-9b1964f75dde").expect("agent");
    let (request, profile) = request_and_profile();
    let (scoring, assignment) = commitments(&request, &profile);
    let (activated, verifier, keys, principals) = trust_material();
    let directory = tempdir().expect("ledger directory");
    let ledger_path = directory.path().join("ledger");
    let witness_path = directory.path().join("witness");
    File::create(&ledger_path).expect("ledger file");
    File::create(&witness_path).expect("witness file");
    let binding = digest("binding:commit-boundary");
    let ledger = DurableLedger::create(open_rw(&ledger_path), binding, 64).expect("ledger");
    let witness = LedgerWitnessStore::create(open_rw(&witness_path), binding).expect("witness");
    let parent = File::open(directory.path()).expect("parent");
    let writer = LedgerWriter::from_durable(ledger, witness, activated, &parent, &parent)
        .expect("writer");
    let learning = Arc::new(IntuitionPolicyLearningSink::new(writer));
    let pins = AgentdIntuitionPolicyPinsV2 {
        policy_profile_digest: canonical_policy_profile_digest_v1(&profile).expect("profile"),
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
        pins.clone(),
        learning.clone(),
    )
    .expect("host");
    let completeness = sign_evidence(
        &verifier,
        &principals[0],
        &keys[0],
        LearningEvidenceRoleV1::Generator,
        "evidence:commit-boundary:completeness",
        &canonical_completeness_evidence_payload_v1(&request).expect("completeness"),
    );
    let profile_evidence = sign_evidence(
        &verifier,
        &principals[1],
        &keys[1],
        LearningEvidenceRoleV1::Evaluator,
        "evidence:commit-boundary:profile",
        &canonical_profile_qualification_payload_v1(&profile).expect("profile"),
    );
    let runtime_evidence = sign_evidence(
        &verifier,
        &principals[2],
        &keys[2],
        LearningEvidenceRoleV1::Observer,
        "evidence:commit-boundary:runtime",
        &canonical_runtime_commitment_payload_v2(&request, &profile, &scoring, &assignment)
            .expect("runtime"),
    );
    let prepared = host
        .prepare_v3(
            &agent_id,
            SPAWN_GENERATION,
            request,
            profile,
            scoring,
            assignment,
            IntuitionQualificationEvidenceV2 {
                completeness: &completeness,
                profile_qualification: &profile_evidence,
                runtime: &runtime_evidence,
            },
            id("episode:commit-boundary"),
            digest("snapshot:commit-boundary"),
            NOW,
        )
        .expect("prepared");
    let payload = prepared
        .decision_signing_payload()
        .expect("payload")
        .expect("selected");
    let mut decision_evidence = sign_evidence(
        &verifier,
        &principals[0],
        &keys[0],
        LearningEvidenceRoleV1::Generator,
        "evidence:commit-boundary:decision",
        &payload,
    );
    // A later-valid Decision signature must not extend the original three-party
    // qualification, whose earliest expiry is 200.
    decision_evidence.expires_at = 400;
    decision_evidence.signature = keys[0]
        .sign(&decision_evidence.signing_bytes())
        .to_bytes();

    for field in 0..10 {
        let mut changed = pins.clone();
        match field {
            0 => changed.policy_profile_digest = digest("changed:profile"),
            1 => changed.policy_digest = digest("changed:policy"),
            2 => changed.policy_generation = PolicyGeneration::new(5).expect("generation"),
            3 => changed.objective_class_digest = digest("changed:class"),
            4 => changed.model_artifact_digest = digest("changed:model"),
            5 => changed.scorer_contract_digest = digest("changed:scorer"),
            6 => changed.calibration_artifact_digest = digest("changed:calibration"),
            7 => changed.ood_artifact_digest = digest("changed:ood"),
            8 => changed.risk_rule_digest = digest("changed:risk"),
            9 => changed.rng_owner_digest = Some(digest("changed:rng")),
            _ => unreachable!(),
        }
        let other = AgentdIntuitionPolicyHostV1::new_product(
            agent_id.clone(),
            SPAWN_GENERATION,
            verifier.clone(),
            changed,
            learning.clone(),
        )
        .expect("other host with same identity, generation and trust");
        assert!(matches!(
            other.commit_v3(
                &agent_id,
                SPAWN_GENERATION,
                prepared.clone(),
                Digest32::ZERO,
                Some(decision_evidence.clone()),
                NOW,
            ),
            Err(AgentdIntuitionPolicyError::PreparedProfileMismatch)
        ));
    }
    assert!(matches!(
        host.commit_v3(
            &agent_id,
            SPAWN_GENERATION,
            prepared.clone(),
            Digest32::ZERO,
            Some(decision_evidence.clone()),
            NOW - 1,
        ),
        Err(AgentdIntuitionPolicyError::PreparedClockReversed)
    ));
    for now in [200, 201, 399] {
        assert!(matches!(
            host.commit_v3(
                &agent_id,
                SPAWN_GENERATION,
                prepared.clone(),
                Digest32::ZERO,
                Some(decision_evidence.clone()),
                now,
            ),
            Err(AgentdIntuitionPolicyError::PreparedEvidenceExpired)
        ));
    }
    let committed = host
        .commit_v3(
            &agent_id,
            SPAWN_GENERATION,
            prepared,
            Digest32::ZERO,
            Some(decision_evidence),
            199,
        )
        .expect("unchanged host and valid evidence lifetime");
    assert_eq!(
        committed.learning.expect("durable receipt").sequence.get(),
        1,
        "a rejected prepare/commit attempt must not append a Decision"
    );
}
