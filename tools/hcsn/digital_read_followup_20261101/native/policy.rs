//! Frozen 48 -> 32 -> 7 policy. The only belief is this learned output.
use crate::cell;
use crate::task;
use serde::Deserialize;
use serde::Serialize;

#[derive(Clone, Copy, Debug, Deserialize, Serialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum Controller {
    Fixed,
    Value,
    StructuredValue,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Network {
    pub w1: Vec<Vec<f64>>,
    pub b1: Vec<f64>,
    pub w2: Vec<Vec<f64>>,
    pub b2: Vec<f64>,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Followup {
    pub rule: String,
    pub trainable_head_coordinates: usize,
    pub additional_head_updates: usize,
    pub original_allocated_head_coordinates: usize,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Policy {
    pub schema: String,
    pub family: String,
    pub fit: u64,
    pub public_feature_names: Vec<String>,
    pub representation_feature_names: Vec<String>,
    pub network: Network,
    pub kernel: Option<cell::Kernel>,
    #[serde(default)]
    pub followup: Option<Followup>,
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq)]
pub struct Scores {
    pub q: [f64; 6],
    pub belief_logit: f64,
    pub belief: f64,
}

impl Scores {
    pub fn for_controller(mut self, controller: Controller) -> Self {
        if controller == Controller::StructuredValue {
            self.q[0] = 0.0;
            self.q[4] = 1.0 - 2.0 * self.belief;
            self.q[5] = 2.0 * self.belief - 1.0;
        }
        self
    }
}

impl Policy {
    pub fn validate(&self, public: &task::Public) -> Result<(), String> {
        if self.followup.as_ref().is_some_and(|m| {
            m.rule != "structured terminals; frozen old kernel"
                || m.trainable_head_coordinates != 1700
                || m.additional_head_updates != 240
                || m.original_allocated_head_coordinates != 1799
        }) {
            return Err("incompatible followup training metadata".into());
        }
        let n = &self.network;
        if self.schema != "digital-read-before-policy-v1"
            || ![
                "ordinary_base",
                "ordinary_bank",
                "clocked_bank",
                "first_passage_bank",
                "raw_history",
            ]
            .contains(&self.family.as_str())
            || self.public_feature_names != task::public_names()
            || self.representation_feature_names != cell::representation_names(&self.family)
            || n.w1.len() != 32
            || n.w1.iter().any(|r| r.len() != 48)
            || n.b1.len() != 32
            || n.w2.len() != 7
            || n.w2.iter().any(|r| r.len() != 32)
            || n.b2.len() != 7
            || n.w1
                .iter()
                .flatten()
                .chain(n.w2.iter().flatten())
                .chain(&n.b1)
                .chain(&n.b2)
                .any(|x| !x.is_finite())
        {
            return Err("policy schema/shape/feature identity".into());
        }
        if self.family == "raw_history" {
            if self.kernel.is_some() {
                return Err("raw history cannot contain a cell kernel".into());
            }
        } else {
            let k = self.kernel.as_ref().ok_or("cell family requires kernel")?;
            k.validate(&self.family)?;
            for dt in std::iter::once(0.0).chain(public.duration.iter().copied()) {
                k.lookup(dt, 0, 0.5)?;
                for reliability in &public.reliability {
                    k.lookup(dt, -1, *reliability)?;
                    k.lookup(dt, 1, *reliability)?;
                }
            }
        }
        Ok(())
    }

    pub fn representation(
        &self,
        state: &task::State,
        cell: &cell::State,
    ) -> Result<[f64; 12], String> {
        if let Some(kernel) = &self.kernel {
            cell.validate()?;
            Ok(kernel
                .lookup(0.0, state.last_symbol, state.last_reliability)?
                .features[cell.index])
        } else {
            Ok(state.history_features())
        }
    }

    pub fn predict(&self, public: &[f64], representation: &[f64; 12]) -> Result<Scores, String> {
        if public.len() != 36 {
            return Err("public feature width".into());
        }
        let x = public
            .iter()
            .chain(representation)
            .copied()
            .collect::<Vec<_>>();
        if x.iter().any(|v| !v.is_finite()) {
            return Err("nonfinite policy input".into());
        }
        let n = &self.network;
        let h: [f64; 32] = std::array::from_fn(|j| {
            (n.b1[j] + n.w1[j].iter().zip(&x).map(|(w, x)| w * x).sum::<f64>()).tanh()
        });
        let y: [f64; 7] = std::array::from_fn(|j| {
            n.b2[j] + n.w2[j].iter().zip(h).map(|(w, x)| w * x).sum::<f64>()
        });
        if y.iter().any(|v| !v.is_finite()) {
            return Err("nonfinite neural scores".into());
        }
        let logit = y[6];
        let e = (-logit.abs()).exp();
        let belief = if logit >= 0.0 {
            1.0 / (1.0 + e)
        } else {
            e / (1.0 + e)
        };
        let scores = Scores {
            q: std::array::from_fn(|i| y[i]),
            belief_logit: logit,
            belief,
        };
        Ok(if self.followup.is_some() {
            scores.for_controller(Controller::StructuredValue)
        } else {
            scores
        })
    }
}

pub fn select(
    scores: &Scores,
    legal: [bool; 6],
    state: &task::State,
    controller: Controller,
) -> Result<usize, String> {
    let scores = scores.clone().for_controller(controller);
    if !legal.iter().any(|x| *x) {
        return Err("terminal policy query".into());
    }
    let action = match controller {
        Controller::Fixed => task::fixed_action(state, legal, scores.belief),
        Controller::Value | Controller::StructuredValue => {
            let mut best = legal.iter().position(|x| *x).ok_or("no legal action")?;
            for i in best + 1..6 {
                if legal[i] && scores.q[i] > scores.q[best] {
                    best = i;
                }
            }
            best
        }
    };
    if !legal[action] {
        return Err("controller selected illegal action".into());
    }
    Ok(action)
}
