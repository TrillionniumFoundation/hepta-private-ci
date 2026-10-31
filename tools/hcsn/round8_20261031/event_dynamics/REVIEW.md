# Independent review of the frozen state-task study

Reviewed files: `../state_task/data.py`, `models.py`, `train.py`, `evaluate.py`,
`protocol.json`, `test_task.py`, `FREEZE.json`, training records and train/dev
data. The reviewer did not run inference on confirmation data or modify the
frozen source/checkpoints. At the inspection, all manifest hashes matched,
12 model records existed, and none of the four confirmation NPZ files existed.

## Findings requiring a recorded response

### R1: confirmation seeds were used by a pre-freeze numerical test

`test_teacher_matches_stable_kernel` calls `make_data("low_noise", protocol)`
and `make_data("moving_boundary", protocol)`. Those calls use the registered
confirmation seeds 91003 and 91004 and generate their complete datasets before
checking 64 rows against the independent kernel. The root executor confirmed
that this test was run before `FREEZE.json` was written. It did not evaluate
model predictions, but it violates the literal rule that confirmation data
would first be generated after checkpoint/source freeze.

Required response: retain the original protocol, freeze and checkpoint bytes;
record this deviation. Before any confirmation prediction, register a separate
amendment using fresh independent seeds for all four regimes and commit that
amendment and its read-only generation/evaluation path. The root executor has
accepted this response and designated 191001--191004. This review does not
claim that the later remote commit or new evaluation has already completed.

The old samples may remain numerical audit fixtures. They must not be silently
relabelled as previously unseen confirmation observations.

### R2: structural equivalence and an empirical cost gate were conflated

`evaluate.py` hard-codes `analytic_state_irreplaceable=False`. The accompanying
constructive argument is valid for this task: a nonspiking two-accumulator
filter can compute the same posterior and risk. However, the protocol's
economic rejection rule additionally requires measured quality noninferiority
and no greater full execution cost. That conjunction is not computed by the
hard-coded verdict.

Required response: preserve the structural statement as a distinct mathematical
scope conclusion. A supplementary read-only analysis must calculate the actual
quality margins and cost/amortization conditions from frozen predictions and
measured costs. The root executor has accepted this separation. It must not
reinterpret a hard-coded structural label as an observed timing result.

### R3: complete-cost reporting needs additional aggregation

The frozen evaluator records model loading (except initial creation of the
fixed reference), total training CPU, fixture loading and batch/scalar predictor
timings. It does not yet calculate the registered amortization horizons
128/1000/10000/100000 or aggregate data/teacher generation, per-model training,
selection, serialization and any failed development into those totals.

Its predictor benchmark also calls `tensor_data(sample)`, which converts the
unused true probability target. That target is never passed into `forward`,
so this is not an information leak, but it is unnecessary deployment work and
should not be presented as a query-only serving path.

Required response: retain the old measurements with their true scope; add a
query-only timing path using history, lengths and query parameters, and a
transparent full-cost/amortization ledger without double-counting nested
timers. The root executor has accepted this response. The fixed reference's
construction/loading cost and shared costs should be explicit as well.

## Checks that support the intended limited conclusions

1. The observed increment contract is `dy=mu*dt+sensor_sd*sqrt(dt)*noise` with
   one latent mode per history and independently chosen positive intervals and
   sensor scales. The log likelihood depends on history through exactly
   `A=sum(dy/sensor_sd^2)` and `B=sum(dt/sensor_sd^2)`. The code's three-mode
   posterior is the correct sufficient-statistic posterior for this contract.
2. The future Brownian path begins after the sensor history. These observations
   are not a censored path known to have survived a barrier. The implementation
   therefore does not omit a needed survival likelihood under its stated task.
3. No model forward call receives `latent_mode_for_audit_only`, `posterior`,
   `teacher_components` or the target probability. The ordinary fixed filter
   recomputes its posterior from the same causal inputs and the same publicly
   known model constants used by the analytic filter. Its exact formula is a
   legitimate constructive reference, not an additional observation.
4. Analytic/fixed filters are model-informed algorithms; the unrestricted MLP
   and GRU must learn more of the mapping. Comparisons can quantify that chosen
   inductive bias under this known synthetic model. They cannot establish a
   generic advantage of spikes, model-free learning or a new universal memory
   architecture. The analytic filter here has no sampled spike/reset process.
5. Development MSE selects each checkpoint; training contains no confirmation
   prediction call. The inspected 12 records cover the four registered models
   and three seeds. Recorded training CPU totals 31.871366577 seconds, including
   the in-loop development checks and checkpoint serialization within that
   timer's scope. Train/dev arrays are finite and padded history entries are
   zero. Original checkpoint bytes match `FREEZE.json`.
6. Paired comparisons first calculate each frozen seed model's loss/regret and
   then average those per-episode quantities. They do not use an unpriced
   prediction ensemble to select actions. The bootstrap is descriptive over
   episodes conditional on these three trained models; it does not estimate
   population uncertainty over training seeds or justify broad claims across
   tasks. Individual seed results remain necessary.

## Review disposition

The task and sufficient-state calculation are coherent. The fixed ordinary
reference does not steal hidden information and is deliberately strong enough
to expose architectural equivalence. Confirmation should proceed only through
the recorded fresh-seed amendment, preserving the original deviation. Quality,
cost and the structural equivalence statement need separate reported outcomes.
This review is not a declaration of passed confirmation results.
