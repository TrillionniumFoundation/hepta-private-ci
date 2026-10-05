//! Public source adapter checks; no scientific acceptance or cohort consumption.
#![allow(clippy::unwrap_used)]
use super::*;
use pretty_assertions::assert_eq;
use serde_json::Value;

fn feature(number: u64, split: &str) -> Feature {
    Feature {
        domain: "hepta.healthver.public-feature-record.v1".into(),
        source: "HealthVer".into(),
        source_split: split.into(),
        source_row_1based: number,
        upstream_id: format!("row-{number}"),
        claim_text: format!("public claim {number}"),
        evidence_text: format!("public evidence {number}"),
        topic: "public topic".into(),
        question: "public question".into(),
    }
}
fn fixture() -> (Vec<u8>, Vec<u8>, Vec<u8>) {
    let mut rows = Vec::new();
    let mut graph = Vec::new();
    let mut membership = Vec::new();
    for (number, split, group, partition) in [
        (2, "train", 1, "final-public-development"),
        (3, "train", 2, "prior-public-calibration"),
        (4, "dev", 1, "unscored"),
    ] {
        let f = feature(number, split);
        let pin = f.digest().unwrap().to_string();
        let component = Digest32::of_bytes(&[group]).to_string();
        graph.push(
            serde_json::json!({"feature":f,"feature_digest":pin,"component_digest":component,
            "claim_feature_digest":Digest32::of_bytes(b"claim").to_string(),
            "evidence_feature_digest":Digest32::of_bytes(b"evidence").to_string()}),
        );
        if split == "train" {
            let d = Digest32::of_bytes(b"original annotation").to_string();
            rows.push(serde_json::to_string(&serde_json::json!({
                "source":"HealthVer","source_commit":"b20ac99ceed62f5264a319fa25a854df1668d85b",
                "source_split":"train","source_file_sha256":TRAIN,"source_row_1based":number,
                "upstream_id":f.upstream_id,"claim_text":f.claim_text,"evidence_text":f.evidence_text,
                "topic_sha256":d,"question_sha256":d,"normalized_claim_sha256":d,
                "normalized_evidence_sha256":d,"original_row_sha256":d,"row_sha256":d,
                "component_sha256":component,"partition":"calibration","gold":"SUPPORT"
            })).unwrap());
            membership.push(
                serde_json::json!({"pair_id":f.pair_id(),"feature_digest":pin,
                "component_digest":component,"partition":partition}),
            );
        }
    }
    (
        rows.join("\n").into_bytes(),
        serde_json::to_vec(&membership).unwrap(),
        serde_json::to_vec(&graph).unwrap(),
    )
}

