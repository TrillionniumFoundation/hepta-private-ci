use super::*;
use crate::cell_test_support::*;
use crate::perception_test_support::*;
use crate::*;
use pretty_assertions::assert_eq;

#[derive(Default)]
struct CaptureControl { requests: Vec<NeuronFeatureRequestV1> }

impl NeuronInferenceControlPort for CaptureControl {
    fn execute_feature(&mut self, request: &NeuronFeatureRequestV1) -> Result<NeuronFeatureReceiptV1, NeuronModelError> {
        self.requests.push(request.clone());
        Ok(feature_receipt(request, /*latency*/ 20))
    }
}

struct UnexpectedEncoder;
impl CellInputEncoderV1 for UnexpectedEncoder {
    fn encode(&self, _: &CellEncodingRequestV1<'_>) -> Result<CellEncodedInputV1, CellExecutionError> {
        panic!("committed operation must not re-encode");
    }
}

#[test]
fn perception_fixture_reaches_shared_inference_and_owner_replay_keeps_exact_evidence() {
    let sources = [actor_source()];
    let observation = observation();
    let encoder = checked(PerceptionCellEncoderV1::new(binding(&observation), &sources));
    let mut definition = definition();
    definition.max_input_bytes = 65_536;
    let mut owner = checked(CellPartitionOwnerV1::new(/*max_partitions*/ 1, /*max_receipts_per_partition*/ 8));
    checked(owner.admit(scope("run1"), &definition, d("frontier"), /*writer_epoch*/ 1));
    let mut input = input("run1");
    input.observation = checked(observation.encode());
    let prepared = checked(prepare_cell_step(&definition, &owner, &encoder, input.clone(), /*now_micros*/ 10));
    let expected_request = prepared.model_request.clone();
    assert_eq!(prepared.encoded, CellEncodedInputV1 {
        encoder_digest: d("encoder"), feature_vector_q24: vec![1 << 24, 1 << 23],
        consumed_bytes: input.observation.len(), truncated_bytes: 0,
    });
    let mut control = CaptureControl::default();
    let inferred = checked(infer_cell(prepared, &mut owner, &mut control, /*now_micros*/ 11));
    assert_eq!(control.requests, vec![NeuronFeatureRequestV1 {
        request_id: expected_request.request_id,
        generation: expected_request.generation,
        model_id: expected_request.model_id,
        encoder_digest: expected_request.encoder_digest,
        head_digest: expected_request.head_digest,
        weights_digest: expected_request.weights_digest,
        input_digest: expected_request.input_digest,
        feature_vector_q24: expected_request.feature_vector_q24,
        expected_output_width: expected_request.expected_output_width,
    }]);
    let proposed = checked(decide_cell(inferred, /*now_micros*/ 12));
    let receipt = checked(commit_cell_step(&mut owner, proposed, /*now_micros*/ 13));
    match checked(enter_cell_step(&definition, &owner, &UnexpectedEncoder, input.clone(), /*now_micros*/ 14)) {
        CellStepEntryV1::Replayed(replayed) => assert_eq!(*replayed, receipt),
        CellStepEntryV1::Ready(_) => panic!("expected owner replay"),
    }
    assert_eq!((receipt.authority, receipt.cost.consumed_input_bytes, receipt.cost.truncated_input_bytes),
        (AuthorityPosture::DENY_ALL, input.observation.len(), 0));
    let mut changed = observation;
    changed.evidence[0].raw_bytes[0] ^= 1;
    changed.latents[0].evidence_digests = vec![checked(changed.evidence[0].digest()).into_array()];
    input.observation = checked(changed.encode());
    assert!(matches!(enter_cell_step(&definition, &owner, &UnexpectedEncoder, input, /*now_micros*/ 14), Err(CellExecutionError::OperationConflict)));
}

#[test]
fn perception_adapter_checks_scope_frontier_encoder_and_actor_source_before_inference() {
    let original = observation();
    let sources = [actor_source()];
    let encoder = checked(PerceptionCellEncoderV1::new(binding(&original), &sources));
    let scope = scope("run1");
    for (mutation, expected) in [
        (0, CellExecutionError::ScopeMismatch),
        (1, CellExecutionError::StaleSource),
        (2, CellExecutionError::EncodingMismatch),
        (3, CellExecutionError::StaleSource),
    ] {
        let mut changed = original.clone();
        match mutation {
            0 => changed.scope_digest = d("other-scope").into_array(),
            1 => changed.source_frontier = d("other-frontier").into_array(),
            2 => changed.latent_model_digest = d("other-model").into_array(),
            3 => {
                changed.evidence[0].raw_bytes[0] ^= 1;
                changed.latents[0].evidence_digests = vec![checked(changed.evidence[0].digest()).into_array()];
            }
            _ => unreachable!(),
        }
        let bytes = checked(changed.encode());
        assert_eq!(encoder.encode(&CellEncodingRequestV1 {
            scope: &scope, source_frontier: d("frontier"), encoder_digest: d("encoder"),
            observation: &bytes, checkpoint: None,
        }), Err(expected));
    }
}
