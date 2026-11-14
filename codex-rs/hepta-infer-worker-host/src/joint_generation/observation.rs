//! Owner supplied delivery facts. The model cannot manufacture committed output.

use crate::codec::Packet;
use crate::codec::Result;
use crate::decoder::Prefixes;
use crate::protocol::MAX_PREFIX_BYTES;

pub(crate) const OBSERVATION_PROFILE: &str = "owner-prefix-budget-v1";
pub(crate) const OBSERVATION_FEATURES: usize = 68;

#[derive(Clone, Debug, Eq, PartialEq)]
pub(crate) struct OwnerContext {
    pub(crate) required_mask: u8,
    pub(crate) optional_mask: u8,
    /// Wall microseconds, fixed by HJREQV02 and owner-prefix-budget-v1.
    pub(crate) budget_total: u64,
    pub(crate) budget_remaining: u64,
    pub(crate) task_digest: [u8; 32],
}

impl OwnerContext {
    pub(crate) fn validate(&self) -> Result<()> {
        if self.required_mask & self.optional_mask != 0
            || self.required_mask | self.optional_mask == 0
            || (self.required_mask | self.optional_mask) & !15 != 0
            || self.budget_total == 0
            || self.budget_remaining > self.budget_total
            || self.task_digest == [0; 32]
        {
            return Err("invalid owner delivery context".into());
        }
        Ok(())
    }

    pub(crate) fn validate_delivery_successor(&self, previous: &Self) -> Result<()> {
        self.validate()?;
        if self.required_mask != previous.required_mask
            || self.optional_mask != previous.optional_mask
            || self.budget_total != previous.budget_total
            || self.task_digest != previous.task_digest
            || self.budget_remaining > previous.budget_remaining
        {
            return Err("owner delivery contract or budget changed".into());
        }
        Ok(())
    }

    pub(crate) fn remaining_fraction(&self) -> f64 {
        self.budget_remaining as f64 / self.budget_total as f64
    }

    pub(crate) fn write_packet(&self, packet: &mut Packet) {
        packet.meta.extend([
            ("owner.budget_unit".into(), "wall-microseconds-v1".into()),
            ("owner.required_mask".into(), self.required_mask.to_string()),
            ("owner.optional_mask".into(), self.optional_mask.to_string()),
            ("owner.budget_total".into(), self.budget_total.to_string()),
            (
                "owner.budget_remaining".into(),
                self.budget_remaining.to_string(),
            ),
            (
                "owner.task_digest".into(),
                self.task_digest
                    .iter()
                    .map(|byte| format!("{byte:02x}"))
                    .collect(),
            ),
        ]);
    }

    pub(crate) fn read_packet(packet: &Packet) -> Result<Self> {
        if packet.text("owner.budget_unit")? != "wall-microseconds-v1" {
            return Err("unknown owner budget unit".into());
        }
        let digest = packet.text("owner.task_digest")?;
        if digest.len() != 64 || !digest.is_ascii() {
            return Err("owner task digest width".into());
        }
        let mut task_digest = [0; 32];
        for (index, byte) in task_digest.iter_mut().enumerate() {
            *byte = u8::from_str_radix(&digest[2 * index..2 * index + 2], 16)
                .map_err(|_| "owner task digest encoding")?;
        }
        let owner = Self {
            required_mask: packet
                .text("owner.required_mask")?
                .parse()
                .map_err(|_| "owner required mask")?,
            optional_mask: packet
                .text("owner.optional_mask")?
                .parse()
                .map_err(|_| "owner optional mask")?,
            budget_total: packet
                .text("owner.budget_total")?
                .parse()
                .map_err(|_| "owner total budget")?,
            budget_remaining: packet
                .text("owner.budget_remaining")?
                .parse()
                .map_err(|_| "owner remaining budget")?,
            task_digest,
        };
        owner.validate()?;
        Ok(owner)
    }
}

