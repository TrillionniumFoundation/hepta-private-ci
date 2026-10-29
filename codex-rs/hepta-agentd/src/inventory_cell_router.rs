//! Native learned role routing with exact, independently keyed name bindings.
//! This bounded English inventory profile has no open-world language claim.

use std::collections::BTreeSet;
use std::future::Future;
use std::pin::Pin;
use codex_hepta_cognitive_types::{InventoryCellKindV1, InventoryCellRequestV1, InventoryCellRouteV1, MemoryOperationV1};
use codex_hepta_cognitive_types::hnmf::{ContractDigestV1, ContractIdV1};
use codex_hepta_memory::InventoryCellOwnerSnapshotV1;
use codex_hepta_types::Digest32;
use serde::Deserialize;
use crate::{InventoryCellAddressResolverV1, InventoryCellResolvedAddressV1};

pub const INVENTORY_CELL_TEXT_PROFILE_V1: &str = "hepta.memory.ascii-words-ngrams-sha256-l2.v1";
const DIMENSION: usize = 2048;

#[derive(Clone, Copy, Deserialize, Eq, PartialEq)]
#[serde(rename_all = "snake_case")]
enum AddressKind { Entity, Workflow }
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Alias {
    kind: AddressKind,
    key: ContractIdV1,
    phrases: Vec<String>,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct RouterWire {
    schema: String,
    feature_profile: String,
    dimension: usize,
    training_digest: ContractDigestV1,
    calibration_digest: ContractDigestV1,
    weights: Vec<Vec<f32>>,
    bias: Vec<f32>,
    threshold: f32,
    minimum_margin: f32,
    aliases: Vec<Alias>,
}

/// A pinned local addressing model, not a source or execution authority. Learned
/// role weights contain no policy values; aliases contain only names and keys.
pub struct InventoryCellTextRouterV1 {
    digest: ContractDigestV1,
    wire: RouterWire,
}

impl InventoryCellTextRouterV1 {
    pub fn from_bytes(bytes: &[u8], expected: Digest32) -> Result<Self, String> {
        if bytes.is_empty() || bytes.len() > 1024 * 1024 || Digest32::of_bytes(bytes) != expected {
            return Err("inventory router byte bound or digest".to_string());
        }
        let mut wire: RouterWire = serde_json::from_slice(bytes).map_err(|error| error.to_string())?;
        if wire.schema != "hepta.memory.inventory-text-router.v1" || wire.feature_profile != INVENTORY_CELL_TEXT_PROFILE_V1
            || wire.dimension != DIMENSION || wire.weights.len() != 4 || wire.bias.len() != 4
            || wire.weights.iter().any(|row| row.len() != DIMENSION || row.iter().any(|value| !value.is_finite()))
            || wire.bias.iter().any(|value| !value.is_finite())
            || !wire.threshold.is_finite() || !(0.0..=1.1).contains(&wire.threshold)
            || !wire.minimum_margin.is_finite() || !(0.0..=1.0).contains(&wire.minimum_margin)
            || wire.aliases.is_empty() || wire.aliases.len() > 256
        {
            return Err("inventory router numeric, vocabulary or feature profile".to_string());
        }
        let mut identities = BTreeSet::new();
        let mut names = BTreeSet::new();
        for alias in &mut wire.aliases {
            if alias.phrases.is_empty() || alias.phrases.len() > 8
                || !identities.insert((alias.kind == AddressKind::Workflow, alias.key.as_str().to_owned()))
            {
                return Err("inventory router duplicate or unbounded alias key".to_string());
            }
            for phrase in &mut alias.phrases {
                if !phrase.is_ascii() || phrase.len() > 128 {
                    return Err("inventory router alias character profile".to_string());
                }
                *phrase = words(phrase).join(" ");
                if phrase.is_empty() || !names.insert(phrase.clone()) {
                    return Err("inventory router alias is empty or ambiguous".to_string());
                }
            }
        }
        Ok(Self { digest: ContractDigestV1::from_digest(expected).map_err(|error| error.to_string())?, wire })
    }

    pub fn training_digest(&self) -> ContractDigestV1 { self.wire.training_digest }
    pub fn calibration_digest(&self) -> ContractDigestV1 { self.wire.calibration_digest }

    /// Classify a bounded question. Unknown, ambiguous, mismatched namespace and
    /// below-calibration decisions abstain; the caller supplies no desired role.
    pub fn route_text(&self, text: &str) -> Result<Option<InventoryCellRouteV1>, String> {
        if text.is_empty() || text.len() > 8192 || !text.is_ascii() { return Ok(None); }
        let tokens = words(text);
        if tokens.len() > 256 { return Ok(None); }
        let normalized = format!(" {} ", tokens.join(" "));
        let mut entities = BTreeSet::new();
        let mut workflows = BTreeSet::new();
        let mut masked = normalized.clone();
        for alias in &self.wire.aliases {
            for phrase in &alias.phrases {
                let needle = format!(" {phrase} ");
                if normalized.contains(&needle) {
                    let (keys, replacement) = match alias.kind {
                        AddressKind::Entity => (&mut entities, " entity_port "),
                        AddressKind::Workflow => (&mut workflows, " workflow_port "),
                    };
                    keys.insert(alias.key.clone());
                    masked = masked.replace(&needle, replacement);
                }
            }
        }
        if entities.len() > 1 || workflows.len() > 1 || (entities.is_empty() && workflows.is_empty()) { return Ok(None); }
        let features = features(&masked);
        let mut logits = self.wire.bias.clone();
        for (logit, weights) in logits.iter_mut().zip(&self.wire.weights) {
            let mut sum = 0.0_f32;
            for (weight, feature) in weights.iter().zip(&features) { sum += weight * feature; }
            *logit += sum;
        }
        if logits.iter().any(|value| !value.is_finite()) { return Err("inventory router nonfinite inference".to_string()); }
        let mut order = [0_usize, 1, 2, 3];
        order.sort_by(|a, b| logits[*b].total_cmp(&logits[*a]).then(a.cmp(b)));
        let highest = logits[order[0]];
        let scores: Vec<_> = logits.iter().map(|value| (*value - highest).exp()).collect();
        let total: f32 = scores.iter().sum();
        let confidence = scores[order[0]] / total;
        let margin = (scores[order[0]] - scores[order[1]]) / total;
        if order[0] == 3 || confidence < self.wire.threshold || margin < self.wire.minimum_margin { return Ok(None); }
        let route = InventoryCellRouteV1 {
            operation: match order[0] { 0 => MemoryOperationV1::Semantic, 1 => MemoryOperationV1::Procedure, _ => MemoryOperationV1::Apply },
            entity: entities.into_iter().next(), workflow: workflows.into_iter().next(),
        };
        if route.validate().is_err() { return Ok(None); }
        Ok(Some(route))
    }
}

impl InventoryCellAddressResolverV1 for InventoryCellTextRouterV1 {
    fn model_digest(&self) -> ContractDigestV1 { self.digest }
    fn resolve<'a>(&'a self, request: &'a InventoryCellRequestV1, snapshot: &'a InventoryCellOwnerSnapshotV1) -> Pin<Box<dyn Future<Output = Result<Option<InventoryCellResolvedAddressV1>, String>> + Send + 'a>> {
        Box::pin(async move {
            let Some(route) = self.route_text(&request.text)? else { return Ok(None); };
            if route.entity.as_ref().is_some_and(|key| snapshot.current(key, InventoryCellKindV1::Semantic).is_none())
                || route.workflow.as_ref().is_some_and(|key| snapshot.current(key, InventoryCellKindV1::Skill).is_none())
            {
                return Ok(None);
            }
            Ok(Some(InventoryCellResolvedAddressV1 { request: request.clone(), route, owner_cut_digest: snapshot.owner_cut_digest(), model_digest: self.digest }))
        })
    }
}

