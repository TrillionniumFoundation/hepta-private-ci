use super::*;
use serde_json::json;

fn sensor() -> UntrustedLearningOperatorProtocolV1 {
    UntrustedLearningOperatorProtocolV1::SensorCore(Box::new(
        UntrustedOperatorSensorCoreManifestV1 {
            sensor_core_id: "sensor-core".into(),
            state_axis_digest: "a".repeat(64),
            points_digest: "b".repeat(64),
            count: 2,
            fill_distance_q32: 10,
            separation_radius_q32: 5,
            mesh_ratio_q32: 2,
            hull_digest: "c".repeat(64),
            construction_algorithm: "farthest_point".into(),
            seed_digest: "d".repeat(64),
            predecessor_id: None,
            expires_unix_ms: 100,
        },
    ))
}

fn regularity() -> UntrustedLearningOperatorProtocolV1 {
    UntrustedLearningOperatorProtocolV1::Regularity(Box::new(UntrustedRegularityProfileV1 {
        profile_id: "regularity".into(),
        artifact_digest: "a".repeat(64),
        mode: "direct".into(),
        measured_rank: 1,
        reconstruction_gain_q32: 1,
        monotonicity_violations: 0,
        positivity_violations: 0,
        holder_residuals: json!({"gain": 1}),
        action_lipschitz_residuals: json!({"axis": {"gain": 1}}),
        ood_margin_q32: 2,
        total_error_q32: 3,
        decision: "pass".into(),
    }))
}

fn applicability() -> UntrustedLearningOperatorProtocolV1 {
    UntrustedLearningOperatorProtocolV1::Applicability(Box::new(
        UntrustedOperatorApplicabilityCertificateV1 {
            certificate_id: "certificate".into(),
            axis_partition_digest: "a".repeat(64),
            domain_digest: "b".repeat(64),
            action_space_digest: "c".repeat(64),
            holder_exponents: json!({"state": 1}),
            holder_constants: json!({"state": 2}),
            state_lipschitz: json!({"state": 3}),
            action_lipschitz: json!({"action": 4}),
            ellipticity_nu_lcb_q32: 1,
            horizon_micros: 10,
            control_interval_profile_digest: "d".repeat(64),
            jump_policy_digest: "e".repeat(64),
            ood_policy_digest: "f".repeat(64),
            evaluator_identity: "evaluator".into(),
            expires_unix_ms: 100,
            decision: "pass".into(),
        },
    ))
}

fn fixtures() -> [UntrustedLearningOperatorProtocolV1; 3] {
    [sensor(), regularity(), applicability()]
}

fn from_value(id: &str, value: Value) -> UntrustedLearningOperatorProtocolV1 {
    match id {
        "OperatorSensorCoreManifestV1" => UntrustedLearningOperatorProtocolV1::SensorCore(
            Box::new(serde_json::from_value(value).unwrap()),
        ),
        "RegularityProfileV1" => UntrustedLearningOperatorProtocolV1::Regularity(Box::new(
            serde_json::from_value(value).unwrap(),
        )),
        _ => UntrustedLearningOperatorProtocolV1::Applicability(Box::new(
            serde_json::from_value(value).unwrap(),
        )),
    }
}

#[test]
fn all_registered_views_round_trip_without_native_authority() {
    for fixture in fixtures() {
        let bytes = fixture.encode_canonical().unwrap();
        let decoded = decode_learning_operator_protocol(fixture.protocol_id(), 1, &bytes).unwrap();
        assert_eq!(decoded, fixture);
        assert_eq!(decoded.encode_canonical().unwrap(), bytes);
        assert_eq!(
            decoded.semantic_digest().unwrap(),
            Sha256Digest::for_bytes(&bytes)
        );
    }
}

