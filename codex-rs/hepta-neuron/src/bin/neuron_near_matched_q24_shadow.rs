//! Research-only: execute a physically learned d->h private affine adapter,
//! original immutable Q24 temporal kernel, and quantized private binary Head.
//! New V1 file/schema; production neuron models, V1 journal, final-use and CNS
//! are never changed. A synthetic model cannot supply independent NDU evidence.

use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::env;
use std::fs;
use std::path::Path;
use std::str::FromStr;

use codex_hepta_neuron::ActivationPopulationV2;
use codex_hepta_neuron::DiagonalSsmCheckpointV1;
use codex_hepta_neuron::DiagonalSsmConfigV1;
use codex_hepta_neuron::GatedSparseCheckpointV3;
use codex_hepta_neuron::GatedSparseConfigV3;
use codex_hepta_neuron::LowRankMinGruCheckpointV1;
use codex_hepta_neuron::LowRankMinGruConfigV1;
use codex_hepta_neuron::PopulationSparseCheckpointV2;
use codex_hepta_neuron::PopulationSparseConfigV2;
use codex_hepta_neuron::PopulationSparseTickV2;
use codex_hepta_neuron::TemporalGateV3;
use codex_hepta_neuron::TemporalProjectionEdgeV2;
use codex_hepta_neuron::diagonal_ssm_tick_v1;
use codex_hepta_neuron::gated_sparse_tick_v3;
use codex_hepta_neuron::low_rank_min_gru_tick_v1;
use codex_hepta_neuron::population_sparse_tick_v2;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use serde::Deserialize;
use serde::Deserializer;
use serde::Serialize;
use serde::de::MapAccess;
use serde::de::Visitor;
use serde_json::json;

const Q: i64 = 1 << 24;
const H: i64 = 8 * Q;
const MAX_MODEL: usize = 8 * 1024 * 1024;
const MAX_TRACE: usize = 4 * 1024 * 1024;
const MAX_HEADER: usize = 1024 * 1024;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct TensorEntry {
    dtype: String,
    shape: Vec<usize>,
    data_offsets: [usize; 2],
}

