//! Bounded receding-horizon planning over the actual frozen generation kernel.
//!
//! This is the single-particle, zero-noise specialization of
//! `hepta.ndu.finite-entropic.v1`. Emission randomness is fixed by the admitted
//! sampler seed. Duration forecasts are explicit checkpoint metadata, not
//! measured timings; actual planning/decoder costs remain in the host receipt.

use crate::codec::Packet;
use crate::codec::Result;
use crate::decoder::Prefixes;
use crate::decoder::commit_chunk;
use crate::math::sigmoid;
use crate::model::ACTIONS;
use crate::model::Model;
use crate::model::State;
use crate::observation::DeliveryObservation;
use crate::observation::OwnerContext;
use crate::protocol::EmissionLaw;

pub(crate) const NDU_PROFILE: &str = "ndu-finite-deterministic-v1";
pub(crate) const ACTOR_PROFILE: &str = "actor-greedy-observed-v1";

pub(crate) fn validate_profile(model: &Model) -> Result<()> {
    match model.weights.text("inference_profile")? {
        NDU_PROFILE => Profile::read(model).map(|_| ()),
        ACTOR_PROFILE => Ok(()),
        _ => Err("unknown observed inference profile".into()),
    }
}

#[derive(Clone, Debug, PartialEq)]
pub(crate) struct PlanningReceipt {
    pub(crate) profile: String,
    pub(crate) action: usize,
    pub(crate) horizon: usize,
    pub(crate) forecasts: usize,
    pub(crate) forecast_cap: usize,
    pub(crate) exhausted: bool,
    pub(crate) scored: [bool; 7],
    pub(crate) scores: [f64; 7],
    pub(crate) selected_duration_micros: u64,
}

impl PlanningReceipt {
    pub(crate) fn write_packet(&self, packet: &mut Packet) {
        let (objective, noise) = if self.profile == ACTOR_PROFILE {
            ("actor-probability-argmax-v1", "not-evaluated")
        } else {
            (
                "hepta.ndu.finite-entropic.v1",
                "single-particle-fixed-emission-seed-v1",
            )
        };
        for (key, value) in [
            ("profile", self.profile.clone()),
            ("objective", objective.into()),
            ("noise", noise.into()),
            ("action", self.action.to_string()),
            ("horizon", self.horizon.to_string()),
            ("forecasts", self.forecasts.to_string()),
            ("forecast_cap", self.forecast_cap.to_string()),
            ("exhausted", self.exhausted.to_string()),
            ("duration_micros", self.selected_duration_micros.to_string()),
        ] {
            packet.meta.insert(format!("planning.{key}"), value);
        }
        packet.vector("planning.scores", self.scores.to_vec());
        packet.vector(
            "planning.scored",
            self.scored.map(|value| f64::from(u8::from(value))).to_vec(),
        );
    }

    pub(crate) fn read(packet: &Packet) -> Result<Option<Self>> {
        if !packet.meta.contains_key("planning.profile") {
            return Ok(None);
        }
        let number = |key: &str| -> Result<usize> {
            packet
                .text(&format!("planning.{key}"))?
                .parse()
                .map_err(|_| "invalid planning counter".into())
        };
        let scores: [f64; 7] = packet
            .get("planning.scores")?
            .try_into()
            .map_err(|_| "planning score width")?;
        let mask = packet.get("planning.scored")?;
        if mask.len() != 7 || mask.iter().any(|value| ![0.0, 1.0].contains(value)) {
            return Err("invalid planning score mask".into());
        }
        let receipt = Self {
            profile: packet.text("planning.profile")?.into(),
            action: number("action")?,
            horizon: number("horizon")?,
            forecasts: number("forecasts")?,
            forecast_cap: number("forecast_cap")?,
            exhausted: packet
                .text("planning.exhausted")?
                .parse()
                .map_err(|_| "invalid planner exhaustion")?,
            scored: std::array::from_fn(|index| mask[index] == 1.0),
            scores,
            selected_duration_micros: packet
                .text("planning.duration_micros")?
                .parse()
                .map_err(|_| "invalid duration forecast")?,
        };
        let (objective, noise) = if receipt.profile == ACTOR_PROFILE {
            ("actor-probability-argmax-v1", "not-evaluated")
        } else {
            (
                "hepta.ndu.finite-entropic.v1",
                "single-particle-fixed-emission-seed-v1",
            )
        };
        if ![NDU_PROFILE, ACTOR_PROFILE].contains(&receipt.profile.as_str())
            || receipt.action >= 7
            || !receipt.scored[receipt.action]
            || receipt.horizon > 4
            || receipt.forecast_cap > 512
            || receipt.forecasts > receipt.forecast_cap
            || receipt.scores.iter().any(|value| !value.is_finite())
            || packet.text("planning.objective")? != objective
            || packet.text("planning.noise")? != noise
        {
            return Err("invalid retained planning receipt".into());
        }
        Ok(Some(receipt))
    }
}

