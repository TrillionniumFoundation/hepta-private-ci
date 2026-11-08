use super::*;
use crate::CellPartitionOwnerV1;
use crate::cell_test_support::*;
use pretty_assertions::assert_eq;

fn mask_digest(parameters: &[StableId]) -> Digest32 {
    let mut bytes = b"hepta.cell.trainable-mask.v1".to_vec();
    for parameter in parameters {
        bytes.extend_from_slice(&(parameter.as_str().len() as u32).to_be_bytes());
        bytes.extend_from_slice(parameter.as_str().as_bytes());
    }
    Digest32::of_bytes(&bytes)
}

fn request() -> CellUpdateRequestV1 {
    let trainable_parameters = vec![id("head.weight")];
    CellUpdateRequestV1 {
        proposal_id: id("proposal"),
        scope: scope("run1"),
        base_bundle_digest: d("bundle"),
        source_frontier: d("frontier"),
        dataset_digest: d("dataset"),
        dataset_bytes: 1024,
        credit_profile_digest: d("credit"),
        trainable_mask_digest: mask_digest(&trainable_parameters),
        trainable_parameters,
        from_generation: checked(Generation::new(1)),
        candidate_generation: checked(Generation::new(2)),
        budget: CellUpdateBudgetV1 {
            maximum_dataset_bytes: 2048,
            maximum_steps: 10,
            maximum_elapsed_micros: 10_000,
            maximum_working_bytes: 8192,
        },
    }
}

fn candidate(request: &CellUpdateRequestV1) -> CellUpdateOutcomeV1 {
    CellUpdateOutcomeV1::Candidate(Box::new(CellUpdateCandidateV1 {
        proposal_id: request.proposal_id.clone(),
        request_digest: request.semantic_digest(),
        base_bundle_digest: request.base_bundle_digest,
        dataset_digest: request.dataset_digest,
        credit_profile_digest: request.credit_profile_digest,
        trainable_mask_digest: request.trainable_mask_digest,
        candidate_generation: request.candidate_generation,
        candidate_artifact_digest: d("candidate"),
        changed_parameters: request.trainable_parameters.clone(),
        executed_steps: 2,
        elapsed_micros: 100,
        peak_working_bytes: 4096,
        authority: AuthorityPosture::DENY_ALL,
    }))
}

struct Learner {
    calls: usize,
    retained: CellUpdateOutcomeV1,
}

impl CellUpdatePortV1 for Learner {
    fn propose(
        &mut self,
        _: &CellUpdateRequestV1,
    ) -> Result<CellUpdateOutcomeV1, CellExecutionError> {
        self.calls += 1;
        Ok(self.retained.clone())
    }
}

fn admitted_owner(
    definition: &CellDefinitionV1,
    request: &CellUpdateRequestV1,
) -> CellPartitionOwnerV1 {
    let mut owner = checked(CellPartitionOwnerV1::new(
        /*max_partitions*/ 2, /*max_receipts_per_partition*/ 2,
    ));
    checked(owner.admit(
        request.scope.clone(),
        definition,
        request.source_frontier,
        /*writer_epoch*/ 1,
    ));
    owner
}

#[test]
fn caller_cannot_expand_the_registered_training_mask_even_with_its_matching_digest() {
    let owner = owner(&["run1"]);
    let before = checked(owner.snapshot(&scope("run1")));
    for parameters in [
        vec![id("backbone.weight")],
        vec![id("head.weight"), id("backbone.weight")],
    ] {
        let mut request = request();
        request.trainable_mask_digest = mask_digest(&parameters);
        request.trainable_parameters = parameters;
        let mut learner = Learner {
            calls: 0,
            retained: CellUpdateOutcomeV1::NoUpdate,
        };
        assert_eq!(
            propose_cell_update(&definition(), &owner, &mut learner, &request),
            Err(CellExecutionError::InvalidInput)
        );
        assert_eq!(learner.calls, 0);
        assert_eq!(checked(owner.snapshot(&request.scope)), before);
    }
}

#[test]
fn registered_definition_prevents_a_caller_from_replacing_the_training_policy() {
    let owner = owner(&["run1"]);
    let before = checked(owner.snapshot(&scope("run1")));
    let mut altered = definition();
    altered.trainable_parameters.push(id("backbone.weight"));
    let mut request = request();
    request.trainable_parameters = altered.trainable_parameters.clone();
    request.trainable_mask_digest = mask_digest(&request.trainable_parameters);
    let mut learner = Learner {
        calls: 0,
        retained: candidate(&request),
    };
    assert_eq!(
        propose_cell_update(&altered, &owner, &mut learner, &request),
        Err(CellExecutionError::IncompatibleBundle)
    );
    assert_eq!(learner.calls, 0);
    assert_eq!(checked(owner.snapshot(&request.scope)), before);
}

