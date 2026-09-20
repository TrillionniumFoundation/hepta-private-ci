# NDU forward-backward implementation specification

**Plan:** `HEPTA-GLOBAL-MODULAR-DEVELOPMENT-PLAN` v8.0.0  
**Specification:** `ALG-NDU-FBSDE`  
**Bound modules:** `objective.compiler`, `utility.ndu`, `intelligence.control`  
**Documentation state:** `closed` for the enumerated specification requirements only  
**Implementation state:** not implied

## 1. Scope, ownership and non-claims

`utility.ndu` owns bounded preference and recursive-utility projections for system, domain, agent and episode subjects. `objective.compiler` supplies immutable goals, legal action classes and hard constraints. `intelligence.control` composes owner ports, not a replacement store, trainer or execution spine. An organ contributes supported consequences; emitting a score does not make an organ, database row or neuron an NDU subject.

This specification defines a deterministic implementation baseline and a separately qualified stochastic candidate. It does not establish dynamic-preference efficacy, production activation, biological equivalence, or autonomous software evolution. The four-level hierarchy, event sourcing and deployment controls are Hepta engineering extensions. `docs/evidence/CLAIMS.json` and current independent evidence govern capability claims.

Existing exported deterministic primitives in `codex-rs/hepta-ndu/src/lib.rs` include `evaluate_candidates`, `solve_preference_target`, `validate_staged_updates`, `evaluate_recursive_utility` and `mul_q32_ties_even`. Reuse compatible primitives and add owner-scoped adapters; a symbol inventory proves neither a real consumer nor an implemented stochastic solver.

## 2. Symbols, dimensions, units and normalization

| Symbol | Meaning | Pilot bound | Representation |
|---|---|---:|---|
| `s` | subject | system/domain/agent/episode | scoped identifier |
| `k` | event boundary | monotone `u64` | exact integer |
| `dt_k` | logical duration | 1 ms to 3600 s | integer microseconds |
| `P_k` | latent preference | dimension <=64, [-1,1] | signed Q32 |
| `O_k` | approved observations | dimension <=256 | normalized Q24 |
| `COST_k` | resource consumption | dimension <=32 | nonnegative Q32 |
| `R_k` | bounded risk state | dimension <=32, [0,1] | Q32 |
| `A_k` | legal action descriptor | dimension <=128 | typed bounded encoding |
| `M^P,M^U` | martingale drivers | each dimension <=32 | increment manifest |
| `U_k` | recursive utility | dimension <=8 | bounded Q32 |
| `Z_k` | utility noise sensitivity | utility x driver dimensions | bounded Q24 |
| `Sigma_k` | conditional increment covariance | driver x driver dimensions | declared numeric profile |
| `B_k` | utility/increment conditional cross moment | utility x driver dimensions | declared numeric profile |

Normalization, units, feature order, clipping locations, scales and conditional-moment conventions belong to immutable artifacts bound into `RunStartSnapshotV1`. `COST_k` is not the covariance matrix. Convert microseconds to the declared solver time unit with checked arithmetic; never silently treat microseconds as seconds. Reject invalid dimensions, non-finite numbers, unknown units and missing profiles. Pre-clipping violations and projection counts remain observable.

Signed Q32 and Q24 are distinct from the HNMF ppm/toward-zero reference. Conversion records bind both profiles, rounding, units, source/output digests and absolute error. Identifier, authority, deletion, fence and deadline fields are exact; they never pass through approximate numerical conversion.

## 3. Formal model and invariants

For a resource-constrained subject, the analysis model is

    dP_t = b_theta(t,P_t,O_t,COST_t,R_t,A_t) dt
           + sigma_theta(t,P_t,O_t,COST_t,R_t,A_t) dM_t^P
    dU_t = -f_phi(t,P_t,O_t,COST_t,R_t,A_t,U_t,Z_t) dt + Z_t dM_t^U
    U_T  = G(P_T,Y_T,J)

`J` is an immutable objective; `Y_T` is an independently observed terminal outcome. Forward and backward drivers are logically distinct; their joint convention is explicit. The selected driver/filtration must support the martingale representation required by the chosen solver. If it does not, the analysis needs an additional orthogonal martingale term or a different qualified model. The pilot rejects an unsupported representation rather than hiding unexplained noise in a fitted Z head.

The forward event discretization is

    P_(k+1) = project_P(P_k + b_theta(k,...) dt_k
                       + sigma_theta(k,...) DeltaM^P_(k+1)).