/// Reject duplicate tensor names; TensorEntry's derived deserializer rejects
/// duplicate fields, unlike reading a safetensors header as a generic JSON map.
struct UniqueTensorHeader(BTreeMap<String, TensorEntry>);
impl<'de> Deserialize<'de> for UniqueTensorHeader {
    fn deserialize<D: Deserializer<'de>>(d: D) -> Result<Self, D::Error> {
        struct HeaderVisitor;
        impl<'de> Visitor<'de> for HeaderVisitor {
            type Value = UniqueTensorHeader;
            fn expecting(&self, f: &mut std::fmt::Formatter) -> std::fmt::Result {
                f.write_str("unique physical safetensors tensor names")
            }
            fn visit_map<A: MapAccess<'de>>(self, mut map: A) -> Result<Self::Value, A::Error> {
                let mut entries = BTreeMap::new();
                while let Some((name, tensor)) = map.next_entry::<String, TensorEntry>()? {
                    if entries.insert(name, tensor).is_some() {
                        return Err(serde::de::Error::custom("duplicate tensor name"));
                    }
                }
                Ok(UniqueTensorHeader(entries))
            }
        }
        d.deserialize_map(HeaderVisitor)
    }
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Trace {
    schema: String,
    scope_digest: String,
    objective_digest: String,
    ndu_digest: String,
    body_digest: String,
    events: Vec<Event>,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Event {
    sequence: u64,
    monotonic_micros: u64,
    temporal_drive_q24: Vec<i64>,
    prediction_q24: Vec<i64>,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
struct StepOutcome {
    sequence: u64,
    predecessor_sha256: String,
    checkpoint_sha256: String,
    activation_q24: Vec<i64>,
    adapted_drive_q24: Vec<i64>,
    adapted_prediction_q24: Vec<i64>,
    prediction_error_q24: i64,
    quantized_head_logit_q24: i64,
    head_sign_margin_status: &'static str,
    head_sign_margin_twice_q24_lsb: u64,
}

struct WeightBank {
    q24: BTreeMap<String, Vec<i64>>,
    parameter_count: usize,
    tensor_count: usize,
}
type ShapeSpec = (&'static str, &'static str, Vec<usize>);

fn fail(what: &str) -> String {
    what.to_owned()
}

/// Only the two physically near-matchable tiers from the independently checked
/// 32D geometry preflight. Never silently relabel 2K trained weights as 256K.
fn registered_near_match(
    arm: &str,
    ceiling: usize,
) -> Result<(usize, Option<usize>, usize), String> {
    match (ceiling, arm) {
        (2048, "v2") => Ok((58, None, 2031)),
        (2048, "v3") => Ok((53, None, 2015)),
        (2048, "ssm") => Ok((55, None, 2036)),
        (2048, "min_gru") => Ok((45, Some(2), 2026)),
        (8192, "v2") => Ok((234, None, 8191)),
        (8192, "v3") => Ok((215, None, 8171)),
        (8192, "ssm") => Ok((221, None, 8178)),
        (8192, "min_gru") => Ok((182, Some(2), 8191)),
        _ => Err(fail("unregistered near-matched Cell candidate/tier")),
    }
}
fn digest(s: &str) -> Result<Digest32, String> {
    let parsed = Digest32::from_str(s).map_err(|_| fail("invalid lowercase digest"))?;
    if parsed.is_zero() {
        return Err(fail("zero digest"));
    }
    Ok(parsed)
}
fn expected(
    arm: &str,
    width: usize,
    rank: Option<usize>,
    source_width: usize,
) -> Result<Vec<ShapeSpec>, String> {
    if !(5..=256).contains(&source_width) {
        return Err(fail("invalid shared source feature width"));
    }
    if !(5..=256).contains(&width) {
        return Err(fail("invalid native width"));
    }
    let mut tensors = vec![
        ("adapter.weight", "F32", vec![width, source_width]),
        ("adapter.bias", "F32", vec![width]),
        ("head.weight", "F32", vec![1, width]),
        ("head.bias", "F32", vec![1]),
        ("structure.projection", "I64", vec![width]),
    ];
    match arm {
        "v2" => {
            if rank.is_some() {
                return Err(fail("unexpected V2 rank"));
            }
        }
        "v3" => {
            if rank.is_some() {
                return Err(fail("unexpected V3 rank"));
            }
            for name in [
                "temporal.gate_bias",
                "temporal.input_gain",
                "temporal.change_gain",
            ] {
                tensors.push((name, "I64", vec![width]));
            }
        }
        "ssm" => {
            if rank.is_some() {
                return Err(fail("unexpected SSM rank"));
            }
            for name in ["temporal.decay_per_step", "temporal.input_gain"] {
                tensors.push((name, "I64", vec![width]));
            }
        }
        "min_gru" => {
            let r = rank.ok_or_else(|| fail("minGRU rank missing"))?;
            if r == 0 || r > width {
                return Err(fail("minGRU rank invalid"));
            }
            tensors.extend([
                ("temporal.gate_input", "I64", vec![r, width]),
                ("temporal.gate_output", "I64", vec![width, r]),
                ("temporal.candidate_input", "I64", vec![r, width]),
                ("temporal.candidate_output", "I64", vec![width, r]),
                ("temporal.gate_bias", "I64", vec![width]),
                ("temporal.candidate_bias", "I64", vec![width]),
            ]);
        }
        _ => return Err(fail("unknown experimental arm")),
    }
    Ok(tensors)
}

fn load_file(path: &Path, expected_hash: Digest32, maximum: usize) -> Result<Vec<u8>, String> {
    if path.is_symlink() || path.parent().is_some_and(Path::is_symlink) {
        return Err(fail("symlinked research artifact"));
    }
    let meta = fs::metadata(path).map_err(|e| e.to_string())?;
    if !meta.is_file() || meta.len() == 0 || meta.len() > maximum as u64 {
        return Err(fail("physical file size or type rejected"));
    }
    let bytes = fs::read(path).map_err(|e| e.to_string())?;
    if bytes.len() as u64 != meta.len() || Digest32::of_bytes(&bytes) != expected_hash {
        return Err(fail("physical artifact or trace SHA mismatch"));
    }
    let after = fs::metadata(path).map_err(|e| e.to_string())?;
    if after.len() != meta.len() || after.modified().ok() != meta.modified().ok() {
        return Err(fail("source changed while reading"));
    }
    Ok(bytes)
}

/// IEEE-754 F32 bytes are first converted exactly to F64. Scaling by 2^24
/// is exactly representable for the admitted [-8,8] domain. Round ties-to-even
/// and reject larger weights, rather than permitting an overflowing native Head.
fn f32_to_q24_head(value: f32) -> Result<i64, String> {
    if !value.is_finite() || !(-8.0..=8.0).contains(&value) {
        return Err(fail("nonfinite or out-of-range physical F32 Head"));
    }
    let rounded = (f64::from(value) * (Q as f64)).round_ties_even();
    Ok(rounded as i64)
}

fn q24_mul_round_ties_even(left: i64, right: i64) -> Result<i64, String> {
    let product = i128::from(left) * i128::from(right);
    let absolute = product.abs();
    let denominator = i128::from(Q);
    let quotient = absolute / denominator;
    let remainder = absolute % denominator;
    let round_up =
        remainder * 2 > denominator || (remainder * 2 == denominator && quotient % 2 != 0);
    let rounded = (quotient + i128::from(round_up)) * product.signum();
    i64::try_from(rounded).map_err(|_| fail("native Q24 Head multiplication overflow"))
}

/// The quantized research Head consumes **native sparse Q24 activation**, not
/// the floating surrogate's pre-competition state. It is not calibrated.
fn quantized_head_logit(
    activation_q24: &[i64],
    head_q24: &[i64],
    bias_q24: i64,
) -> Result<i64, String> {
    if activation_q24.len() != head_q24.len() || activation_q24.is_empty() {
        return Err(fail("native Q24 Head activation/weight dimension mismatch"));
    }
    let mut sum = bias_q24;
    for (&activation, &weight) in activation_q24.iter().zip(head_q24) {
        let product = q24_mul_round_ties_even(activation, weight)?;
        sum = sum
            .checked_add(product)
            .ok_or_else(|| fail("native Q24 Head sum overflow"))?;
    }
    Ok(sum)
}

/// Sufficient same-activation F32->Q24 Head sign bound. Exactly stored
/// finite F32 coefficients are independently checked within [-8, 8] and
/// rounded ties-even into Q24; native Q24 activation |x_i| <= 8Q.
///
/// The F32 bias contributes <= 0.5 Q24 LSB. Each channel contributes
/// <= 8*0.5 coefficient LSB + 0.5 product-rounding LSB = 4.5 Q24 LSB.
/// Thus |real_F32_linear_head - Q24_linear_head| * Q <= (9*n+1)/2.
///
/// This ONLY covers an ideal real-arithmetic linear readout on the same
/// Q24 activation, not Torch FP32 accumulation, different temporal states,
/// calibration, binary action authorization or production final-use.
fn research_q24_head_sign_margin(
    logit_q24: i64,
    activation_q24: &[i64],
) -> Result<(&'static str, u64), String> {
    if !(5..=256).contains(&activation_q24.len())
        || activation_q24.iter().any(|v| !(-H..=H).contains(v))
    {
        return Err(fail(
            "quantized Head margin requires bounded native Q24 activation",
        ));
    }
    let twice_margin = u64::try_from(activation_q24.len() * 9 + 1)
        .map_err(|_| fail("research margin width overflow"))?;
    // i128 handles i64::MIN safely; checked Head arithmetic rejects
    // overflowing dot products *before* this function is called.
    let twice_abs_logit = i128::from(logit_q24).abs() * 2;
    let result = if twice_abs_logit <= i128::from(twice_margin) {
        "QUANTIZATION_AMBIGUOUS_ABSTAIN"
    } else if logit_q24 > 0 {
        "ACCEPT_POSITIVE_RESEARCH_ONLY"
    } else {
        "ACCEPT_NEGATIVE_RESEARCH_ONLY"
    };
    Ok((result, twice_margin))
}

fn physical_weights(
    bytes: &[u8],
    arm: &str,
    width: usize,
    rank: Option<usize>,
    cap: usize,
    source_width: usize,
) -> Result<WeightBank, String> {
    if bytes.len() < 10 {
        return Err(fail("truncated safetensors"));
    }
    let header_len = u64::from_le_bytes(
        bytes[..8]
            .try_into()
            .map_err(|_| fail("bad header length"))?,
    );
    let header_len = usize::try_from(header_len).map_err(|_| fail("huge header"))?;
    if !(2..=MAX_HEADER).contains(&header_len) || header_len > bytes.len() - 8 {
        return Err(fail("invalid safetensors header length"));
    }
    let UniqueTensorHeader(entries) =
        serde_json::from_slice::<UniqueTensorHeader>(&bytes[8..8 + header_len])
            .map_err(|e| format!("invalid or duplicate physical tensor header: {e}"))?;
    let schema = expected(arm, width, rank, source_width)?;
    let expected_names: BTreeSet<&str> = schema.iter().map(|x| x.0).collect();
    if entries.len() != schema.len() || entries.keys().any(|x| !expected_names.contains(x.as_str()))
    {
        return Err(fail("missing or unexpected physical tensor"));
    }
    let data = &bytes[8 + header_len..];
    let mut ranges = Vec::new();
    let mut weights = BTreeMap::new();
    let mut count = 0usize;
    for (name, dtype, shape) in schema {
        let entry = entries.get(name).ok_or_else(|| fail("missing tensor"))?;
        if entry.dtype != dtype || entry.shape != shape {
            return Err(format!("{name}: wrong dtype or shape"));
        }
        let elements = shape
            .iter()
            .try_fold(1usize, |n, d| n.checked_mul(*d))
            .ok_or_else(|| fail("tensor dimension overflow"))?;
        let size = elements
            .checked_mul(if dtype == "I64" { 8 } else { 4 })
            .ok_or_else(|| fail("tensor byte overflow"))?;
        let [start, end] = entry.data_offsets;
        if start >= end || end > data.len() || end - start != size {
            return Err(fail("tensor data offsets invalid"));
        }
        ranges.push((start, end));
        count = count
            .checked_add(elements)
            .ok_or_else(|| fail("parameter count overflow"))?;
        let payload = &data[start..end];
        if dtype == "F32" {
            let mut out = Vec::with_capacity(elements);
            for chunk in payload.chunks_exact(4) {
                let value = f32::from_le_bytes(chunk.try_into().map_err(|_| fail("bad float"))?);
                out.push(f32_to_q24_head(value)?);
            }
            weights.insert(name.to_owned(), out);
        } else {
            let mut out = Vec::with_capacity(elements);
            for chunk in payload.chunks_exact(8) {
                let value = i64::from_le_bytes(chunk.try_into().map_err(|_| fail("bad Q24"))?);
                let admitted = if name == "structure.projection" {
                    value == Q
                } else if name == "temporal.gate_bias" && arm == "v3"
                    || name == "temporal.decay_per_step" && arm == "ssm"
                {
                    (0..=Q).contains(&value)
                } else {
                    (-Q..=Q).contains(&value)
                };
                if !admitted {
                    return Err(format!("{name}: incompatible native Q24 value"));
                }
                out.push(value);
            }
            weights.insert(name.to_owned(), out);
        }
    }
    ranges.sort_unstable();
    let mut next = 0usize;
    for (start, end) in ranges {
        if start != next {
            return Err(fail("overlap or unclaimed safetensors bytes"));
        }
        next = end;
    }
    if next != data.len() || count > cap {
        return Err(fail("unclaimed data or exceeded private-parameter cap"));
    }
    Ok(WeightBank {
        q24: weights,
        parameter_count: count,
        tensor_count: entries.len(),
    })
}

fn weights<'a>(bank: &'a WeightBank, name: &str) -> Result<&'a Vec<i64>, String> {
    bank.q24
        .get(name)
        .ok_or_else(|| format!("missing native parameter {name}"))
}

