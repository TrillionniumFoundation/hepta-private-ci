use super::*;

fn d(label: &str) -> Digest32 {
    Digest32::of_bytes(label.as_bytes())
}

fn request() -> LocalTextRequestV1 {
    LocalTextRequestV1 {
        request_id: StableId::new("request.1").unwrap(),
        operation_id: StableId::new("operation.1").unwrap(),
        owner_generation: Generation::new(9).unwrap(),
        release: LocalTextReleaseBindingV1 {
            release_root: d("release"),
            dependency_closure_digest: d("closure"),
            tokenizer_digest: d("tokenizer"),
            preprocessor_digest: d("preprocessor"),
            chat_template_digest: d("template"),
        },
        input: LocalTextInputV1::from_utf8("é\nraw\0".as_bytes()).unwrap(),
        generation: LocalTextGenerationPolicyV1 {
            decoding_profile_digest: d("decoding"),
            maximum_input_tokens: 4096,
            maximum_output_tokens: 2048,
        },
    }
}

fn observation(request: &LocalTextRequestV1) -> LocalTextObservationV1 {
    LocalTextObservationV1 {
        request_digest: local_text_request_digest_v1(request).unwrap(),
        readback: LoadedRootReadbackV1 {
            load_operation_id: StableId::new("load.1").unwrap(),
            attempt_id: StableId::new("attempt.1").unwrap(),
            owner_generation: request.owner_generation,
            release: request.release.clone(),
            parent_release_root: Some(d("parent")),
            tensor_inventory_digest: d("inventory"),
            adapter_digest: Some(d("adapter")),
            runtime_digest: d("runtime"),
            device_digest: d("device"),
        },
        status: LocalTextObservedStatusV1::Completed,
        output_utf8: "答\n".as_bytes().to_vec(),
        observed_input_tokens: Some(12),
        observed_output_tokens: Some(3),
    }
}

#[test]
fn request_and_report_match_independent_binary_digest_vectors() {
    // Independently encoded with SHA-256, big-endian lengths/counters and
    // explicit optional-value tags; neither vector invokes these Rust builders.
    let request = request();
    assert_eq!(
        local_text_request_digest_v1(&request).unwrap().to_string(),
        "92eee419f78d60c8c2c95e7124485c8ee18c678dc81544bfddab2b01939e0b9c"
    );
    assert_eq!(
        local_text_observation_digest_v1(&request, &observation(&request))
            .unwrap()
            .to_string(),
        "b3ae505f2b8f42d82ff2803064b1c1f2f45cd03c0275be96f0592079ff1ed277"
    );
}

#[test]
fn input_preserves_exact_utf8_and_rejects_before_oversize_copy() {
    let raw = "é\r\nraw\0 ".as_bytes();
    assert_eq!(
        LocalTextInputV1::from_utf8(raw)
            .unwrap()
            .as_str()
            .as_bytes(),
        raw
    );
    for bytes in [vec![], vec![b'x'; MAX_INPUT_BYTES + 1]] {
        assert_eq!(
            LocalTextInputV1::from_utf8(&bytes),
            Err(LocalTextContractError::InputLimit)
        );
    }
    for bytes in [vec![0xff], vec![0xc3], vec![0xc0, 0x80]] {
        assert_eq!(
            LocalTextInputV1::from_utf8(&bytes),
            Err(LocalTextContractError::InvalidUtf8)
        );
    }
    let at_limit = "é".repeat(MAX_INPUT_BYTES / 2);
    assert_eq!(
        LocalTextInputV1::from_utf8(at_limit.as_bytes())
            .unwrap()
            .as_str(),
        at_limit
    );
    let mut nfc = request();
    nfc.input = LocalTextInputV1::from_utf8("é".as_bytes()).unwrap();
    let mut nfd = nfc.clone();
    nfd.input = LocalTextInputV1::from_utf8("e\u{301}".as_bytes()).unwrap();
    assert_ne!(
        local_text_request_digest_v1(&nfc),
        local_text_request_digest_v1(&nfd)
    );
}

