//! Finite belief-grid stopping with a price frozen within each episode.
use crate::Result;
use serde::{Deserialize, Serialize};

#[derive(Clone, Copy, Debug, Deserialize, Serialize, PartialEq)]
#[serde(rename_all = "snake_case")]
pub enum Action {
    Positive,
    Negative,
    Abstain,
    Continue,
}

#[derive(Clone, Copy, Debug, Deserialize, Serialize, PartialEq)]
#[serde(rename_all = "snake_case")]
pub enum ReadoutKind {
    Snn,
    RawBeliefDp,
    RawBeliefMyopic,
}

#[derive(Clone, Debug)]
pub struct Boundary {
    pub rows: Vec<Vec<f64>>,
    pub grid_points: usize,
    pub build_terms: usize,
}

fn interpolate(row: &[f64], p: f64) -> f64 {
    let index = p.clamp(0.0, 1.0) * (row.len() - 1) as f64;
    let left = (index.floor() as usize).min(row.len() - 2);
    row[left] + (index - left as f64) * (row[left + 1] - row[left])
}

impl Boundary {
    pub fn build(reliability: f64, cost: f64, horizon: usize, grid_points: usize) -> Result<Self> {
        if !(0.5..1.0).contains(&reliability)
            || !cost.is_finite()
            || cost < 0.0
            || horizon == 0
            || horizon > 16
            || grid_points < 101
            || grid_points > 2001
            || grid_points % 2 == 0
        {
            return Err("Unregistered stopping context".into());
        }
        let mut value: Vec<f64> = (0..grid_points)
            .map(|i| {
                (2.0 * i as f64 / (grid_points - 1) as f64 - 1.0)
                    .abs()
                    .max(0.05)
            })
            .collect();
        let mut rows = vec![vec![f64::NEG_INFINITY; grid_points]];
        for _ in 1..horizon {
            let mut continuation = Vec::with_capacity(grid_points);
            let mut next = Vec::with_capacity(grid_points);
            for i in 0..grid_points {
                let p = i as f64 / (grid_points - 1) as f64;
                let chance = reliability * p + (1.0 - reliability) * (1.0 - p);
                let plus = reliability * p / chance;
                let minus = (1.0 - reliability) * p / (1.0 - chance);
                let wait = -cost
                    + chance * interpolate(&value, plus)
                    + (1.0 - chance) * interpolate(&value, minus);
                continuation.push(wait);
                next.push(wait.max((2.0 * p - 1.0).abs()).max(0.05));
            }
            rows.push(continuation);
            value = next;
        }
        Ok(Self {
            rows,
            grid_points,
            build_terms: 2 * grid_points * (horizon - 1),
        })
    }

    pub fn action(
        &self,
        logit: f64,
        remaining: usize,
        kind: ReadoutKind,
    ) -> Result<(Action, f64, f64)> {
        if !logit.is_finite()
            || (kind != ReadoutKind::RawBeliefMyopic && remaining >= self.rows.len())
        {
            return Err("Readout outside registered horizon".into());
        }
        let p = if logit >= 0.0 {
            1.0 / (1.0 + (-logit).exp())
        } else {
            let e = logit.exp();
            e / (1.0 + e)
        };
        let immediate = (2.0 * p - 1.0).abs();
        let continuation = if remaining == 0 {
            -1.0
        } else {
            interpolate(
                &self.rows[if kind == ReadoutKind::RawBeliefMyopic {
                    1
                } else {
                    remaining
                }],
                p,
            )
        };
        let action = if immediate >= 0.05 && (remaining == 0 || immediate >= continuation) {
            if logit > 0.0 {
                Action::Positive
            } else {
                Action::Negative
            }
        } else if remaining == 0 || 0.05 >= continuation {
            Action::Abstain
        } else {
            Action::Continue
        };
        Ok((action, immediate, continuation))
    }
}
