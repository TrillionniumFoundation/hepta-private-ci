use super::*;
use pretty_assertions::assert_eq;

fn id(value: &str) -> StableId {
    let Ok(value) = StableId::new(value) else {
        panic!("test identifier must be valid");
    };
    value
}

fn digest(value: &[u8]) -> Digest32 {
    Digest32::of_bytes(value)
}

fn generation(value: u64) -> Generation {
    let Ok(value) = Generation::new(value) else {
        panic!("test generation must be non-zero");
    };
    value
}

fn must<T>(result: Result<T, Error>) -> T {
    match result {
        Ok(value) => value,
        Err(error) => panic!("unexpected error: {error:?}"),
    }
}

fn digest_legacy_request_v1(request: &ProposalRequest) -> Result<Digest32, Error> {
    let mut parameter_deltas = request.parameter_deltas.clone();
    parameter_deltas.sort_by(|left, right| left.parameter_id.cmp(&right.parameter_id));
    let mut topology_deltas = request.topology_deltas.clone();
    topology_deltas.sort_by(|left, right| {
        left.module_id
            .cmp(&right.module_id)
            .then_with(|| left.operation.cmp(&right.operation))
    });
    let mut bytes = b"hepta.plasticity.proposal.v1".to_vec();
    push_legacy_id(&mut bytes, &request.proposal_id)?;
    push_legacy_id(&mut bytes, &request.proposer_id)?;
    push_legacy_id(&mut bytes, &request.evaluator_id)?;
    bytes.extend_from_slice(&request.baseline_generation.get().to_be_bytes());
    bytes.extend_from_slice(&request.candidate_generation.get().to_be_bytes());
    bytes.extend_from_slice(request.evaluation_digest.as_array());
    bytes.extend_from_slice(&request.maximum_absolute_delta.raw().to_be_bytes());
    for delta in &parameter_deltas {
        push_legacy_id(&mut bytes, &delta.parameter_id)?;
        bytes.extend_from_slice(&delta.delta.raw().to_be_bytes());
        bytes.extend_from_slice(&delta.lower_bound.raw().to_be_bytes());
        bytes.extend_from_slice(&delta.upper_bound.raw().to_be_bytes());
        bytes.extend_from_slice(delta.evidence_digest.as_array());
    }
    for delta in &topology_deltas {
        push_legacy_id(&mut bytes, &delta.module_id)?;
        bytes.push(match delta.operation {
            TopologyOperation::Add => 0,
            TopologyOperation::Remove => 1,
            TopologyOperation::Replace => 2,
        });
        bytes.extend_from_slice(delta.predecessor_digest.as_array());
        bytes.extend_from_slice(delta.candidate_digest.as_array());
        bytes.extend_from_slice(delta.evidence_digest.as_array());
    }
    Ok(Digest32::of_bytes(&bytes))
}

fn push_legacy_id(bytes: &mut Vec<u8>, value: &StableId) -> Result<(), Error> {
    let length = u32::try_from(value.as_str().len()).map_err(|_| Error::Arithmetic)?;
    bytes.extend_from_slice(&length.to_be_bytes());
    bytes.extend_from_slice(value.as_str().as_bytes());
    Ok(())
}

fn legacy_request() -> ProposalRequest {
    ProposalRequest {
        proposal_id: id("proposal:1"),
        proposer_id: id("proposer:1"),
        evaluator_id: id("evaluator:1"),
        baseline_generation: generation(1),
        candidate_generation: generation(2),
        evaluation_digest: digest(b"evaluation"),
        evaluation_eligible: true,
        maximum_absolute_delta: FixedQ32::from_raw(10),
        parameter_deltas: vec![ParameterDelta {
            parameter_id: id("parameter:1"),
            delta: FixedQ32::from_raw(5),
            lower_bound: FixedQ32::from_raw(-10),
            upper_bound: FixedQ32::from_raw(10),
            evidence_digest: digest(b"parameter-evidence"),
        }],
        topology_deltas: vec![TopologyDelta {
            module_id: id("module:1"),
            operation: TopologyOperation::Replace,
            predecessor_digest: digest(b"old"),
            candidate_digest: digest(b"new"),
            evidence_digest: digest(b"topology-evidence"),
        }],
    }
}

