# CPU-budget exchange: reinvest saved proof-checking CPU in verified search

Research-only extension of PR #1546. No production policy, Encoder, Reader, NDU/FBSDE solver, Riccati module, or frozen heuristic changes.

## Rationale and limits

The opt-in exact-Fraction terminal prefilter avoids fully replaying a postfix expression when its trusted local rational value cannot equal the goal. It STILL invokes the unchanged independent verifier for any possible success. A prior microsecond CPU-deadline pilot produced extreme non-preemptive overshoots; it was rejected and never pushed. This experiment instead matches measured total CPU on an old calibration cohort, freezes a larger successor cap, then measures success and CPU on disjoint numeric questions.

The experiment uses fixed hash-ordered four-number multisets over integers 1..9, with the repository's existing digest identity:
- Calibration: catalogue positions 0:204, 204 previously exposed tasks.
- Development: 300:348, 48 multisets not used to choose the budget.
- Frozen-profile confirmation: 348:396, 48 more multisets, disjoint in original numbers but NOT necessarily in intermediate rational states.

Three source budgets are 256, 512, and 1024 successors. Candidate cap lists are predeclared:
- 256: 256, 320, 384, 448, 512
- 512: 512, 640, 768, 896, 1024
- 1024: 1024, 1280, 1536, 1792, 2048

For each original budget, execute 3 counterbalanced calibration repetitions on the old 204 questions. Select only by median aggregate process CPU: choose the largest prefilter cap whose calibration total CPU does not exceed the reference. Proof existence and outcomes are NOT used for that decision; a dedicated test flips all fake success labels without changing the selection. Save the selection before any evaluation. Run five counterbalanced repetitions on the next 48 questions, retaining raw proofs, costs, failures and prediction seals. The subsequent confirmation fixes 512 -> 1024 irrespective of any evaluation outcomes.

## Observed LOCAL evidence, not an independent hosted result

The local exact-source CPU PyTorch 2.10.0 execution selected the same 2x caps in two development reruns. On 48 different questions in positions 300:348:

| Reference -> optimized cap | Verified proofs | Measured total CPU ratio |
|---|---:|---:|
| 256 -> 512 | 27 -> 34 (+7) | ~0.999 first run; ~1.028 second median |
| 512 -> 1024 | 34 -> 38 (+4) | ~0.86 second run |
| 1024 -> 2048 | 38 -> 38 (no gain) | ~0.74 second run |

No reference proof was lost. However, the strict *whole-matrix* check fails because one 256-cap repetition exceeded the registered 5% total-CPU tolerance. Disposition: stop_no_stable_aggregate_cpu_gain. Do not silently replace this with the favorable first-run median.

A subsequent separate frozen 512 -> 1024 confirmation on positions 348:396 completed 480/480 predictions: direct 22/48 versus prefilter 29/48, seven additional independently verified proofs and zero original losses in each of five repeats. Measured new/old CPU ratios ranged 0.856–0.980 per repeat. Disposition: independent_natural_domain_required, NOT production_accepted.

These repeated runs represent 48 different tasks in each cohort, NOT hundreds of independent test samples. All tasks belong to the same synthetic arithmetic family, and intermediate states may overlap. No natural-language, multimodal, independent reviewer or reader adequacy outcome follows.

## Accounting, failure safety, and promotion rules

- CPU via process_time_ns is measured around search construction and execution, including the internal verifier. A second external proof check is outside the measured window and is never presented as paid model inference.
- Input generators, frozen heuristic and exact proof verifier are identical. A previously found proof MUST remain identical at the same successor count after prefiltering and extending the cap. Missing proofs fail the test, not the denominator.
- Calibration policy selection reads CPU totals only; never success labels. The source-cohort split, caps and confirmation profile were fixed before their corresponding outcomes.
- Every planned invocation journals its start and its final result. Exceptions retain partial rows and unknown work; hardware failures cannot be guaranteed safe by fsync.
- Whole-matrix admission requires zero lost proofs, improved proof count at some cap, and for EVERY budget and EVERY evaluation repeat optimized total CPU no more than 105% of reference.
- Frozen 512-profile confirmation additionally requires zero lost proofs, at least one new proof and every repeated 48-task aggregate CPU ratio <=1.05.
- No true hard CPU deadline, exact FLOP equivalence, statistically independent language benchmark or general NDU/FBSDE reasoning claim is made.

## Reproduction

From an exact Git checkout set HEPTA_MEMORY_TESTED_COMMIT to git rev-parse HEAD. Run the scripts under scripts/memory_cell named system2_cpu_exchange.py and system2_cpu_confirmation.py, each with a new output-directory argument, then the full MemoryCell Python test discovery. The existing research workflow runs them after all inherited regression, static, numerical and canonical-result gates and uploads sealed raw evidence.

This is resource-allocation engineering research. Meaningful Neuron Cell/NDU advancement still requires budget-matched language/compositional tasks, verified multi-step evidence sufficiency, independent answer judgments and explicit incremental utility versus a strong frozen Reader.
