use super::*;

fn generator() -> serde_json::Value {
    let pin = codex_hepta_types::Digest32::of_bytes(b"original whole static source").to_string();
    serde_json::json!({
        "schema":"hepta.fixed-paired-generator-config.v1", "uid":986,"gid":975,
        "program_digest":pin,"private_key_path":"/original-G/private.key",
        "root_verifying_key_hex":"00".repeat(32),
        "source":{"path":"/root-enrolled/old-input","digest":pin},
        "scope_digest":pin,"objective_digest":pin,"distribution_generation":1,"authority_epoch":1,
        "inaccessible_paths":["/Gold","/Okey","/Ekey","/Skey","/private-custody"]
    })
}
#[test]
fn original_generator_group_and_whole_custody_fields_survive_exact_source_projection() {
    let original = generator();
    let source = ParameterRoleSourceV3 {
        path: "/root-enrolled/current-round-input".into(),
        digest: codex_hepta_types::Digest32::of_bytes(b"whole current round").to_string(),
    };
    let bytes = project_original_paired_parameter_configuration_v1(
        &serde_json::to_vec(&original).unwrap(),
        OriginalPairedParameterConfigurationV1::Generator { inputs: &source },
    )
    .unwrap();
    let actual: serde_json::Value = serde_json::from_slice(&bytes).unwrap();
    let mut expected = original.clone();
    expected["source"] = serde_json::to_value(&source).unwrap();
    assert_eq!(actual, expected);
    for field in ["uid", "gid"] {
        let mut altered = original.clone();
        altered[field] = 0.into();
        assert!(
            project_original_paired_parameter_configuration_v1(
                &serde_json::to_vec(&altered).unwrap(),
                OriginalPairedParameterConfigurationV1::Generator { inputs: &source }
            )
            .is_err()
        );
    }
    let mut injected = original;
    injected["arbitrary_payload_to_sign"] = "caller payload".into();
    assert!(
        project_original_paired_parameter_configuration_v1(
            &serde_json::to_vec(&injected).unwrap(),
            OriginalPairedParameterConfigurationV1::Generator { inputs: &source }
        )
        .is_err()
    );
    // No configuration/codec success replaces the actual UID/GID/cgroup guard.
    assert!(
        crate::fixed_calibration_host::boundary_in_service(986, 976, "hepta-native-generator-")
            .is_err()
    );
}

#[test]
fn original_parameter_finish_requires_distinct_full_sink_and_acknowledgement_parents() {
    let pin = codex_hepta_types::Digest32::of_bytes(b"complete original Source").to_string();
    let source = ParameterRoleSourceV3 {
        path: "/root-enrolled/full-source".into(),
        digest: pin.clone(),
    };
    let original = serde_json::json!({"schema":"hepta.fixed-paired-custody-finish-config.v1", "program_digest":pin,"root_verifying_key_hex":"00".repeat(32), "execution":source,"evaluator_result":source, "private_directory":"/original-private-custody", "witness_path":"/original-witness", "evidence_path":"/original-evidence/full.json","ack_path":"/original-ack/ack.txt", "self_iteration":null,"parameter_evaluation":source});
    let evidence: PathBuf = "/root-enrolled/round-evidence/full.json".into();
    let ack: PathBuf = "/root-enrolled/round-ack/ack.txt".into();
    let bytes = project_original_paired_parameter_configuration_v1(
        &serde_json::to_vec(&original).unwrap(),
        OriginalPairedParameterConfigurationV1::Finish {
            publication: &source,
            evaluation: &source,
            parameter: &source,
            evidence_path: &evidence,
            acknowledgement_path: &ack,
        },
    )
    .unwrap();
    let actual: serde_json::Value = serde_json::from_slice(&bytes).unwrap();
    assert_eq!(actual["private_directory"], original["private_directory"]);
    assert_eq!(actual["witness_path"], original["witness_path"]);
    assert!(
        project_original_paired_parameter_configuration_v1(
            &serde_json::to_vec(&original).unwrap(),
            OriginalPairedParameterConfigurationV1::Finish {
                publication: &source,
                evaluation: &source,
                parameter: &source,
                evidence_path: &evidence,
                acknowledgement_path: &evidence.with_file_name("ack.txt")
            }
        )
        .is_err()
    );
}
