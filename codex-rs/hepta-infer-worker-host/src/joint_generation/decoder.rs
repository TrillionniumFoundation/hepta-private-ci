//! Pure extraction of #4442 sampling/chunk selection, with explicit framing.
//! No research session lock, journal, output path or publication is retained.

use crate::codec::Result;
use crate::math::normal;
use crate::math::sigmoid;
use crate::math::uniform;
use crate::model::Model;
use crate::model::State;
use crate::protocol::EmissionLaw;
use crate::protocol::MAX_PREFIX_BYTES;
use crate::protocol::Reader;
use crate::protocol::Sampler;

pub(crate) const TOTAL_UNITS: [u32; 4] = [16, 1024, 4, 2];

#[derive(Clone, Debug, Default, Eq, PartialEq)]
pub(crate) struct Prefixes {
    pub(crate) cursors: [u32; 4],
    pub(crate) bytes: [Vec<u8>; 4],
    pub(crate) observed: bool,
}

impl Prefixes {
    pub(crate) fn read(prefix: &[u8]) -> Result<Self> {
        Self::read_profile(prefix, false)
    }

    pub(crate) fn for_model(model: &Model) -> Self {
        Self {
            observed: model.is_observed(),
            ..Self::default()
        }
    }

    pub(crate) fn read_for_model(prefix: &[u8], model: &Model) -> Result<Self> {
        if model.is_observed() {
            Self::read_profile(prefix, true)
        } else {
            Self::read(prefix)
        }
    }

    pub(crate) fn read_profile(prefix: &[u8], observed: bool) -> Result<Self> {
        if prefix.len() > MAX_PREFIX_BYTES {
            return Err("prefix too large".into());
        }
        let mut reader = Reader::new(prefix);
        let mut parsed = Self {
            observed,
            ..Self::default()
        };
        while !reader.is_empty() {
            if reader.take(4)? != if observed { b"HGC2" } else { b"HGC1" } {
                return Err("unknown output frame".into());
            }
            let modality = reader.byte()?;
            let start = reader.u32()?;
            let units = reader.u32()?;
            let length = reader.u32()? as usize;
            let payload = reader.take(length)?;
            parsed.append(modality, start, units, payload)?;
        }
        Ok(parsed)
    }

    fn append(&mut self, modality: u8, start: u32, units: u32, payload: &[u8]) -> Result<()> {
        let index = usize::from(modality);
        let totals = if self.observed {
            [16, 1024, 4, crate::text_codec::TEXT_SCALAR_LIMIT]
        } else {
            TOTAL_UNITS
        };
        let total = *totals.get(index).ok_or("unknown output modality")?;
        let end = start.checked_add(units).ok_or("output range overflow")?;
        if units == 0 || start != self.cursors[index] || end > total {
            return Err("noncontiguous output range".into());
        }
        if self.observed {
            crate::media_codec::validate_chunk(modality, start, units, payload)?;
        } else {
            match modality {
                0 if payload.len() == units as usize * 48 => {}
                1 if payload.len() == units as usize * 2 => {}
                2 if payload.len() == units as usize * 768 => {}
                3 => validate_text(payload, start, units)?,
                _ => return Err("output payload length".into()),
            }
        }
        self.bytes[index].extend(payload);
        self.cursors[index] = end;
        Ok(())
    }

    pub(crate) fn frame(&mut self, modality: u8, units: u32, payload: &[u8]) -> Result<Vec<u8>> {
        let start = *self
            .cursors
            .get(usize::from(modality))
            .ok_or("unknown output modality")?;
        self.append(modality, start, units, payload)?;
        let mut frame = if self.observed { b"HGC2" } else { b"HGC1" }.to_vec();
        frame.push(modality);
        for value in [start, units, payload.len() as u32] {
            frame.extend(value.to_le_bytes());
        }
        frame.extend(payload);
        Ok(frame)
    }
}

/// Commit codecs advance only the separate byte decoder state. Continuous core
/// state and every already committed byte are retained across content actions.
pub(crate) fn commit_chunk(
    model: &Model,
    state: &mut State,
    modality: u8,
    start: u32,
    units: u32,
    law: EmissionLaw,
) -> Result<Vec<u8>> {
    if !model.is_observed() {
        return chunk(model, state, modality, start, units, law);
    }
    let index = usize::from(modality);
    let total = *model.total_units().get(index).ok_or("unknown modality")?;
    if units == 0 || start.checked_add(units).is_none_or(|end| end > total) {
        return Err("commit exceeds remaining output".into());
    }
    if modality == 3 {
        return crate::text_codec::generate(model, state, start, units, law);
    }
    let all = sample_bytes(model, state, modality, law)?;
    let unit_bytes = [48, 2, 768][index];
    crate::media_codec::encode_chunk(
        modality,
        start,
        units,
        &all[start as usize * unit_bytes..(start + units) as usize * unit_bytes],
    )
}

