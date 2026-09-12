//! Typed sensor/actuator seam for the deterministic cart body.
//!
//! `SyntheticCartIoV1` is a real native caller path: a typed sensor read is
//! admitted, a bounded controller command is wrapped with an actuator identity,
//! and the command is dispatched to the plant with a terminal receipt. The
//! adapter owns no credentials and can never grant authority. It is a
//! deterministic simulator/HIL seam; it does not claim hardware calibration,
//! physical safety or external effect success.

use codex_hepta_types::{AuthorityPosture, Digest32, StableId};

use super::{
    CartCommandV1, CartError, CartSensorProfileV1, CartSimulatorV1, SyntheticCartObservationV1,
    SyntheticCartPlant,
};

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct TypedSensorReadingV1 {
    pub sensor_id: StableId,
    pub observation: SyntheticCartObservationV1,
    pub payload_digest: Digest32,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct TypedActuatorDispatchV1 {
    pub actuator_id: StableId,
    pub command: CartCommandV1,
    /// Explicitly deny-all: this seam is a simulator/HIL fixture and has no
    /// capability to cause an external effect.
    pub authority: AuthorityPosture,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SyntheticActuatorReceiptV1 {
    pub actuator_id: StableId,
    pub observed_tick: u64,
    pub terminal_observation: SyntheticCartObservationV1,
    pub terminal_payload_digest: Digest32,
    /// A successful simulation step still carries no production authority.
    pub authority: AuthorityPosture,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum EmbodimentIoError {
    Cart(CartError),
    SensorIdentityMismatch,
    ActuatorIdentityMismatch,
    AuthorityNotDenied,
}

impl From<CartError> for EmbodimentIoError {
    fn from(error: CartError) -> Self {
        Self::Cart(error)
    }
}

/// Native, typed body adapter. The profile and identities are immutable for
/// the adapter lifetime; replacing either requires constructing a new body
/// generation explicitly.
pub struct SyntheticCartIoV1 {
    sensor_id: StableId,
    actuator_id: StableId,
    profile: CartSensorProfileV1,
    plant: CartSimulatorV1,
}

impl SyntheticCartIoV1 {
    pub fn new(
        sensor_id: StableId,
        actuator_id: StableId,
        profile: CartSensorProfileV1,
        plant: CartSimulatorV1,
    ) -> Result<Self, EmbodimentIoError> {
        if sensor_id.as_str().is_empty() || actuator_id.as_str().is_empty() {
            return Err(EmbodimentIoError::SensorIdentityMismatch);
        }
        if plant.observe().generation != profile.generation
            || plant.observe().clock != profile.clock
            || plant.observe().synthetic_calibration != profile.synthetic_calibration
        {
            return Err(EmbodimentIoError::SensorIdentityMismatch);
        }
        Ok(Self {
            sensor_id,
            actuator_id,
            profile,
            plant,
        })
    }

    #[must_use]
    pub fn profile(&self) -> CartSensorProfileV1 {
        self.profile
    }

    /// Read the current typed state. `now_tick` is supplied by the caller so
    /// age/future checks remain explicit and testable.
    pub fn read_sensor(&self, now_tick: u64) -> Result<TypedSensorReadingV1, EmbodimentIoError> {
        let observation = self.plant.observe();
        if now_tick > self.profile.valid_until_tick {
            return Err(EmbodimentIoError::Cart(CartError::ExpiredCalibration));
        }
        if observation.tick > now_tick || now_tick - observation.tick > 2 {
            return Err(EmbodimentIoError::Cart(CartError::StaleOrFutureSample));
        }
        Ok(TypedSensorReadingV1 {
            sensor_id: self.sensor_id.clone(),
            payload_digest: observation.observation_digest(),
            observation,
            authority: AuthorityPosture::DENY_ALL,
        })
    }

    /// Dispatch exactly one typed actuator command and return a terminal
    /// simulator observation. Any non-deny authority is rejected before the
    /// plant is touched; the plant itself also validates command binding,
    /// generation, tick and calibration identity.
    pub fn dispatch(
        &mut self,
        dispatch: TypedActuatorDispatchV1,
    ) -> Result<SyntheticActuatorReceiptV1, EmbodimentIoError> {
        if dispatch.authority != AuthorityPosture::DENY_ALL {
            return Err(EmbodimentIoError::AuthorityNotDenied);
        }
        if dispatch.actuator_id != self.actuator_id {
            return Err(EmbodimentIoError::ActuatorIdentityMismatch);
        }
        let observed_tick = dispatch.command.observed_tick;
        let terminal_observation = self.plant.advance(dispatch.command)?;
        Ok(SyntheticActuatorReceiptV1 {
            actuator_id: self.actuator_id.clone(),
            observed_tick,
            terminal_payload_digest: terminal_observation.observation_digest(),
            terminal_observation,
            authority: AuthorityPosture::DENY_ALL,
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::CART_Q24_SCALE;
    use codex_hepta_types::Generation;

    fn profile() -> CartSensorProfileV1 {
        CartSensorProfileV1 {
            generation: Generation::new(1).expect("generation"),
            clock: Digest32::of_bytes(b"io.clock"),
            synthetic_calibration: Digest32::of_bytes(b"io.calibration"),
            valid_until_tick: 100,
        }
    }

    fn adapter() -> SyntheticCartIoV1 {
        let profile = profile();
        let plant = CartSimulatorV1::new(
            super::super::CartStateV1 {
                position_q24: CART_Q24_SCALE / 4,
                velocity_q24: 0,
            },
            profile,
        )
        .expect("plant");
        SyntheticCartIoV1::new(
            StableId::new("sensor.cart").expect("sensor id"),
            StableId::new("actuator.cart").expect("actuator id"),
            profile,
            plant,
        )
        .expect("adapter")
    }

    #[test]
    fn typed_sensor_controller_actuator_slice_returns_terminal_receipt() {
        let mut io = adapter();
        let profile = io.profile();
        let reading = io.read_sensor(0).expect("sensor read");
        assert_eq!(reading.sensor_id.as_str(), "sensor.cart");
        assert_eq!(
            reading.payload_digest,
            reading.observation.observation_digest()
        );
        assert_eq!(reading.authority, AuthorityPosture::DENY_ALL);

        let mut controller = super::super::CartControllerV1::new(profile);
        let command = controller
            .command(
                &reading.observation,
                0,
                super::super::CartControlMode::TrackOrigin,
            )
            .expect("controller command");
        let receipt = io
            .dispatch(TypedActuatorDispatchV1 {
                actuator_id: StableId::new("actuator.cart").expect("actuator id"),
                command,
                authority: AuthorityPosture::DENY_ALL,
            })
            .expect("dispatch");
        assert_eq!(receipt.observed_tick, 0);
        assert_eq!(receipt.terminal_observation.tick, 1);
        assert_eq!(
            receipt.terminal_payload_digest,
            receipt.terminal_observation.observation_digest()
        );
        assert_eq!(receipt.authority, AuthorityPosture::DENY_ALL);
    }

    #[test]
    fn non_denied_authority_and_wrong_actuator_are_rejected_without_mutation() {
        let mut io = adapter();
        let reading = io.read_sensor(0).expect("sensor read");
        let mut controller = super::super::CartControllerV1::new(io.profile());
        let command = controller
            .command(
                &reading.observation,
                0,
                super::super::CartControlMode::TrackOrigin,
            )
            .expect("controller command");
        let before = io.read_sensor(0).expect("sensor reread");
        let mut authority = AuthorityPosture::DENY_ALL;
        authority.runtime = true;
        assert_eq!(
            io.dispatch(TypedActuatorDispatchV1 {
                actuator_id: StableId::new("actuator.cart").expect("actuator id"),
                command,
                authority,
            }),
            Err(EmbodimentIoError::AuthorityNotDenied)
        );
        assert_eq!(io.read_sensor(0).expect("sensor reread"), before);

        assert_eq!(
            io.dispatch(TypedActuatorDispatchV1 {
                actuator_id: StableId::new("actuator.other").expect("actuator id"),
                command,
                authority: AuthorityPosture::DENY_ALL,
            }),
            Err(EmbodimentIoError::ActuatorIdentityMismatch)
        );
        assert_eq!(io.read_sensor(0).expect("sensor reread"), before);
    }

    #[test]
    fn sensor_age_and_calibration_expiry_fail_closed() {
        let io = adapter();
        assert_eq!(
            io.read_sensor(3),
            Err(EmbodimentIoError::Cart(CartError::StaleOrFutureSample))
        );
        let profile = io.profile();
        assert_eq!(
            io.read_sensor(profile.valid_until_tick + 1),
            Err(EmbodimentIoError::Cart(CartError::ExpiredCalibration))
        );
    }
}
