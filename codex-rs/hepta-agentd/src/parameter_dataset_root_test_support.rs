//! Only fixture initialization writes; the actual dataset command is read-only.
use super::*;
use codex_hepta_agent_components::types::ProbabilityQ32;

pub(super) fn populate_original_dataset_ledger(
    fixture: &mut ClockFixture,
    root: &Path,
    trust: &Arc<ActivatedLearningTrustV1>,
    now: u64,
) {
    populate_original_dataset_ledger_count(fixture, root, trust, now, 1);
}
pub(super) fn populate_original_dataset_ledger_count(
    fixture: &mut ClockFixture,
    root: &Path,
    trust: &Arc<ActivatedLearningTrustV1>,
    now: u64,
    episodes: usize,
) {
    let path = root.join("authenticated-dataset-ledger.bin");
    let binding = digest("actual root production dataset ledger");
    let ledger = DurableLedger::create(new_file(&path), binding, 64.max(episodes * 2))
        .expect("fixture explicit initial ledger");
    let witness = LedgerWitnessStore::create(
        new_file(&root.join("authenticated-dataset-witness.bin")),
        binding,
    )
    .expect("original witness");
    let directory = fs::File::open(root).expect("same actual directory");
    let mut writer =
        LedgerWriter::from_durable(ledger, witness, (**trust).clone(), &directory, &directory)
            .expect("sole original production writer");
    for episode in 0..episodes {
        let name = |label: &str| id(&format!("{label}.{episode}"));
        let candidates = vec![id("dataset.action"), id("abstain")];
        let decision = ProductionDecisionV2 {
            record_id: name("dataset.decision"),
            episode_id: name("dataset.episode"),
            run_snapshot_digest: digest("dataset run"),
            objective_digest: trust.verifier().objective_digest(),
            policy_digest: digest("dataset policy"),
            selected_candidate_id: candidates[0].clone(),
            selected_propensity: ProbabilityQ32::ONE,
            completeness: CandidateSetCompletenessReceiptV1 {
                set_id: id("dataset.frontier"),
                state_digest: digest("dataset state"),
                generator_id: id("fixture.signer.0"),
                generator_code_digest: digest("fixture generator"),
                grammar_digest: digest("dataset grammar"),
                hard_filter_digest: digest("dataset filter"),
                truncation_digest: digest("dataset truncation"),
                candidates_digest: candidate_ids_digest_v2(&candidates),
                candidate_count: 2,
                omitted_count_bound: 0,
                canonical_order_digest: candidate_order_digest_v2(&candidates),
                complete_for_generator: true,
            },
            candidate_ids: candidates,
            support_digest: digest("dataset decision support"),
        };
        let generator = sign(
            trust,
            0,
            LearningEvidenceRoleV1::Generator,
            &decision_signing_payload_v2(&decision).expect("original decision bytes"),
            now,
        );
        writer
            .append_decision(
                writer.snapshot().expect("actual predecessor").head_digest,
                decision,
                &generator,
                now,
            )
            .expect("actual original G admission");
        let observer = trust
            .verifier()
            .verify(
                LearningEvidenceRoleV1::Observer,
                &sign(
                    trust,
                    1,
                    LearningEvidenceRoleV1::Observer,
                    b"fixture principal observation",
                    now,
                ),
                b"fixture principal observation",
                now,
            )
            .expect("original independent O")
            .principal()
            .clone();
        let outcome = AuthenticatedOutcomeV1 {
            record_id: name("dataset.outcome.record"),
            outcome_id: name("dataset.outcome"),
            episode_id: name("dataset.episode"),
            observer,
            observed_at: Some(now),
            value: Some(FixedQ32::ONE),
            unit_profile_digest: digest("dataset units"),
            support_digest: digest("dataset outcome support"),
            watermark: OutcomeWatermarkV1 {
                latest_observable_at: now,
                expected_delay_profile_digest: digest("dataset delay"),
                terminality: OutcomeTerminalityV1::Terminal,
                censoring_reason: None,
                correction_predecessor: None,
                finalized_at: Some(now),
            },
        };
        let evidence = sign(
            trust,
            1,
            LearningEvidenceRoleV1::Observer,
            &outcome_signing_payload_v2(&outcome),
            now,
        );
        writer
            .append_outcome(
                writer.snapshot().expect("predecessor").head_digest,
                outcome,
                &evidence,
                now,
            )
            .expect("actual original O outcome admission");
    }
    let anchor = writer
        .witness_frontier()
        .expect("original complete acknowledgment")
        .anchor;
    let expected = writer.snapshot().expect("complete original snapshot");
    drop(writer);
    // This initial fixture handoff occurs before composition/start. The port
    // never reopens this or another Ledger after the owner starts.
    fixture.owner.ledger = DurableLedger::recover(
        existing_file(&path),
        binding,
        64.max(episodes * 2),
        LedgerRecovery::Acknowledged(anchor),
    )
    .expect("initial complete original custody");
    fixture.files.ledger = path;
    assert_eq!(
        fixture
            .owner
            .ledger
            .snapshot()
            .expect("same retained Ledger"),
        expected
    );
}

