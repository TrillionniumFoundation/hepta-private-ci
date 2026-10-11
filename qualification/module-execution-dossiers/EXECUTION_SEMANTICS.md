# Detailed execution semantics for the V8 module dossiers

Parent authority: `docs/DEVELOPMENT.md` (`HEPTA-GLOBAL-MODULAR-DEVELOPMENT-PLAN`, 8.0.0).
Companion scope: implementation design, analytic examples and qualification fixtures. This is not a new global plan or a production protocol admission. Existing module ownership, mandatory package predecessors, activation gates and evidence claims remain authoritative.

## 1. Design, implementation and capability are different gates

A design record states what must be built. A source record identifies committed code. A deployment record identifies the caller, executable, host and physical state actually used. An experiment records independently observed outcomes. These four record classes must not share a `complete` boolean.

Coding entry requires a reviewed work-package envelope, exact source/tree, frozen public contracts, exclusive write paths, an implementation algorithm, state/error model, fixtures and a rollback design. It does not require observations from a future calendar window. Integration entry additionally requires compiled native ports, actual stores and callers, crash/reopen tests, revocation, target-profile measurements and independently checked composition. Capability and release entry additionally require the applicable `RDY-EXT-001` through `RDY-EXT-009` receipts. Documentation cannot issue any of them.

The module details below specify proposed implementation operations. They are not declarations that an identically named Rust function exists. Existing exported APIs are preserved; each implementation package supplies an explicit design-operation-to-native-symbol mapping, including the product caller and commit. A test-only caller cannot satisfy the product-caller field. A path or symbol inventory cannot prove execution.

## 2. Objective grammar and conflict algorithm

The first deterministic compiler accepts conjunctions of the following atoms only: a bounded interval on a registered scalar; membership/exclusion on a finite registered enum; required/forbidden action class; equality on immutable scope or generation; and a dependency implication between two registered action-class booleans. Predicate execution is limited to registered observation adapters. Free-form code, unrestricted quantifiers, arbitrary nonlinear arithmetic, arbitrary regex and unbounded recursion are rejected before solving.

Each atom contains `id`, `precedence`, `axis`, `operator`, `value`, `unit`, `evidenceSource`, `terminality` and `originDigest`. Precedence is the existing constitutional/principal/environment/task/soft ordering. Soft atoms never participate in hard feasibility. Compile output distinguishes `feasible`, `infeasible`, `unsupported_language` and `budget_exhausted`; the last two must not be relabelled infeasible.

For scalar/enum atoms, feasibility groups by axis and intersects intervals or finite sets. Action implications are positive Horn edges a -> b: propagate the required-true set along the bounded graph (SCC condensation is optional), reject if the closure intersects the forbidden set, and set unforced booleans false. Cycles terminate through visited-node tracking. Graph closure costs O(V+E); arbitrary negated/disjunctive implications are outside this pilot. A satisfiable boolean assignment is not effect authority. Pure normalization and sorting cost O(n log n); the full conflict extraction does not inherit that bound. Given a feasibility oracle with cost C(n), deterministic deletion filtering costs at most n+1 oracle calls and O(n C(n)) work. It returns an inclusion-minimal unsatisfied subset, not a minimum-cardinality subset. The implementation must use that term in receipts.

Pilot input bounds remain 256 constraints, 128 predicates and 128 legal action classes. The profile also caps oracle calls at 257 and records elapsed budget, oracle count and unresolved constraints. An expired wall-clock budget emits `budget_exhausted` and preserves the original objective. No partial conflict set permits dropping a hard constraint. Advanced SAT/SMT, disjunction or nonlinear predicates require a separate versioned profile and independent review.

Acceptance cases: intersect [0,1] with [2,3] -> infeasible; intersect [0,2] with [1,3] -> [1,2]; an irrelevant third atom is removed from the conflict core; unsupported operators reject; constraint order permutations produce identical canonical core ordering; resource exhaustion never grants an action.