/// Bounded observation constructed from the admitted predecessor's parsed bytes.
/// The byte summaries are lossy; the exact prefix remains owned by the journal.
#[derive(Clone, Debug, PartialEq)]
pub(crate) struct DeliveryObservation {
    pub(crate) owner: OwnerContext,
    pub(crate) cursors: [u32; 4],
    pub(crate) totals: [u32; 4],
    pub(crate) committed: [Vec<u8>; 4],
}

impl DeliveryObservation {
    pub(crate) fn new(owner: &OwnerContext, prefixes: &Prefixes, totals: [u32; 4]) -> Result<Self> {
        owner.validate()?;
        for (index, (cursor, total)) in prefixes.cursors.iter().zip(totals).enumerate() {
            if total == 0
                || *cursor > total
                || (*cursor != 0 && (owner.required_mask | owner.optional_mask) & (1 << index) == 0)
            {
                return Err("prefix contradicts delivery obligations".into());
            }
        }
        if prefixes.bytes.iter().map(Vec::len).sum::<usize>() > MAX_PREFIX_BYTES {
            return Err("observation prefix bound".into());
        }
        Ok(Self {
            owner: owner.clone(),
            cursors: prefixes.cursors,
            totals,
            committed: prefixes.bytes.clone(),
        })
    }

    pub(crate) fn remaining_fraction(&self) -> f64 {
        self.owner.remaining_fraction()
    }

    pub(crate) fn required_complete(&self) -> bool {
        self.cursors
            .iter()
            .zip(self.totals)
            .enumerate()
            .all(|(index, (cursor, total))| {
                self.owner.required_mask & (1 << index) == 0 || *cursor == total
            })
    }

    pub(crate) fn modality_allowed(&self, index: usize) -> bool {
        index < 4 && (self.owner.required_mask | self.owner.optional_mask) & (1 << index) != 0
    }

    /// Per modality: progress, required/optional, byte count, mean/variance,
    /// order-sensitive checksum, nonempty flag, and the last eight ordered bytes.
    /// Global features state the remaining/spent fractions, total-budget scale
    /// and fraction of outstanding required units. All are finite and bounded.
    pub(crate) fn features(&self) -> Vec<f64> {
        let mut result = Vec::with_capacity(OBSERVATION_FEATURES);
        let mut required_units = 0_u64;
        let mut required_remaining = 0_u64;
        for index in 0..4 {
            let bytes = &self.committed[index];
            let required = self.owner.required_mask & (1 << index) != 0;
            let optional = self.owner.optional_mask & (1 << index) != 0;
            let count = bytes.len().max(1) as f64;
            let mean = bytes
                .iter()
                .map(|value| f64::from(*value) / 255.0)
                .sum::<f64>()
                / count;
            let variance = bytes
                .iter()
                .map(|value| (f64::from(*value) / 255.0 - mean).powi(2))
                .sum::<f64>()
                / count;
            let checksum = bytes.iter().fold(2_166_136_261_u32, |hash, byte| {
                (hash ^ u32::from(*byte)).wrapping_mul(16_777_619)
            });
            result.extend([
                f64::from(self.cursors[index]) / f64::from(self.totals[index]),
                f64::from(u8::from(required)),
                f64::from(u8::from(optional)),
                bytes.len() as f64 / MAX_PREFIX_BYTES as f64,
                mean,
                variance,
                if bytes.is_empty() {
                    0.0
                } else {
                    f64::from(checksum) / f64::from(u32::MAX)
                },
                f64::from(u8::from(!bytes.is_empty())),
            ]);
            let suffix = &bytes[bytes.len().saturating_sub(8)..];
            result.extend(std::iter::repeat_n(0.0, 8 - suffix.len()));
            result.extend(suffix.iter().map(|value| f64::from(*value) / 255.0));
            if required {
                required_units += u64::from(self.totals[index]);
                required_remaining += u64::from(self.totals[index] - self.cursors[index]);
            }
        }
        let remaining = self.remaining_fraction();
        result.extend([
            remaining,
            1.0 - remaining,
            (self.owner.budget_total as f64).ln_1p() / (u64::MAX as f64).ln_1p(),
            required_remaining as f64 / required_units.max(1) as f64,
        ]);
        result
    }
}

#[cfg(test)]
#[path = "observation_tests.rs"]
mod tests;
