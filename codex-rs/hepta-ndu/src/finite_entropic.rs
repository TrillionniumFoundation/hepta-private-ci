//! Finite-horizon entropic utility shared by generation and training profiles.
//!
//! This is a scalar, model-based planning operator, not an FBSDE solver or a
//! claim about calibrated environment noise. Terminal scores must be supplied
//! by a separately bound critic or external evaluator. This module grants no
//! authority and never invokes actions.

use std::error::Error;
use std::fmt;

pub const FINITE_ENTROPIC_PROFILE_ID: &str = "hepta.ndu.finite-entropic.v1";

/// Objective coefficients. Durations are seconds, not decision counts.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct FiniteEntropicProfileV1 {
    pub risk: f64,
    pub discount_per_second: f64,
    pub latency_weight: f64,
}

impl Default for FiniteEntropicProfileV1 {
    fn default() -> Self {
        Self {
            risk: 0.25,
            discount_per_second: 1.0,
            latency_weight: 0.01,
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum FiniteEntropicError {
    Profile,
    Duration,
    Lottery,
    Arithmetic,
}

impl fmt::Display for FiniteEntropicError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl Error for FiniteEntropicError {}

impl FiniteEntropicProfileV1 {
    pub fn validate(&self) -> Result<(), FiniteEntropicError> {
        if !(self.risk.is_finite()
            && self.risk >= 0.0
            && self.latency_weight.is_finite()
            && self.latency_weight >= 0.0
            && self.discount_per_second.is_finite()
            && 0.0 < self.discount_per_second
            && self.discount_per_second <= 1.0)
        {
            return Err(FiniteEntropicError::Profile);
        }
        Ok(())
    }

    /// Charge duration once and discount the complete continuation by elapsed
    /// time. A terminal payoff is not added again at intermediate states.
    pub fn edge(
        &self,
        duration_seconds: f64,
        continuation: f64,
    ) -> Result<f64, FiniteEntropicError> {
        self.validate()?;
        if !duration_seconds.is_finite() || duration_seconds < 0.0 {
            return Err(FiniteEntropicError::Duration);
        }
        if !continuation.is_finite() {
            return Err(FiniteEntropicError::Arithmetic);
        }
        let value = -self.latency_weight * duration_seconds
            + self.discount_per_second.powf(duration_seconds) * continuation;
        if !value.is_finite() {
            return Err(FiniteEntropicError::Arithmetic);
        }
        Ok(value)
    }

    /// CE(X) = -log E[exp(-risk X)] / risk; risk=0 is the expectation.
    ///
    /// Upstream binds the noise law, samples and probabilities. A deterministic
    /// single-particle rollout is explicitly a zero-noise specialization.
    pub fn certainty_equivalent(
        &self,
        values: &[f64],
        probabilities: &[f64],
    ) -> Result<f64, FiniteEntropicError> {
        self.validate()?;
        if values.is_empty()
            || values.len() > 512
            || values.len() != probabilities.len()
            || values.iter().any(|value| !value.is_finite())
            || probabilities
                .iter()
                .any(|probability| !probability.is_finite() || *probability < 0.0)
        {
            return Err(FiniteEntropicError::Lottery);
        }
        let total: f64 = probabilities.iter().sum();
        if !total.is_finite() || (total - 1.0).abs() > 1e-9 {
            return Err(FiniteEntropicError::Lottery);
        }
        let mean: f64 = values
            .iter()
            .zip(probabilities)
            .map(|(x, p)| x * (p / total))
            .sum();
        let small_spread = self.risk > 0.0
            && values
                .iter()
                .zip(probabilities)
                .filter(|(_, probability)| **probability > 0.0)
                .all(|(value, _)| (self.risk * (value - mean)).abs() <= 1e-3);
        let result = if self.risk == 0.0 {
            mean
        } else if small_spread {
            // log(sum p exp(-risk*x)) loses the entire risk correction when
            // risk is tiny. Centering plus expm1/log1p has the mean as a stable
            // continuous limit and retains the first nonzero risk penalty.
            let correction: f64 = values
                .iter()
                .zip(probabilities)
                .filter(|(_, probability)| **probability > 0.0)
                .map(|(value, probability)| {
                    (probability / total) * (-self.risk * (value - mean)).exp_m1()
                })
                .sum();
            mean - correction.ln_1p() / self.risk
        } else {
            // Zero-probability extrema cannot determine the numerical origin.
            let minimum = values
                .iter()
                .zip(probabilities)
                .filter(|(_, probability)| **probability > 0.0)
                .map(|(value, _)| *value)
                .fold(f64::INFINITY, f64::min);
            let exponential_mean: f64 = values
                .iter()
                .zip(probabilities)
                .filter(|(_, probability)| **probability > 0.0)
                .map(|(value, probability)| {
                    (probability / total) * (-self.risk * (value - minimum)).exp()
                })
                .sum();
            minimum - exponential_mean.ln() / self.risk
        };
        if !result.is_finite() {
            return Err(FiniteEntropicError::Arithmetic);
        }
        Ok(result)
    }
}

#[cfg(test)]
#[path = "finite_entropic_tests.rs"]
mod tests;
