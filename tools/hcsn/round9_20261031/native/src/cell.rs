//! Frozen five-state regenerative CTMC, not an exact continuum diffusion solver.
//! Split intervals preserve the sampled integrated-hazard budget and RNG stream.
use codex_hepta_types::Digest32;
use serde::Deserialize;
use serde::Serialize;

#[derive(Clone, Copy, Debug, Deserialize, Serialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum Family {
    Ordinary,
    Distribution,
    Sampled,
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct Snapshot {
    pub schema: String,
    pub model: String,
    pub family: Family,
    pub sequence: u64,
    pub elapsed_micros: u64,
    pub probability_bits: [String; 5],
    pub gates_bits: [String; 2],
    pub event_count_bits: String,
    pub index: usize,
    pub rng_state_hex: String,
    pub rng_draws: u64,
    pub hazard_bits: String,
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq)]
pub struct Jump {
    pub elapsed_seconds: f64,
    pub before: usize,
    pub after: usize,
    pub fired: bool,
}

#[derive(Clone)]
pub struct Cell {
    pub parameters: [f64; 11],
    pub family: Family,
    pub model: Digest32,
    pub sequence: u64,
    pub elapsed_micros: u64,
    pub probability: [f64; 5],
    pub gates: [f64; 2],
    pub events: f64,
    pub index: usize,
    rng: u64,
    draws: u64,
    hazard: f64,
}

fn sigmoid(x: f64) -> f64 {
    1.0 / (1.0 + (-x).exp())
}
fn bits(x: f64) -> String {
    format!("{:016x}", x.to_bits())
}
fn number(x: &str) -> Result<f64, String> {
    if x.len() != 16 {
        return Err("noncanonical float bits".into());
    }
    let value = f64::from_bits(u64::from_str_radix(x, 16).map_err(|e| e.to_string())?);
    if !value.is_finite() || bits(value) != x {
        return Err("invalid float bits".into());
    }
    Ok(value)
}

impl Cell {
    pub fn new(parameters: [f64; 11], family: Family, seed: u64) -> Result<Self, String> {
        if parameters.iter().any(|x| !x.is_finite() || x.abs() > 3.0) {
            return Err("parameter domain".into());
        }
        let mut binding = b"hcsn.native-finite-cell.v1;splitmix64-open52;hazard-retained".to_vec();
        binding.push(match family {
            Family::Ordinary => 0,
            Family::Distribution => 1,
            Family::Sampled => 2,
        });
        for p in parameters {
            binding.extend_from_slice(&p.to_bits().to_le_bytes());
        }
        let mut cell = Self {
            parameters,
            family,
            model: Digest32::of_bytes(&binding),
            sequence: 0,
            elapsed_micros: 0,
            probability: [0.0; 5],
            gates: [0.5; 2],
            events: 0.0,
            index: 0,
            rng: seed,
            draws: 0,
            hazard: 0.0,
        };
        cell.probability = cell.origin();
        if family == Family::Sampled {
            cell.index = cell.choose(&cell.origin());
            cell.hazard = -cell.uniform().ln();
        }
        Ok(cell)
    }