fn legacy_proposal() -> PlasticityProposal {
    let request = legacy_request();
    let proposal_digest = must(digest_legacy_request_v1(&request));
    PlasticityProposal {
        proposal_id: request.proposal_id,
        proposer_id: request.proposer_id,
        evaluator_id: request.evaluator_id,
        baseline_generation: request.baseline_generation,
        candidate_generation: request.candidate_generation,
        evaluation_digest: request.evaluation_digest,
        parameter_deltas: request.parameter_deltas,
        topology_deltas: request.topology_deltas,
        proposal_digest,
        status: ProposalStatus::RequiresIndependentAcceptance,
        authority: AuthorityPosture::DENY_ALL,
    }
}

fn parameter_delta(layer: &str, parameter: &str, value: i64, evidence: &[u8]) -> ParameterDeltaV2 {
    ParameterDeltaV2 {
        layer_id: id(layer),
        parameter_id: id(parameter),
        delta: FixedQ32::from_raw(value),
        lower_bound: FixedQ32::from_raw(-10),
        upper_bound: FixedQ32::from_raw(10),
        evidence_digest: digest(evidence),
    }
}

fn v2_request() -> ParameterProposalRequestV2 {
    let selected_artifact_digest = digest(b"selected-artifact");
    ParameterProposalRequestV2 {
        proposal_id: id("proposal:2"),
        proposer_id: id("proposer:1"),
        evaluator_id: id("evaluator:1"),
        selected_artifact_digest,
        window: ProposalWindowV2 {
            window_id: id("window:1"),
            window_digest: digest(b"window"),
        },
        baseline_generation: generation(7),
        candidate_generation: generation(8),
        dataset_digest: digest(b"dataset"),
        update_rule_digest: digest(b"update-rule"),
        modulator_digest: digest(b"modulator"),
        modulator_broadcast_digest: digest(b"broadcast"),
        eligibility_digest: digest(b"eligibility"),
        evaluation_digest: digest(b"evaluation"),
        rollback_predecessor_digest: selected_artifact_digest,
        norm_layers: vec![
            LayerNormDenominatorV2 {
                layer_id: id("layer:b"),
                baseline_squared_l2_raw_q64: 4_000_000,
            },
            LayerNormDenominatorV2 {
                layer_id: id("layer:a"),
                baseline_squared_l2_raw_q64: 1_000_000,
            },
        ],
        candidates: vec![
            ParameterCandidateRequestV2 {
                candidate_id: id("candidate:update"),
                kind: ParameterCandidateKindV2::Update,
                parameter_deltas: vec![
                    parameter_delta("layer:b", "parameter:b", -3, b"delta-b"),
                    parameter_delta("layer:a", "parameter:a", 2, b"delta-a"),
                ],
            },
            ParameterCandidateRequestV2 {
                candidate_id: id("candidate:no-change"),
                kind: ParameterCandidateKindV2::NoChange,
                parameter_deltas: Vec::new(),
            },
        ],
    }
}

#[test]
fn legacy_v1_is_explicit_read_only_and_never_upconverted() {
    assert_eq!(propose(legacy_request()), Err(Error::LegacyWriteDisabled));
    assert_eq!(
        propose_versioned(ProposalWriteRequest::LegacyV1(Box::new(legacy_request()))),
        Err(Error::LegacyWriteDisabled)
    );
    let record = ProposalRecord::LegacyV1(Box::new(legacy_proposal()));
    let read = must(read_versioned_proposal(1, record.clone()));
    assert_eq!(read.record, record);
    assert_eq!(
        read.digest_verification,
        ProposalDigestVerification::UnavailableLegacyMissingMaximumAbsoluteDelta
    );
    assert_eq!(
        read_versioned_proposal(2, record),
        Err(Error::VersionPayloadMismatch)
    );
    assert_eq!(
        dispatch_proposal_version(3),
        Err(Error::UnsupportedVersion(3))
    );
}

