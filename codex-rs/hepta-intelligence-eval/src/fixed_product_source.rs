//! Adapt an authenticated, label-free source batch to the native complete graph.
//! Archive years and filesystem timestamps never become prediction times.
use crate::FrozenTaskSourceLineageV1;
use crate::TaskSourceRecordV1;
use crate::TaskSourceScopeV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use serde::Deserialize;
use std::collections::BTreeMap;
use std::collections::BTreeSet;

type HostResult<T> = Result<T, Box<dyn std::error::Error>>;
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Batch {
    schema: String,
    batch_id: String,
    source_archive_digest: String,
    source_pairs_digest: String,
    task_template_digest: String,
    task_sources: Vec<Task>,
    rows: Vec<Row>,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Task {
    claim_id: u64,
    cited_doc_ids: Vec<u64>,
    source_claim_file_digest: String,
    source_claim_row_1based: u64,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Row {
    row_id: String,
    claim_id: u64,
    doc_id: u64,
    source_record_digest: String,
    prompt: String,
    prompt_digest: String,
}
/// Does not authenticate raw source bytes: the host must open the frozen Root
/// batch with its expected SHA and protected-ancestor/inode checks first.
pub(crate) fn frozen_source_graph(
    bytes: &[u8],
    objective: Digest32,
) -> HostResult<(FrozenTaskSourceLineageV1, usize, usize)> {
    if bytes.len() > 16 * 1024 * 1024 || objective.is_zero() {
        return Err("bounded masked source/objective".into());
    }
    let batch: Batch = serde_json::from_slice(bytes)?;
    if batch.schema != "hepta.masked-calibration-reference-batch.v1"
        || batch.task_sources.is_empty()
        || batch.task_sources.len() > 100_000
        || batch.rows.is_empty()
        || batch.rows.len() > 100_000
        || batch.source_pairs_digest.parse::<Digest32>()?.is_zero()
    {
        return Err("masked source schema/count/pins".into());
    }
    StableId::new(batch.batch_id)?;
    let scope = TaskSourceScopeV1 {
        objective_digest: objective,
        task_definition_digest: batch.task_template_digest.parse()?,
        source_archive_digest: batch.source_archive_digest.parse()?,
    };
    let mut tasks = BTreeMap::new();
    let mut records = Vec::new();
    for task in &batch.task_sources {
        if task.cited_doc_ids.is_empty()
            || task.cited_doc_ids.len() > 128
            || tasks.insert(task.claim_id, task).is_some()
        {
            return Err("complete unique source tasks required".into());
        }
        let dependencies = task
            .cited_doc_ids
            .iter()
            .map(|doc| StableId::new(format!("scifact.document.{doc}")))
            .collect::<Result<Vec<_>, _>>()?;
        let file: Digest32 = task.source_claim_file_digest.parse()?;
        // This is the canonical masked dependency node, not the original gold
        // claim's content digest. The archive/file/row provenance remains exact.
        let mut node = b"hepta.eval.masked-source-dependency-node.v1".to_vec();
        node.extend_from_slice(scope.source_archive_digest.as_array());
        node.extend_from_slice(file.as_array());
        node.extend_from_slice(&task.source_claim_row_1based.to_be_bytes());
        node.extend_from_slice(&task.claim_id.to_be_bytes());
        let mut ids = task.cited_doc_ids.clone();
        ids.sort_unstable();
        node.extend_from_slice(&(ids.len() as u32).to_be_bytes());
        for doc in ids {
            node.extend_from_slice(&doc.to_be_bytes());
        }
        records.push(TaskSourceRecordV1 {
            source_file_digest: file,
            source_row_index: task.source_claim_row_1based,
            source_record_digest: Digest32::of_bytes(&node),
            task_id: StableId::new(format!("scifact.claim.{}", task.claim_id))?,
            dependency_ids: dependencies,
        });
    }
    let mut rows = BTreeSet::new();
    for row in &batch.rows {
        let task = tasks
            .get(&row.claim_id)
            .ok_or("scored task absent from complete graph")?;
        if !task.cited_doc_ids.contains(&row.doc_id)
            || !rows.insert(StableId::new(row.row_id.clone())?)
            || row.prompt.len() > 256 * 1024
            || row.prompt.is_empty()
            || Digest32::of_bytes(row.prompt.as_bytes()) != row.prompt_digest.parse::<Digest32>()?
        {
            return Err("scored pair/source/prompt binding".into());
        }
        records.push(TaskSourceRecordV1 {
            source_file_digest: task.source_claim_file_digest.parse()?,
            source_row_index: task.source_claim_row_1based,
            source_record_digest: row.source_record_digest.parse()?,
            task_id: StableId::new(format!("scifact.claim.{}", row.claim_id))?,
            dependency_ids: task
                .cited_doc_ids
                .iter()
                .map(|doc| StableId::new(format!("scifact.document.{doc}")))
                .collect::<Result<Vec<_>, _>>()?,
        });
    }
    Ok((
        FrozenTaskSourceLineageV1::freeze(&scope, &records)?,
        tasks.len(),
        rows.len(),
    ))
}
#[cfg(test)]
#[path = "fixed_product_source_tests.rs"]
mod tests;