fn words(text: &str) -> Vec<String> {
    text.split(|character: char| !character.is_ascii_alphanumeric() && character != '_')
        .filter(|word| !word.is_empty()).map(str::to_ascii_lowercase).collect()
}
fn features(text: &str) -> Vec<f32> {
    let tokens = words(text);
    let mut vector = vec![0.0_f32; DIMENSION];
    let mut add = |token: &str| {
        let digest = Digest32::of_bytes(token.as_bytes());
        let bytes = digest.as_array();
        let index = u64::from_le_bytes(bytes[..8].try_into().expect("fixed digest width")) as usize % DIMENSION;
        vector[index] += if bytes[8] & 1 == 0 { 1.0 } else { -1.0 };
    };
    for word in &tokens {
        add(&format!("u:{word}"));
        let padded = format!("^{word}$");
        for trigram in padded.as_bytes().windows(3) {
            add(&format!("c:{}", std::str::from_utf8(trigram).expect("ASCII feature token")));
        }
    }
    for pair in tokens.windows(2) { add(&format!("b:{} {}", pair[0], pair[1])); }
    let mut squared = 0.0_f32;
    for value in &vector { squared += value * value; }
    let norm = squared.sqrt();
    if norm > 0.0 { for value in &mut vector { *value /= norm; } }
    vector
}
