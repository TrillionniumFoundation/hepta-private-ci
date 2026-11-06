use super::*;
use crate::cell_test_support::*;
use crate::*;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use pretty_assertions::assert_eq;

#[test]
fn complete_native_path_commits_policy_and_state_only_at_owner_boundary() {
    let mut owner = owner(&["run1"]);
    let before = checked(owner.snapshot(&scope("run1")));
    let proposed = proposal(&mut owner, input("run1"));
    assert_eq!(checked(owner.snapshot(&scope("run1"))), before);
    let expected = proposed.receipt().clone();
    let receipt = checked(commit_cell_step(
        &mut owner, proposed, /*now_micros*/ 13,
    ));
    assert_eq!(receipt, expected);
    assert_eq!(receipt.selected_candidate, id("a"));
    assert_eq!(
        receipt
            .policy
            .iter()
            .map(|p| p.probability_ppm)
            .sum::<u32>(),
        1_000_000
    );
    assert_eq!(receipt.authority, AuthorityPosture::DENY_ALL);
    assert_eq!(receipt.cost.model_latency_micros, 20);
    assert_eq!(
        checked(owner.snapshot(&scope("run1")))
            .checkpoint
            .map(|c| c.digest()),
        Some(receipt.checkpoint_after)
    );
    assert_eq!(
        checked(owner.reconcile(
            &scope("run1"),
            &receipt.operation_id,
            receipt.operation_digest
        )),
        Some(receipt)
    );
}

#[test]
fn complete_mask_is_checked_and_masked_maximum_cannot_win() {
    let mut owner = owner(&["run1"]);
    let mut incomplete = input("run1");
    incomplete.candidates.pop();
    assert!(matches!(
        prepare_cell_step(
            &definition(),
            &owner,
            &Encoder,
            incomplete,
            /*now_micros*/ 10
        ),
        Err(CellExecutionError::IncompleteCandidates)
    ));
    let mut masked = input("run1");
    masked.candidates[0].allowed = false;
    let proposed = proposal(&mut owner, masked);
    assert_eq!(proposed.receipt().selected_candidate, id("abstain"));
    assert_eq!(
        proposed.receipt().policy[0],
        CellPolicyEntryV1 {
            candidate_id: id("a"),
            allowed: false,
            probability_ppm: 0,
        }
    );
}

#[test]
fn state_and_exact_operation_identity_are_partitioned_by_run() {
    let mut owner = owner(&["run1", "run2"]);
    let first = proposal(&mut owner, input("run1"));
    assert!(matches!(
        prepare_cell_step(
            &definition(),
            &owner,
            &Encoder,
            input("run1"),
            /*now_micros*/ 11
        ),
        Err(CellExecutionError::InferencePending)
    ));
    let other = proposal(&mut owner, input("run2"));
    let receipt = checked(commit_cell_step(&mut owner, first, /*now_micros*/ 13));
    assert_eq!(
        checked(owner.lookup(
            &scope("run1"),
            &receipt.operation_id,
            receipt.semantic_request_digest
        )),
        Some(receipt.clone())
    );
    assert_ne!(
        checked(commit_cell_step(&mut owner, other, /*now_micros*/ 14)).checkpoint_after,
        receipt.checkpoint_after
    );
    assert!(matches!(
        owner.reconcile(&scope("run1"), &receipt.operation_id, d("different")),
        Err(CellExecutionError::OperationConflict)
    ));
}

#[test]
fn competing_prepared_writers_and_frontier_reset_are_fenced() {
    let mut owner = owner(&["run1"]);
    let first = checked(prepare_cell_step(
        &definition(),
        &owner,
        &Encoder,
        input("run1"),
        /*now_micros*/ 10,
    ));
    let mut other_input = input("run1");
    other_input.operation_id = id("other");
    let competitor = checked(prepare_cell_step(
        &definition(),
        &owner,
        &Encoder,
        other_input,
        /*now_micros*/ 10,
    ));
    let first = checked(infer_cell(
        first,
        &mut owner,
        &mut Model {
            calls: 0,
            latency: 20,
        },
        /*now_micros*/ 11,
    ));
    assert_eq!(
        owner.reset_at_frontier(&scope("run1"), d("new-frontier"), /*writer_epoch*/ 2),
        Err(CellExecutionError::InferencePending)
    );
    let first = checked(decide_cell(first, /*now_micros*/ 12));
    checked(commit_cell_step(&mut owner, first, /*now_micros*/ 13));
    let mut model = Model {
        calls: 0,
        latency: 20,
    };
    assert!(matches!(
        infer_cell(competitor, &mut owner, &mut model, /*now_micros*/ 14),
        Err(CellExecutionError::CommitConflict)
    ));
    assert_eq!(model.calls, 0);
    let mut next = input("run1");
    next.operation_id = id("next");
    next.monotonic_micros = 15;
    let prepared = checked(prepare_cell_step(
        &definition(),
        &owner,
        &Encoder,
        next,
        /*now_micros*/ 15,
    ));
    checked(owner.reset_at_frontier(&scope("run1"), d("new-frontier"), /*writer_epoch*/ 2));
    assert!(matches!(
        infer_cell(prepared, &mut owner, &mut model, /*now_micros*/ 16),
        Err(CellExecutionError::CommitConflict)
    ));
    assert_eq!(model.calls, 0);
    assert_eq!(checked(owner.snapshot(&scope("run1"))).checkpoint, None);
}