/// Frozen feature vector d -> learned private h affine adapter, calculated with
/// signed Q24 nearest/ties-to-even. Prediction uses the same linear map without
/// adding the observation bias. This experimental binding never changes the
/// original immutable source Q24 tick or grants model authorization.
fn q24_adapter_tick(
    source: &PopulationSparseTickV2,
    bank: &WeightBank,
    model_sha: Digest32,
    width: usize,
) -> Result<PopulationSparseTickV2, String> {
    let source_width = source.temporal_drive_q24.len();
    if !(5..=256).contains(&source_width)
        || !(5..=256).contains(&width)
        || source.prediction_q24.len() != source_width
    {
        return Err(fail("unbounded or mismatched shared adapter input"));
    }
    let matrix = weights(bank, "adapter.weight")?;
    let bias = weights(bank, "adapter.bias")?;
    if matrix.len() != source_width * width || bias.len() != width {
        return Err(fail("missing physical adapter matrix or bias shape"));
    }
    let mut drive = Vec::with_capacity(width);
    let mut prediction = Vec::with_capacity(width);
    for output in 0..width {
        let mut projected = bias[output];
        let mut predicted = 0_i64;
        for col in 0..source_width {
            let weight = matrix[output * source_width + col];
            projected = projected
                .checked_add(q24_mul_round_ties_even(
                    weight,
                    source.temporal_drive_q24[col],
                )?)
                .ok_or_else(|| fail("native adapter observation sum overflow"))?;
            predicted = predicted
                .checked_add(q24_mul_round_ties_even(weight, source.prediction_q24[col])?)
                .ok_or_else(|| fail("native adapter prediction sum overflow"))?;
        }
        drive.push(projected.clamp(-H, H));
        prediction.push(predicted.clamp(-H, H));
    }
    let mut bytes = b"hepta.neuron.near-matched-adapter-input.q24.v1".to_vec();
    bytes.extend_from_slice(source.input_digest.as_array());
    bytes.extend_from_slice(model_sha.as_array());
    bytes.extend_from_slice(&(source_width as u64).to_be_bytes());
    bytes.extend_from_slice(&(width as u64).to_be_bytes());
    for value in drive.iter().chain(&prediction) {
        bytes.extend_from_slice(&value.to_be_bytes());
    }
    let mut adapted = source.clone();
    adapted.temporal_drive_q24 = drive;
    adapted.prediction_q24 = prediction;
    adapted.input_digest = Digest32::of_bytes(&bytes);
    Ok(adapted)
}
fn base_config(
    model_sha: Digest32,
    trace_sha: Digest32,
    width: usize,
) -> Result<PopulationSparseConfigV2, String> {
    let generation = Generation::new(1).map_err(|e| format!("generation: {e:?}"))?;
    let k = (width / 10).max(1);
    let split = width / 2;
    let config = PopulationSparseConfigV2 {
        model_digest: model_sha,
        normalization_digest: Digest32::of_parts(&[
            b"hepta.neuron.trained-shadow-norm.v1",
            trace_sha.as_array(),
        ]),
        generation,
        temporal_width: width,
        activation_width: width,
        global_top_k: k,
        temporal_decay_q24: Q / 2,
        projection: (0..width)
            .map(|i| TemporalProjectionEdgeV2 {
                source_temporal: i,
                target_activation: i,
                weight_q24: Q,
            })
            .collect(),
        inhibition_gain_q24: Q / 2,
        inhibition: Vec::new(),
        populations: vec![
            ActivationPopulationV2 {
                start: 0,
                len: split,
                top_k: k.div_ceil(2),
            },
            ActivationPopulationV2 {
                start: split,
                len: width - split,
                top_k: (k / 2).max(1),
            },
        ],
        activity_decay_q24: Q / 2,
        target_activity_q24: Q / 2,
        threshold_rate_q24: Q / 16,
        threshold_min_q24: -Q,
        threshold_max_q24: Q,
        eligibility_decay_q24: Q / 2,
    };
    config
        .digest()
        .map_err(|e| format!("native V2 admission: {e:?}"))?;
    Ok(config)
}

