# Checkpoint-own-law Bellman compilation: structural gain, head-edit failure

This is one frozen follow-up to `wsp_20261104`, using the same five archived renewal checkpoints. It does not read a live Trader checkpoint. The completed experiment supports **finite-task structural planning efficacy** and rejects **pure weight-edit efficacy**. The structural policy uses the checkpoint's own stored transition and observation model to plan all subsequent decisions. The direct-edit and matched gradient arms compile that policy's targets into the original 196 output parameters.

The protocol was frozen at `2026-11-05T00:34:40.591995+00:00` before new validation/test scoring. Its SHA256 is `735df99e3366a5d9343e1642a8c370b8d3359169bc70a98572476c6747a88251`. Full experiment records are in [execution_r1/run](execution_r1/run), and the primary outcome is [RESULTS.json](execution_r1/run/RESULTS.json). This is a local source/protocol freeze, not an external preregistration.

## Result and qualification

Five existing fits (11, 23, 37, 53, 71), each with 64 original TRAIN worlds, 16 new validation worlds per domain, and 32 new TEST worlds per domain, were retained. The unit for the primary paired intervals is a fit, not a world. Four primary comparisons use two-sided Student-t intervals with df=4 and Bonferroni familywise 95% coverage. Both domain lower bounds must exceed the prespecified utility threshold 0.005 for a category to qualify.

| Primary comparison against incumbent C | TEST mean utility gain | Familywise 95% interval | Gate |
|---|---:|---:|---|
| D after validation gating, IID | 0 | [0, 0] | Fail |
| D after validation gating, OOD | 0 | [0, 0] | Fail |
| J structural Bellman, IID | 0.1052767633 | [0.0477670749, 0.1627864517] | Pass |
| J structural Bellman, OOD | 0.2021614690 | [0.1203594012, 0.2839635367] | Pass |

All five direct-edit candidates D, all five matched-gradient candidates G, and all five random controls R failed the frozen validation gate. All were restored exactly to C. The independent verifier confirms the selected TEST utilities equal the corresponding restored C utilities. No rejected edit was promoted. J is a separately specified structural policy and was never labeled as a parameter edit.

The primary qualification is limited to expected utility in this finite task under the frozen evaluator. Production, actual packet execution, full economic net value, energy, and continuous whole-network global optimality remain unqualified. OOD describes the distribution relative to original TRAIN; its distribution was exposed during validation. TEST contains new instances, not a never-before-seen distribution. Only five fitted checkpoints support the fit-level interval.

## Task, information boundary, and mathematical program

The task has six ticks, initial budget three, and actions STOP, WAIT, READ, REPAIR, SUBMIT-0 and SUBMIT-1. A delayed read observes the latent sign when it completes; the prediction target is the sign at tick six. REPAIR repairs the sensor, not the latent first-passage/reset process. Fees, elapsed-time costs, legality, pending requests and completion semantics come from the pinned original task implementation.

`OwnTableLaw` uses the deployed checkpoint's stored transition tables, coordinates, prior construction, and TRAIN-fitted confusion matrix. It never reconstructs a nominal law from raw model parameters. An unknown duration/drive table entry fails. Preparation checks compare own-law posteriors with deployed bank[7] on 1,582 original TRAIN rows: maximum difference 2.220446049250313e-16; initial mass difference zero. The exact five published C coefficients are read from `OLD_CONTINUATION_HEADS.json.gz` and the complete reconstructed JSON identities are checked, rather than re-solving the previous edit.

For every original TRAIN world, the program enumerates every structurally lawful full state and every legal continuation. It preserves distinct sunk-charge feature states even when their future decision problem shares a Markov key. There are 144,397 full TRAIN states in total. The Markov key contains tick, budget, broken flag, pending request and completed observation history. Future value does not depend on costs already paid, so Bellman recursion uses this smaller key while the neural feature computation keeps the full state.

For a legal nonterminal action, the existing supplied-law Bellman recurrence is reused:

```text
Q(s,a) = sum_o p_own(o | s,a) * [max_legal_b Q(s'(s,a,o),b) - incremental_fee(s,a,o)]
```

STOP has value zero. The two submission values are `1 - 2 p_own` and `2 p_own - 1`. J executes these full continuation values and the own-law posterior. The planner receives the public schedule and completed history. Environment-truth transitions, true posteriors and evaluator Q values are absent from targets and policy inputs. Evaluation uses the separate frozen truth law. The targets are supervised by a program using the checkpoint's own model: this is program-teacher distillation, not unsupervised or data-free optimization.

