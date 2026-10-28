//! Checks backed by real forward bytes and the actual withdrawal owner.
use super::*;

fn bytes(value: &Value) -> TestResult<Vec<u8>> {
    let text = value.as_str().ok_or("hex byte string")?;
    if text.len() > 256 * 1024 || !text.len().is_multiple_of(2) || !text.is_ascii() {
        return Err("bounded complete bytes required".into());
    }
    (0..text.len())
        .step_by(2)
        .map(|offset| Ok(u8::from_str_radix(&text[offset..offset + 2], 16)?))
        .collect()
}

pub(super) fn choice(
    task: &Value,
    row: &Value,
    actions: &[StableId; 2],
    model: &Value,
    start: u64,
    end: u64,
) -> TestResult<usize> {
    let request = bytes(&row["request_bytes_hex"])?;
    let response = bytes(&row["response_bytes_hex"])?;
    let expected = json!({"schema":"hepta-smollm-inference-input-v1","request_id":task["id"],"prompt":task["prompt"]});
    let actual: Value = serde_json::from_slice(&response)?;
    let at = row["decision_at"].as_u64().ok_or("actual query start")?;
    let observed = row["observed_at"].as_u64().ok_or("actual query end")?;
    if serde_json::from_slice::<Value>(&request)? != expected
        || actual != row["response"]
        || row["task"] != task["id"]
        || row["query_sha256"]
            != Digest32::of_bytes(task["prompt"].as_str().ok_or("prompt")?.as_bytes()).to_string()
        || row["response_sha256"] != Digest32::of_bytes(&response).to_string()
        || actual["input_sha256"] != Digest32::of_bytes(&request).to_string()
        || actual["request_id"] != task["id"]
        || actual["file_sha256"] != model["file_sha256"]
        || actual["artifact"] != model["adapter"]
        || actual["contract"] != model["contract"]
        || actual["profile"] != "hepta-smollm-single-token-action-score-v1"
        || actual["action_ids"] != json!(actions.iter().map(StableId::as_str).collect::<Vec<_>>())
        || actual["authority"]
            != json!({"installation_authorized":false,"selection_authorized":false,
            "independent_accepted":false,"prospective_accepted":false,"public_reward_eligible":false,"hepta_final_use":false})
        || at < start
        || observed < at
        || observed > end
    {
        return Err("actual model/query/response bytes or observed time changed".into());
    }
    let scores = actual["scores_q32"].as_array().ok_or("actual logits")?;
    if scores.len() != 2 {
        return Err("two original action logits required".into());
    }
    Ok(usize::from(
        scores[1].as_i64().ok_or("logit")? > scores[0].as_i64().ok_or("logit")?,
    ))
}

pub(super) fn retention(root: &Path, rows: &[Value], study: &Value) -> TestResult<Vec<Digest32>> {
    let mut receipts = Vec::new();
    for family in ["integer-comparison", "uppercase"] {
        let selected = rows
            .iter()
            .filter(|row| row["family"] == family)
            .collect::<Vec<_>>();
        let parent = selected
            .iter()
            .filter(|row| row["parent_correct"] == true)
            .count();
        let child = selected
            .iter()
            .filter(|row| row["child_correct"] == true)
            .count();
        let passed = selected.len() == 512 && child >= parent;
        let receipt = save(
            &root.join(format!("retention-{family}.json")),
            &json!({
            "schema":"hepta-neural-study-observed-family-retention-v1","study":study,"family":family,
            "observations":selected,"parent_correct":parent,"child_correct":child,"passed":passed,
            "rule":"512 actual future observations per original training family; child_correct >= parent_correct",
            "claim_scope":"finite observed no-degradation gate; no population noninferiority or external retention claim"}),
        )?;
        if !passed {
            return Err(
                format!("actual {family} retention gate rejected child; no installation").into(),
            );
        }
        receipts.push(
            receipt["sha256"]
                .as_str()
                .ok_or("actual retention digest")?
                .parse()?,
        );
    }
    Ok(receipts)
}

pub(super) fn withdrawal(
    root: &Path,
    registry: &DatasetWithdrawalRegistry,
    dataset: &ledger::DatasetSnapshotReceiptV3,
    trained: &Value,
) -> TestResult<Digest32> {
    let snapshot = registry.snapshot();
    let recovered = DatasetWithdrawalRegistry::from_snapshot(snapshot.clone())?;
    let scope = snapshot
        .scope()
        .ok_or("scoped actual withdrawal owner required")?;
    let source = dataset.snapshot.dataset_digest;
    let binding = read_pin(&trained["training_data"])?;
    if recovered.snapshot() != snapshot
        || snapshot.scope_digest() != registry.scope_digest()
        || snapshot.head_digest != registry.head_digest()
        || !snapshot.records().is_empty()
        || recovered.is_withdrawn(source)
        || registry.is_withdrawn(source)
        || binding["source_dataset_digest"] != source.to_string()
        || trained["source_dataset_digest"] != source.to_string()
    {
        return Err("live withdrawal registry or actual source dataset check failed".into());
    }
    let receipt = save(
        &root.join("withdrawal-source-check.json"),
        &json!({
        "schema":"hepta-neural-study-actual-withdrawal-source-check-v1","checked_unix_micros":now(),
        "scope":{"authority_domain_id":scope.authority_domain_id.as_str(),"registry_id":scope.registry_id.as_str(),"scope_id":scope.scope_id.as_str()},
        "scope_digest":scope.digest().to_string(),"head_digest":snapshot.head_digest.to_string(),
        "record_count":snapshot.records().len(),"source_dataset_checks":[{"dataset_digest":source.to_string(),"is_withdrawn":false}],
        "snapshot_roundtrip_equal":true,"training_data":trained["training_data"],"training_consumption":trained["training_consumption"],
        "claim_scope":"actual empty scoped registry has no active withdrawal obligation for the exact consumed dataset; no removed-data unlearning efficacy claim",
        "installation_authority":false}),
    )?;
    Ok(receipt["sha256"]
        .as_str()
        .ok_or("checked withdrawal receipt digest")?
        .parse()?)
}
