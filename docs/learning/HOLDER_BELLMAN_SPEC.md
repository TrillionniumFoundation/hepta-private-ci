# Hölder-regular Bellman operator implementation specification

**Plan:** `HEPTA-GLOBAL-MODULAR-DEVELOPMENT-PLAN` v8.0.0  
**Specification:** `ALG-HOLDER-BELLMAN`  
**Bound modules:** `learning.operator`, `learning.artifacts`, `intuition.policy`  
**Documentation state:** `closed`  
**Implementation state:** not implied

## 1. Scope, ownership and non-claims

This specification defines the only permitted use of Hölder-space Bellman/operator learning in Hepta. `learning.operator` trains qualification-space candidates; `learning.artifacts` owns immutable sensor cores and operator artifacts; `intuition.policy` may consume a selected value signal but may not train, install or promote it.

The whole Hepta system is not converted into DQN. The method applies only to explicitly registered continuous state coordinates for which an applicability certificate is current. Discrete events, jumps, authority, truth, deletion, leases, CAS and writer ownership remain hybrid or deterministic axes. The cited paper does not prove convergence of a complete sampled implementation with exploration, replay, target networks and stochastic-gradient optimization; Hepta therefore treats learned operators as bounded candidates requiring independent causal evaluation.

## 2. Symbols, dimensions, units and normalization

| Symbol | Meaning | Pilot bound |
|---|---|---:|
| `x in X` | smooth continuous state | `d_x <= 32`, normalized compact box |
| `j in J` | discrete event/jump state | at most `256` registered categories |
| `h in H` | deterministic hard state | digest-bound, never learned |
| `a in A` | legal action | `d_a <= 16` continuous plus bounded category |
| `dt` | control interval | `[10 ms, 1 hour]` |
| `b(t,x,a)` | controlled drift | bounded vector |
| `sigma(t,x,a)` | diffusion factor | bounded matrix |
| `r(t,x,a)` | bounded instantaneous utility | Q32 |
| `g(x)` | bounded terminal value | Q32 |
| `T_dt` | one-step Bellman operator | artifact function |
| `S={x_i}` | fixed sensor core | `N <= 4096` pilot |
| `h_S` | fill distance | normalized state units |
| `q_S` | separation radius | normalized state units |
| `rho_S=h_S/q_S` | mesh ratio | dimensionless |
| `R` | measured separation rank | `<=64` pilot |

Normalization, reachable-set bounds, axis class, action metric, fixed-point scale and event-boundary semantics are versioned. An axis may move from jump to smooth only through a new applicability certificate and artifact generation. Hard axes cannot be embedded into a learned latent vector to evade this rule.

## 3. Formal model and invariants

The paper-aligned analysis domain uses a controlled diffusion

\[
dX_t=b(t,X_t,a_t)dt+\sigma(t,X_t,a_t)dW_t
\]

on a compact reachable subset and the finite-horizon Bellman update

\[
(T_{dt}V)(t,x)=\sup_{a\in A}E\left[\int_t^{t+dt}r(s,X_s,a)ds+V(t+dt,X_{t+dt})\right].
\]

An `OperatorApplicabilityCertificateV1` is mandatory and records:

1. the exact smooth axes and excluded jump/hard axes;
2. compact operating domain and action space;
3. empirical or analytical Hölder exponent and constants for `b`, `sigma`, `r` and terminal values;
4. state Lipschitz diagnostics and action Lipschitz diagnostics;
5. the lower bound `nu` for uniform ellipticity of `sigma sigma^T`;
6. event-to-control-interval mapping and horizon;
7. out-of-domain detector, expiry and independent evaluator;
8. fallback when any assumption is unsupported.

Uniform ellipticity means every unit vector `v` satisfies `v^T sigma sigma^T v >= nu` on the declared domain. A lower confidence bound `nu_LCB <= 0` fails the certificate. Deliberately injecting artificial noise into an authority or truth coordinate is forbidden.

Hepta partitions state as `(x,j,h)`. The operator conditions only on a frozen jump/hard snapshot. A jump creates a new segment and may change the active operator artifact. It does not receive a fictitious smooth interpolation. The learned branch/trunk architecture is anisotropic:

```text
continuation-value samples on fixed sensor core -> branch encoder
smooth state x -> Hölder-state trunk
legal action a -> Lipschitz/categorical action trunk
jump/hard snapshot -> bounded conditioning digest, not learned transition authority
rank-R tensor product -> direct value/action-gap/operator output
```

Reconstruction weights must be nonnegative and sum to one where monotonicity and positivity are required. The measured `L_infinity` reconstruction gain must be at most `1.02`. Low separation rank is an empirical gate, not an assumption.

## 4. Deterministic reference algorithm

Before any neural operator exists, Hepta implements a tabulated monotone reference on the fixed sensor core:

```text
load immutable sensor core S and action grid A_ref
validate applicability certificate and frozen jump/hard digest
for every sensor x_i:
  for every legal reference action a_j:
    simulate or integrate registered deterministic local model
    target[i,j] = bounded reward + monotone_interpolate(V_next, x_next)
  V_now[i] = max_j target[i,j]
emit direct targets, action gaps, residuals and coverage diagnostics
```

