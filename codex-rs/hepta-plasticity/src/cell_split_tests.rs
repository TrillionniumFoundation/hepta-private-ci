    use super::*;
    use crate::TopologyOperationV2;

    fn id(value: &str) -> StableId {
        StableId::new(value).expect("id")
    }
    fn digest(value: &[u8]) -> Digest32 {
        Digest32::of_bytes(value)
    }
    fn generation(value: u64) -> Generation {
        Generation::new(value).expect("generation")
    }
    fn request() -> CellSplitCandidateRequestV1 {
        CellSplitCandidateRequestV1 {
            proposal_id: id("proposal:split:1"),
            proposer_id: id("generator:split"),
            evaluator_id: id("evaluator:split"),
            cell_id: id("cell:parent"),
            child_a_id: id("cell:child-a"),
            child_b_id: id("cell:child-b"),
            parent_artifact_digest: digest(b"parent"),
            baseline_generation: generation(1),
            candidate_generation: generation(2),
            window_digest: digest(b"window"),
            evidence: CellSplitEvidenceV1 {
                residual_digest: digest(b"residual"),
                conflict_digest: digest(b"conflict"),
                split_trigger_digest: digest(b"trigger"),
                baseline_utility_q24: Q24,
                child_a_utility_q24: Q24 + Q24 / 4,
                child_b_utility_q24: Q24,
                retained_task_utility_q24: Q24,
                resource_delta_q24: Q24 / 2,
                independent_evaluation_digest: digest(b"evaluation"),
            },
            state_mapping: vec![CellSplitStateMappingV1 {
                source_slot: 0,
                child_a_slot: Some(0),
                child_b_slot: Some(0),
                state_digest: digest(b"state"),
                optimizer_state_digest: Some(digest(b"optimizer")),
            }],
            capability_typing_digest: digest(b"capability"),
            compatibility_plan_digest: digest(b"compatibility"),
            migration_digest: digest(b"migration"),
            rollback_digest: digest(b"rollback"),
            writer_handoff_digest: digest(b"handoff"),
            resource_review_digest: digest(b"resource"),
            security_review_digest: digest(b"security"),
        }
    }

    #[test]
    fn split_is_deterministic_and_proposal_only() {
        let left = propose_cell_split_candidate_v1(request()).expect("candidate");
        let right = propose_cell_split_candidate_v1(request()).expect("candidate");
        assert_eq!(left, right);
        assert_eq!(left.status, ProposalStatus::RequiresIndependentAcceptance);
        assert!(!left.authority.grants_any());
        verify_cell_split_candidate_v1(&left).expect("verify");
    }

    #[test]
    fn rejects_self_evaluation() {
        let mut value = request();
        value.evaluator_id = value.proposer_id.clone();
        assert_eq!(
            propose_cell_split_candidate_v1(value),
            Err(CellSplitCandidateErrorV1::SelfEvaluation)
        );
    }

    #[test]
    fn rejects_generation_gap() {
        let mut value = request();
        value.candidate_generation = generation(3);
        assert_eq!(
            propose_cell_split_candidate_v1(value),
            Err(CellSplitCandidateErrorV1::GenerationNotExactSuccessor)
        );
    }

    #[test]
    fn rejects_child_identity_collision() {
        let mut value = request();
        value.child_b_id = value.child_a_id.clone();
        assert_eq!(
            propose_cell_split_candidate_v1(value),
            Err(CellSplitCandidateErrorV1::ChildIdentity)
        );
    }

    #[test]
    fn rejects_target_collision() {
        let mut value = request();
        value.state_mapping.push(CellSplitStateMappingV1 {
            source_slot: 1,
            child_a_slot: Some(0),
            child_b_slot: None,
            state_digest: digest(b"state-1"),
            optimizer_state_digest: None,
        });
        assert!(matches!(
            propose_cell_split_candidate_v1(value),
            Err(CellSplitCandidateErrorV1::MappingTargetCollision(0))
        ));
    }

    #[test]
    fn rejects_mutated_digest() {
        let mut candidate = propose_cell_split_candidate_v1(request()).expect("candidate");
        candidate.migration_digest = digest(b"changed");
        assert!(matches!(
            verify_cell_split_candidate_v1(&candidate),
            Err(CellSplitCandidateErrorV1::DigestMismatch)
        ));
    }

    #[test]
    fn option_encoding_distinguishes_absent_from_max_slot() {
        let mut absent = request();
        absent.state_mapping[0].child_a_slot = None;
        absent.state_mapping[0].child_b_slot = Some(0);
        let mut max_slot = absent.clone();
        max_slot.state_mapping[0].child_a_slot = Some(u32::MAX);
        let absent = propose_cell_split_candidate_v1(absent).expect("absent");
        let max_slot = propose_cell_split_candidate_v1(max_slot).expect("max slot");
        assert_ne!(absent.proposal_digest, max_slot.proposal_digest);
    }

    #[test]
    fn projects_only_typed_split_change() {
        let candidate = propose_cell_split_candidate_v1(request()).expect("candidate");
        let change = candidate.topology_change_v2();
        assert_eq!(change.operation, TopologyOperationV2::Split);
        assert_eq!(change.predecessor_digest, Some(candidate.parent_artifact_digest));
        assert_eq!(change.candidate_digest, Some(candidate.proposal_digest));
    }