#[test]
fn deadlines_and_changed_bundle_reject_before_backend_dispatch() {
    let mut owner = owner(&["run1"]);
    let mut changed = definition();
    changed.bundle_digest = d("new-bundle");
    assert!(matches!(
        prepare_cell_step(
            &changed,
            &owner,
            &Encoder,
            input("run1"),
            /*now_micros*/ 10
        ),
        Err(CellExecutionError::IncompatibleBundle)
    ));
    let prepared = checked(prepare_cell_step(
        &definition(),
        &owner,
        &Encoder,
        input("run1"),
        /*now_micros*/ 10,
    ));
    let mut model = Model {
        calls: 0,
        latency: 20,
    };
    assert!(matches!(
        infer_cell(prepared, &mut owner, &mut model, /*now_micros*/ 100),
        Err(CellExecutionError::DeadlineExceeded)
    ));
    assert_eq!(model.calls, 0);
}

#[test]
fn actual_over_budget_inference_is_recorded_and_abstains() {
    let mut owner = owner(&["run1"]);
    let prepared = checked(prepare_cell_step(
        &definition(),
        &owner,
        &Encoder,
        input("run1"),
        /*now_micros*/ 10,
    ));
    let inferred = checked(infer_cell(
        prepared,
        &mut owner,
        &mut Model {
            calls: 0,
            latency: 3000,
        },
        /*now_micros*/ 11,
    ));
    let proposed = checked(decide_cell(inferred, /*now_micros*/ 12));
    assert_eq!(proposed.receipt().selected_candidate, id("abstain"));
    assert_eq!(proposed.receipt().cost.model_latency_micros, 3000);
}

struct Batch {
    calls: usize,
    omit: bool,
}

impl CellMicrobatchInferenceControlPortV1 for Batch {
    fn execute_feature_batch(
        &mut self,
        requests: &[codex_hepta_infer_core::NeuronFeatureRequestV1],
    ) -> Result<Vec<codex_hepta_infer_core::NeuronFeatureReceiptV1>, NeuronModelError> {
        self.calls += 1;
        let mut results: Vec<_> = requests
            .iter()
            .rev()
            .map(|request| feature_receipt(request, /*latency*/ 20))
            .collect();
        if self.omit {
            results.pop();
        }
        Ok(results)
    }
}

#[test]
fn shared_microbatch_matches_reordered_outputs_to_isolated_requests() {
    let mut owner = owner(&["run1", "run2"]);
    let mut queue = checked(CellBatchQueueV1::new(
        /*max_queued*/ 2, /*max_batch*/ 2,
    ));
    for run in ["run1", "run2"] {
        let prepared = checked(prepare_cell_step(
            &definition(),
            &owner,
            &Encoder,
            input(run),
            /*now_micros*/ 10,
        ));
        checked(queue.enqueue(prepared, /*now_micros*/ 11));
    }
    let mut model = Batch {
        calls: 0,
        omit: false,
    };
    let results = queue.dispatch_next(&mut owner, &mut model, /*clock_micros*/ || 12);
    assert_eq!(model.calls, 1);
    assert_eq!(results.len(), 2);
    for result in results {
        let proposed = checked(decide_cell(checked(result.result), /*now_micros*/ 13));
        assert_eq!(proposed.receipt().scope, result.scope);
        checked(commit_cell_step(
            &mut owner, proposed, /*now_micros*/ 14,
        ));
    }
}

