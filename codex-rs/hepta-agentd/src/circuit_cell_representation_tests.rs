use std::cell::Cell;

use codex_hepta_types::Generation;
use pretty_assertions::assert_eq;

use super::*;
use crate::CircuitCellRepresentationResolverV1;
use crate::CircuitCellRepresentationUseV1;

struct CurrentOwners {
    current: CellRepresentationUseV1,
    calls: Cell<usize>,
    stale_on: usize,
}

impl CircuitCellRepresentationResolverV1 for CurrentOwners {
    fn current_use(
        &self,
        scope: &CellScopeV1,
    ) -> Result<CellRepresentationUseV1, CellExecutionError> {
        assert_eq!(scope, &self.current.scope);
        let call = self.calls.get() + 1;
        self.calls.set(call);
        let mut current = self.current.clone();
        if call >= self.stale_on {
            current.producer.generation = checked(Generation::new(3));
        }
        Ok(current)
    }
}

fn projected_input() -> (
    RegisteredCellBackendV1,
    CellNativeRepresentationInputV1,
    CellRepresentationUseV1,
) {
    let (backend, projected, current, _, _, _) = projected_materials();
    (backend, projected, current)
}

fn projected_materials() -> (
    RegisteredCellBackendV1,
    CellNativeRepresentationInputV1,
    CellRepresentationUseV1,
    CellRepresentationNegotiationV1,
    CellRepresentationV1,
    CellGlobalQ24SelectionV1,
) {
    let definition = cell_definition();
    let generation = checked(Generation::new(1));
    let capability = CellCapabilityContractV1 {
        type_id: id("representation-type"),
        generation,
        role: CellFunctionalRoleV1::MemoryAssociation,
        input_schema_digest: checked(cell_global_feature_schema_digest_v1(2)),
        output_schema_digest: cell_native_decision_schema_digest_v1(),
        state_schema_digest: definition.state_schema_digest,
        behavior_contract_digest: d("behavior"),
    };
    let registration = CellBackendRegistrationV1 {
        backend_id: id("representation-backend"),
        family: CellBackendFamilyV1::FrozenRepresentationPrivateHead,
        expert: CellExpertVersionV1 {
            version_id: id("expert"),
            type_id: capability.type_id.clone(),
            capability_digest: checked(capability.digest()),
            shared_base_digest: d("shared-model"),
            parameter_bundle_digest: definition.bundle_digest,
        },
        capability,
        definition,
    };
    let registry = checked(CellBackendRegistryV1::new(
        vec![registration.clone()],
        /*max_backends*/ 1,
    ));
    let backend =
        checked(registry.resolve(&registration.backend_id, checked(registration.digest()))).clone();
    let profile = CellRepresentationProfileV1 {
        profile_id: id("encoder-global"),
        generation,
        semantic_schema_digest: d("encoder-semantics"),
        kind: CellRepresentationKindV1::GlobalVector,
        tensors: vec![CellTensorLayoutV1 {
            name: id("features"),
            role: CellTensorRoleV1::Features,
            dtype: CellTensorDtypeV1::F32Le,
            shape: vec![768],
            axes: vec![id("feature")],
            modality: None,
            optional: false,
        }],
        max_payload_bytes: 768 * 4,
    };
    let context = CellRepresentationContextV1 {
        producer_id: id("encoder-owner"),
        producer_generation: checked(Generation::new(2)),
        producer_binding_digest: d("encoder-artifact"),
        scope: scope("run-1"),
        source_frontier: d("frontier"),
        source_bundle_digest: d("source-bundle"),
        source_record_digest: d("source-record"),
        causal_receipt_digest: d("source-cause"),
    };
    let source = checked(CellRepresentationV1::new(
        profile.clone(),
        context.clone(),
        vec![CellTensorValueV1::Present(
            (0..768).flat_map(|_| 0.5_f32.to_le_bytes()).collect(),
        )],
    ));
    let mut output = profile.clone();
    output.profile_id = id("native-global");
    output.semantic_schema_digest = checked(cell_global_feature_schema_digest_v1(2));
    output.tensors[0].dtype = CellTensorDtypeV1::SignedQ24Le;
    output.tensors[0].shape = vec![2];
    output.max_payload_bytes = 16;
    let selection = checked(CellGlobalQ24SelectionV1::new(vec![0, 767]));
    let component = CellProjectionComponentV1 {
        component_id: id("qualified-selection"),
        generation,
        input_profile_digest: checked(profile.digest()),
        output_profile_digest: checked(output.digest()),
        implementation_digest: CellGlobalQ24SelectionV1::implementation_digest(),
        parameters_digest: selection.parameters_digest(),
        quality_evidence_digest: d("owner-quality-evidence"),
    };
    let producer = CellRepresentationProducerV1 {
        producer_id: context.producer_id.clone(),
        generation: context.producer_generation,
        binding_digest: context.producer_binding_digest,
        offered_profiles: vec![checked(profile.digest())],
        max_payload_bytes: profile.max_payload_bytes,
    };
    let consumer = CellRepresentationConsumerV1 {
        consumer_id: registration.backend_id,
        generation,
        binding_digest: backend.digest(),
        accepted_profiles: vec![checked(output.digest())],
        qualified_projections: vec![checked(component.digest())],
        max_payload_bytes: output.max_payload_bytes,
    };
    let current = CellRepresentationUseV1 {
        producer: CellRepresentationEndpointUseV1 {
            endpoint_id: producer.producer_id.clone(),
            generation: producer.generation,
            binding_digest: producer.binding_digest,
            contract_digest: checked(producer.digest()),
        },
        consumer: CellRepresentationEndpointUseV1 {
            endpoint_id: consumer.consumer_id.clone(),
            generation: consumer.generation,
            binding_digest: consumer.binding_digest,
            contract_digest: checked(consumer.digest()),
        },
        scope: context.scope,
        source_frontier: context.source_frontier,
    };
    let negotiation = checked(CellRepresentationNegotiationV1::projected(
        producer, consumer, profile, output, component,
    ));
    let projected = checked(CellNativeRepresentationInputV1::project(
        &backend,
        &negotiation,
        &source,
        &current,
        &selection,
    ));
    (backend, projected, current, negotiation, source, selection)
}

