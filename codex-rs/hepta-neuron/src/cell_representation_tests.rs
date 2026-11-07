use crate::cell_test_support::RecordedControl;
use crate::cell_test_support::checked;
use crate::cell_test_support::d;
use crate::cell_test_support::definition;
use crate::cell_test_support::id;
use crate::cell_test_support::input;
use crate::cell_test_support::scope;
use crate::*;
use codex_hepta_types::Generation;
use pretty_assertions::assert_eq;

type E = CellRepresentationErrorV1;

fn context() -> CellRepresentationContextV1 {
    CellRepresentationContextV1 {
        producer_id: id("representation-producer"),
        producer_generation: checked(Generation::new(/*value*/ 2)),
        producer_binding_digest: d("producer-artifact"),
        scope: scope("run1"),
        source_frontier: d("frontier"),
        source_bundle_digest: d("source-bundle"),
        source_record_digest: d("source-record"),
        causal_receipt_digest: d("source-causal-receipt"),
    }
}

fn global(dtype: CellTensorDtypeV1, width: usize) -> CellRepresentationProfileV1 {
    CellRepresentationProfileV1 {
        profile_id: id("global-representation"),
        generation: checked(Generation::new(/*value*/ 1)),
        semantic_schema_digest: d("global-semantics"),
        kind: CellRepresentationKindV1::GlobalVector,
        tensors: vec![CellTensorLayoutV1 {
            name: id("features"),
            role: CellTensorRoleV1::Features,
            dtype,
            shape: vec![width as u64],
            axes: vec![id("feature")],
            modality: None,
            optional: false,
        }],
        max_payload_bytes: width as u64 * dtype.element_bytes(),
    }
}

fn f32_source(values: &[f32]) -> CellRepresentationV1 {
    checked(CellRepresentationV1::new(
        global(CellTensorDtypeV1::F32Le, values.len()),
        context(),
        vec![CellTensorValueV1::Present(
            values
                .iter()
                .flat_map(|value| value.to_le_bytes())
                .collect(),
        )],
    ))
}

fn endpoints(
    profile: &CellRepresentationProfileV1,
) -> (CellRepresentationProducerV1, CellRepresentationConsumerV1) {
    let context = context();
    let digest = checked(profile.digest());
    (
        CellRepresentationProducerV1 {
            producer_id: context.producer_id,
            generation: context.producer_generation,
            binding_digest: context.producer_binding_digest,
            offered_profiles: vec![digest],
            max_payload_bytes: profile.max_payload_bytes,
        },
        CellRepresentationConsumerV1 {
            consumer_id: id("consumer"),
            generation: checked(Generation::new(/*value*/ 1)),
            binding_digest: d("consumer-artifact"),
            accepted_profiles: vec![digest],
            qualified_projections: vec![],
            max_payload_bytes: profile.max_payload_bytes,
        },
    )
}

fn current(
    producer: &CellRepresentationProducerV1,
    consumer: &CellRepresentationConsumerV1,
) -> CellRepresentationUseV1 {
    CellRepresentationUseV1 {
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
        scope: scope("run1"),
        source_frontier: d("frontier"),
    }
}

fn native_backend(width: usize) -> RegisteredCellBackendV1 {
    let mut definition = definition();
    definition.runtime.input_feature_dimension = width;
    definition.max_input_bytes = 65_536;
    let capability = CellCapabilityContractV1 {
        type_id: id("typed-memory"),
        generation: checked(Generation::new(/*value*/ 7)),
        role: CellFunctionalRoleV1::MemoryAssociation,
        input_schema_digest: checked(cell_global_feature_schema_digest_v1(width)),
        output_schema_digest: cell_native_decision_schema_digest_v1(),
        state_schema_digest: definition.state_schema_digest,
        behavior_contract_digest: d("memory-behavior"),
    };
    let registration = CellBackendRegistrationV1 {
        backend_id: id("native-backend"),
        family: CellBackendFamilyV1::FrozenRepresentationPrivateHead,
        expert: CellExpertVersionV1 {
            version_id: id("expert-v1"),
            type_id: capability.type_id.clone(),
            capability_digest: checked(capability.digest()),
            shared_base_digest: d("shared-model"),
            parameter_bundle_digest: definition.bundle_digest,
        },
        capability,
        definition,
    };
    let digest = checked(registration.digest());
    let registry = checked(CellBackendRegistryV1::new(
        vec![registration.clone()],
        /*max_backends*/ 1,
    ));
    checked(registry.resolve(&registration.backend_id, digest)).clone()
}

fn owner(backend: &RegisteredCellBackendV1) -> CellPartitionOwnerV1 {
    let mut owner = checked(CellPartitionOwnerV1::new(
        /*max_partitions*/ 1, /*max_receipts_per_partition*/ 8,
    ));
    checked(owner.admit(
        scope("run1"),
        &backend.registration().definition,
        d("frontier"),
        /*writer_epoch*/ 1,
    ));
    owner
}