The 85-input, 48-hidden-unit representation and all physical/observation parameters remain fixed for weight arms. The 147 continuation parameters and 49 belief-logit parameters form two separately constrained groups. Each minimizes a fixed weighted target MSE plus `1e-4 * ||theta - C||^2`, subject to `||theta - C|| <= 0.5 * ||C||` for that group, with a small fixed inward numerical radius. Continuation weights balance worlds, eligible states and legal continuation actions. Belief weights balance worlds and full states. Targets clip posterior probabilities only at `[1e-12, 1-1e-12]`; all clipping counts are retained.

D solves the convex block quadratic with eigendecomposition and one shared secular multiplier per group. G uses projected gradient descent on exactly the same objective, data, center, constraints and precision, with step `1/L`. Each method stops from its own numerical Frank-Wolfe gap at `1e-8`; G never receives D's optimum as a stopping target. All ten fit/group problems converge under both D and G, giving twenty converged solver results. Cholesky, KKT and original-data/Gram comparisons are numerical diagnostics; no outward-rounded proof of an exact continuous optimum is claimed. Exact rational arithmetic verifies the norm of the stored F64 parameter differences.

## Ablations and what failed

All values below are descriptive TEST means; only the four comparisons above are primary qualification gates. The complete paired descriptive intervals and per-fit values are retained in `RESULTS.json`.

| Arm | Meaning | IID utility | OOD utility |
|---|---|---:|---:|
| A | Original checkpoint | 0.224856086 | 0.108183409 |
| C | Exact published continuation incumbent | 0.237007222 | 0.110282802 |
| P | C continuation plus own analytic terminal posterior | 0.238325152 | 0.131892905 |
| J | Full own-law Bellman structural policy | **0.342283985** | **0.312444271** |
| D | Direct compilation of both groups | 0.188444332 | 0.062361353 |
| G | Matched projected-gradient compilation | 0.188446032 | 0.062791274 |
| DQ | Direct continuation edit alone | 0.190206919 | 0.061990823 |
| DB | Direct belief edit alone | 0.239730193 | 0.120802224 |
| R | One deterministic norm-matched random edit | 0.071049671 | 0.009910565 |
| D/G/R gated | All restore to C | 0.237007222 | 0.110282802 |

Mean own-law continuation target loss improves from 0.0238500229 for C to 0.0163374851 for D; belief-logit target loss improves from 0.0277612196 to 0.0193217276. G reaches almost the same objectives, within the common numerical stopping tolerance. Nevertheless D loses 0.0485628901 IID utility and 0.0479214490 OOD utility. The continuation-only ablation loses similarly. Belief-only and posterior-only effects are small and have descriptive fit-level intervals containing zero; they do not establish a separate repair qualification.

The retained behavior diagnostics show why lower average surrogate error is insufficient evidence of value: IID C requests 1.2842 reads and pays 0.136884 fees per world, while D requests 1.6764 and pays 0.162510. J requests 1.0232 and pays 0.100136. J's selected-Q error and decision regret are much smaller under the evaluator, but each arm visits its own state distribution; these error metrics are not same-state paired comparisons or a complete causal attribution. The evidence supports retaining the complete own-law planner and identifies failure of this particular fixed-feature, constrained head compilation. It does not prove that no possible head edit could work.

## Cost and resource accounting

The complete formal worker, including imports, startup and final writes, used **460.038810 CPU seconds**, **460.985993 wall seconds**, and **197,607,424 bytes peak RSS**. It exited zero under the frozen 900 CPU-second / 1,200 wall-second caps. The independently measured process receipt is [PROCESS_RECEIPT.json](execution_r1/PROCESS_RECEIPT.json); the internal summary timer ends before its own final write and is not substituted for this complete worker cost.

| Cost across five fits | D direct | G matched gradient |
|---|---:|---:|
| Solver stage, CPU seconds | 0.301806320 | 5.355101679 |
| Same target/features/Gram/eigen setup + own solve + own save/load, CPU seconds | 200.809890306 | 206.330770568 |

The solver-stage ratio is 17.74, but the inclusive construction ratio is only **1.02749** because target construction and feature evaluation dominate. The inclusive comparison charges the same common preparation to each method and excludes validation and whole-process startup. This is a comparison against matched output-head PGD, not full-network Adam/SGD retraining. No general training-cost advantage follows.

J cold preparation is separate from lookup. Across the 320 TEST worlds it costs **66.206353918 CPU seconds**, including compilation, residual auditing, serialization, loading and artifact binding. Mean cold cost is 0.206894856 seconds per world. Tables contain 123,080 total Markov states (148–782 per world) and 23,812,341 uncompressed row bytes. Instrumented warm policy calls do not establish native runtime throughput. Every arm/world starts with its own empty feature cache; truth-evaluator cache sharing means total evaluation CPU is not an inference benchmark. Existing simulated task fees do not price real CPU or energy, so economic net value remains unqualified.

