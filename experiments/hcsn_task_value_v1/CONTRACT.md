# Task-value continuous-spiking mathematical and event contract

This contract describes the implemented research objects in `model.py`, `operators.py`, `oracle.py`, and `oracle_gradients.py`. The He--Xiong Call/Put terminology motivates an analogy; it does not identify the task values below with financial prices, probabilities, physical forces, or a complete credit equilibrium. Source identities are recorded in `SOURCE_BASELINE.json` and the executed reports.

## 1. Three distinct mathematical objects

| Object | State and dynamics | What is optimized or evaluated |
| --- | --- | --- |
| Brownian policy reference | One active coordinate on `(-infinity,b)`, constant local coefficients, an upper event boundary, fixed reset, Erlang refractory time | The analytic boundary optimizes the specified stationary affine-running-reward contract, under the conditions in section 5. |
| Neural finite probability flow | Per physical cell: 8 active finite-volume bins on `[-2,b)` and 2 refractory phases; upwind rates, conservative moving-boundary overlap maps | `model.py` applies a selected boundary policy. `value_vectors` evaluates that policy on its **own finite generator**. This policy need not optimize that finite grid. |
| General two-cell QVI oracle | Joint tensor state of two bounded active grids and their independent Erlang phases; blocked outward jumps; general running/impulse rewards and stochastic reset kernels | Howard or Jacobi optimizes WAIT/FIRE1/FIRE2 on this particular finite model. The neural forward pass does not call this joint oracle. |

The neural cells retain probability distributions, not only membrane means. Their learned content state is a separate vector. The joint oracle may couple cells through rewards or reset kernels; this does not turn the neural model's independent per-cell flows into a joint distribution. A result for one row of this table is not a certificate for another row.

## 2. Typed event quantities and initial information

Let `pi_0` be the full active-plus-refractory state distribution immediately after the preceding processed observation. Conditional information includes this distribution, held coefficients, the declared event policy, horizon, observation chronology, and reset/refractory law. Let `N` count eligible FIRE events, including declared instantaneous boundary-remap events. Use:

| Symbol | Definition | Unit and implementation status |
| --- | --- | --- |
| `C(T)` | `E[N(T) | information]` | Expected count; nonnegative and potentially greater than 1. `activity`/`events` records this quantity. |
| `P(T)` | `Pr(N(T) >= 1 | information)` | Probability in `[0,1]`; it is not the emitted expected count. The selected neural readout does not separately expose it. |
| `F(T)` | CDF of a specified first passage/event time | Equals `P(T)` only with the same initial distribution, eligibility, event definition, horizon, coefficients, and intervention chronology. An active-only Brownian first-hit formula does not include a remaining refractory delay or a later remap automatically. |
| `H_rho(T)` | `E[exp(-rho*tau_1) 1{tau_1<=T} | information]` | Discounted first-event transform; also specify whether `T` is finite or infinite. It is neither `C` nor a general loss value. |
| `mathcal K(s,dy)` | Conditional reset probability kernel | Every row is nonnegative and sums to 1. It is distinct from event cost `K`. |
| `A(t)` | Expected event flux/rate during a held-coefficient interval | In the neural finite generator, active last-bin mass times its exit rate; unit `events/second`. Instantaneous remap counts are atoms, not finite rates. |
| `pi(t)` | Distribution over active bins and refractory phases | The tensor named `probability`; it is not `P(T)`. |

For the same event count, `C(T) >= P(T)`. Equality requires at most one event almost surely. Absorbing first-hit/no-event propagation and regenerative repeated-event propagation are different operators. A no-event operator is substochastic; its lost mass must not be normalized back to one. `advance_probability` accepts only the tagged regenerative operator and records its bounded roundoff correction.

For an observation step, define the count as the sum of evolution events over its elapsed duration and the endpoint observation-map event. This definition remains meaningful at zero duration: evolution contributes zero, but a shrinking boundary may still trigger a map event. Standard interval notation must not silently discard that atom.

The current neural initial state interpolates the subthreshold coordinate `x=0` onto active bin centers. A different initial state already above the boundary requires an explicit immediate event; it must not be silently projected below threshold. Initial refractory mass starts with its stated remaining phase, not a fresh refractory clock.

## 3. Physical time, observation order, and missingness

`dt` is in **seconds**; `Classifier.config.seconds_per_dt` is 1. No multiplier converts an audiovisual event gap into an arbitrary internal step. Drift has units `state/second`, diffusion `state/sqrt(second)`, and discount `1/second`. The payoff uses one utility unit per state unit, so `K` is an event utility cost and `a*x` is utility per second.

For an observation at `t_k`, `prepare_interval` and `RewardFlowCell.forward` perform this ordered update:

1. Propagate the previous probability state through `(t_{k-1},t_k)` using the **previous held coefficients**, accumulating repeated count, running reward, and event payoff.
2. Receive the current observation, select its new coefficients and boundary, and remap the propagated distribution by physical-bin overlap. Active mass above a new lower boundary triggers an immediate event; its payoff integrates its actual previous physical location minus current `K`.
3. Preserve existing refractory phase mass during remapping. The remap does not restart refractory residence. Phase progression occurred during the elapsed interval and continues in subsequent intervals.
4. Complete content decay using the previously held recovery gate, then use current information to write content and select the next held gate. The current observation cannot change coefficients or content writes during the elapsed past interval.