#[test]
fn exact_field_shape_order_and_limits_match_real_registry() {
    let registry: Value = serde_json::from_str(include_str!(
        "../../../docs/contracts/PROTOCOL_SCHEMAS.json"
    ))
    .unwrap();
    let contracts: Value =
        serde_json::from_str(include_str!("../../../docs/contracts/CONTRACTS.json")).unwrap();
    for fixture in fixtures() {
        let contract = contracts["contracts"]
            .as_array()
            .unwrap()
            .iter()
            .find(|entry| entry["id"] == fixture.protocol_id())
            .unwrap();
        assert_eq!(contract["version"], 1);
        assert_eq!(contract["authorityDelta"], "none");
        let registered = registry["protocols"]
            .as_array()
            .unwrap()
            .iter()
            .find(|entry| entry["id"] == fixture.protocol_id())
            .unwrap();
        assert_eq!(
            registered["maximumEncodedBytes"],
            MAX_LEARNING_OPERATOR_PROTOCOL_BYTES
        );
        assert_eq!(registered["canonicalEncoding"], "canonical_json_utf8");
        assert_eq!(registered["denyUnknownCriticalFields"], true);
        let bytes = fixture.encode_canonical().unwrap();
        let encoded = String::from_utf8(bytes.clone()).unwrap();
        let fields: Value = serde_json::from_slice(&bytes).unwrap();
        let mut previous = 0;
        let mut present = 0;
        for field in registered["fields"].as_array().unwrap() {
            let name = field["name"].as_str().unwrap();
            if !fields.as_object().unwrap().contains_key(name) {
                assert_eq!(field["required"], false);
                continue;
            }
            let position = encoded.find(&format!("\"{name}\":")).unwrap();
            assert!(position >= previous, "registry field order drift: {name}");
            previous = position;
            present += 1;
            let mut invalid = fields.clone();
            match field["type"].as_str().unwrap() {
                "id128" | "enum" => {
                    invalid[name] =
                        json!("a".repeat(field["maxBytes"].as_u64().unwrap() as usize + 1))
                }
                "bounded_object" => {
                    invalid[name] = json!({"oversize": "a".repeat(field["maxBytes"].as_u64().unwrap() as usize)})
                }
                "sha256" => invalid[name] = json!("G".repeat(64)),
                _ => continue,
            }
            assert!(
                from_value(fixture.protocol_id(), invalid)
                    .encode_canonical()
                    .is_err(),
                "registered bound not enforced: {name}"
            );
        }
        assert_eq!(present, fields.as_object().unwrap().len());
    }
    assert!(
        contracts["contracts"]
            .as_array()
            .unwrap()
            .iter()
            .any(|entry| entry["id"] == "BellmanOperatorArtifactV1")
    );
    assert!(
        !registry["protocols"]
            .as_array()
            .unwrap()
            .iter()
            .any(|entry| entry["id"] == "BellmanOperatorArtifactV1")
    );
}

#[test]
fn version_dispatch_rejects_unknown_missing_schema_and_relabeling() {
    let bytes = sensor().encode_canonical().unwrap();
    for version in [0, 2, u32::MAX] {
        assert_eq!(
            decode_learning_operator_protocol("OperatorSensorCoreManifestV1", version, &bytes),
            Err(LearningOperatorProtocolError::UnsupportedVersion(version))
        );
    }
    assert_eq!(
        decode_learning_operator_protocol("unregistered", 1, &bytes),
        Err(LearningOperatorProtocolError::UnknownProtocol)
    );
    assert_eq!(
        decode_learning_operator_protocol("BellmanOperatorArtifactV1", 1, b"HEPTTB01"),
        Err(LearningOperatorProtocolError::MissingCanonicalSchema)
    );
    assert!(decode_learning_operator_protocol("RegularityProfileV1", 1, &bytes).is_err());
}

#[test]
fn unknown_missing_duplicate_and_noncanonical_fields_are_rejected() {
    for fixture in fixtures() {
        let encoded = String::from_utf8(fixture.encode_canonical().unwrap()).unwrap();
        for invalid in [
            format!(" {encoded}"),
            encoded.replacen('{', "{\"authority\":true,", 1),
        ] {
            assert!(
                decode_learning_operator_protocol(fixture.protocol_id(), 1, invalid.as_bytes())
                    .is_err()
            );
        }
        let mut value: Value = serde_json::from_str(&encoded).unwrap();
        value
            .as_object_mut()
            .unwrap()
            .remove("expiresUnixMs")
            .or_else(|| value.as_object_mut().unwrap().remove("profileId"));
        assert!(
            decode_learning_operator_protocol(
                fixture.protocol_id(),
                1,
                &serde_json::to_vec(&value).unwrap()
            )
            .is_err()
        );
    }
    let encoded = String::from_utf8(regularity().encode_canonical().unwrap()).unwrap();
    let duplicate = encoded.replace("\"gain\":1", "\"gain\":0,\"gain\":1");
    assert_eq!(
        decode_learning_operator_protocol("RegularityProfileV1", 1, duplicate.as_bytes()),
        Err(LearningOperatorProtocolError::NonCanonical)
    );
    let duplicate_top = encoded.replacen(
        "\"measuredRank\":1",
        "\"measuredRank\":1,\"measuredRank\":1",
        1,
    );
    assert_eq!(
        decode_learning_operator_protocol("RegularityProfileV1", 1, duplicate_top.as_bytes()),
        Err(LearningOperatorProtocolError::Json)
    );
    let sensor = String::from_utf8(sensor().encode_canonical().unwrap()).unwrap();
    let explicit_null = sensor.replace(
        "\"expiresUnixMs\"",
        "\"predecessorId\":null,\"expiresUnixMs\"",
    );
    assert_eq!(
        decode_learning_operator_protocol(
            "OperatorSensorCoreManifestV1",
            1,
            explicit_null.as_bytes()
        ),
        Err(LearningOperatorProtocolError::NonCanonical)
    );
}

