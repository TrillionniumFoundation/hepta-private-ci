//! Small factorized heads over the unchanged, pinned multilingual feature space.
//! Scores rank hypotheses; development calibration is not a population guarantee.

use std::collections::BTreeSet;
use codex_hepta_cognitive_types::{InventoryCellRouteV1, MemoryOperationV1};
use codex_hepta_cognitive_types::hnmf::{ContractDigestV1, ContractIdV1};
use codex_hepta_types::Digest32;
use serde::Deserialize;

pub const INVENTORY_CELL_SEMANTIC_PROFILE_V1: &str = "hepta.memory.inventory-raw-minilm-384.v1";
pub const INVENTORY_CELL_SEMANTIC_ENCODER_V1: &str = "4bff7b22bc544468dca828c404026aaa5d011ce83e305d056c14a24658955faf";
const INTENTS: [&str; 8] = ["semantic", "skill", "compose", "reject:mutation", "reject:external", "reject:prediction", "reject:negation", "reject:other"];
const SHAPES: [&str; 4] = ["policy_tuple", "program", "computed_integer", "unsupported"];

#[derive(Clone, Copy, Deserialize, Eq, PartialEq)]
#[serde(rename_all = "snake_case")]
enum AddressKind { Entity, Workflow }
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Alias { kind: AddressKind, key: ContractIdV1, phrases: Vec<String> }
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct HeadWire {
    schema: String,
    feature_profile: String,
    encoder_digest: ContractDigestV1,
    dimension: usize,
    training_digest: ContractDigestV1,
    calibration_digest: ContractDigestV1,
    intent_labels: Vec<String>,
    shape_labels: Vec<String>,
    intent_weights: Vec<Vec<f32>>,
    intent_bias: Vec<f32>,
    shape_weights: Vec<Vec<f32>>,
    shape_bias: Vec<f32>,
    threshold: f32,
    minimum_margin: f32,
    aliases: Vec<Alias>,
}

/// A bounded inference hypothesis.  No owner values, executable authority,
/// source records or answer lookup table are included in the artifact.
pub struct InventoryCellSemanticHeadV1 {
    digest: ContractDigestV1,
    wire: HeadWire,
}

impl InventoryCellSemanticHeadV1 {
    pub fn from_bytes(bytes: &[u8], expected: Digest32) -> Result<Self, String> {
        if bytes.is_empty() || bytes.len() > 1024 * 1024 || Digest32::of_bytes(bytes) != expected {
            return Err("semantic head byte bound or digest".to_string());
        }
        let mut wire: HeadWire = serde_json::from_slice(bytes).map_err(|error| error.to_string())?;
        if wire.schema != "hepta.memory.inventory-semantic-router.v1"
            || wire.feature_profile != INVENTORY_CELL_SEMANTIC_PROFILE_V1
            || wire.encoder_digest.to_string() != INVENTORY_CELL_SEMANTIC_ENCODER_V1
            || wire.dimension != 384 || !wire.intent_labels.iter().map(String::as_str).eq(INTENTS)
            || !wire.shape_labels.iter().map(String::as_str).eq(SHAPES)
            || !valid_head(&wire.intent_weights, &wire.intent_bias, INTENTS.len())
            || !valid_head(&wire.shape_weights, &wire.shape_bias, SHAPES.len())
            || !wire.threshold.is_finite() || !(0.0..=1.01).contains(&wire.threshold)
            || !wire.minimum_margin.is_finite() || !(0.0..=1.0).contains(&wire.minimum_margin)
            || wire.aliases.is_empty() || wire.aliases.len() > 256
        {
            return Err("semantic head feature, labels, numeric bounds or encoder profile".to_string());
        }
        let mut identities = BTreeSet::new();
        let mut phrases = BTreeSet::new();
        for alias in &mut wire.aliases {
            if alias.phrases.is_empty() || alias.phrases.len() > 8
                || !identities.insert((alias.kind == AddressKind::Workflow, alias.key.clone()))
            {
                return Err("semantic head duplicate or unbounded registry key".to_string());
            }
            for phrase in &mut alias.phrases {
                if !phrase.is_ascii() || phrase.len() > 128 { return Err("semantic alias character profile".to_string()); }
                *phrase = words(phrase).join(" ");
                if phrase.is_empty() || !phrases.insert(phrase.clone()) { return Err("semantic alias is empty or ambiguous".to_string()); }
            }
        }
        Ok(Self { digest: ContractDigestV1::from_digest(expected).map_err(|error| error.to_string())?, wire })
    }