#[test]
fn legacy_v1_migration_digest_is_fixed() {
    assert_eq!(
        must(digest_legacy_request_v1(&legacy_request())).to_string(),
        "a143a54a94d60d2734237612f1c2e0af4b4d986ea52efa6099765b83442dedb4"
    );
}

#[test]
fn legacy_v1_read_rejects_authority_and_missing_opaque_digest() {
    let mut proposal = legacy_proposal();
    proposal.authority.selection = true;
    assert_eq!(
        read_versioned_proposal(1, ProposalRecord::LegacyV1(Box::new(proposal))),
        Err(Error::AuthorityGranted)
    );

    let mut proposal = legacy_proposal();
    proposal.proposal_digest = Digest32::ZERO;
    assert_eq!(
        read_versioned_proposal(1, ProposalRecord::LegacyV1(Box::new(proposal))),
        Err(Error::EmptyDigest("proposal"))
    );
}

#[test]
fn v2_matches_canonical_golden_vectors_and_grants_no_authority() {
    let proposal = must(propose_v2(v2_request()));
    assert_eq!(
        proposal.norm_profile.profile_digest.to_string(),
        "d31bd6f69d36817557272d747e5209d431e3ef3058e6f415dc57da4f8f98fb97"
    );
    assert_eq!(
        proposal.proposal_digest.to_string(),
        "e2ecdc9e0fd3278865665a2b0b168a3048919e86e8979e2e90bc6e5db9ab357c"
    );
    assert_eq!(proposal.candidates.len(), 2);
    assert_eq!(
        proposal.candidates[0].kind,
        ParameterCandidateKindV2::NoChange
    );
    assert_eq!(
        proposal.status,
        ProposalStatus::RequiresIndependentAcceptance
    );
    assert!(!proposal.authority.grants_any());
    assert_eq!(proposal.candidate_generation, generation(8));
    assert_eq!(
        proposal.candidates[1]
            .norm_metrics
            .global_delta_squared_l2_raw_q64,
        13
    );
    assert_eq!(
        proposal.norm_profile.global_baseline_squared_l2_raw_q64,
        5_000_000
    );
}

#[test]
fn v2_write_and_read_dispatch_are_exact() {
    assert_eq!(ProposalVersion::LegacyV1.as_u16(), 1);
    assert_eq!(ProposalVersion::ParameterV2.as_u16(), 2);
    let record = must(propose_versioned(ProposalWriteRequest::ParameterV2(
        Box::new(v2_request()),
    )));
    assert_eq!(record.version(), ProposalVersion::ParameterV2);
    assert_eq!(
        read_versioned_proposal(1, record.clone()),
        Err(Error::VersionPayloadMismatch)
    );
    let read = must(read_versioned_proposal(2, record.clone()));
    assert_eq!(read.record, record);
    assert_eq!(
        read.digest_verification,
        ProposalDigestVerification::VerifiedV2
    );
}

#[test]
fn v2_binds_every_required_digest() {
    let mutations: [fn(&mut ParameterProposalRequestV2); 9] = [
        |request| request.selected_artifact_digest = Digest32::ZERO,
        |request| request.window.window_digest = Digest32::ZERO,
        |request| request.dataset_digest = Digest32::ZERO,
        |request| request.update_rule_digest = Digest32::ZERO,
        |request| request.modulator_digest = Digest32::ZERO,
        |request| request.modulator_broadcast_digest = Digest32::ZERO,
        |request| request.eligibility_digest = Digest32::ZERO,
        |request| request.evaluation_digest = Digest32::ZERO,
        |request| request.rollback_predecessor_digest = Digest32::ZERO,
    ];
    for mutate in mutations {
        let mut request = v2_request();
        mutate(&mut request);
        assert!(matches!(propose_v2(request), Err(Error::EmptyDigest(_))));
    }
}

