use super::*;
use crate::CircuitCellRepresentationEncoderV1;
use crate::circuit_cell_output_schema_v2;
use crate::decode_circuit_cell_ports_v2;
use pretty_assertions::assert_eq;
use std::sync::Arc;

struct Encoders(CircuitCellRepresentationEncoderV1);
impl CellInputEncoderV1 for Encoders {
    fn encode(
        &self,
        request: &CellEncodingRequestV1<'_>,
    ) -> Result<CellEncodedInputV1, CellExecutionError> {
        if request.encoder_digest == self.0.digest() {
            self.0.encode(request)
        } else {
            Encoder.encode(request)
        }
    }
}

struct ObservedModel {
    model: Model,
    features: Vec<Vec<i64>>,
}
impl NeuronInferenceControlPort for ObservedModel {
    fn execute_feature(
        &mut self,
        request: &NeuronFeatureRequestV1,
    ) -> Result<NeuronFeatureReceiptV1, NeuronModelError> {
        self.features.push(request.feature_vector_q24.clone());
        self.model.execute_feature(request)
    }
}
impl CellInferenceReadbackPortV1 for ObservedModel {
    fn read_feature(
        &mut self,
        request: &NeuronFeatureRequestV1,
    ) -> Result<Option<NeuronFeatureReceiptV1>, NeuronModelError> {
        self.model.read_feature(request)
    }
}

#[tokio::test]
async fn committed_q24_ports_feed_successor_features_and_replay_original_output() {
    let (mut definition, mut bindings) = configuration();
    let mut producer = bindings[0].clone();
    producer.node_id = "compute".to_string();
    producer.cell.cell_id = id("source-cell");
    for route in &mut producer.routes {
        if route.outcome == CircuitExitV2::Succeeded {
            route.selected_edges = vec!["next".to_string()];
        }
    }
    let first_cell = producer.cell.clone();
    let encoder = checked(CircuitCellRepresentationEncoderV1::new(
        first_cell.cell_id.clone(),
        first_cell.bundle_digest,
        first_cell.state_schema_digest,
        first_cell.runtime.state_width,
    ));
    bindings[0].cell.runtime.encoder_digest = encoder.digest();
    bindings[0].cell.runtime.input_feature_dimension = 2 * first_cell.runtime.state_width;
    let second_cell = bindings[0].cell.clone();
    bindings.push(producer);
    definition.route_policy_digest = checked(circuit_cell_route_policy_digest_v1(&bindings));
    let program = &mut definition.programs[0];
    program.entry_node = "compute".to_string();
    program.nodes[0].input_schema = circuit_cell_output_schema_v2();
    program.nodes.push(CircuitNodeV2 {
        node_id: "compute".to_string(),
        input_schema: Sha256Digest::for_bytes(b"raw"),
        output_schema: circuit_cell_output_schema_v2(),
        kind: CircuitNodeKindV2::Compute { max_work: 2_000 },
    });
    program.edges.push(CircuitEdgeV2 {
        edge_id: "next".to_string(),
        from: "compute".to_string(),
        to: "decide".to_string(),
        feedback_delay_ms: None,
    });
    let (_directory, store, dispatch) = create_run(&definition).await;
    let mut first_request = request(&dispatch);
    first_request.scope.cell_id = first_cell.cell_id.clone();
    let admission = claim(&store, &dispatch, &first_cell, &first_request, 13).await;
    let owner = native_owner(&bindings);
    let mut runtime = AgentdCircuitCellOwnerV1::new(
        checked(CircuitCellRegistryV1::new(definition, bindings)),
        owner,
        ObservedModel {
            model: Model::new(/*latency*/ 20, /*lose_response*/ false),
            features: vec![],
        },
        Encoders(encoder),
    );
    let first = checked(runtime.execute(admission, first_request.clone(), time));
    let decoded = checked(decode_circuit_cell_ports_v2(&first.output));
    assert_eq!(
        &decoded.representation,
        first.decision.representation.as_ref()
    );
    assert_eq!(decoded.action.policy, first.decision.policy);
    let recovered = checked(
        store
            .recover_circuit_computation("run-1", dispatch.activation_id, &fence(), 21)
            .await,
    );
    assert_eq!(
        checked(
            runtime.execute(recovered, first_request, || CircuitCellTimeV1 {
                circuit_millis: 22,
                cell_micros: 22,
            })
        ),
        first
    );
    assert_eq!(runtime.inference_control.features.len(), 1);
    let mut changed_audit = first.decision.clone();
    changed_audit.operation_id = id("different-audit");
    changed_audit.cost.queue_age_micros += 1;
    assert_eq!(
        checked(encode_ports(&changed_audit, first_cell.state_schema_digest)),
        first.output
    );
    Arc::make_mut(&mut changed_audit.representation).drive_q24[0] += 1;
    assert_ne!(
        checked(encode_ports(&changed_audit, first_cell.state_schema_digest)),
        first.output
    );
    assert_eq!(
        checked(encode_output(&changed_audit)),
        checked(encode_output(&first.decision))
    );

    apply(
        &store,
        "first-complete",
        22,
        CircuitEventV2::Complete {
            completion: first.completion,
        },
    )
    .await;
    let next = apply(
        &store,
        "next-advance",
        23,
        CircuitEventV2::Advance { quantum: 1 },
    )
    .await;
    assert_eq!(next.dispatches.len(), 1);
    let dispatch = &next.dispatches[0];
    let mut second_request = request(dispatch);
    second_request.observation = first.output;
    second_request.monotonic_micros = 30;
    let admission = claim(&store, dispatch, &second_cell, &second_request, 24).await;
    let second = checked(
        runtime.execute(admission, second_request, || CircuitCellTimeV1 {
            circuit_millis: 25,
            cell_micros: 31,
        }),
    );
    let mut expected = decoded.representation.drive_q24;
    expected.extend(decoded.representation.prediction_q24);
    assert_eq!(
        runtime.inference_control.features,
        vec![vec![1 << 24, 1 << 23], expected]
    );
    assert_eq!(second.decision.authority, AuthorityPosture::DENY_ALL);
    assert_eq!(second.output, checked(encode_output(&second.decision)));
    let settled = apply(
        &store,
        "second-complete",
        26,
        CircuitEventV2::Complete {
            completion: second.completion,
        },
    )
    .await;
    assert_eq!(
        (
            settled.run.budget().spent(),
            settled.run.budget().reserved()
        ),
        (40, 0)
    );
    let finished = apply(&store, "exit", 27, CircuitEventV2::Advance { quantum: 1 }).await;
    assert_eq!(finished.run.outcome(), Some(CircuitExitV2::Succeeded));
    store.close().await;
}

