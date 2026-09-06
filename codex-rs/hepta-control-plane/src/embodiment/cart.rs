//! Synthetic one-dimensional unit-mass cart; metres, seconds and m/s².
//! Profile `cart-explicit-euler-q24-rne-v1`: dt=1/100, Q24 observations/actions,
//! each Euler increment rounded to nearest with ties to even (<= 0.5 Q24 LSB).
//! Quantized stopping time can differ from the exact-rational 50-tick reference.
//! No hardware adapter, runtime authority or physical calibration is provided.

use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;

pub const CART_Q24_SCALE: i64 = 1 << 24;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct CartStateV1 {
    pub position_q24: i64,
    pub velocity_q24: i64,
}

impl CartStateV1 {
    /// Engineering bounds plus the documented sufficient symmetric stopping
    /// margin, computed exactly on the Q24 state without floating point.
    pub fn validate(self) -> Result<(), CartError> {
        let x = i128::from(self.position_q24).abs();
        let v = i128::from(self.velocity_q24).abs();
        let s = i128::from(CART_Q24_SCALE);
        if x > s || v > s {
            return Err(CartError::OutsideEnvelope);
        }
        // |x| + v²/4 + |v|/100 <= 1, multiplied by 100*S².
        if 100 * x * s + 25 * v * v + v * s > 100 * s * s {
            return Err(CartError::StoppingMargin);
        }
        Ok(())
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct CartSensorProfileV1 {
    pub generation: Generation,
    pub clock: Digest32,
    pub synthetic_calibration: Digest32,
    pub valid_until_tick: u64,
}

/// Synthetic truth only. Tick units are exactly 10 ms in the named clock.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct SyntheticCartObservationV1 {
    pub state: CartStateV1,
    pub tick: u64,
    pub generation: Generation,
    pub clock: Digest32,
    pub synthetic_calibration: Digest32,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum CartControlMode {
    TrackOrigin,
    EmergencyBrake,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct CartCommandV1 {
    pub generation: Generation,
    pub observed_tick: u64,
    pub acceleration_q24: i64,
    pub saturated: bool,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum CartError {
    OutsideEnvelope,
    StoppingMargin,
    IdentityMismatch,
    ExpiredCalibration,
    StaleOrFutureSample,
    ClockRegression,
    InvalidCommand,
    TickOverflow,
}

/// Pure native simulation port. Implementations must retain the declared plant,
/// time unit, numeric profile and synthetic provenance, with no external effect.
pub trait SyntheticCartPlant {
    fn observe(&self) -> SyntheticCartObservationV1;
    fn advance(&mut self, command: CartCommandV1) -> Result<SyntheticCartObservationV1, CartError>;
}

pub struct CartSimulatorV1 {
    state: CartStateV1,
    profile: CartSensorProfileV1,
    tick: u64,
    stop_latched: bool,
}

impl CartSimulatorV1 {
    pub fn new(state: CartStateV1, profile: CartSensorProfileV1) -> Result<Self, CartError> {
        state.validate()?;
        if profile.synthetic_calibration.is_zero() || profile.clock.is_zero() {
            return Err(CartError::IdentityMismatch);
        }
        Ok(Self {
            state,
            profile,
            tick: 0,
            stop_latched: false,
        })
    }

    /// Independent simulator stop path. Latches before braking and fences any
    /// previously prepared non-braking command, even when validation fails.
    pub fn emergency_brake(&mut self) -> Result<SyntheticCartObservationV1, CartError> {
        self.stop_latched = true;
        let requested = -100 * self.state.velocity_q24;
        let acceleration_q24 = requested.clamp(-2 * CART_Q24_SCALE, 2 * CART_Q24_SCALE);
        self.advance(CartCommandV1 {
            generation: self.profile.generation,
            observed_tick: self.tick,
            acceleration_q24,
            saturated: acceleration_q24 != requested,
        })
    }
}

impl SyntheticCartPlant for CartSimulatorV1 {
    fn observe(&self) -> SyntheticCartObservationV1 {
        SyntheticCartObservationV1 {
            state: self.state,
            tick: self.tick,
            generation: self.profile.generation,
            clock: self.profile.clock,
            synthetic_calibration: self.profile.synthetic_calibration,
        }
    }

    fn advance(&mut self, command: CartCommandV1) -> Result<SyntheticCartObservationV1, CartError> {
        if command.generation != self.profile.generation
            || command.observed_tick != self.tick
            || command.acceleration_q24.unsigned_abs() > (2 * CART_Q24_SCALE) as u64
            || (self.stop_latched
                && command.acceleration_q24
                    != (-100 * self.state.velocity_q24)
                        .clamp(-2 * CART_Q24_SCALE, 2 * CART_Q24_SCALE))
        {
            return Err(CartError::InvalidCommand);
        }
        let tick = self.tick.checked_add(1).ok_or(CartError::TickOverflow)?;
        // Both updates use the OLD state: this is explicit, not symplectic Euler.
        let next = CartStateV1 {
            position_q24: self.state.position_q24 + round_hundredth(self.state.velocity_q24),
            velocity_q24: self.state.velocity_q24 + round_hundredth(command.acceleration_q24),
        };
        next.validate()?;
        self.state = next;
        self.tick = tick;
        Ok(self.observe())
    }
}

/// Bounded local PD/braking controller; it has no model or central RPC handle.
pub struct CartControllerV1 {
    profile: CartSensorProfileV1,
    last_tick: Option<u64>,
    last_now: Option<u64>,
    stopped: bool,
}

impl CartControllerV1 {
    pub fn new(profile: CartSensorProfileV1) -> Self {
        Self {
            profile,
            last_tick: None,
            last_now: None,
            stopped: false,
        }
    }

    /// Stop latches until a fresh controller/profile is explicitly constructed.
    /// Sample maximum age is 20 ms; future/duplicate/regressing samples fail.
    pub fn command(
        &mut self,
        sample: &SyntheticCartObservationV1,
        now_tick: u64,
        mode: CartControlMode,
    ) -> Result<CartCommandV1, CartError> {
        if mode == CartControlMode::EmergencyBrake {
            self.stopped = true;
        }
        if sample.generation != self.profile.generation
            || sample.clock != self.profile.clock
            || sample.synthetic_calibration != self.profile.synthetic_calibration
            || sample.synthetic_calibration.is_zero()
            || sample.clock.is_zero()
        {
            return Err(CartError::IdentityMismatch);
        }
        if now_tick > self.profile.valid_until_tick {
            return Err(CartError::ExpiredCalibration);
        }
        if sample.tick > now_tick || now_tick - sample.tick > 2 {
            return Err(CartError::StaleOrFutureSample);
        }
        if self.last_tick.is_some_and(|last| sample.tick <= last)
            || self.last_now.is_some_and(|last| now_tick < last)
        {
            return Err(CartError::ClockRegression);
        }
        sample.state.validate()?;
        let requested = if self.stopped {
            -100 * sample.state.velocity_q24
        } else {
            -4 * sample.state.position_q24 - 4 * sample.state.velocity_q24
        };
        let acceleration_q24 = requested.clamp(-2 * CART_Q24_SCALE, 2 * CART_Q24_SCALE);
        self.last_tick = Some(sample.tick);
        self.last_now = Some(now_tick);
        Ok(CartCommandV1 {
            generation: sample.generation,
            observed_tick: sample.tick,
            acceleration_q24,
            saturated: acceleration_q24 != requested,
        })
    }
}

fn round_hundredth(value: i64) -> i64 {
    let quotient = value / 100;
    let remainder = value % 100;
    if remainder.abs() > 50 || (remainder.abs() == 50 && quotient % 2 != 0) {
        quotient + value.signum()
    } else {
        quotient
    }
}

#[cfg(test)]
#[path = "cart_tests.rs"]
mod tests;