#[test]
fn every_request_context_and_real_input_affect_its_identity() {
    let original = request();
    let expected = local_text_request_digest_v1(&original).unwrap();
    let changes: [fn(&mut LocalTextRequestV1); 12] = [
        |r| r.request_id = StableId::new("request.2").unwrap(),
        |r| r.operation_id = StableId::new("operation.2").unwrap(),
        |r| r.owner_generation = Generation::new(10).unwrap(),
        |r| r.release.release_root = d("changed"),
        |r| r.release.dependency_closure_digest = d("changed"),
        |r| r.release.tokenizer_digest = d("changed"),
        |r| r.release.preprocessor_digest = d("changed"),
        |r| r.release.chat_template_digest = d("changed"),
        |r| r.input = LocalTextInputV1::from_utf8(b"different real bytes").unwrap(),
        |r| r.generation.decoding_profile_digest = d("changed"),
        |r| r.generation.maximum_input_tokens += 1,
        |r| r.generation.maximum_output_tokens += 1,
    ];
    for change in changes {
        let mut changed = original.clone();
        change(&mut changed);
        assert_ne!(local_text_request_digest_v1(&changed).unwrap(), expected);
        assert_eq!(
            validate_local_text_observation_shape_v1(&changed, &observation(&original)),
            Err(LocalTextContractError::BindingMismatch)
        );
    }
    // Separately framed strings cannot move bytes between identities.
    let mut split = original;
    split.request_id = StableId::new("request.").unwrap();
    split.operation_id = StableId::new("1operation.1").unwrap();
    assert_ne!(local_text_request_digest_v1(&split).unwrap(), expected);
}

#[test]
fn zero_release_fields_and_policy_limits_refuse_without_pilot_specific_limits() {
    let changes: [fn(&mut LocalTextRequestV1); 6] = [
        |r| r.release.release_root = Digest32::ZERO,
        |r| r.release.dependency_closure_digest = Digest32::ZERO,
        |r| r.release.tokenizer_digest = Digest32::ZERO,
        |r| r.release.preprocessor_digest = Digest32::ZERO,
        |r| r.release.chat_template_digest = Digest32::ZERO,
        |r| r.generation.decoding_profile_digest = Digest32::ZERO,
    ];
    for change in changes {
        let mut changed = request();
        change(&mut changed);
        assert_eq!(
            local_text_request_digest_v1(&changed),
            Err(LocalTextContractError::EmptyDigest)
        );
    }
    for limit in [0, MAX_TOKENS + 1] {
        for input in [false, true] {
            let mut changed = request();
            if input {
                changed.generation.maximum_input_tokens = limit;
            } else {
                changed.generation.maximum_output_tokens = limit;
            }
            assert_eq!(
                local_text_request_digest_v1(&changed),
                Err(LocalTextContractError::TokenLimit)
            );
        }
    }
    let mut at_limit = request();
    at_limit.generation.maximum_input_tokens = MAX_TOKENS;
    at_limit.generation.maximum_output_tokens = MAX_TOKENS;
    assert!(local_text_request_digest_v1(&at_limit).is_ok());
}

#[test]
fn readback_shape_drift_is_rejected_but_consistent_data_is_not_verified_use() {
    let request = request();
    let original = observation(&request);
    let changes: [fn(&mut LocalTextObservationV1); 8] = [
        |o| o.request_digest = d("wrong request"),
        |o| o.readback.owner_generation = Generation::new(10).unwrap(),
        |o| o.readback.release.release_root = d("wrong release"),
        |o| o.readback.tensor_inventory_digest = Digest32::ZERO,
        |o| o.readback.runtime_digest = Digest32::ZERO,
        |o| o.readback.device_digest = Digest32::ZERO,
        |o| o.readback.parent_release_root = Some(Digest32::ZERO),
        |o| o.readback.adapter_digest = Some(Digest32::ZERO),
    ];
    for change in changes {
        let mut changed = original.clone();
        change(&mut changed);
        assert!(validate_local_text_observation_shape_v1(&request, &changed).is_err());
        assert!(local_text_observation_digest_v1(&request, &changed).is_err());
    }
    // All fields are freely constructible reports, without a load or model.
    assert_eq!(
        validate_local_text_observation_shape_v1(&request, &original),
        Ok(())
    );
    let mut report = original.clone();
    report.readback.parent_release_root = None;
    report.readback.adapter_digest = None;
    assert_eq!(
        validate_local_text_observation_shape_v1(&request, &report),
        Ok(())
    );
    assert_ne!(
        local_text_observation_digest_v1(&request, &original),
        local_text_observation_digest_v1(&request, &report)
    );
}

