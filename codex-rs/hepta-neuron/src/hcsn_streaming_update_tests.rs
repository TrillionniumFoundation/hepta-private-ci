use super::*;
use crate::cell_test_support::*;
use crate::hcsn_streaming_test_support::fixture;
use crate::*;
use codex_hepta_types::Generation;
use pretty_assertions::assert_eq;
use serde_json::Value;

fn admission(state: &HcsnStreamingStateV1) -> HcsnStreamingUpdateAdmissionV1 {
    let mut mask = b"hepta.cell.trainable-mask.v1".to_vec();
    let parameters = vec![id("readout.bias"), id("readout.weight")];
    for name in &parameters {
        mask.extend_from_slice(&(name.as_str().len() as u32).to_be_bytes());
        mask.extend_from_slice(name.as_str().as_bytes());
    }
    HcsnStreamingUpdateAdmissionV1 {
        request: CellUpdateRequestV1 {
            proposal_id: id("streaming-ridge-proposal"),
            scope: scope("run1"),
            base_bundle_digest: d("bundle"),
            source_frontier: d("frontier"),
            dataset_digest: state.snapshot.binding.dataset_digest,
            dataset_bytes: 128,
            credit_profile_digest: d("credit"),
            trainable_mask_digest: Digest32::of_bytes(&mask),
            trainable_parameters: parameters,
            from_generation: checked(Generation::new(1)),
            candidate_generation: checked(Generation::new(2)),
            budget: CellUpdateBudgetV1 {
                maximum_dataset_bytes: 1_024,
                maximum_steps: 1,
                maximum_elapsed_micros: 300_000_000,
                maximum_working_bytes: 2_000_000_000,
            },
        },
        research_binding: state.snapshot.binding,
        base_parameters_digest: Digest32::of_bytes(&state.snapshot.parameters),
        // Unit host context, not a measured task-performance assertion.
        observed_peak_working_bytes: 1_000_000_000,
    }
}

fn candidate() -> Vec<u8> {
    let fixture: Value = checked(serde_json::from_str(include_str!(
        "../tests/fixtures/hcsn-streaming-ridge-v1.json"
    )));
    checked(serde_json::to_vec(&fixture["candidate_readout"]))
}

#[test]
fn actual_ridge_solution_reaches_cell_update_without_live_state_mutation() {
    let (context, clock, bytes) = fixture();
    let state = checked(restore_hcsn_research_state_v2(
        &context,
        &clock,
        &bytes,
        &HcsnStreamingCodecV1,
    ))
    .state;
    let admitted = admission(&state);
    let request = admitted.request.clone();
    let mut port = checked(HcsnStreamingUpdatePortV1::prepare(
        admitted,
        &state,
        &candidate(),
    ));
    let owner = owner(&["run1"]);
    let before = checked(owner.snapshot(&scope("run1")));
    let artifact_digest = Digest32::of_bytes(port.artifact_bytes());
    assert_eq!(
        port.lineage()[5],
        hcsn_streaming_request_digest_v1(&request)
    );
    assert_eq!(port.lineage()[6], state.clock_digest());
    assert_eq!(port.lineage()[7], artifact_digest);
    let outcome = checked(propose_cell_update(
        &definition(),
        &owner,
        &mut port,
        &request,
    ));
    match outcome {
        CellUpdateOutcomeV1::Candidate(candidate) => {
            assert_eq!(candidate.changed_parameters, request.trainable_parameters);
            assert_eq!(candidate.candidate_artifact_digest, artifact_digest);
            assert_eq!(candidate.candidate_generation, request.candidate_generation);
            assert_eq!(candidate.executed_steps, 1);
            assert_eq!(candidate.authority, AuthorityPosture::DENY_ALL);
        }
        CellUpdateOutcomeV1::NoUpdate => panic!("real fixture did not change the readout"),
    }
    assert_eq!(checked(owner.snapshot(&scope("run1"))), before);
    assert_eq!(checked(state.encode()), bytes);
    assert_eq!(
        port.propose(&request),
        Err(CellExecutionError::OperationConflict)
    );
}

#[test]
fn rejects_fake_solve_and_wrong_rule_budget_or_parameter_bindings() {
    let (context, clock, bytes) = fixture();
    let state = checked(restore_hcsn_research_state_v2(
        &context,
        &clock,
        &bytes,
        &HcsnStreamingCodecV1,
    ))
    .state;
    for mutation in [
        "solve",
        "dataset",
        "base",
        "mask",
        "rule",
        "time",
        "memory",
        "scope",
        "frontier",
        "bundle",
        "generation",
    ] {
        let mut admitted = admission(&state);
        let mut payload = candidate();
        match mutation {
            "solve" => {
                let mut value: Value = checked(serde_json::from_slice(&payload));
                value["weight"]["bits"][0] = Value::from(1_000_f64.to_bits());
                payload = checked(serde_json::to_vec(&value));
            }
            "dataset" => admitted.request.dataset_digest = d("another-dataset"),
            "base" => admitted.base_parameters_digest = d("another-model"),
            "mask" => admitted.request.trainable_parameters = vec![id("flow.drive.weight")],
            "rule" => admitted.research_binding.learning_rule_digest = d("bp"),
            "time" => admitted.request.budget.maximum_elapsed_micros = 0,
            "memory" => admitted.observed_peak_working_bytes = 0,
            "scope" => admitted.request.scope.run_id = id("other-run"),
            "frontier" => admitted.request.source_frontier = d("other-frontier"),
            "bundle" => admitted.request.base_bundle_digest = d("other-bundle"),
            "generation" => {
                admitted.request.from_generation = checked(Generation::new(3));
                admitted.request.candidate_generation = checked(Generation::new(4));
            }
            _ => panic!("unknown mutation"),
        }
        assert_eq!(
            HcsnStreamingUpdatePortV1::prepare(admitted, &state, &payload).err(),
            Some(CellExecutionError::InvalidInput),
            "{mutation}"
        );
    }
}

#[test]
fn failed_and_discarded_proposals_cannot_reuse_the_one_step_budget() {
    let (mut context, clock, bytes) = fixture();
    let original = checked(restore_hcsn_research_state_v2(
        &context,
        &clock,
        &bytes,
        &HcsnStreamingCodecV1,
    ))
    .state;
    let value: Value = checked(serde_json::from_str(include_str!(
        "../tests/fixtures/hcsn-streaming-ridge-v1.json"
    )));
    for variant in checked(value["cost_overruns"].as_array().ok_or("variants")) {
        let hex = checked(variant["state_hex"].as_str().ok_or("state hex"));
        let bytes = (0..hex.len())
            .step_by(2)
            .map(|i| checked(u8::from_str_radix(&hex[i..i + 2], 16)))
            .collect::<Vec<_>>();
        assert_eq!(
            Digest32::of_bytes(&bytes).to_string(),
            variant["state_digest"]
        );
        let clock = checked(HcsnClockCheckpointV1::initial(
            &context.profile,
            context.identity,
            original.time_micros(),
            Digest32::of_bytes(&bytes),
        ));
        context.checkpoint_digest = clock.digest();
        let state = checked(restore_hcsn_research_state_v2(
            &context,
            &checked(clock.encode()),
            &bytes,
            &HcsnStreamingCodecV1,
        ))
        .state;
        assert_eq!(state.controller.solves, 1);
        assert_eq!(state.cost().charged_proposals, 2);
        assert_eq!(
            HcsnStreamingUpdatePortV1::prepare(admission(&state), &state, &candidate()).err(),
            Some(CellExecutionError::InvalidInput)
        );
    }
}
