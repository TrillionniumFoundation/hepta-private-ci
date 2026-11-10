# HCSN independent review — 2026-11-10, update 2

## Outcome

One completed GRU development fit has now been independently reproduced exactly: all saved logits, reported metrics, episode labels and shared-weight invariants agree. That fit still reports **training adequacy false**. The full scientific admission remains **HOLD**.

The source review identifies resolved defects, two fixes that are only in the next canonical version, and outstanding numerical/scientific gates. The running development campaign uses its original immutable source. The accompanying JSON binds the reviewed files, historical receipts and the separately executed reproduction. It does not assert full repository CI.

## Independently executed reproduction

| Check | Result |
| --- | --- |
| Candidate | GRU, seed 101, learning rate 0.001, frozen run-source-v1 |
| D episodes / events | 128 / 31,952; episode hashes and labels verified |
| Fresh best.pt logits vs stored logits | Maximum absolute difference 0 |
| Independent NumPy metrics vs report | Maximum absolute difference 0 |
| Initial / best / last frontend and head | Every shared tensor exactly unchanged |
| Actual core updates | All four GRU parameter tensors changed |
| Update ledger | 360 main + 256 diagnostic updates; 30 complete epochs |
| Selected checkpoint | Epoch 16 |
| D accuracy / macro-F1 | 0.5117050575863795 / 0.15827456447784624 |
| Original training adequacy | False; not upgraded by successful reproduction |

The remote start RPC timed out, but the durable process had completed. A read-only lookup recovered its result; no duplicate run was launched. Raw independent logits and the script remain in the reviewer’s separate native directory. The complete 39,094-byte receipt has an exact local copy with SHA256 `78bfd675f333eb32e5530446e8c05429ccf244cf49941993a8cb570974806a92`.

## Findings

| ID | Severity | Status | Finding |
| --- | --- | --- | --- |
| P0-01 | high | resolved_in_source | E is financial equity; finite/regenerative neural values are separate |
| P0-02 | high | resolved_in_contract | A repeated query is different from an observation update |
| P1-01 | high | resolved_in_source | Posterior gradient coverage must include the entire retained batch |
| P1-02 | medium | resolved_in_source | Trace budgets and source changes now fail closed |
| P1-03 | high | no_formula_defect_found | Log F/G preserves rare probabilities and nonpositive-time semantics |
| P1-04 | high | open_numerical_gate | Repeated short-time QPR projection has a structural small-step error |
| P1-05 | medium | mathematical_expressions_consistent | Finite continuation reference handles regenerated counts and remaining age |
| P2-01 | high | resolved_in_source | Event-time LIF needs stable periods and a declared count domain |
| P2-02 | high | resolved_in_source | Changed source removes adequacy credit; recovery remains unsupported |
| P2-03 | high | resolved_for_uci | Tail padding no longer repeats HCSN observations |
| P2-04 | medium | fixed_in_canonical_but_retained_in_running_v1 | Plateau threshold and strict best-checkpoint selection differ |
| P2-05 | medium | fixed_in_canonical_but_retained_in_running_v1 | Malformed fit evidence could abort the controller summary |
| P2-06 | medium | cost_scope_disclosed | Campaign costs include spawn/import and failed children, with explicit omissions |
| P2-07 | high | interface_fixed_empirical_gate_open | Shared frontend/head isolation and training sufficiency have limited meanings |
| P2-08 | medium | disclosed_semantic_difference | Temporal cores use different physical timing conventions |
| P3-01 | high | finite_fixture_only | The QVI oracle is not financial E or a trained task boundary |
| P3-02 | high | value_derivative_verified_scope | Cost derivative applies to finite values under a fixed optimal active set |
| P4-01 | medium | protocol_explicit | Synthetic memory controls require a new training experiment |
| P2-09 | high | independently_reproduced_but_adequacy_false | One completed GRU development fit reproduces exactly without gaining training-adequacy credit |

### P0-01: E is financial equity; finite/regenerative neural values are separate

The old HX implementation provides hx_equity_closed and independent hx_equity. C is a killed single-cycle reward, F/G are first-hit quantities, U includes regeneration, M counts all events and J=dM/dt. The new differentiable network does not consume financial E.

**Required interpretation/action:** Do not rename arbitrary neural readouts or the finite QVI fixture as financial equity, and do not claim the old financial free boundary solves a sensor-task objective.

**Evidence:** independent source inspection and mathematical reasoning

**Sources:** `qualification/hcsn_differentiable/MODEL.md`, `qualification/hcsn_differentiable/semantics.py`.

### P0-02: A repeated query is different from an observation update

