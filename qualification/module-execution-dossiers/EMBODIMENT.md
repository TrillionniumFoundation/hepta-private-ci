# Simulator-first body and controller pilot

Scope: a concrete proposed `EMB-0` through `EMB-3` profile, not physical activation or AGI certification. It implements one small plant before a general body. CNS roles, owner modules and their authority remain unchanged.

## 1. Plant and body state

The first simulator is a one-dimensional unit-mass cart with state position x in metres and velocity v in metres/second, action acceleration u in metres/second squared and sample period dt=0.01 seconds. The canonical discrete plant is explicit Euler: x_next=x+dt*v; v_next=v+dt*u. Do not silently substitute another integrator or time unit.

The simulator supplies tagged x/v observations with monotonic tick, clock identity, calibration, body generation, source interval and uncertainty. Simulation truth is labelled synthetic, not real sensor calibration. The initial profile has direct state observation; a later partial-observation filter requires a separate estimator profile and calibration tests.

## 2. Deterministic control and mathematical scope

For target x=0,v=0, use u=clip(-4*x-4*v,-2,2). With no saturation, the ideal closed-loop matrix is [[1,0.01],[-0.04,0.96]], characteristic polynomial (lambda-0.98)^2. This proves stability of that ideal discrete linear model, not robustness to arbitrary delay, contact, rounding, noisy sensors or hardware failures.

The initial experiment starts at x=0.5,v=0. Proposed engineering bounds are |x|<=1, |v|<=1 and |u|<=2. An independent envelope monitor rejects a requested trajectory outside the qualified reachable region; merely clipping acceleration does not ensure a safe stopping distance. The test suite reports trajectories, constraints and saturation rather than claiming a general invariant set from this one starting point.

Reference arithmetic may be exact rational. Native Q24 implementation binds rounding/projection and compares declared conversion error and replay goldens. A different controller, gain, plant, integrator or dt is a new profile, not an in-place change to the active body.

## 3. Timing and emergency path

Proposed local periods are 1 ms reflex and 10 ms sensor/control, with sensor maximum age 20 ms and watchdog expiry 30 ms. These are design targets, not measurements. Essential paths preallocate bounded state and have no model call, synchronous CNS RPC or unbounded retry.

Use response-time analysis with actual qualified worst-case execution C, blocking B, periods T and deadlines D: R_i=C_i+B_i+sum_j ceil(R_i/T_j)*C_j for higher-priority tasks, solved within a bounded iteration count. Require R_i<=D_i, and account for I/O, IRQ, kernel and clock effects in the target profile. p99 latency alone cannot establish a hard deadline.

The stated response-time recurrence assumes one processor, fixed priorities, preemptible tasks, bounded blocking and no unaccounted release jitter. A different scheduler, multicore interference or release jitter requires its own analysis/profile; do not reuse this scalar fixture as its certificate.

An emergency stop directly reaches the local safe-state mechanism without model cooperation. Hardware stop circuitry, watchdog, force/speed limits and restart interlocks need independent target evidence. In this exact simulator, the stop profile commands `u=clip(-v/dt,-2,2)` each tick until v=0. The sufficient symmetric stopping-margin check is `abs(x)+v*v/4+abs(v)*dt<=1` before accepting the profile. Outside that margin, declare the state unqualified rather than claim that braking guarantees containment. For x=0,v=1, the explicit-Euler stop takes 50 ticks and travels 0.255 m. This does not model hardware delay or friction. Zero acceleration never means instantaneous zero velocity.

## 4. World-model implementation

Keep transition estimation separate from value estimation. The first learned simulator candidate fits a small action-conditioned linear transition model to immutable training episodes and compares with the exact known plant baseline. Fit only on supported state/action coverage; condition the design matrix, declare estimator/regularization and reject insufficient support.

Validate held-out one-step and twenty-step position/velocity error, prediction interval calibration, out-of-range events and action intervention response. Proposed simulator-only targets are position RMSE<=0.01 m, velocity RMSE<=0.02 m/s and twenty-step position RMSE<=0.05 m within the declared region. A safety-monitor failure is never compensated by average prediction accuracy. Synthetic rollouts cannot certify actual external outcomes.

## 5. Scheduling, uncertainty and fault matrix

Reject stale/future-skewed samples, expired calibration, clock regression, mixed body generations and unknown units before fusion. A sensor/actuator failure cannot be disguised as model uncertainty with an invented confidence score. Essential disagreement routes to local veto/stop or a previously qualified fallback.

Inject sample loss/duplication, delayed commands, saturation, stuck actuator, central outage, clock drift, lost acknowledgements, new body generation, thermal/resource breach and emergency stop during dispatch. Payload changes after final authorization require re-binding or veto. Local feedback may cycle only under its registered bounded profile; startup/fallback graphs stay acyclic.

## 6. Expansion and acceptance

Progress through deterministic simulator, randomized digital twin, software-in-loop, hardware-in-loop, supervised bounded canary and separately authorized activation. Record exact simulator/hardware/firmware/calibration and target OS identities, timing distributions, deadline misses, stop latency, sim-to-real residuals and rollback. Digital browser/Matrix/service organs can exercise the same identity/intent/outcome rules without claiming physical embodiment.

Next plants add partial observability, contact and multiple degrees of freedom only after concrete body frames, estimator/controller, sample timing, constraints and hazard tests are frozen. A complete organ registry or successful cart simulation is not a claim of general intelligence, human anatomical equivalence or arbitrary-robot control.