## 3. NDU conditional covariance and backward regression

The deterministic zero-noise path remains unchanged. For a stochastic candidate, the increment convention must be explicit. Let m = Delta M and centered increment m_c = m - E[m | F_k]. Define C_k = E[m_c m_c^T | F_k] and B_k = E[(U_next - E[U_next | F_k]) m_c^T | F_k]. A verified zero-mean martingale convention reduces C_k to the uncentered second moment; empirical nonzero means must not be hidden by centering only U. Under the declared local linear martingale regression, solve

    Z_k C_k = B_k.

For nonsingular C_k, Z_k = B_k C_k^{-1}. When C_k = dt I, this reduces to B_k / dt. If a manifest stores the covariance rate Q_k = C_k / dt, the formula is (B_k / dt) Q_k^{-1}. Dividing by dt alone is not correct for a general covariance rate. Mean centering is mandatory unless the conditional zero-mean convention is already established and checked.

Implement a linear solve, not explicit numerical matrix inversion. The covariance manifest binds increment units, conditioning features, estimator/sampling window, whitening transform, eigenvalue floor, condition-number ceiling, dt floor and supported subspace. The pilot full-rank path requires a positive eigenvalue lower bound and condition estimate <= 10^6; a failing bound disables the stochastic candidate. A singular covariance is rejected in the pilot. A pseudoinverse is allowed only under a separately qualified supported-subspace profile with residual and null-space identifiability tests; it cannot silently impute unsupported directions.

Whitened increments use m = L xi with E[xi xi^T | F_k] = dt I and C_k = dt L L^T. Store whether a learned head produces coefficients in m or xi coordinates, and convert before publishing. The coefficient artifact binds this convention; loading mismatched conventions is a compatibility failure.

Analytic fixtures: scalar C=2dt and U_next=3m must recover Z=3, not 6; correlated C=[[2,1],[1,2]] and Z=[3,-1] produce B=[5,1] and recover [3,-1]; singular covariance rejects; identity covariance reproduces the old simplified formula. These tests validate the regression convention, not the entire FBSDE solution, causal identification or NDU efficacy.

A local empirical spectral-radius estimate is a diagnostic, not a global stability proof. Activation additionally binds a declared operating region, coefficient regularity bounds, gain/delay uncertainty, parent-freezing schedule, perturbation suite and deterministic exit. Preference adaptation cannot modify objective success, consent or evaluation thresholds. Judge outcomes on a fixed external objective as well as the adaptive utility.

## 4. Single-decision and sequential causal estimands

Every evaluation plan declares `estimandClass`: `single_decision`, `finite_horizon_history_policy`, or `unsupported`. Retrieval ranking at a fixed decision boundary may use the existing single-decision IPS/SNIPS/DR formulas when its consistency, support and assignment assumptions hold. Long-horizon policies may not reuse that estimate as an episode-value certificate.

For a finite horizon H, record the pre-action history H_t, complete legal set, behavior and evaluation probabilities, action, reward, discount, terminal/censoring status and policy/observer generations for every step. Assume consistency, sequential conditional exchangeability for the logged history and positivity on evaluation-policy support. Unobserved confounding or unsupported actions yields insufficient evidence, not model-repaired support.

A qualification reference uses the backward sequential DR recursion:

    D_H = terminal_value (zero when the terminal reward is already included)
    D_t = V_hat(H_t) + rho_t * (r_t + gamma_t * D_(t+1) - Q_hat(H_t,a_t))
    rho_t = pi_e(a_t | H_t) / pi_b(a_t | H_t)
    V_hat(H_t) = sum_a pi_e(a | H_t) Q_hat(H_t,a).

The horizon and terminal-value convention are manifest fields to prevent double-counting. Q/V models are trained on disjoint episode/principal/time folds; all rows of a dependent trajectory remain in one fold. Confidence intervals resample independent trajectory clusters, not correlated individual decisions. If clusters are dependent across episodes, the cluster identifier expands accordingly.