    pub fn model_digest(&self) -> ContractDigestV1 { self.digest }
    pub fn encoder_digest(&self) -> ContractDigestV1 { self.wire.encoder_digest }
    pub fn training_digest(&self) -> ContractDigestV1 { self.wire.training_digest }
    pub fn calibration_digest(&self) -> ContractDigestV1 { self.wire.calibration_digest }

    pub(crate) fn has_valid_addresses(&self, text: &str) -> bool { self.addresses(text).is_some() }

    /// Evaluate a feature vector from the exact pinned raw-text encoder.  The
    /// runtime supplies that vector through its bound worker, never on the wire
    /// from the caller.  This method itself grants no owner or release authority.
    pub fn route_features(&self, text: &str, features: &[f32]) -> Result<Option<InventoryCellRouteV1>, String> {
        let Some((entity, workflow)) = self.addresses(text) else { return Ok(None); };
        if features.len() != 384 || features.iter().any(|value| !value.is_finite()) {
            return Err("semantic head feature shape or finite bound".to_string());
        }
        let squared: f32 = features.iter().map(|value| value * value).sum();
        if (squared - 1.0).abs() > 0.002 { return Err("semantic head features are not L2 normalized".to_string()); }
        let intent = probabilities(&self.wire.intent_weights, &self.wire.intent_bias, features)?;
        let shape = probabilities(&self.wire.shape_weights, &self.wire.shape_bias, features)?;
        let mut scores = [0.0_f32; 4];
        for i in 0..3 { scores[i] = intent[i] * shape[i]; }
        let mut rejection = 0.0_f32;
        for value in &intent[3..] { rejection += value; }
        scores[3] = rejection + shape[3];
        let total: f32 = scores.iter().sum();
        if !total.is_finite() || total <= 0.0 { return Err("semantic head ranking normalization failed".to_string()); }
        for score in &mut scores { *score /= total; }
        let mut order = [0_usize, 1, 2, 3];
        order.sort_by(|a, b| scores[*b].total_cmp(&scores[*a]).then(a.cmp(b)));
        let winner = order[0];
        if winner == 3 || scores[winner] < self.wire.threshold
            || scores[winner] - scores[order[1]] < self.wire.minimum_margin { return Ok(None); }
        let route = InventoryCellRouteV1 {
            operation: [MemoryOperationV1::Semantic, MemoryOperationV1::Procedure, MemoryOperationV1::Apply][winner],
            entity, workflow,
        };
        if route.validate().is_err() { return Ok(None); }
        Ok(Some(route))
    }

    fn addresses(&self, text: &str) -> Option<(Option<ContractIdV1>, Option<ContractIdV1>)> {
        if text.trim().is_empty() || text.len() > 8192 { return None; }
        // This normalization is only for registered-name matching.  The encoder
        // sees the original Unicode text, with no name/date masking or rewriting.
        let normalized = format!(" {} ", words(text).join(" "));
        let mut entities = BTreeSet::new();
        let mut workflows = BTreeSet::new();
        for alias in &self.wire.aliases {
            if alias.phrases.iter().any(|phrase| normalized.contains(&format!(" {phrase} "))) {
                match alias.kind {
                    AddressKind::Entity => { entities.insert(alias.key.clone()); }
                    AddressKind::Workflow => { workflows.insert(alias.key.clone()); }
                }
            }
        }
        if entities.len() > 1 || workflows.len() > 1 || (entities.is_empty() && workflows.is_empty()) { return None; }
        Some((entities.into_iter().next(), workflows.into_iter().next()))
    }
}

fn valid_head(weights: &[Vec<f32>], bias: &[f32], labels: usize) -> bool {
    weights.len() == labels && bias.len() == labels && bias.iter().all(|value| value.is_finite())
        && weights.iter().all(|row| row.len() == 384 && row.iter().all(|value| value.is_finite()))
}
fn probabilities(weights: &[Vec<f32>], bias: &[f32], features: &[f32]) -> Result<Vec<f32>, String> {
    let mut logits = bias.to_vec();
    for (logit, row) in logits.iter_mut().zip(weights) {
        let mut sum = 0.0_f32;
        for (weight, feature) in row.iter().zip(features) { sum += weight * feature; }
        *logit += sum;
    }
    if logits.iter().any(|value| !value.is_finite()) { return Err("semantic head nonfinite logits".to_string()); }
    let highest = logits.iter().copied().fold(f32::NEG_INFINITY, f32::max);
    let mut scores: Vec<_> = logits.iter().map(|value| (*value - highest).exp()).collect();
    let total: f32 = scores.iter().sum();
    for score in &mut scores { *score /= total; }
    Ok(scores)
}
fn words(text: &str) -> Vec<String> {
    text.split(|character: char| !character.is_ascii_alphanumeric() && character != '_')
        .filter(|word| !word.is_empty()).map(str::to_ascii_lowercase).collect()
}