#[test]
fn v2_requires_distinct_role_ids_exact_successor_and_rollback() {
    let mut request = v2_request();
    request.evaluator_id = request.proposer_id.clone();
    assert_eq!(propose_v2(request), Err(Error::SelfEvaluation));

    let mut request = v2_request();
    request.candidate_generation = generation(9);
    assert_eq!(propose_v2(request), Err(Error::GenerationNotExactSuccessor));

    let mut request = v2_request();
    request.baseline_generation = generation(u64::MAX);
    assert_eq!(propose_v2(request), Err(Error::GenerationNotExactSuccessor));

    let mut request = v2_request();
    request.rollback_predecessor_digest = digest(b"other-artifact");
    assert_eq!(propose_v2(request), Err(Error::RollbackPredecessorMismatch));
}

#[test]
fn v2_distinct_ids_and_supplied_candidates_remain_non_authoritative() {
    let mut request = v2_request();
    request.evaluator_id = id("caller-asserted-evaluator");
    request
        .candidates
        .retain(|candidate| candidate.kind == ParameterCandidateKindV2::NoChange);
    request.dataset_digest = digest(b"caller-asserted-dataset");
    request.evaluation_digest = digest(b"caller-asserted-evaluation");

    let proposal = must(propose_v2(request));

    assert_eq!(proposal.candidates.len(), 1);
    assert_eq!(
        proposal.status,
        ProposalStatus::RequiresIndependentAcceptance
    );
    assert!(!proposal.authority.grants_any());
}

#[test]
fn v2_digest_rejects_nonzero_header_binding_tampering() {
    let mutations: [fn(&mut ParameterProposalV2); 12] = [
        |proposal| proposal.proposal_id = id("proposal:tampered"),
        |proposal| proposal.proposer_id = id("proposer:tampered"),
        |proposal| proposal.evaluator_id = id("evaluator:tampered"),
        |proposal| proposal.window.window_id = id("window:tampered"),
        |proposal| proposal.window.window_digest = digest(b"tampered-window"),
        |proposal| {
            proposal.baseline_generation = generation(8);
            proposal.candidate_generation = generation(9);
        },
        |proposal| proposal.dataset_digest = digest(b"tampered-dataset"),
        |proposal| proposal.update_rule_digest = digest(b"tampered-update"),
        |proposal| proposal.modulator_digest = digest(b"tampered-modulator"),
        |proposal| proposal.modulator_broadcast_digest = digest(b"tampered-broadcast"),
        |proposal| proposal.eligibility_digest = digest(b"tampered-eligibility"),
        |proposal| proposal.evaluation_digest = digest(b"tampered-evaluation"),
    ];
    for mutate in mutations {
        let mut proposal = must(propose_v2(v2_request()));
        mutate(&mut proposal);
        assert_eq!(
            verify_parameter_proposal_v2(&proposal),
            Err(Error::ProposalDigestMismatch)
        );
    }
}