#[tokio::test]
async fn representation_encoder_rejects_cross_scope_frontier_shape_and_noncanonical_bytes() {
    let (mut definition, bindings) = configuration();
    for node in &mut definition.programs[0].nodes {
        node.output_schema = circuit_cell_output_schema_v2();
        if node.node_id != "decide" {
            node.input_schema = circuit_cell_output_schema_v2();
        }
    }
    let cell = bindings[0].cell.clone();
    let (_directory, store, dispatch) = create_run(&definition).await;
    let request = request(&dispatch);
    let admission = claim(&store, &dispatch, &cell, &request, 13).await;
    let owner = native_owner(&bindings);
    let mut runtime = AgentdCircuitCellOwnerV1::new(
        checked(CircuitCellRegistryV1::new(definition, bindings)),
        owner,
        Model::new(/*latency*/ 20, /*lose_response*/ false),
        Encoder,
    );
    let output = checked(runtime.execute(admission, request, time)).output;
    let encoder = checked(CircuitCellRepresentationEncoderV1::new(
        cell.cell_id.clone(),
        cell.bundle_digest,
        cell.state_schema_digest,
        cell.runtime.state_width,
    ));
    let consumer = scope("run-1");
    let encode = |consumer: &codex_hepta_neuron::CellScopeV1, frontier, bytes: &[u8]| {
        encoder.encode(&CellEncodingRequestV1 {
            scope: consumer,
            source_frontier: frontier,
            encoder_digest: encoder.digest(),
            observation: bytes,
            checkpoint: None,
        })
    };
    assert_eq!(
        checked(encode(&consumer, d("frontier"), &output)).truncated_bytes,
        0
    );
    for changed in ["agent", "run", "principal"] {
        let mut wrong = consumer.clone();
        match changed {
            "agent" => wrong.agent_id = id("different-agent"),
            "run" => wrong.run_id = id("different-run"),
            "principal" => wrong.principal_digest = d("different-principal"),
            _ => unreachable!(),
        }
        assert_eq!(
            encode(&wrong, d("frontier"), &output),
            Err(CellExecutionError::EncodingMismatch)
        );
    }
    assert_eq!(
        encode(&consumer, d("other-frontier"), &output),
        Err(CellExecutionError::EncodingMismatch)
    );
    for (bundle, schema, width) in [
        (
            d("other-bundle"),
            cell.state_schema_digest,
            cell.runtime.state_width,
        ),
        (
            cell.bundle_digest,
            d("other-schema"),
            cell.runtime.state_width,
        ),
        (
            cell.bundle_digest,
            cell.state_schema_digest,
            cell.runtime.state_width - 1,
        ),
    ] {
        let wrong = checked(CircuitCellRepresentationEncoderV1::new(
            cell.cell_id.clone(),
            bundle,
            schema,
            width,
        ));
        assert_eq!(
            wrong.encode(&CellEncodingRequestV1 {
                scope: &consumer,
                source_frontier: d("frontier"),
                encoder_digest: wrong.digest(),
                observation: &output,
                checkpoint: None,
            }),
            Err(CellExecutionError::EncodingMismatch)
        );
    }
    let mut trailing = output.clone();
    trailing.push(0);
    let mut invalid_width = output.clone();
    let width_offset = b"hepta.circuit.cell-ports.v2\0".len() + 4 * 32;
    invalid_width[width_offset..width_offset + 4].copy_from_slice(&257_u32.to_be_bytes());
    let mut invalid_q24 = output.clone();
    invalid_q24[width_offset + 4..width_offset + 12].copy_from_slice(&i64::MAX.to_be_bytes());
    for bytes in [
        &output[..output.len() - 1],
        &trailing,
        &invalid_width,
        &invalid_q24,
    ] {
        assert!(decode_circuit_cell_ports_v2(bytes).is_err());
        assert_eq!(
            encode(&consumer, d("frontier"), bytes),
            Err(CellExecutionError::EncodingMismatch)
        );
    }
    store.close().await;
}
