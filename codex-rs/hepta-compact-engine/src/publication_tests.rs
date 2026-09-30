use super::*;

use codex_hepta_cognitive_types::lane_c::CognitiveSnapshotKeyV1;
use pretty_assertions::assert_eq;

use crate::CompactionQualificationV2;
use crate::authenticated::tests::evidence;
use crate::authenticated::tests::fixture;
use crate::authenticated::tests::trust;
use crate::build_qualified_candidate;
use crate::compaction_qualification_payload_v1;
use crate::prove_compaction_with_signed_evidence_v1;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("valid id")
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn generation(value: u64) -> Generation {
    Generation::new(value).expect("valid generation")
}

struct Host {
    owner: StableId,
    scope: StableId,
    purpose: StableId,
    selected: CompactionSelectedStateV1,
    source_cut: Digest32,
    policy_generation: Generation,
    policy_digest: Digest32,
    verifier: LearningEvidenceVerifierV1,
}

impl Host {
    fn context(&self, now: u64) -> CompactionPublicationContextV1<'_> {
        CompactionPublicationContextV1 {
            owner_agent_id: &self.owner,
            scope_id: &self.scope,
            purpose_id: &self.purpose,
            selected: &self.selected,
            policy_generation: self.policy_generation,
            policy_digest: self.policy_digest,
            source_cut_digest: self.source_cut,
            verifier: &self.verifier,
            now,
        }
    }
}

fn publication_request(
    next_generation: u64,
    source_generation: u64,
    predecessor: Option<Digest32>,
) -> (CompactionPublicationRequestV1, Host) {
    let fixture = fixture();
    let policy = CompactionPolicyV2 {
        policy_id: id("policy:compact"),
        algorithm_digest: digest("algorithm"),
        compatibility_digest: digest("compatibility"),
        maximum_retained_records: 1,
        protected_record_ids: Vec::new(),
    };
    let inputs = vec![CompactionInputRecordV2 {
        record: fixture.candidate.retained_records[0].clone(),
        retention_priority: 1,
        retention_reason_digest: digest("reason"),
    }];
    let mut vector = fixture.candidate.source_snapshot.vector;
    vector.compact_checkpoint_generation = generation(source_generation);
    let candidate = build_qualified_candidate(
        CognitiveSnapshotKeyV1::new(vector).expect("valid vector"),
        generation(next_generation),
        predecessor,
        &policy,
        inputs.clone(),
    )
    .expect("structurally valid candidate");
    let qualification = CompactionQualificationV2 {
        candidate_digest: candidate.candidate_digest,
        ..fixture.qualification
    };
    let payload = compaction_qualification_payload_v1(&candidate, &fixture.binding, &qualification)
        .expect("valid payload");
    let proof = prove_compaction_with_signed_evidence_v1(
        &candidate,
        fixture.binding.clone(),
        qualification,
        &evidence(&fixture.verifier, &payload),
        &fixture.verifier,
        /*now*/ 30,
    )
    .expect("valid signed proof");
    let selected = match predecessor {
        None => CompactionSelectedStateV1::Empty,
        Some(checkpoint_digest) => CompactionSelectedStateV1::Selected {
            generation: generation(source_generation),
            checkpoint_digest,
        },
    };
    let request = CompactionPublicationRequestV1 {
        owner_agent_id: id("owner:agent"),
        scope_id: candidate.source_snapshot.vector.scope_id.clone(),
        purpose_id: candidate.source_snapshot.vector.purpose_id.clone(),
        operation_id: id("operation:compact-1"),
        policy_generation: generation(/*value*/ 1),
        expected_selected: selected.clone(),
        candidate,
        policy,
        inputs,
        authenticated_proof: proof,
    };
    let host = Host {
        owner: request.owner_agent_id.clone(),
        scope: request.scope_id.clone(),
        purpose: request.purpose_id.clone(),
        selected,
        source_cut: fixture.binding.source_cut_digest,
        policy_generation: request.policy_generation,
        policy_digest: request.candidate.policy_digest,
        verifier: fixture.verifier,
    };
    (request, host)
}