The baseline also reports per-decision importance sampling and cumulative ratios, ESS by time/depth, maximum cumulative weight, omitted/censored trajectories and support coverage by subgroup. Pilot H <= 128; excessive cumulative ratios, low deep-horizon ESS or incomplete history return insufficient evidence. Clipping, censoring correction and sequential stopping rules are preregistered and report their changed estimand/bias. No estimator label alone proves identification or safe policy improvement.

A two-step analytic DR fixture uses (V,Q,r,rho,gamma) = (1/4,1/4,1/5,1/2,9/10) and (1/2,1/2,1,2,1); with D_2=0, D_1=3/2 and D_0=9/10. A zero behavior propensity rejects before division. These are numeric fixtures, not future-calendar observations.

Reference: Jiang and Li, *Doubly Robust Off-policy Value Evaluation for Reinforcement Learning*, PMLR 48 (2016), https://proceedings.mlr.press/v48/jiang16.html. The estimator adaptation and its assumptions require implementation-specific independent review; this citation grants no Hepta capability.

## 5. Numeric profile compatibility

The companion labels the existing HNMF reference arithmetic `hnmf-ppm-toward-zero-v1` for qualification purposes; this label is not a previously registered production profile. Preserve that reference arithmetic. Keep Q24 and Q32 nearest/ties-to-even profiles explicit. A serialized value binds `profileId`, `scale`, `unit`, `shape`, `range`, `rounding`, `overflowPolicy` and `normalizationDigest`. Different profiles are not byte-compatible aliases.

For integer value x at scale S and target scale T, compute x*T in checked wide arithmetic; then apply the target rounding to (x*T)/S. Toward-zero uses the sign and integer magnitude quotient. Nearest/ties-to-even rounds the magnitude up exactly when twice the remainder exceeds S, or equals S and the quotient is odd. Restore the sign after rounding. Reject overflow and illegal units. Clipping is permitted only at named mathematical projections and increments a counter.

Cross-profile equality is numeric within the declared conversion error, never equality of source bytes or digests. A conversion receipt binds original value digest, source/target profiles, converted value digest and absolute error bound. Round-trip error is the sum of the two conversion bounds. Never quantize authority, identifier, writer-fence, deadline or deletion state as an approximate numeric signal.

Fixtures include positive and negative half ties, zero, odd/even target bins, ppm -> Q24 -> ppm, maximum integer overflow, unknown profile and incompatible unit. In particular +2.5 -> 2, +3.5 -> 4, -2.5 -> -2 and -3.5 -> -4 under ties-to-even.

## 6. Qualification threshold composition

Thresholds combine by intersection of requirements, not by whichever module supplied the last profile. For lower bounds use the maximum; for upper bounds use the minimum. Missing metrics and incompatible units block evaluation. Fixed prohibitions (authority mutation, self-acceptance, deletion resurrection) remain zero-tolerance regardless of utility.

An HNMF-local profile containing ESS=200 cannot lower a system or longitudinal requirement. A joint longitudinal/system causal claim also requires the canonical ESS >= 400 and >= 10% of eligible rows, plus every applicable trajectory-depth/subgroup floor. The effective minimum is therefore max(200,400,ceil(0.1*n),registered_stricter_minimum). Passing ESS is necessary, not sufficient; it does not create independent samples or guarantee power. The experiment owner preregisters effect size, power or precision target, cluster count and calendar windows.

Candidate LCB > baseline UCB remains the existing conservative efficacy gate. Report a prespecified paired-difference interval as additional analysis, not as an unreviewed substitute for the canonical gate. The final future holdout is not reused for adaptive candidate tuning. Sequential monitoring, multiple candidates and repeated versions require a declared alpha budget or a fresh confirmatory holdout.

## 7. State handoff and organ replacement

