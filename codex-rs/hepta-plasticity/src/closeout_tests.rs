use super::*;
use std::fs::OpenOptions;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("valid test id")
}

fn digest(value: &[u8]) -> Digest32 {
    Digest32::of_bytes(value)
}

fn generation(value: u64) -> Generation {
    Generation::new(value).expect("valid generation")
}

fn empty_request() -> ParameterProposalRequestV2 {
    let selected_artifact_digest = digest(b"artifact");
    ParameterProposalRequestV2 {
        proposal_id: id("proposal:generated"),
        proposer_id: id("proposer:generated"),
        evaluator_id: id("evaluator:independent"),
        selected_artifact_digest,
        window: ProposalWindowV2 {
            window_id: id("window:generated"),
            window_digest: digest(b"window"),
        },
        baseline_generation: generation(10),
        candidate_generation: generation(11),
        dataset_digest: digest(b"dataset"),
        update_rule_digest: digest(b"update-rule"),
        modulator_digest: digest(b"modulator"),
        modulator_broadcast_digest: digest(b"broadcast"),
        eligibility_digest: digest(b"eligibility"),
        evaluation_digest: digest(b"evaluation"),
        rollback_predecessor_digest: selected_artifact_digest,
        norm_layers: vec![LayerNormDenominatorV2 {
            layer_id: id("layer:a"),
            baseline_squared_l2_raw_q64: 1_000_000_000,
        }],
        candidates: Vec::new(),
    }
}

fn signals() -> Vec<ParameterLearningSignalV1> {
    vec![
        ParameterLearningSignalV1 {
            layer_id: id("layer:a"),
            parameter_id: id("parameter:a"),
            score_raw: 3,
            lower_bound: FixedQ32::from_raw(-10),
            upper_bound: FixedQ32::from_raw(10),
            evidence_digest: digest(b"parameter:a:evidence"),
        },
        ParameterLearningSignalV1 {
            layer_id: id("layer:a"),
            parameter_id: id("parameter:b"),
            score_raw: -2,
            lower_bound: FixedQ32::from_raw(-10),
            upper_bound: FixedQ32::from_raw(10),
            evidence_digest: digest(b"parameter:b:evidence"),
        },
    ]
}

struct TestEvidenceVerifier;

impl EvidenceVerifier for TestEvidenceVerifier {
    fn verify_evidence(&self, claim: &EvidenceClaimV1, now_ms: u64) -> Result<(), Error> {
        if claim.producer_id != id("trusted:producer")
            || now_ms < claim.issued_at_ms
            || now_ms > claim.expires_at_ms
        {
            return Err(Error::EvidenceVerificationFailed(format!(
                "{:?}",
                claim.kind
            )));
        }
        Ok(())
    }
}

struct TestEvaluatorVerifier;

impl IndependentEvaluatorVerifier for TestEvaluatorVerifier {
    fn verify_independent_evaluator(
        &self,
        claim: &EvaluatorClaimV1,
        now_ms: u64,
    ) -> Result<(), Error> {
        if claim.proposer_id == claim.evaluator_id
            || now_ms < claim.issued_at_ms
            || now_ms > claim.expires_at_ms
        {
            return Err(Error::IndependentEvaluatorVerificationFailed(
                claim.evaluator_id.to_string(),
            ));
        }
        Ok(())
    }
}

fn claim(kind: EvidenceKindV1, subject_digest: Digest32) -> EvidenceClaimV1 {
    EvidenceClaimV1 {
        kind,
        subject_digest,
        producer_id: id("trusted:producer"),
        selected_artifact_digest: digest(b"artifact"),
        window_digest: digest(b"window"),
        issued_at_ms: 1_000,
        expires_at_ms: 2_000,
        receipt_digest: digest(format!("receipt:{kind:?}:{subject_digest}").as_bytes()),
    }
}

