use super::*;

fn digest(label: &str) -> String {
    Digest32::of_bytes(label.as_bytes()).to_string()
}
fn fixture() -> BellmanOperatorArtifactWireV1 {
    let term = |name| BellmanErrorTermWireV1 {
        evidence_digest: digest(name),
        normalized_error_q32: 100,
    };
    BellmanOperatorArtifactWireV1 {
        action_trunk_digest: digest("action"),
        applicability_digest: digest("applicability"),
        artifact_id: "artifact:one".into(),
        branch_digest: digest("branch"),
        error_budget: BellmanErrorBudgetWireV1 {
            dominant_approval_evidence_digest: None,
            schema: "hepta.bellman-error-budget.q32.v1".into(),
            model: term("model"),
            network: term("network"),
            optimization: term("optimization"),
            reconstruction: term("reconstruction"),
            rollout: term("rollout"),
            sensor: term("sensor"),
            statistical: term("statistical"),
        },
        normalization_digest: digest("normalization"),
        predecessor_artifact_id: None,
        rank: 64,
        rollback_digest: digest("rollback"),
        runtime_tuple_digest: digest("runtime"),
        sensor_core_digest: digest("sensor"),
        state_trunk_digest: digest("state"),
        training_code_digest: digest("code"),
        training_dataset_digest: digest("dataset"),
    }
}

#[test]
fn canonical_roundtrip_ordering_and_independent_pin() {
    let admitted = CanonicalBellmanArtifactV1::from_record(fixture()).expect("admit");
    let value: serde_json::Value = serde_json::from_slice(admitted.canonical_json()).expect("json");
    let reordered = serde_json::to_vec_pretty(&value).expect("pretty");
    assert_eq!(
        CanonicalBellmanArtifactV1::from_json(&reordered).expect("decode"),
        admitted
    );
    assert_eq!(
        CanonicalBellmanArtifactV1::from_pinned_json(&reordered, admitted.canonical_digest())
            .expect("pinned"),
        admitted
    );
    assert_eq!(
        CanonicalBellmanArtifactV1::from_pinned_json(&reordered, Digest32::ZERO),
        Err(BellmanArtifactWireError::PinMismatch)
    );
    assert_eq!(
        CanonicalBellmanArtifactV1::from_pinned_json(&reordered, Digest32::of_bytes(b"other")),
        Err(BellmanArtifactWireError::PinMismatch)
    );
    assert_eq!(
        admitted.canonical_json(),
        serde_json::to_vec(&value).expect("sorted lexical fields")
    );
}

#[test]
fn missing_unknown_duplicate_and_wrong_type_fields_reject() {
    let original = serde_json::to_value(fixture()).expect("fixture");
    for field in original.as_object().expect("object").keys() {
        let mut value = original.clone();
        value.as_object_mut().expect("object").remove(field);
        assert_eq!(
            CanonicalBellmanArtifactV1::from_json(&serde_json::to_vec(&value).expect("json")),
            Err(BellmanArtifactWireError::Json),
            "missing {field}"
        );
    }
    for path in ["", "errorBudget", "errorBudget.model"] {
        let mut value = original.clone();
        let target = match path {
            "" => &mut value,
            "errorBudget" => &mut value["errorBudget"],
            _ => &mut value["errorBudget"]["model"],
        };
        target
            .as_object_mut()
            .expect("object")
            .insert("unknown".into(), serde_json::json!(true));
        assert_eq!(
            CanonicalBellmanArtifactV1::from_json(&serde_json::to_vec(&value).expect("json")),
            Err(BellmanArtifactWireError::Json)
        );
    }
    let encoded = serde_json::to_string(&original).expect("json");
    let duplicate = encoded.replacen("{", "{\"rank\":64,", 1);
    assert_eq!(
        CanonicalBellmanArtifactV1::from_json(duplicate.as_bytes()),
        Err(BellmanArtifactWireError::Json)
    );
    let nested = encoded.replace("\"model\":{", "\"model\":{\"normalizedErrorQ32\":100,");
    assert_eq!(
        CanonicalBellmanArtifactV1::from_json(nested.as_bytes()),
        Err(BellmanArtifactWireError::Json)
    );
    for wrong in [
        serde_json::json!(1.5),
        serde_json::json!("64"),
        serde_json::json!(-1),
        serde_json::json!(u64::MAX),
    ] {
        let mut value = original.clone();
        value["rank"] = wrong;
        assert_eq!(
            CanonicalBellmanArtifactV1::from_json(&serde_json::to_vec(&value).expect("json")),
            Err(BellmanArtifactWireError::Json)
        );
    }
}