#[test]
fn incomplete_microbatch_cannot_publish_any_state() {
    let mut owner = owner(&["run1", "run2"]);
    let mut queue = checked(CellBatchQueueV1::new(
        /*max_queued*/ 2, /*max_batch*/ 2,
    ));
    for run in ["run1", "run2"] {
        let prepared = checked(prepare_cell_step(
            &definition(),
            &owner,
            &Encoder,
            input(run),
            /*now_micros*/ 10,
        ));
        checked(queue.enqueue(prepared, /*now_micros*/ 11));
    }
    let results = queue.dispatch_next(
        &mut owner,
        &mut Batch {
            calls: 0,
            omit: true,
        },
        /*clock_micros*/ || 12,
    );
    assert_eq!(results.len(), 2);
    assert!(
        results
            .into_iter()
            .all(|r| matches!(r.result, Err(CellExecutionError::ModelBindingMismatch)))
    );
    assert_eq!(checked(owner.snapshot(&scope("run1"))).checkpoint, None);
}

struct UncertainOwner {
    inner: CellPartitionOwnerV1,
}

impl CellStateOwnerV1 for UncertainOwner {
    fn admit_inference(
        &mut self,
        admission: CellInferenceAdmissionV1,
    ) -> Result<(), CellExecutionError> {
        self.inner.admit_inference(admission)
    }
    fn pending_inference(
        &self,
        scope: &CellScopeV1,
    ) -> Result<Option<CellInferenceAdmissionV1>, CellExecutionError> {
        self.inner.pending_inference(scope)
    }
    fn lookup(
        &self,
        scope: &CellScopeV1,
        operation_id: &StableId,
        digest: Digest32,
    ) -> Result<Option<CellDecisionReceiptV1>, CellExecutionError> {
        self.inner.lookup(scope, operation_id, digest)
    }
    fn snapshot(&self, scope: &CellScopeV1) -> Result<CellOwnerSnapshotV1, CellExecutionError> {
        self.inner.snapshot(scope)
    }
    fn commit(
        &mut self,
        proposal: CellStateProposalV1,
        now_micros: u64,
    ) -> Result<CellDecisionReceiptV1, CellExecutionError> {
        self.inner.commit(proposal, now_micros)?;
        Err(CellExecutionError::CommitUncertain)
    }
    fn reconcile(
        &self,
        scope: &CellScopeV1,
        operation_id: &StableId,
        digest: Digest32,
    ) -> Result<Option<CellDecisionReceiptV1>, CellExecutionError> {
        self.inner.reconcile(scope, operation_id, digest)
    }
}

#[test]
fn uncertain_commit_reconciles_exact_persisted_decision_without_new_inference() {
    let mut owner = UncertainOwner {
        inner: owner(&["run1"]),
    };
    let proposed = proposal(&mut owner, input("run1"));
    let expected = proposed.receipt().clone();
    assert!(matches!(
        commit_cell_step(&mut owner, proposed, /*now_micros*/ 13),
        Err(CellExecutionError::CommitUncertain)
    ));
    assert_eq!(
        checked(owner.reconcile(
            &expected.scope,
            &expected.operation_id,
            expected.operation_digest
        )),
        Some(expected)
    );
}

fn update_request() -> CellUpdateRequestV1 {
    let parameter = id("head.weight");
    let mut mask = b"hepta.cell.trainable-mask.v1".to_vec();
    mask.extend_from_slice(&(parameter.as_str().len() as u32).to_be_bytes());
    mask.extend_from_slice(parameter.as_str().as_bytes());
    CellUpdateRequestV1 {
        proposal_id: id("proposal"),
        scope: scope("run1"),
        base_bundle_digest: d("bundle"),
        source_frontier: d("frontier"),
        dataset_digest: d("dataset"),
        dataset_bytes: 1024,
        credit_profile_digest: d("credit"),
        trainable_mask_digest: Digest32::of_bytes(&mask),
        trainable_parameters: vec![parameter],
        from_generation: checked(Generation::new(1)),
        candidate_generation: checked(Generation::new(2)),
        budget: CellUpdateBudgetV1 {
            maximum_dataset_bytes: 2048,
            maximum_steps: 10,
            maximum_elapsed_micros: 10000,
            maximum_working_bytes: 8192,
        },
    }
}

struct Learner {
    wrong_parameter: bool,
    steps: u64,
}