fn projection_parts(
    backend: &RegisteredCellBackendV1,
    source: &CellRepresentationV1,
    selection: &CellGlobalQ24SelectionV1,
) -> (
    CellRepresentationProducerV1,
    CellRepresentationConsumerV1,
    CellRepresentationProfileV1,
    CellProjectionComponentV1,
) {
    let width = backend
        .registration()
        .definition
        .runtime
        .input_feature_dimension;
    let mut target = global(CellTensorDtypeV1::SignedQ24Le, width);
    target.semantic_schema_digest = checked(cell_global_feature_schema_digest_v1(width));
    let component = CellProjectionComponentV1 {
        component_id: id("qualified-global-selection"),
        generation: checked(Generation::new(/*value*/ 1)),
        input_profile_digest: source.profile_digest(),
        output_profile_digest: checked(target.digest()),
        implementation_digest: CellGlobalQ24SelectionV1::implementation_digest(),
        parameters_digest: selection.parameters_digest(),
        quality_evidence_digest: d("independent-quality-evidence"),
    };
    let (producer, mut consumer) = endpoints(source.profile());
    consumer.consumer_id = backend.registration().backend_id.clone();
    consumer.binding_digest = backend.digest();
    consumer.accepted_profiles = vec![checked(target.digest())];
    consumer.qualified_projections = vec![checked(component.digest())];
    consumer.max_payload_bytes = target.max_payload_bytes;
    (producer, consumer, target, component)
}

fn negotiated(
    backend: &RegisteredCellBackendV1,
    source: &CellRepresentationV1,
    selection: &CellGlobalQ24SelectionV1,
) -> CellRepresentationNegotiationV1 {
    let (producer, consumer, target, component) = projection_parts(backend, source, selection);
    checked(CellRepresentationNegotiationV1::projected(
        producer,
        consumer,
        source.profile().clone(),
        target,
        component,
    ))
}

fn request(representation: &CellNativeRepresentationInputV1) -> CellStepInputV1 {
    let mut request = input("run1");
    request.observation = representation.observation_bytes().to_vec();
    request
}

fn ready(entry: CellStepEntryV1) -> PreparedCellStepV1 {
    match entry {
        CellStepEntryV1::Ready(prepared) => *prepared,
        CellStepEntryV1::Replayed(_) => panic!("expected a fresh proposal"),
    }
}

#[test]
fn direct_768_preserves_exact_layout_and_bytes_without_widening_native_v1() {
    let values: Vec<_> = (0..768).map(|index| (index as f32) / 256.0).collect();
    let source = f32_source(&values);
    let (producer, consumer) = endpoints(source.profile());
    let current = current(&producer, &consumer);
    let negotiation = checked(CellRepresentationNegotiationV1::direct(
        producer,
        consumer,
        source.profile().clone(),
    ));
    assert_eq!(negotiation.consume_direct(&source, &current), Ok(&source));
    assert_eq!(source.payload_bytes(), 768 * 4);
    assert_eq!(source.profile().tensors[0].shape, vec![768]);
    assert_eq!(
        cell_global_feature_schema_digest_v1(/*width*/ 768),
        Err(CellExecutionError::CapacityExceeded)
    );
}

#[test]
fn spare_payload_and_metadata_allocations_are_released_without_changing_identity() {
    let original = f32_source(&[1.0, 0.5]);
    let large_id = |value: &str| {
        let mut allocation = String::with_capacity(16_384);
        allocation.push_str(value);
        checked(StableId::new(allocation))
    };
    let mut profile = original.profile().clone();
    profile.profile_id = large_id(profile.profile_id.as_str());
    profile.tensors[0].name = large_id(profile.tensors[0].name.as_str());
    profile.tensors[0].axes[0] = large_id("feature");
    profile.tensors[0].axes.reserve_exact(128);
    profile.tensors[0].shape.reserve_exact(128);
    profile.tensors.reserve_exact(128);
    let mut context = context();
    context.producer_id = large_id(context.producer_id.as_str());
    context.scope.run_id = large_id(context.scope.run_id.as_str());
    let mut values = original.tensors().to_vec();
    let CellTensorValueV1::Present(bytes) = &mut values[0] else {
        panic!("present fixture");
    };
    bytes.reserve_exact(16_384);
    values.reserve_exact(128);
    let compact = checked(CellRepresentationV1::new(profile, context, values));
    assert_eq!(compact, original);
    assert_eq!(compact.values.capacity(), compact.values.len());
    assert_eq!(
        compact.profile().tensors.capacity(),
        compact.profile().tensors.len()
    );
    let layout = &compact.profile().tensors[0];
    assert_eq!(layout.axes.capacity(), layout.axes.len());
    assert_eq!(layout.shape.capacity(), layout.shape.len());
    let CellTensorValueV1::Present(bytes) = &compact.tensors()[0] else {
        panic!("present fixture");
    };
    assert_eq!(bytes.capacity(), bytes.len());
    let (mut producer, mut consumer) = endpoints(compact.profile());
    producer.offered_profiles.reserve_exact(128);
    consumer.accepted_profiles.reserve_exact(128);
    consumer.qualified_projections.reserve_exact(128);
    let current = current(&producer, &consumer);
    let negotiated = checked(CellRepresentationNegotiationV1::direct(
        producer,
        consumer,
        compact.profile().clone(),
    ));
    assert_eq!(
        negotiated.producer.offered_profiles.capacity(),
        negotiated.producer.offered_profiles.len()
    );
    assert_eq!(
        negotiated.consumer.accepted_profiles.capacity(),
        negotiated.consumer.accepted_profiles.len()
    );
    assert_eq!(
        negotiated.consumer.qualified_projections.capacity(),
        negotiated.consumer.qualified_projections.len()
    );
    assert_eq!(negotiated.consume_direct(&compact, &current), Ok(&original));
}

