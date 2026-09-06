use super::*;
use pretty_assertions::assert_eq;

fn ok<T, E: std::fmt::Debug>(result: Result<T, E>) -> T {
    match result {
        Ok(value) => value,
        Err(error) => panic!("fixture failed: {error:?}"),
    }
}

fn profile() -> CartSensorProfileV1 {
    CartSensorProfileV1 {
        generation: ok(Generation::new(1)),
        clock: Digest32::of_bytes(b"sim.clock"),
        synthetic_calibration: Digest32::of_bytes(b"synthetic direct state"),
        valid_until_tick: 10_000,
    }
}

#[test]
fn typed_controller_and_plant_replay_the_explicit_euler_q24_golden() {
    let mut simulator = ok(CartSimulatorV1::new(
        CartStateV1 {
            position_q24: CART_Q24_SCALE / 2,
            velocity_q24: 0,
        },
        profile(),
    ));
    let mut controller = CartControllerV1::new(profile());
    let (mut reference_x, mut reference_v) = (0.5_f64, 0.0_f64);
    for tick in 0..1_000 {
        let observation = simulator.observe();
        let command = ok(controller.command(&observation, tick, CartControlMode::TrackOrigin));
        let next = ok(simulator.advance(command));
        let reference_u = (-4.0 * reference_x - 4.0 * reference_v).clamp(-2.0, 2.0);
        reference_x += 0.01 * reference_v;
        reference_v += 0.01 * reference_u;
        assert!(
            (next.state.position_q24 as f64 / CART_Q24_SCALE as f64 - reference_x).abs() < 0.000_01
        );
        assert!(
            (next.state.velocity_q24 as f64 / CART_Q24_SCALE as f64 - reference_v).abs() < 0.000_01
        );
        if tick == 0 {
            assert_eq!(
                next.state,
                CartStateV1 {
                    position_q24: 8_388_608,
                    velocity_q24: -335_544
                }
            );
        }
    }
    assert_eq!(
        simulator.observe().state,
        CartStateV1 {
            position_q24: 13,
            velocity_q24: -25
        }
    );
}

#[test]
fn quantized_braking_reports_its_difference_from_the_rational_reference() {
    let mut simulator = ok(CartSimulatorV1::new(
        CartStateV1 {
            position_q24: 0,
            velocity_q24: CART_Q24_SCALE,
        },
        profile(),
    ));
    let mut ticks = 0;
    for _ in 0..100 {
        let stopped = ok(simulator.emergency_brake());
        ticks += 1;
        if stopped.state.velocity_q24 == 0 {
            break;
        }
    }
    assert_eq!(
        (ticks, simulator.observe().state),
        (
            51,
            CartStateV1 {
                position_q24: 4_278_194,
                velocity_q24: 0
            }
        )
    );
    // Exact rational Euler braking is 50 ticks / 0.255 m; native accumulated
    // quantization leaves 16 Q24 LSB of velocity at tick 50, requiring one more.
    assert!(
        (simulator.observe().state.position_q24 as f64 / CART_Q24_SCALE as f64 - 0.255).abs()
            < 0.000_001
    );
}

#[test]
fn rejected_dispatch_does_not_mutate_the_plant_and_stop_fences_old_work() {
    let mut simulator = ok(CartSimulatorV1::new(
        CartStateV1 {
            position_q24: 0,
            velocity_q24: CART_Q24_SCALE / 2,
        },
        profile(),
    ));
    let before = simulator.observe();
    let command = CartCommandV1 {
        generation: profile().generation,
        observed_tick: 0,
        acceleration_q24: 3 * CART_Q24_SCALE,
        saturated: false,
    };
    assert_eq!(simulator.advance(command), Err(CartError::InvalidCommand));
    assert_eq!(simulator.observe(), before);
    let stopped = ok(simulator.emergency_brake());
    let queued = CartCommandV1 {
        observed_tick: stopped.tick,
        acceleration_q24: CART_Q24_SCALE,
        ..command
    };
    assert_eq!(simulator.advance(queued), Err(CartError::InvalidCommand));
    assert_eq!(simulator.observe(), stopped);
    assert_eq!(
        CartStateV1 {
            position_q24: CART_Q24_SCALE,
            velocity_q24: CART_Q24_SCALE / 2
        }
        .validate(),
        Err(CartError::StoppingMargin)
    );
}

#[test]
fn stale_future_duplicate_generation_and_calibration_samples_are_rejected() {
    let simulator = ok(CartSimulatorV1::new(
        CartStateV1 {
            position_q24: 0,
            velocity_q24: 0,
        },
        profile(),
    ));
    let sample = simulator.observe();
    let mut controller = CartControllerV1::new(profile());
    assert_eq!(
        controller.command(&sample, /*now_tick*/ 3, CartControlMode::TrackOrigin),
        Err(CartError::StaleOrFutureSample)
    );
    let future = SyntheticCartObservationV1 { tick: 1, ..sample };
    assert_eq!(
        controller.command(&future, /*now_tick*/ 0, CartControlMode::TrackOrigin),
        Err(CartError::StaleOrFutureSample)
    );
    let mixed = SyntheticCartObservationV1 {
        generation: ok(Generation::new(2)),
        ..sample
    };
    assert_eq!(
        controller.command(&mixed, /*now_tick*/ 0, CartControlMode::TrackOrigin),
        Err(CartError::IdentityMismatch)
    );
    assert_eq!(
        controller.command(
            &sample,
            /*now_tick*/ 10_001,
            CartControlMode::TrackOrigin
        ),
        Err(CartError::ExpiredCalibration)
    );
    ok(controller.command(&sample, /*now_tick*/ 0, CartControlMode::TrackOrigin));
    assert_eq!(
        controller.command(&sample, /*now_tick*/ 0, CartControlMode::TrackOrigin),
        Err(CartError::ClockRegression)
    );
}

#[test]
fn controller_reports_saturation_and_keeps_stop_latched() {
    let simulator = ok(CartSimulatorV1::new(
        CartStateV1 {
            position_q24: CART_Q24_SCALE / 2,
            velocity_q24: CART_Q24_SCALE / 2,
        },
        profile(),
    ));
    let sample = simulator.observe();
    let mut controller = CartControllerV1::new(profile());
    let command = ok(controller.command(
        &sample,
        /*now_tick*/ 0,
        CartControlMode::EmergencyBrake,
    ));
    assert!(command.saturated);
    let next = SyntheticCartObservationV1 {
        tick: 1,
        state: CartStateV1 {
            position_q24: CART_Q24_SCALE / 2,
            velocity_q24: 0,
        },
        ..sample
    };
    assert_eq!(
        ok(controller.command(&next, /*now_tick*/ 1, CartControlMode::TrackOrigin)),
        CartCommandV1 {
            generation: profile().generation,
            observed_tick: 1,
            acceleration_q24: 0,
            saturated: false
        }
    );
}
