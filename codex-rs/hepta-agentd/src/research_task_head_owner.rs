//! Offline research ownership of the existing float/gated task Head.
//!
//! Constructor pins are trusted host configuration, not request authentication
//! or a revocation oracle. This owner is not registered with daemon startup,
//! ObjectiveStart, the Q24 model port, or FinalUse. Pair identity means the
//! declared tuple, including crossed negatives; it never means label equality.

use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::error::Error;
use std::fmt;

use codex_hepta_neuron::LoadedTaskHeadV1;
use codex_hepta_neuron::TaskFeatureIdentityV1;
use codex_hepta_neuron::TaskHeadError;
use codex_hepta_neuron::TaskPredictionV1;
use codex_hepta_types::Digest32;
use serde::Deserialize;
use serde::Serialize;

const WIDTH: usize = 3073;
const MAX_HEADER_BYTES: usize = 64 * 1024;
const MAX_INVENTORY_BYTES: usize = 4 * 1024 * 1024;
const MAX_INVENTORY_ROWS: usize = 4096;
const MAX_REQUEST_BYTES: usize = 32 * 1024 * 1024;
const MAX_BATCH_ROWS: usize = 512;
const MAX_ROW_BYTES: usize = 256 * 1024;
const LAYOUT: &str = "concat-text-image-product-absolute-difference-cosine-v1";

/// Fixed research cases; their names confer no semantic pairing correctness.
#[derive(Clone, Copy, Debug, Deserialize, Eq, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum ResearchTaskHeadCaseV1 {
    Paired,
    MissingText,
    MissingImage,
    ShuffledImage,
    MixedPresence,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