enum NativeModel {
    V2(
        PopulationSparseConfigV2,
        Option<PopulationSparseCheckpointV2>,
    ),
    V3(GatedSparseConfigV3, Option<GatedSparseCheckpointV3>),
    Ssm(DiagonalSsmConfigV1, Option<DiagonalSsmCheckpointV1>),
    MinGru(LowRankMinGruConfigV1, Option<LowRankMinGruCheckpointV1>),
}
impl NativeModel {
    fn new(
        arm: &str,
        bank: &WeightBank,
        model_sha: Digest32,
        trace_sha: Digest32,
        width: usize,
        rank: Option<usize>,
    ) -> Result<Self, String> {
        let base = base_config(model_sha, trace_sha, width)?;
        let model = match arm {
            "v2" => Self::V2(base, None),
            "v3" => {
                let bias = weights(bank, "temporal.gate_bias")?;
                let input = weights(bank, "temporal.input_gain")?;
                let change = weights(bank, "temporal.change_gain")?;
                let gates = (0..width)
                    .map(|i| TemporalGateV3 {
                        bias_q24: bias[i],
                        input_gain_q24: input[i],
                        change_gain_q24: change[i],
                    })
                    .collect();
                Self::V3(GatedSparseConfigV3 { base, gates }, None)
            }
            "ssm" => Self::Ssm(
                DiagonalSsmConfigV1 {
                    base,
                    decay_per_step_q24: weights(bank, "temporal.decay_per_step")?.clone(),
                    input_gain_q24: weights(bank, "temporal.input_gain")?.clone(),
                    time_quantum_micros: 1_000_000,
                },
                None,
            ),
            "min_gru" => Self::MinGru(
                LowRankMinGruConfigV1 {
                    base,
                    rank: rank.ok_or_else(|| fail("minGRU rank required"))?,
                    gate_input_q24: weights(bank, "temporal.gate_input")?.clone(),
                    gate_output_q24: weights(bank, "temporal.gate_output")?.clone(),
                    candidate_input_q24: weights(bank, "temporal.candidate_input")?.clone(),
                    candidate_output_q24: weights(bank, "temporal.candidate_output")?.clone(),
                    gate_bias_q24: weights(bank, "temporal.gate_bias")?.clone(),
                    candidate_bias_q24: weights(bank, "temporal.candidate_bias")?.clone(),
                },
                None,
            ),
            _ => return Err(fail("invalid arm")),
        };
        match &model {
            Self::V2(c, _) => c.digest().map_err(|e| format!("config: {e:?}"))?,
            Self::V3(c, _) => c.digest().map_err(|e| format!("config: {e:?}"))?,
            Self::Ssm(c, _) => c.digest().map_err(|e| format!("config: {e:?}"))?,
            Self::MinGru(c, _) => c.digest().map_err(|e| format!("config: {e:?}"))?,
        };
        Ok(model)
    }

