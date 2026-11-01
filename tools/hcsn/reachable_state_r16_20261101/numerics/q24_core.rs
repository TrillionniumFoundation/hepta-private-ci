//! Integer-only Q24 probability arithmetic for the finite R15 operator.
//!
//! Largest-remainder Q24 counts have a separate structural-support bitmap.
//! A positive probability can round to zero counts, but does not become an
//! impossible hypothesis. An unresolved zero-likelihood observation requests
//! more precision instead of guessing its posterior or injecting tail mass.

pub const SCALE: u32 = 1 << 24;
pub const MAX_STATES: usize = 512;
pub type Outcome<T> = Result<T, &'static str>;

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Probability {
    pub counts: Vec<u32>,
    pub support: Vec<bool>,
    /// Ceiling of the L1 error bound multiplied by SCALE (at most 2*SCALE).
    pub error_units: u32,
}

pub fn ceil_ratio(numerator: u128, denominator: u128) -> Outcome<u128> {
    if denominator == 0 {
        return Err("zero denominator");
    }
    Ok(numerator / denominator + u128::from(numerator % denominator != 0))
}

pub fn apportion(weights: &[u128]) -> Outcome<Probability> {
    if weights.is_empty() || weights.len() > MAX_STATES {
        return Err("unsupported probability dimension");
    }
    let total = weights.iter().try_fold(0u128, |sum, weight| {
        sum.checked_add(*weight).ok_or("weight sum overflow")
    })?;
    if total == 0 {
        return Err("zero probability mass");
    }
    let support = weights.iter().map(|weight| *weight > 0).collect::<Vec<_>>();
    let mut counts = vec![0u32; weights.len()];
    let mut remainders = Vec::with_capacity(weights.len());
    let mut allocated = 0u32;
    for (index, weight) in weights.iter().enumerate() {
        if *weight > 0 {
            let product = weight
                .checked_mul(u128::from(SCALE))
                .ok_or("apportionment product overflow")?;
            let floor = u32::try_from(product / total).map_err(|_| "count overflow")?;
            counts[index] = floor;
            allocated += floor;
            remainders.push((product % total, index));
        }
    }
    remainders.sort_unstable_by(|a, b| b.0.cmp(&a.0).then_with(|| a.1.cmp(&b.1)));
    for (_, index) in remainders.iter().take((SCALE - allocated) as usize) {
        counts[*index] += 1;
    }
    let discrepancy = counts
        .iter()
        .zip(weights)
        .try_fold(0u128, |sum, (count, weight)| {
            let left = u128::from(*count)
                .checked_mul(total)
                .ok_or("radius overflow")?;
            let right = weight
                .checked_mul(u128::from(SCALE))
                .ok_or("radius overflow")?;
            sum.checked_add(left.abs_diff(right))
                .ok_or("radius sum overflow")
        })?;
    let error_units =
        u32::try_from(ceil_ratio(discrepancy, total)?).map_err(|_| "radius conversion overflow")?;
    let result = Probability {
        counts,
        support,
        error_units,
    };
    result.validate()?;
    Ok(result)
}

impl Probability {
    pub fn validate(&self) -> Outcome<()> {
        if self.counts.is_empty()
            || self.counts.len() > MAX_STATES
            || self.counts.iter().any(|count| *count > SCALE)
            || self.support.len() != self.counts.len()
            || self
                .counts
                .iter()
                .zip(&self.support)
                .any(|(count, support)| *count > 0 && !support)
            || self
                .counts
                .iter()
                .map(|count| u64::from(*count))
                .sum::<u64>()
                != u64::from(SCALE)
            || self.error_units > 2 * SCALE
        {
            return Err("invalid normalized Q24 probability");
        }
        Ok(())
    }
}

#[derive(Clone, Debug)]
pub struct Kernel {
    pub rows: Vec<Probability>,
    pub ticks: u64,
    pub max_error_units: u32,
}

impl Kernel {
    pub fn new(weights: &[Vec<u128>], ticks: u64) -> Outcome<Self> {
        let size = weights.len();
        if size == 0 || size > MAX_STATES || weights.iter().any(|row| row.len() != size) {
            return Err("non-square transition");
        }
        let rows = weights
            .iter()
            .map(|row| apportion(row))
            .collect::<Outcome<Vec<_>>>()?;
        let max_error_units = rows.iter().map(|row| row.error_units).max().unwrap_or(0);
        Ok(Self {
            rows,
            ticks,
            max_error_units,
        })
    }
}

#[derive(Clone, Debug)]
pub struct Emission {
    pub rows: Vec<Probability>,
    pub max_error_units: u32,
}

