//! Bounded, time-discretized FBSDE candidate training.
//!
//! This module owns a deterministic linear pilot only. It validates an
//! immutable trajectory snapshot and its filtration boundary, fits a
//! fixed-horizon backward value model, estimates every time-slice Z head with
//! the existing covariance kernel, emits canonical coefficient bytes, and
//! supports an independent replay. Every result is DENY_ALL: artifact
//! registration, independent acceptance, selection and activation remain
//! separate owner boundaries.

use std::collections::BTreeSet;
use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;

use crate::AdmittedCovarianceProfileV1;
use crate::AdmittedNduCoefficientProfileV1;
use crate::AdmittedZConversionProfileV1;
use crate::ConditionalMomentSampleV1;
use crate::CovarianceError;
use crate::NduCoefficientProjectionV1;
use crate::NduCoefficientProfileError;
use crate::ZEstimateV1;
use crate::estimate_conditional_moments;
use crate::project_z_estimate_to_coefficient_q24;
use crate::solve_backward_regression;

mod api;
mod codec;
mod math;
mod types;
mod validation;

pub use api::*;
pub use types::*;

use codec::*;
use math::*;
use validation::*;

#[cfg(test)]
mod tests;

const Q24_SCALE: f64 = 16_777_216.0;
const MAX_TRAJECTORIES: usize = 512;
const MAX_HORIZON: usize = 64;
const MAX_FEATURES: usize = 32;
const MAX_DRIVERS: usize = 32;
const MAX_UTILITIES: usize = 8;
const MAX_EPOCHS: usize = 200;
const MIN_TRAIN_TRAJECTORIES: usize = 4;
const MIN_HOLDOUT_TRAJECTORIES: usize = 2;
