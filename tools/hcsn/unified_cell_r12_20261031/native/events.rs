//! Gillespie paths for the same finite Q used by belief propagation.
//! A sample path and expected occupancy are deliberately different objects.

use crate::core;
use crate::sha256;

pub struct Jump {
    pub time: f64,
    pub from: usize,
    pub to: usize,
    pub kind: &'static str,
}

pub struct PathState {
    pub q: Vec<f64>,
    pub active: usize,
    pub current: usize,
    pub time: f64,
    pub next_time: f64,
    pub next_state: usize,
    pub rng: u64,
    pub counts: [u64; 5], // all jumps, hits, phases, resets, content switches
    pub history: String,
}

impl PathState {
    pub fn validate(&self) -> Result<(), String> {
        let n = 2 * (self.active + 2);
        if self.active == 0
            || n > core::MAX_DIMENSION
            || self.current >= n
            || self.next_state >= n
            || !self.time.is_finite()
            || self.time < 0.0
            || self.next_time.is_nan()
            || self.next_time < self.time
            || self.q.len() != n * n
        {
            return Err("Invalid trajectory shape/clock".into());
        }
        let mut p = vec![0.0; n];
        p[self.current] = 1.0;
        core::propagate_row(n, &self.q, 0.0, &p).map_err(|e| format!("Invalid path Q: {e:?}"))?;
        for i in 0..n {
            for j in 0..n {
                if i != j && self.q[i * n + j] > 0.0 {
                    self.kind(i, j)?;
                }
            }
        }
        if self.next_time.is_finite()
            && (self.next_state == self.current
                || self.q[self.current * n + self.next_state] <= 0.0)
        {
            return Err("Pending transition is not reachable under the stored Q".into());
        }
        if self.next_time.is_infinite() && self.q[self.current * n + self.current] != 0.0 {
            return Err("Infinite pending time is only allowed in an absorbing state".into());
        }
        Ok(())
    }

    pub fn new(q: Vec<f64>, prior: &[f64], seed: u64) -> Result<Self, String> {
        let n = prior.len();
        if n < 6 || n % 2 != 0 {
            return Err(
                "Expected two content blocks with active cells and two recovery phases".into(),
            );
        }
        core::propagate_row(n, &q, 0.0, prior).map_err(|e| format!("Invalid path input: {e:?}"))?;
        let mut model = Self {
            q,
            active: n / 2 - 2,
            current: 0,
            time: 0.0,
            next_time: f64::INFINITY,
            next_state: 0,
            rng: seed,
            counts: [0; 5],
            history: sha256::hex(b"hcsn-r12-gillespie-v1"),
        };
        let draw = model.uniform();
        let mut cumulative = 0.0;
        for (i, value) in prior.iter().enumerate() {
            cumulative += value;
            if *value > 0.0 {
                model.current = i;
            }
            if draw < cumulative {
                break;
            }
        }
        model.schedule()?;
        model.validate()?;
        Ok(model)
    }

    fn uniform(&mut self) -> f64 {
        self.rng = self.rng.wrapping_add(0x9e3779b97f4a7c15);
        let mut x = self.rng;
        x = (x ^ (x >> 30)).wrapping_mul(0xbf58476d1ce4e5b9);
        x = (x ^ (x >> 27)).wrapping_mul(0x94d049bb133111eb);
        x ^= x >> 31;
        // 52 random bits; both endpoints are excluded without rounding to 1.
        ((x >> 12) + 1) as f64 / 4503599627370497.0
    }

    fn schedule(&mut self) -> Result<(), String> {
        let n = 2 * (self.active + 2);
        let rate = -self.q[self.current * n + self.current];
        if rate == 0.0 {
            self.next_time = f64::INFINITY;
            self.next_state = self.current;
            return Ok(());
        }
        self.next_time = self.time - self.uniform().ln() / rate;
        if !self.next_time.is_finite() || self.next_time <= self.time {
            return Err("Event time not resolvable in f64".into());
        }
        let draw = self.uniform() * rate;
        let mut cumulative = 0.0;
        for j in 0..n {
            if j == self.current {
                continue;
            }
            let rate = self.q[self.current * n + j];
            cumulative += rate;
            if rate > 0.0 {
                self.next_state = j;
            }
            if draw < cumulative {
                break;
            }
        }
        Ok(())
    }

    pub fn kind(&self, from: usize, to: usize) -> Result<&'static str, String> {
        let width = self.active + 2;
        let (a, b, same) = (from % width, to % width, from / width == to / width);
        if a == 0 && b == self.active && same {
            return Ok("first_hit");
        }
        if a == self.active && b == self.active + 1 && same {
            return Ok("refractory_phase");
        }
        if a == self.active + 1 && b < self.active {
            return Ok(if same { "reset_keep" } else { "reset_switch" });
        }
        if a < self.active && b < self.active && same && a.abs_diff(b) == 1 {
            return Ok("active_jump");
        }
        Err("Q transition violates the declared first-hit/recovery layout".into())
    }

    pub fn advance(&mut self, dt: f64) -> Result<Vec<Jump>, String> {
        if !dt.is_finite() || dt < 0.0 || !(self.time + dt).is_finite() {
            return Err("Invalid event interval".into());
        }
        let target = self.time + dt;
        let mut jumps = Vec::new();
        while self.next_time <= target {
            if jumps.len() >= 1_000_000 {
                return Err("Explicit per-interval event budget exceeded".into());
            }
            let (from, to, at) = (self.current, self.next_state, self.next_time);
            let kind = self.kind(from, to)?;
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
                    .ok_or("Event counter overflow")?;
            }
            let mut bytes = self.history.as_bytes().to_vec();
            bytes.extend_from_slice(&at.to_bits().to_be_bytes());
            bytes.extend_from_slice(&(from as u64).to_be_bytes());
            bytes.extend_from_slice(&(to as u64).to_be_bytes());
            self.history = sha256::hex(&bytes);
            jumps.push(Jump {
                time: at,
                from,
                to,
                kind,
            });
            self.current = to;
            self.time = at;
            self.schedule()?;
        }
        self.time = target;
        Ok(jumps)
    }
}
