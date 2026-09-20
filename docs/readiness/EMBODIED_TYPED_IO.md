# Typed embodiment I/O slice

`codex-hepta-control-plane::SyntheticCartIoV1` is the repository's first native
sensor-to-controller-to-actuator vertical slice. It is deliberately bounded to
the deterministic Q24 cart simulator and provides a typed seam for the later
simulator/HIL adapter:

1. `read_sensor(now_tick)` returns `TypedSensorReadingV1`, binding sensor id,
   body generation, clock, calibration, monotonic tick and a typed cart state.
   Future, stale and expired-calibration samples fail closed.
2. The existing bounded `CartControllerV1` consumes that observation and emits a
   generation/tick/profile/observation-bound `CartCommandV1`.
3. `dispatch(TypedActuatorDispatchV1)` checks actuator identity and requires the
   explicit `AuthorityPosture::DENY_ALL` posture before advancing the plant.
   `SyntheticActuatorReceiptV1` records the terminal typed observation and its
   digest.

The path is deterministic and has no credentials, model calls, network, writer,
or external effect authority. A successful receipt means one simulator step; it
is not a hardware actuation, calibration certificate, physical-safety result,
or production readiness claim. A hardware adapter must implement the same
identity, generation, calibration, age, payload-binding, watchdog and terminal
reconciliation rules and then pass independent HIL and safety gates.

Native tests cover a complete sensor/controller/actuator step, authority and
actuator-identity rejection without plant mutation, and stale/expired sensor
fail-closed behavior.