#[test]
fn original_parameter_dataset_fixture_admits_real_generator_and_observer_records() {
    let root = tempfile::tempdir().expect("independent fixture root");
    let mut fixture = clock_fixture(crate::authbus_ingress::now_ms);
    let now = crate::authbus_ingress::now_ms().expect("actual clock");
    let scope = JournalScope {
        scope_digest: digest("original dataset fixture scope"),
        objective_digest: fixture.parameter.admission.objective_digest,
    };
    let (trust, _) = learning_trust(scope, now, now + 120_000);
    populate_original_dataset_ledger(&mut fixture, root.path(), &trust, now);
    let snapshot = fixture.owner.ledger.snapshot().expect("same held Ledger");
    assert_eq!(snapshot.records().len(), 2);
    assert!(matches!(
        &snapshot.records()[0].event,
        LedgerEvent::AuthenticatedDecisionV2(decision)
            if decision.candidate_ids.iter().any(|candidate| candidate.as_str() == "abstain")
    ));
    assert!(matches!(
        &snapshot.records()[1].event,
        LedgerEvent::AuthenticatedOutcomeV2(outcome)
            if outcome.observer_id.as_str() == "fixture.signer.1"
                && !outcome.authentication_digest.is_zero()
    ));
}
pub(super) fn sign(
    trust: &ActivatedLearningTrustV1,
    index: usize,
    role: LearningEvidenceRoleV1,
    payload: &[u8],
    now: u64,
) -> SignedLearningEvidenceV1 {
    let key = SigningKey::from_bytes(&[u8::try_from(index + 11).expect("fixture key"); 32]);
    let mut evidence = SignedLearningEvidenceV1 {
        evidence_id: id(&format!(
            "dataset.evidence.{index}.{}",
            Digest32::of_bytes(payload)
        )),
        principal_id: id(&format!("fixture.signer.{index}")),
        role,
        trust_digest: trust.verifier().trust_digest(),
        scope_digest: trust.verifier().scope_digest(),
        objective_digest: trust.verifier().objective_digest(),
        authority_epoch: trust.verifier().authority_epoch(),
        issued_at: now,
        expires_at: trust.expires_at(),
        payload_digest: Digest32::of_bytes(payload),
        signature: [0; 64],
    };
    evidence.signature = key.sign(&evidence.signing_bytes()).to_bytes();
    evidence
}