    fn tick(
        &mut self,
        event: &PopulationSparseTickV2,
        head_q24: &[i64],
        bias_q24: i64,
    ) -> Result<StepOutcome, String> {
        let make = |before: Digest32,
                    after: Digest32,
                    activation: Vec<i64>,
                    prediction_error_q24: i64|
         -> Result<StepOutcome, String> {
            let quantized_head_logit_q24 = quantized_head_logit(&activation, head_q24, bias_q24)?;
            let (head_sign_margin_status, head_sign_margin_twice_q24_lsb) =
                research_q24_head_sign_margin(quantized_head_logit_q24, &activation)?;
            Ok(StepOutcome {
                sequence: event.sequence,
                predecessor_sha256: before.to_string(),
                checkpoint_sha256: after.to_string(),
                activation_q24: activation,
                adapted_drive_q24: event.temporal_drive_q24.clone(),
                adapted_prediction_q24: event.prediction_q24.clone(),
                prediction_error_q24,
                quantized_head_logit_q24,
                head_sign_margin_status,
                head_sign_margin_twice_q24_lsb,
            })
        };
        match self {
            Self::V2(cfg, prior) => {
                let (next, receipt) = population_sparse_tick_v2(cfg, event, prior.as_ref())
                    .map_err(|e| format!("V2 native tick: {e:?}"))?;
                let out = make(
                    receipt.checkpoint_before,
                    receipt.checkpoint_after,
                    receipt.activation_q24,
                    receipt.prediction_error_q24,
                )?;
                *prior = Some(next);
                Ok(out)
            }
            Self::V3(cfg, prior) => {
                let (next, receipt) = gated_sparse_tick_v3(cfg, event, prior.as_ref())
                    .map_err(|e| format!("V3 native tick: {e:?}"))?;
                let out = make(
                    receipt.checkpoint_before,
                    receipt.checkpoint_after,
                    receipt.activation_q24,
                    receipt.prediction_error_q24,
                )?;
                *prior = Some(next);
                Ok(out)
            }
            Self::Ssm(cfg, prior) => {
                let (next, receipt) = diagonal_ssm_tick_v1(cfg, event, prior.as_ref())
                    .map_err(|e| format!("SSM native tick: {e:?}"))?;
                let out = make(
                    receipt.checkpoint_before,
                    receipt.checkpoint_after,
                    receipt.activation_q24,
                    receipt.prediction_error_q24,
                )?;
                *prior = Some(next);
                Ok(out)
            }
            Self::MinGru(cfg, prior) => {
                let (next, receipt) = low_rank_min_gru_tick_v1(cfg, event, prior.as_ref())
                    .map_err(|e| format!("minGRU native tick: {e:?}"))?;
                let out = make(
                    receipt.checkpoint_before,
                    receipt.checkpoint_after,
                    receipt.activation_q24,
                    receipt.prediction_error_q24,
                )?;
                *prior = Some(next);
                Ok(out)
            }
        }
    }
}