For stochastic fixtures, the reference uses a counter-based seed and a fixed number of antithetic paths per `(sensor,action)`. Sample order cannot alter results. Interpolation outside the sensor hull returns OOD rather than extrapolating.

Golden vector `HBO-GV-001` uses one state dimension, sensors `[0,0.5,1]`, actions `[-0.5,0.5]`, deterministic transition `x'=clip(x+0.2a,0,1)`, reward `-(x-0.75)^2-0.1a^2`, `V_next(x)=x`, and `dt=1`. The canonical real-valued target table, ordered by sensor then action, is `[[-0.5875,-0.4875],[0.3125,0.5125],[0.8125,0.9125]]`; the greedy action is `0.5` at every sensor and the action gaps are `[0.1,0.2,0.1]`. Signed Q32 targets are `[[-2523293286,-2093796557],[1342177280,2201170739],[3489660928,3919157658]]`, with Q32 gaps `[429496730,858993459,429496730]`. The neural direct head must match this reference within the declared approximation budget.

## 5. Trainable or estimated algorithm

The pilot operator is a tensor-product DeepONet-style model:

\[
\widehat T(V)(x,a)=c+\sum_{r=1}^{R}B_r(V(S))\,T_r^x(x)\,T_r^a(a).
\]

`B` consumes continuation values only at the immutable sensor core. `T^x` uses smooth activations and spectral/norm constraints appropriate to the registered Hölder profile. `T^a` is Lipschitz-constrained and supports categorical embeddings only for registered action categories. Rank begins at `8` and may grow to `64` only when held-out singular-value diagnostics justify it.

Training data is built from immutable episode and model snapshots; replay rows cannot replace the sensor core. The objective is

\[
L=L_{direct}+\lambda_{gap}L_{action-gap}+\lambda_{mono}L_{monotone}
+\lambda_{gain}L_{gain}+\lambda_{rank}L_{rank}+\lambda_{ood}L_{ood}.
\]

A direct target head is required for off-policy candidates. Residual mode predicts `T(V)-V` only on a measured near-greedy active set where the minimum action gap and support floor pass. Residual mode is disabled when its error amplification estimate exceeds the direct target estimate.

Optimization uses counter-based deterministic batching, future-time validation, gradient-norm cap `1.0`, immutable normalization and early stopping. The manifest records network dimensions, activations, rank, sensor digest, action metric, optimizer, precision, device, software tuple and training code digest.

## 6. Data, protocol and lineage schema

The following records are canonical cross-module protocols registered in `docs/contracts/CONTRACTS.json` and `docs/contracts/PROTOCOL_SCHEMAS.json`:

```text
OperatorApplicabilityCertificateV1 {
  certificate_id, axis_partition_digest, domain_digest,
  action_space_digest, holder_exponents, holder_constants,
  state_lipschitz, action_lipschitz, ellipticity_nu_lcb,
  horizon, control_interval_profile, jump_policy_digest,
  evaluator, expiry, decision
}

OperatorSensorCoreManifestV1 {
  sensor_core_id, state_axis_digest, points_digest, count,
  fill_distance_q32, separation_radius_q32, mesh_ratio_q32,
  hull_digest, construction_algorithm, seed_digest,
  predecessor, expiry
}

RegularityProfileV1 {
  artifact_digest, direct_or_residual, measured_rank,
  reconstruction_gain_q32, monotonicity_violations,
  positivity_violations, holder_residuals,
  action_lipschitz_residuals, ood_margin, decision
}

BellmanOperatorArtifactV1 {
  artifact_id, applicability_digest, sensor_core_digest,
  branch_digest, state_trunk_digest, action_trunk_digest,
  rank, normalization_digest, training_dataset_digest,
  training_code_digest, runtime_tuple_digest,
  error_budget, predecessor, rollback_digest
}
```

The sensor core is create-only. Runtime observations may inform a proposal for a future core but may not mutate the selected core. All target rows bind the policy, objective, jump/hard snapshot, candidate set, propensity/support, outcome source and dataset lineage. Correction and deletion propagate through targets, model checkpoints and derived artifacts.

## 7. Numerical stability, complexity and resource bounds

Sensor geometry is measured as

\[
h_S=\sup_{x\in X}\min_i\|x-x_i\|,\qquad
q_S=\frac12\min_{i\ne j}\|x_i-x_j\|,\qquad
\rho_S=h_S/q_S.
\]

The pilot sensor construction uses deterministic farthest-point insertion over a fixed candidate design. It stops at the smaller of the error target or `4096` points. Accepted cores require `rho_S <= 4`, no duplicate points, positive `q_S` and held-out OOD margin coverage.

The complete operator error budget is explicit:

\[
epsilon_{total}=\epsilon_{model}+\epsilon_{sensor}+\epsilon_{reconstruction}
+\epsilon_{network}+\epsilon_{optimization}+\epsilon_{statistical}
+\epsilon_{rollout}.
\]