struct Profile {
    discount: f64,
    latency_weight: f64,
    horizon: usize,
    cap: usize,
    durations: [u64; 7],
}

impl Profile {
    fn read(model: &Model) -> Result<Self> {
        let f64_value = |name: &str| -> Result<f64> {
            model
                .weights
                .text(name)?
                .parse()
                .map_err(|_| format!("invalid {name}"))
        };
        let usize_value = |name: &str| -> Result<usize> {
            model
                .weights
                .text(name)?
                .parse()
                .map_err(|_| format!("invalid {name}"))
        };
        let risk = f64_value("ndu.risk")?;
        let discount = f64_value("ndu.discount_per_second")?;
        let latency_weight = f64_value("ndu.latency_weight")?;
        let horizon = usize_value("ndu.horizon")?;
        let cap = usize_value("ndu.max_forecasts")?;
        let durations: Vec<u64> = model
            .weights
            .text("ndu.action_micros")?
            .split(',')
            .map(|value| {
                value
                    .parse()
                    .map_err(|_| "invalid action duration".to_string())
            })
            .collect::<Result<_>>()?;
        let durations: [u64; 7] = durations
            .try_into()
            .map_err(|_| "duration forecast width")?;
        if !(risk.is_finite()
            && risk >= 0.0
            && discount.is_finite()
            && 0.0 < discount
            && discount <= 1.0
            && latency_weight.is_finite()
            && latency_weight >= 0.0)
            || !(1..=4).contains(&horizon)
            || !(7..=512).contains(&cap)
            || durations
                .iter()
                .any(|value| *value == 0 || *value > 3_600_000_000)
            || model.weights.text("ndu.critic_output")? != "sigmoid-quality-v1"
        {
            return Err("invalid finite NDU profile".into());
        }
        Ok(Self {
            discount,
            latency_weight,
            horizon,
            cap,
            durations,
        })
    }

    fn edge(&self, duration_micros: u64, future: f64) -> Result<f64> {
        let seconds = duration_micros as f64 / 1_000_000.0;
        let value = -self.latency_weight * seconds + self.discount.powf(seconds) * future;
        if !value.is_finite() {
            return Err("nonfinite recursive utility".into());
        }
        Ok(value)
    }
}

#[derive(Clone)]
struct Node {
    state: State,
    prefixes: Prefixes,
    owner: OwnerContext,
}

struct Search<'a> {
    model: &'a Model,
    public: &'a Packet,
    law: EmissionLaw,
    profile: Profile,
    calls: usize,
    limit: usize,
    exhausted: bool,
}

impl Search<'_> {
    fn inspect(&self, node: &Node) -> Result<Packet> {
        let observation =
            DeliveryObservation::new(&node.owner, &node.prefixes, self.model.total_units())?;
        self.model.inspect_observed(&node.state, &observation)
    }

    fn forecast(&mut self, node: &Node, action: usize) -> Result<Option<Node>> {
        let duration = self.profile.durations[action];
        if duration > node.owner.budget_remaining {
            return Ok(None);
        }
        if self.calls >= self.limit {
            self.exhausted = true;
            return Ok(None);
        }
        self.calls += 1;
        let mut next = node.clone();
        next.owner.budget_remaining -= duration;
        next.state = self
            .model
            .advance(&node.state, ACTIONS[action], self.public)?;
        if action == 6 {
            // Evaluate the bytes that this STOP would actually propose. These
            // hypothetical bytes never enter the host's committed prefix.
            for (index, total) in self.model.total_units().iter().enumerate() {
                if next.owner.required_mask & (1 << index) == 0 && next.prefixes.cursors[index] == 0
                {
                    continue;
                }
                let units = total - next.prefixes.cursors[index];
                if units != 0 {
                    let payload = commit_chunk(
                        self.model,
                        &mut next.state,
                        index as u8,
                        next.prefixes.cursors[index],
                        units,
                        self.law,
                    )?;
                    next.prefixes.frame(index as u8, units, &payload)?;
                }
            }
        }
        Ok(Some(next))
    }

    fn value(&mut self, node: &Node, depth: usize) -> Result<f64> {
        let inspection = self.inspect(node)?;
        if node.state.stopped {
            return quality(&inspection, "delivery_critic");
        }
        if depth == 0 || node.owner.budget_remaining == 0 {
            return quality(&inspection, "critic");
        }
        let legal = inspection.get("policy.legal_mask")?;
        let mut best = None::<f64>;
        // Consider delivery before optional deeper work. Forecast-cap exhaustion
        // falls back to the frozen continuation critic, never a new action.
        for action in [6, 0, 1, 2, 3, 4, 5] {
            if legal.get(action) != Some(&1.0) {
                continue;
            }
            if let Some(next) = self.forecast(node, action)? {
                let continuation = self.value(&next, depth - 1)?;
                let score = self
                    .profile
                    .edge(self.profile.durations[action], continuation)?;
                best = Some(best.map_or(score, |prior| prior.max(score)));
            }
        }
        match best {
            Some(value) => Ok(value),
            None => quality(&inspection, "critic"),
        }
    }
}

