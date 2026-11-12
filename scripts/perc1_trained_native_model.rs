//! Actual trained acquisition MLP and an explicit lossless FP64 feature carrier.
//! Carrier limbs inhabit the bounded Q24 transport; they are not latent magnitudes.

use crate::*;
use std::collections::BTreeSet;

pub const CODEC: &str = "perc1.fp64-u22-dictionary-carrier.v1";
pub const OUTPUT_ADAPTER: &str = "perc1.fp64-budget-threshold-ordinal-drive.v1";
pub const WIDTH: usize = 32;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Features {
    pub schema: String,
    pub rows: Vec<Vec<f64>>,
    pub candidate_ids: Vec<String>,
    pub upper_costs: Vec<u64>,
    pub remaining_budget: u64,
    pub head_sha256: String,
    pub head_canonical_sha256: String,
    pub feature_rows_sha256: String,
    pub carrier_digest: String,
    pub source_bindings: BTreeMap<String, String>,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Parameters {
    w1: Vec<Vec<f64>>,
    b1: Vec<f64>,
    w2: Vec<Vec<f64>>,
    b2: Vec<f64>,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Calibration {
    bias: Vec<f64>,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Head {
    schema: String,
    status: String,
    scientific_qualified: bool,
    layout: Vec<usize>,
    means: Vec<f64>,
    scales: Vec<f64>,
    parameters: Parameters,
    calibration: Calibration,
    pub cost_value: f64,
    pub threshold: f64,
    training_receipt: serde_json::Value,
}

fn finite(values: impl Iterator<Item = f64>, lower: f64, upper: f64) -> bool {
    values
        .into_iter()
        .all(|v| v.is_finite() && (lower..=upper).contains(&v))
}

pub fn bits_digest(rows: &[Vec<f64>]) -> Digest32 {
    let mut bytes = b"perc1.native-features.f64.v1".to_vec();
    bytes.extend_from_slice(&(rows.len() as u64).to_le_bytes());
    bytes.extend_from_slice(&(rows.first().map_or(0, Vec::len) as u64).to_le_bytes());
    for value in rows.iter().flatten() {
        bytes.extend_from_slice(&value.to_le_bytes());
    }
    Digest32::of_bytes(&bytes)
}

pub fn carrier(rows: &[Vec<f64>]) -> Result<Vec<i64>> {
    let width = rows.first().map_or(0, Vec::len);
    if !(1..=4).contains(&rows.len())
        || !(5..=84).contains(&width)
        || rows.iter().any(|r| r.len() != width)
        || !finite(rows.iter().flatten().copied(), -1e100, 1e100)
    {
        return Err("invalid feature layout".into());
    }
    let mut dictionary = Vec::new();
    let mut indices = Vec::new();
    for value in rows.iter().flatten() {
        let bits = value.to_bits();
        let index = match dictionary.iter().position(|v| *v == bits) {
            Some(index) => index,
            None => {
                dictionary.push(bits);
                dictionary.len() - 1
            }
        };
        indices.push(index as i64);
    }
    let mut values = vec![rows.len() as i64, width as i64, dictionary.len() as i64];
    for bits in dictionary {
        values.extend([
            (bits & 0x3fffff) as i64,
            ((bits >> 22) & 0x3fffff) as i64,
            (bits >> 44) as i64,
        ]);
    }
    values.extend(indices);
    if values.len() > 512 {
        return Err("lossless carrier exceeds original 512 scalar cap".into());
    }
    Ok(values)
}

pub fn decode(values: &[i64]) -> Result<Vec<Vec<f64>>> {
    if values.len() < 3 || values.iter().any(|v| !(0..=0x3fffff).contains(v)) {
        return Err("invalid lossless carrier".into());
    }
    let (count, width, unique) = (values[0] as usize, values[1] as usize, values[2] as usize);
    if !(1..=4).contains(&count)
        || !(5..=84).contains(&width)
        || unique > count * width
        || values.len() != 3 + unique * 3 + count * width
    {
        return Err("invalid lossless carrier dimensions".into());
    }
    let mut dictionary = Vec::new();
    for limb in values[3..3 + unique * 3].chunks_exact(3) {
        if limb[2] > 0xfffff {
            return Err("noncanonical FP64 limbs".into());
        }
        dictionary.push(f64::from_bits(
            limb[0] as u64 | ((limb[1] as u64) << 22) | ((limb[2] as u64) << 44),
        ));
    }
    let flat: Vec<f64> = values[3 + unique * 3..]
        .iter()
        .map(|v| {
            dictionary
                .get(*v as usize)
                .copied()
                .ok_or("invalid dictionary index")
        })
        .collect::<std::result::Result<_, _>>()?;
    let rows: Vec<Vec<f64>> = flat.chunks_exact(width).map(<[f64]>::to_vec).collect();
    if carrier(&rows)? != values {
        return Err("noncanonical lossless carrier".into());
    }
    Ok(rows)
}

impl Head {
    pub fn validate(&self) -> Result<()> {
        let r = &self.training_receipt;
        if self.layout.len() != 2 || !(1..=16).contains(&self.layout[0]) || self.layout[1] > 64 {
            return Err("invalid trained acquisition head".into());
        }
        let width = self.layout[0] + self.layout[1] + 4;
        let hidden = r["hidden"].as_u64().unwrap_or(0) as usize;
        let p = &self.parameters;
        if self.schema != "perc1.acquisition-mlp-head.v1"
            || self.status != "HOLD"
            || self.scientific_qualified
            || self.layout.len() != 2
            || !(1..=16).contains(&self.layout[0])
            || self.layout[1] > 64
            || !(1..=64).contains(&hidden)
            || self.means.len() != width
            || self.scales.len() != width
            || p.w1.len() != width
            || p.w1.iter().any(|v| v.len() != hidden)
            || p.b1.len() != hidden
            || p.w2.len() != hidden
            || p.w2.iter().any(|v| v.len() != 2)
            || p.b2.len() != 2
            || self.calibration.bias.len() != 2
            || !finite(self.means.iter().copied(), -1e100, 1e100)
            || !finite(self.scales.iter().copied(), 1e-6, 1e100)
            || !finite(
                p.w1.iter()
                    .flatten()
                    .chain(&p.b1)
                    .chain(p.w2.iter().flatten())
                    .chain(&p.b2)
                    .copied(),
                -1e6,
                1e6,
            )
            || !finite(self.calibration.bias.iter().copied(), -1e100, 1e100)
            || !finite([self.cost_value].into_iter(), 0.0, 1e6)
            || !finite([self.threshold].into_iter(), 0.0, 1.0)
            || r["schema"] != "perc1.acquisition-mlp-training.v1"
            || r["algorithm"] != "tanh_sgd_momentum_v1"
            || r["steps"].as_u64().is_none_or(|v| !(1..=2000).contains(&v))
            || r["train_count"]
                .as_u64()
                .is_none_or(|v| !(1..=10000).contains(&v))
            || r["dev_count"]
                .as_u64()
                .is_none_or(|v| !(1..=10000).contains(&v))
        {
            return Err("invalid trained acquisition head".into());
        }
        Ok(())
    }

    pub fn infer(&self, rows: &[Vec<f64>]) -> Result<Vec<[f64; 2]>> {
        let p = &self.parameters;
        let mut output = Vec::new();
        for row in rows {
            if row.len() != self.means.len() {
                return Err("MLP width mismatch".into());
            }
            let x: Vec<f64> = row
                .iter()
                .zip(&self.means)
                .zip(&self.scales)
                .map(|((v, m), s)| (v - m) / s)
                .collect();
            let hidden: Vec<f64> = (0..p.b1.len())
                .map(|j| {
                    let mut sum = 0.0;
                    for (value, weights) in x.iter().zip(&p.w1) {
                        sum += value * weights[j];
                    }
                    (sum + p.b1[j]).tanh()
                })
                .collect();
            let mut raw = [0.0; 2];
            for (j, result) in raw.iter_mut().enumerate() {
                for (activation, weights) in hidden.iter().zip(&p.w2) {
                    *result += activation * weights[j];
                }
                *result += p.b2[j];
                *result += self.calibration.bias[j];
            }
            if !finite(raw.into_iter(), -1e100, 1e100) {
                return Err("nonfinite native MLP result".into());
            }
            output.push(raw);
        }
        Ok(output)
    }

    pub fn parameter_bytes(&self) -> u64 {
        let p = &self.parameters;
        (self.means.len()
            + self.scales.len()
            + p.w1.iter().map(Vec::len).sum::<usize>()
            + p.b1.len()
            + p.w2.iter().map(Vec::len).sum::<usize>()
            + p.b2.len()
            + 2) as u64
            * 8
    }
}

impl Features {
    pub fn validate(&self, head: &Head, raw_head: &[u8]) -> Result<Vec<i64>> {
        head.validate()?;
        if self.head_sha256 != Digest32::of_bytes(raw_head).to_string()
            || self.head_canonical_sha256
                != Digest32::of_bytes(raw_head.strip_suffix(b"\n").unwrap_or(raw_head)).to_string()
        {
            return Err("head raw/canonical byte binding mismatch".into());
        }
        let required = [
            "feature_extractor_sha256",
            "feature_profile_sha256",
            "original_image_sha256",
            "producer_wire_sha256",
            "latent_receipt_sha256",
            "source_evidence_sha256",
            "source_manifest_sha256",
            "projection_sha256",
        ];
        if required
            .iter()
            .any(|k| !self.source_bindings.contains_key(*k))
            || self.source_bindings.values().any(|v| {
                v.len() != 64
                    || v == &"0".repeat(64)
                    || !v
                        .bytes()
                        .all(|c| c.is_ascii_digit() || (b'a'..=b'f').contains(&c))
            })
            || head.training_receipt["feature_extractor_sha256"].as_str()
                != self
                    .source_bindings
                    .get("feature_extractor_sha256")
                    .map(String::as_str)
        {
            return Err("source/feature recipe binding mismatch".into());
        }
        if self.schema != "perc1.acquisition-native-features.v1"
            || self.rows.len() != self.candidate_ids.len()
            || self.upper_costs.len() != self.rows.len()
            || self.upper_costs.contains(&0)
            || self.remaining_budget > i64::MAX as u64
            || self.rows.iter().any(|r| r.len() != head.means.len())
            || self.candidate_ids.iter().collect::<BTreeSet<_>>().len() != self.rows.len()
            || self
                .candidate_ids
                .iter()
                .any(|v| v == "abstain" || id(v).is_err())
        {
            return Err("invalid candidate catalog".into());
        }
        let values = carrier(&self.rows)?;
        if self.feature_rows_sha256 != bits_digest(&decode(&values)?).to_string()
            || self.carrier_digest != canonical_feature_vector_digest_v1(&values).to_string()
        {
            return Err("lossless feature/carrier digest mismatch".into());
        }
        Ok(values)
    }

    pub fn vectors(
        &self,
        head: &Head,
        raw: &[[f64; 2]],
    ) -> Result<(Vec<i64>, Vec<i64>, Vec<[f64; 3]>)> {
        if raw.len() != self.rows.len() {
            return Err("retained MLP output shape mismatch".into());
        }
        let mut drive = vec![0; WIDTH];
        let mut predictions = Vec::new();
        let mut bits = Vec::new();
        for raw in raw {
            if raw.iter().any(|v| !v.is_finite()) {
                return Err("nonfinite retained MLP output".into());
            }
            let gain = raw[0].clamp(-1.0, 1.0);
            let cost = (raw[1] * 1e6).max(0.0);
            let net = gain - head.cost_value * cost;
            if !net.is_finite() {
                return Err("nonfinite native acquisition value".into());
            }
            predictions.push([gain, cost, net]);
            for value in raw {
                bits.extend_from_slice(&value.to_le_bytes());
            }
        }
        // Preserve exact FP64 threshold/order, including positive sub-Q24 margins.
        // These are policy ordinals, not quantized logits or calibrated utility.
        for (i, prediction) in predictions.iter().enumerate() {
            if self.upper_costs[i] <= self.remaining_budget && prediction[2] > head.threshold {
                let lower = predictions
                    .iter()
                    .enumerate()
                    .filter(|(j, other)| {
                        self.upper_costs[*j] <= self.remaining_budget
                            && other[2] > head.threshold
                            && other[2] < prediction[2]
                    })
                    .count();
                drive[i] = (lower as i64 + 1) * Q / 4;
            }
        }
        let commitment = Digest32::of_bytes(&bits)
            .into_array()
            .into_iter()
            .map(i64::from)
            .collect();
        Ok((drive, commitment, predictions))
    }
}

pub struct Encoder {
    pub scope: CellScopeV1,
    pub frontier: Digest32,
    pub digest: Digest32,
    pub values: Vec<i64>,
}
impl CellInputEncoderV1 for Encoder {
    fn encode(
        &self,
        request: &CellEncodingRequestV1<'_>,
    ) -> std::result::Result<CellEncodedInputV1, CellExecutionError> {
        if request.scope != &self.scope
            || request.source_frontier != self.frontier
            || request.encoder_digest != self.digest
            || Digest32::of_bytes(request.observation) != self.frontier
        {
            return Err(CellExecutionError::EncodingMismatch);
        }
        Ok(CellEncodedInputV1 {
            encoder_digest: self.digest,
            feature_vector_q24: self.values.clone(),
            consumed_bytes: request.observation.len(),
            truncated_bytes: 0,
        })
    }
}
