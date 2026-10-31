//! Public piecewise constant intervals schedule all owner work in Rust.
use super::Interval;
use super::Owner;
use super::Receipt;
use super::Request;
use crate::native::LIMIT;
use std::time::Instant;

impl Owner {
    pub fn interval(&mut self, interval: Interval, subdivisions: u64) -> Result<Receipt, String> {
        let start = Instant::now();
        if interval.operation != "interval"
            || ![1, 16].contains(&subdivisions)
            || interval.duration_micros < subdivisions
            || interval.duration_micros > 128_000_000
            || interval.pair_before != self.pair_digest.to_string()
            || self.cell.sequence + subdivisions > LIMIT as u64
            || self.poisoned
            || !interval.driver.is_finite()
            || interval.driver.abs() > 1.
            || interval.horizon_micros == 0
            || interval.horizon_micros > 128_000_000
            || self
                .cell
                .elapsed_micros
                .checked_add(interval.duration_micros)
                .is_none_or(|x| x > (1_u64 << 52))
        {
            return Err("interval envelope/frontier".into());
        }
        // Content validation and inference precede every commit. Failed reads cannot
        // leave fifteen dense commits behind a caller's old acknowledged frontier.
        let content_start = Instant::now();
        let mut decoded = self.decode(&interval.content)?;
        let content_nanos = content_start.elapsed().as_nanos().try_into().unwrap_or(u64::MAX);
        let (mut physics, mut native, mut journal, mut witness, mut checkpoint, mut durable) = (0, 0, 0, 0, 0, 0);
        let mut jumps = Vec::new();
        let mut last = None;
        for part in 0..subdivisions {
            let final_part = part + 1 == subdivisions;
            let request = Request {
                sequence: self.cell.sequence + 1,
                pair_before: self.pair_digest.to_string(),
                driver: interval.driver,
                duration_micros: interval.duration_micros / subdivisions
                    + u64::from(part < interval.duration_micros % subdivisions),
                horizon_micros: interval.horizon_micros,
                reset: interval.reset && final_part,
                content: if final_part { interval.content.clone() } else { None },
            };
            let mut receipt = self.commit(request, if final_part { decoded.take() } else { None })?;
            physics += receipt.physics_execution_nanos;
            native += receipt.native_execution_micros;
            journal += receipt.journal_bytes_written;
            witness += receipt.witness_bytes_written;
            checkpoint += receipt.physics_checkpoint_bytes_written;
            durable += receipt.durable_bytes_written;
            jumps.append(&mut receipt.jumps);
            last = Some(receipt);
        }
        let mut receipt = last.ok_or("empty interval")?;
        receipt.jumps = jumps;
        receipt.scheduled_commits = subdivisions;
        receipt.physics_execution_nanos = physics;
        receipt.native_execution_micros = native;
        receipt.journal_bytes_written = journal;
        receipt.witness_bytes_written = witness;
        receipt.physics_checkpoint_bytes_written = checkpoint;
        receipt.durable_bytes_written = durable;
        receipt.content_execution_nanos = content_nanos;
        receipt.complete_owner_nanos = start.elapsed().as_nanos().try_into().unwrap_or(u64::MAX);
        Ok(receipt)
    }
}