fn trace_input(trace: &Trace, trace_sha: Digest32) -> Result<Vec<PopulationSparseTickV2>, String> {
    if trace.schema != "hepta.neuron.physical-q24-shadow-trace.v1"
        || trace.events.is_empty()
        || trace.events.len() > 1024
    {
        return Err(fail("bad or unbounded native trace"));
    }
    let scope = digest(&trace.scope_digest)?;
    let objective = digest(&trace.objective_digest)?;
    let ndu = digest(&trace.ndu_digest)?;
    let body = digest(&trace.body_digest)?;
    let width = trace.events[0].temporal_drive_q24.len();
    if !(5..=256).contains(&width) {
        return Err(fail("invalid trace width"));
    }
    let mut prev_time = 0;
    let mut out = Vec::new();
    for (index, row) in trace.events.iter().enumerate() {
        if row.sequence != (index + 1) as u64
            || row.monotonic_micros <= prev_time
            || row.temporal_drive_q24.len() != width
            || row.prediction_q24.len() != width
            || row
                .temporal_drive_q24
                .iter()
                .chain(&row.prediction_q24)
                .any(|v| !(-H..=H).contains(v))
        {
            return Err(fail("invalid sequence, clock, prediction, or input width"));
        }
        prev_time = row.monotonic_micros;
        let mut bytes = b"hepta.neuron.physical-trained-q24-input.v1".to_vec();
        bytes.extend_from_slice(trace_sha.as_array());
        bytes.extend_from_slice(&row.sequence.to_be_bytes());
        bytes.extend_from_slice(&row.monotonic_micros.to_be_bytes());
        for x in row.temporal_drive_q24.iter().chain(&row.prediction_q24) {
            bytes.extend_from_slice(&x.to_be_bytes());
        }
        out.push(PopulationSparseTickV2 {
            scope_digest: scope,
            objective_digest: objective,
            ndu_digest: ndu,
            body_digest: body,
            input_digest: Digest32::of_bytes(&bytes),
            sequence: row.sequence,
            monotonic_micros: row.monotonic_micros,
            temporal_drive_q24: row.temporal_drive_q24.clone(),
            prediction_q24: row.prediction_q24.clone(),
        });
    }
    Ok(out)
}
fn args() -> Result<BTreeMap<String, String>, String> {
    let mut map = BTreeMap::new();
    let mut it = env::args().skip(1);
    while let Some(name) = it.next() {
        if !name.starts_with("--") {
            return Err(fail("expected named arguments"));
        }
        let value = it.next().ok_or_else(|| fail("missing argument value"))?;
        if map.insert(name, value).is_some() {
            return Err(fail("duplicate CLI key"));
        }
    }
    let allowed = [
        "--arm",
        "--model",
        "--model-sha256",
        "--trace",
        "--trace-sha256",
        "--cap",
        "--hidden-width",
        "--rank",
    ];
    if map.len() < 6
        || map.keys().any(|x| !allowed.contains(&x.as_str()))
        || allowed[..7].iter().any(|x| !map.contains_key(*x))
    {
        return Err(fail(
            "required: --arm --model --model-sha256 --trace --trace-sha256 --cap --hidden-width",
        ));
    }
    Ok(map)
}
fn arg<'a>(map: &'a BTreeMap<String, String>, name: &str) -> Result<&'a str, String> {
    map.get(name)
        .map(String::as_str)
        .ok_or_else(|| fail("missing CLI field"))
}