#[test]
fn report_identity_binds_readback_attempt_output_usage_and_status() {
    let request = request();
    let original = observation(&request);
    let expected = local_text_observation_digest_v1(&request, &original).unwrap();
    let changes: [fn(&mut LocalTextObservationV1); 11] = [
        |o| o.readback.load_operation_id = StableId::new("load.2").unwrap(),
        |o| o.readback.attempt_id = StableId::new("attempt.2").unwrap(),
        |o| o.readback.tensor_inventory_digest = d("changed"),
        |o| o.readback.parent_release_root = Some(d("changed")),
        |o| o.readback.adapter_digest = Some(d("changed")),
        |o| o.readback.runtime_digest = d("changed"),
        |o| o.readback.device_digest = d("changed"),
        |o| o.output_utf8.push(b' '),
        |o| o.observed_input_tokens = Some(13),
        |o| o.observed_output_tokens = Some(4),
        |o| o.status = LocalTextObservedStatusV1::Failed,
    ];
    for change in changes {
        let mut changed = original.clone();
        change(&mut changed);
        assert_ne!(
            local_text_observation_digest_v1(&request, &changed).unwrap(),
            expected
        );
    }
    assert_ne!(expected, local_text_request_digest_v1(&request).unwrap());
}

#[test]
fn partial_and_failed_reports_keep_unknown_usage_without_inventing_terminal_release() {
    let request = request();
    let mut report = observation(&request);
    for status in [
        LocalTextObservedStatusV1::Indeterminate,
        LocalTextObservedStatusV1::Failed,
    ] {
        report.status = status;
        report.observed_input_tokens = None;
        report.observed_output_tokens = None;
        let unknown = local_text_observation_digest_v1(&request, &report).unwrap();
        report.observed_input_tokens = Some(0);
        report.observed_output_tokens = Some(0);
        assert_eq!(
            validate_local_text_observation_shape_v1(&request, &report),
            Ok(())
        );
        assert_ne!(
            local_text_observation_digest_v1(&request, &report).unwrap(),
            unknown
        );
    }
    report.status = LocalTextObservedStatusV1::Completed;
    report.observed_input_tokens = None;
    assert_eq!(
        validate_local_text_observation_shape_v1(&request, &report),
        Err(LocalTextContractError::MissingReportedUsage)
    );
    report.observed_input_tokens = Some(1);
    report.observed_output_tokens = None;
    assert_eq!(
        validate_local_text_observation_shape_v1(&request, &report),
        Err(LocalTextContractError::MissingReportedUsage)
    );
    report.observed_input_tokens = Some(0);
    report.observed_output_tokens = Some(0);
    assert_eq!(
        validate_local_text_observation_shape_v1(&request, &report),
        Err(LocalTextContractError::TokenLimit)
    );
    report.observed_input_tokens = Some(1);
    report.output_utf8.clear();
    assert_eq!(
        validate_local_text_observation_shape_v1(&request, &report),
        Ok(())
    );
}

#[test]
fn output_bytes_utf8_and_reported_token_bounds_are_independent() {
    let request = request();
    let mut report = observation(&request);
    report.output_utf8 = vec![b'x'; MAX_OUTPUT_BYTES];
    assert!(local_text_observation_digest_v1(&request, &report).is_ok());
    report.output_utf8.push(b'x');
    assert_eq!(
        validate_local_text_observation_shape_v1(&request, &report),
        Err(LocalTextContractError::OutputLimit)
    );
    report.output_utf8 = vec![0xff];
    assert_eq!(
        validate_local_text_observation_shape_v1(&request, &report),
        Err(LocalTextContractError::InvalidUtf8)
    );
    report.output_utf8.clear();
    for input in [false, true] {
        let mut changed = report.clone();
        if input {
            changed.observed_input_tokens = Some(request.generation.maximum_input_tokens + 1);
        } else {
            changed.observed_output_tokens = Some(request.generation.maximum_output_tokens + 1);
        }
        assert_eq!(
            validate_local_text_observation_shape_v1(&request, &changed),
            Err(LocalTextContractError::TokenLimit)
        );
    }
}