#[test]
fn exact_semantics_producer_scope_frontier_and_consumer_budget_are_required() {
    let source = f32_source(&[1.0, 0.5]);
    let (producer, consumer) = endpoints(source.profile());
    let negotiation = checked(CellRepresentationNegotiationV1::direct(
        producer.clone(),
        consumer.clone(),
        source.profile().clone(),
    ));
    for index in 0..3 {
        let mut binding = current(&producer, &consumer);
        let expected = match index {
            0 => {
                binding.scope = scope("other-run");
                E::ScopeMismatch
            }
            1 => {
                binding.source_frontier = d("new-frontier");
                E::StaleSource
            }
            2 => {
                binding.consumer.binding_digest = d("new-backend");
                E::StaleConsumer
            }
            _ => unreachable!("fixture index"),
        };
        assert_eq!(negotiation.consume_direct(&source, &binding), Err(expected));
    }
    for index in 0..3 {
        let mut changed = context();
        match index {
            0 => changed.producer_id = id("other-producer"),
            1 => changed.producer_generation = checked(Generation::new(/*value*/ 3)),
            2 => changed.producer_binding_digest = d("changed-producer-parameters"),
            _ => unreachable!("fixture index"),
        }
        let changed = checked(CellRepresentationV1::new(
            source.profile().clone(),
            changed,
            source.tensors().to_vec(),
        ));
        assert_eq!(
            negotiation.consume_direct(&changed, &current(&producer, &consumer)),
            Err(E::StaleProducer)
        );
    }
    let mut different = source.profile().clone();
    different.semantic_schema_digest = d("same-width-different-semantics");
    assert!(matches!(
        CellRepresentationNegotiationV1::direct(producer.clone(), consumer.clone(), different),
        Err(E::Incompatible)
    ));
    let mut smaller = consumer.clone();
    smaller.max_payload_bytes = source.payload_bytes() - 1;
    let current = current(&producer, &smaller);
    let limited = checked(CellRepresentationNegotiationV1::direct(
        producer,
        smaller,
        source.profile().clone(),
    ));
    assert_eq!(limited.consume_direct(&source, &current), Err(E::Capacity));
}

#[test]
fn negotiation_and_sealed_projection_recheck_both_endpoint_identities() {
    let source = f32_source(&[1.0, 0.5]);
    let (producer, consumer) = endpoints(source.profile());
    let direct_current = current(&producer, &consumer);
    let direct = checked(CellRepresentationNegotiationV1::direct(
        producer,
        consumer,
        source.profile().clone(),
    ));
    let backend = native_backend(/*width*/ 2);
    let owner = owner(&backend);
    let selection = checked(CellGlobalQ24SelectionV1::new(vec![0, 1]));
    let projected = negotiated(&backend, &source, &selection);
    let projected_current = current(&projected.producer, &projected.consumer);
    let native = checked(CellNativeRepresentationInputV1::project(
        &backend,
        &projected,
        &source,
        &projected_current,
        &selection,
    ));

    // Change only the new owner observation. The old bytes, negotiation,
    // source frontier and consumer state still have their original identity.
    for index in 0..8 {
        let mut direct_changed = direct_current.clone();
        let mut projected_changed = projected_current.clone();
        for changed in [&mut direct_changed, &mut projected_changed] {
            let endpoint = if index < 4 {
                &mut changed.producer
            } else {
                &mut changed.consumer
            };
            match index % 4 {
                0 => endpoint.endpoint_id = id("replacement-owner"),
                1 => endpoint.generation = checked(Generation::new(/*value*/ 3)),
                2 => endpoint.binding_digest = d("replacement-binding"),
                3 => endpoint.contract_digest = d("replacement-contract"),
                _ => unreachable!("fixture index"),
            }
        }
        let expected = if index < 4 {
            E::StaleProducer
        } else {
            E::StaleConsumer
        };
        assert_eq!(
            direct.consume_direct(&source, &direct_changed),
            Err(expected.clone())
        );
        assert_eq!(
            CellNativeRepresentationInputV1::project(
                &backend,
                &projected,
                &source,
                &projected_changed,
                &selection
            ),
            Err(expected)
        );
        let expected = if index < 4 {
            CellExecutionError::StaleSource
        } else {
            CellExecutionError::IncompatibleBundle
        };
        assert_eq!(
            native.validate_current_use(&backend, &projected_changed),
            Err(expected.clone())
        );
        match backend.enter_representation(
            &owner,
            &native,
            &projected_changed,
            request(&native),
            /*now_micros*/ 10,
        ) {
            Err(error) => assert_eq!(error, expected),
            Ok(_) => panic!("stale endpoints must not prepare another computation"),
        }
        assert_eq!(checked(owner.pending_inference(&scope("run1"))), None);
    }
    assert_eq!(direct.consume_direct(&source, &direct_current), Ok(&source));
    assert_eq!(
        native.validate_current_use(&backend, &projected_current),
        Ok(())
    );
    assert!(matches!(
        backend.enter_representation(
            &owner,
            &native,
            &projected_current,
            request(&native),
            /*now_micros*/ 10
        ),
        Ok(CellStepEntryV1::Ready(_))
    ));
}