#[test]
fn bootstrap_preserves_complete_preimages_and_does_not_infer_selection_from_vector_placeholder() {
    let (request, host) = publication_request(
        /*next_generation*/ 1, /*source_generation*/ 1, /*predecessor*/ None,
    );
    let expected = request.clone();
    let proposal =
        CompactionPublicationProposalV1::new(request, &host.context(/*now*/ 30)).unwrap();
    assert_eq!(proposal.request(), &expected);
    assert_eq!(proposal.authority(), AuthorityPosture::DENY_ALL);
    assert_eq!(
        proposal.intent_digest(),
        Digest32::of_bytes(proposal.intent_bytes())
    );
    proposal.revalidate(&host.context(/*now*/ 40)).unwrap();
    let mut selected_host = host;
    selected_host.selected = CompactionSelectedStateV1::Selected {
        generation: generation(/*value*/ 1),
        checkpoint_digest: digest("existing-checkpoint"),
    };
    assert_eq!(
        proposal.revalidate(&selected_host.context(/*now*/ 40)),
        Err(CompactionPublicationError::SelectedStateChanged)
    );
}

#[test]
fn successor_requires_exact_predecessor_adjacent_generation_and_current_source_generation() {
    let (request, host) = publication_request(
        /*next_generation*/ 2,
        /*source_generation*/ 1,
        Some(digest("selected")),
    );
    let proposal =
        CompactionPublicationProposalV1::new(request, &host.context(/*now*/ 30)).unwrap();
    proposal.revalidate(&host.context(/*now*/ 40)).unwrap();
    let (request, mut host) = publication_request(
        /*next_generation*/ 3,
        /*source_generation*/ 1,
        Some(digest("selected")),
    );
    assert_eq!(
        CompactionPublicationProposalV1::new(request.clone(), &host.context(/*now*/ 30)),
        Err(CompactionPublicationError::CheckpointLineage)
    );
    host.selected = CompactionSelectedStateV1::Selected {
        generation: generation(/*value*/ 2),
        checkpoint_digest: digest("selected"),
    };
    let mut altered = request;
    altered.expected_selected = host.selected.clone();
    assert_eq!(
        CompactionPublicationProposalV1::new(altered, &host.context(/*now*/ 30)),
        Err(CompactionPublicationError::SourceGenerationBinding)
    );
}

#[test]
fn empty_selected_state_rejects_nonbootstrap_source_generation() {
    let (request, host) = publication_request(
        /*next_generation*/ 1, /*source_generation*/ 7, /*predecessor*/ None,
    );
    assert_eq!(
        CompactionPublicationProposalV1::new(request, &host.context(/*now*/ 30)),
        Err(CompactionPublicationError::SourceGenerationBinding)
    );
}

#[test]
fn selected_digest_zero_and_generation_overflow_fail_before_admission() {
    let (request, mut host) = publication_request(
        /*next_generation*/ 2,
        /*source_generation*/ 1,
        Some(digest("selected")),
    );
    for (selected, expected) in [
        (
            CompactionSelectedStateV1::Selected {
                generation: generation(/*value*/ 1),
                checkpoint_digest: Digest32::ZERO,
            },
            CompactionPublicationError::EmptySelectedDigest,
        ),
        (
            CompactionSelectedStateV1::Selected {
                generation: generation(u64::MAX),
                checkpoint_digest: digest("selected"),
            },
            CompactionPublicationError::GenerationOverflow,
        ),
    ] {
        host.selected = selected.clone();
        let mut altered = request.clone();
        altered.expected_selected = selected;
        assert_eq!(
            CompactionPublicationProposalV1::new(altered, &host.context(/*now*/ 30)),
            Err(expected)
        );
    }
}

#[test]
fn proposal_and_host_owner_scope_purpose_are_independent_bindings() {
    let (request, host) = publication_request(
        /*next_generation*/ 1, /*source_generation*/ 1, /*predecessor*/ None,
    );
    for field in ["owner", "scope", "purpose"] {
        let mut altered = request.clone();
        let expected = match field {
            "owner" => {
                altered.owner_agent_id = id("owner:foreign");
                CompactionPublicationError::OwnerBinding
            }
            "scope" => {
                altered.scope_id = id("scope:foreign");
                CompactionPublicationError::ScopeBinding
            }
            "purpose" => {
                altered.purpose_id = id("purpose:foreign");
                CompactionPublicationError::PurposeBinding
            }
            _ => unreachable!(),
        };
        assert_eq!(
            CompactionPublicationProposalV1::new(altered, &host.context(/*now*/ 30)),
            Err(expected)
        );
    }
    let mut false_scope_host = host;
    false_scope_host.scope = id("scope:foreign");
    let mut altered = request;
    altered.scope_id = false_scope_host.scope.clone();
    assert_eq!(
        CompactionPublicationProposalV1::new(altered, &false_scope_host.context(/*now*/ 30)),
        Err(CompactionPublicationError::ScopeBinding)
    );
}