#[test]
fn inference_only_definition_rejects_training_before_contacting_the_learner() {
    let mut definition = definition();
    definition.trainable_parameters.clear();
    let request = request();
    let owner = admitted_owner(&definition, &request);
    let before = checked(owner.snapshot(&request.scope));
    let mut learner = Learner {
        calls: 0,
        retained: candidate(&request),
    };
    assert_eq!(
        propose_cell_update(&definition, &owner, &mut learner, &request),
        Err(CellExecutionError::InvalidInput)
    );
    assert_eq!(learner.calls, 0);
    assert_eq!(checked(owner.snapshot(&request.scope)), before);
}

#[test]
fn owner_admission_rejects_duplicate_or_oversized_training_policies() {
    let mut definition = definition();
    definition.trainable_parameters = (0..MAX_CELL_TRAINABLE_PARAMETERS)
        .map(|index| id(&format!("parameter.{index}")))
        .collect();
    let request = request();
    let mut owner = admitted_owner(&definition, &request);
    let before = checked(owner.snapshot(&request.scope));
    let mut oversized = definition.trainable_parameters.clone();
    oversized.push(id("one.too.many"));
    for parameters in [oversized, vec![id("head.weight"), id("head.weight")]] {
        let mut invalid = definition.clone();
        invalid.trainable_parameters = parameters;
        assert_eq!(
            owner.admit(
                scope("invalid-policy"),
                &invalid,
                d("frontier"),
                /*writer_epoch*/ 1,
            ),
            Err(CellExecutionError::InvalidDefinition)
        );
        let mut learner = Learner {
            calls: 0,
            retained: CellUpdateOutcomeV1::NoUpdate,
        };
        assert_eq!(
            propose_cell_update(&invalid, &owner, &mut learner, &request),
            Err(CellExecutionError::InvalidDefinition)
        );
        assert_eq!(learner.calls, 0);
        assert_eq!(checked(owner.snapshot(&request.scope)), before);
    }
}

#[test]
fn retained_candidate_cannot_cross_cell_task_principal_source_or_budget() {
    let original = request();
    let retained = candidate(&original);
    let changes: &[fn(&mut CellUpdateRequestV1)] = &[
        |request| request.scope.agent_id = id("another.agent"),
        |request| request.scope.cell_id = id("another.cell"),
        |request| request.scope.run_id = id("another.run"),
        |request| request.scope.principal_digest = d("another.principal"),
        |request| request.source_frontier = d("another.frontier"),
        |request| request.dataset_bytes += 1,
        |request| request.budget.maximum_dataset_bytes += 1,
        |request| request.budget.maximum_steps += 1,
        |request| request.budget.maximum_elapsed_micros += 1,
        |request| request.budget.maximum_working_bytes += 1,
    ];
    for (index, change) in changes.iter().enumerate() {
        let mut changed = original.clone();
        change(&mut changed);
        let mut definition = definition();
        definition.cell_id = changed.scope.cell_id.clone();
        let owner = admitted_owner(&definition, &changed);
        let before = checked(owner.snapshot(&changed.scope));
        let mut learner = Learner {
            calls: 0,
            retained: retained.clone(),
        };
        assert_eq!(
            propose_cell_update(&definition, &owner, &mut learner, &changed),
            Err(CellExecutionError::InvalidInput),
            "reused candidate accepted request mutation {index}"
        );
        assert_eq!(learner.calls, 1);
        assert_eq!(checked(owner.snapshot(&changed.scope)), before);
        // The new owner/request is valid; a freshly bound candidate can pass.
        learner.retained = candidate(&changed);
        assert_eq!(
            checked(propose_cell_update(
                &definition,
                &owner,
                &mut learner,
                &changed,
            )),
            learner.retained
        );
        assert_eq!(checked(owner.snapshot(&changed.scope)), before);
    }
}

#[test]
fn valid_subset_and_no_update_keep_candidates_authority_free_and_live_state_unchanged() {
    let mut definition = definition();
    definition.trainable_parameters.push(id("head.bias"));
    let request = request();
    let mut owner = admitted_owner(&definition, &request);
    checked(owner.admit(
        scope("run2"),
        &definition,
        d("frontier"),
        /*writer_epoch*/ 1,
    ));
    let scopes = [request.scope.clone(), scope("run2")];
    let before = scopes
        .each_ref()
        .map(|scope| checked(owner.snapshot(scope)));
    for expected in [candidate(&request), CellUpdateOutcomeV1::NoUpdate] {
        let mut learner = Learner {
            calls: 0,
            retained: expected.clone(),
        };
        let result = checked(propose_cell_update(
            &definition,
            &owner,
            &mut learner,
            &request,
        ));
        assert_eq!(result, expected);
        if let CellUpdateOutcomeV1::Candidate(candidate) = result {
            assert_eq!(candidate.authority, AuthorityPosture::DENY_ALL);
        }
        assert_eq!(learner.calls, 1);
        assert_eq!(
            scopes
                .each_ref()
                .map(|scope| checked(owner.snapshot(scope))),
            before
        );
    }
}
