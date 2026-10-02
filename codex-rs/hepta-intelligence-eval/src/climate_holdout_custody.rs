//! Import the Root-frozen feature cut into the existing fenced gold custody.
//! No evaluator, label-conditioned selection, new CAS format or authority is
//! introduced. Preparation is separate from registering or consuming a cohort.
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
use serde_json::Value;
use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::path::Path;
use std::path::PathBuf;

const ORIGINAL_SOURCE: &str = "8a4b9032d861be482ffb49dddfd283ffa6089e654f1e968040011882c5eb6e0b";
const PREVIEW: &str = "8c5322d863be6c1a184ebb23b7764ad2881120ca80f9dd46ccb8f408c7f8e0ed";
const COMPARISON: &str = "4ae450750faebb7b9ed74423683eb17cfecfa7834f9f418c329c7969f95fe96e";

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Config {
    schema: String,
    program_digest: String,
    source: Source,
    feature_cut: Source,
    feature_adapter_program: Source,
    private_directory: PathBuf,
    witness_path: PathBuf,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct FeatureCut {
    schema: String,
    source_digest: String,
    adapter_program_digest: String,
    preview_program_digest: String,
    comparison_program_digest: String,
    known_feature_inventory_digest: String,
    original_source_pins: BTreeMap<String, String>,
    known_feature_records: usize,
    public_health_source_pins: BTreeMap<String, String>,
    public_scifact_footprint_digest: String,
    normalization: String,
    public_example_claim_ids: Vec<String>,
    components: Vec<Vec<String>>,
    source_claims: usize,
    source_evidence_rows: usize,
    annotation_values_used: bool,
    #[serde(rename = "old_gold_keys_CAS_opened")]
    old_gold_keys_cas_opened: bool,
}

impl FeatureCut {
    fn validate(&self, adapter: Digest32) -> HostResult<()> {
        if self.schema != "hepta.climate-fever.feature-cut.v1"
            || self.source_digest != ORIGINAL_SOURCE
            || digest(&self.adapter_program_digest)? != adapter
            || self.preview_program_digest != PREVIEW
            || self.comparison_program_digest != COMPARISON
            || self.source_claims != 1535
            || self.source_evidence_rows != 7675
            || self.annotation_values_used
            || self.old_gold_keys_cas_opened
            || self.public_example_claim_ids != ["0"]
            || self.normalization
                != "NFC/casefold/canonical-whitespace; article underscores equal spaces"
            || !(1..=24000).contains(&self.known_feature_records)
            || self.components.is_empty()
            || self.components.len() > self.source_claims
        {
            return Err("original complete feature-only Climate cut required".into());
        }
        let historical = [
            "masked72_sha256",
            "source99_sha256",
            "config72_sha256",
            "witness72_sha256",
            "initialize99_sha256",
        ];
        if self
            .original_source_pins
            .keys()
            .map(String::as_str)
            .collect::<BTreeSet<_>>()
            != historical.into_iter().collect()
            || self
                .public_health_source_pins
                .keys()
                .map(String::as_str)
                .collect::<BTreeSet<_>>()
                != ["train", "dev", "test"].into_iter().collect()
        {
            return Err("complete original feature provenance required".into());
        }
        for value in self
            .original_source_pins
            .values()
            .chain(self.public_health_source_pins.values())
            .chain([
                &self.known_feature_inventory_digest,
                &self.public_scifact_footprint_digest,
            ])
        {
            if digest(value)?.is_zero() {
                return Err("feature provenance digest".into());
            }
        }
        let mut used = BTreeSet::new();
        let mut previous = None;
        for component in &self.components {
            if component.is_empty()
                || component.len() > self.source_claims
                || previous.is_some_and(|prior| prior >= component)
            {
                return Err("canonical complete feature components".into());
            }
            previous = Some(component);
            let mut last = None;
            for id in component {
                if id == "0"
                    || id.is_empty()
                    || id.len() > 256
                    || last.is_some_and(|prior| prior >= id)
                    || !used.insert(id)
                {
                    return Err("duplicate or public example component membership".into());
                }
                last = Some(id);
            }
        }
        Ok(())
    }
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct ClimateRow {
    claim_id: String,
    claim: String,
    // Aggregate DISPUTED and claim-level labels are never mapped to gold.
    #[serde(rename = "claim_label")]
    _claim_label: Value,
    evidences: Vec<Evidence>,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Evidence {
    evidence_id: String,
    evidence_label: String,
    article: String,
    evidence: String,
    #[serde(rename = "entropy")]
    _entropy: Value,
    #[serde(rename = "votes")]
    _votes: Value,
}

struct Prepared {
    gold: Vec<u8>,
    masked: Vec<u8>,
    counts: PreparedHoldoutCounts,
}

fn prepare(raw: &[u8], cut_bytes: &[u8], cut: &FeatureCut) -> HostResult<Prepared> {
    let mut claims = BTreeMap::new();
    let mut evidence_ids = BTreeSet::new();
    for line in std::str::from_utf8(raw)?.lines() {
        let row: ClimateRow = serde_json::from_str(line)?;
        if row.claim_id.is_empty()
            || row.claim_id.len() > 256
            || row.claim.trim().is_empty()
            || row.claim.len() > 32768
            || row.evidences.len() != 5
        {
            return Err("complete bounded original Climate source row".into());
        }
        for evidence in &row.evidences {
            if evidence.evidence_id.is_empty()
                || evidence.evidence_id.len() > 256
                || !evidence_ids.insert((row.claim_id.clone(), evidence.evidence_id.clone()))
                || evidence.article.trim().is_empty()
                || evidence.article.len() > 32768
                || evidence.evidence.trim().is_empty()
                || evidence.evidence.len() > 32768
            {
                return Err("original Climate evidence identity or features".into());
            }
        }
        let identity = row.claim_id.clone();
        if claims
            .insert(identity, (row, Digest32::of_bytes(line.as_bytes())))
            .is_some()
        {
            return Err("duplicate original Climate claim".into());
        }
        if claims.len() > cut.source_claims {
            return Err("Climate source bound".into());
        }
    }
    if claims.len() != cut.source_claims || evidence_ids.len() != cut.source_evidence_rows {
        return Err("complete original Climate source count".into());
    }
    let mut tasks = Vec::new();
    let mut features = Vec::new();
    let mut neutral = 0;
    for component in &cut.components {
        for id in component {
            let (claim, claim_digest) = claims
                .get(id)
                .ok_or("feature cut contains unknown source claim")?;
            for evidence in &claim.evidences {
                let feature = serde_json::json!({
                    "source_schema":"climate-fever.official-evidence.v1", "claim_id":claim.claim_id,
                    "evidence_id":evidence.evidence_id, "claim_text":claim.claim,
                    "title":evidence.article, "abstract_sentences":[evidence.evidence],
                    "claim_source_record_digest":claim_digest.to_string(),
                    "source_component_claim_ids":component,
                });
                features.push(feature.clone());
                let gold = match evidence.evidence_label.as_str() {
                    "SUPPORTS" => "SUPPORT",
                    "REFUTES" => "CONTRADICT",
                    "NOT_ENOUGH_INFO" => {
                        neutral += 1;
                        continue;
                    }
                    _ => return Err("unknown original per-evidence gold label".into()),
                };
                tasks.push(serde_json::json!({"features":feature,"gold":gold,
                    "original_evidence_label":evidence.evidence_label}));
            }
        }
    }
    if tasks.is_empty() {
        return Err("no genuinely disjoint per-evidence binary gold remains".into());
    }
    let eligible_claims = cut.components.iter().map(Vec::len).sum();
    let gold = serde_json::to_vec(&serde_json::json!({
        "schema":"hepta.source-pinned-private-gold.v1", "source_archive_digest":ORIGINAL_SOURCE,
        "feature_cut_digest":Digest32::of_bytes(cut_bytes).to_string(),"tasks":tasks,
        "scope":"Locally unused Climate-FEVER claim/evidence binary classification; neutral evidence excluded from scoring after complete component selection; no pretraining-unseen, superiority or longitudinal claim",
    }))?;
    Ok(Prepared {
        gold,
        masked: serde_json::to_vec(&features)?,
        counts: PreparedHoldoutCounts {
            eligible_claims,
            eligible_components: cut.components.len(),
            labeled_pairs: tasks.len(),
            excluded_shared_claims: claims.len() - eligible_claims,
            unjudged_pairs_not_scored: neutral,
        },
    })
}

fn config(path: &Path) -> HostResult<(Config, Digest32, Vec<u8>, FeatureCut)> {
    boundary()?;
    let bytes = read_root_review_input(path, 16 * 1024)?;
    let config: Config = serde_json::from_slice(&bytes)?;
    if config.schema != "hepta.fixed-climate-holdout.config.v1"
        || config.source.digest != ORIGINAL_SOURCE
        || Digest32::of_bytes(&read_root_review_input(
            &std::env::current_exe()?,
            128 * 1024 * 1024,
        )?) != digest(&config.program_digest)?
    {
        return Err("original Climate custody program/source pin".into());
    }
    private_directory(&config.private_directory)?;
    private_directory(config.witness_path.parent().ok_or("witness parent")?)?;
    if config.witness_path.parent() == Some(config.private_directory.as_path()) {
        return Err("Climate witness requires an independently retained directory".into());
    }
    let adapter = source(&config.feature_adapter_program, 65536)?;
    let cut_bytes = source(&config.feature_cut, 1024 * 1024)?;
    let cut: FeatureCut = serde_json::from_slice(&cut_bytes)?;
    cut.validate(Digest32::of_bytes(&adapter))?;
    Ok((config, Digest32::of_bytes(&bytes), cut_bytes, cut))
}

pub fn prepare_climate_source_holdout(path: &Path) -> HostResult<()> {
    let (config, config_digest, cut_bytes, cut) = config(path)?;
    let prepared = prepare(&source(&config.source, 16 * 1024 * 1024)?, &cut_bytes, &cut)?;
    initialize_private_holdout(
        &config.private_directory,
        &config.witness_path,
        config_digest,
        &prepared.gold,
        &prepared.masked,
        prepared.counts,
    )
}

pub fn inspect_climate_source_holdout(path: &Path) -> HostResult<()> {
    let (config, config_digest, _, _) = config(path)?;
    inspect_private_holdout(
        &config.private_directory,
        &config.witness_path,
        config_digest,
    )
}

#[cfg(test)]
#[path = "climate_holdout_custody_tests.rs"]
mod tests;