#[test]
fn changed_owner_policies_invalidate_the_negotiated_contract() {
    let source = f32_source(&[1.0, 0.5]);
    let backend = native_backend(/*width*/ 2);
    let selection = checked(CellGlobalQ24SelectionV1::new(vec![0, 1]));
    let negotiation = negotiated(&backend, &source, &selection);
    let original = current(&negotiation.producer, &negotiation.consumer);
    let native = checked(CellNativeRepresentationInputV1::project(
        &backend,
        &negotiation,
        &source,
        &original,
        &selection,
    ));
    for index in 0..5 {
        let mut producer = negotiation.producer.clone();
        let mut consumer = negotiation.consumer.clone();
        match index {
            0 => producer.offered_profiles = vec![d("replacement-input-profile")],
            1 => producer.max_payload_bytes -= 1,
            2 => consumer.accepted_profiles = vec![d("replacement-output-profile")],
            3 => consumer.qualified_projections.clear(),
            4 => consumer.max_payload_bytes -= 1,
            _ => unreachable!("fixture index"),
        }
        let changed = current(&producer, &consumer);
        // Endpoint IDs, generations and implementation bindings stayed equal;
        // policy revocation must still fence the cached negotiated route.
        let expected = if index < 2 {
            E::StaleProducer
        } else {
            E::StaleConsumer
        };
        assert_eq!(
            CellNativeRepresentationInputV1::project(
                &backend,
                &negotiation,
                &source,
                &changed,
                &selection
            ),
            Err(expected)
        );
        let expected = if index < 2 {
            CellExecutionError::StaleSource
        } else {
            CellExecutionError::IncompatibleBundle
        };
        assert_eq!(
            native.validate_current_use(&backend, &changed),
            Err(expected)
        );
    }
}

#[test]
fn malformed_layouts_overflows_and_missing_required_tensors_are_refused() {
    let original = global(CellTensorDtypeV1::F32Le, /*width*/ 2);
    for index in 0..6 {
        let mut profile = original.clone();
        match index {
            0 => profile.tensors[0].shape = vec![0],
            1 => profile.tensors[0].shape = vec![u64::MAX],
            2 => profile.tensors[0].axes.clear(),
            3 => profile.tensors[0].optional = true,
            4 => profile.max_payload_bytes = 7,
            5 => profile.tensors.push(profile.tensors[0].clone()),
            _ => unreachable!("fixture index"),
        }
        assert!(profile.digest().is_err());
    }
    for values in [
        vec![],
        vec![CellTensorValueV1::Present(vec![0; 7])],
        vec![CellTensorValueV1::Missing {
            reason: id("unavailable"),
        }],
    ] {
        assert_eq!(
            CellRepresentationV1::new(original.clone(), context(), values),
            Err(E::InvalidPayload)
        );
    }
}

#[test]
fn token_ids_and_masks_remain_distinct_and_invalid_masks_do_not_enter() {
    let mut profile = global(CellTensorDtypeV1::I32Le, /*width*/ 3);
    profile.kind = CellRepresentationKindV1::TokenSequence {
        tokenizer_digest: d("tokenizer-v7"),
    };
    profile.tensors[0].role = CellTensorRoleV1::Tokens;
    profile.tensors[0].name = id("tokens");
    profile.tensors[0].axes = vec![id("token")];
    let mut mask = profile.tensors[0].clone();
    mask.name = id("mask");
    mask.role = CellTensorRoleV1::Mask;
    mask.dtype = CellTensorDtypeV1::U8;
    profile.tensors.push(mask);
    profile.max_payload_bytes = 15;
    let token_bytes: Vec<_> = [42_i32, 500, 0]
        .iter()
        .flat_map(|value| value.to_le_bytes())
        .collect();
    let values = vec![
        CellTensorValueV1::Present(token_bytes),
        CellTensorValueV1::Present(vec![1, 1, 0]),
    ];
    let source = checked(CellRepresentationV1::new(
        profile.clone(),
        context(),
        values.clone(),
    ));
    let (producer, consumer) = endpoints(&profile);
    let current = current(&producer, &consumer);
    let negotiation = checked(CellRepresentationNegotiationV1::direct(
        producer,
        consumer,
        profile.clone(),
    ));
    assert_eq!(
        checked(negotiation.consume_direct(&source, &current)).tensors(),
        values
    );
    let mut malformed = values;
    malformed[1] = CellTensorValueV1::Present(vec![1, 2, 0]);
    assert_eq!(
        CellRepresentationV1::new(profile.clone(), context(), malformed),
        Err(E::InvalidPayload)
    );
    profile.tensors[1].shape = vec![2];
    assert_eq!(profile.digest(), Err(E::InvalidProfile));
}