`StateHandoffReceiptV1` is defined by the companion JSON Schema in this directory. This schema is an implementation/qualification contract; admission into production wire registries and native producer/consumer compilation remain explicit integration tasks, never inferred from schema presence. The schema owns only the handoff evidence format, not the domain facts being migrated.

The pilot is a cardinality-preserving replacement within one registered module owner; sourceModule must equal targetModule. A canonical owner transfer requires a reviewed data-authority registry change. Split/merge, cardinality-changing transforms and multi-shard cutovers require a separately qualified composite migration profile, not reuse of this pilot receipt. The source owner prepares the handoff; the destination owner reports validation; a distinct witness verifies phases; the supervisor consumes a separately selected body generation. Only the existing authority owner can grant writer leases. The handoff record cannot mint a lease or acceptance.

Phases are prepared -> admission_stopped -> drained -> old_writer_fenced -> snapshotted -> migrated -> validated -> new_writer_fenced -> route_published -> retired. Before old-writer fencing only the old lease is valid. During migration neither writer lease is valid. At new_writer_fenced only the new lease is valid, but product admission remains closed until route_published. Lease validity and business-write admission are separate fields: old admission closes at admission_stopped; new admission opens only with route publication. At no phase may both writers be valid or admit writes. Persist each phase before externally acknowledging it. A stale phase/operation ID with a different semantic digest conflicts. Each phase record hashes the prior canonical receipt; identical record retries are observations only and execute no effect. New revocations still take effect immediately; if the bound frontier changes, stop the cutover and issue a newly reviewed handoff under the current frontier.

The receipt binds data domain, operation ID, source/destination organ and body generation, old/new writer fence, authority epoch, phase, source range/digest, outbox watermark, unresolved-operation inventory digest, migration plan/schema digests, target digest, tombstone/revocation frontier, consumer compatibility, route digest, rollback predecessor, witnesses and evidence digests. The schema requires source/target host and manifest digests, old/new body generations, authority epoch, rollback-predecessor digest and witness-evidence references. A canonical ordered export range (firstSequence, lastExclusiveSequence, recordCount, rangeManifestDigest) is required after snapshotted; targetRecordCount must match for this pilot after migrated; outboxWatermark is required after drained. Previously published progress fields and evidence digests cannot change in later phase records. Count/byte/time/resource limits are profile-bound. The new fence must be greater than the old fence; changing a string label does not establish fencing.

Interrupt and reopen at every phase. Recovery resumes from the durable phase and queries the current authority owner. It never guesses ownership from which process starts first. Unknown external effects block mutation cutover until the designated reconciler resolves or quarantines them. A non-authoritative migration target must not be writable through the product route. Failures after new-fence establishment fence that writer before any predecessor reactivation.

Rollback is a new authorized transition with a fresh fence and current revocation frontier, not replay of an old grant. A predecessor that is incompatible or revoked is unusable: quarantine and human recovery replace blind rollback. Retire only after drains, reader migration, projection invalidation and historical-record interpretability are proved.

## 8. Organ graphs, real-time loops and world models

Separate four graphs: initialization/ownership DAG; runtime dataflow graph; fallback graph; and deployment/failure-domain graph. Runtime feedback may be cyclic when its sample period, delay, gain, saturation and stability evidence are explicit. Do not reject all feedback because an initialization DAG is acyclic. Do not let a cyclic fallback or a synchronous central dependency enter an essential local control loop.

For each physical target, define coordinate frames, units, monotonic clock mapping, sensor rate/age, calibration uncertainty, body generation, actuator saturation and emergency envelope before controller integration. Start with a specified simulated low-degree-of-freedom plant and a deterministic bounded controller; pick and freeze one controller per plant profile. A generic `motor.control` role is not a controller implementation. Real hardware timing, emergency circuitry and limits are externally measured gates.