#[test]
fn selected_pointer_changes_or_wrong_predecessor_reject_new_and_retained_proposals() {
    let (request, mut host) = publication_request(
        /*next_generation*/ 2,
        /*source_generation*/ 1,
        Some(digest("selected")),
    );
    let proposal =
        CompactionPublicationProposalV1::new(request.clone(), &host.context(/*now*/ 30)).unwrap();
    host.selected = CompactionSelectedStateV1::Selected {
        generation: generation(/*value*/ 1),
        checkpoint_digest: digest("different-selected"),
    };
    assert_eq!(
        proposal.revalidate(&host.context(/*now*/ 30)),
        Err(CompactionPublicationError::SelectedStateChanged)
    );
    let mut altered = request;
    altered.expected_selected = host.selected.clone();
    assert_eq!(
        CompactionPublicationProposalV1::new(altered, &host.context(/*now*/ 30)),
        Err(CompactionPublicationError::CheckpointLineage)
    );
}

#[test]
fn policy_input_and_candidate_substitution_do_not_inherit_a_valid_proposal() {
    let (request, host) = publication_request(
        /*next_generation*/ 1, /*source_generation*/ 1, /*predecessor*/ None,
    );
    let mut altered = request.clone();
    altered.policy.algorithm_digest = digest("different-policy");
    assert_eq!(
        CompactionPublicationProposalV1::new(altered, &host.context(/*now*/ 30)),
        Err(CompactionPublicationError::Compaction(
            QualifiedCompactionError::CandidateSourceMismatch
        ))
    );
    let mut altered = request.clone();
    altered.inputs[0].retention_priority += 1;
    assert_eq!(
        CompactionPublicationProposalV1::new(altered, &host.context(/*now*/ 30)),
        Err(CompactionPublicationError::Compaction(
            QualifiedCompactionError::CandidateSourceMismatch
        ))
    );
    let mut altered = request;
    altered.candidate.retained_records[0].content_digest = digest("substituted-payload");
    assert!(matches!(
        CompactionPublicationProposalV1::new(altered, &host.context(/*now*/ 30)),
        Err(CompactionPublicationError::Compaction(_))
    ));
}

#[test]
fn current_source_and_expired_or_rotated_trust_reject_retained_proposal() {
    let (request, mut host) = publication_request(
        /*next_generation*/ 1, /*source_generation*/ 1, /*predecessor*/ None,
    );
    let binding = request.authenticated_proof.source_binding().clone();
    let proposal =
        CompactionPublicationProposalV1::new(request, &host.context(/*now*/ 30)).unwrap();
    assert!(matches!(
        proposal.revalidate(&host.context(/*now*/ 91)),
        Err(CompactionPublicationError::Authentication(_))
    ));
    host.source_cut = digest("changed-owner-source-cut");
    assert_eq!(
        proposal.revalidate(&host.context(/*now*/ 30)),
        Err(CompactionPublicationError::Authentication(
            AuthenticatedCompactionError::SourceCutBinding
        ))
    );
    host.source_cut = binding.source_cut_digest;
    let mut changed = trust(&binding);
    changed.signers[0].controller_id = id("rotated-controller");
    host.verifier = LearningEvidenceVerifierV1::new(changed).unwrap();
    assert!(matches!(
        proposal.revalidate(&host.context(/*now*/ 30)),
        Err(CompactionPublicationError::Authentication(_))
    ));
}

#[test]
fn sealed_proof_from_another_candidate_cannot_admit_valid_changed_inputs() {
    let (mut request, host) = publication_request(
        /*next_generation*/ 1, /*source_generation*/ 1, /*predecessor*/ None,
    );
    request.inputs[0].record.content_digest = digest("new-content");
    request.candidate = build_qualified_candidate(
        request.candidate.source_snapshot.clone(),
        generation(/*value*/ 1),
        /*predecessor_checkpoint_digest*/ None,
        &request.policy,
        request.inputs.clone(),
    )
    .unwrap();
    assert_eq!(
        CompactionPublicationProposalV1::new(request, &host.context(/*now*/ 30)),
        Err(CompactionPublicationError::Authentication(
            AuthenticatedCompactionError::CandidateBinding
        ))
    );
}