fn execute() -> Result<serde_json::Value, String> {
    let opts = args()?;
    let arm = arg(&opts, "--arm")?;
    let cap: usize = arg(&opts, "--cap")?.parse().map_err(|_| fail("bad cap"))?;
    if ![2048, 8192].contains(&cap) {
        return Err(fail(
            "16K/64K/256K near-matched geometry is not implemented",
        ));
    }
    let rank = opts
        .get("--rank")
        .map(|s| s.parse::<usize>().map_err(|_| fail("bad rank")))
        .transpose()?;
    let model_sha = digest(arg(&opts, "--model-sha256")?)?;
    let trace_sha = digest(arg(&opts, "--trace-sha256")?)?;
    let trace_bytes = load_file(Path::new(arg(&opts, "--trace")?), trace_sha, MAX_TRACE)?;
    let trace: Trace = serde_json::from_slice(&trace_bytes).map_err(|e| format!("trace: {e}"))?;
    let inputs = trace_input(&trace, trace_sha)?;
    let source_width = inputs[0].temporal_drive_q24.len();
    let width: usize = arg(&opts, "--hidden-width")?
        .parse()
        .map_err(|_| fail("invalid hidden width"))?;
    let (registered_width, registered_rank, registered_count) = registered_near_match(arm, cap)?;
    if width != registered_width || rank != registered_rank {
        return Err(fail(
            "candidate width/rank differs from registered realized geometry",
        ));
    }
    let model_path = Path::new(arg(&opts, "--model")?);
    let bytes = load_file(model_path, model_sha, MAX_MODEL)?;
    let bank = physical_weights(&bytes, arm, width, rank, cap, source_width)?;
    if source_width != 32 || bank.parameter_count != registered_count {
        return Err(fail(
            "physical trained model is not an exactly registered 32D budget shape",
        ));
    }
    let adapted_inputs = inputs
        .iter()
        .map(|input| q24_adapter_tick(input, &bank, model_sha, width))
        .collect::<Result<Vec<_>, _>>()?;

    let head_q24 = weights(&bank, "head.weight")?;
    let head_bias_q24 = *weights(&bank, "head.bias")?
        .first()
        .ok_or_else(|| fail("missing quantized Head bias"))?;
    let mut first = NativeModel::new(arm, &bank, model_sha, trace_sha, width, rank)?;
    let mut a = Vec::with_capacity(inputs.len());
    for input in &adapted_inputs {
        a.push(first.tick(input, head_q24, head_bias_q24)?);
    }

    // Reopen the physical artifact, construct an independent empty state and
    // replay the original exact ordered input bytes. This is NOT a crash test.
    let again = load_file(model_path, model_sha, MAX_MODEL)?;
    if again != bytes {
        return Err(fail("same-sha reloaded artifact changed"));
    }
    let bank2 = physical_weights(&again, arm, width, rank, cap, source_width)?;
    let replay_inputs = inputs
        .iter()
        .map(|input| q24_adapter_tick(input, &bank2, model_sha, width))
        .collect::<Result<Vec<_>, _>>()?;
    let head_q24_reload = weights(&bank2, "head.weight")?;
    let bias_q24_reload = *weights(&bank2, "head.bias")?
        .first()
        .ok_or_else(|| fail("missing reloaded Q24 Head bias"))?;
    let mut second = NativeModel::new(arm, &bank2, model_sha, trace_sha, width, rank)?;
    let mut b = Vec::with_capacity(inputs.len());
    for input in &replay_inputs {
        b.push(second.tick(input, head_q24_reload, bias_q24_reload)?);
    }
    if a != b {
        return Err(fail("native Q24 replay frontier mismatch"));
    }

    Ok(json!({
        "schema":"hepta.neuron.near-matched-native-adapter-replay.v1",
        "arm":arm, "private_parameter_cap":cap, "private_parameter_count":bank.parameter_count,
        "physical_tensor_count":bank.tensor_count,
        "selected_private_weight_sha256":model_sha.to_string(),
        "trace_sha256":trace_sha.to_string(),
        "original_tick_count":inputs.len(),
        "width":width,
        "shared_encoder_feature_width":source_width,
        "native_q24_adapter_forward_invoked":true,
        "native_q24_adapter_math_independently_verified":false,
        "native_q24_kernel_invoked":true,
        "independent_empty_state_replay_equal":true,
        "frontier":a,
        "f32_head_executed":false,
        "quantized_q24_head_executed_in_rust":true,
        "f32_to_q24_head_round_ties_even_profile":"hepta.neuron.f32-q24-head.v1",
        "head_sign_margin_profile":"hepta.neuron.same-activation-head-sign-margin.v1",
        "head_margin_abstention_is_research_only":true,
        "head_margin_authorized_for_final_use":false,
        "torch_f32_native_q24_prediction_parity_verified":false,
        "trusted_target_host_attested":false,
        "durable_checkpoint_cas_verified":false,
        "crash_recovery_verified":false,
        "ndu_eligible":false,
        "production_qualification":false,
        "decision":"NO_PROMOTION"
    }))
}