Operator readout queries do not advance state. The interval_value/call feature pays a queried endpoint terminal feature each time; summing it over intervals overpays U. network.forward at zero time with observed=True still conditions and writes content. True padding requires observed=False and valid=False.

**Required interpretation/action:** Use the continuation-value functions for once-only terminal payoff; retain the distinction between duplicate queries, repeated observations and padding.

**Evidence:** Earlier targeted native run: 9 tests passed; receipt linked below. Exact formatted final source is reserved for root revalidation.

**Sources:** `qualification/hcsn_differentiable/MODEL.md`, `qualification/hcsn_differentiable/tests/test_readout_semantics.py`.

### P1-01: Posterior gradient coverage must include the entire retained batch

The earlier first-posterior gradient cache could grant coverage to later unchecked posteriors. Current code compares every basis derivative via forward AD against 80-digit central differences, then all recorded posterior mixtures with those coefficients held fixed.

**Required interpretation/action:** This verifies derivatives of continuum basis continuation with fixed posterior coefficients, not derivatives through observation filtering or all learned training trajectories.

**Evidence:** independent source inspection and mathematical reasoning

**Sources:** `qualification/hcsn_differentiable/training_domain_audit.py`.

### P1-02: Trace budgets and source changes now fail closed

The prior record-count cap could exceed the 64 MiB reader budget. The current writer caps bytes, reserves a footer, records drop reasons and truncation, excludes supplied padding, and hashes source before/after. The auditor refuses complete coverage when records were dropped or sources changed.

**Required interpretation/action:** The caller must still bind capture calls to its optimizer ledger. Complete retained coverage is not proof that every training call was supplied.

**Evidence:** independent source inspection and mathematical reasoning

**Sources:** `qualification/hcsn_differentiable/training_domain.py`, `qualification/hcsn_differentiable/training_domain_audit.py`.

### P1-03: Log F/G preserves rare probabilities and nonpositive-time semantics

The two first-hit terms combine by logaddexp before exponentiation; nonpositive durations use a safe inactive computation and return log probability minus infinity with zero branch derivative. The discounted root uses a safe expression at zero drift.

**Required interpretation/action:** A finite log-risk helper does not change the network risk channel into log-risk; current risk remains an expected interval event count. The finite fixture collection does not certify an entire parameter box.

**Evidence:** Formula and branch inspection; fixture execution reported by numerical owner, not rerun in this review.

**Sources:** `qualification/hcsn_differentiable/operator.py`, `qualification/hcsn_differentiable/tests/test_logrisk.py`.

### P1-04: Repeated short-time QPR projection has a structural small-step error

For a uniform source cell of width h, a tiny Brownian step crosses one edge with probability approximately sigma*sqrt(dt)/(h*sqrt(2*pi)). Reconstructing a uniform cell after each step gives effective diffusivity of order sigma*h/(sqrt(2*pi)*sqrt(dt)), which does not approach sigma^2/2 at fixed h. Larger truncation endpoints reduce real tail occupancy but do not automatically fix all-basis or infinitely repeated tiny-gap error.

**Required interpretation/action:** Keep failed perpetual stress gates failed. A finite actual-schedule audit is a different, explicitly scoped qualification. Closed quadrature alone cannot remove projection error; silently subdividing gaps is not justified.

**Evidence:** independent source inspection and mathematical reasoning

**Sources:** `qualification/hcsn_differentiable/operator.py`, `qualification/hcsn_differentiable/training_domain_audit.py`.

### P1-05: Finite continuation reference handles regenerated counts and remaining age

For event index k, the reference uses first passage across x+k*x_reset with deadline T-k*d. Discounted event mass includes exp(-rho*k*d). The refractory occupation formula separates full and recent waits; remaining-phase integration truncates to r<=T, multiplies U/H by exp(-rho*r), and leaves count/active probability undiscounted. These expressions are consistent with the declared process.

**Required interpretation/action:** The helper currently constructs default rewards .4/1/.2 and reset=True. Its caller must bind the exact probability, grid, parameters and full durations and prove these settings match the audited model. Order doubling is a sensitivity measurement, not a certified quadrature bound. Errors scaled by max(1,abs(reference)) are absolute errors for probabilities below one, not relative rare-tail accuracy. No future observations are applied.

**Evidence:** independent source inspection and mathematical reasoning

**Sources:** `qualification/hcsn_differentiable/training_domain_finite.py`.

### P2-01: Event-time LIF needs stable periods and a declared count domain

The original tau*log(I/(I-1)) can round to zero at very large I and create infinite counts/NaNs. Current log1p formulas avoid that cancellation and reject event counts above one million. The geometric trace sums all within-interval crossings; local AD treats the integer event count as fixed, which is correct between count changes.