#[test]
fn byte_bounds_cover_objects_fields_and_document_before_parse() {
    assert_eq!(
        decode_learning_operator_protocol(
            "RegularityProfileV1",
            1,
            &vec![b' '; MAX_LEARNING_OPERATOR_PROTOCOL_BYTES + 1]
        ),
        Err(LearningOperatorProtocolError::Bounds)
    );
    assert!(
        decode_learning_operator_protocol(
            "RegularityProfileV1",
            1,
            &vec![b' '; MAX_LEARNING_OPERATOR_PROTOCOL_BYTES]
        )
        .is_err()
    );
    let mut fixture = applicability();
    if let UntrustedLearningOperatorProtocolV1::Applicability(value) = &mut fixture {
        value.holder_exponents = json!({"x": "a".repeat(8_184)});
    }
    assert!(fixture.encode_canonical().is_ok());
    if let UntrustedLearningOperatorProtocolV1::Applicability(value) = &mut fixture {
        value.holder_exponents = json!({"x": "a".repeat(8_185)});
    }
    assert_eq!(
        fixture.encode_canonical(),
        Err(LearningOperatorProtocolError::Bounds)
    );
    let mut fixture = sensor();
    if let UntrustedLearningOperatorProtocolV1::SensorCore(value) = &mut fixture {
        value.sensor_core_id = "é".repeat(65);
    }
    assert_eq!(
        fixture.encode_canonical(),
        Err(LearningOperatorProtocolError::Bounds)
    );
}

#[test]
fn typed_numbers_use_exact_registered_widths_without_scientific_admission() {
    let mut fixture = sensor();
    if let UntrustedLearningOperatorProtocolV1::SensorCore(value) = &mut fixture {
        value.count = u32::MAX;
        value.fill_distance_q32 = i64::MIN;
        value.separation_radius_q32 = i64::MAX;
        value.expires_unix_ms = u64::MAX;
    }
    let encoded = String::from_utf8(fixture.encode_canonical().unwrap()).unwrap();
    assert_eq!(
        decode_learning_operator_protocol(fixture.protocol_id(), 1, encoded.as_bytes()).unwrap(),
        fixture
    );
    for invalid in [
        encoded.replace("4294967295", "4294967296"),
        encoded.replace("18446744073709551615", "18446744073709551616"),
        encoded.replace("-9223372036854775808", "-9223372036854775809"),
        encoded.replace("4294967295", "1.0"),
    ] {
        assert!(
            decode_learning_operator_protocol(fixture.protocol_id(), 1, invalid.as_bytes())
                .is_err()
        );
    }
}

#[test]
fn every_semantic_field_changes_transport_digest() {
    for fixture in fixtures() {
        let original = fixture.semantic_digest().unwrap();
        let fields: Value = serde_json::from_slice(&fixture.encode_canonical().unwrap()).unwrap();
        for (name, value) in fields.as_object().unwrap() {
            let mut modified = fields.clone();
            modified[name] = match value {
                Value::String(value) if value.len() == 64 => json!("0".repeat(64)),
                Value::String(value) => json!(format!("{value}_changed")),
                Value::Number(value) => json!(value.as_i64().unwrap() + 1),
                Value::Object(_) => json!({"changed": 1}),
                _ => panic!("unexpected fixture field {name}"),
            };
            assert_ne!(
                from_value(fixture.protocol_id(), modified)
                    .semantic_digest()
                    .unwrap(),
                original,
                "unbound field {name}"
            );
        }
    }
    let mut with_predecessor = sensor();
    if let UntrustedLearningOperatorProtocolV1::SensorCore(value) = &mut with_predecessor {
        value.predecessor_id = Some("previous".into());
    }
    assert_ne!(
        with_predecessor.semantic_digest().unwrap(),
        sensor().semantic_digest().unwrap()
    );
}

#[test]
fn nested_object_order_is_stable_and_non_objects_or_deep_trees_fail() {
    let mut fixture = regularity();
    if let UntrustedLearningOperatorProtocolV1::Regularity(value) = &mut fixture {
        value.holder_residuals = serde_json::from_str("{\"z\":{\"z\":2,\"a\":1},\"a\":0}").unwrap();
    }
    let encoded = String::from_utf8(fixture.encode_canonical().unwrap()).unwrap();
    assert!(encoded.contains("\"holderResiduals\":{\"a\":0,\"z\":{\"a\":1,\"z\":2}}"));
    for invalid in [Value::Null, json!([]), json!(1)] {
        if let UntrustedLearningOperatorProtocolV1::Regularity(value) = &mut fixture {
            value.holder_residuals = invalid;
        }
        assert_eq!(
            fixture.encode_canonical(),
            Err(LearningOperatorProtocolError::Object)
        );
    }
    let mut deep = json!({});
    for _ in 0..130 {
        deep = json!({"nested": deep});
    }
    if let UntrustedLearningOperatorProtocolV1::Regularity(value) = &mut fixture {
        value.holder_residuals = deep;
    }
    assert_eq!(
        fixture.encode_canonical(),
        Err(LearningOperatorProtocolError::Bounds)
    );
}