Preparation is separately retained: two preparation checks use 3.157098624 and 3.434965710 CPU seconds; synthetic state counting uses 0.719326583 seconds. Public input recovery records 2.702490917 remote CPU seconds plus 0.184370975 local verification/extraction seconds. The independent record verifier uses 1.614201 CPU seconds. These known components are not a complete total of source retrieval, editing or exploratory shell work.

## Independent acceptance and provenance

[verify_records.py](verify_records.py) reconstructs stored-model identities, exact group norms, quadratic gradients, candidate-to-gate bindings, gate decisions, restoration utilities, qualification flags, all four primary intervals and schedule deduplication. Its df=4 Student-t critical value comes from the closed-form CDF, independently of SciPy's t routine. Maximum interval difference is 3.3306690738754696e-16; maximum Gram-gradient difference is 5.532672844171804e-14. It passed on its first execution. The [verification output](execution_r1/verification.stdout.log) and [process receipt](execution_r1/VERIFICATION_PROCESS_RECEIPT.json) bind its source and primary records. This verifier does **not** reexecute model features, Bellman calculations or trajectories; the complete frozen replay command below provides that separate check.

Content hashes establish zero duplicates against 1,936 available prior unique schedules and between all 480 new validation/TEST schedules. The available history does not contain the original formal-confirmation content or arbitrary unknown external runs. The latest separate digital-feedback confirmation, PR #4798 (`77b24407b9898aa44769502fbb22c24fb7193a58`), was read before the protocol: its 32-fit study has zero of four primary benefit passes and zero of 256 overall quality passes. Its exposed records are neither targets nor a new holdout here.

The old research and source files remain byte-identical. The package depends on sibling `../../wsp_20261104`, at research base `2d0120e208ed81515837a7530c9f6943af03e87f`. Original archive provenance is `5b69a046d886cf4c2a73c50e58197360ea15d8f5`, archive SHA256 `87173e7699117f9870393832f428b9f3e0046efe7f92035be7b37f5348ad9124`. The acquisition command validates all 3,550 archive members before writing the ten selected model/data files. No new private Trader data is included.

## Reproduce

Run these commands from this `ndu_policy` directory in a checkout containing the stacked old package. Python 3.12, NumPy and SciPy are required; the frozen STARTED receipt records Python 3.12.14 and NumPy 2.3.5. SciPy 1.17.0 was observed in the same environment after completion and is recorded separately in `RUNTIME_ENVIRONMENT.json`; its version was not captured by the frozen STARTED receipt. The bounded runner uses POSIX resource limits (Linux/macOS).

```bash
python ../../wsp_20261104/joint/acquire_inputs.py --output recovered_inputs
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 \
  python run_bounded.py \
    --joint ../../wsp_20261104/joint \
    --history ../../wsp_20261104 \
    --inputs recovered_inputs \
    --protocol PROTOCOL_FROZEN.json \
    --output independent_replay
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 \
  python verify_records.py independent_replay/run PROTOCOL_FROZEN.json \
    --history ../../wsp_20261104
python summarize_records.py independent_replay/run independent_replay/DERIVED_ANALYSIS.json
```

For offline input recovery, add `--repository /path/to/checkout` to `acquire_inputs.py`; the checkout must contain the pinned archive commit. Each output directory must be new. The runner fails and retains partial records on a source mismatch, duplicate schedule, numerical failure, state/row cap or runtime cap. No seed replacement or reduced-fit fallback is permitted. Timing fields need not reproduce exactly; source/data, candidates and task results are the relevant numerical replay targets.

To inspect the included evidence without scoring again:

```bash
python verify_records.py execution_r1/run PROTOCOL_FROZEN.json --history ../../wsp_20261104
```

## Next engineering boundary

`planning.compile_own` returns the full table artifact bound to canonical public-world and checkpoint hashes. `enumerate_states`, `ctx.outcomes` with that own-law object, and the pinned task successor supply a Markov DAG suitable for a Rust Bellman solver. Each reachable state has at most two nonterminal actions and at most four total nonterminal successor edges; each action has at most three outcomes. The 320 saved TEST worlds therefore have at most 492,320 edges. Full rows are regenerated deterministically from the saved worlds/checkpoint; this run stores their exact row hashes, sizes and residuals rather than duplicating every table.

A native port must compare every legal Q and selected action, retain the same terminal values and incremental costs, and repeat the already-exposed TEST trajectories. Such a migration check is engineering replay, not a fresh scientific holdout or a new efficacy qualification. No native-port evidence is mixed into this frozen experiment.