#[test]
fn bounded_ids_digest_rank_and_optional_lineage_reject_substitution() {
    let mut record = fixture();
    record.artifact_id = "a".repeat(128);
    CanonicalBellmanArtifactV1::from_record(record.clone()).expect("inclusive id bound");
    record.artifact_id.push('a');
    assert_eq!(
        CanonicalBellmanArtifactV1::from_record(record),
        Err(BellmanArtifactWireError::Identity)
    );
    for rank in [0, 65, u32::MAX] {
        let mut record = fixture();
        record.rank = rank;
        assert_eq!(
            CanonicalBellmanArtifactV1::from_record(record),
            Err(BellmanArtifactWireError::Rank)
        );
    }
    for bad in [
        "0".repeat(64),
        "a".repeat(63),
        "G".repeat(64),
        "A".repeat(64),
    ] {
        let mut record = fixture();
        record.rollback_digest = bad;
        assert_eq!(
            CanonicalBellmanArtifactV1::from_record(record),
            Err(BellmanArtifactWireError::Digest)
        );
    }
    let mut record = fixture();
    record.predecessor_artifact_id = Some(record.artifact_id.clone());
    assert_eq!(
        CanonicalBellmanArtifactV1::from_record(record),
        Err(BellmanArtifactWireError::Identity)
    );
    let mut value = serde_json::to_value(fixture()).expect("json");
    value["predecessorArtifactId"] = serde_json::Value::Null;
    assert_eq!(
        CanonicalBellmanArtifactV1::from_json(&serde_json::to_vec(&value).expect("json")),
        Err(BellmanArtifactWireError::Json)
    );
    assert_eq!(
        CanonicalBellmanArtifactV1::from_json(&vec![b' '; MAX_BELLMAN_ARTIFACT_JSON_BYTES + 1]),
        Err(BellmanArtifactWireError::Size)
    );
}

#[test]
fn all_seven_terms_and_exact_error_limits_are_required() {
    let mut value = serde_json::to_value(fixture()).expect("json");
    value["errorBudget"]
        .as_object_mut()
        .expect("object")
        .remove("rollout");
    assert_eq!(
        CanonicalBellmanArtifactV1::from_json(&serde_json::to_vec(&value).expect("json")),
        Err(BellmanArtifactWireError::Json)
    );
    let mut record = fixture();
    record.error_budget.schema = "hepta.bellman-error-budget.q32.v2".into();
    assert_eq!(
        CanonicalBellmanArtifactV1::from_record(record),
        Err(BellmanArtifactWireError::ErrorBudget)
    );
    let mut record = fixture();
    record.error_budget.model.normalized_error_q32 = -1;
    assert_eq!(
        CanonicalBellmanArtifactV1::from_record(record),
        Err(BellmanArtifactWireError::ErrorBudget)
    );
    let mut record = fixture();
    record.error_budget.model.normalized_error_q32 = FixedQ32::ONE.raw() / 20 - 600;
    assert_eq!(
        CanonicalBellmanArtifactV1::from_record(record.clone()),
        Err(BellmanArtifactWireError::DominantApprovalMissing)
    );
    record.error_budget.dominant_approval_evidence_digest = Some(digest("independent-approval"));
    CanonicalBellmanArtifactV1::from_record(record.clone())
        .expect("inclusive total with claimed approval");
    record.error_budget.model.normalized_error_q32 += 1;
    assert_eq!(
        CanonicalBellmanArtifactV1::from_record(record),
        Err(BellmanArtifactWireError::ErrorBudget)
    );
}

#[test]
fn canonical_digest_binds_every_artifact_field() {
    let original = CanonicalBellmanArtifactV1::from_record(fixture()).expect("admit");
    let value = serde_json::to_value(fixture()).expect("json");
    for name in [
        "actionTrunkDigest",
        "applicabilityDigest",
        "branchDigest",
        "normalizationDigest",
        "rollbackDigest",
        "runtimeTupleDigest",
        "sensorCoreDigest",
        "stateTrunkDigest",
        "trainingCodeDigest",
        "trainingDatasetDigest",
    ] {
        let mut changed = value.clone();
        changed[name] = serde_json::json!(digest("different"));
        let changed =
            CanonicalBellmanArtifactV1::from_json(&serde_json::to_vec(&changed).expect("json"))
                .expect("changed");
        assert_ne!(
            original.canonical_digest(),
            changed.canonical_digest(),
            "{name}"
        );
    }
    for change in 0..5 {
        let mut record = fixture();
        match change {
            0 => record.artifact_id = "artifact:other".into(),
            1 => record.rank = 1,
            2 => record.predecessor_artifact_id = Some("artifact:previous".into()),
            3 => record.error_budget.sensor.normalized_error_q32 += 1,
            _ => record.error_budget.sensor.evidence_digest = digest("other-evidence"),
        }
        assert_ne!(
            original.canonical_digest(),
            CanonicalBellmanArtifactV1::from_record(record)
                .expect("changed")
                .canonical_digest()
        );
    }
}