#[test]
fn deepest_accepted_constructed_object_round_trips_at_parser_limit() {
    let mut fixture = regularity();
    let mut deep = json!({});
    for _ in 0..125 {
        deep = json!({"nested": deep});
    }
    if let UntrustedLearningOperatorProtocolV1::Regularity(value) = &mut fixture {
        value.holder_residuals = deep.clone();
    }
    let bytes = fixture.encode_canonical().unwrap();
    assert_eq!(
        decode_learning_operator_protocol(fixture.protocol_id(), 1, &bytes).unwrap(),
        fixture
    );
    if let UntrustedLearningOperatorProtocolV1::Regularity(value) = &mut fixture {
        value.holder_residuals = json!({"nested": deep});
    }
    assert_eq!(
        fixture.encode_canonical(),
        Err(LearningOperatorProtocolError::Bounds)
    );
}

#[test]
fn constructed_oversize_strings_keys_and_branch_fail_before_clone_or_sort() {
    let mut huge_digest = sensor();
    if let UntrustedLearningOperatorProtocolV1::SensorCore(value) = &mut huge_digest {
        value.points_digest = "a".repeat(1_048_576);
    }
    assert_eq!(
        huge_digest.encode_canonical(),
        Err(LearningOperatorProtocolError::Digest)
    );
    for object in [
        json!({"small": "x".repeat(1_048_576)}),
        json!({"x".repeat(1_048_576): 0}),
        json!({"branch": [{"nested": "x".repeat(1_048_576)}]}),
    ] {
        let mut fixture = regularity();
        if let UntrustedLearningOperatorProtocolV1::Regularity(value) = &mut fixture {
            value.holder_residuals = object;
        }
        assert_eq!(
            fixture.encode_canonical(),
            Err(LearningOperatorProtocolError::Bounds)
        );
    }
}

#[test]
fn nested_number_tokens_do_not_change_with_unified_serde_features() {
    let bytes = String::from_utf8(regularity().encode_canonical().unwrap()).unwrap();
    for token in [
        "1e0",
        "1e+00",
        "1.00",
        "-0",
        "18446744073709551616",
        "1e400",
    ] {
        let invalid = bytes.replacen("\"gain\":1", &format!("\"gain\":{token}"), 1);
        assert!(
            decode_learning_operator_protocol("RegularityProfileV1", 1, invalid.as_bytes())
                .is_err()
        );
    }
    for token in [
        "1.0",
        "-0.0",
        "1e+30",
        "9007199254740993",
        "18446744073709551615",
    ] {
        let valid = bytes.replacen("\"gain\":1", &format!("\"gain\":{token}"), 1);
        let decoded =
            decode_learning_operator_protocol("RegularityProfileV1", 1, valid.as_bytes()).unwrap();
        assert_eq!(decoded.encode_canonical().unwrap(), valid.as_bytes());
    }
}

#[test]
fn serde_private_members_are_rejected_at_root_nested_and_array_locations() {
    for key in [
        "$serde_json::private::Number",
        "$serde_json::private::RawValue",
        "$serde_json::private::future",
    ] {
        for object in [
            json!({key: "1"}),
            json!({"nested": {key: "1"}}),
            json!({"items": [{key: "1"}]}),
        ] {
            let mut fixture = regularity();
            if let UntrustedLearningOperatorProtocolV1::Regularity(value) = &mut fixture {
                value.holder_residuals = object;
            }
            assert_eq!(
                fixture.encode_canonical(),
                Err(LearningOperatorProtocolError::ReservedMember)
            );
        }
        let original = String::from_utf8(regularity().encode_canonical().unwrap()).unwrap();
        for object in [
            format!("{{\"{key}\":\"1\"}}"),
            format!("{{\"nested\":{{\"{key}\":\"1\"}}}}"),
            format!("{{\"items\":[{{\"{key}\":\"1\"}}]}}"),
        ] {
            let wire = original.replacen(
                "\"holderResiduals\":{\"gain\":1}",
                &format!("\"holderResiduals\":{object}"),
                1,
            );
            assert!(
                decode_learning_operator_protocol("RegularityProfileV1", 1, wire.as_bytes())
                    .is_err()
            );
        }
    }
}
