use super::*;

struct UnavailableStage;
impl LearningIterationStageOwnerPortsV1 for UnavailableStage {
    fn validate_recovery<'a>(
        &'a self,
        _: &'a LearningIterationSnapshotV1,
    ) -> LearningIterationOwnerFutureV1<'a, ()> {
        Box::pin(async { Ok(()) })
    }

    fn execute_stage<'a>(
        &'a self,
        _: &'a LearningIterationSnapshotV1,
        _: LearningIterationStageV1,
    ) -> LearningIterationOwnerFutureV1<'a, LearningIterationReceiptV1> {
        Box::pin(async { Err(LearningIterationRuntimeErrorV1::Unavailable) })
    }

    fn prepare_proposal<'a>(
        &'a self,
        _: &'a LearningIterationSnapshotV1,
    ) -> LearningIterationOwnerFutureV1<'a, PreparedLearningIterationProposalV1> {
        Box::pin(async { Err(LearningIterationRuntimeErrorV1::Unavailable) })
    }

    fn receipt_attestation<'a>(
        &'a self,
        _: &'a LearningIterationSnapshotV1,
        _: &'a LearningIterationReceiptV1,
        _: u64,
    ) -> LearningIterationOwnerFutureV1<'a, SignedLearningEvidenceV1> {
        Box::pin(async { Err(LearningIterationRuntimeErrorV1::Unavailable) })
    }
}

#[test]
fn named_original_ports_route_all_seven_stages_without_aliasing() {
    let make_port =
        || -> Arc<dyn LearningIterationStageOwnerPortsV1> { Arc::new(UnavailableStage) };
    let stage_ports = LearningIterationOriginalStagePortsV1 {
        experience: make_port(),
        dataset: make_port(),
        trainer: make_port(),
        evaluator: make_port(),
        proposal: make_port(),
        selector: make_port(),
        next_use_observer: make_port(),
    };
    let stages = [
        (
            LearningIterationStageV1::Experience,
            &stage_ports.experience,
        ),
        (LearningIterationStageV1::Dataset, &stage_ports.dataset),
        (LearningIterationStageV1::Training, &stage_ports.trainer),
        (LearningIterationStageV1::Evaluation, &stage_ports.evaluator),
        (LearningIterationStageV1::Proposal, &stage_ports.proposal),
        (LearningIterationStageV1::Selection, &stage_ports.selector),
        (
            LearningIterationStageV1::NextUse,
            &stage_ports.next_use_observer,
        ),
    ];
    for (index, (stage, expected)) in stages.iter().enumerate() {
        assert!(Arc::ptr_eq(stage_ports.for_stage(*stage), expected));
        for (other_index, (_, other)) in stages.iter().enumerate() {
            if index != other_index {
                assert!(!Arc::ptr_eq(expected, other));
            }
        }
    }
}
