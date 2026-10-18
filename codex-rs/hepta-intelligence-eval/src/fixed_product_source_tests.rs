use super::*;
fn batch() -> serde_json::Value {
    let digest = Digest32::of_bytes(b"source").to_string();
    serde_json::json!({"schema":"hepta.masked-calibration-reference-batch.v1","batch_id":"batch",
        "source_archive_digest":digest,"source_pairs_digest":digest,"task_template_digest":digest,
        "task_sources":[
            {"claim_id":1,"cited_doc_ids":[11],"source_claim_file_digest":digest,"source_claim_row_1based":1},
            {"claim_id":2,"cited_doc_ids":[11,12],"source_claim_file_digest":digest,"source_claim_row_1based":2},
            {"claim_id":3,"cited_doc_ids":[12],"source_claim_file_digest":digest,"source_claim_row_1based":3}],
        "rows":[{"row_id":"row","claim_id":1,"doc_id":11,"source_record_digest":Digest32::of_bytes(b"actual source pair").to_string(),
            "prompt":"actual prompt","prompt_digest":Digest32::of_bytes(b"actual prompt").to_string()}]})
}
#[test]
fn product_source_graph_binds_unscored_bridge_and_actual_prompt() -> HostResult<()> {
    let batch = batch();
    let objective = Digest32::of_bytes(b"objective");
    let (full, tasks, rows) = frozen_source_graph(&serde_json::to_vec(&batch)?, objective)?;
    assert_eq!((tasks, rows), (3, 1));
    let mut absent = batch.clone();
    absent["task_sources"]
        .as_array_mut()
        .ok_or("sources")?
        .remove(1);
    let (partial, _, _) = frozen_source_graph(&serde_json::to_vec(&absent)?, objective)?;
    assert_ne!(full.source_graph_digest(), partial.source_graph_digest());
    let mut changed = batch;
    changed["rows"][0]["prompt"] = serde_json::json!("changed prompt");
    assert!(frozen_source_graph(&serde_json::to_vec(&changed)?, objective).is_err());
    Ok(())
}
#[test]
fn product_source_graph_rejects_missing_citation_duplicate_task_and_injected_gold() -> HostResult<()>
{
    let objective = Digest32::of_bytes(b"objective");
    let mut missing = batch();
    missing["rows"][0]["doc_id"] = serde_json::json!(999);
    assert!(frozen_source_graph(&serde_json::to_vec(&missing)?, objective).is_err());
    let mut duplicate = batch();
    let repeated = duplicate["task_sources"][0].clone();
    duplicate["task_sources"]
        .as_array_mut()
        .ok_or("sources")?
        .push(repeated);
    assert!(frozen_source_graph(&serde_json::to_vec(&duplicate)?, objective).is_err());
    let mut gold = batch();
    gold["rows"][0]["gold"] = serde_json::json!("SUPPORT");
    assert!(frozen_source_graph(&serde_json::to_vec(&gold)?, objective).is_err());
    Ok(())
}
