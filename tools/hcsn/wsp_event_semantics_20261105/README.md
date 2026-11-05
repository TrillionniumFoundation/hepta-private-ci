# Actual-checkpoint event semantics: endpoint, first passage and reset

**The existing research bank predicts endpoint events. It is not a first-passage bank.** This package executes a new, fixed-input numerical diagnosis of that distinction on all five unchanged research checkpoints and all 320 original TRAIN schedules. It also tests what the existing `REPAIR` action changes. No model was trained, edited, selected, deployed or claimed to improve.

The main worker completed on **2026-11-05 at 05:18:07 UTC**. All source and input identities were frozen before its first execution. This is a reproducible diagnostic on already exposed TRAIN inputs, not a new held-out efficacy experiment or an external preregistration.

## What was actually executed

The five `joint-policy-v1` renewal checkpoints are fits 11, 23, 37, 53 and 71. Each contains 85 input coordinates, a 48-unit tanh representation, four affine outputs, three stored 33-by-33 CTMC generators and twelve stored transition matrices. The source explicitly declares `sign(X_deadline6)>0` as the task target, including early submissions. The original bank comprises three endpoint thresholds at three horizons. These are research artifacts from the predecessor `value_edit` package, not Pocket4's Laya/RowLoRA artifacts.

The diagnostics use the stored generators and transition matrices, not regenerated generators inferred from nominal metadata. Before any event calculation, all **60 generator/transition pairs** were compared. The largest absolute element difference was **2.4646951146678475e-14**, below the frozen 2e-10 threshold.

For each of the original 320 public schedules, the calculation starts from its exact stored-policy prior. It follows the scheduled drives and durations and reports horizons 1, 2 and 6. These are **320 initial-state predictions**, not a sweep over all reachable states. The number of independent new validation or test worlds is **zero**. No observation is added during this prediction, matching the original bank's no-new-observation semantics. A second computation uses a Poisson uniformization series, independently of the Padé matrix exponential. All **300 stochastic transition comparisons** passed; the maximum discrepancy was **1.63202784619898e-14**. The full scheduled propagation discrepancy was at most **2.5646151868841116e-14**.

These residuals qualify a numerical comparison under the specified finite CTMC. They are not outward-rounded certificates or a proof about a continuous-space diffusion.

## The endpoint bank and first passage are different targets

For threshold `K`, the frozen event convention is:

\[
\tau_K=\inf\{t\geq0:u(X_t)>K\}.
\]

Initial probability already above `K` is counted as a first-hit atom at time zero. At K=0, that initial event atom is 0.5 in every tested prior and is included in the reported 0.888023654 deadline first-hit probability. The coordinate comparison is strict. The original endpoint quantity is `Pr(u(X_T)>K)`. The first-hit quantity is `Pr(tau_K<=T)`. A path can cross the threshold and later return below it, so the first-hit event contains the endpoint event.

The following are descriptive means over the same 320 original TRAIN schedules. A tick denotes a schedule boundary; elapsed physical time varies with the supplied durations.

| Horizon | Threshold K | Original endpoint bank | First-hit probability | Difference |
|---|---:|---:|---:|---:|
| 1 | -0.5 | 0.790680413 | 0.908749302 | +0.118068889 |
| 1 | 0 | 0.482995199 | 0.646471042 | +0.163475843 |
| 1 | 0.5 | 0.184799368 | 0.294456380 | +0.109657012 |
| 2 | -0.5 | 0.784007123 | 0.943696261 | +0.159689138 |
| 2 | 0 | 0.488832656 | 0.723234422 | +0.234401766 |
| 2 | 0.5 | 0.201707432 | 0.376991582 | +0.175284150 |
| 6 | -0.5 | 0.777679748 | 0.988146536 | +0.210466788 |
| 6 | 0 | 0.495064646 | 0.888023654 | +0.392959008 |
| 6 | 0.5 | 0.218110168 | 0.577351939 | +0.359241771 |

All **2,880** comparisons differ by more than the frozen reporting threshold of 2e-8. This is not a failure of the endpoint predictor: it establishes that changing the name of an endpoint feature does not give it first-passage semantics. The largest individual deadline difference at K=0 is 0.581075253.

The original bank was independently reconstructed from the stored transition matrices and checked against the checkpoint's actual policy feature function. No caller-supplied substitute bank was used.