async fn projected_run(
    definition: &BoundedCircuitDefinitionV2,
    projected: &CellNativeRepresentationInputV1,
) -> (
    tempfile::TempDir,
    AutomationStore,
    CircuitDispatchV2,
    CellStepInputV1,
) {
    let directory = tempfile::tempdir().expect("private representation circuit");
    let layout = checked(HeptaFleetRoot::parse(directory.path().join("fleet")))
        .layout()
        .agent(&fence().owner_agent_id);
    let store = checked(AutomationStore::open(&layout).await);
    checked(
        store
            .create_bounded_circuit_run(
                definition,
                &CircuitStartV2 {
                    run_id: "run-1".to_string(),
                    scope_digest: checked(circuit_cell_scope_digest_v1(&scope("run-1"))),
                    input_digest: Sha256Digest::for_bytes(projected.observation_bytes()),
                    created_at_ms: 10,
                    lease_duration_ms: 500,
                },
                &fence(),
            )
            .await,
    );
    let advanced = apply(
        &store,
        "advance",
        11,
        CircuitEventV2::Advance { quantum: 1 },
    )
    .await;
    let dispatch = advanced.dispatches[0].clone();
    let mut request = request(&dispatch);
    request.observation = projected.observation_bytes().to_vec();
    (directory, store, dispatch, request)
}

#[tokio::test]
async fn represented_circuit_uses_both_current_owners_and_replays_after_their_selection_changes() {
    let (backend, projected, current) = projected_input();
    let (definition, bindings) = configuration();
    let (_directory, store, dispatch, request) = projected_run(&definition, &projected).await;
    let admission = claim(&store, &dispatch, &bindings[0].cell, &request, 13).await;
    let model = Model::new(/*latency*/ 20, /*lose_response*/ false);
    let calls = model.calls.clone();
    let owner = native_owner(&bindings);
    let mut runtime = AgentdCircuitCellOwnerV1::new(
        checked(CircuitCellRegistryV1::new(definition, bindings)),
        owner,
        model,
        Encoder,
    );
    let resolver = CurrentOwners {
        current,
        calls: Cell::new(0),
        stale_on: 4,
    };
    let represented = || CircuitCellRepresentationUseV1 {
        backend: &backend,
        input: &projected,
        resolver: &resolver,
    };
    let executed =
        checked(runtime.execute_representation(admission, request.clone(), represented(), time));
    assert_eq!(
        resolver.calls.get(),
        3,
        "at preparation, before admission, and at actual model contact"
    );
    assert_eq!(executed.decision.authority, AuthorityPosture::DENY_ALL);
    assert_eq!(
        executed.decision.cost.consumed_input_bytes,
        projected.observation_bytes().len()
    );
    let recovery = checked(
        store
            .recover_circuit_computation("run-1", dispatch.activation_id, &fence(), 21)
            .await,
    );
    let replayed = checked(runtime.execute_representation(
        recovery,
        request,
        represented(),
        || CircuitCellTimeV1 {
            circuit_millis: 22,
            cell_micros: 22,
        },
    ));
    assert_eq!(replayed, executed);
    assert_eq!((calls.load(Ordering::SeqCst), resolver.calls.get()), (1, 3));
    let mut foreign = backend.registration().clone();
    foreign.expert.version_id = id("different-expert-same-definition");
    let foreign_registry = checked(CellBackendRegistryV1::new(
        vec![foreign.clone()],
        /*max_backends*/ 1,
    ));
    let foreign = checked(foreign_registry.resolve(&foreign.backend_id, checked(foreign.digest())));
    let recovery = checked(
        store
            .recover_circuit_computation("run-1", dispatch.activation_id, &fence(), 22)
            .await,
    );
    let mut replay_input = input("run-1");
    replay_input.operation_id = checked(circuit_cell_operation_id_v1(&dispatch));
    replay_input.observation = projected.observation_bytes().to_vec();
    assert_eq!(
        runtime.execute_representation(
            recovery,
            replay_input,
            CircuitCellRepresentationUseV1 {
                backend: foreign,
                input: &projected,
                resolver: &resolver,
            },
            || CircuitCellTimeV1 {
                circuit_millis: 23,
                cell_micros: 23
            }
        ),
        Err(CircuitCellErrorV1::Cell(
            CellExecutionError::IncompatibleBundle
        ))
    );
    assert_eq!((calls.load(Ordering::SeqCst), resolver.calls.get()), (1, 3));
    let completion = apply(
        &store,
        "complete",
        23,
        CircuitEventV2::Complete {
            completion: replayed.completion,
        },
    )
    .await;
    assert_eq!(
        (
            completion.run.budget().spent(),
            completion.run.budget().reserved()
        ),
        (20, 0)
    );
    store.close().await;
}

