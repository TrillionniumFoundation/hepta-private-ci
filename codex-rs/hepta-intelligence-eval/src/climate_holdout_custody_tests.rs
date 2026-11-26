use super::*;
use pretty_assertions::assert_eq;

fn cut() -> FeatureCut {
    let pin = Digest32::of_bytes(b"fixture provenance").to_string();
    FeatureCut {
        schema: "hepta.climate-fever.feature-cut.v1".into(),
        source_digest: ORIGINAL_SOURCE.into(),
        adapter_program_digest: pin.clone(),
        preview_program_digest: PREVIEW.into(),
        comparison_program_digest: COMPARISON.into(),
        known_feature_inventory_digest: pin.clone(),
        original_source_pins: [
            "masked72_sha256",
            "source99_sha256",
            "config72_sha256",
            "witness72_sha256",
            "initialize99_sha256",
        ]
        .into_iter()
        .map(|name| (name.into(), pin.clone()))
        .collect(),
        known_feature_records: 15321,
        public_health_source_pins: ["train", "dev", "test"]
            .into_iter()
            .map(|name| (name.into(), pin.clone()))
            .collect(),
        public_scifact_footprint_digest: pin,
        normalization: "NFC/casefold/canonical-whitespace; article underscores equal spaces".into(),
        public_example_claim_ids: vec!["0".into()],
        components: vec![vec!["1".into(), "2".into()]],
        source_claims: 1535,
        source_evidence_rows: 7675,
        annotation_values_used: false,
        old_gold_keys_cas_opened: false,
    }
}

fn row(id: &str, label: &str) -> Value {
    serde_json::json!({"claim_id":id,"claim":"actual claim text","claim_label":"DISPUTED",
        "evidences":(0..5).map(|index| serde_json::json!({
            "evidence_id":format!("shared-source-{index}"), "evidence_label":label,
            "article":"original article", "evidence":format!("actual sentence {index}"),
            "entropy":0,"votes":[]
        })).collect::<Vec<_>>()})
}

fn bytes(rows: &[Value]) -> Vec<u8> {
    rows.iter()
        .map(Value::to_string)
        .collect::<Vec<_>>()
        .join("\n")
        .into_bytes()
}

#[test]
fn disputed_claim_is_not_gold_and_shared_evidence_keeps_original_identity() -> HostResult<()> {
    let mut cut = cut();
    cut.source_claims = 3;
    cut.source_evidence_rows = 15;
    let rows = [
        row("0", "REFUTES"),
        row("1", "SUPPORTS"),
        row("2", "REFUTES"),
    ];
    let prepared = prepare(&bytes(&rows), b"original cut", &cut)?;
    let gold: Value = serde_json::from_slice(&prepared.gold)?;
    let expected = ["SUPPORT"; 5]
        .into_iter()
        .chain(["CONTRADICT"; 5])
        .collect::<Vec<_>>();
    assert_eq!(
        gold["tasks"]
            .as_array()
            .ok_or("tasks")?
            .iter()
            .map(|task| task["gold"].as_str().ok_or("gold"))
            .collect::<Result<Vec<_>, _>>()?,
        expected
    );
    let masked: Vec<Value> = serde_json::from_slice(&prepared.masked)?;
    assert_eq!(masked.len(), 10);
    assert!(
        masked
            .iter()
            .all(|feature| feature["source_component_claim_ids"] == serde_json::json!(["1", "2"]))
    );
    assert!(
        masked
            .iter()
            .all(|feature| feature.get("doc_id").is_none() && feature.get("gold").is_none())
    );
    Ok(())
}

#[test]
fn neutral_features_survive_and_gold_changes_do_not_select_a_feature_subset() -> HostResult<()> {
    let mut cut = cut();
    cut.source_claims = 3;
    cut.source_evidence_rows = 15;
    let mut rows = [
        row("0", "SUPPORTS"),
        row("1", "SUPPORTS"),
        row("2", "NOT_ENOUGH_INFO"),
    ];
    let before = prepare(&bytes(&rows), b"cut", &cut)?;
    assert_eq!(
        (
            before.counts.labeled_pairs,
            before.counts.unjudged_pairs_not_scored
        ),
        (5, 5)
    );
    let masked: Vec<Value> = serde_json::from_slice(&before.masked)?;
    assert_eq!(masked.len(), 10);
    // Change every annotation, including the per-evidence scoring membership.
    // The complete masked bytes must remain identical, including every digest.
    for (index, claim) in rows.iter_mut().enumerate() {
        claim["claim_label"] = serde_json::json!({"ignored":"opaque"});
        for evidence in claim["evidences"].as_array_mut().ok_or("evidence")? {
            evidence["evidence_label"] = serde_json::json!(if index == 1 {
                "NOT_ENOUGH_INFO"
            } else {
                "REFUTES"
            });
            evidence["entropy"] = serde_json::json!(123);
            evidence["votes"] = serde_json::json!(["changed annotation"]);
        }
    }
    let after = prepare(&bytes(&rows), b"cut", &cut)?;
    assert_eq!(before.masked, after.masked);
    assert_ne!(before.gold, after.gold);
    assert_eq!(
        (
            after.counts.labeled_pairs,
            after.counts.unjudged_pairs_not_scored
        ),
        (5, 5)
    );
    Ok(())
}

#[test]
fn full_feature_provenance_rejects_label_selection_and_membership_drift() -> HostResult<()> {
    let adapter = Digest32::of_bytes(b"fixture provenance");
    cut().validate(adapter)?;
    for change in 0..6 {
        let mut invalid = cut();
        match change {
            0 => invalid.annotation_values_used = true,
            1 => invalid.old_gold_keys_cas_opened = true,
            2 => invalid.components[0].push("1".into()),
            3 => invalid.components[0] = vec!["0".into()],
            4 => {
                invalid.original_source_pins.remove("source99_sha256");
            }
            5 => {
                invalid.adapter_program_digest = Digest32::of_bytes(b"changed adapter").to_string()
            }
            _ => unreachable!(),
        }
        assert!(invalid.validate(adapter).is_err());
    }
    Ok(())
}

#[test]
fn incomplete_duplicate_unknown_gold_and_all_neutral_inputs_fail_closed() {
    let mut cut = cut();
    cut.source_claims = 3;
    cut.source_evidence_rows = 15;
    let rows = [
        row("0", "SUPPORTS"),
        row("1", "SUPPORTS"),
        row("2", "REFUTES"),
    ];
    assert!(prepare(&bytes(&rows[..2]), b"cut", &cut).is_err());
    assert!(
        prepare(
            &bytes(&[
                row("0", "SUPPORTS"),
                row("1", "SUPPORTS"),
                row("1", "REFUTES")
            ]),
            b"cut",
            &cut
        )
        .is_err()
    );
    for label in ["DISPUTED", "NOT_ENOUGH_INFO"] {
        assert!(
            prepare(
                &bytes(&[row("0", "SUPPORTS"), row("1", label), row("2", label)]),
                b"cut",
                &cut
            )
            .is_err()
        );
    }
    let mut unknown = cut;
    unknown.components = vec![vec!["missing".into()]];
    assert!(prepare(&bytes(&rows), b"cut", &unknown).is_err());
}