At identical audiovisual timestamps, `async_av.merge_observations` uses ascending time and then **audio before video**. The second event has `dt=0`; both observations can update content and boundary in that fixed order. No claim of invariance under swapping tied modalities is made.

There are two distinct missingness cases:

- `observed=False` at the model API means there is no new observation to consume: keep the held signal/coefficients, suppress content writing, and still evolve probability, refractory phases, and content decay for nonzero `dt`. Padded rows have zero `dt` and no new observation.
- A **known missing acquisition** in the audiovisual frontend retains its acquisition time, modality marker, valid terminal position, and zeroed payload/delta and observed-modality flags. The frontend's last observed modality state is unchanged. The registered `experiment.data` adapter sets `observed = valid & any(payload-observed flags)`: without a new payload, HCSN evolves through the elapsed time but does not refresh its held signal/coefficients or write content. Treating known missingness metadata as a new observation is a permissible different API contract, but is not this registered adapter's behavior.

Missing payload is not an observed zero or silence. Source missingness is not claimed: modality removal is an imposed intervention. Frontend feature differences and ages use past observed values only. Evaluation must read the last valid event, not padded output.

The registered external two-gate and LIF controls take one discrete recurrent step per observed event, including the first event and tied events with `dt=0`; an unobserved event skips that recurrent step. Physical seconds remain shared input features. This is an event-index recurrence, not the same physical-time differential equation as the HCSN flow.

## 4. Reset, refractory residence, and reward accounting

On an eligible boundary event the neural flow enters refractory phase zero. It traverses `m` exponential stages at rate `lambda=m/tau`, then recovers through the interpolated reset kernel. Its duration has mean `tau`, variance `tau^2/m`, and transform

\[
D(\rho)=\left(1+\rho\tau/m\right)^{-m}.
\]

This is an Erlang law, not a deterministic delay. Neural stage indices progress `0 -> ... -> m-1 -> recovery`; the two-cell oracle enters its final refractory index and counts down to zero before recovery. The index conventions represent the same Erlang law and must not be compared as equal remaining times at equal raw indices. Refractory mass cannot FIRE. It may recover and fire again within a sufficiently long observation interval, so count can exceed one. Reset and refractory parameters are trainable; in the current model they are input-independent and therefore held fixed within a forward episode. A new boundary changes neither existing phase identity nor elapsed residence.

Current active running reward is `g(x)=a*x`; refractory running reward is zero. Active interval exits pay `b_old-K_old`; observation remap events pay `x_old-K_current`. `reward` is the **undiscounted expected accumulated** running-plus-impulse reward of that step. `cost` separately records expected event cost using the corresponding old/current `K`; it is not CPU time, FLOPs, energy, or a second payoff to subtract without declaring a new objective.

The general oracle permits signed running reward on every state, including refractory states, and signed state-dependent impulse reward. It therefore permits negative values; the zero-running-reward “wait forever has zero value” argument is not applicable universally. General rewards may create disconnected firing regions.

## 5. Verified affine Brownian policy and admissible domain

For held coefficients, active dynamics are `dX=mu dt+sigma dW`. FIRE pays `X-K`, followed by zero-reward refractory residence and reset to `r`. Discount is `rho>0`; `sigma>0`, `tau>0`, and phase count `m` is a positive integer. To avoid conflict with the activity rate `A(t)`, write the amplitude as `beta`:

\[
\kappa=\frac{\sqrt{\mu^2+2\rho\sigma^2}-\mu}{\sigma^2},\qquad
U(x)=\frac{ax}{\rho}+\frac{a\mu}{\rho^2},\qquad
\beta=1-a/\rho.
\]

\[
K_{\rm eff}=\frac{K+U(0)-D U(r)}{\beta},\qquad
\kappa(b-K_{\rm eff})+D e^{-\kappa(b-r)}-1=0.
\]

The implemented upper-boundary family requires `beta>0` and `K_eff>r`. The equivalent delay passed to the existing implicit root is `tau_eff=(m/rho)*log1p(rho*tau/m)`, so `exp(-rho*tau_eff)=D` exactly in real arithmetic. This changes the transform used in the root; it does not relabel the physical refractory law as deterministic.

Below the optimal boundary,

\[
J(x)=U(x)+\frac{\beta}{\kappa}e^{\kappa(x-b)},\qquad
G(x)=x-K+D J(r).
\]

Value matching and smooth fit are `J(b)=G(b)` and `J'(b)=G'(b)=1`, not the financial equity conditions `E(b)=E'(b)=0`. Above `b`, immediate intervention is optimal for this contract. In the continuation region `J-G>=0`; its derivative is `beta*(exp(kappa*(x-b))-1)`. The stopping-region WAIT residual is negative at the boundary and decreases with `x` because `a-rho<0`.

