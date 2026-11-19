# Shared-generator quantities and persistent DDE state

Research successor to #6129 through the executable graded migration #6144 and
the source/target binding fix #6153. Exact parent is
`16466e0bbb7808783453c6854803201560acab45`.
This contract retains the definitions in `hcsn_differentiable/MODEL.md` §6.
It does not rename financial equity into a neural reward.

## Quantities, clocks and units

Let `tau` be the first lower hit in one killed active cycle, `q>0` the
discount rate, `d>0` the deterministic refractory delay, `x_r>0` the reset
distance, `a` a constant reward/time and `h` a reward/event. Time has the
units of the actual supplied timestamps; event rate is Hz only for seconds.
The joint solver fixes these parameters over the whole retained history.

| Quantity | Definition | Units and horizon |
| --- | --- | --- |
| `C_T(x)` | Expected discounted running reward until `min(T,tau)`, optionally plus a declared terminal payoff on survival; zero absorption payoff. | Reward, one killed cycle, finite horizon. Here terminal payoff is zero. |
| `F(T,x)` | `P_x(tau <= T)`. | Probability, one cycle; bounded by one. |
| `G_q(T,x)` | `E_x[exp(-q*tau) 1(tau <= T)]`. | Discounted first-hit probability, one cycle. `1-G_q` is not survival. |
| `U(x)` | Full perpetual regenerative reward, including every hit, every delay and reset continuation. | Reward, infinite horizon, fixed policy. |
| `J(t)` | `d E[N_t]/dt`, including hits after resets. In the nodal model it is `lower @ active(t)`. | Expected events/time, episode clock. |
| `M(t)` | `E[N_t] = integral_0^t J(s) ds`. | Expected event count, may exceed one; episode clock. |

The first-hit density `f=dF/dT` and repeated-event density `J` differ after
regeneration. Define the separate single-cycle quantity
`C^(a,h)(x)=a(1-G_q(infinity,x))/q+h G_q(infinity,x)`.
Then `U(x)=C^(a,h)(x)+G_q(infinity,x) exp(-q*d) U(x_r)` and
`U(x_r)=C^(a,h)(x_r)/(1-exp(-q*d)G_q(infinity,x_r))`.
The hit payoff is paid on entering refractory state, never again on release.
At remaining delay `r`, continuation is `exp(-q*r) U(x_r)`.

`JointModel.perpetual()` uses the same finite CTMC generator and reset law as
`solve()`. Its upper boundary is a permanently active, nonreturning escape
compartment with continuation `a/q`, not a returning half-line tail. Initial
lower-boundary mass is rejected. A zero-time release atom enters reset once;
the query at the release deadline sees the state after release. Releasing a
refractory packet is not a new hit and does not increment M.

## Mapping solver fields to the mathematical objects

| Field | Meaning |
| --- | --- |
| `active`, `upper`, `refractory` | Current probability and signed marked measures. Column zero is probability; other columns are signed content, not probabilities. |
| `events` | M and its signed-mark counterparts, cumulative from the original episode origin. |
| `discounted_events` | `H_q(t)=integral_0^t exp(-q*s) J(s) ds`; repeated hits, not G. |
| `discounted_active_time` | `A_q(t)=integral_0^t exp(-q*s) P(active at s) ds`, including upper escape. Units: time. |
| `discounted_remaining_phase` | Current remaining-age measure integrated against `exp(-q*r)`. Dimensionless; it is one moment, not a sufficient delay state. |

The finite accrued reward is `a*A_q(t)+h*H_q(t)`. Add the current
continuation, discounted by `exp(-q*t)`, to compare with the original U.
The solver does not label M as a risk probability, does not supply a QVI/free
boundary, and does not count repeated queries as rewards or observations.

## A checkpoint contains the actual causal state

`solve(..., export_state=True)` returns bounded canonical JSON checkpoint
bytes. `solve(absolute_query_times, checkpoint=bytes, ...)` advances from its
retained clock. It does not reexecute the episode prefix. The checkpoint keeps:

- Current interior/upper/refractory probability and every signed-content
  channel, cumulative reward/event integrals, and original conserved totals.
- Accepted BDF Newton polynomials of lower-hit flux covering the last delay
  window. These are the actual dense solution coefficients, not a sampled
  histogram or a uniform distribution of recent hit mass.
- Unreleased initial uniform/atomic packets and original source discontinuity
  times. Source jumps remain split after each delay shift.
- Exact physics, local source hashes, absolute episode clock, numerical schema
  and a byte digest. Changed source/physics and missing history are rejected.

Restore recomputes refractory mass and the discount-age moment from retained
flux and pending sources, for every signed channel. It also requires unique
atom deadlines, complete pending-source breakpoints, and the same bounded
breakpoint budget before expanding the restored schedule. These checks reject
the separately retained deleted-source/deleted-knot counterexamples.

Polynomials are evaluated from portable numeric coefficients, without pickle
or an executable deserialization format. Restoring at an atom deadline does
not release it twice. The digest detects corruption, not provenance or owner
authorization. This format is version-bound; it does not implicitly migrate
checkpoints from a different solver, grid or parameter version.

Continuation restarts the BDF integrator from the saved physical state and
history. It is not bitwise identity with an uninterrupted adaptive integrator;
all state channels and the dynamic value identity are checked under tightened
controls. The returned `internal_steps` counts only work performed in the
current call, and `integration_started_at` exposes the actual resume clock.

## Qualification boundaries

Cold-process tests exercise real dense histories, source/physics fences,
multiple irregular resumes, pending uniform release, exact atoms, signed
content and an independent serial CTMC reference inherited from #6129.
Two different remaining-age laws can share every returned summary at time
zero and later differ by approximately 0.498 in active mass; a regression
retains that distinction through serialization.

This closes a bounded numerical-state continuation implementation gap. It
does not repair uniform-grid short-time first-hit errors, qualify posterior
migration, make parameter changes during a retained history valid, serialize
an autograd graph, complete six original C2 training replays, establish task
benefit or authorize Cell adoption. Overall research status remains HOLD.