fn evidence() -> Vec<EvidenceClaimV1> {
    let request = empty_request();
    let mut claims = vec![
        claim(
            EvidenceKindV1::SelectedArtifact,
            request.selected_artifact_digest,
        ),
        claim(EvidenceKindV1::Window, request.window.window_digest),
        claim(EvidenceKindV1::Dataset, request.dataset_digest),
        claim(EvidenceKindV1::UpdateRule, request.update_rule_digest),
        claim(EvidenceKindV1::Modulator, request.modulator_digest),
        claim(
            EvidenceKindV1::ModulatorBroadcast,
            request.modulator_broadcast_digest,
        ),
        claim(EvidenceKindV1::Eligibility, request.eligibility_digest),
        claim(EvidenceKindV1::Evaluation, request.evaluation_digest),
    ];
    for signal in signals() {
        claims.push(claim(EvidenceKindV1::Parameter, signal.evidence_digest));
    }
    claims
}

fn evaluator() -> EvaluatorClaimV1 {
    let request = empty_request();
    EvaluatorClaimV1 {
        proposer_id: request.proposer_id,
        evaluator_id: request.evaluator_id,
        selected_artifact_digest: request.selected_artifact_digest,
        window_digest: request.window.window_digest,
        evaluation_digest: request.evaluation_digest,
        issued_at_ms: 1_000,
        expires_at_ms: 2_000,
        attestation_digest: digest(b"independent-evaluator-attestation"),
    }
}

#[test]
fn native_generator_builds_ranked_bounded_candidates() {
    let proposal = generate_parameter_proposal_v2(
        empty_request(),
        signals(),
        CandidateGeneratorConfigV1 {
            maximum_step_raw: 2,
            maximum_update_candidates: 2,
        },
    )
    .expect("generation must succeed");

    assert_eq!(proposal.candidates.len(), 3);
    assert_eq!(
        proposal.candidates[0].kind,
        ParameterCandidateKindV2::NoChange
    );
    assert_eq!(proposal.candidates[1].parameter_deltas.len(), 1);
    assert_eq!(proposal.candidates[2].parameter_deltas.len(), 2);
    assert_eq!(
        proposal.candidates[1].parameter_deltas[0].parameter_id,
        id("parameter:a")
    );
    assert_eq!(
        proposal.candidates[1].parameter_deltas[0].delta,
        FixedQ32::from_raw(2)
    );
    assert!(!proposal.authority.grants_any());
}

#[test]
fn authenticated_path_rejects_missing_or_stale_evidence() {
    let generated = generate_parameter_proposal_v2(
        empty_request(),
        signals(),
        CandidateGeneratorConfigV1 {
            maximum_step_raw: 2,
            maximum_update_candidates: 2,
        },
    )
    .expect("generation must succeed");
    let request = ParameterProposalRequestV2 {
        proposal_id: generated.proposal_id.clone(),
        proposer_id: generated.proposer_id.clone(),
        evaluator_id: generated.evaluator_id.clone(),
        selected_artifact_digest: generated.selected_artifact_digest,
        window: generated.window.clone(),
        baseline_generation: generated.baseline_generation,
        candidate_generation: generated.candidate_generation,
        dataset_digest: generated.dataset_digest,
        update_rule_digest: generated.update_rule_digest,
        modulator_digest: generated.modulator_digest,
        modulator_broadcast_digest: generated.modulator_broadcast_digest,
        eligibility_digest: generated.eligibility_digest,
        evaluation_digest: generated.evaluation_digest,
        rollback_predecessor_digest: generated.rollback_predecessor_digest,
        norm_layers: generated.norm_profile.layers.clone(),
        candidates: generated
            .candidates
            .iter()
            .map(|candidate| ParameterCandidateRequestV2 {
                candidate_id: candidate.candidate_id.clone(),
                kind: candidate.kind,
                parameter_deltas: candidate.parameter_deltas.clone(),
            })
            .collect(),
    };

    let mut missing = evidence();
    missing.retain(|entry| entry.kind != EvidenceKindV1::Evaluation);
    assert!(matches!(
        propose_authenticated_v1(
            AuthenticatedParameterProposalRequestV1 {
                request: request.clone(),
                evidence: missing,
                evaluator: evaluator(),
                now_ms: 1_500,
            },
            &TestEvidenceVerifier,
            &TestEvaluatorVerifier,
        ),
        Err(Error::MissingAuthenticatedEvidence(_))
    ));

    assert!(matches!(
        propose_authenticated_v1(
            AuthenticatedParameterProposalRequestV1 {
                request,
                evidence: evidence(),
                evaluator: evaluator(),
                now_ms: 2_500,
            },
            &TestEvidenceVerifier,
            &TestEvaluatorVerifier,
        ),
        Err(Error::StaleAuthenticatedEvidence(_))
    ));
}