#[test]
fn modality_absence_is_explicit_and_all_views_of_one_modality_agree() {
    let mut profile = global(CellTensorDtypeV1::U8, /*width*/ 2);
    profile.kind = CellRepresentationKindV1::MultimodalSpatiotemporal {
        coordinate_system_digest: d("camera-coordinate-system"),
        timebase_digest: d("microseconds-timebase"),
    };
    profile.tensors[0].name = id("image");
    profile.tensors[0].axes = vec![id("time")];
    profile.tensors[0].modality = Some(id("image"));
    let mut audio = profile.tensors[0].clone();
    audio.name = id("audio");
    audio.modality = Some(id("audio"));
    audio.optional = true;
    let mut audio_mask = audio.clone();
    audio_mask.name = id("audio-mask");
    audio_mask.role = CellTensorRoleV1::Mask;
    profile.tensors.extend([audio, audio_mask]);
    profile.max_payload_bytes = 6;
    let absent = CellTensorValueV1::Missing {
        reason: id("not-recorded-v1"),
    };
    let values = vec![
        CellTensorValueV1::Present(vec![3, 4]),
        absent.clone(),
        absent,
    ];
    let source = checked(CellRepresentationV1::new(
        profile.clone(),
        context(),
        values.clone(),
    ));
    let mut partial = values;
    partial[2] = CellTensorValueV1::Present(vec![0, 0]);
    assert_eq!(
        CellRepresentationV1::new(profile.clone(), context(), partial),
        Err(E::InvalidPayload)
    );
    let zeros = checked(CellRepresentationV1::new(
        profile.clone(),
        context(),
        vec![
            CellTensorValueV1::Present(vec![3, 4]),
            CellTensorValueV1::Present(vec![0, 0]),
            CellTensorValueV1::Present(vec![0, 0]),
        ],
    ));
    assert_ne!(source.digest(), zeros.digest());
    let (producer, consumer) = endpoints(&profile);
    let current = current(&producer, &consumer);
    let negotiation = checked(CellRepresentationNegotiationV1::direct(
        producer, consumer, profile,
    ));
    assert_eq!(negotiation.consume_direct(&source, &current), Ok(&source));
}

#[test]
fn trainable_profile_requires_every_declared_component_class_and_exact_bytes() {
    let mut profile = global(CellTensorDtypeV1::U8, /*width*/ 1);
    profile.kind = CellRepresentationKindV1::TrainableState {
        training_protocol_digest: d("training-protocol"),
    };
    let layout = profile.tensors[0].clone();
    profile.tensors = [
        ("weights", CellTensorRoleV1::Weights),
        ("optimizer", CellTensorRoleV1::Optimizer),
        ("rng", CellTensorRoleV1::Rng),
        ("sampler", CellTensorRoleV1::Sampler),
        ("cursor", CellTensorRoleV1::TrainingCursor),
    ]
    .into_iter()
    .map(|(name, role)| CellTensorLayoutV1 {
        name: id(name),
        role,
        ..layout.clone()
    })
    .collect();
    profile.max_payload_bytes = 5;
    let values: Vec<_> = (0..5)
        .map(|value| CellTensorValueV1::Present(vec![value]))
        .collect();
    let original = checked(CellRepresentationV1::new(
        profile.clone(),
        context(),
        values.clone(),
    ));
    for index in 0..5 {
        let mut incomplete = profile.clone();
        incomplete.tensors.remove(index);
        assert_eq!(incomplete.digest(), Err(E::InvalidProfile));
        let mut changed = values.clone();
        changed[index] = CellTensorValueV1::Present(vec![99]);
        assert_ne!(
            checked(CellRepresentationV1::new(
                profile.clone(),
                context(),
                changed
            ))
            .digest(),
            original.digest()
        );
    }
    let (producer, consumer) = endpoints(&profile);
    let current = current(&producer, &consumer);
    let negotiation = checked(CellRepresentationNegotiationV1::direct(
        producer, consumer, profile,
    ));
    assert_eq!(
        negotiation.consume_direct(&original, &current),
        Ok(&original)
    );
}

#[test]
fn generated_output_uses_its_codec_and_is_not_relabelled_as_a_native_decision() {
    let mut profile = global(CellTensorDtypeV1::U8, /*width*/ 4);
    profile.kind = CellRepresentationKindV1::GenerationOutput {
        codec_digest: d("utf8-output-codec"),
    };
    profile.tensors[0].role = CellTensorRoleV1::Output;
    profile.tensors[0].axes = vec![id("byte")];
    let source = checked(CellRepresentationV1::new(
        profile.clone(),
        context(),
        vec![CellTensorValueV1::Present(b"text".to_vec())],
    ));
    let (producer, consumer) = endpoints(&profile);
    let current = current(&producer, &consumer);
    let negotiation = checked(CellRepresentationNegotiationV1::direct(
        producer,
        consumer,
        profile.clone(),
    ));
    assert_eq!(negotiation.consume_direct(&source, &current), Ok(&source));
    let original = checked(profile.digest());
    profile.kind = CellRepresentationKindV1::GenerationOutput {
        codec_digest: d("different-output-codec"),
    };
    assert_ne!(checked(profile.digest()), original);
}