#[test]
fn candidate_set_is_bounded_and_has_exactly_one_no_change() {
    let mut request = v2_request();
    request.candidates.clear();
    assert_eq!(propose_v2(request), Err(Error::CandidateCountOutOfRange));

    let mut request = v2_request();
    request.candidates[0].parameter_deltas =
        vec![parameter_delta("layer:a", "parameter:a", 1, b"delta"); 4_097];
    assert_eq!(propose_v2(request), Err(Error::ParameterLimitExceeded));

    let mut request = v2_request();
    request.candidates = (0..33)
        .map(|index| ParameterCandidateRequestV2 {
            candidate_id: id(&format!("candidate:no-change-{index}")),
            kind: ParameterCandidateKindV2::NoChange,
            parameter_deltas: Vec::new(),
        })
        .collect();
    assert_eq!(propose_v2(request), Err(Error::CandidateCountOutOfRange));

    let mut request = v2_request();
    request
        .candidates
        .retain(|candidate| candidate.kind == ParameterCandidateKindV2::Update);
    assert_eq!(propose_v2(request), Err(Error::MissingNoChangeCandidate));

    let mut request = v2_request();
    request.candidates.push(ParameterCandidateRequestV2 {
        candidate_id: id("candidate:no-change-2"),
        kind: ParameterCandidateKindV2::NoChange,
        parameter_deltas: Vec::new(),
    });
    assert_eq!(propose_v2(request), Err(Error::MultipleNoChangeCandidates));

    let mut request = v2_request();
    let duplicate_candidate = request.candidates[1].clone();
    request.candidates.push(duplicate_candidate);
    assert_eq!(
        propose_v2(request),
        Err(Error::DuplicateCandidate("candidate:no-change".to_string()))
    );

    let mut request = v2_request();
    request.candidates[1].parameter_deltas.push(parameter_delta(
        "layer:a",
        "parameter:extra",
        1,
        b"extra",
    ));
    assert_eq!(
        propose_v2(request),
        Err(Error::NoChangeHasDeltas("candidate:no-change".to_string()))
    );
}

#[test]
fn update_candidates_reject_empty_zero_duplicate_and_unprofiled_deltas() {
    let mut request = v2_request();
    request.candidates[0].parameter_deltas.clear();
    assert_eq!(
        propose_v2(request),
        Err(Error::UpdateHasNoDeltas("candidate:update".to_string()))
    );

    let mut request = v2_request();
    request.candidates[0].parameter_deltas[0].delta = FixedQ32::ZERO;
    assert_eq!(
        propose_v2(request),
        Err(Error::ZeroParameterDelta("parameter:b".to_string()))
    );

    let mut request = v2_request();
    let mut duplicate = request.candidates[0].parameter_deltas[0].clone();
    duplicate.layer_id = id("layer:a");
    request.candidates[0].parameter_deltas.push(duplicate);
    assert_eq!(
        propose_v2(request),
        Err(Error::DuplicateParameter("parameter:b".to_string()))
    );

    let mut request = v2_request();
    request.candidates[0].parameter_deltas[0].layer_id = id("layer:missing");
    assert_eq!(
        propose_v2(request),
        Err(Error::MissingNormLayer("layer:missing".to_string()))
    );
}

#[test]
fn update_candidates_reject_bad_bounds_and_missing_evidence() {
    let mut request = v2_request();
    request.candidates[0].parameter_deltas[0].lower_bound = FixedQ32::from_raw(5);
    request.candidates[0].parameter_deltas[0].upper_bound = FixedQ32::from_raw(-5);
    assert_eq!(
        propose_v2(request),
        Err(Error::InvertedBounds("parameter:b".to_string()))
    );

    let mut request = v2_request();
    request.candidates[0].parameter_deltas[0].upper_bound = FixedQ32::from_raw(-4);
    assert_eq!(
        propose_v2(request),
        Err(Error::DeltaOutsideBounds("parameter:b".to_string()))
    );

    let mut request = v2_request();
    request.candidates[0].parameter_deltas[0].evidence_digest = Digest32::ZERO;
    assert_eq!(
        propose_v2(request),
        Err(Error::EmptyDigest("parameter evidence"))
    );
}