#[tokio::test]
async fn represented_circuit_refuses_stale_before_admission_and_preserves_post_admission_unknown() {
    for stale_on in [1, 2, 3] {
        let (backend, projected, current) = projected_input();
        let (definition, bindings) = configuration();
        let (_directory, store, dispatch, request) = projected_run(&definition, &projected).await;
        let admission = claim(&store, &dispatch, &bindings[0].cell, &request, 13).await;
        let model = Model::new(/*latency*/ 20, /*lose_response*/ false);
        let calls = model.calls.clone();
        let reads = model.reads.clone();
        let owner = native_owner(&bindings);
        let mut runtime = AgentdCircuitCellOwnerV1::new(
            checked(CircuitCellRegistryV1::new(definition, bindings)),
            owner,
            model,
            Encoder,
        );
        let resolver = CurrentOwners {
            current,
            calls: Cell::new(0),
            stale_on,
        };
        let represented = || CircuitCellRepresentationUseV1 {
            backend: &backend,
            input: &projected,
            resolver: &resolver,
        };
        assert!(
            runtime
                .execute_representation(admission, request.clone(), represented(), time)
                .is_err()
        );
        assert_eq!(calls.load(Ordering::SeqCst), 0);
        assert_eq!(
            checked(runtime.state_owner().pending_inference(&request.scope)).is_some(),
            stale_on == 3
        );
        let recovery = checked(
            store
                .recover_circuit_computation("run-1", dispatch.activation_id, &fence(), 21)
                .await,
        );
        assert!(
            runtime
                .execute_representation(recovery, request, represented(), || CircuitCellTimeV1 {
                    circuit_millis: 22,
                    cell_micros: 22
                })
                .is_err()
        );
        assert_eq!(
            (calls.load(Ordering::SeqCst), resolver.calls.get()),
            (0, stale_on)
        );
        assert_eq!(reads.load(Ordering::SeqCst), usize::from(stale_on == 3));
        let run = checked(store.bounded_circuit_run("run-1").await).expect("original run");
        assert_eq!(run.budget().reserved(), 2_000);
        store.close().await;
    }
}

#[tokio::test]
async fn generic_circuit_entry_cannot_skip_representation_endpoint_checks() {
    let (_backend, projected, _current) = projected_input();
    let (definition, bindings) = configuration();
    let (_directory, store, dispatch, request) = projected_run(&definition, &projected).await;
    let admission = claim(&store, &dispatch, &bindings[0].cell, &request, 13).await;
    let model = Model::new(/*latency*/ 20, /*lose_response*/ false);
    let calls = model.calls.clone();
    let owner = native_owner(&bindings);
    let mut runtime = AgentdCircuitCellOwnerV1::new(
        checked(CircuitCellRegistryV1::new(definition, bindings)),
        owner,
        model,
        projected,
    );
    assert_eq!(
        runtime.execute(admission, request.clone(), time),
        Err(CircuitCellErrorV1::InputMismatch)
    );
    assert_eq!(calls.load(Ordering::SeqCst), 0);
    assert_eq!(
        checked(runtime.state_owner().pending_inference(&request.scope)),
        None
    );
    assert_eq!(
        checked(store.bounded_circuit_run("run-1").await)
            .expect("run")
            .budget()
            .reserved(),
        2_000
    );
    store.close().await;
}

#[path = "circuit_cell_representation_recovery_tests.rs"]
mod recovery;

#[path = "circuit_cell_representation_guard_tests.rs"]
mod guard;