The backward conditional linear-regression convention is

    m_k     = DeltaM^U_(k+1)
    mu_k    = E[m_k | F_k]
    m_c     = m_k - mu_k
    u_c     = U_(k+1) - E[U_(k+1) | F_k]
    Sigma_k = E[m_c m_c^T | F_k]
    B_k     = E[u_c m_c^T | F_k]
    Z_k Sigma_k = B_k.

Use a stable linear solve, not explicit matrix inversion. For positive-definite Sigma, this determines Z on the supported coordinates. Only when `Sigma_k = dt_k I` does the result reduce to `B_k / dt_k`. If the manifest stores covariance rate `Q_k = Sigma_k / dt_k`, solve `Z_k Q_k = B_k / dt_k`. A general covariance rate cannot be omitted. Center both quantities unless the conditional-zero-mean martingale convention is established and checked. This corrects the formerly implicit standard-driver assumption; old artifact bytes are not reinterpreted.

For whitening `m = L xi`, with `E[xi xi^T | F_k] = dt I`, the manifest declares whether the head predicts `Z_m` or `Z_xi`; `Z_xi = Z_m L`. Coordinate conversion and residual checks precede publication. Singular covariance is unsupported in the pilot. A pseudoinverse requires a separately reviewed supported-subspace profile, null-space identifiability and residual tests.

The backward Euler candidate is

    U_k = project_U E[U_(k+1)
                      + f_phi(k,P_k,...,U_(k+1),Z_k) dt_k | F_k].

Conditional expectations use only pre-boundary features. Event duration, stopping, censoring and history conditioning are manifest fields. Future outcomes may label training rows but cannot enter runtime features. A stochastic approximation is not identical to the deterministic discounted baseline for an arbitrary generator.

Hard constraints are filtered before Pareto/scalarization. Preferences may change bounded allocation, exploration, evidence effort and abstention, never success criteria, observer identity, privacy, consent or authority. Parent/child exchange only bounded budget, shadow price, continuation utility, uncertainty, residual and expiry via `NduBoundaryConditionV1`. Freeze the parent revision; accept a candidate state with damping `P_next=(1-eta)P_old+eta*P_candidate`, eta in [1/16,1/4]. Do not select parent and child parameter artifacts in the same generation.

## 4. Deterministic reference algorithm

Set diffusion and both increments to zero. Use the registered discrete utility profile, canonical event ordering and signed fixed-point arithmetic:

    validate objective, subject, legal set, units, predecessor and coefficients
    P[0] = predecessor preference
    for event k in canonical order:
        P[k+1] = registered_projection(P[k] + dt[k]*bounded_drift(P[k],event[k]))
    U[n] = bounded_terminal_utility(P[n], independent_outcome, objective)
    for k from n-1 down to 0:
        U[k] = registered_projection(instant[k] + discount[k]*U[k+1])
    publish immutable candidate rows, counters, source lineage and residuals

Feasibility precedes scoring. Missing support/units is unavailable, not zero cost. Without a registered complete scalarization profile, return a Pareto frontier and slow-path/abstain disposition. All candidates include the permitted no-op/abstain alternative.

`NDU-GV-001`: P0=0; two unit steps; drifts 0.25,-0.5; instantaneous utilities 0.5,0.25; discount 0.8; terminal utility 1. Expected real values are P=[0,0.25,-0.25], U=[1.34,1.05,1]. Q32 nearest/ties-to-even goldens are P=[0,1073741824,-1073741824], U=[5755256177,4509715661,4294967296]. Canonical reference goldens are exact; the separate adaptive zero-noise comparison uses the declared tolerance.

The deterministic fixed-point solve has at most 64 iterations and residual <=2^-20; exhaustion reports unavailable. Damping, clipping or a bounded iteration count alone does not prove convergence.

## 5. Trainable or estimated algorithm

Separate `PreferenceFilter`, bounded `PreferenceDriftNet`, factorized `PreferenceDiffusionNet`, monotone/bounded `UtilityGeneratorNet` and `ConditionalZHead`. Coefficient artifacts identify the operating domain, model architecture, conditional features, moment window, increment units, dt floor, eigenvalue floor, condition-number ceiling and optional whitening transform. The full-rank pilot requires a positive covariance eigenvalue floor and condition estimate <=10^6. Failure disables the stochastic candidate.

Train on immutable `DatasetSnapshotV1`, grouped by episode, principal scope, objective class and real observation time. Fit normalizers and conditional-moment models on training folds only. Keep all correlated trajectory rows together. Evaluate out of time and on an independent fixed external objective, not only the adapting internal utility. Report latent-state identifiability and parameter sensitivity; equivalent hidden-state parameterizations are not identified by an internal utility gain.