A world model estimates transition/outcome distributions and uncertainty; a value model evaluates supported consequences. A knowledge graph and Bellman value output do not by themselves implement state estimation or dynamics identification. World-model validation includes held-out one-step and multistep prediction, calibration, unknown event detection, action-conditioned interventions and sim-to-real residuals. Synthetic trajectories remain marked synthetic and cannot certify real effects.

## 9. Developmental learning and bounded structural search

Within `control.engineering` and `learning.plasticity`, maintain a capability-gap queue derived from independently observed failures, uncertainty and coverage debt. Task selection ranks expected information or utility improvement minus compute, interference and rollback cost under immutable scope/resource constraints. No task may be made easier after seeing the candidate result. Human priorities and essential operation budgets dominate exploration.

The first search is a bounded deterministic neighborhood: no-change, one parameter-group delta, one prompt revision, one workflow edit, or one typed organ operation. Generate at most 32 candidates and change at most one structural operation per pilot candidate. Compare simplicity, resource cost, retained-task behavior and rollback as well as utility. Increase search complexity only under a reviewed profile. Stop on repeated duplicates, exhausted budget, base drift, hidden-test exposure, absent support or rollback failure.

An `add` must name the unmet capability and compare to a no-organ baseline; `split` partitions every fact and writer; `merge` preserves evaluator/authority separation; `rewire` validates ports and feedback/fallback stability; `retire` drains and preserves history. Runtime routing among prequalified compatible organs is distinct from changing code, weights, schema or writer assignments. The latter always creates a next-generation candidate.

## 10. Authorized external-system adaptation

The first Debian target is one explicitly enrolled unprivileged user service inside an isolated VM or rootfs. Discover only enrolled paths, units and endpoints; bind package/source/configuration identity. Use typed argument arrays and explicit environment variables, never interpolate untrusted shell text. APT key/source changes, root installs, kernel changes and peer enrollment are excluded from this first slice.

Define the service contract as query_state, start, stop and propose_config; each effect has separate authorization, idempotency, timeout and trusted terminal observation. Package install/remove/configure are distinct later operations because maintainer scripts and partial configuration are not atomically reversible. A package rollback is not a business-data rollback.

A portable evolution package contains adapter/code/artifact hashes, compatible system manifest, tests, evaluation, migration, rollback and expiry. It contains no credentials, grant, host enrollment or inherited acceptance. Each destination independently authorizes and qualifies the package. Network reachability or open-source licensing is not host-owner consent. Unauthorized propagation, privilege expansion and secret copying are mandatory rejection cases.

## 11. C1 integration acceptance and parallel work

Use the seven canonical lanes. Shared type and protocol files require one designated contract integrator and an explicit co-owner envelope; no two teams publish competing meanings under the same version. Public schema changes invalidate affected consumers and require exact-source plus synthetic-merge tests.

C1 acceptance crosses real process and storage boundaries: request -> immutable objective -> coherent retrieval candidates -> recorded assignment -> independent outcome -> ledger fsync and reopen -> eligible dataset -> bounded training -> frozen disjoint evaluation -> immutable artifact -> independently selected next snapshot -> a new process demonstrates changed behavior -> rollback under current revocations. Record a product caller rather than a library-only fixture.

The C1 harness injects failures before and after each durable publication, supplies delayed/corrected outcomes, corrupts artifact bytes, revokes training lineage, races stale writers and kills/restarts the loading process. These engineering tests may qualify composition, not future efficacy. Calendar-window, real-model, physical and independent acceptance gates remain separate.

## 12. Scope-limited closure

The companion enumerates module-specific design requirements and the audit topics above. A machine pass verifies declared coverage, referenced paths, content identities, analytic fixtures and schema/state-machine consistency; it is not semantic completeness, proof of a full implementation, or an independent review. Unknown newly discovered gaps are appended rather than suppressed. `all_gaps_closed` remains false while any implementation, integration, external or independent-decision gate is unresolved.