#[test]
fn oversized_input_count_rejects_before_cloning_or_candidate_rebuild() {
    let (mut request, host) = publication_request(
        /*next_generation*/ 1, /*source_generation*/ 1, /*predecessor*/ None,
    );
    request.inputs = vec![request.inputs[0].clone(); MAX_QUALIFIED_COMPACTION_INPUTS + 1];
    assert_eq!(
        CompactionPublicationProposalV1::new(request, &host.context(/*now*/ 30)),
        Err(CompactionPublicationError::Compaction(
            QualifiedCompactionError::InputLimitExceeded
        ))
    );
}

#[test]
fn native_intent_identity_is_stable_across_use_time_and_binds_operation_owner_policy_and_selection()
{
    let (request, host) = publication_request(
        /*next_generation*/ 1, /*source_generation*/ 1, /*predecessor*/ None,
    );
    let proposal =
        CompactionPublicationProposalV1::new(request.clone(), &host.context(/*now*/ 30)).unwrap();
    let later =
        CompactionPublicationProposalV1::new(request.clone(), &host.context(/*now*/ 40)).unwrap();
    assert_eq!(proposal.intent_bytes(), later.intent_bytes());
    for field in ["operation", "owner", "policy-generation"] {
        let mut changed = request.clone();
        let mut altered_host = Host {
            owner: host.owner.clone(),
            scope: host.scope.clone(),
            purpose: host.purpose.clone(),
            selected: host.selected.clone(),
            source_cut: host.source_cut,
            policy_generation: host.policy_generation,
            policy_digest: host.policy_digest,
            verifier: fixture().verifier,
        };
        match field {
            "operation" => changed.operation_id = id("operation:different"),
            "owner" => {
                changed.owner_agent_id = id("owner:different");
                altered_host.owner = changed.owner_agent_id.clone();
            }
            "policy-generation" => {
                changed.policy_generation = generation(/*value*/ 2);
                altered_host.policy_generation = changed.policy_generation;
            }
            _ => unreachable!(),
        }
        let altered =
            CompactionPublicationProposalV1::new(changed, &altered_host.context(/*now*/ 30))
                .unwrap();
        assert_ne!(altered.intent_digest(), proposal.intent_digest());
    }
    let (successor, successor_host) = publication_request(
        /*next_generation*/ 2,
        /*source_generation*/ 1,
        Some(digest("selected")),
    );
    let successor =
        CompactionPublicationProposalV1::new(successor, &successor_host.context(/*now*/ 30))
            .unwrap();
    assert_ne!(successor.intent_digest(), proposal.intent_digest());
}

#[test]
fn configured_policy_generation_and_aggregate_citation_budget_fail_closed() {
    let (request, host) = publication_request(
        /*next_generation*/ 1, /*source_generation*/ 1, /*predecessor*/ None,
    );
    let mut changed = request.clone();
    changed.policy_generation = generation(/*value*/ 2);
    assert_eq!(
        CompactionPublicationProposalV1::new(changed, &host.context(/*now*/ 30)),
        Err(CompactionPublicationError::PolicyGenerationBinding)
    );
    let mut changed = request;
    changed.inputs[0].record.citations = vec![
        codex_hepta_cognitive_types::Citation {
            source_id: id("source:one"),
            source_digest: digest("source")
        };
        crate::MAX_COMPACTION_CITATIONS + 1
    ];
    assert_eq!(
        CompactionPublicationProposalV1::new(changed, &host.context(/*now*/ 30)),
        Err(CompactionPublicationError::Compaction(
            QualifiedCompactionError::ResourceBudgetExceeded(
                crate::CompactionResourceError::CitationLimitExceeded
            )
        ))
    );
}

#[test]
fn current_configured_policy_content_cannot_be_replaced_by_matching_generation_label() {
    let (request, mut host) = publication_request(
        /*next_generation*/ 1, /*source_generation*/ 1, /*predecessor*/ None,
    );
    let proposal =
        CompactionPublicationProposalV1::new(request.clone(), &host.context(/*now*/ 30)).unwrap();
    for digest in [Digest32::ZERO, digest("different-configured-policy")] {
        host.policy_digest = digest;
        assert_eq!(
            CompactionPublicationProposalV1::new(request.clone(), &host.context(/*now*/ 30)),
            Err(CompactionPublicationError::PolicyBinding)
        );
        assert_eq!(
            proposal.revalidate(&host.context(/*now*/ 30)),
            Err(CompactionPublicationError::PolicyBinding)
        );
    }
}
