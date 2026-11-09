//! Stateful autoregressive UTF-8 byte decoder; one unit is one Unicode scalar.

use crate::codec::Result;
use crate::math::uniform;
use crate::model::Model;
use crate::model::State;
use crate::protocol::EmissionLaw;
use crate::protocol::Sampler;

pub(crate) const TEXT_PROFILE: &str = "utf8-byte256-scalar128-v1";
pub(crate) const TEXT_SCALAR_LIMIT: u32 = 128;

pub(crate) fn generate(
    model: &Model,
    state: &mut State,
    start: u32,
    units: u32,
    law: EmissionLaw,
) -> Result<Vec<u8>> {
    let text = state.text.as_ref().ok_or("missing byte decoder state")?;
    if units == 0
        || start != text.units
        || start
            .checked_add(units)
            .is_none_or(|end| end > TEXT_SCALAR_LIMIT)
    {
        return Err("noncontiguous text decoder request".into());
    }
    // A failed proposal must not leave a partially advanced byte decoder.
    let mut successor = state.clone();
    let seed = law.seed ^ ((state.steps as u64) << 32) ^ (3_u64 << 48);
    let mut result = Vec::new();
    for _ in 0..units {
        let mut scalar = Vec::new();
        loop {
            let logits = model.byte_logits(&successor)?;
            let legal: Vec<usize> = (0..256)
                .filter(|byte| valid_next(&scalar, *byte as u8))
                .collect();
            let maximum = legal
                .iter()
                .map(|index| logits[*index])
                .fold(f64::NEG_INFINITY, f64::max);
            let counter = u64::from(
                successor
                    .text
                    .as_ref()
                    .ok_or("missing byte decoder state")?
                    .bytes,
            );
            let selected = if law.sampler == Sampler::Mean {
                *legal
                    .iter()
                    .find(|index| logits[**index] == maximum)
                    .ok_or("empty text byte law")?
            } else {
                let mass: f64 = legal
                    .iter()
                    .map(|index| (logits[*index] - maximum).exp())
                    .sum();
                let threshold = uniform(seed, counter) * mass;
                let mut accumulated = 0.0;
                let mut selected = *legal.last().ok_or("empty text byte law")?;
                for index in legal {
                    accumulated += (logits[index] - maximum).exp();
                    if accumulated >= threshold {
                        selected = index;
                        break;
                    }
                }
                selected
            } as u8;
            model.consume_byte(&mut successor, selected)?;
            scalar.push(selected);
            if std::str::from_utf8(&scalar).is_ok() {
                break;
            }
            if scalar.len() == 4 {
                return Err("invalid UTF-8 decoder transition".into());
            }
        }
        result.extend(scalar);
        successor
            .text
            .as_mut()
            .ok_or("missing byte decoder state")?
            .units += 1;
    }
    *state = successor;
    Ok(result)
}

fn valid_next(prefix: &[u8], byte: u8) -> bool {
    match prefix {
        [] => byte <= 0x7f || (0xc2..=0xf4).contains(&byte),
        [0xe0] => (0xa0..=0xbf).contains(&byte),
        [0xed] => (0x80..=0x9f).contains(&byte),
        [0xf0] => (0x90..=0xbf).contains(&byte),
        [0xf4] => (0x80..=0x8f).contains(&byte),
        [_] | [_, _] | [_, _, _] => (0x80..=0xbf).contains(&byte),
        _ => false,
    }
}

#[cfg(test)]
#[path = "text_codec_tests.rs"]
mod tests;