fn main() {
    match execute() {
        Ok(result) => println!("{result}"),
        Err(reason) => {
            eprintln!(
                "{}",
                json!({
                    "status":"BLOCKED_NEAR_MATCHED_NATIVE_Q24_SHADOW",
                    "reason":reason, "production_qualification":false
                })
            );
            std::process::exit(2);
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn f32_to_q24_round_ties_even_matches_signed_oracle() -> Result<(), String> {
        assert_eq!(f32_to_q24_head(0.5 / Q as f32)?, 0);
        assert_eq!(f32_to_q24_head(1.5 / Q as f32)?, 2);
        assert_eq!(f32_to_q24_head(-1.5 / Q as f32)?, -2);
        assert_eq!(f32_to_q24_head(-2.5 / Q as f32)?, -2);
        assert_eq!(f32_to_q24_head(8.0)?, 8 * Q);
        assert_eq!(f32_to_q24_head(-8.0)?, -8 * Q);
        assert!(f32_to_q24_head(f32::NAN).is_err());
        assert!(f32_to_q24_head(f32::INFINITY).is_err());
        assert!(f32_to_q24_head(8.5).is_err());
        Ok(())
    }

    #[test]
    fn signed_q24_head_multiplication_and_dot_are_exact() -> Result<(), String> {
        assert_eq!(q24_mul_round_ties_even(1, Q / 2)?, 0);
        assert_eq!(q24_mul_round_ties_even(3, Q / 2)?, 2);
        assert_eq!(q24_mul_round_ties_even(-3, Q / 2)?, -2);
        assert_eq!(q24_mul_round_ties_even(-5, Q / 2)?, -2);
        assert_eq!(
            quantized_head_logit(&[Q, Q], &[Q / 2, -(Q / 2)], Q / 4)?,
            Q / 4
        );
        assert_eq!(quantized_head_logit(&[Q / 2, Q / 2], &[3, 3], 0)?, 4);
        assert!(quantized_head_logit(&[1, 1], &[Q, Q], i64::MAX).is_err());
        assert!(quantized_head_logit(&[Q], &[], 0).is_err());
        Ok(())
    }

    #[test]
    fn conservative_sign_margin_abstains_at_exact_boundary() -> Result<(), String> {
        let width16 = vec![0_i64; 16];
        for value in [-72, 0, 72] {
            let (status, bound) = research_q24_head_sign_margin(value, &width16)?;
            assert_eq!(bound, 145);
            assert_eq!(status, "QUANTIZATION_AMBIGUOUS_ABSTAIN");
        }
        assert_eq!(
            research_q24_head_sign_margin(73, &width16)?.0,
            "ACCEPT_POSITIVE_RESEARCH_ONLY"
        );
        assert_eq!(
            research_q24_head_sign_margin(-73, &width16)?.0,
            "ACCEPT_NEGATIVE_RESEARCH_ONLY"
        );
        let width256 = vec![H; 256];
        assert_eq!(
            research_q24_head_sign_margin(1152, &width256)?.0,
            "QUANTIZATION_AMBIGUOUS_ABSTAIN"
        );
        assert_eq!(
            research_q24_head_sign_margin(1153, &width256)?.0,
            "ACCEPT_POSITIVE_RESEARCH_ONLY"
        );
        Ok(())
    }

    #[test]
    fn conservative_sign_margin_rejects_invalid_activation_and_bounds() -> Result<(), String> {
        assert!(research_q24_head_sign_margin(1000, &[0; 4]).is_err());
        assert!(research_q24_head_sign_margin(1000, &[0; 257]).is_err());
        let mut invalid = vec![0_i64; 16];
        invalid[0] = H + 1;
        assert!(research_q24_head_sign_margin(1000, &invalid).is_err());
        // An extreme logit must not overflow the margin magnitude check.
        assert_eq!(
            research_q24_head_sign_margin(i64::MIN, &[0; 16])?.0,
            "ACCEPT_NEGATIVE_RESEARCH_ONLY"
        );
        Ok(())
    }

    #[test]
    fn conservative_sign_margin_never_promotes_zero_head() -> Result<(), String> {
        let activation = vec![0; 32];
        let logit = quantized_head_logit(&activation, &[0; 32], 0)?;
        assert_eq!(logit, 0);
        assert_eq!(
            research_q24_head_sign_margin(logit, &activation)?.0,
            "QUANTIZATION_AMBIGUOUS_ABSTAIN"
        );
        Ok(())
    }
    #[test]
    fn only_eight_registered_near_matched_physical_candidates_are_admitted() {
        assert_eq!(registered_near_match("v2", 2048), Ok((58, None, 2031)));
        assert_eq!(registered_near_match("v3", 8192), Ok((215, None, 8171)));
        assert_eq!(
            registered_near_match("min_gru", 8192),
            Ok((182, Some(2), 8191))
        );
        for ceiling in [16384, 65536, 262144] {
            for arm in ["v2", "v3", "ssm", "min_gru"] {
                assert!(registered_near_match(arm, ceiling).is_err());
            }
        }
        assert!(registered_near_match("foreign", 2048).is_err());
    }

    #[test]
    fn adapter_signed_q24_projection_binds_physical_matrix_and_digest() -> Result<(), String> {
        let mut matrix = vec![0_i64; 25];
        matrix[0] = Q / 2;
        matrix[5] = -(Q / 2);
        let bank = WeightBank {
            q24: BTreeMap::from([
                ("adapter.weight".to_owned(), matrix),
                ("adapter.bias".to_owned(), vec![0; 5]),
            ]),
            parameter_count: 30,
            tensor_count: 2,
        };
        let source = PopulationSparseTickV2 {
            scope_digest: Digest32::of_bytes(b"scope"),
            objective_digest: Digest32::of_bytes(b"objective"),
            ndu_digest: Digest32::of_bytes(b"ndu"),
            body_digest: Digest32::of_bytes(b"body"),
            input_digest: Digest32::of_bytes(b"first source input"),
            sequence: 1,
            monotonic_micros: 1000,
            temporal_drive_q24: vec![3, -5, 0, 0, 0],
            prediction_q24: vec![-5, 3, 0, 0, 0],
        };
        let model = Digest32::of_bytes(b"actual physical weight bytes");
        let after = q24_adapter_tick(&source, &bank, model, 5)?;
        assert_eq!(after.temporal_drive_q24, vec![2, -2, 0, 0, 0]);
        assert_eq!(after.prediction_q24, vec![-2, -2, 0, 0, 0]);
        assert_ne!(after.input_digest, source.input_digest);
        assert_eq!(source.temporal_drive_q24, vec![3, -5, 0, 0, 0]);
        assert!(q24_adapter_tick(&source, &bank, model, 6).is_err());
        let changed_model = Digest32::of_bytes(b"another model identity");
        assert_ne!(
            after.input_digest,
            q24_adapter_tick(&source, &bank, changed_model, 5)?.input_digest
        );
        Ok(())
    }
}