struct RowBinding {
    case_id: ResearchTaskHeadCaseV1,
    row_index: usize,
    row_id: String,
    pair_block_id: String,
    image_id: u64,
    caption_id: u64,
    source_caption_image_id: u64,
    source_record_digest: String,
    text_provenance_sha256: String,
    image_provenance_sha256: String,
    present_mask: u8,
    features_sha256: String,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct OwnerManifest {
    schema: String,
    mode: String,
    authority: String,
    production_activation_allowed: bool,
    task_admission_allowed: bool,
    action_execution_allowed: bool,
    source_commit: String,
    source_report_sha256: String,
    source_plan_sha256: String,
    cohort_manifest_sha256: String,
    bank_manifest_sha256: String,
    feature_payload_sha256: String,
    producer_code_sha256: String,
    source_head_manifest_sha256: String,
    source_head_weights_sha256: String,
    native_head_manifest_sha256: String,
    native_head_weights_sha256: String,
    feature_identity: TaskFeatureIdentityV1,
    feature_layout: String,
    width: usize,
    required_present_mask: u8,
    temperature: f64,
    confidence_threshold: f64,
    state_contract: String,
    numeric_profile: String,
    inventory_sha256: String,
    inventory_rows: usize,
}

// LoadedTaskHeadV1 first validates the complete strict native manifest. This
// second view only cross-binds its source/semantic fields to the owner receipt.
#[derive(Deserialize)]
struct NativeBinding {
    source_head_manifest_sha256: String,
    source_head_weights_sha256: String,
    feature_layout: String,
    width: usize,
    required_present_mask: u8,
    temperature: f64,
    confidence_threshold: f64,
    state_contract: String,
    numeric_profile: String,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Inventory {
    schema: String,
    rows: Vec<RowBinding>,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct RequestRow {
    binding: RowBinding,
    features: Vec<f32>,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Request {
    owner_manifest_sha256: String,
    feature_identity: TaskFeatureIdentityV1,
    rows: Vec<RequestRow>,
}

/// A research observation, never an admission or permission receipt.
#[derive(Debug, Serialize)]
pub struct ResearchTaskHeadRowReceiptV1 {
    pub case_id: ResearchTaskHeadCaseV1,
    pub row_index: usize,
    pub row_id: String,
    pub source_record_digest: String,
    pub status: &'static str,
    pub accepted: bool,
    pub prediction: Option<TaskPredictionV1>,
}

/// Separate from the frozen scientific report and all production decisions.
#[derive(Debug, Serialize)]
pub struct ResearchTaskHeadOwnerReceiptV1 {
    pub schema: &'static str,
    pub owner_manifest_sha256: String,
    pub native_head_manifest_sha256: String,
    pub input_rows: usize,
    pub forward_calls: usize,
    pub rows: Vec<ResearchTaskHeadRowReceiptV1>,
    pub mode: &'static str,
    pub authority: &'static str,
    pub production_activation_allowed: bool,
    pub task_admission_allowed: bool,
    pub action_execution_allowed: bool,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ResearchTaskHeadOwnerError {
    Bounds,
    Encoding,
    Integrity,
    Contract,
    DuplicateRow,
    Native(TaskHeadError),
}

impl fmt::Display for ResearchTaskHeadOwnerError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl Error for ResearchTaskHeadOwnerError {}

/// Owns one immutable Head and a fixed host-pinned producer inventory.
pub struct AgentdResearchTaskHeadOwnerV1 {
    head: LoadedTaskHeadV1,
    owner_pin: Digest32,
    inventory: BTreeMap<(ResearchTaskHeadCaseV1, usize), RowBinding>,
    forward_entries: u64,
}

impl AgentdResearchTaskHeadOwnerV1 {
    /// Install independently retained host pins, never pins from a score request.
    /// Inputs are bounded bytes, not paths; there is no file or network access.
    pub fn from_artifacts(
        owner_manifest: &[u8],
        inventory_bytes: &[u8],
        native_manifest: &[u8],
        weights: &[u8],
        expected_owner_pin: Digest32,
        expected_native_pin: Digest32,
    ) -> Result<Self, ResearchTaskHeadOwnerError> {
        use ResearchTaskHeadOwnerError as E;
        if owner_manifest.is_empty()
            || owner_manifest.len() > MAX_HEADER_BYTES
            || inventory_bytes.is_empty()
            || inventory_bytes.len() > MAX_INVENTORY_BYTES
            || native_manifest.is_empty()
            || native_manifest.len() > MAX_HEADER_BYTES
            || weights.is_empty()
            || weights.len() > 1024 * 1024
        {
            return Err(E::Bounds);
        }
        if expected_owner_pin.is_zero() || Digest32::of_bytes(owner_manifest) != expected_owner_pin
        {
            return Err(E::Integrity);
        }
        let manifest: OwnerManifest =
            serde_json::from_slice(owner_manifest).map_err(|_| E::Encoding)?;
        validate_manifest(&manifest)?;
        if parse_pin(&manifest.native_head_manifest_sha256)? != expected_native_pin
            || parse_pin(&manifest.native_head_weights_sha256)? != Digest32::of_bytes(weights)
            || parse_pin(&manifest.inventory_sha256)? != Digest32::of_bytes(inventory_bytes)
        {
            return Err(E::Integrity);
        }
        let head = LoadedTaskHeadV1::from_artifact(native_manifest, weights, expected_native_pin)
            .map_err(E::Native)?;
        let native: NativeBinding =
            serde_json::from_slice(native_manifest).map_err(|_| E::Encoding)?;
        if head.feature_identity() != &manifest.feature_identity
            || native.source_head_manifest_sha256 != manifest.source_head_manifest_sha256
            || native.source_head_weights_sha256 != manifest.source_head_weights_sha256
            || native.feature_layout != manifest.feature_layout
            || native.width != manifest.width
            || native.required_present_mask != manifest.required_present_mask
            || native.temperature != manifest.temperature
            || native.confidence_threshold != manifest.confidence_threshold
            || native.state_contract != manifest.state_contract
            || native.numeric_profile != manifest.numeric_profile
        {
            return Err(E::Contract);
        }
        validate_row_byte_bounds(inventory_bytes)?;
        let rows: Inventory = serde_json::from_slice(inventory_bytes).map_err(|_| E::Encoding)?;
        if rows.schema != "hepta.research-task-head-row-inventory.v1"
            || rows.rows.len() != manifest.inventory_rows
        {
            return Err(E::Contract);
        }
        let mut inventory = BTreeMap::new();
        let mut sources = BTreeSet::new();
        for row in rows.rows {
            validate_row(&row)?;
            if !sources.insert((row.case_id, row.row_id.clone()))
                || inventory
                    .insert((row.case_id, row.row_index), row)
                    .is_some()
            {
                return Err(E::DuplicateRow);
            }
        }
        Ok(Self {
            head,
            owner_pin: expected_owner_pin,
            inventory,
            forward_entries: 0,
        })
    }

    /// Preflight the entire owned batch before any Head entry, then score only
    /// complete rows. Request-supplied hashes cannot replace installed pins.
    pub fn score_json(
        &mut self,
        request_bytes: &[u8],
    ) -> Result<ResearchTaskHeadOwnerReceiptV1, ResearchTaskHeadOwnerError> {
        use ResearchTaskHeadOwnerError as E;
        if request_bytes.is_empty() || request_bytes.len() > MAX_REQUEST_BYTES {
            return Err(E::Bounds);
        }
        validate_row_byte_bounds(request_bytes)?;
        let request: Request = serde_json::from_slice(request_bytes).map_err(|_| E::Encoding)?;
        if request.rows.is_empty() || request.rows.len() > MAX_BATCH_ROWS {
            return Err(E::Bounds);
        }
        if parse_pin(&request.owner_manifest_sha256)? != self.owner_pin
            || &request.feature_identity != self.head.feature_identity()
        {
            return Err(E::Integrity);
        }
        let mut seen = BTreeSet::new();
        let mut previous = None;
        for row in &request.rows {
            let key = (row.binding.case_id, row.binding.row_index);
            if !seen.insert(key) {
                return Err(E::DuplicateRow);
            }
            if previous.is_some_and(|prior| prior >= key) {
                return Err(E::Contract);
            }
            previous = Some(key);
            if self.inventory.get(&key) != Some(&row.binding)
                || row.features.len() != WIDTH
                || row.features.iter().any(|value| !value.is_finite())
                || feature_digest(&row.features) != parse_pin(&row.binding.features_sha256)?
            {
                return Err(E::Integrity);
            }
        }
        let mut rows = Vec::with_capacity(request.rows.len());
        let mut forward_calls = 0;
        for row in request.rows {
            let prediction = if row.binding.present_mask & 3 == 3 {
                self.forward_entries = self.forward_entries.checked_add(1).ok_or(E::Bounds)?;
                forward_calls += 1;
                Some(
                    self.head
                        .predict(
                            &row.features,
                            &request.feature_identity,
                            row.binding.present_mask,
                        )
                        .map_err(E::Native)?,
                )
            } else {
                None
            };
            rows.push(ResearchTaskHeadRowReceiptV1 {
                case_id: row.binding.case_id,
                row_index: row.binding.row_index,
                row_id: row.binding.row_id,
                source_record_digest: row.binding.source_record_digest,
                status: if prediction.is_some() {
                    "SCORED_RESEARCH_ONLY"
                } else {
                    "REJECTED_MISSING_REQUIRED_MODALITY"
                },
                accepted: prediction.as_ref().is_some_and(|value| value.accepted),
                prediction,
            });
        }
        Ok(ResearchTaskHeadOwnerReceiptV1 {
            schema: "hepta.research-task-head-owner-receipt.v1",
            owner_manifest_sha256: self.owner_pin.to_string(),
            native_head_manifest_sha256: self.head.manifest_sha256().to_string(),
            input_rows: rows.len(),
            forward_calls,
            rows,
            mode: "SHADOW_ONLY",
            authority: "DENY_ALL",
            production_activation_allowed: false,
            task_admission_allowed: false,
            action_execution_allowed: false,
        })
    }
}

// Rows are direct containers inside an array one level below the envelope.
// Scan all such arrays, independent of escaped JSON keys and serde's accepted
// positional sequence representation of structs (including the envelope).
// Count each row container's original UTF-8 bytes, including delimiters and
// internal whitespace, but not whitespace between array elements. This is
// an allocation-free bounds preflight, not a JSON parser: serde still rejects
// malformed syntax, wrong types, duplicate keys and unknown fields afterwards.
fn validate_row_byte_bounds(bytes: &[u8]) -> Result<(), ResearchTaskHeadOwnerError> {
    let mut depth = 0_usize;
    let mut root_array = false;
    let mut in_string = false;
    let mut escaped = false;
    let mut row_start = None;
    for (offset, byte) in bytes.iter().copied().enumerate() {
        if row_start.is_some_and(|start| offset - start + 1 > MAX_ROW_BYTES) {
            return Err(ResearchTaskHeadOwnerError::Bounds);
        }
        if in_string {
            if escaped {
                escaped = false;
            } else if byte == b'\\' {
                escaped = true;
            } else if byte == b'"' {
                in_string = false;
            }
            continue;
        }
        match byte {
            b'"' => in_string = true,
            b'{' | b'[' => {
                if depth == 1 && byte == b'[' {
                    root_array = true;
                }
                if depth == 2 && root_array {
                    row_start = Some(offset);
                }
                depth += 1;
            }
            b'}' | b']' => {
                if depth == 3 {
                    row_start = None;
                }
                if depth == 2 && byte == b']' {
                    root_array = false;
                }
                depth = depth.saturating_sub(1);
            }
            _ => {}
        }
    }
    Ok(())
}

fn parse_pin(value: &str) -> Result<Digest32, ResearchTaskHeadOwnerError> {
    if value.len() != 64
        || !value
            .bytes()
            .all(|v| v.is_ascii_digit() || (b'a'..=b'f').contains(&v))
    {
        return Err(ResearchTaskHeadOwnerError::Contract);
    }
    let pin: Digest32 = value
        .parse()
        .map_err(|_| ResearchTaskHeadOwnerError::Contract)?;
    if pin.is_zero() {
        return Err(ResearchTaskHeadOwnerError::Contract);
    }
    Ok(pin)
}

fn feature_digest(features: &[f32]) -> Digest32 {
    let bytes: Vec<u8> = features
        .iter()
        .flat_map(|value| value.to_le_bytes())
        .collect();
    Digest32::of_bytes(&bytes)
}

fn validate_row(row: &RowBinding) -> Result<(), ResearchTaskHeadOwnerError> {
    if row.row_index >= MAX_INVENTORY_ROWS
        || row.image_id == 0
        || row.caption_id == 0
        || row.source_caption_image_id == 0
        || row.present_mask & !0b1_1111 != 0
    {
        return Err(ResearchTaskHeadOwnerError::Contract);
    }
    for value in [
        &row.row_id,
        &row.pair_block_id,
        &row.source_record_digest,
        &row.text_provenance_sha256,
        &row.image_provenance_sha256,
        &row.features_sha256,
    ] {
        parse_pin(value)?;
    }
    Ok(())
}

fn validate_manifest(manifest: &OwnerManifest) -> Result<(), ResearchTaskHeadOwnerError> {
    if manifest.schema != "hepta.research-task-head-owner.v1"
        || manifest.mode != "SHADOW_ONLY"
        || manifest.authority != "DENY_ALL"
        || manifest.production_activation_allowed
        || manifest.task_admission_allowed
        || manifest.action_execution_allowed
        || manifest.width != WIDTH
        || manifest.required_present_mask != 3
        || manifest.feature_layout != LAYOUT
        || manifest.state_contract != "zero_state_only"
        || manifest.numeric_profile != "f32-io-f64-accum-gelu-erf-v1"
        || !manifest.temperature.is_finite()
        || !(0.0..=100.0).contains(&manifest.temperature)
        || manifest.temperature == 0.0
        || !(0.0..=1.0).contains(&manifest.confidence_threshold)
        || !(1..=MAX_INVENTORY_ROWS).contains(&manifest.inventory_rows)
        || manifest.source_commit.len() != 40
        || !manifest
            .source_commit
            .bytes()
            .all(|v| v.is_ascii_digit() || (b'a'..=b'f').contains(&v))
    {
        return Err(ResearchTaskHeadOwnerError::Contract);
    }
    for value in [
        &manifest.source_report_sha256,
        &manifest.source_plan_sha256,
        &manifest.cohort_manifest_sha256,
        &manifest.bank_manifest_sha256,
        &manifest.feature_payload_sha256,
        &manifest.producer_code_sha256,
        &manifest.source_head_manifest_sha256,
        &manifest.source_head_weights_sha256,
        &manifest.native_head_manifest_sha256,
        &manifest.native_head_weights_sha256,
        &manifest.inventory_sha256,
    ] {
        parse_pin(value)?;
    }
    Ok(())
}

#[cfg(test)]
#[path = "research_task_head_owner_tests.rs"]
mod tests;