#[test]
fn topology_v2_is_bounded_candidate_only_and_deny_all() {
    let graph = digest(b"graph");
    let proposal = propose_topology_v2(TopologyProposalRequestV2 {
        proposal_id: id("topology:proposal"),
        proposer_id: id("topology:proposer"),
        evaluator_id: id("topology:evaluator"),
        selected_graph_digest: graph,
        window: ProposalWindowV2 {
            window_id: id("topology:window"),
            window_digest: digest(b"topology-window"),
        },
        baseline_generation: generation(20),
        candidate_generation: generation(21),
        evaluation_digest: digest(b"topology-evaluation"),
        rollback_predecessor_digest: graph,
        candidates: vec![
            TopologyCandidateRequestV2 {
                candidate_id: id("topology:no-change"),
                kind: TopologyCandidateKindV2::NoChange,
                delta: None,
            },
            TopologyCandidateRequestV2 {
                candidate_id: id("topology:replace"),
                kind: TopologyCandidateKindV2::Mutation,
                delta: Some(TopologyDeltaV2 {
                    module_id: id("module:slow-learner"),
                    operation: TopologyOperation::Replace,
                    predecessor_digest: digest(b"module-old"),
                    candidate_digest: digest(b"module-new"),
                    migration_digest: digest(b"migration"),
                    rollback_digest: digest(b"rollback"),
                    evidence_digest: digest(b"topology-evidence"),
                }),
            },
        ],
    })
    .expect("topology proposal");

    assert_eq!(proposal.candidates.len(), 2);
    assert_eq!(proposal.status, ProposalStatus::RequiresIndependentAcceptance);
    assert!(!proposal.authority.grants_any());
    verify_topology_proposal_v2(&proposal).expect("verify topology proposal");
}

#[test]
fn composed_engine_generates_authenticates_and_durably_appends() {
    let nonce = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .expect("clock")
        .as_nanos();
    let path = std::env::temp_dir().join(format!("hepta-plasticity-closeout-{nonce}.bin"));
    let file = OpenOptions::new()
        .create_new(true)
        .read(true)
        .write(true)
        .open(&path)
        .expect("create registry");
    let scope = digest(b"registry-scope");
    let mut registry =
        ProductionProposalRegistry::initialize_new(file, scope, 1, 16).expect("open registry");

    let receipt = generate_authenticate_and_append_v1(
        &mut registry,
        ComposedParameterProposalRequestV1 {
            request: empty_request(),
            signals: signals(),
            generator: CandidateGeneratorConfigV1 {
                maximum_step_raw: 2,
                maximum_update_candidates: 2,
            },
            evidence: evidence(),
            evaluator: evaluator(),
            now_ms: 1_500,
            expected_predecessor_frame_digest: Digest32::ZERO,
        },
        &TestEvidenceVerifier,
        &TestEvaluatorVerifier,
    )
    .expect("composed append");

    assert_eq!(receipt.sequence, 1);
    assert_eq!(receipt.disposition, AppendDisposition::Inserted);
    assert!(!receipt.authority.grants_any());
    assert_eq!(registry.record_count().expect("count"), 1);
    let anchor = registry
        .current_anchor()
        .expect("anchor")
        .expect("non-empty anchor");
    drop(registry);

    let file = OpenOptions::new()
        .read(true)
        .write(true)
        .open(&path)
        .expect("reopen registry");
    let reopened =
        ProductionProposalRegistry::open_anchored(file, scope, 1, 16, anchor).expect("anchored");
    assert_eq!(reopened.record_count().expect("count"), 1);
    drop(reopened);
    let _ = std::fs::remove_file(path);
}
