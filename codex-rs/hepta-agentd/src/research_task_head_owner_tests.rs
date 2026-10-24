use super::*;
use serde_json::Value;
use serde_json::json;

fn must<T, E: fmt::Debug>(result: Result<T, E>) -> T {
    match result {
        Ok(value) => value,
        Err(error) => panic!("{error:?}"),
    }
}

struct Fixture {
    header: Value,
    native: Value,
    inventory: Vec<RowBinding>,
    features: Vec<f32>,
    weights: Vec<u8>,
}

impl Fixture {
    fn new(count: usize) -> Self {
        let features = vec![0.0; WIDTH];
        let mut weights = vec![0.0_f32; 5 * WIDTH + 4];
        let bias = weights.len() - 2;
        weights[bias] = 2.0;
        let weights: Vec<u8> = weights.iter().flat_map(|v| v.to_le_bytes()).collect();
        let identity = json!({"encoder_sha256":"1".repeat(64),
            "checkpoint_revision":"2".repeat(40), "preprocess_sha256":"3".repeat(64),
            "generation":1, "scope_id":"research-fixture", "purpose":"research",
            "revocation_epoch":0});
        let native = json!({"schema":"hepta.native-task-head.v1",
            "numeric_profile":"f32-io-f64-accum-gelu-erf-v1", "state_contract":"zero_state_only",
            "mode":"SHADOW_ONLY", "authority":"DENY_ALL", "feature_identity":identity,
            "feature_layout":LAYOUT, "width":WIDTH, "state_width":1, "adapter_rank":1,
            "task_count":2, "required_present_mask":3, "temperature":0.25,
            "confidence_threshold":0.7, "source_head_manifest_sha256":"4".repeat(64),
            "source_head_weights_sha256":"5".repeat(64),
            "weights_sha256":Digest32::of_bytes(&weights).to_string(), "weights_bytes":weights.len()});
        let mut header = json!({"schema":"hepta.research-task-head-owner.v1",
            "mode":"SHADOW_ONLY", "authority":"DENY_ALL", "production_activation_allowed":false,
            "task_admission_allowed":false, "action_execution_allowed":false,
            "source_commit":"6".repeat(40), "feature_identity":native["feature_identity"],
            "feature_layout":LAYOUT, "width":WIDTH, "required_present_mask":3,
            "temperature":0.25, "confidence_threshold":0.7, "state_contract":"zero_state_only",
            "numeric_profile":"f32-io-f64-accum-gelu-erf-v1", "inventory_rows":count,
            "source_head_manifest_sha256":native["source_head_manifest_sha256"],
            "source_head_weights_sha256":native["source_head_weights_sha256"],
            "native_head_weights_sha256":native["weights_sha256"]});
        for key in [
            "source_report_sha256",
            "source_plan_sha256",
            "cohort_manifest_sha256",
            "bank_manifest_sha256",
            "feature_payload_sha256",
            "producer_code_sha256",
        ] {
            header[key] = json!("7".repeat(64));
        }
        let inventory = (0..count)
            .map(|index| RowBinding {
                case_id: ResearchTaskHeadCaseV1::Paired,
                row_index: index,
                row_id: Digest32::of_bytes(&index.to_le_bytes()).to_string(),
                pair_block_id: "8".repeat(64),
                image_id: 1 + (index % 2) as u64,
                caption_id: 10 + index as u64,
                source_caption_image_id: 1,
                source_record_digest: "9".repeat(64),
                text_provenance_sha256: "a".repeat(64),
                image_provenance_sha256: "b".repeat(64),
                present_mask: 3,
                features_sha256: feature_digest(&features).to_string(),
            })
            .collect();
        Self {
            header,
            native,
            inventory,
            features,
            weights,
        }
    }

    fn package(&self) -> (Vec<u8>, Vec<u8>, Vec<u8>) {
        let inventory = must(serde_json::to_vec(&json!({
            "schema":"hepta.research-task-head-row-inventory.v1", "rows":self.inventory})));
        let native = must(serde_json::to_vec(&self.native));
        let mut header = self.header.clone();
        header["inventory_sha256"] = json!(Digest32::of_bytes(&inventory).to_string());
        header["native_head_manifest_sha256"] = json!(Digest32::of_bytes(&native).to_string());
        (must(serde_json::to_vec(&header)), inventory, native)
    }