The candidate loss is a recorded weighted sum of filter, BSDE, Z regression, conservation, stability and calibration losses. Pilot optimizer defaults remain AdamW, learning rate 3e-4, weight decay 1e-4, gradient norm cap 1.0, at most 200 epochs, early stopping after 12 validation evaluations. Record exact precision, software/device tuple, batch construction, counter-based random stream and search budget. Defaults are specifications, not measured training results.

Start with deterministic/scalar or tabular baselines. Add stochastic or neural complexity only after equal-resource ablations show supported improvement. Prediction, utility, policy, calibration and observer models have separate artifacts and may not self-label their own outcomes.

## 6. Data, protocol and lineage schema

Canonical production protocols remain owned by `docs/contracts/CONTRACTS.json` and `docs/contracts/PROTOCOL_SCHEMAS.json`. This correction adds no unregistered field to an existing wire version.

`NduCoefficientManifestV1` binds artifact, subject/objective class, dimensions, fixed-point scales, bounds, normalization, runtime, predecessor, expiry and rollback. The integration package must register a versioned coefficient-profile reference for the covariance/conditioning convention before admitting a stochastic implementation that needs it. An incompatible existing consumer returns unavailable; it cannot silently assume identity covariance.

`NduWellPosednessCertificateV1` binds operating domain, coefficient boundedness and Lipschitz assumptions, square integrability, conditional means, generator monotonicity/dissipativity, Z growth, terminal conditions, continuity scope, solver stability and independent decision. An empirical local spectral-radius estimate is a diagnostic, not a universal well-posedness or global stability proof.

`NduUpdateReceiptV1` binds subject, old/new revision, event, objective, coefficient, duration, before/after/utility digests, uncertainty, projection count, boundary and conservation residuals and disposition. The full idempotency identity is subject + objective + predecessor + event + coefficient within principal scope. A shorter local key is valid only inside an object whose immutable scope already binds the omitted fields; cross-run collision tests are mandatory.

Preference/utility rows append by revision. A selected projection pointer changes atomically only after immutable data and required evidence exist. Corrections append revoked ancestry and rebuilt successors. Lineage is source -> approved feature generation -> dataset -> training code -> coefficient -> evaluation -> selected snapshot -> runtime observation. No raw secret, unrestricted prompt or consumable authority token is stored in this chain.

## 7. Numerical stability, complexity and resource bounds

Dense runtime is bounded by O(d_p^2+d_p*d_o); covariance factorization is O(d_m^3) in a bounded slow solver, not a mandatory central operation per token. Cache compatible factors only by exact covariance/profile generation. Report conditioning, linear-solve residual, conversion error, dt floor, projection rate and missing support. Do not treat residual alone as a proof of statistical or model error.

Reference-host targets remain p95 <=2 ms, p99 <=5 ms, transient allocation <=256 KiB, persistent projection <=256 KiB per active subject, hierarchy depth <=4, zero central synchronous RPC and at most one selected-artifact lookup per process generation. These are targets until a named-host receipt exists. Hot paths cannot allocate proportional to episode history. Revocation checks remain current even when artifacts are cached.

Training bounds remain 512 event boundaries per episode and gradient checkpointing above 128, with explicit batch byte/count limits. Sequential evaluation has its own registered horizon; truncation cannot silently change the estimand. An over-horizon trajectory receives a separately declared estimand/profile or insufficient evidence.

## 8. Failure detection, fallback and rollback

Reject unknown subject, stale objective, missing legal set, wrong units/dimensions, expired/revoked artifacts, convention mismatch, bad covariance, unsupported representation, conservation failure or simultaneous parent/child selection. Optional input masks increase uncertainty; they do not manufacture support.

Fallback is a compatible selected adaptive artifact, then compatible selected deterministic artifact, then valid deterministic objective-class snapshot, then immutable objective baseline, then abstain/slow path. Every predecessor is checked against current revocations. A revoked or incompatible predecessor is quarantined, not loaded because it once worked.

Crash before publication leaves the predecessor. Crash after durable commit but before acknowledgement is reconciled by original identity/digest. Recover current revocation and tombstone frontiers before exposing projections. Rollback is a new fenced transition; it cannot reset epochs, resurrect deleted lineage or reuse old grants.

## 9. Security, authority, privacy and unlearning