impl CellUpdatePortV1 for Learner {
    fn propose(
        &mut self,
        r: &CellUpdateRequestV1,
    ) -> Result<CellUpdateOutcomeV1, CellExecutionError> {
        Ok(CellUpdateOutcomeV1::Candidate(Box::new(
            CellUpdateCandidateV1 {
                proposal_id: r.proposal_id.clone(),
                base_bundle_digest: r.base_bundle_digest,
                dataset_digest: r.dataset_digest,
                credit_profile_digest: r.credit_profile_digest,
                trainable_mask_digest: r.trainable_mask_digest,
                candidate_generation: r.candidate_generation,
                candidate_artifact_digest: d("candidate"),
                changed_parameters: if self.wrong_parameter {
                    vec![id("unregistered.weight")]
                } else {
                    r.trainable_parameters.clone()
                },
                executed_steps: self.steps,
                elapsed_micros: 100,
                peak_working_bytes: 4096,
                authority: AuthorityPosture::DENY_ALL,
            },
        )))
    }
}

#[test]
fn updates_are_next_generation_bounded_candidates_and_do_not_mutate_live_state() {
    let owner = owner(&["run1"]);
    let before = checked(owner.snapshot(&scope("run1")));
    let result = checked(propose_cell_update(
        &definition(),
        &owner,
        &mut Learner {
            wrong_parameter: false,
            steps: 2,
        },
        &update_request(),
    ));
    assert!(matches!(result, CellUpdateOutcomeV1::Candidate(_)));
    assert_eq!(checked(owner.snapshot(&scope("run1"))), before);
    assert!(matches!(
        propose_cell_update(
            &definition(),
            &owner,
            &mut Learner {
                wrong_parameter: true,
                steps: 2,
            },
            &update_request()
        ),
        Err(CellExecutionError::InvalidInput)
    ));
    assert!(matches!(
        propose_cell_update(
            &definition(),
            &owner,
            &mut Learner {
                wrong_parameter: false,
                steps: 11,
            },
            &update_request()
        ),
        Err(CellExecutionError::InvalidInput)
    ));
}

struct ForbiddenEncoder;

impl CellInputEncoderV1 for ForbiddenEncoder {
    fn encode(
        &self,
        _: &CellEncodingRequestV1<'_>,
    ) -> Result<CellEncodedInputV1, CellExecutionError> {
        panic!("a committed operation must not encode or infer again")
    }
}

#[test]
fn entry_replays_before_encoding_and_new_snapshot_cannot_reidentify_an_operation() {
    let mut owner = owner(&["run1"]);
    let proposed = proposal(&mut owner, input("run1"));
    let receipt = checked(commit_cell_step(
        &mut owner, proposed, /*now_micros*/ 13,
    ));
    assert_eq!(
        checked(canonical_cell_step_request_digest_v1(
            &definition(),
            &input("run1")
        )),
        receipt.semantic_request_digest
    );
    match checked(enter_cell_step(
        &definition(),
        &owner,
        &ForbiddenEncoder,
        input("run1"),
        /*now_micros*/ 500,
    )) {
        CellStepEntryV1::Replayed(actual) => assert_eq!(*actual, receipt),
        CellStepEntryV1::Ready(_) => panic!("committed operation prepared twice"),
    }
    assert!(matches!(
        prepare_cell_step(
            &definition(),
            &owner,
            &ForbiddenEncoder,
            input("run1"),
            /*now_micros*/ 14
        ),
        Err(CellExecutionError::OperationAlreadyCommitted)
    ));
    let mut changed = input("run1");
    changed.observation = b"changed-input".to_vec();
    assert!(matches!(
        prepare_cell_step(
            &definition(),
            &owner,
            &ForbiddenEncoder,
            changed,
            /*now_micros*/ 14
        ),
        Err(CellExecutionError::OperationConflict)
    ));
    assert_eq!(checked(owner.snapshot(&scope("run1"))).revision, 1);
}

struct WrongRequestControl {
    wrong_source: bool,
}

impl NeuronInferenceControlPort for WrongRequestControl {
    fn execute_feature(
        &mut self,
        request: &codex_hepta_infer_core::NeuronFeatureRequestV1,
    ) -> Result<codex_hepta_infer_core::NeuronFeatureReceiptV1, NeuronModelError> {
        let mut other = request.clone();
        if self.wrong_source {
            other.input_digest = d("another-source");
        } else {
            other.request_id = id("another-operation");
        }
        Ok(feature_receipt(&other, /*latency*/ 20))
    }
}

