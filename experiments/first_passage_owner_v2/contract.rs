//! Versioned, bounded research state. The observation producer supplies physics.
use codex_hepta_types::Digest32;
use serde::Deserialize;
use serde::Serialize;

pub const PROFILE: &str = "hepta.fpt.owner-adoption.v2";
pub const ZERO: &str = "0000000000000000000000000000000000000000000000000000000000000000";
pub const LIMIT: u64 = 256;
pub const DAY_US: u64 = 86_400_000_000;
pub const PRICE_SCALE: i128 = 4_000_000;

pub fn hash<T: Serialize>(value: &T) -> Result<String, String> {
    serde_json::to_vec(value)
        .map(|bytes| Digest32::of_bytes(&bytes).to_string())
        .map_err(|e| e.to_string())
}

pub fn digest(value: &str) -> Result<Digest32, String> {
    value.parse().map_err(|e| format!("digest: {e}"))
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct Model {
    pub drift: f64,
    pub weights: [f64; 2],
    pub interaction: f64,
    pub sigma: f64,
    pub cancel_rate: f64,
    pub barrier: f64,
    pub reset_gap: f64,
    pub refractory_us: u64,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub struct CreditRule {
    pub initial_micros: i64,
    pub maximum_micros: i64,
    pub step_micros: i64,
    pub target_quarters: i64,
    pub maximum_read_price_micros: i64,
}

impl CreditRule {
    pub fn next(&self, prior: i64, residue: i64, attempts: u64, elapsed_us: u64) -> (i64, i64) {
        let balance = i128::from(prior) * PRICE_SCALE + i128::from(residue);
        let ceiling = i128::from(self.maximum_micros) * PRICE_SCALE;
        // Idle time expires first. It cannot bank a negative price for a later read.
        let idle = (balance
            - i128::from(self.step_micros)
                * i128::from(self.target_quarters)
                * i128::from(elapsed_us))
        .clamp(0, ceiling);
        let next = (idle + i128::from(self.step_micros) * PRICE_SCALE * i128::from(attempts))
            .clamp(0, ceiling);
        ((next / PRICE_SCALE) as i64, (next % PRICE_SCALE) as i64)
    }

    pub fn permits(&self, price: i64, residue: i64) -> bool {
        i128::from(price) * PRICE_SCALE + i128::from(residue)
            <= i128::from(self.maximum_read_price_micros) * PRICE_SCALE
    }
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct Config {
    pub run_id: String,
    pub objective_digest: String,
    pub artifact_digest: String,
    pub model: Model,
    pub deadline_us: u64,
    pub read_budget: u64,
    pub credit: CreditRule,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(tag = "kind", deny_unknown_fields)]
pub enum Phase {
    Active,
    Refractory { until_us: u64 },
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub struct Cancellation {
    pub seed: u64,
    pub counter: u64,
    pub at_us: Option<u64>,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct Checkpoint {
    pub level: f64,
    pub time_us: u64,
    pub phase: Phase,
    pub events: u64,
    pub rng_seed: u64,
    pub rng_counter: u64,
    pub cancellation: Cancellation,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(tag = "kind", deny_unknown_fields)]
pub enum Action {
    Read {
        relative_path: String,
        query: String,
    },
    Wait,
    Stop,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct Request {
    pub schema: String,
    pub sequence: u64,
    pub predecessor: String,
    pub config: Config,
    pub checkpoint: Checkpoint,
    pub hit_times_us: Vec<u64>,
    pub owner_monotonic_us: u64,
    pub expected_price_micros: i64,
    pub expected_price_residue: i64,
    pub ndu_receipt_digest: String,
    pub features_q24: [i64; 5],
    pub action: Action,
}

impl Request {
    pub fn validate(&self, prior: Option<&Self>) -> Result<(), String> {
        let c = &self.config;
        let m = &c.model;
        let s = &self.checkpoint;
        let rule = &c.credit;
        let scalars = [
            m.drift,
            m.weights[0],
            m.weights[1],
            m.interaction,
            m.sigma,
            m.cancel_rate,
            m.barrier,
            m.reset_gap,
            s.level,
        ];
        if self.schema != PROFILE
            || !(1..=LIMIT).contains(&self.sequence)
            || c.run_id.is_empty()
            || c.run_id.len() > 64
            || c.read_budget > LIMIT
            || c.deadline_us > DAY_US
            || s.time_us > c.deadline_us
            || scalars.iter().any(|v| !v.is_finite() || v.abs() > 1e6)
            || !(1e-6..=100.0).contains(&m.sigma)
            || !(0.0..=100.0).contains(&m.cancel_rate)
            || !(1e-6..=1e6).contains(&m.reset_gap)
            || !(1..=DAY_US).contains(&m.refractory_us)
            || self.hit_times_us.len() > 128
            || self.owner_monotonic_us == 0
            || self
                .features_q24
                .iter()
                .any(|v| !(-8 * (1 << 24)..=8 * (1 << 24)).contains(v))
            || !(0..=1_000_000_000).contains(&rule.maximum_micros)
            || !(0..=rule.maximum_micros).contains(&rule.initial_micros)
            || !(0..=1_000_000_000).contains(&rule.step_micros)
            || !(0..=4).contains(&rule.target_quarters)
            || !(0..=rule.maximum_micros).contains(&rule.maximum_read_price_micros)
            || !(0..=rule.maximum_micros).contains(&self.expected_price_micros)
            || !(0..PRICE_SCALE as i64).contains(&self.expected_price_residue)
        {
            return Err("request/model/resource domain".into());
        }
        digest(&self.predecessor)?;
        codex_hepta_types::StableId::new(&c.run_id).map_err(|e| format!("run identity: {e}"))?;
        for value in [
            &c.objective_digest,
            &c.artifact_digest,
            &self.ndu_receipt_digest,
        ] {
            if digest(value)?.is_zero() {
                return Err("missing external identity".into());
            }
        }
        match (&s.phase, s.level) {
            (Phase::Active, level) if level > m.barrier => {}
            (Phase::Refractory { until_us }, level)
                if *until_us > s.time_us
                    && until_us.saturating_sub(s.time_us) <= m.refractory_us
                    && level == m.barrier + m.reset_gap => {}
            _ => return Err("inconsistent physical phase".into()),
        }
        if (m.cancel_rate == 0.0) != s.cancellation.at_us.is_none()
            || s.cancellation.counter != u64::from(m.cancel_rate > 0.0)
            || s.cancellation
                .at_us
                .is_some_and(|t| t == 0 || s.time_us > t)
        {
            return Err("cancellation clock inconsistent with rate/time".into());
        }
        if let Action::Read {
            relative_path,
            query,
        } = &self.action
            && (relative_path.is_empty()
                || relative_path.len() > 512
                || query.len() > 256
                || std::path::Path::new(relative_path)
                    .components()
                    .any(|p| !matches!(p, std::path::Component::Normal(_))))
        {
            return Err("read path/query domain".into());
        }
        if let Some(p) = prior {
            if c != &p.config
                || s.cancellation != p.checkpoint.cancellation
                || s.rng_seed != p.checkpoint.rng_seed
                || s.rng_counter < p.checkpoint.rng_counter
                || s.time_us < p.checkpoint.time_us
                || self.owner_monotonic_us <= p.owner_monotonic_us
            {
                return Err("immutable model/cancel identity or clock changed".into());
            }
            let mut until = match p.checkpoint.phase {
                Phase::Active => 0,
                Phase::Refractory { until_us } => until_us,
            };
            let mut last = p.checkpoint.time_us;
            for &hit in &self.hit_times_us {
                if hit <= last
                    || hit <= until
                    || hit > s.time_us
                    || s.cancellation.at_us.is_some_and(|t| hit >= t)
                {
                    return Err("event order/refractory/cancellation violated".into());
                }
                until = hit
                    .checked_add(m.refractory_us)
                    .ok_or("refractory overflow")?;
                last = hit;
            }
            let phase = if until > s.time_us {
                Phase::Refractory { until_us: until }
            } else {
                Phase::Active
            };
            if s.events
                != p.checkpoint
                    .events
                    .checked_add(self.hit_times_us.len() as u64)
                    .ok_or("event overflow")?
                || s.phase != phase
                || (s.time_us == p.checkpoint.time_us && s != &p.checkpoint)
            {
                return Err("event count or phase continuation changed".into());
            }
            if until != 0 && until >= s.time_us && s.level != m.barrier + m.reset_gap {
                return Err("refractory release changed the reset level".into());
            }
            if matches!(p.checkpoint.phase, Phase::Refractory { until_us } if until_us >= s.time_us)
                && s.rng_counter != p.checkpoint.rng_counter
            {
                return Err("refractory holding consumed a diffusion draw".into());
            }
        } else if self.sequence != 1
            || self.predecessor != ZERO
            || s.time_us != 0
            || s.events != 0
            || !self.hit_times_us.is_empty()
            || s.phase != Phase::Active
            || s.rng_counter != 0
        {
            return Err("invalid initial state".into());
        }
        Ok(())
    }
}