#[test]
fn scores_only_original_subset_and_retains_unscored_complete_lineage() {
    let (labels, members, graph) = fixture();
    let p = prepare(&labels, &members, &graph).unwrap();
    let gold: Value = serde_json::from_slice(&p.gold).unwrap();
    let masked: Vec<Value> = serde_json::from_slice(&p.masked).unwrap();
    assert_eq!(
        (
            gold["tasks"].as_array().unwrap().len(),
            masked.len(),
            p.counts.eligible_components
        ),
        (1, 2, 1)
    );
    assert_eq!(
        gold["feature_membership_digest"],
        Digest32::of_bytes(&members).to_string()
    );
    assert_eq!(gold["unscored_component_feature_rows"], 1);
    assert!(gold["scope"].as_str().unwrap().contains("Not an unseen"));
}
#[test]
fn changing_public_annotations_changes_gold_but_not_complete_masked_bytes() {
    let (labels, members, graph) = fixture();
    let before = prepare(&labels, &members, &graph).unwrap();
    let changed = std::str::from_utf8(&labels)
        .unwrap()
        .lines()
        .map(|line| {
            let mut row: Value = serde_json::from_str(line).unwrap();
            row["gold"] = Value::from("CONTRADICT");
            for key in [
                "topic_sha256",
                "question_sha256",
                "normalized_claim_sha256",
                "normalized_evidence_sha256",
                "original_row_sha256",
                "row_sha256",
            ] {
                row[key] = Value::from(Digest32::of_bytes(b"changed annotation").to_string());
            }
            serde_json::to_string(&row).unwrap()
        })
        .collect::<Vec<_>>()
        .join("\n");
    let after = prepare(changed.as_bytes(), &members, &graph).unwrap();
    assert_eq!(before.masked, after.masked);
    assert_ne!(before.gold, after.gold);
}
#[test]
fn shared_component_cannot_be_split_between_prior_and_final_partitions() {
    let (labels, members, graph) = fixture();
    let mut labels: Vec<Value> = std::str::from_utf8(&labels)
        .unwrap()
        .lines()
        .map(|l| serde_json::from_str(l).unwrap())
        .collect();
    let mut members: Vec<Value> = serde_json::from_slice(&members).unwrap();
    let mut graph: Vec<Value> = serde_json::from_slice(&graph).unwrap();
    let common = members[0]["component_digest"].clone();
    members[1]["component_digest"] = common.clone();
    labels[1]["component_sha256"] = common.clone();
    graph[1]["component_digest"] = common;
    let labels = labels
        .iter()
        .map(|r| serde_json::to_string(r).unwrap())
        .collect::<Vec<_>>()
        .join("\n");
    assert!(
        prepare(
            labels.as_bytes(),
            &serde_json::to_vec(&members).unwrap(),
            &serde_json::to_vec(&graph).unwrap()
        )
        .is_err()
    );
}
#[test]
fn replaced_feature_and_missing_original_gold_task_are_rejected() {
    let (labels, members, graph) = fixture();
    let mut changed: Vec<Value> = serde_json::from_slice(&graph).unwrap();
    changed[0]["feature"]["claim_text"] = Value::from("different public claim");
    assert!(prepare(&labels, &members, &serde_json::to_vec(&changed).unwrap()).is_err());
    assert!(prepare(b"", &members, &graph).is_err());
}
#[test]
fn neutral_or_unknown_public_label_cannot_be_mapped_to_binary_gold() {
    let (labels, members, graph) = fixture();
    let changed = std::str::from_utf8(&labels)
        .unwrap()
        .replace("SUPPORT", "NEUTRAL");
    assert!(prepare(changed.as_bytes(), &members, &graph).is_err());
}

#[test]
#[ignore = "requires Root-protected original public development source pins and cap0 service"]
fn original_public_source_subset_retains_all_component_bridge_features() {
    boundary().unwrap();
    let root = PathBuf::from(std::env::var("HEPTA_PUBLIC_CUSTODY_SOURCE_DIRECTORY").unwrap());
    let calibration = source(
        &Source {
            path: root.join("calibration-pairs.jsonl"),
            digest: CALIBRATION.into(),
        },
        16 * 1024 * 1024,
    )
    .unwrap();
    let membership = source(
        &Source {
            path: root.join("public-feature-membership.json"),
            digest: MEMBERSHIP.into(),
        },
        1024 * 1024,
    )
    .unwrap();
    let graph = source(
        &Source {
            path: root.join("public-complete-feature-graph.json"),
            digest: GRAPH.into(),
        },
        32 * 1024 * 1024,
    )
    .unwrap();
    let p = prepare(&calibration, &membership, &graph).unwrap();
    assert_eq!(
        (
            p.counts.labeled_pairs,
            p.counts.eligible_components,
            p.counts.eligible_claims
        ),
        (97, 6, 310)
    );
    let masked: Vec<Value> = serde_json::from_slice(&p.masked).unwrap();
    let gold: Value = serde_json::from_slice(&p.gold).unwrap();
    assert_eq!(
        (masked.len(), gold["tasks"].as_array().unwrap().len()),
        (310, 97)
    );
    assert_eq!(gold["unscored_component_feature_rows"], 213);
    assert!(masked.iter().any(|r| r["source_split"] == "dev"));
    assert!(
        masked
            .iter()
            .all(|r| r.get("gold").is_none() && r.get("original_row_sha256").is_none())
    );
}