#[test]
fn norm_profile_rejects_duplicate_zero_and_overflow_denominators() {
    let mut request = v2_request();
    request.norm_layers.clear();
    assert_eq!(propose_v2(request), Err(Error::NormLayerCountOutOfRange));

    let mut request = v2_request();
    request.norm_layers = vec![
        LayerNormDenominatorV2 {
            layer_id: id("layer:repeated"),
            baseline_squared_l2_raw_q64: 1,
        };
        257
    ];
    assert_eq!(propose_v2(request), Err(Error::NormLayerCountOutOfRange));

    let mut request = v2_request();
    let duplicate_layer = request.norm_layers[1].layer_id.clone();
    request.norm_layers[0].layer_id = duplicate_layer;
    assert_eq!(
        propose_v2(request),
        Err(Error::DuplicateNormLayer("layer:a".to_string()))
    );

    let mut request = v2_request();
    request.norm_layers[0].baseline_squared_l2_raw_q64 = 0;
    assert_eq!(
        propose_v2(request),
        Err(Error::ZeroNormDenominator("layer:b".to_string()))
    );

    let mut request = v2_request();
    request.norm_layers[0].baseline_squared_l2_raw_q64 = u128::MAX;
    assert_eq!(propose_v2(request), Err(Error::Arithmetic));
}

#[test]
fn per_layer_gate_is_not_implied_by_global_gate() {
    assert_eq!(
        parameter_v2::within_relative_limit(100, 1_000_001_000_000, 2_500),
        Ok(true)
    );
    assert_eq!(
        parameter_v2::within_relative_limit(100, 1_000_000, 5_000),
        Ok(false)
    );
    let mut request = v2_request();
    request.norm_layers = vec![
        LayerNormDenominatorV2 {
            layer_id: id("layer:a"),
            baseline_squared_l2_raw_q64: 1_000_000,
        },
        LayerNormDenominatorV2 {
            layer_id: id("layer:b"),
            baseline_squared_l2_raw_q64: 1_000_000_000_000,
        },
    ];
    request.candidates[0].parameter_deltas =
        vec![parameter_delta("layer:a", "parameter:a", 10, b"delta-a")];
    assert_eq!(
        propose_v2(request),
        Err(Error::PerLayerTrustRegionExceeded(
            "candidate:update:layer:a".to_string()
        ))
    );
}

#[test]
fn squared_relative_limit_accepts_the_boundary_and_fails_on_overflow() {
    assert_eq!(
        parameter_v2::within_relative_limit(25, 1_000_000, 5_000),
        Ok(true)
    );
    assert_eq!(
        parameter_v2::within_relative_limit(26, 1_000_000, 5_000),
        Ok(false)
    );
    assert_eq!(
        parameter_v2::within_relative_limit(u128::MAX, u128::MAX, 5_000),
        Err(Error::Arithmetic)
    );
}

#[test]
fn global_gate_is_not_replaced_by_per_layer_gates() {
    assert_eq!(
        parameter_v2::within_relative_limit(16, 1_000_000, 5_000),
        Ok(true)
    );
    assert_eq!(
        parameter_v2::within_relative_limit(32, 2_000_000, 2_500),
        Ok(false)
    );
    let mut request = v2_request();
    request.norm_layers = vec![
        LayerNormDenominatorV2 {
            layer_id: id("layer:a"),
            baseline_squared_l2_raw_q64: 1_000_000,
        },
        LayerNormDenominatorV2 {
            layer_id: id("layer:b"),
            baseline_squared_l2_raw_q64: 1_000_000,
        },
    ];
    request.candidates[0].parameter_deltas = vec![
        parameter_delta("layer:a", "parameter:a", 4, b"delta-a"),
        parameter_delta("layer:b", "parameter:b", 4, b"delta-b"),
    ];
    assert_eq!(
        propose_v2(request),
        Err(Error::GlobalTrustRegionExceeded(
            "candidate:update".to_string()
        ))
    );
}

#[test]
fn canonical_order_is_independent_of_input_order() {
    let left = must(propose_v2(v2_request()));
    let mut request = v2_request();
    request.norm_layers.reverse();
    request.candidates.reverse();
    for candidate in &mut request.candidates {
        candidate.parameter_deltas.reverse();
    }
    assert_eq!(must(propose_v2(request)), left);
}