#[test]
fn projected_negotiation_requires_independently_supplied_component_pins() {
    let source = f32_source(&[1.0, 0.5, 0.0]);
    let backend = native_backend(/*width*/ 2);
    let selection = checked(CellGlobalQ24SelectionV1::new(vec![0, 1]));
    let (producer, consumer, target, component) = projection_parts(&backend, &source, &selection);
    for index in 0..4 {
        let mut component = component.clone();
        let mut consumer = consumer.clone();
        match index {
            0 => consumer.qualified_projections.clear(),
            1 => component.parameters_digest = d("unreviewed-parameters"),
            2 => component.quality_evidence_digest = d("substituted-quality-evidence"),
            3 => component.generation = checked(Generation::new(/*value*/ 2)),
            _ => unreachable!("fixture index"),
        }
        assert!(matches!(
            CellRepresentationNegotiationV1::projected(
                producer.clone(),
                consumer,
                source.profile().clone(),
                target.clone(),
                component,
            ),
            Err(E::UnqualifiedProjection)
        ));
    }
    let negotiation = negotiated(&backend, &source, &selection);
    assert_eq!(
        negotiation.consume_direct(&source, &current(&producer, &consumer)),
        Err(E::ProjectionRequired)
    );
    let wrong_selection = checked(CellGlobalQ24SelectionV1::new(vec![0, 2]));
    assert_eq!(
        CellNativeRepresentationInputV1::project(
            &backend,
            &negotiation,
            &source,
            &current(&producer, &consumer),
            &wrong_selection
        ),
        Err(E::Incompatible)
    );
}

#[test]
fn full_768_source_and_projection_identity_reach_the_existing_owner_pipeline() {
    let mut values = vec![0.0; 768];
    values[0] = 1.0;
    values[767] = 0.5;
    let source = f32_source(&values);
    let backend = native_backend(/*width*/ 2);
    let mut owner = owner(&backend);
    let selection = checked(CellGlobalQ24SelectionV1::new(vec![0, 767]));
    let negotiation = negotiated(&backend, &source, &selection);
    let current = current(&negotiation.producer, &negotiation.consumer);
    let representation = checked(CellNativeRepresentationInputV1::project(
        &backend,
        &negotiation,
        &source,
        &current,
        &selection,
    ));
    let prepared = ready(checked(backend.enter_representation(
        &owner,
        &representation,
        &current,
        request(&representation),
        /*now_micros*/ 10,
    )));
    assert_eq!(
        prepared.model_request.feature_vector_q24,
        vec![1 << 24, 1 << 23]
    );
    let mut control = RecordedControl::new();
    let inferred = checked(infer_cell(
        prepared,
        &mut owner,
        &mut control,
        /*now_micros*/ 11,
    ));
    let receipt = checked(commit_cell_step(
        &mut owner,
        checked(decide_cell(inferred, /*now_micros*/ 12)),
        /*now_micros*/ 13,
    ));
    assert_eq!(
        receipt.cost.consumed_input_bytes,
        representation.observation_bytes().len()
    );
    assert_eq!(receipt.cost.truncated_input_bytes, 0);
    assert_eq!(
        representation.projection_receipt().source_payload_bytes,
        768 * 4
    );
    assert_eq!(
        representation.projection_receipt().authority(),
        codex_hepta_types::AuthorityPosture::DENY_ALL
    );
    match checked(backend.enter_representation(
        &owner,
        &representation,
        &current,
        request(&representation),
        /*now_micros*/ 101,
    )) {
        CellStepEntryV1::Replayed(replayed) => assert_eq!(*replayed, receipt),
        CellStepEntryV1::Ready(_) => panic!("committed operation must not dispatch again"),
    }
    // An unselected coordinate still belongs to the full source identity.
    values[500] = 0.25;
    let changed = f32_source(&values);
    let changed = checked(CellNativeRepresentationInputV1::project(
        &backend,
        &negotiation,
        &changed,
        &current,
        &selection,
    ));
    assert!(matches!(
        backend.enter_representation(
            &owner,
            &changed,
            &current,
            request(&changed),
            /*now_micros*/ 14
        ),
        Err(CellExecutionError::OperationConflict)
    ));
    assert_eq!((control.executions, control.reads), (1, 0));
}