    // SplitMix64 is a reproducible simulation generator, not a security primitive.
    fn uniform(&mut self) -> f64 {
        self.rng = self.rng.wrapping_add(0x9e3779b97f4a7c15);
        let mut z = self.rng;
        z = (z ^ (z >> 30)).wrapping_mul(0xbf58476d1ce4e5b9);
        z = (z ^ (z >> 27)).wrapping_mul(0x94d049bb133111eb);
        z ^= z >> 31;
        self.draws += 1;
        // Midpoints of 2^52 bins: strictly inside (0,1), exactly representable.
        ((z >> 12) as f64 + 0.5) / 4503599627370496.0
    }
    fn choose(&mut self, weights: &[f64; 5]) -> usize {
        let target = self.uniform() * weights.iter().sum::<f64>();
        let mut total = 0.0;
        for (i, w) in weights.iter().enumerate() {
            total += w;
            if target < total {
                return i;
            }
        }
        weights
            .iter()
            .rposition(|x| *x > 0.0)
            .expect("positive transition mass")
    }
    fn origin(&self) -> [f64; 5] {
        let boundary = 0.8 + 0.4 * sigmoid(self.parameters[3]);
        let reset = -0.3 + 0.2 * sigmoid(self.parameters[4]);
        let x = (reset + 1.0) / ((boundary + 1.0) / 3.0) - 0.5;
        let left = x.floor() as usize;
        let mut p = [0.0; 5];
        p[left] = left as f64 + 1.0 - x;
        p[left + 1] = x - left as f64;
        p
    }
    pub fn generator(&self, driver: f64) -> [[f64; 6]; 6] {
        let p = self.parameters;
        let drift = 0.1 + 0.8 * sigmoid(p[0] + p[1] * driver);
        let sigma = 0.25 + 0.25 * sigmoid(p[2]);
        let h = (1.8 + 0.4 * sigmoid(p[3])) / 3.0;
        let diffusion = sigma * sigma / (2.0 * h * h);
        let up = diffusion + drift / h;
        let recovery = 2.0 / (0.3 + 0.5 * sigmoid(p[5]));
        let mut q = [[0.0; 6]; 6];
        for (i, row) in q.iter_mut().enumerate().take(3) {
            if i > 0 {
                row[i - 1] = diffusion;
                row[i] -= diffusion;
            }
            row[if i == 2 { 4 } else { i + 1 }] = up;
            row[i] -= up;
        }
        q[2][5] = up; // reward accumulator: number of repeated latent fires.
        q[4][3] = recovery;
        q[4][4] = -recovery;
        for (i, weight) in self.origin().iter().enumerate().take(3) {
            q[3][i] = recovery * weight;
        }
        q[3][3] = -recovery;
        q
    }
    fn gates_rates(&self, driver: f64) -> [f64; 2] {
        std::array::from_fn(|i| {
            let x = self.parameters[3 * i]
                + self.parameters[3 * i + 1] * driver
                + self.parameters[3 * i + 2] * driver * driver;
            x.max(0.0) + (-x.abs()).exp().ln_1p()
        })
    }
    pub fn query(&self, driver: f64, horizon_micros: u64) -> Result<[f64; 5], String> {
        domain(driver, horizon_micros)?;
        if horizon_micros == 0 {
            return Err("positive query horizon required".into());
        }
        let t = horizon_micros as f64 / 1e6;
        let mut result = [0.0; 5];
        if self.family == Family::Ordinary {
            let rates = self.gates_rates(driver);
            result[..4].copy_from_slice(&[
                self.gates[0],
                self.gates[1],
                -(-rates[0] * t).exp_m1(),
                -(-rates[1] * t).exp_m1(),
            ]);
        } else {
            let mut p = [0.0; 6];
            if self.family == Family::Sampled {
                p[self.index] = 1.0;
            } else {
                p[..5].copy_from_slice(&self.probability);
            }
            let q = self.generator(driver);
            let propagated = uniformize(p, q, t)?;
            let mut killed = q;
            killed[2][4] = 0.0;
            // Retain the firing flux into an absorbing accumulator. Positive
            // summation preserves tiny hits that 1 - survival would cancel.
            let hit = uniformize(p, killed, t)?[5];
            let count = propagated[5];
            if !(-2e-11..=1.0 + 2e-11).contains(&hit) || count + 2e-11 < hit {
                return Err("event contract".into());
            }
            result[..4].copy_from_slice(&[
                (p[0] + 3.0 * p[1] + 5.0 * p[2]) / 6.0,
                p[3] + p[4],
                count / (1.0 + count),
                hit.clamp(0.0, 1.0),
            ]);
        }
        result[4] = sigmoid(
            result[..4]
                .iter()
                .zip(&self.parameters[6..10])
                .map(|(x, w)| x * w)
                .sum::<f64>()
                + self.parameters[10],
        );
        Ok(result)
    }
    pub fn advance(&mut self, sequence: u64, driver: f64, micros: u64, reset: bool) -> Result<Vec<Jump>, String> {
        domain(driver, micros)?;
        if self.sequence.checked_add(1) != Some(sequence) {
            return Err("duplicate/stale sequence".into());
        }
        let end = self.elapsed_micros.checked_add(micros).ok_or("clock overflow")?;
        if end > (1_u64 << 52) {
            return Err("clock precision envelope".into());
        }
        let mut next = self.clone();
        let t = micros as f64 / 1e6;
        let mut jumps = Vec::new();
        match self.family {
            Family::Ordinary => {
                let rates = next.gates_rates(driver);
                let target = [sigmoid(2.0 * driver), driver * driver];
                for i in 0..2 {
                    let retain = (-rates[i] * t).exp();
                    next.gates[i] = retain * next.gates[i] + (1.0 - retain) * target[i];
                }
                if reset {
                    next.gates = [0.5; 2];
                }
            }
            Family::Distribution => {
                let mut p = [0.0; 6];
                p[..5].copy_from_slice(&self.probability);
                let out = uniformize(p, next.generator(driver), t)?;
                next.events += out[5];
                next.probability.copy_from_slice(&out[..5]);
                if reset {
                    next.probability = next.origin();
                }
            }
            Family::Sampled => {
                let q = next.generator(driver);
                let mut spent = 0.0;
                loop {
                    let rate = -q[next.index][next.index];
                    let remaining = t - spent;
                    if next.hazard > rate * remaining {
                        next.hazard -= rate * remaining;
                        break;
                    }
                    spent += next.hazard / rate;
                    let mut weights = [0.0; 5];
                    weights.copy_from_slice(&q[next.index][..5]);
                    weights[next.index] = 0.0;
                    let after = next.choose(&weights);
                    let fired = next.index == 2 && after == 4;
                    jumps.push(Jump {
                        elapsed_seconds: self.elapsed_micros as f64 / 1e6 + spent,
                        before: next.index,
                        after,
                        fired,
                    });
                    next.events += f64::from(u8::from(fired));
                    next.index = after;
                    next.hazard = -next.uniform().ln();
                    if jumps.len() > 100_000 {
                        return Err("event budget".into());
                    }
                }
                if reset {
                    next.index = next.choose(&next.origin());
                    next.hazard = -next.uniform().ln();
                }
            }
        }
        next.sequence = sequence;
        next.elapsed_micros = end;
        next.validate()?;
        *self = next;
        Ok(jumps)
    }
    fn validate(&self) -> Result<(), String> {
        if self.draws > (1_u64 << 52)
            || !self.events.is_finite()
            || self.events < 0.0
            || self.index >= 5
            || !self.hazard.is_finite()
            || self.probability.iter().any(|x| !x.is_finite() || *x < -2e-12)
            || (self.probability.iter().sum::<f64>() - 1.0).abs() > 2e-10
            || self.gates.iter().any(|x| !x.is_finite() || !(0.0..=1.0).contains(x))
            || (self.family == Family::Sampled && self.hazard <= 0.0)
        {
            return Err("invalid physical state".into());
        }
        Ok(())
    }
    pub fn snapshot(&self) -> Snapshot {
        Snapshot {
            schema: "hcsn.native-cell-state.v1".into(),
            model: self.model.to_string(),
            family: self.family,
            sequence: self.sequence,
            elapsed_micros: self.elapsed_micros,
            probability_bits: self.probability.map(bits),
            gates_bits: self.gates.map(bits),
            event_count_bits: bits(self.events),
            index: self.index,
            rng_state_hex: format!("{:016x}", self.rng),
            rng_draws: self.draws,
            hazard_bits: bits(self.hazard),
        }
    }
    pub fn restore(&mut self, s: &Snapshot) -> Result<(), String> {
        if s.schema != "hcsn.native-cell-state.v1"
            || s.model != self.model.to_string()
            || s.family != self.family
            || s.elapsed_micros > (1_u64 << 52)
            || s.rng_state_hex.len() != 16
        {
            return Err("snapshot binding".into());
        }
        let mut next = self.clone();
        for (target, source) in next.probability.iter_mut().zip(&s.probability_bits) {
            *target = number(source)?;
        }
        for (target, source) in next.gates.iter_mut().zip(&s.gates_bits) {
            *target = number(source)?;
        }
        next.events = number(&s.event_count_bits)?;
        next.hazard = number(&s.hazard_bits)?;
        next.rng = u64::from_str_radix(&s.rng_state_hex, 16).map_err(|e| e.to_string())?;
        next.index = s.index;
        next.draws = s.rng_draws;
        next.sequence = s.sequence;
        next.elapsed_micros = s.elapsed_micros;
        if format!("{:016x}", next.rng) != s.rng_state_hex {
            return Err("noncanonical rng".into());
        }
        next.validate()?;
        *self = next;
        Ok(())
    }
}