**Required interpretation/action:** Do not claim smooth derivatives at grazing events or event-count transitions. This is an analytic event-time reference, not a validated implementation of EventProp.

**Evidence:** Large-current failure independently identified earlier; all-six-input finite-difference checks reported passed by training owner.

**Sources:** `proposals/localization-v3/cores.py`, `proposals/localization-v3/test_cores.py`.

### P2-02: Changed source removes adequacy credit; recovery remains unsupported

Current finally logic sets status=source_changed and adequacy=False on hash changes. Partial checkpoints retain model/optimizer/RNG but not an exact mid-epoch cursor and ordering state sufficient for exact resume; resume_supported=False is now explicit.

**Required interpretation/action:** No exact recovery or P5 adoption credit should be inferred from the existence of interrupted.pt.

**Evidence:** independent source inspection and mathematical reasoning

**Sources:** `proposals/localization-v3/train.py`.

### P2-03: Tail padding no longer repeats HCSN observations

The current UCI model passes x[...,12:24].any(-1) as observed and valid masks for HCSN; these coordinates are the actual UCI observation-mask features. The recorder excludes those padded states.

**Required interpretation/action:** This heuristic is UCI-specific and cannot be used for the symbolic P4 21-to-25 adapter. New task drivers must supply explicit episode-length valid masks.

**Evidence:** independent source inspection and mathematical reasoning

**Sources:** `proposals/localization-v3/cores.py`, `qualification/hcsn_differentiable/training_domain.py`.

### P2-04: Plateau threshold and strict best-checkpoint selection differ

The running v1 used score > best + plateau_delta both for checkpoint selection and plateau reset. At .299 then .3005 with delta=.002, time-to-.3 is recorded while best.pt remains at .299. The current canonical v2 separates strict best score from plateau_anchor; the frozen running v1 remains unchanged.

**Required interpretation/action:** For v1, interpret first observed time-to-quality separately from selected checkpoint quality. Preserve the historical selection rule in every comparison; do not retrofit new-source credit to old results.

**Evidence:** Exact arithmetic counterexample plus source inspection; canonical fix reported by owner and observed in current source.

**Sources:** `proposals/localization-v3/train.py`.

### P2-05: Malformed fit evidence could abort the controller summary

In v1, log hashing and result.json parsing were outside the exception guard, so missing/corrupt fit output could make future.result abort the controller before RESULT.json. Raw commands and stdout/stderr would remain. Current canonical catches this as evidence_failed and retains the attempt.

**Required interpretation/action:** For the active v1 campaign, independently reconcile the complete 36-attempt roster and retain every failed/timeout attempt even if no final summary is produced. No occurrence of this failure was observed in this review.

**Evidence:** independent source inspection and mathematical reasoning

**Sources:** `proposals/localization-v3/campaign.py`.

### P2-06: Campaign costs include spawn/import and failed children, with explicit omissions

Dispatch-to-return wall includes process spawn/import and timeout work. RUSAGE_CHILDREN includes reaped failed children. Full-process RSS is measured; per-fit CPU starts later but campaign child CPU covers aggregate process CPU. Diagnostic updates and main updates are separate. No automatic retries are implemented.

**Required interpretation/action:** External host contention and concurrency prevent a clean hardware-efficiency comparison. Historical preparation/reservations and physical energy remain unknown, not zero. The actual locked plan uses default quality threshold .3, plateau delta .002 and one thread, per training-owner confirmation.

**Evidence:** independent source inspection and mathematical reasoning

**Sources:** `proposals/localization-v3/campaign.py`, `proposals/localization-v3/train.py`, `proposals/localization-v3/README.md`.

### P2-07: Shared frontend/head isolation and training sufficiency have limited meanings

Independent RNG streams produce identical frontend/head weights per seed and freeze them in the primary regime. Only cores train; their parameter counts, state capacities and output ranges differ. The declared adequacy rule is minimum epochs plus a development plateau and a successful training-only memorization diagnostic, with initial tensors and optimizer restored before the main fit.

**Required interpretation/action:** This is a reproducible stopping-rule pass, not a proof of statistical or optimization convergence. Report each core under the fixed interface; keep any jointly trained interface as a separate experiment. CPU FP64 causal attention does not establish optimized-GPU Transformer efficiency. Complete seven-arm scientific comparison remains on HOLD until HCSN numerical admission and the larger confirmation protocol.

**Evidence:** independent source inspection and mathematical reasoning

**Sources:** `proposals/localization-v3/cores.py`, `proposals/localization-v3/train.py`, `proposals/localization-v3/README.md`.

### P2-08: Temporal cores use different physical timing conventions

Event-time LIF holds the current observation over the preceding gap. HCSN propagates the prior over the gap and observes at the endpoint. PLIF and S4D remain event-indexed and receive elapsed time through the common input; CfC receives actual durations.