pub(super) async fn verify_actual_dataset_socket(
    client: &AgentdClient,
    round: &crate::AgentdSelfIterationRoundV1,
    context: &(PathBuf, Digest32),
    root: &Path,
    snapshot: &LedgerSnapshot,
    installed_artifact_head: Digest32,
) -> crate::PreparedParameterDatasetV1 {
    let context: Value =
        serde_json::from_slice(&fs::read(&context.0).expect("fixture public context"))
            .expect("whole context");
    let producer: PrincipalWire = serde_json::from_value(context["dataset"]["producer"].clone())
        .expect("original complete producer");
    let producer_source = write_source(
        root.join("dataset-producer.json"),
        serde_json::to_vec(&producer).expect("original pure principal codec"),
    );
    let plan = DatasetFreezePlanV2 {
        snapshot_id: id("dataset.actual.held.round"),
        objective_digest: snapshot
            .records()
            .iter()
            .find_map(|r| {
                if let LedgerEvent::AuthenticatedDecisionV2(d) = &r.event {
                    Some(d.objective_digest)
                } else {
                    None
                }
            })
            .expect("actual G objective"),
        inclusion_policy_digest: digest("actual pinned inclusion"),
    };
    let plan_source=write_source(root.join("dataset-plan.json"),serde_json::to_vec(&json!({"schema":"hepta.parameter.dataset-freeze-plan.v1","snapshot_id":plan.snapshot_id.as_str(),"objective_digest":plan.objective_digest.to_string(),"inclusion_policy_digest":plan.inclusion_policy_digest.to_string()})).expect("whole original plan"));
    let (generation, facts) = client
        .prepare_parameter_dataset_v1(
            round.clone(),
            producer_source.0.clone(),
            producer_source.1,
            plan_source.0.clone(),
            plan_source.1,
        )
        .await
        .expect("actual Root reads complete original held Ledger");
    assert_eq!(
        generation, 2,
        "runtime generation; original client separately checks spawn1"
    );
    assert_eq!(
        facts.ledger_record_count,
        u64::try_from(snapshot.records().len()).expect("count")
    );
    assert_eq!(facts.ledger_head_digest, snapshot.head_digest.to_string());
    assert_eq!(
        facts.installed_artifact_head,
        installed_artifact_head.to_string()
    );
    assert_ne!(
        facts.installed_artifact_head,
        facts.proposal_registry_predecessor
    );
    assert_eq!(
        facts.freeze_payload_hex,
        crate::client::encode_hex(
            &dataset_freeze_signing_payload_v2(snapshot, &plan)
                .expect("original complete freeze bytes")
        )
    );
    let now = crate::authbus_ingress::now_ms().expect("actual clock");
    assert_eq!(
        facts.dataset.native().expect("whole original receipt"),
        freeze_dataset_from_ledger(
            snapshot,
            plan,
            producer.principal().expect("original producer"),
            now
        )
        .expect("same original algorithm")
    );
    assert_eq!(
        facts.proposal_registry_predecessor,
        Digest32::ZERO.to_string()
    );
    let repeated = client
        .prepare_parameter_dataset_v1(
            round.clone(),
            producer_source.0.clone(),
            producer_source.1,
            plan_source.0.clone(),
            plan_source.1,
        )
        .await
        .expect("exact read repetition");
    assert_eq!(repeated.0, generation);
    assert_eq!(
        serde_json::to_vec(&repeated.1.dataset).expect("repeated receipt"),
        serde_json::to_vec(&facts.dataset).expect("whole receipt")
    );
    assert_eq!(repeated.1.freeze_payload_hex, facts.freeze_payload_hex);
    assert_eq!(
        repeated.1.installed_artifact_head,
        facts.installed_artifact_head
    );
    assert_eq!(
        repeated.1.proposal_registry_predecessor,
        facts.proposal_registry_predecessor
    );
    assert!(
        client
            .prepare_parameter_dataset_v1(
                round.clone(),
                producer_source.0.clone(),
                digest("wrong producer pin"),
                plan_source.0.clone(),
                plan_source.1
            )
            .await
            .is_err()
    );
    let mut expired_producer = producer;
    expired_producer.expires_at = now - 1;
    let expired = write_source(
        root.join("dataset-expired-producer.json"),
        serde_json::to_vec(&expired_producer).expect("expired fixture source"),
    );
    assert!(
        client
            .prepare_parameter_dataset_v1(
                round.clone(),
                expired.0,
                expired.1,
                plan_source.0,
                plan_source.1
            )
            .await
            .is_err()
    );
    facts
}