#[test]
fn changed_quality_evidence_cannot_reinterpret_an_existing_operation() {
    let source = f32_source(&[1.0, 0.5]);
    let backend = native_backend(/*width*/ 2);
    let mut owner = owner(&backend);
    let selection = checked(CellGlobalQ24SelectionV1::new(vec![0, 1]));
    let old_negotiation = negotiated(&backend, &source, &selection);
    let old_current = current(&old_negotiation.producer, &old_negotiation.consumer);
    let old = checked(CellNativeRepresentationInputV1::project(
        &backend,
        &old_negotiation,
        &source,
        &old_current,
        &selection,
    ));
    let prepared = ready(checked(backend.enter_representation(
        &owner,
        &old,
        &old_current,
        request(&old),
        /*now_micros*/ 10,
    )));
    let mut control = RecordedControl::new();
    control.failure = Some(NeuronModelError::Indeterminate);
    assert!(matches!(
        infer_cell(prepared, &mut owner, &mut control, /*now_micros*/ 11),
        Err(CellExecutionError::Backend(NeuronModelError::Indeterminate))
    ));
    let (producer, mut consumer, target, mut component) =
        projection_parts(&backend, &source, &selection);
    component.quality_evidence_digest = d("new-quality-evidence");
    consumer.qualified_projections = vec![checked(component.digest())];
    let changed = checked(CellRepresentationNegotiationV1::projected(
        producer,
        consumer,
        source.profile().clone(),
        target,
        component,
    ));
    let changed_current = current(&changed.producer, &changed.consumer);
    let changed = checked(CellNativeRepresentationInputV1::project(
        &backend,
        &changed,
        &source,
        &changed_current,
        &selection,
    ));
    assert_eq!(
        old.projection_receipt().output_digest,
        changed.projection_receipt().output_digest
    );
    assert!(matches!(
        backend.recover_representation(
            &owner,
            &changed,
            request(&changed),
            &mut control,
            /*now_micros*/ 12
        ),
        Err(CellExecutionError::OperationConflict)
    ));
    let observed = control.receipt.take();
    let pending = checked(owner.pending_inference(&scope("run1")));
    // The current quality policy prevents fresh use of the sealed old route,
    // but cannot erase the original UNKNOWN admission or block its readback.
    assert!(matches!(
        backend.enter_representation(
            &owner,
            &old,
            &changed_current,
            request(&old),
            /*now_micros*/ 12
        ),
        Err(CellExecutionError::IncompatibleBundle)
    ));
    assert_eq!(checked(owner.pending_inference(&scope("run1"))), pending);
    assert!(matches!(
        backend.recover_representation(
            &owner,
            &old,
            request(&old),
            &mut control,
            /*now_micros*/ 12
        ),
        Err(CellExecutionError::InferencePending)
    ));
    assert_eq!(checked(owner.pending_inference(&scope("run1"))), pending);
    assert!(matches!(
        backend.enter_representation(
            &owner,
            &old,
            &old_current,
            request(&old),
            /*now_micros*/ 12
        ),
        Err(CellExecutionError::InferencePending)
    ));
    control.receipt = observed;
    let inferred = checked(backend.recover_representation(
        &owner,
        &old,
        request(&old),
        &mut control,
        /*now_micros*/ 101,
    ));
    let receipt = checked(commit_cell_step(
        &mut owner,
        checked(decide_cell(inferred, /*now_micros*/ 102)),
        /*now_micros*/ 103,
    ));
    assert!(receipt.deadline_exceeded);
    assert_eq!(receipt.selected_candidate, id("abstain"));
    assert_eq!((control.executions, control.reads), (1, 2));
}

#[test]
fn conversion_uses_ties_even_and_rejects_bad_unselected_values() {
    let backend = native_backend(/*width*/ 4);
    let source = f32_source(&[
        1.0 / 33_554_432.0,
        3.0 / 33_554_432.0,
        -3.0 / 33_554_432.0,
        5.0 / 33_554_432.0,
    ]);
    let selection = checked(CellGlobalQ24SelectionV1::new(vec![0, 1, 2, 3]));
    let negotiation = negotiated(&backend, &source, &selection);
    let current_pins = current(&negotiation.producer, &negotiation.consumer);
    let native = checked(CellNativeRepresentationInputV1::project(
        &backend,
        &negotiation,
        &source,
        &current_pins,
        &selection,
    ));
    let prepared = ready(checked(backend.enter_representation(
        &owner(&backend),
        &native,
        &current_pins,
        request(&native),
        /*now_micros*/ 10,
    )));
    assert_eq!(prepared.model_request.feature_vector_q24, vec![0, 2, -2, 2]);
    let backend = native_backend(/*width*/ 2);
    let selection = checked(CellGlobalQ24SelectionV1::new(vec![0, 1]));
    for bad in [f32::NAN, f32::INFINITY, f32::NEG_INFINITY, 8.5, -8.5] {
        let source = f32_source(&[1.0, 0.5, bad]);
        let negotiation = negotiated(&backend, &source, &selection);
        let current = current(&negotiation.producer, &negotiation.consumer);
        assert_eq!(
            CellNativeRepresentationInputV1::project(
                &backend,
                &negotiation,
                &source,
                &current,
                &selection
            ),
            Err(E::InvalidPayload)
        );
    }
}