fn validate_text(bytes: &[u8], start: u32, units: u32) -> Result<()> {
    let mut text = std::str::from_utf8(bytes).map_err(|_| "text frame encoding")?;
    for index in start..start + units {
        let (key, delimiter, maximum) = if index == 0 {
            ("action=", ';', 62)
        } else {
            ("sound=", '\n', 16)
        };
        text = text.strip_prefix(key).ok_or("text frame label")?;
        let (digits, suffix) = text.split_once(delimiter).ok_or("text frame delimiter")?;
        let value = digits.parse::<u8>().map_err(|_| "text label domain")?;
        if value > maximum || value.to_string() != digits {
            return Err("text label domain".into());
        }
        text = suffix;
    }
    if !text.is_empty() {
        return Err("text frame trailing bytes".into());
    }
    Ok(())
}

pub(crate) fn chunk(
    model: &Model,
    state: &State,
    modality: u8,
    start: u32,
    units: u32,
    law: EmissionLaw,
) -> Result<Vec<u8>> {
    if model.is_observed() {
        return Err("v4 requires the stateful commit codec".into());
    }
    let index = usize::from(modality);
    let total = *TOTAL_UNITS.get(index).ok_or("unknown modality")?;
    if units == 0 || start.checked_add(units).is_none_or(|end| end > total) {
        return Err("commit exceeds remaining output".into());
    }
    let all = sample_bytes(model, state, modality, law)?;
    if modality == 3 {
        let mut output = Vec::new();
        for (index, label) in all
            .iter()
            .enumerate()
            .skip(start as usize)
            .take(units as usize)
        {
            output.extend(
                if index == 0 {
                    format!("action={label};")
                } else {
                    format!("sound={label}\n")
                }
                .as_bytes(),
            );
        }
        Ok(output)
    } else {
        let unit_bytes = [48, 2, 768][index];
        Ok(all[start as usize * unit_bytes..(start + units) as usize * unit_bytes].to_vec())
    }
}

fn sample_bytes(model: &Model, state: &State, modality: u8, law: EmissionLaw) -> Result<Vec<u8>> {
    let index = usize::from(modality);
    let outputs = model.outputs(state)?;
    let values = outputs.get(index).ok_or("unknown modality")?;
    let seed = law.seed ^ ((state.steps as u64) << 32) ^ ((index as u64) << 48);
    if modality == 3 {
        let mut labels = Vec::new();
        for (position, logits) in [&values[..63], &values[63..]].iter().enumerate() {
            let maximum = logits.iter().copied().fold(f64::NEG_INFINITY, f64::max);
            let weights: Vec<f64> = logits.iter().map(|v| (v - maximum).exp()).collect();
            let selected = if law.sampler == Sampler::Mean {
                logits
                    .iter()
                    .position(|value| *value == maximum)
                    .ok_or("empty text logits")?
            } else {
                let threshold = uniform(seed, position as u64) * weights.iter().sum::<f64>();
                let mut accumulated = 0.0;
                let mut selected = weights.len() - 1;
                for (index, value) in weights.iter().enumerate() {
                    accumulated += value;
                    if accumulated >= threshold {
                        selected = index;
                        break;
                    }
                }
                selected
            };
            labels.push(selected as u8);
        }
        return Ok(labels);
    }
    let sampled: Vec<f64> = values
        .iter()
        .enumerate()
        .map(|(index, value)| {
            let value = value
                + if law.sampler == Sampler::Mean {
                    0.0
                } else {
                    0.035 * normal(seed, index as u64)
                };
            if modality == 1 {
                value.tanh()
            } else {
                sigmoid(value)
            }
        })
        .collect();
    if modality == 1 {
        return Ok(sampled
            .iter()
            .flat_map(|value| {
                ((value.clamp(-1.0, 1.0) * 32767.0).round_ties_even() as i16).to_le_bytes()
            })
            .collect());
    }
    let frames = if modality == 2 { 4 } else { 1 };
    let mut bytes = Vec::with_capacity(sampled.len());
    for frame in 0..frames {
        for pixel in 0..256 {
            for channel in 0..3 {
                bytes.push(
                    (sampled[frame * 768 + channel * 256 + pixel] * 255.0).round_ties_even() as u8,
                );
            }
        }
    }
    Ok(bytes)
}
