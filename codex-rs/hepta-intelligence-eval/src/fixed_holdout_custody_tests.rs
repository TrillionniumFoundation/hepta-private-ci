use super::eligible_components;
use codex_hepta_types::Digest32;
use serde_json::Value;

fn claim(id: u64, docs: &[u64]) -> (Value, Digest32) {
    let row = serde_json::json!({"id":id,"cited_doc_ids":docs,"evidence":{}});
    let digest = Digest32::of_bytes(row.to_string().as_bytes());
    (row, digest)
}

#[test]
fn heldout_discards_the_whole_indirect_component_touching_earlier_sources()
-> Result<(), Box<dyn std::error::Error>> {
    let earlier = vec![claim(1, &[11])];
    let heldout = vec![
        claim(2, &[11, 12]),
        claim(3, &[12, 13]),
        claim(4, &[13]),
        claim(5, &[20]),
        claim(6, &[20, 21]),
    ];
    assert_eq!(eligible_components(&earlier, &heldout)?, vec![vec![3, 4]]);
    Ok(())
}

#[test]
fn repeated_claim_and_gold_evidence_document_also_exclude_a_component()
-> Result<(), Box<dyn std::error::Error>> {
    let earlier = vec![claim(1, &[11])];
    let mut annotated = claim(3, &[22]);
    annotated.0["evidence"] = serde_json::json!({"11":[{"label":"SUPPORT"}]});
    let heldout = vec![claim(1, &[99]), annotated, claim(4, &[22]), claim(5, &[30])];
    assert_eq!(eligible_components(&earlier, &heldout)?, vec![vec![3]]);
    assert!(eligible_components(&earlier, &[claim(8, &[30]), claim(8, &[40])]).is_err());
    Ok(())
}