**Required interpretation/action:** These are candidate timing conventions, not direct label leakage for endpoint classification. Freeze and disclose them; a continuous-time physical equivalence or superiority claim requires a separately matched convention.

**Evidence:** independent source inspection and mathematical reasoning

**Sources:** `proposals/localization-v3/cores.py`.

### P3-01: The QVI oracle is not financial E or a trained task boundary

The finite reflecting birth/death model uses synthetic g(x)=x, cost=.6, delay=.2 and reset=1.37. Uniformized policy iteration and independent Bellman iteration solve that finite problem. Fixed threshold, fitted logistic policy and optimal finite action set are distinct groups. No financial equity expression or real sensor utility enters this objective.

**Required interpretation/action:** Only finite-fixture optimality and implementation consistency may be claimed. The fixture does not make E trainable or establish an effective neural free-boundary mechanism.

**Evidence:** independent source inspection and mathematical reasoning

**Sources:** `qualification/hcsn_qvi/oracle.py`, `qualification/hcsn_qvi/run_oracle.py`, `qualification/hcsn_qvi/README.md`.

### P3-02: Cost derivative applies to finite values under a fixed optimal active set

For A=I-K_pi and reward derivative -pi, dU/dcost=A^-1(-pi). This matches the code. The central-difference comparison is qualified only when both perturbations retain the active set. The threshold bracket is a discrete grid interval; no continuous boundary derivative is calculated. condition_inf is the fixed-policy linear-system condition number.

**Required interpretation/action:** Do not describe the result as an implicit continuous-boundary gradient, a boundary conditioning certificate, smooth pasting, or real-task benefit. Reflecting truncation and reset interpolation remain part of the finite problem.

**Evidence:** Independent equation review; prior exhaustive seven-state, DP comparison and active-set-crossing tests passed on the earlier receipt, pending root exact-source revalidation.

**Sources:** `qualification/hcsn_qvi/oracle.py`, `qualification/hcsn_qvi/run_oracle.py`.

### P4-01: Synthetic memory controls require a new training experiment

The symbolic suite has overwrite retrieval, delayed ordered copy and two-key composition. Clock and symbol streams are independent. Query values are absent; copy requests have no answer-revealing index. The 21-dimensional input is padded with four zeros to reuse a 25-input framework without changing information.

**Required interpretation/action:** Use a fresh common 25-input frontend and eight-class head, explicit valid masks and a separate synthetic driver/manifest. UCI-trained zero-shot failure is not mechanism counterevidence. Generator validation and exact symbolic answers grant no model-training credit; the generated extrapolation probe is not blinded confirmation.

**Evidence:** independent source inspection and mathematical reasoning

**Sources:** `qualification/hcsn_memory_controls/generate.py`, `qualification/hcsn_memory_controls/PROTOCOL.md`.

### P2-09: One completed GRU development fit reproduces exactly without gaining training-adequacy credit

For gru-s101-lr0.001, all 128 D episodes and 31,952 labels match their manifest hashes. A fresh best.pt forward pass exactly matches stored logits. NumPy metric recomputation matches all reported values. Initial/best/last shared frontend and head tensors are identical; all four GRU core tensors changed. The journal reconciles 360 main updates, 256 diagnostic updates and 30 completed epochs. Selected epoch is 16; development accuracy is 0.5117050575863795 and macro-F1 is 0.15827456447784624.

**Required interpretation/action:** The original fit reports development_plateau but training_adequacy_established=False. Independent reproducibility does not overrule its memorization gate, validate the other 35 fits, provide an E confirmation score or establish HCSN benefit.

**Evidence:** Actually executed independent reviewer script on the immutable run-source-v1; native receipt and exact local copy SHA256 78bfd675f333eb32e5530446e8c05429ccf244cf49941993a8cb570974806a92.

**Sources:** `proposals/localization-v3/cores.py`, `proposals/localization-v3/train.py`.

## Remaining gates

- Exact final source validation and overall CI are separate.
- True filtered-posterior law, full learned physical domain and all training calls remain unqualified.
- The failed perpetual tiny-step stress condition is not erased by an actual finite-schedule fixture.
- Complete fair trained seven-core comparison and independent confirmation remain pending.
- Real asynchronous multimodal task benefit, complete physical energy, scale and production adoption remain unestablished.

## Provenance

JSON: `hcsn-independent-review-20261110-v2.json`. Source hashes retain the original review snapshot; that capture is not atomic. Historical test receipts precede later formatting or source changes and are not silently transferred to current hashes. This update supersedes only the earlier unknown reproduction outcome; it preserves the original review as a separate file.