NDU neither dispatches models/tools nor grants network, filesystem, secret, Matrix, fleet, selection, merge, promotion or release authority. The reader cannot select the artifact it consumes. Subject IDs are purpose/scoped pseudonyms. Preferences are uncertain internal estimates, not psychological diagnoses or authority statements about people.

Negative tests cover instruction/credential injection into features, outcome-observer substitution, cross-principal caches and reward redefinition. Evaluate task success against a fixed independent external measure as well as internal utility. Unlearning traverses feature caches, projections, datasets, optimizer checkpoints, artifacts, evaluations and backup/restore. If selective removal is unsupported, revoke and retrain; a logical tombstone alone does not prove parameter unlearning.

## 10. Verification, golden vectors and property tests

Keep `NDU-GV-001`, projection, monotonicity, terminal-revision mismatch, parent-child conservation, staged-versus-simultaneous coupling, crash/reopen, idempotency, correction, zero-noise parity and fixed-point edge tests.

Add exact backward-regression cases: scalar Sigma=2dt with U_next=3m recovers Z=3 rather than 6; Sigma=[[2,1],[1,2]], B=[5,1] recovers [3,-1]; identity covariance reduces to B/dt; singular/indefinite covariance rejects; nonzero sample means require centering both terms; whitened-coordinate conversion preserves the predicted increment. A reference numeric pass proves the tested algebra, not conditional identification, a complete FBSDE solution or efficacy.

Property tests require boundedness, deterministic replay, unit/profile compatibility, monotonically advancing revision, conservation, registered projection non-expansion, no hard-axis mutation and safe rollback. Faults include storage-full, corrupt manifests, expired boundaries, revocation, acknowledgement loss, process kill, covariance collapse, unsupported dimensions and wall-clock exhaustion.

## 11. Quantitative acceptance gates

| Gate | Required threshold |
|---|---|
| Adaptive zero-noise parity | every component within 2 Q32 units |
| Undeclared bound violation | 0 |
| Projection rate after warm-up | <0.4% |
| Resource residual | <=1 Q32 unit |
| Risk residual | <=10 ppm |
| Boundary residual p99 | <=10,000 ppm |
| Coupling spectral radius upper 95% bound | <0.95, with declared region/delay assumptions |
| Standardized martingale conditional mean | absolute value <0.02 |
| 90% interval coverage | [0.87,0.93] |
| Future utility | candidate LCB > baseline UCB |
| Old-task subgroup degradation | no worse than 2% |
| Deterministic fallback coverage | 100% supported objective classes |
| Current-run parameter replacement | 0 |
| Learned hard-axis mutation | 0 |

Apply all relevant thresholds by intersection: maximum lower bound and minimum upper bound after checking units and estimand compatibility. ESS or a local diagnostic cannot waive the canonical future-window, support, retention or safety gates. Candidate selection and repeated monitoring require preregistered multiplicity/alpha allocation. No threshold is lowered after seeing a result.

## 12. Paper traceability and Hepta extensions

`PAPER-NDU-FOUNDATIONS-2024` supplies resource-constrained endogenous-preference motivation. `PAPER-NDU-UPA-2025` supplies the continuous-time FBSDE/residual-network framing. `PAPER-NDU-EU-2025` supplies the multidimensional square-integrable martingale and explicit well-posedness/control-condition boundary. Use the exact source scopes and locators in `PAPER_TRACEABILITY.json`; abstract-level locks are not full theorem verification.

The four-level hierarchy, fixed-point event discretization, covariance estimation, numerical profile, source ownership, causal evaluation, deletion lineage and next-snapshot governance require Hepta-specific implementation and review. No cited paper is substituted for telemetry identifiability, hierarchy stability, policy efficacy, biological mechanism or safe code evolution.

## 13. Implementation sequence and completion rule

Implement shared protocols/numerics, deterministic goldens, owner projections, coherent consumers, conditional moments, stochastic shadow solver and certificate, backward-regression parity, frozen-parent hierarchy, immutable training, independent future/retention evaluation, next-snapshot loading and rollback. Freeze covariance/profile admission before stochastic consumer coding; unchanged deterministic APIs remain usable.

Documentation completion means this file, its exact blob identity in `ALGORITHM_SPECS.json`, paper scopes and required CI agree. Source completion additionally requires native code, stores, callers and tests. Dynamic efficacy additionally requires supported real future outcomes and distinct independent decisions. This document does not advance `D0_SPECIFIED_ONLY`, authorize a production writer or set all capability gaps closed.
