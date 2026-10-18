//! Adapt a previously frozen public development task subset into original custody.
//! This is repeated public scoring, never an unseen or complete binary cohort.
use crate::fixed_holdout_custody::HostResult;
use crate::fixed_holdout_custody::PreparedHoldoutCounts;
use crate::fixed_holdout_custody::Source;
use crate::fixed_holdout_custody::boundary;
use crate::fixed_holdout_custody::digest;
use crate::fixed_holdout_custody::initialize_private_holdout;
use crate::fixed_holdout_custody::inspect_private_holdout;
use crate::fixed_holdout_custody::private_directory;
use crate::fixed_holdout_custody::source;
use codex_hepta_learning_ledger::read_root_review_input;
use codex_hepta_types::Digest32;
use serde::Deserialize;
use serde::Serialize;
use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::path::Path;
use std::path::PathBuf;

const CALIBRATION: &str = "da7bd98b34236c432abf4de791863db1f65624205db8fe5f4493a5558a892732";
const MEMBERSHIP: &str = "ed5b089cacf7a33d59cf78f326f25ebc29d03929b734a56459d61e7bb8ab2c4e";
const GRAPH: &str = "5d3935a0da31bd13a959c3858c9d9cf92fea2089495a3902e90061743a97e080";
const TRAIN: &str = "57668949f79d0f46e66d74df4b0bc9812cad4d5ad7c5dd03dfba008a608b3f2a";

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Config {
    schema: String,
    program_digest: String,
    calibration: Source,
    feature_membership: Source,
    complete_feature_graph: Source,
    private_directory: PathBuf,
    witness_path: PathBuf,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct CalibrationRow {
    source: String,
    source_commit: String,
    source_split: String,
    source_file_sha256: String,
    source_row_1based: u64,
    upstream_id: String,
    claim_text: String,
    evidence_text: String,
    topic_sha256: String,
    question_sha256: String,
    normalized_claim_sha256: String,
    normalized_evidence_sha256: String,
    original_row_sha256: String,
    row_sha256: String,
    component_sha256: String,
    partition: String,
    gold: String,
}
#[derive(Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct Feature {
    domain: String,
    source: String,
    source_split: String,
    source_row_1based: u64,
    upstream_id: String,
    claim_text: String,
    evidence_text: String,
    topic: String,
    question: String,
}
impl Feature {
    fn pair_id(&self) -> String {
        format!("healthver:{}:{}", self.source_split, self.source_row_1based)
    }
    fn digest(&self) -> HostResult<Digest32> {
        // Value uses the canonical sorted map, matching the original feature
        // preimage, independently of Rust struct declaration order.
        Ok(Digest32::of_bytes(&serde_json::to_vec(
            &serde_json::to_value(self)?,
        )?))
    }
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct GraphRow {
    feature: Feature,
    feature_digest: String,
    component_digest: String,
    claim_feature_digest: String,
    evidence_feature_digest: String,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Member {
    pair_id: String,
    feature_digest: String,
    component_digest: String,
    partition: String,
}
struct Prepared {
    gold: Vec<u8>,
    masked: Vec<u8>,
    counts: PreparedHoldoutCounts,
}
fn prepare(calibration: &[u8], membership_bytes: &[u8], graph: &[u8]) -> HostResult<Prepared> {
    let mut labels = BTreeMap::new();
    for line in std::str::from_utf8(calibration)?.lines() {
        let row: CalibrationRow = serde_json::from_str(line)?;
        if row.source != "HealthVer"
            || row.source_commit != "b20ac99ceed62f5264a319fa25a854df1668d85b"
            || row.source_split != "train"
            || row.source_file_sha256 != TRAIN
            || row.source_row_1based < 2
            || row.partition != "calibration"
            || !matches!(row.gold.as_str(), "SUPPORT" | "CONTRADICT")
            || row.claim_text.trim().is_empty()
            || row.evidence_text.trim().is_empty()
            || labels.len() >= 24000
        {
            return Err("original public binary training-calibration source required".into());
        }
        for pin in [
            &row.topic_sha256,
            &row.question_sha256,
            &row.normalized_claim_sha256,
            &row.normalized_evidence_sha256,
            &row.original_row_sha256,
            &row.row_sha256,
            &row.component_sha256,
        ] {
            if digest(pin)?.is_zero() {
                return Err("original public source provenance".into());
            }
        }
        let id = format!("healthver:train:{}", row.source_row_1based);
        if labels.insert(id, row).is_some() {
            return Err("duplicate original public task".into());
        }
    }
    let graph: Vec<GraphRow> = serde_json::from_slice(graph)?;
    let membership: Vec<Member> = serde_json::from_slice(membership_bytes)?;
    if graph.is_empty() || graph.len() > 24000 || membership.is_empty() || membership.len() > 24000
    {
        return Err("complete bounded public feature graph/membership".into());
    }
    let mut features = BTreeMap::new();
    for row in graph {
        if row.feature.domain != "hepta.healthver.public-feature-record.v1"
            || row.feature.source != "HealthVer"
            || !matches!(row.feature.source_split.as_str(), "train" | "dev")
            || row.feature.source_row_1based < 2
            || row.feature.claim_text.trim().is_empty()
            || row.feature.evidence_text.trim().is_empty()
            || row.feature.digest()? != digest(&row.feature_digest)?
            || digest(&row.component_digest)?.is_zero()
            || digest(&row.claim_feature_digest)?.is_zero()
            || digest(&row.evidence_feature_digest)?.is_zero()
        {
            return Err("original annotation-free feature graph changed".into());
        }
        if features.insert(row.feature.pair_id(), row).is_some() {
            return Err("duplicate complete feature graph row".into());
        }
    }
    let mut tasks = Vec::new();
    let mut components = BTreeSet::new();
    let mut partitions = BTreeMap::new();
    let mut seen = BTreeSet::new();
    for member in membership {
        let row = features
            .get(&member.pair_id)
            .ok_or("public member missing from complete graph")?;
        let label = labels
            .get(&member.pair_id)
            .ok_or("not an original public train binary task")?;
        if !seen.insert(member.pair_id.clone())
            || member.feature_digest != row.feature_digest
            || member.component_digest != row.component_digest
            || label.component_sha256 != row.component_digest
            || label.upstream_id != row.feature.upstream_id
            || label.claim_text != row.feature.claim_text
            || label.evidence_text != row.feature.evidence_text
            || !matches!(
                member.partition.as_str(),
                "final-public-development" | "prior-public-calibration"
            )
            || partitions
                .get(&member.component_digest)
                .is_some_and(|p| p != &member.partition)
        {
            return Err("original public subset/components changed".into());
        }
        partitions.insert(member.component_digest.clone(), member.partition.clone());
        if member.partition == "final-public-development" {
            components.insert(member.component_digest);
            tasks.push(serde_json::json!({"features":row.feature,"gold":label.gold}));
        }
    }
    if tasks.is_empty() {
        return Err("no predeclared public development tasks".into());
    }
    // Preserve all selected-component features, including neutral and dev
    // bridge rows. They do not become fake predictions or extra scored tasks.
    let complete_features: Vec<_> = features
        .values()
        .filter(|row| components.contains(&row.component_digest))
        .map(|row| &row.feature)
        .collect();
    let masked = serde_json::to_vec(&complete_features)?;
    let gold = serde_json::to_vec(&serde_json::json!({
        "schema":"hepta.source-pinned-private-gold.v1",
        "source_calibration_digest":Digest32::of_bytes(calibration).to_string(),
        "feature_membership_digest":Digest32::of_bytes(membership_bytes).to_string(),
        "unscored_component_feature_rows":complete_features.len()-tasks.len(),
        "scope":"Repeated public HealthVer train task subset; full component feature lineage includes unscored neutral/dev rows. Not an unseen, complete binary cohort, superiority or model-upgrade claim.",
        "tasks":tasks,
    }))?;
    Ok(Prepared {
        gold,
        masked,
        counts: PreparedHoldoutCounts {
            eligible_claims: complete_features.len(),
            eligible_components: components.len(),
            labeled_pairs: tasks.len(),
            excluded_shared_claims: features.len() - complete_features.len(),
            unjudged_pairs_not_scored: 0,
        },
    })
}
fn config(path: &Path) -> HostResult<(Config, Digest32)> {
    boundary()?;
    let bytes = read_root_review_input(path, 16 * 1024)?;
    let config: Config = serde_json::from_slice(&bytes)?;
    if config.schema != "hepta.fixed-public-development-custody.config.v1"
        || config.calibration.digest != CALIBRATION
        || config.feature_membership.digest != MEMBERSHIP
        || config.complete_feature_graph.digest != GRAPH
        || Digest32::of_bytes(&read_root_review_input(
            &std::env::current_exe()?,
            128 * 1024 * 1024,
        )?) != digest(&config.program_digest)?
    {
        return Err("original public development source/program pins required".into());
    }
    private_directory(&config.private_directory)?;
    private_directory(config.witness_path.parent().ok_or("witness parent")?)?;
    if config.witness_path.parent() == Some(config.private_directory.as_path()) {
        return Err("public development witness must be independently retained".into());
    }
    Ok((config, Digest32::of_bytes(&bytes)))
}
pub fn prepare_public_development_custody(path: &Path) -> HostResult<()> {
    let (config, config_digest) = config(path)?;
    let prepared = prepare(
        &source(&config.calibration, 16 * 1024 * 1024)?,
        &source(&config.feature_membership, 1024 * 1024)?,
        &source(&config.complete_feature_graph, 32 * 1024 * 1024)?,
    )?;
    initialize_private_holdout(
        &config.private_directory,
        &config.witness_path,
        config_digest,
        &prepared.gold,
        &prepared.masked,
        prepared.counts,
    )
}
pub fn inspect_public_development_custody(path: &Path) -> HostResult<()> {
    let (config, config_digest) = config(path)?;
    inspect_private_holdout(
        &config.private_directory,
        &config.witness_path,
        config_digest,
    )
}

#[cfg(test)]
#[path = "public_development_custody_tests.rs"]
mod tests;