fn domain(driver: f64, micros: u64) -> Result<(), String> {
    if !driver.is_finite() || driver.abs() > 1.0 || micros > 128_000_000 {
        return Err("driver/duration envelope".into());
    }
    Ok(())
}

/// Positive uniformization with scaling and absolute/accumulator-relative
/// truncation criteria. Geometric Poisson remainder estimates below apply in
/// exact arithmetic to this nonnegative substochastic active kernel and linear
/// reward; they are not a certificate for accumulated floating-point error.
fn uniformize(mut p: [f64; 6], q: [[f64; 6]; 6], t: f64) -> Result<[f64; 6], String> {
    if t == 0.0 {
        return Ok(p);
    }
    let rate = (0..5).map(|i| -q[i][i]).fold(0.0_f64, f64::max);
    let parts = (rate * t / 8.0).ceil().max(1.0) as usize;
    let mu = rate * t / parts as f64;
    let mut u = q;
    for (i, row) in u.iter_mut().enumerate() {
        for (j, x) in row.iter_mut().enumerate() {
            *x = *x / rate + f64::from(u8::from(i == j));
        }
    }
    for _ in 0..parts {
        let mass = p[..5].iter().sum::<f64>();
        let initial_reward = p[5];
        let reward_per_jump = u[..5].iter().map(|row| row[5]).fold(0.0_f64, f64::max);
        let mut term = p;
        let mut weight = (-mu).exp();
        let mut sum = term.map(|x| x * weight);
        let mut converged = false;
        for k in 1..256 {
            term = std::array::from_fn(|j| (0..6).map(|i| term[i] * u[i][j]).sum());
            weight *= mu / k as f64;
            for j in 0..6 {
                sum[j] += weight * term[j];
            }
            if k as f64 > mu {
                let ratio = mu / (k + 1) as f64;
                // w_(k+j) <= w_k ratio^j. The reward after k+j embedded
                // steps is <= initial_reward + mass*b*(k+j).
                let remaining_mass = weight * ratio / (1.0 - ratio);
                let remaining_steps = remaining_mass / (1.0 - ratio);
                let reward_tail = initial_reward * remaining_mass
                    + mass * reward_per_jump * (k as f64 * remaining_mass + remaining_steps);
                let relative_ok = reward_per_jump == 0.0 || (sum[5] > 0.0 && reward_tail <= 8e-15 * sum[5]);
                if mass * remaining_mass <= 1e-16 && reward_tail <= 1e-16 && relative_ok {
                    converged = true;
                    break;
                }
            }
        }
        if !converged {
            return Err("uniformization truncation limit".into());
        }
        p = sum;
    }
    if p.iter().any(|x| !x.is_finite()) {
        return Err("nonfinite uniformization".into());
    }
    Ok(p)
}