fn quality(packet: &Packet, head: &str) -> Result<f64> {
    let value = packet.get(head)?;
    if value.len() != 1 || !value[0].is_finite() {
        return Err("invalid frozen critic output".into());
    }
    Ok(sigmoid(value[0]))
}

pub(crate) fn choose(
    model: &Model,
    state: &State,
    prefixes: &Prefixes,
    owner: &OwnerContext,
    public: &Packet,
    law: EmissionLaw,
) -> Result<PlanningReceipt> {
    let profile_name = model.weights.text("inference_profile")?;
    let node = Node {
        state: state.clone(),
        prefixes: prefixes.clone(),
        owner: owner.clone(),
    };
    let observation = DeliveryObservation::new(owner, prefixes, model.total_units())?;
    let inspection = model.inspect_observed(state, &observation)?;
    let legal = inspection.get("policy.legal_mask")?;
    let mut receipt = PlanningReceipt {
        profile: profile_name.into(),
        action: 0,
        horizon: 0,
        forecasts: 0,
        forecast_cap: 0,
        exhausted: false,
        scored: [false; 7],
        scores: [0.0; 7],
        selected_duration_micros: 0,
    };
    if profile_name == ACTOR_PROFILE {
        let probabilities = inspection.get("policy.probabilities")?;
        let selected = (0..7)
            .filter(|index| legal.get(*index) == Some(&1.0))
            .max_by(|left, right| {
                probabilities[*left]
                    .total_cmp(&probabilities[*right])
                    .then_with(|| right.cmp(left))
            })
            .ok_or("no legal actor action")?;
        receipt.action = selected;
        receipt.scored = std::array::from_fn(|index| legal[index] == 1.0);
        if probabilities.len() != 7 {
            return Err("actor probability width".into());
        }
        receipt.scores.copy_from_slice(probabilities);
        return Ok(receipt);
    }
    if profile_name != NDU_PROFILE {
        return Err("unknown observed inference profile".into());
    }
    let profile = Profile::read(model)?;
    receipt.horizon = profile.horizon;
    receipt.forecast_cap = profile.cap;
    let mut search = Search {
        model,
        public,
        law,
        limit: profile.cap,
        profile,
        calls: 0,
        exhausted: false,
    };
    let mut roots = Vec::new();
    // Materialize every affordable legal root before allocating deeper search;
    // enumeration order cannot suppress an entire alternative.
    for action in 0..7 {
        if legal.get(action) == Some(&1.0)
            && let Some(next) = search.forecast(&node, action)?
        {
            roots.push((action, next));
        }
    }
    if roots.is_empty() {
        return Err("no affordable legal action under admitted budget".into());
    }
    let remaining = search.profile.cap - search.calls;
    let count = roots.len();
    for (index, (action, next)) in roots.into_iter().enumerate() {
        search.limit = search.calls + remaining / count + usize::from(index < remaining % count);
        let continuation = search.value(&next, search.profile.horizon - 1)?;
        receipt.scores[action] = search
            .profile
            .edge(search.profile.durations[action], continuation)?;
        receipt.scored[action] = true;
    }
    receipt.action = (0..7)
        .filter(|index| receipt.scored[*index])
        .max_by(|left, right| {
            receipt.scores[*left]
                .total_cmp(&receipt.scores[*right])
                .then_with(|| right.cmp(left))
        })
        .ok_or("no scored action")?;
    receipt.forecasts = search.calls;
    receipt.exhausted = search.exhausted;
    receipt.selected_duration_micros = search.profile.durations[receipt.action];
    Ok(receipt)
}