#[test]
fn inference_control_rejects_receipts_from_a_different_source_or_request() {
    for wrong_source in [true, false] {
        let mut owner = owner(&["run1"]);
        let prepared = checked(prepare_cell_step(
            &definition(),
            &owner,
            &Encoder,
            input("run1"),
            /*now_micros*/ 10,
        ));
        assert!(matches!(
            infer_cell(
                prepared,
                &mut owner,
                &mut WrongRequestControl { wrong_source },
                /*now_micros*/ 11
            ),
            Err(CellExecutionError::Backend(NeuronModelError::Rejected))
        ));
        assert_eq!(checked(owner.snapshot(&scope("run1"))).checkpoint, None);
        assert!(checked(owner.pending_inference(&scope("run1"))).is_some());
    }
}

struct WrongModelControl;

impl NeuronInferenceControlPort for WrongModelControl {
    fn execute_feature(
        &mut self,
        request: &codex_hepta_infer_core::NeuronFeatureRequestV1,
    ) -> Result<codex_hepta_infer_core::NeuronFeatureReceiptV1, NeuronModelError> {
        use codex_hepta_infer_core::*;
        let good = feature_receipt(request, /*latency*/ 20);
        let mut runtime = good.runtime_tuple;
        runtime.model_manifest_digest = d("unadmitted-manifest");
        Ok(checked(build_neuron_feature_receipt_v1(
            request,
            runtime,
            NeuronFeatureObservationV1 {
                encoder_digest: good.encoder_digest,
                head_digest: good.head_digest,
                drive_q24: good.drive_q24,
                prediction_q24: good.prediction_q24,
                observed_memory_bytes: good.observed_memory_bytes,
                transient_allocation_bytes: good.transient_allocation_bytes,
                queue_age_micros: good.queue_age_micros,
                latency_micros: good.latency_micros,
                status: good.status,
            },
        )))
    }
}

#[test]
fn a_request_valid_receipt_must_still_match_the_entire_frozen_runtime_tuple() {
    let mut owner = owner(&["run1"]);
    let prepared = checked(prepare_cell_step(
        &definition(),
        &owner,
        &Encoder,
        input("run1"),
        /*now_micros*/ 10,
    ));
    assert!(matches!(
        infer_cell(
            prepared,
            &mut owner,
            &mut WrongModelControl,
            /*now_micros*/ 11
        ),
        Err(CellExecutionError::ModelBindingMismatch)
    ));
}

struct ForgedBatch;

impl CellMicrobatchInferenceControlPortV1 for ForgedBatch {
    fn execute_feature_batch(
        &mut self,
        requests: &[codex_hepta_infer_core::NeuronFeatureRequestV1],
    ) -> Result<Vec<codex_hepta_infer_core::NeuronFeatureReceiptV1>, NeuronModelError> {
        let mut receipts: Vec<_> = requests
            .iter()
            .map(|request| feature_receipt(request, /*latency*/ 20))
            .collect();
        let first = receipts[0].request_digest;
        receipts[0].request_digest = receipts[1].request_digest;
        receipts[1].request_digest = first;
        Ok(receipts)
    }
}

#[test]
fn batch_routing_digest_cannot_relabel_a_receipt_for_another_cell() {
    let mut owner = owner(&["run1", "run2"]);
    let mut queue = checked(CellBatchQueueV1::new(
        /*max_queued*/ 2, /*max_batch*/ 2,
    ));
    for run in ["run1", "run2"] {
        let prepared = checked(prepare_cell_step(
            &definition(),
            &owner,
            &Encoder,
            input(run),
            /*now_micros*/ 10,
        ));
        checked(queue.enqueue(prepared, /*now_micros*/ 11));
    }
    let results = queue.dispatch_next(&mut owner, &mut ForgedBatch, /*clock_micros*/ || 12);
    assert_eq!(results.len(), 2);
    assert!(results.into_iter().all(|r| matches!(
        r.result,
        Err(CellExecutionError::Backend(NeuronModelError::Rejected))
    )));
    assert_eq!(checked(owner.snapshot(&scope("run1"))).revision, 0);
    assert_eq!(checked(owner.snapshot(&scope("run2"))).revision, 0);
}

