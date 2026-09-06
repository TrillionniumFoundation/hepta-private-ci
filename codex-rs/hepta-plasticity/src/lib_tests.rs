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

fn parameter_delta(
    layer: &str,
    parameter: &str,
    value: i64,
    evidence: &[u8],
) -> ParameterDeltaV2 {
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
        proposal
            .norm_profile
            .global_baseline_squared_l2_raw_q64,
        5_000_000
    );
}

#[test]
fn v2_write_and_read_dispatch_are_exact() {
    assert_eq!(ProposalVersion::LegacyV1.as_u16(), 1);
    assert_eq!(ProposalVersion::ParameterV2.as_u16(), 2);
    let record = must(propose_versioned(ProposalWriteRequest::ParameterV2(Box::new(
        v2_request(),
    ))));
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