// Frozen independently with Python json.dumps(sort_keys=True, separators=(",", ":"))
// and hashlib.sha256 over UTF-8; neither expected value uses the Rust serializer.
#[test]
fn independent_python_canonical_vector_matches_bytes_and_digest() {
    const JSON: &str = r#"{"actionTrunkDigest":"bd938c688f49b77c7fc537c6b9222e2c97ebddd63076b87f2feaec66fb9c05d0","applicabilityDigest":"2042bc7aa65ee8093727c5bd00b4e0b1ec98b07739dbe6c0aac706c36cbaf173","artifactId":"artifact:python-golden","branchDigest":"f38c764c8aa00b6578f4254a4dc6d9b50f88fa926e270ea7859bd1b707cd8662","errorBudget":{"model":{"evidenceDigest":"9372c470eeadd5ecd9c3c74c2b3cb633f8e2f2fad799250a0f70d652b6b825e4","normalizedErrorQ32":17},"network":{"evidenceDigest":"3009be769fb8f956e8413ee9f3e0836e34968bc40457d0a10c549d2edcf00cc1","normalizedErrorQ32":18},"optimization":{"evidenceDigest":"be92e94aba0be148ec1f142becadb01480a3c633ed6e675d98945416a5a3d24d","normalizedErrorQ32":19},"reconstruction":{"evidenceDigest":"d3986ad4c179b5809a041dc934093a926a10f6c47858c1ceabf660726ccea10f","normalizedErrorQ32":20},"rollout":{"evidenceDigest":"a4fa034cc780dbd72a36bf51ba5ee7afd509020953aae10021794638543fd997","normalizedErrorQ32":21},"schema":"hepta.bellman-error-budget.q32.v1","sensor":{"evidenceDigest":"ca73f61034afc26d96c85c0d2285e1f08b283b891426cef8c05eda5bf3e12ddf","normalizedErrorQ32":22},"statistical":{"evidenceDigest":"a8f9c6d33384115eeb63b2442bcc075c59b3573d8027a3b6323753bb021714e8","normalizedErrorQ32":23}},"normalizationDigest":"ba4ae54580817dffe5ea28891b706be38ad14dedf766df4c9b802c8ea0c2efa2","predecessorArtifactId":"artifact:previous","rank":7,"rollbackDigest":"da25480fb483e6ce3d30f1a179c3c07e9f3b045425b0ac54acc6758a97e2db62","runtimeTupleDigest":"d92c6a81b2ff50096bcda80885427d1f59a25b5f483f7055523504925d16ab23","sensorCoreDigest":"ca73f61034afc26d96c85c0d2285e1f08b283b891426cef8c05eda5bf3e12ddf","stateTrunkDigest":"4ba69735ca53765ed6a709edb56c6ea236b7193a3b29a6b390c346f0f4340e4e","trainingCodeDigest":"5694d08a2e53ffcae0c3103e5ad6f6076abd960eb1f8a56577040bc1028f702b","trainingDatasetDigest":"b277fd623676a525c29b9eb155afc8c9010681814ceafb2d7627f47b9a232576"}"#;
    const SHA256: &str = "3e8c662ece42c6ca149cdc152005d8128da876e3143af094eb51e23f35058ed8";
    let artifact = CanonicalBellmanArtifactV1::from_json(JSON.as_bytes()).expect("golden input");
    assert_eq!(artifact.canonical_json(), JSON.as_bytes());
    assert_eq!(artifact.canonical_digest().to_string(), SHA256);
    let mut padded = JSON.as_bytes().to_vec();
    padded.resize(MAX_BELLMAN_ARTIFACT_JSON_BYTES, b' ');
    assert_eq!(
        CanonicalBellmanArtifactV1::from_json(&padded).expect("inclusive ingress bound"),
        artifact
    );
    padded.push(b' ');
    assert_eq!(
        CanonicalBellmanArtifactV1::from_json(&padded),
        Err(BellmanArtifactWireError::Size)
    );
}