#[test]
fn q24_selection_preserves_extreme_values_and_checks_indices() {
    let profile = global(CellTensorDtypeV1::SignedQ24Le, /*width*/ 3);
    let values: Vec<_> = [-(8_i64 << 24), 0, 8_i64 << 24]
        .iter()
        .flat_map(|value| value.to_le_bytes())
        .collect();
    let source = checked(CellRepresentationV1::new(
        profile,
        context(),
        vec![CellTensorValueV1::Present(values)],
    ));
    let backend = native_backend(/*width*/ 2);
    let selection = checked(CellGlobalQ24SelectionV1::new(vec![2, 0]));
    let negotiation = negotiated(&backend, &source, &selection);
    let current_pins = current(&negotiation.producer, &negotiation.consumer);
    let native = checked(CellNativeRepresentationInputV1::project(
        &backend,
        &negotiation,
        &source,
        &current_pins,
        &selection,
    ));
    let prepared = ready(checked(backend.enter_representation(
        &owner(&backend),
        &native,
        &current_pins,
        request(&native),
        /*now_micros*/ 10,
    )));
    assert_eq!(
        prepared.model_request.feature_vector_q24,
        vec![8 << 24, -(8 << 24)]
    );
    let outside = checked(CellGlobalQ24SelectionV1::new(vec![0, 3]));
    let negotiation = negotiated(&backend, &source, &outside);
    let current = current(&negotiation.producer, &negotiation.consumer);
    assert_eq!(
        CellNativeRepresentationInputV1::project(
            &backend,
            &negotiation,
            &source,
            &current,
            &outside
        ),
        Err(E::InvalidPayload)
    );
    assert_eq!(
        CellGlobalQ24SelectionV1::new(vec![0, 0]),
        Err(E::InvalidProfile)
    );
    assert_eq!(
        CellGlobalQ24SelectionV1::new((0..513).collect()),
        Err(E::Capacity)
    );
}

#[test]
fn native_entry_rejects_changed_observation_scope_source_and_backend_before_dispatch() {
    let source = f32_source(&[1.0, 0.5]);
    let backend = native_backend(/*width*/ 2);
    let owner = owner(&backend);
    let selection = checked(CellGlobalQ24SelectionV1::new(vec![0, 1]));
    let negotiation = negotiated(&backend, &source, &selection);
    let current = current(&negotiation.producer, &negotiation.consumer);
    let native = checked(CellNativeRepresentationInputV1::project(
        &backend,
        &negotiation,
        &source,
        &current,
        &selection,
    ));
    for index in 0..3 {
        let mut changed = request(&native);
        let expected = match index {
            0 => {
                changed.observation[0] ^= 1;
                CellExecutionError::EncodingMismatch
            }
            1 => {
                changed.scope = scope("other-run");
                CellExecutionError::ScopeMismatch
            }
            2 => {
                changed.source_frontier = d("stale-frontier");
                CellExecutionError::StaleSource
            }
            _ => unreachable!("fixture index"),
        };
        match backend
            .enter_representation(&owner, &native, &current, changed, /*now_micros*/ 10)
        {
            Err(error) => assert_eq!(error, expected),
            Ok(_) => panic!("changed binding must be refused"),
        }
    }
    let mut changed = backend.registration().clone();
    changed.expert.version_id = id("new-expert");
    let digest = checked(changed.digest());
    let registry = checked(CellBackendRegistryV1::new(
        vec![changed.clone()],
        /*max_backends*/ 1,
    ));
    let changed = checked(registry.resolve(&changed.backend_id, digest));
    assert!(matches!(
        changed.enter_representation(
            &owner,
            &native,
            &current,
            request(&native),
            /*now_micros*/ 10
        ),
        Err(CellExecutionError::IncompatibleBundle)
    ));
    assert_eq!(checked(owner.pending_inference(&scope("run1"))), None);
}

#[test]
fn projection_obeys_producer_output_and_native_observation_budgets() {
    let source = f32_source(&[1.0; 768]);
    let backend = native_backend(/*width*/ 2);
    let selection = checked(CellGlobalQ24SelectionV1::new(vec![0, 767]));
    for index in 0..2 {
        let (mut producer, mut consumer, target, component) =
            projection_parts(&backend, &source, &selection);
        match index {
            0 => producer.max_payload_bytes = source.payload_bytes() - 1,
            1 => consumer.max_payload_bytes = 15,
            _ => unreachable!("fixture index"),
        }
        let negotiation = checked(CellRepresentationNegotiationV1::projected(
            producer,
            consumer,
            source.profile().clone(),
            target,
            component,
        ));
        let current = current(&negotiation.producer, &negotiation.consumer);
        assert_eq!(
            CellNativeRepresentationInputV1::project(
                &backend,
                &negotiation,
                &source,
                &current,
                &selection
            ),
            Err(E::Capacity)
        );
    }
    let mut registration = backend.registration().clone();
    registration.definition.max_input_bytes = source.payload_bytes() as usize;
    let digest = checked(registration.digest());
    let registry = checked(CellBackendRegistryV1::new(
        vec![registration.clone()],
        /*max_backends*/ 1,
    ));
    let backend = checked(registry.resolve(&registration.backend_id, digest));
    let negotiation = negotiated(backend, &source, &selection);
    let current = current(&negotiation.producer, &negotiation.consumer);
    assert_eq!(
        CellNativeRepresentationInputV1::project(
            backend,
            &negotiation,
            &source,
            &current,
            &selection
        ),
        Err(E::Capacity)
    );
}

#[path = "cell_representation_recovery_tests.rs"]
mod recovery;
