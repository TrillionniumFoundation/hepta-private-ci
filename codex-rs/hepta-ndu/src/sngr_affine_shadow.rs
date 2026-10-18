//! Authority-free scalar, affine, fully coupled FBSDE shooting reference.
//!
//! dX = U dt (+ sigma dW), dU = Z dW, U_T = a X_T + b.
//! This module checks the zero-noise exact characteristic and its boundary
//! matching. It is NOT a learned stochastic solver or a production policy.
//! Unsupported singular/crossed decoupling domains fail closed.

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;

const MAX_SHOOTING_SLICES: usize = 64;
const MIN_DENOMINATOR: f64 = 1e-10;

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct SngrAffineBoundaryShadowV1 {
    pub slope: f64,
    pub intercept: f64,
}

impl SngrAffineBoundaryShadowV1 {
    fn evaluate(self, state: f64) -> Result<f64, SngrAffineShadowError> {
        checked(self.slope * state + self.intercept)
    }
}

#[derive(Clone, Debug, PartialEq)]
pub struct SngrAffineShootingRequestShadowV1 {
    pub initial_state: f64,
    pub durations: Vec<f64>,
    pub terminal: SngrAffineBoundaryShadowV1,
    pub tolerance: f64,
}

#[derive(Clone, Debug, PartialEq)]
pub struct SngrAffineSliceShadowV1 {
    pub index: usize,
    pub duration: f64,
    pub state_in: f64,
    pub state_out: f64,
    pub utility_in: f64,
    pub utility_out: f64,
    pub boundary_residual: f64,
    pub forward_residual: f64,
}

