//! Piecewise-constant CTMC paths with model changes at a declared clock time.
//! Pending randomness is unit-exponential exposure, never an old destination.
use crate::core;
use crate::prepared::Model;
use crate::sha256;
use std::sync::Arc;

pub struct Jump {
    pub time: f64,
    pub from: usize,
    pub to: usize,
    pub kind: &'static str,
    pub version: u64,
}

#[derive(Clone, Copy)]
pub enum HazardPolicy {
    PreserveExposure,
    Resample,
}

pub struct PathState {
    pub model: Arc<Model>,
    pub current: usize,
    pub time: f64,
    pub hazard_anchor: f64,
    pub threshold: f64,
    pub rng: u64,
    pub counts: [u64; 5],
    pub migrations: u64,
    pub history: String,
}

impl PathState {
    pub fn kind(n: usize, from: usize, to: usize) -> Result<&'static str, String> {
        let active = n / 2 - 2;
        let width = active + 2;
        let (a, b, same) = (from % width, to % width, from / width == to / width);
        if a == 0 && b == active && same {
            return Ok("first_hit");
        }
        if a == active && b == active + 1 && same {
            return Ok("refractory_phase");
        }
        if a == active + 1 && b < active {
            return Ok(if same { "reset_keep" } else { "reset_switch" });
        }
        if a < active && b < active && same && a.abs_diff(b) == 1 {
            return Ok("active_jump");
        }
        Err("Transition violates active/recovery/content layout".into())
    }

    pub fn validate_layout(model: &Model) -> Result<(), String> {
        if model.n < 6 || model.n % 2 != 0 {
            return Err("Expected two content blocks and two recovery phases".into());
        }
        for i in 0..model.n {
            for j in 0..model.n {
                if i != j && model.q[i * model.n + j] > 0.0 {
                    Self::kind(model.n, i, j)?;
                }
            }
        }
        Ok(())
    }

    pub fn validate(&self) -> Result<(), String> {
        Self::validate_layout(&self.model)?;
        if self.current >= self.model.n
            || !self.time.is_finite()
            || self.time < 0.0
            || !self.hazard_anchor.is_finite()
            || self.hazard_anchor < 0.0
            || self.hazard_anchor > self.time
            || !self.threshold.is_finite()
            || self.threshold <= 0.0
            || self.history.len() != 64
            || !self.history.bytes().all(|c| c.is_ascii_hexdigit())
            || self.counts[4] > self.counts[3]
            || self.counts[1..4]
                .iter()
                .try_fold(0u64, |a, b| a.checked_add(*b))
                .is_none_or(|x| x > self.counts[0])
        {
            return Err("Invalid trajectory state/exposure/counters".into());
        }
        if self.next_time()? < self.time {
            return Err("Pending exposure has already expired".into());
        }
        Ok(())
    }

    pub fn new(model: Arc<Model>, prior: &[f64], seed: u64) -> Result<Self, String> {
        Self::validate_layout(&model)?;
        if prior.len() != model.n {
            return Err("Prior dimension differs from Q".into());
        }
        core::probability_mass(prior).map_err(|e| format!("Invalid prior: {e:?}"))?;
        let mut state = Self {
            model,
            current: 0,
            time: 0.0,
            hazard_anchor: 0.0,
            threshold: 1.0,
            rng: seed,
            counts: [0; 5],
            migrations: 0,
            history: sha256::hex(b"hcsn-r13-exposure-events-v1"),
        };
        let draw = state.uniform();
        let mut cumulative = 0.0;
        for (index, value) in prior.iter().enumerate() {
            cumulative += value;
            if *value > 0.0 {
                state.current = index;
            }
            if draw < cumulative {
                break;
            }
        }
        state.threshold = -state.uniform().ln();
        state.validate()?;
        Ok(state)
    }

    fn uniform(&mut self) -> f64 {
        self.rng = self.rng.wrapping_add(0x9e3779b97f4a7c15);
        let mut x = self.rng;
        x = (x ^ (x >> 30)).wrapping_mul(0xbf58476d1ce4e5b9);
        x = (x ^ (x >> 27)).wrapping_mul(0x94d049bb133111eb);
        x ^= x >> 31;
        ((x >> 12) + 1) as f64 / 4503599627370497.0
    }

    pub fn rate(&self) -> f64 {
        -self.model.q[self.current * self.model.n + self.current]
    }

    pub fn next_time(&self) -> Result<f64, String> {
        let rate = self.rate();
        if rate == 0.0 {
            return Ok(f64::INFINITY);
        }
        let at = self.hazard_anchor + self.threshold / rate;
        if !at.is_finite() || at <= self.hazard_anchor {
            return Err("Next clock is not resolvable in float64".into());
        }
        Ok(at)
    }

    pub fn remaining_exposure(&self) -> f64 {
        self.threshold - self.rate() * (self.time - self.hazard_anchor)
    }

    pub fn advance_to(&mut self, target: f64) -> Result<Vec<Jump>, String> {
        if !target.is_finite() || target < self.time {
            return Err("Invalid/backward clock".into());
        }
        let mut jumps = Vec::new();
        while self.next_time()? <= target {
            if jumps.len() >= 1_000_000 {
                return Err("Event budget exceeded".into());
            }
            let at = self.next_time()?;
            let from = self.current;
            let draw = self.uniform() * self.rate();
            let mut cumulative = 0.0;
            let mut to = from;
            for j in 0..self.model.n {
                if j == from {
                    continue;
                }
                let rate = self.model.q[from * self.model.n + j];
                cumulative += rate;
                if rate > 0.0 {
                    to = j;
                }
                if draw < cumulative {
                    break;
                }
            }
            let kind = Self::kind(self.model.n, from, to)?;
            let increments = [
                true,
                kind == "first_hit",
                kind == "refractory_phase",
                kind == "reset_keep" || kind == "reset_switch",
                kind == "reset_switch",
            ];
            for (count, increment) in self.counts.iter_mut().zip(increments) {
                *count = count
                    .checked_add(u64::from(increment))
                    .ok_or("Counter overflow")?;
            }
            let mut digest = self.history.as_bytes().to_vec();
            digest.extend_from_slice(&at.to_bits().to_be_bytes());
            digest.extend_from_slice(&(from as u64).to_be_bytes());
            digest.extend_from_slice(&(to as u64).to_be_bytes());
            digest.extend_from_slice(self.model.identity.as_bytes());
            self.history = sha256::hex(&digest);
            jumps.push(Jump {
                time: at,
                from,
                to,
                kind,
                version: self.model.version,
            });
            self.current = to;
            self.time = at;
            self.hazard_anchor = at;
            self.threshold = -self.uniform().ln();
        }
        self.time = target;
        Ok(jumps)
    }

    pub fn migrate(
        &mut self,
        at: f64,
        model: Arc<Model>,
        policy: HazardPolicy,
    ) -> Result<Vec<Jump>, String> {
        Self::validate_layout(&model)?;
        if model.n != self.model.n || model.version <= self.model.version {
            return Err(
                "Migration requires the same state layout and a newer model version".into(),
            );
        }
        // Old-Q events at exactly at are processed before the right-continuous update.
        let jumps = self.advance_to(at)?;
        let remaining = self.remaining_exposure();
        if !remaining.is_finite() || remaining <= 0.0 {
            return Err("Residual exposure cannot be represented positively".into());
        }
        let mut digest = self.history.as_bytes().to_vec();
        digest.extend_from_slice(b"MIGRATE");
        digest.extend_from_slice(&at.to_bits().to_be_bytes());
        digest.extend_from_slice(model.identity.as_bytes());
        digest.push(match policy {
            HazardPolicy::PreserveExposure => 0,
            HazardPolicy::Resample => 1,
        });
        self.history = sha256::hex(&digest);
        self.threshold = match policy {
            HazardPolicy::PreserveExposure => remaining,
            HazardPolicy::Resample => -self.uniform().ln(),
        };
        self.hazard_anchor = at;
        self.model = model;
        self.migrations = self
            .migrations
            .checked_add(1)
            .ok_or("Migration count overflow")?;
        self.validate()?;
        Ok(jumps)
    }
}
