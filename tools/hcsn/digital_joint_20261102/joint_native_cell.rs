//! Persisted full conditional memory; reconstruction verifies checkpoint identity.
use crate::policy;
use crate::task;
use serde::Deserialize;
use serde::Serialize;

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct State {
    pub mass: Vec<f64>,
    pub bank: Vec<f64>,
}

impl State {
    pub fn new(
        policy: &policy::Policy,
        public: &task::Public,
        state: &task::State,
    ) -> Result<Self, String> {
        let (mass, bank) = policy.representation(public, state)?;
        let result = Self { mass, bank };
        result.validate()?;
        Ok(result)
    }

    pub fn validate(&self) -> Result<(), String> {
        if self.mass.len() != 33
            || self.bank.len() != 9
            || self
                .mass
                .iter()
                .chain(&self.bank)
                .any(|p| !p.is_finite() || *p < -1e-9 || *p > 1.0 + 1e-9)
            || (self.mass.iter().sum::<f64>() - 1.0).abs() > 1e-8
            || self
                .bank
                .chunks(3)
                .any(|p| p[0] + 1e-12 < p[1] || p[1] + 1e-12 < p[2])
        {
            return Err("invalid full conditional memory checkpoint".into());
        }
        Ok(())
    }
}