impl Emission {
    pub fn new(weights: &[Vec<u128>]) -> Outcome<Self> {
        let columns = weights.first().ok_or("empty emission")?.len();
        if weights.len() > MAX_STATES || weights.iter().any(|row| row.len() != columns) {
            return Err("ragged emission");
        }
        let rows = weights
            .iter()
            .map(|row| apportion(row))
            .collect::<Outcome<Vec<_>>>()?;
        let max_error_units = rows.iter().map(|row| row.error_units).max().unwrap_or(0);
        Ok(Self {
            rows,
            max_error_units,
        })
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Memory {
    pub addresses: Vec<Probability>,
    pub completed: u64,
    pub clock_ticks: u64,
}

impl Memory {
    pub fn validate(&self) -> Outcome<()> {
        if self.addresses.is_empty() || self.addresses.len() > 64 {
            return Err("unsupported address count");
        }
        let size = self.addresses[0].counts.len();
        for address in &self.addresses {
            address.validate()?;
            if address.counts.len() != size {
                return Err("inconsistent address dimensions");
            }
        }
        Ok(())
    }

    pub fn advance(&mut self, kernel: &Kernel, maximum_error: u32) -> Outcome<()> {
        self.validate()?;
        let size = kernel.rows.len();
        if self.addresses[0].counts.len() != size {
            return Err("transition dimension mismatch");
        }
        let completed = self
            .completed
            .checked_add(1)
            .ok_or("operation counter overflow")?;
        let clock_ticks = self
            .clock_ticks
            .checked_add(kernel.ticks)
            .ok_or("clock overflow")?;
        let mut next = Vec::with_capacity(self.addresses.len());
        for address in &self.addresses {
            let mut weights = vec![0u128; size];
            let mut support = vec![false; size];
            for (source, count) in address.counts.iter().enumerate() {
                for (destination, weight) in weights.iter_mut().enumerate() {
                    *weight +=
                        u128::from(*count) * u128::from(kernel.rows[source].counts[destination]);
                    support[destination] |=
                        address.support[source] && kernel.rows[source].support[destination];
                }
            }
            let mut result = apportion(&weights)?;
            result.support = support;
            result.validate()?;
            result.error_units =
                (result.error_units + address.error_units + kernel.max_error_units).min(2 * SCALE);
            if result.error_units > maximum_error {
                return Err("precision required: transition error budget");
            }
            next.push(result);
        }
        self.addresses = next;
        self.completed = completed;
        self.clock_ticks = clock_ticks;
        Ok(())
    }

    pub fn observe(
        &mut self,
        address: usize,
        emission: &Emission,
        token: usize,
        maximum_error: u32,
    ) -> Outcome<()> {
        self.validate()?;
        let previous = self.addresses.get(address).ok_or("unknown address")?;
        if emission.rows.len() != previous.counts.len()
            || token >= emission.rows.first().ok_or("empty emission")?.counts.len()
        {
            return Err("invalid emission dimension or token");
        }
        let weights = previous
            .counts
            .iter()
            .enumerate()
            .map(|(index, count)| {
                u128::from(*count) * u128::from(emission.rows[index].counts[token])
            })
            .collect::<Vec<_>>();
        let evidence = weights.iter().sum::<u128>();
        let support = previous
            .support
            .iter()
            .enumerate()
            .map(|(index, possible)| *possible && emission.rows[index].support[token])
            .collect::<Vec<_>>();
        if evidence == 0 {
            return Err(if support.iter().any(|possible| *possible) {
                "precision required: positive observation below Q24 resolution"
            } else {
                "impossible observation"
            });
        }
        let mut posterior = apportion(&weights)?;
        posterior.support = support;
        posterior.validate()?;
        let uncertainty = u128::from(previous.error_units + emission.max_error_units);
        let amplified = ceil_ratio(2 * uncertainty * u128::from(SCALE).pow(2), evidence)?;
        posterior.error_units =
            (amplified + u128::from(posterior.error_units)).min(u128::from(2 * SCALE)) as u32;
        if posterior.error_units > maximum_error {
            return Err("precision required: observation error budget");
        }
        let completed = self
            .completed
            .checked_add(1)
            .ok_or("operation counter overflow")?;
        self.addresses[address] = posterior;
        self.completed = completed;
        Ok(())
    }

    pub fn write(&mut self, address: usize, content: usize, classes: usize) -> Outcome<()> {
        self.validate()?;
        let previous = self.addresses.get(address).ok_or("unknown address")?;
        let size = previous.counts.len();
        if classes == 0 || size % classes != 0 || content >= classes {
            return Err("invalid typed write");
        }
        let mut counts = vec![0; size];
        let mut support = vec![false; size];
        for (phase, row) in previous.counts.chunks_exact(classes).enumerate() {
            counts[phase * classes + content] = row.iter().sum();
            support[phase * classes + content] = previous.support
                [phase * classes..(phase + 1) * classes]
                .iter()
                .any(|possible| *possible);
        }
        let completed = self
            .completed
            .checked_add(1)
            .ok_or("operation counter overflow")?;
        self.addresses[address] = Probability {
            counts,
            support,
            error_units: previous.error_units,
        };
        self.completed = completed;
        Ok(())
    }
}