### Correct complements include the equality convention

For this finite grid, `Pr(X_T=K)` can be nonzero. Therefore:

\[
\Pr(X_T>K)+\Pr(X_T\leq K)=1,
\]

while `Pr(X_T>K)+Pr(X_T<K)` omits the mass at equality. At K=0 and horizon 6, mean equality mass is **0.0410237708**. The two strict inequalities therefore sum, on average, to **0.9589762292**, not one. The first-hit complement is the survival event `tau_K>T`; it is not a lower-threshold first-hit event.

The current neural terminal outputs are `SUBMIT_0 = 1-2p` and `SUBMIT_1 = 2p-1`, both derived from one Belief logit. Their sum is zero. This is a symmetric classification utility decoder, not two independent financial Call/Put tensor heads. A financial payoff, discount, strike, accounting or trade-authorization interpretation requires a separate contract.

## First outer-boundary causes have a third outcome: survival

The same stored generator supports a separate competing-event calculation. Its two reference-boundary states are made absorbing, leaving all pre-event rates unchanged. This gives the probabilities of the first lower hit, first upper hit and no outer hit by the deadline.

At horizon 6, the observed means are:

| Quantity | Mean over 320 TRAIN schedules |
|---|---:|
| First lower-boundary hit | 0.290284501 |
| First upper-boundary hit | 0.310792840 |
| No outer-boundary hit yet | 0.398922659 |
| Either first outer hit | 0.601077341 |

The three mutually exclusive outcomes sum to one within the numerical bound. The two hit causes alone do not. Repeated renewal after a first hit is excluded only in this first-event calculation; it remains present in the original dynamics below.

## Endogenous reset exists; the REPAIR action is a different effect

In the actual stored generator, an active state can enter either reference-boundary state. A recovery jump from that boundary back to the interior is an endogenous reset. Expected boundary-entry and reset-departure counts were computed two ways: a Van Loan augmented matrix exponential and the integral of the uniformization transition series. The largest discrepancy was **8.215650382226158e-15**.

At horizon 6:

| Quantity | Mean |
|---|---:|
| Expected boundary entries, including repeat entries | 0.683347661 |
| Probability of at least one boundary entry | 0.601077341 |
| Expected entries beyond the first | 0.082270320 |
| Expected reset departures | 0.440712400 |
| Probability currently at a reference boundary | 0.242635261 |

The entry-minus-departure count equals current boundary occupancy because the initial prior is interior. The excess-entry quantity is `E[(N_entries-1)_+]`; it is an expected count, **not** a probability of repeated resets. These are dynamic effects of the stored model and establish neither an observed physical device event nor a profitable trading signal.

For a separate controlled action check, each public schedule creates an actually reachable failed-read state by issuing the first legal READ and supplying its allowed failure outcome at the declared completion tick. From that same state, the runner compares WAIT and REPAIR, both advancing to the same next tick.

**All 320 comparisons have exactly equal latent mass and analytic bank arrays.** The only changed state fields are `broken` and `charges`, and the only changed shared feature indices are the sensor flag and, where nonzero, the fee coordinate. The continuation policy may react to these changes; the latent process has not received an explicit reset command. This rules out interpreting the existing REPAIR action as a commanded reset of the latent process.

## Mathematical construction and numerical limits

For each piecewise constant segment, the original prediction uses `P = exp(dt*Q)`. For a first-hit event set A, the stopped generator Q^A is Q with all rows in A set to zero. Propagating through `exp(dt*Q^A)` preserves the probability of already having hit A and cannot move it back to the surviving set. Initial mass in A is retained as a hit at time zero.

For the independent series, `lambda = max_i(-Q_ii)` and `R = I+Q/lambda`:

\[
P(t)=\sum_{k=0}^{\infty}e^{-\lambda t}\frac{(\lambda t)^k}{k!}R^k,
\qquad
\int_0^t P(s)ds=\frac1\lambda\sum_{k=0}^{\infty}\Pr\{\mathrm{Poisson}(\lambda t)>k\}R^k.
\]

Multiplying the integral by the nonnegative boundary-entry/reset-departure rate vectors gives expected jump counts. The series used at most 217 terms and a maximum retained-tail estimate of 9.283370182099324e-16. That is a truncation estimate only; it does not enclose floating-point arithmetic. The comparisons use the frozen finite tolerances and explicit checks, not a claim of exact real arithmetic.