No component may be silently omitted or double counted. Pilot limits are `epsilon_total <= 0.05` normalized utility, each unmeasured component fails closed, and no single component may consume more than `50%` of the budget without independent approval.

Runtime p95 is `<=5 ms` and p99 `<=12 ms` for one bounded candidate set of at most `64` actions on the qualified host. Resident operator bytes are `<=256 MiB`; sensor core bytes are `<=32 MiB`; one process generation performs one integrity-checked load. Training has explicit GPU/CPU-hour, memory, path-count and wall-clock ceilings.

## 8. Failure detection, fallback and rollback

Certificate failure, `nu_LCB<=0`, Hölder residual breach, mesh-ratio breach, nonpositive separation radius, rank saturation, reconstruction gain `>1.02`, monotonicity/positivity violation, OOD state, stale jump/hard snapshot, unsupported action, artifact revocation or error-budget breach disables the learned path.

Fallback order is selected direct operator → previous selected direct operator → deterministic sensor reference → deterministic heuristic/value bound → slow-path abstention. Residual mode never becomes a fallback for unsupported off-policy inputs. Rollback selects an exact predecessor containing its own certificate and sensor core; mixing a new branch with an old trunk is forbidden.

A timeout does not fabricate a value. The consumer receives `unavailable` plus the last valid bounded interval and routes according to risk. High-risk or irreversible actions always retain deterministic validation regardless of operator confidence.

## 9. Security, authority, privacy and unlearning

The operator sees approved numeric/typed features only. Raw prompts, credentials, private content, authority tokens and unrestricted external text are forbidden. Hard-state digests may condition cache identity but their semantics are never optimized. `learning.operator` cannot call tools/providers, install artifacts, select itself or label its own outcome.

Poisoning controls bind every row to independent outcome observation, candidate support and correction lineage. Sensor-core proposals are checked for clustering and adversarial holes. Unlearning revokes every target, checkpoint and operator artifact derived from deleted rows; cached operator outputs are invalidated by dataset and artifact generation.

## 10. Verification, golden vectors and property tests

Required tests include analytic diffusion fixtures, degenerate-diffusion rejection, known Hölder and non-Hölder coefficients, state/action anisotropy, jump segmentation, hard-axis immutability, fixed sensor reconstruction, fill/separation/mesh calculations, monotone interpolation, rank recovery, direct-versus-residual gating, OOD hull rejection, deterministic batching, error-budget conservation, artifact reload and rollback.

Property tests enforce legal-action closure, monotonicity under ordered continuation values, positivity where declared, bounded `L_infinity` gain, deterministic replay, no replay-to-sensor mutation and no extrapolation outside the certified domain. Fault tests cover corrupt sensor bytes, partial artifact load, process kill, stale generation and deleted-row resurrection.

## 11. Quantitative acceptance gates

| Gate | Required threshold |
|---|---|
| Applicability certificate | current independent `pass` |
| Uniform ellipticity | `nu_LCB > 0` |
| Sensor count | `16..4096` |
| Separation radius | `>0` |
| Mesh ratio | `<=4` |
| Reconstruction gain | `<=1.02` |
| Monotonicity violations | `0` on mandatory suite |
| Positivity violations | `0` where required |
| Measured rank | `<=64` and held-out justified |
| Total normalized error | `<=0.05` |
| Residual active-set support | `>=0.2` propensity floor or profile-specific stricter bound |
| OOD false acceptance | `<0.5%` |
| Future-time value error | candidate UCB no worse than baseline bound |
| Current-run artifact replacement | `0` |

The simplest sufficient learner wins: a tabular, linear or deterministic reference that meets the same bound is preferred over the neural operator.

## 12. Paper traceability and Hepta extensions

`PAPER-HOLDER-Q-2026` is used only for six publisher-abstract statements: continuous state/action stochastic control, the uniformly elliptic diffusion setting, Hölder-regular coefficients, state-smoothing/action-Lipschitz anisotropy, tensor-product neural-operator motivation and the stiffness/resource tradeoff. Each statement is bound in `PAPER_TRACEABILITY.json` to the immutable PMLR PDF bytes, the publisher Git commit/blob, publication page, abstract sentence and normalized sentence SHA-256. The paper does not establish convergence for a practical sampled DQN stack or any Hepta runtime claim.

Quasi-uniform sensor geometry, bounded monotone/positive reconstruction, the near-greedy residual gate, the smooth/jump/hard partition, event-boundary segmentation, causal episode ledger, fixed-point receipts, immutable sensor-core lifecycle, next-snapshot selection and unlearning are Hepta engineering extensions. They require their own proofs and measurements and may not be attributed to the paper.

## 13. Implementation sequence and completion rule

Implementation order is axis registry and applicability schema → deterministic sensor construction and geometry tests → deterministic Bellman reference → direct tensor-product model → monotone reconstruction and gain tests → OOD and error-budget accounting → action-gap head → near-greedy residual shadow → causal evaluation → immutable artifact and rollback → independent selection.

Documentation closure means this file, the algorithm registry, paper traceability and exact CI agree. Source completion and operator efficacy remain separate. This specification does not by itself advance `O0_NONE`.