    fn owner(&self) -> Result<AgentdResearchTaskHeadOwnerV1, ResearchTaskHeadOwnerError> {
        let (header, inventory, native) = self.package();
        AgentdResearchTaskHeadOwnerV1::from_artifacts(
            &header,
            &inventory,
            &native,
            &self.weights,
            Digest32::of_bytes(&header),
            Digest32::of_bytes(&native),
        )
    }

    fn request(&self) -> Value {
        let mut rows = self.inventory.clone();
        rows.sort_by_key(|row| (row.case_id, row.row_index));
        json!({"owner_manifest_sha256":Digest32::of_bytes(&self.package().0).to_string(),
            "feature_identity":self.native["feature_identity"],
            "rows":rows.iter().map(|row| json!({"binding":row,"features":self.features})).collect::<Vec<_>>()})
    }
}

#[test]
fn declared_original_crossed_and_shuffled_pairs_all_score_without_label_gate() {
    let mut fixture = Fixture::new(3);
    fixture.inventory[2].case_id = ResearchTaskHeadCaseV1::ShuffledImage;
    let mut owner = must(fixture.owner());
    let receipt = must(owner.score_json(&must(serde_json::to_vec(&fixture.request()))));
    assert_eq!(
        (
            receipt.input_rows,
            receipt.forward_calls,
            owner.forward_entries
        ),
        (3, 3, 3)
    );
    assert!(
        receipt
            .rows
            .iter()
            .all(|row| row.status == "SCORED_RESEARCH_ONLY" && row.accepted)
    );
    assert_eq!(
        (
            receipt.mode,
            receipt.authority,
            receipt.production_activation_allowed,
            receipt.task_admission_allowed,
            receipt.action_execution_allowed
        ),
        ("SHADOW_ONLY", "DENY_ALL", false, false, false)
    );
}

#[test]
fn declared_missing_rows_never_enter_native_head_and_mixed_rows_preserve_order() {
    let mut fixture = Fixture::new(6);
    for (row, mask) in fixture.inventory.iter_mut().zip([3, 0, 1, 2, 31, 4]) {
        row.present_mask = mask;
    }
    let mut owner = must(fixture.owner());
    let receipt = must(owner.score_json(&must(serde_json::to_vec(&fixture.request()))));
    assert_eq!((receipt.forward_calls, owner.forward_entries), (2, 2));
    assert_eq!(
        receipt
            .rows
            .iter()
            .map(|row| (row.row_index, row.prediction.is_some(), row.accepted))
            .collect::<Vec<_>>(),
        vec![
            (0, true, true),
            (1, false, false),
            (2, false, false),
            (3, false, false),
            (4, true, true),
            (5, false, false)
        ]
    );
}

#[test]
fn late_row_drift_and_attacker_rehashed_features_fail_before_first_head_entry() {
    let fixture = Fixture::new(2);
    for rehash in [false, true] {
        let mut request = fixture.request();
        request["rows"][1]["features"][WIDTH - 1] = json!(1.0);
        if rehash {
            let mut values = fixture.features.clone();
            values[WIDTH - 1] = 1.0;
            request["rows"][1]["binding"]["features_sha256"] =
                json!(feature_digest(&values).to_string());
        }
        let mut owner = must(fixture.owner());
        assert!(matches!(
            owner.score_json(&must(serde_json::to_vec(&request))),
            Err(ResearchTaskHeadOwnerError::Integrity)
        ));
        assert_eq!(owner.forward_entries, 0);
    }
}

#[test]
fn mask_pair_source_owner_and_feature_identity_cannot_be_replaced_by_wire() {
    let fixture = Fixture::new(2);
    for pointer in [
        "/rows/1/binding/present_mask",
        "/rows/1/binding/image_id",
        "/rows/1/binding/source_caption_image_id",
        "/rows/1/binding/pair_block_id",
        "/rows/1/binding/source_record_digest",
        "/owner_manifest_sha256",
        "/feature_identity/revocation_epoch",
        "/feature_identity/generation",
    ] {
        let mut request = fixture.request();
        let value = request.pointer_mut(pointer).expect("fixture pointer");
        *value = if value.is_string() {
            json!("f".repeat(64))
        } else {
            json!(42)
        };
        let mut owner = must(fixture.owner());
        assert!(
            owner
                .score_json(&must(serde_json::to_vec(&request)))
                .is_err()
        );
        assert_eq!(owner.forward_entries, 0);
    }
}