A closed-form resettable two-state chain, a no-reset chain and the zero-time identity run before any actual-checkpoint calculation. Every original source/input is hashed before and after the run. No raw-parameter regeneration, labels from the evaluator, policy optimizer or hidden holdout enters the diagnostic.

## What the result changes for Weight-Space Programming

The validated generators can produce a first-event reference without retraining. This makes it practical to separate the following contracts before any agent changes a tensor:

1. **Endpoint target:** retain the current `sign(X_6)` task, endpoint bank and symmetric terminal utility. No first-passage repair is claimed merely because the underlying dynamics has boundaries and renewal.
2. **Stopped first-event target:** specify threshold inequality, initial-event atom, first-hit cause, horizon and censoring. If the episode terminates at the event, maintain surviving mass and absorbed cause mass explicitly.
3. **Renewal with historical events:** if observations continue after a hit/reset, maintain the joint distribution of current state and event-history flag, and any bounded count required by the task. The current normalized endpoint mass alone is generally insufficient to reconstruct the probability of never having crossed earlier. Future observations must update the joint state consistently.
4. **Commanded reset:** define a distinct action effect, reset distribution, cost, time and generation boundary if the task actually requires an agent-triggered reset. The current sensor repair action cannot be relabeled to supply this effect.

The corresponding model profile and patch request should bind the checkpoint identity to a target/event/reset contract digest and a verified tensor map. An unbound semantic name should fail admission. This diagnostic supplies a numerical reference for such a contract. It does not integrate a new task into the runtime, bind the Pocket4 Trader to these research tensors or demonstrate a useful weight edit.

## Relation to the earlier negative experiments

The predecessor already performed uniform optimal-Q head fitting, exact trust-region infeasibility checks for complete teacher copying, a terminal-anchored/occupancy-weighted head edit and an OOD failure decomposition. Its gated direct edit failed both primary improvement thresholds; the matched gradient endpoint did not turn that result into a qualified improvement. The present run does not repeat those fitting experiments and does not report their historical costs as new measurements.

The earlier source correctly distinguishes endpoint target semantics, terminal utility, Bellman structural policy controls and pure weight editing. The novel contribution here is the executed same-generator event comparison and the controlled REPAIR/WAIT effect check, not the discovery of a previously unreported successful repair or a new held-out result. The raw held-out examples used in earlier diagnosis remain exposed and cannot be used as fresh confirmation of a later repair.

## Costs and verification

| Phase | Complete child CPU seconds | Wall seconds | Peak child RSS bytes |
|---|---:|---:|---:|
| Input copy and protocol freeze | 0.066467 | 0.125601 | 11,403,264 |
| Actual diagnostic including controls and final writes | 2.059894 | 2.124860 | 59,842,560 |
| Independent record/aggregate verification | 0.121328 | 0.165085 | 19,378,176 |
| Sum of these three child phases | **2.247689** | **2.415545** | — |

The independent record checker verifies all source/input/result identities, all 320 world identities, 21,120 explicit partition identities/containment checks and independent summary arithmetic. It does **not** independently reexecute the CTMC algorithms; the separate expm/series and count-integral comparisons belong to the producer's declared numerical checks.

Nested worker timers are not added to the complete child times. Controller import/final-write work, editor inference, older training, power and production execution are excluded or unknown. The small diagnostic cost is not a measured saving from replacing gradient training.

## Reproduce and inspect

Run from this directory in a clean process with NumPy and SciPy:

```bash
python measure_process.py --output replay_receipt --timeout 190 -- python run_diagnostic.py --protocol PROTOCOL_FROZEN.json --output replay_receipt/run
python measure_process.py --output replay_check --timeout 30 -- python verify_diagnostic.py --run replay_receipt/run --output replay_check/VERIFIED.json
```

All writes are create-only. Existing output directories are rejected. A replay reproduces the same diagnostic input set; it does not create another independent efficacy experiment.

Start with `PROTOCOL_FROZEN.json`, `execution_r1/run/RESULTS.json`, the five compressed per-fit record files, the three `PROCESS_RECEIPT.json` records and `independent_record_check/VERIFIED.json`. The minimal original policy/task definitions and actual input models/schedules are retained under `vendor/` and `inputs/` for source-bound replay.