#[test]
fn read_validation_rejects_tampered_metrics_digest_profile_and_authority() {
    let proposal = must(propose_v2(v2_request()));

    let mut tampered = proposal.clone();
    tampered.candidates[1].norm_metrics.layers[0].delta_squared_l2_raw_q64 += 1;
    assert_eq!(
        verify_parameter_proposal_v2(&tampered),
        Err(Error::NormMetricsMismatch("candidate set".to_string()))
    );

    let mut tampered = proposal.clone();
    tampered.proposal_digest = digest(b"tampered");
    assert_eq!(
        verify_parameter_proposal_v2(&tampered),
        Err(Error::ProposalDigestMismatch)
    );

    let mut tampered = proposal.clone();
    tampered.norm_profile.profile_digest = digest(b"tampered-profile");
    assert_eq!(
        verify_parameter_proposal_v2(&tampered),
        Err(Error::NormProfileMismatch)
    );

    let mut tampered = proposal;
    tampered.authority.runtime = true;
    assert_eq!(
        verify_parameter_proposal_v2(&tampered),
        Err(Error::AuthorityGranted)
    );
}

#[test]
fn registry_is_unique_by_artifact_window_and_idempotent() {
    let proposal = must(propose_v2(v2_request()));
    let mut registry = ProposalRegistry::new(4);
    assert_eq!(
        registry.append_v2(proposal.clone()),
        Ok(AppendDisposition::Inserted)
    );
    assert_eq!(
        registry.append_v2(proposal.clone()),
        Ok(AppendDisposition::Unchanged)
    );
    assert_eq!(registry.record_count(), 1);
    assert_eq!(
        registry.get_v2(
            proposal.selected_artifact_digest,
            &proposal.window.window_id
        ),
        Some(&proposal)
    );
    assert_eq!(
        registry.get_v2_by_proposal_id(&proposal.proposal_id),
        Some(&proposal)
    );

    let mut drifted_request = v2_request();
    drifted_request.proposal_id = id("proposal:drifted-window");
    drifted_request.window.window_digest = digest(b"drifted-window");
    let drifted = must(propose_v2(drifted_request));
    assert!(matches!(
        registry.append_v2(drifted),
        Err(Error::RegistrySlotConflict(_))
    ));

    let mut reused_id_request = v2_request();
    reused_id_request.window.window_id = id("window:2");
    reused_id_request.window.window_digest = digest(b"window-2");
    let reused_id = must(propose_v2(reused_id_request));
    assert_eq!(
        registry.append_v2(reused_id),
        Err(Error::ProposalConflict(proposal.proposal_id.to_string()))
    );
}

#[test]
fn registry_enforces_proposal_identity_capacity_and_legacy_read_only_state() {
    let legacy = legacy_proposal();
    let mut registry = must(ProposalRegistry::with_legacy_v1_history(
        2,
        vec![legacy.clone()],
    ));
    assert_eq!(registry.get(&legacy.proposal_id), Some(&legacy));
    assert_eq!(
        registry.append(legacy.clone()),
        Err(Error::LegacyWriteDisabled)
    );

    let mut request = v2_request();
    request.proposal_id = legacy.proposal_id.clone();
    assert_eq!(
        registry.append_v2(must(propose_v2(request))),
        Err(Error::ProposalConflict(legacy.proposal_id.to_string()))
    );

    let proposal = must(propose_v2(v2_request()));
    assert_eq!(
        registry.append_v2(proposal),
        Ok(AppendDisposition::Inserted)
    );
    let mut request = v2_request();
    request.proposal_id = id("proposal:3");
    request.window.window_id = id("window:2");
    request.window.window_digest = digest(b"window-2");
    assert_eq!(
        registry.append_v2(must(propose_v2(request))),
        Err(Error::RegistryCapacityExceeded)
    );
}