#[derive(Clone, Debug, PartialEq)]
pub struct SngrAffineShootingReceiptShadowV1 {
    pub initial_utility: f64,
    pub final_state: f64,
    pub terminal_residual: f64,
    pub maximum_interface_residual: f64,
    pub maximum_forward_residual: f64,
    pub accepted: bool,
    pub slices: Vec<SngrAffineSliceShadowV1>,
    /// Reproducible synthetic input/algorithm/output digest, NOT a task receipt.
    pub evidence_digest: Digest32,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum SngrAffineShadowError {
    InvalidHorizon,
    InvalidDuration,
    InvalidTolerance,
    NonFinite,
    IllPosed,
}

impl fmt::Display for SngrAffineShadowError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for SngrAffineShadowError {}

fn checked(value: f64) -> Result<f64, SngrAffineShadowError> {
    if value.is_finite() {
        Ok(value)
    } else {
        Err(SngrAffineShadowError::NonFinite)
    }
}

fn validate(request: &SngrAffineShootingRequestShadowV1) -> Result<(), SngrAffineShadowError> {
    checked(request.initial_state)?;
    checked(request.terminal.slope)?;
    checked(request.terminal.intercept)?;
    checked(request.tolerance)?;
    if request.tolerance <= 0.0 || request.tolerance > 1e-4 {
        return Err(SngrAffineShadowError::InvalidTolerance);
    }
    if !(1..=MAX_SHOOTING_SLICES).contains(&request.durations.len()) {
        return Err(SngrAffineShadowError::InvalidHorizon);
    }
    let mut total = 0.0;
    for duration in &request.durations {
        checked(*duration)?;
        if *duration <= 0.0 || *duration > 3600.0 {
            return Err(SngrAffineShadowError::InvalidDuration);
        }
        total = checked(total + *duration)?;
    }
    Ok(())
}

/// Backward decoupling map from the *next* interval's right endpoint.
/// Only the positive-denominator branch is admitted in the shadow profile.
pub fn sngr_affine_continuation_shadow(
    terminal: SngrAffineBoundaryShadowV1,
    duration: f64,
) -> Result<SngrAffineBoundaryShadowV1, SngrAffineShadowError> {
    checked(terminal.slope)?;
    checked(terminal.intercept)?;
    checked(duration)?;
    if duration < 0.0 {
        return Err(SngrAffineShadowError::InvalidDuration);
    }
    let denominator = checked(1.0 - terminal.slope * duration)?;
    if denominator <= MIN_DENOMINATOR {
        return Err(SngrAffineShadowError::IllPosed);
    }
    Ok(SngrAffineBoundaryShadowV1 {
        slope: checked(terminal.slope / denominator)?,
        intercept: checked(terminal.intercept / denominator)?,
    })
}

fn receipt(
    request: &SngrAffineShootingRequestShadowV1,
    slices: Vec<SngrAffineSliceShadowV1>,
    max_interface: f64,
    reset_terminal: bool,
) -> Result<SngrAffineShootingReceiptShadowV1, SngrAffineShadowError> {
    let last = slices.last().ok_or(SngrAffineShadowError::InvalidHorizon)?;
    let initial_utility = slices
        .first()
        .ok_or(SngrAffineShadowError::InvalidHorizon)?
        .utility_in;
    let final_state = last.state_out;
    let terminal_residual =
        checked((last.utility_out - request.terminal.evaluate(final_state)?).abs())?;
    let max_forward = slices
        .iter()
        .fold(0.0_f64, |max, slice| max.max(slice.forward_residual));
    let mut bytes = b"hepta.ndu.sngr-affine-synthetic.shadow.v1".to_vec();
    bytes.push(u8::from(reset_terminal));
    for v in [
        request.initial_state,
        request.terminal.slope,
        request.terminal.intercept,
        request.tolerance,
        terminal_residual,
        max_interface,
        max_forward,
    ] {
        bytes.extend_from_slice(&v.to_bits().to_be_bytes());
    }
    bytes.extend_from_slice(&(slices.len() as u64).to_be_bytes());
    for slice in &slices {
        bytes.extend_from_slice(&(slice.index as u64).to_be_bytes());
        for v in [
            slice.duration,
            slice.state_in,
            slice.state_out,
            slice.utility_in,
            slice.utility_out,
            slice.boundary_residual,
            slice.forward_residual,
        ] {
            bytes.extend_from_slice(&v.to_bits().to_be_bytes());
        }
    }
    Ok(SngrAffineShootingReceiptShadowV1 {
        initial_utility,
        final_state,
        terminal_residual,
        maximum_interface_residual: max_interface,
        maximum_forward_residual: max_forward,
        accepted: terminal_residual.max(max_interface).max(max_forward) <= request.tolerance,
        slices,
        evidence_digest: Digest32::of_bytes(&bytes),
        authority: AuthorityPosture::DENY_ALL,
    })
}

/// Correct multiple shooting: backward continuation fields, then forward steps.
/// Interface and terminal residuals are both required for acceptance.
pub fn solve_sngr_affine_shadow(
    request: &SngrAffineShootingRequestShadowV1,
) -> Result<SngrAffineShootingReceiptShadowV1, SngrAffineShadowError> {
    validate(request)?;
    let mut fields = Vec::with_capacity(request.durations.len() + 1);
    fields.push(request.terminal);
    for duration in request.durations.iter().rev() {
        let continuation = sngr_affine_continuation_shadow(
            *fields.last().ok_or(SngrAffineShadowError::InvalidHorizon)?,
            *duration,
        )?;
        fields.push(continuation);
    }
    fields.reverse();
    let mut x = request.initial_state;
    let mut slices = Vec::with_capacity(request.durations.len());
    let mut max_interface = 0.0_f64;
    for (index, duration) in request.durations.iter().enumerate() {
        let y = fields[index].evaluate(x)?;
        let x_next = checked(x + *duration * y)?;
        let y_next = fields[index + 1].evaluate(x_next)?;
        let boundary_residual = checked((y_next - y).abs())?;
        let forward_residual = checked((x_next - x - *duration * y).abs())?;
        max_interface = max_interface.max(boundary_residual);
        slices.push(SngrAffineSliceShadowV1 {
            index,
            duration: *duration,
            state_in: x,
            state_out: x_next,
            utility_in: y,
            utility_out: y_next,
            boundary_residual,
            forward_residual,
        });
        x = x_next;
    }
    receipt(request, slices, max_interface, /*reset_terminal*/ false)
}

/// Deliberately incorrect negative control: resetting g at each short horizon.
/// Zero terminal residual is NOT evidence of a globally consistent solution.
pub fn naive_sngr_terminal_reset_shadow(
    request: &SngrAffineShootingRequestShadowV1,
) -> Result<SngrAffineShootingReceiptShadowV1, SngrAffineShadowError> {
    validate(request)?;
    let mut x = request.initial_state;
    let mut previous_utility: Option<f64> = None;
    let mut max_interface = 0.0_f64;
    let mut slices = Vec::with_capacity(request.durations.len());
    for (index, duration) in request.durations.iter().enumerate() {
        let local = sngr_affine_continuation_shadow(request.terminal, *duration)?;
        let y = local.evaluate(x)?;
        let x_next = checked(x + *duration * y)?;
        let boundary_residual = previous_utility.map_or(0.0, |old| (y - old).abs());
        max_interface = max_interface.max(boundary_residual);
        let forward_residual = checked((x_next - x - *duration * y).abs())?;
        slices.push(SngrAffineSliceShadowV1 {
            index,
            duration: *duration,
            state_in: x,
            state_out: x_next,
            utility_in: y,
            utility_out: y,
            boundary_residual,
            forward_residual,
        });
        previous_utility = Some(y);
        x = x_next;
    }
    receipt(request, slices, max_interface, /*reset_terminal*/ true)
}

#[cfg(test)]
#[path = "sngr_affine_shadow_tests.rs"]
mod tests;