These statements concern a stationary one-dimensional reward contract. An observation-dependent learned slope does not make this boundary the optimizer of future classification loss, a jointly controlled multimodal sequence, or the coarse finite flow.

## 6. Values and channels in the actual neural finite flow

For a selected boundary policy, let `Q^pi` be its finite regenerative generator, `e` its event-rate vector, and `g` its active running-reward vector padded by zero refractory reward. `operators.value_vectors` solves

\[
(\rho I-Q^\pi)J^\pi=g+e(b-K).
\]

On active centers, `G_i=x_i-K+J_phase0`; on refractory states `G=J` denotes forced continuation, not eligibility to intervene. Both values include the true finite phase/reset dynamics. They are task utilities, not probabilities or restoring/panic forces. Their probability-weighted readouts may be signed and unbounded before the explicitly used `v/(1+abs(v))` squash.

The dual features are active-mass-weighted safety margin, squashed `pi*J`, and squashed `pi*G`. The margin is `sum_active pi_i*(b-x_i)`, not a conditional mean given active status. The physical gate also sees the full probability vector and local coefficients. Content is carried by the learned recurrent vector; boundary or value features alone are not a complete representation of the input.

`fixed`, `direct`, `value`, and `stop_gradient` are distinct policy modes. Freezing boundary-group parameters is also distinct from a fixed boundary: a value boundary can still change through live drift/noise inputs. A `stop_gradient` mode preserves its forward boundary while disconnecting that boundary's derivative.

## 7. General finite QVI and derivative contract

In the joint oracle, `mathcal K_i(s_-i,dy)` is a convex recovery kernel allowed to depend on the other cell's current state. FIRE changes only the eligible cell to its terminal-index refractory entry; stage numbering differs from the neural flow but the declared stage progression is explicit. The finite QVI is

\[
\max\{g+QJ-\rho J,\ R_1+T_1J-J,\ R_2+T_2J-J\}=0,
\]

with ineligible FIRE branches omitted. Two instantaneous fires can occur consecutively, after which a positive-time WAIT/recovery is required. Independent additive cells can have exactly tied, interchangeable firing orders. General policies are returned without assuming one continuous threshold.

For a fixed policy, `A_pi J=b_pi` and `A_pi dot(J)=dot(b_pi)-dot(A_pi)J`. At optimal-action ties, the right directional derivative solves

\[
\max_{a\in\mathcal A^*(s)}\{\dot b_a-\dot A_aJ-A_a u_+\}=0.
\]

The conventional left derivative is `u_-=-D^+J[-direction]`. A nonzero right/left difference is reported as a kink. A fixed-policy derivative alone is not an optimal-value derivative at every tie. Numerical active-set tolerance, base residual, and independently reoptimized finite differences remain part of the evidence.

Phase counts and grids are fixed during these derivatives. Coordinate-reset interpolation is piecewise differentiable; exact nodes require separate one-sided kernels. Centered/upwind stencil switches are also excluded from an undeclared ordinary derivative. Explicit reset tangents preserve row mass and stay within their probability support. These are finite-model derivatives, not general continuum free-boundary regularity results.

## 8. Executed evidence and remaining limits

| Evidence file, relative to this directory | Verified scope |
| --- | --- |
| `results/oracle001/report_20261031T013802298061Z.json` | General finite QVI, 9 tests, independent residual/Jacobi, selected reoptimized FD, and 3 x 700 independent event trajectories. |
| `results/oracle001/report_20261031T013733199135Z.json` | Retained first failure: a bit-equality assertion rejected `4.44e-16` summation roundoff; model unchanged, assertion changed to a declared roundoff tolerance. |
| `results/oracle001/affine_20261031T014102544158Z.json` | Independent explicit-phase spatial QVI: at `h=.00625`, value error `1.88168e-6`, boundary-node error `9.58425e-4`; seven value-gradient errors decrease under refinement. |
| `results/gradient001/oracle_gradients.json` | Independent multi-parameter reoptimization and a true one-sided event-reward kink. |
| `results/flow002/flow_audit.json` | Current source hashes, 8 passing tests, boundary gradients, own-generator values, matrix-exponential comparisons, chronology/chunking/missing-payload/unobserved-wait checks. Earlier `flow001` evidence is retained. |
| `results/experiment001/experiment_audit.json` | 4 passing train-only/interface tests: zero-duration first-event information for external controls, missing-payload behavior, last-valid AV supervision, and retained-state storage. |
| `results/async_frontend001/RESULT.json` | Decoded timestamp/causal-prefix frontend evidence and its explicit previously observed heldout limitation. |

The fine spatial validation does not certify the neural model's 8-bin approximation; coarse-grid policy/value gaps remain relevant. The two-cell grid oracle does not establish a scalable many-cell continuum optimizer. Learned local rewards and successful derivatives do not establish optimal sequence decisions or a quality advantage over matched ordinary models. Hardware throughput, latency, memory, and energy require actual measured execution, including numerical propagation and value solves; event counts alone cannot establish those benefits. Validation claims are tied to the source hashes and domains in the reports, not to later untested edits.
