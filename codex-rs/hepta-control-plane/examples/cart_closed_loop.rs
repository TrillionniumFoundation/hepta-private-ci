//! Executable software-in-loop trace through the existing typed body adapter.
//! No wall-clock/HIL/physical safety or learning efficacy is claimed.
use std::io;
use std::io::Write;

use codex_hepta_control_plane::CART_Q24_SCALE;
use codex_hepta_control_plane::CartControlMode;
use codex_hepta_control_plane::CartControllerV1;
use codex_hepta_control_plane::CartSensorProfileV1;
use codex_hepta_control_plane::CartSimulatorV1;
use codex_hepta_control_plane::CartStateV1;
use codex_hepta_control_plane::SyntheticCartIoV1;
use codex_hepta_control_plane::TypedActuatorDispatchV1;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

fn native<T, E: std::fmt::Debug>(value: Result<T, E>) -> io::Result<T> {
    value.map_err(|error| io::Error::other(format!("native cart boundary: {error:?}")))
}

fn main() -> io::Result<()> {
    let args = std::env::args().skip(1).collect::<Vec<_>>();
    let steps = match args.as_slice() {
        [] => 1000,
        [flag, count] if flag == "--steps" => count.parse::<u64>().map_err(io::Error::other)?,
        _ => {
            return Err(io::Error::other(
                "usage: cart_closed_loop [--steps 1..10000]",
            ));
        }
    };
    if !(1..=10_000).contains(&steps) {
        return Err(io::Error::other("steps must be in 1..10000"));
    }
    let profile = CartSensorProfileV1 {
        generation: native(Generation::new(1))?,
        clock: Digest32::of_bytes(b"cart-cli-simulation-10ms-v1"),
        synthetic_calibration: Digest32::of_bytes(b"direct-synthetic-state-v1"),
        valid_until_tick: steps,
    };
    let initial = CartStateV1 {
        position_q24: CART_Q24_SCALE / 2,
        velocity_q24: 0,
    };
    let mut body = native(SyntheticCartIoV1::new(
        native(StableId::new("sensor.cart"))?,
        native(StableId::new("actuator.cart"))?,
        profile,
        native(CartSimulatorV1::new(initial, profile))?,
    ))?;
    let mut controller = CartControllerV1::new(profile);
    let mut output = io::BufWriter::new(io::stdout().lock());
    writeln!(
        output,
        "tick,position_q24,velocity_q24,acceleration_q24,observation_digest"
    )?;
    for tick in 0..steps {
        let reading = native(body.read_sensor(tick))?;
        let command =
            native(controller.command(&reading.observation, tick, CartControlMode::TrackOrigin))?;
        let acceleration = command.acceleration_q24;
        let receipt = native(body.dispatch(TypedActuatorDispatchV1 {
            actuator_id: native(StableId::new("actuator.cart"))?,
            command,
            authority: AuthorityPosture::DENY_ALL,
        }))?;
        let state = receipt.terminal_observation.state;
        writeln!(
            output,
            "{},{},{},{},{}",
            receipt.terminal_observation.tick,
            state.position_q24,
            state.velocity_q24,
            acceleration,
            receipt.terminal_payload_digest
        )?;
    }
    output.flush()
}