#[test]
fn separate_inventory_can_exceed_header_budget_but_never_its_own_bound() {
    let fixture = Fixture::new(128);
    let (header, inventory, native) = fixture.package();
    assert!(header.len() < MAX_HEADER_BYTES);
    assert!(inventory.len() > MAX_HEADER_BYTES && inventory.len() <= MAX_INVENTORY_BYTES);
    must(fixture.owner());
    for (header_bytes, inventory_bytes) in [
        (vec![b' '; MAX_HEADER_BYTES + 1], inventory.clone()),
        (header.clone(), vec![b' '; MAX_INVENTORY_BYTES + 1]),
    ] {
        assert!(matches!(
            AgentdResearchTaskHeadOwnerV1::from_artifacts(
                &header_bytes,
                &inventory_bytes,
                &native,
                &fixture.weights,
                Digest32::of_bytes(&header),
                Digest32::of_bytes(&native)
            ),
            Err(ResearchTaskHeadOwnerError::Bounds)
        ));
    }
}

#[test]
fn native_semantics_source_parent_and_posture_are_cross_bound_even_after_host_rehash() {
    for key in [
        "source_head_manifest_sha256",
        "source_head_weights_sha256",
        "temperature",
        "confidence_threshold",
        "width",
        "required_present_mask",
        "task_admission_allowed",
    ] {
        let mut fixture = Fixture::new(1);
        fixture.header[key] = match key {
            "temperature" | "confidence_threshold" => json!(0.5),
            "width" => json!(512),
            "required_present_mask" => json!(1),
            "task_admission_allowed" => json!(true),
            "source_head_manifest_sha256" | "source_head_weights_sha256" => json!("f".repeat(64)),
            _ => unreachable!(),
        };
        assert!(matches!(
            fixture.owner(),
            Err(ResearchTaskHeadOwnerError::Contract)
        ));
    }
}

#[test]
fn duplicate_reordered_boolean_unknown_and_label_fields_are_rejected() {
    let fixture = Fixture::new(2);
    let original = must(serde_json::to_string(&fixture.request()));
    let mut duplicate = fixture.request();
    duplicate["rows"][1] = duplicate["rows"][0].clone();
    let mut reordered = fixture.request();
    reordered["rows"].as_array_mut().expect("rows").reverse();
    for bytes in [
        original.replace("\"present_mask\":3", "\"present_mask\":true"),
        original.replace("\"present_mask\":3", "\"present_mask\":32"),
        original.replace("\"features\":[0.0", "\"features\":[NaN"),
        original.replace("\"features\":[0.0", "\"features\":[1e99"),
        original.replace(
            "\"present_mask\":3",
            "\"present_mask\":3,\"present_mask\":3",
        ),
        original.replace("\"present_mask\":3", "\"present_mask\":3,\"label\":1"),
        must(serde_json::to_string(&duplicate)),
        must(serde_json::to_string(&reordered)),
        format!("{original}{{}}"),
    ] {
        let mut owner = must(fixture.owner());
        assert!(owner.score_json(bytes.as_bytes()).is_err());
        assert_eq!(owner.forward_entries, 0);
    }
}

#[test]
fn negative_zero_bytes_and_request_row_budget_are_not_silently_coerced() {
    let fixture = Fixture::new(1);
    let mut request = fixture.request();
    request["rows"][0]["features"][0] = json!(-0.0);
    let mut owner = must(fixture.owner());
    assert!(matches!(
        owner.score_json(&must(serde_json::to_vec(&request))),
        Err(ResearchTaskHeadOwnerError::Integrity)
    ));
    let fixture = Fixture::new(MAX_BATCH_ROWS + 1);
    let mut owner = must(fixture.owner());
    assert!(matches!(
        owner.score_json(&must(serde_json::to_vec(&fixture.request()))),
        Err(ResearchTaskHeadOwnerError::Bounds)
    ));
    assert_eq!(owner.forward_entries, 0);
}

#[test]
fn duplicate_declared_row_identity_is_rejected_even_with_distinct_indices() {
    let mut fixture = Fixture::new(2);
    fixture.inventory[1].row_id = fixture.inventory[0].row_id.clone();
    assert!(matches!(
        fixture.owner(),
        Err(ResearchTaskHeadOwnerError::DuplicateRow)
    ));
}
