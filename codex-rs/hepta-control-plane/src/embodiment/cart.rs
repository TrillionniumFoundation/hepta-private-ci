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

impl CartSensorProfileV1 {
    #[must_use]
    pub fn profile_digest(self) -> Digest32 {
        let mut bytes = Vec::new();
        bytes.extend_from_slice(b"hepta.synthetic-cart.sensor-profile.v1\0");
        bytes.extend_from_slice(&self.generation.get().to_be_bytes());
        bytes.extend_from_slice(self.clock.as_array());
        bytes.extend_from_slice(self.synthetic_calibration.as_array());
        bytes.extend_from_slice(&self.valid_until_tick.to_be_bytes());
        Digest32::of_bytes(&bytes)
    }
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

impl SyntheticCartObservationV1 {
    #[must_use]
    pub fn observation_digest(self) -> Digest32 {
        let mut bytes = Vec::new();
        bytes.extend_from_slice(b"hepta.synthetic-cart.observation.v1\0");
        bytes.extend_from_slice(&self.state.position_q24.to_be_bytes());
        bytes.extend_from_slice(&self.state.velocity_q24.to_be_bytes());
        bytes.extend_from_slice(&self.tick.to_be_bytes());
        bytes.extend_from_slice(&self.generation.get().to_be_bytes());
        bytes.extend_from_slice(self.clock.as_array());
        bytes.extend_from_slice(self.synthetic_calibration.as_array());
        Digest32::of_bytes(&bytes)
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum CartControlMode {
    TrackOrigin,
    EmergencyBrake,
}

impl CartControlMode {
    const fn digest_tag(self) -> u8 {
        match self {
            Self::TrackOrigin => 0,
            Self::EmergencyBrake => 1,
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct CartCommandV1 {
    pub generation: Generation,
    pub observed_tick: u64,
    pub profile_digest: Digest32,
    pub observation_digest: Digest32,
    pub mode: CartControlMode,
    pub acceleration_q24: i64,
    pub saturated: bool,
    /// Unkeyed content binding only. This is not caller authentication or
    /// actuation authority; a trusted runtime must provide those separately.
    pub binding_digest: Digest32,
}

impl CartCommandV1 {
    fn bound(
        generation: Generation,
        observed_tick: u64,
        profile_digest: Digest32,
        observation_digest: Digest32,
        mode: CartControlMode,
        acceleration_q24: i64,
        saturated: bool,
    ) -> Self {
        let mut command = Self {
            generation,
            observed_tick,
            profile_digest,
            observation_digest,
            mode,
            acceleration_q24,
            saturated,
            binding_digest: Digest32::ZERO,
        };
        command.binding_digest = command.calculated_binding_digest();
        command
    }

    fn calculated_binding_digest(self) -> Digest32 {
        let mut bytes = Vec::new();
        bytes.extend_from_slice(b"hepta.synthetic-cart.command.v1\0");
        bytes.extend_from_slice(&self.generation.get().to_be_bytes());
        bytes.extend_from_slice(&self.observed_tick.to_be_bytes());
        bytes.extend_from_slice(self.profile_digest.as_array());
        bytes.extend_from_slice(self.observation_digest.as_array());
        bytes.push(self.mode.digest_tag());
        bytes.extend_from_slice(&self.acceleration_q24.to_be_bytes());
        bytes.push(u8::from(self.saturated));
        Digest32::of_bytes(&bytes)
    }
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
        let observation = self.observe();
        let requested = -100 * self.state.velocity_q24;
        let acceleration_q24 = requested.clamp(-2 * CART_Q24_SCALE, 2 * CART_Q24_SCALE);
        self.advance(CartCommandV1::bound(
            observation.generation,
            observation.tick,
            self.profile.profile_digest(),
            observation.observation_digest(),
            CartControlMode::EmergencyBrake,
            acceleration_q24,
            acceleration_q24 != requested,
        ))
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
        let observation = self.observe();
        let next_stop_latched =
            self.stop_latched || command.mode == CartControlMode::EmergencyBrake;
        if command.generation != self.profile.generation
            || command.observed_tick != self.tick
            || command.profile_digest != self.profile.profile_digest()
            || command.observation_digest != observation.observation_digest()
            || command.acceleration_q24.unsigned_abs() > (2 * CART_Q24_SCALE) as u64
            || command.binding_digest.is_zero()
            || command.binding_digest != command.calculated_binding_digest()
            || (self.stop_latched && command.mode != CartControlMode::EmergencyBrake)
            || (next_stop_latched
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
        self.stop_latched = next_stop_latched;
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
    /// Every rejected command leaves all controller state unchanged.
    pub fn command(
        &mut self,
        sample: &SyntheticCartObservationV1,
        now_tick: u64,
        mode: CartControlMode,
    ) -> Result<CartCommandV1, CartError> {
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
        let stopped = self.stopped || mode == CartControlMode::EmergencyBrake;
        let requested = if stopped {
            -100 * sample.state.velocity_q24
        } else {
            -4 * sample.state.position_q24 - 4 * sample.state.velocity_q24
        };
        let acceleration_q24 = requested.clamp(-2 * CART_Q24_SCALE, 2 * CART_Q24_SCALE);
        let effective_mode = if stopped {
            CartControlMode::EmergencyBrake
        } else {
            CartControlMode::TrackOrigin
        };
        let command = CartCommandV1::bound(
            sample.generation,
            sample.tick,
            self.profile.profile_digest(),
            sample.observation_digest(),
            effective_mode,
            acceleration_q24,
            acceleration_q24 != requested,
        );
        self.stopped = stopped;
        self.last_tick = Some(sample.tick);
        self.last_now = Some(now_tick);
        Ok(command)
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