#[test]
fn shared_inference_ids_are_partitioned_but_do_not_change_with_owner_revision() {
    let mut owner = owner(&["run1", "run2"]);
    let first = checked(prepare_cell_step(
        &definition(),
        &owner,
        &Encoder,
        input("run1"),
        /*now_micros*/ 10,
    ));
    let second = checked(prepare_cell_step(
        &definition(),
        &owner,
        &Encoder,
        input("run2"),
        /*now_micros*/ 10,
    ));
    assert_ne!(
        first.model_request.request_id,
        second.model_request.request_id
    );
    let mut competing = input("run1");
    competing.operation_id = id("other");
    let competing_proposal = proposal(&mut owner, competing);
    checked(commit_cell_step(
        &mut owner,
        competing_proposal,
        /*now_micros*/ 13,
    ));
    let mut later = input("run1");
    later.monotonic_micros = 15;
    let reparsed = checked(prepare_cell_step(
        &definition(),
        &owner,
        &Encoder,
        later,
        /*now_micros*/ 15,
    ));
    assert_eq!(
        first.model_request.request_id,
        reparsed.model_request.request_id
    );
    assert_ne!(
        first.model_request.input_digest,
        reparsed.model_request.input_digest
    );
}

struct UncertainBatch {
    calls: usize,
}

impl CellMicrobatchInferenceControlPortV1 for UncertainBatch {
    fn execute_feature_batch(
        &mut self,
        _: &[codex_hepta_infer_core::NeuronFeatureRequestV1],
    ) -> Result<Vec<codex_hepta_infer_core::NeuronFeatureReceiptV1>, NeuronModelError> {
        self.calls += 1;
        Err(NeuronModelError::Indeterminate)
    }
}

#[test]
fn batch_error_retains_each_admission_and_does_not_repeat_dispatch() {
    let mut owner = owner(&["run1", "run2"]);
    let mut queue = checked(CellBatchQueueV1::new(
        /*max_queued*/ 2, /*max_batch*/ 2,
    ));
    let duplicate = checked(prepare_cell_step(
        &definition(),
        &owner,
        &Encoder,
        input("run1"),
        /*now_micros*/ 10,
    ));
    for run in ["run1", "run2"] {
        let prepared = checked(prepare_cell_step(
            &definition(),
            &owner,
            &Encoder,
            input(run),
            /*now_micros*/ 10,
        ));
        checked(queue.enqueue(prepared, /*now_micros*/ 11));
    }
    let mut model = UncertainBatch { calls: 0 };
    let results = queue.dispatch_next(&mut owner, &mut model, /*clock_micros*/ || 12);
    assert_eq!(results.len(), 2);
    assert!(results.into_iter().all(|r| matches!(
        r.result,
        Err(CellExecutionError::Backend(NeuronModelError::Indeterminate))
    )));
    for run in ["run1", "run2"] {
        assert!(checked(owner.pending_inference(&scope(run))).is_some());
    }
    checked(queue.enqueue(duplicate, /*now_micros*/ 13));
    let results = queue.dispatch_next(&mut owner, &mut model, /*clock_micros*/ || 14);
    assert_eq!(results.len(), 1);
    assert!(
        results
            .into_iter()
            .all(|r| matches!(r.result, Err(CellExecutionError::InferencePending)))
    );
    assert_eq!(model.calls, 1);
}

#[test]
fn batch_dispatch_rechecks_queue_age_and_rejects_clock_rollback_after_admission() {
    for dispatch_at in [11, 17] {
        let mut definition = definition();
        definition.max_queue_age_micros = 5;
        let mut owner = checked(CellPartitionOwnerV1::new(
            /*max_partitions*/ 1, /*max_receipts_per_partition*/ 8,
        ));
        checked(owner.admit(
            scope("run1"),
            &definition,
            d("frontier"),
            /*writer_epoch*/ 1,
        ));
        let prepared = checked(prepare_cell_step(
            &definition,
            &owner,
            &Encoder,
            input("run1"),
            /*now_micros*/ 10,
        ));
        let mut queue = checked(CellBatchQueueV1::new(
            /*max_queued*/ 1, /*max_batch*/ 1,
        ));
        checked(queue.enqueue(prepared, /*now_micros*/ 11));
        let mut reads = 0;
        let mut batch = Batch {
            calls: 0,
            omit: false,
        };
        let results = queue.dispatch_next(&mut owner, &mut batch, || {
            reads += 1;
            if reads == 1 { 12 } else { dispatch_at }
        });
        assert_eq!(reads, 2);
        assert_eq!(batch.calls, 0);
        assert_eq!(results.len(), 1);
        assert!(
            results
                .into_iter()
                .all(|r| matches!(r.result, Err(CellExecutionError::DeadlineExceeded)))
        );
        assert!(checked(owner.pending_inference(&scope("run1"))).is_some());
        assert_eq!(checked(owner.snapshot(&scope("run1"))).revision, 0);
    }
}
